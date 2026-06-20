# AI Job Application Portal — Handoff Doc

> **Purpose of this file:** Single source of truth + handoff for the project. If a new
> terminal / fresh Claude CLI session opens, READ THIS FIRST to know what we're building,
> what's decided, what's been done, and what's next. Keep it updated as we go.
>
> **Last updated:** 2026-06-07 (see Section 12 for the latest session's work)

---

## 1. What we are building (the goal)

An **AI-powered job-application portal** that, for each candidate, automatically:
1. Takes their **resume + email access**.
2. **Scrapes 50–100 active, matching US job links per day** (single-page application boards).
3. **Stores** them well (DB + Excel/Notepad).
4. Goes to each link, **intelligently answers whatever questions that form asks** (from the
   resume + extra profile data: visa status, experience, salary, etc.) and **submits**.
5. Repeats **daily**, for **multiple candidates**.

Example candidates discussed:
- DevOps Engineer, 8 yrs (later: 6–8 yrs band)
- Full Stack Developer, 4–8 yrs

The whole thing should be automated, with a **human review step first**, then flip to
**fully automatic** per candidate once trusted.

---

## 2. Key decisions made (locked)

| Decision | Choice |
|---|---|
| **Where it runs** | User's own Windows machine (for now). Move to a cheap always-on VPS when scaling. |
| **Target job boards** | **Greenhouse + Ashby + Workable** (API-friendly). NOT LinkedIn/Indeed auto-apply (ban risk). |
| **Submit mode** | **Review-then-submit first**, flip to **auto-submit** per-candidate once accuracy is proven. |
| **The AI brain** | Claude **API** (key from console.anthropic.com) — needed because the live app must call Claude automatically 24/7. This interactive Claude CLI = the *builder*; the API = the *runtime brain*. |
| **Tech stack** | Python · FastAPI · SQLite→Postgres · Claude API · httpx (ATS APIs) · Playwright (browser fallback only) · APScheduler (daily run). |

---

## 3. THE BIG TECHNICAL DISCOVERY (our advantage)

**Greenhouse has a fully PUBLIC Job Board API** — no scraping, no browser, no CAPTCHA needed
to *find jobs* and *read their application forms*:

- **List all live jobs:** `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs`
  (public, no auth, no rate limit, only returns ACTIVE jobs → freshness is automatic).
- **Get full job + exact questions:** `GET .../jobs/{job_id}?questions=true`
  → returns every field: label, type, required?, dropdown options, and the **submission field
  name** (e.g. `question_17726081004`) + **option IDs** (e.g. Yes=1 / No=0).
- **Get description for filtering:** `.../jobs/{job_id}?content=true`.

**Submission caveat (be honest):** the *documented* POST submit endpoint needs the company's
private key (we don't have it). So we SUBMIT via either:
  1. **Playwright browser-fill** (reliable default) — but because the API already gave us every
     field name/type/option, this is *deterministic* ("put known value in known field"), not
     fragile DOM-guessing. Much more robust than other projects.
  2. **Replicate the public form POST** (faster, ToS-sensitive, board-dependent) — optimization,
     with #1 as guaranteed fallback.

Ashby & Workable have similar public board APIs → same technique extends coverage.

---

## 4. Architecture — 7 modules

```
                         ┌─────────────────────────────────────────┐
                         │            DASHBOARD (FastAPI)            │
                         │  candidates · review queue · auto toggle  │
                         └─────────────────────────────────────────┘
   M1 INGEST      M2 DISCOVER+SCORE      M3 STORE        M4 ANSWER ENGINE      M5 SUBMIT
 ┌──────────┐   ┌──────────────────┐   ┌─────────┐   ┌──────────────────┐   ┌──────────────┐
 │resume→   │   │ Greenhouse API   │   │SQLite/  │   │ L1 deterministic │   │ API submit   │
 │profile   │──▶│ Ashby API        │──▶│Postgres │──▶│ L2 answer cache  │──▶│  (preferred) │
 │JSON      │   │ Workable API     │   │ +Excel  │   │ L3 Claude reason │   │ Playwright   │
 │+resume_  │   │ AI fit score 1-10│   │ status  │   │ +tailor resume   │   │  (fallback)  │
 │facts lock│   │ (parallel agents)│   │ pipeline│   │ +confidence flag │   │ review→auto  │
 └──────────┘   └──────────────────┘   └─────────┘   └──────────────────┘   └──────────────┘
                                                                                    │
                                                              M6 EMAIL (Gmail OAuth) ┘
                                                          confirmations · OTPs · replies
```

- **M1 Ingest:** resume (PDF/DOCX) → structured profile JSON via Claude API. Captures EXTRA
  fields not on resume: visa/work-auth, requires_sponsorship, salary, locations, EEO prefs.
  `resume_facts` block freezes companies/metrics exactly (anti-hallucination).
- **M2 Discover + Score:** sweep board seed list via API, filter title/location/experience,
  AI relevance score (1–10), detect **knockout questions** (e.g. onsite + non-commutable → skip).
- **M3 Store:** one row per (candidate × job). Status pipeline:
  `found → matched → queued → filling → needs_review → approved → submitted → confirmed`
  (+ `failed / captcha / skipped`). Export to Excel/Sheet.
- **M4 Answer Engine (the heart):** 3 layers —
  - **L1 deterministic:** visa, sponsorship, work-auth, years-exp, salary → straight from
    profile. **AI is NOT allowed to guess these.**
  - **L2 cache:** recurring questions ("How did you hear about us?") answered instantly from
    memory; gets cheaper/more consistent over time.
  - **L3 Claude reasoning:** only NEW / free-text questions hit the API, tailored to that JD.
  - Output = answer sheet keyed by real field names + a confidence flag (`auto_ok` / `needs_human`).
- **M5 Submit:** API-path preferred, Playwright fallback. Review-then-submit → auto-submit.
  CAPTCHA → route to human (see §6).
- **M6 Email:** Gmail OAuth (never store password). Watch confirmations, OTP/verification links,
  recruiter replies.
- **M7 Dashboard:** add candidates, review queue with screenshots, status counts, per-candidate
  auto-submit toggle.

---

## 5. How we handle "every job has different questions" (M4 explained)

We do NOT pre-program answers. For every form:
1. **Read the form as data** (Greenhouse API gives fields/types/options/field-names directly).
2. **Hand questions + profile + JD to Claude** → it answers each field from the candidate data.
3. **Safety:** hard facts (visa/sponsorship/auth/years/salary) come straight from profile, not AI.
   Low-confidence / sensitive → `needs_review`. EEO → candidate's stated preference.
4. **Cache** recurring question patterns per candidate (L2).

A brand-new question is no different from a familiar one — the AI reads whatever is actually
on the page and answers from the profile.

---

## 6. CAPTCHA strategy (3-tier)

User has built a **custom CNN text-CAPTCHA solver** (98.6% acc) for the Telangana Bhubharati
land portal — location: `E:\Koushik_Practice\bhubharathi\` (model: `data/captcha_model_98.6.pt`).
Solid: ResNet-style CNN, 5 per-char heads (36 classes), HSV de-noise preprocessing, mixup,
TTA, confidence gate, self-collecting retrain loop.

**Important:** it solves **5-char TEXT captchas** only. Job boards use **reCAPTCHA / hCaptcha /
Turnstile** (behavioral) — a CNN can't crack those. So:
1. **AVOID (primary):** API-first on Greenhouse/Ashby/Workable → no CAPTCHA at all.
2. **REUSE the CNN:** only if we add a board with classic text CAPTCHAs (the solver code is
   already a reusable `solve()` module).
3. **HUMAN fallback:** reCAPTCHA/hCaptcha → route that one job to dashboard for a 2-sec click.
   (Paid CapSolver optional, but human routing is cheaper/lower-risk.)

Reusable from the Bhubharati project: Selenium session handling, retries, resume logic in
`extract_bulk.py` → useful for M5 browser-fallback path.

---

## 7. Reference projects analysed (what to steal)

| Project | Take this idea |
|---|---|
| **santifer/career-ops** (Claude Code, GH/Ashby/Lever) | reasoning-based fit scoring + parallel sub-agents + reusable STAR/essay stories |
| **eliornl/applypilot** (FastAPI+Postgres+LangGraph) | AI-mapping + deterministic rules for fields; multi-user w/ encrypted keys; dashboard |
| **neonwatty/job-apply-plugin** | hard-gate sensitive questions (visa/salary) — confirm, never AI-guess |
| **wodsuz/EasyApplyJobsBot** | persistent answer cache (reuse answers across jobs) |
| **Pickle-Pixel/ApplyPilot** | full 6-stage autonomous pipeline shape + `resume_facts` anti-hallucination lock |
| applypilot.app (SaaS) | UI/pricing reference only (NOT an auto-applier) |

**Lesson from all:** avoid LinkedIn/Indeed auto-apply (every browser-on-hostile-board project
warns of bans). Quality+targeting beats spray-and-pray (career-ops did ~100 tailored apps and
the creator got hired; Pickle's "1000 jobs" risks spam-flagging candidates).

**Our differentiators:** API-first (ban-resistant) · true multi-candidate · 3-layer answer
engine · confidence-gated auto-submit · email loop. No existing project combines all of these.

---

## 8. WHAT'S BEEN DONE (working code in this folder)

- **`scrape_jobs.py`** — WORKING. Sweeps ~214 Greenhouse board tokens (parallel, 16 at a time),
  filters US + Full Stack / DevOps + seniority, writes two files. Runs in **~10 seconds**.
- **`FullStack_Developer_Jobs.txt`** — 60 active US Full Stack links (4–8 yr target).
- **`DevOps_Engineer_Jobs.txt`** — 50 active US DevOps links (6–8 yr target).

**Proven live during the session:**
- Parsed 2 real Greenhouse links → pulled their exact application questions via API
  (Nav `navtechnologies/5985843004` = 12 fields incl. visa/sponsorship/salary;
   Kunai `kunai/5101473007` = 11 fields, flagged as ONSITE-NYC knockout).
- Got submission-level field names + option IDs for Nav job.
- Swept 92 live boards (~3,000 jobs) → 60 FS + 50 DevOps links in <10s.

**Known caveats on current lists:**
- Title-level filtering is approximate — a few "Staff+/Engineering Manager" (>8 yr) slipped in.
  Precise 4–8 / 6–8 yr filtering needs the L3 JD-reading step (not yet added).
- A few links are on custom company domains (brex.com/careers, alloy.com) but are
  Greenhouse-backed (`gh_jid=`) and applyable.

---

## 9. NEXT STEPS (suggested build order)

1. **[next]** Add **JD-reading L3 filter** so lists are EXACTLY 4–8 / 6–8 yrs; regenerate clean files.
2. Build **M1 resume → profile JSON** parser (Claude API). Fast, fully testable.
3. Build **M3 storage** (SQLite + Excel export) with the status pipeline.
4. Expand **M2** into a proper module: bigger board seed list (target ~300–500 tokens) + Ashby/Workable.
5. Build **M4 answer engine** (L1/L2/L3) + **M5 submit** for ONE job end-to-end, review-then-submit.
6. **M7 dashboard**, then **M6 email**, then scale to multi-candidate + auto-submit.

**Before going LIVE (not needed to build):** a **Claude API key** from console.anthropic.com.

---

## 10. Open questions / things to confirm with user

- Exact required fields for the candidate profile (esp. visa/work-auth wording).
- How to handle the work-authorization nuance for visa holders (e.g. H-1B "authorized to work
  for our Company?" → often needs human review).
- Volume cap per candidate per day (to avoid spam-flagging).
- Whether to add Ashby/Workable now or after Greenhouse is solid.

---

## 11. Useful commands / snippets

```bash
# List a board's live jobs
curl -s "https://boards-api.greenhouse.io/v1/boards/databricks/jobs?content=false"

# Get one job's application questions (field names + option IDs)
curl -s "https://boards-api.greenhouse.io/v1/boards/navtechnologies/jobs/5985843004?questions=true"

# Run the daily scraper (writes the two .txt files)
cd "D:\Pallavi_New_Hackathon_Apr_2026\New_Project" && python scrape_jobs.py
```

URL → (board, job_id) parsing handles all forms:
- `/embed/job_app?for=BOARD&token=JOBID`
- `/BOARD/jobs/JOBID`
- custom domain with `?gh_jid=JOBID`

---

## 12. SESSION UPDATE — 2026-06-07 (major progress)

### 12a. BIG BOARD POOL acquired (15,533 boards)
Pulled public token lists from the repo **Feashliaa/job-board-aggregator** (CC BY-NC 4.0 —
NON-commercial; build our own list before commercial use). Saved under `seed/`:
- `seed/greenhouse_companies.json` — **8,180** tokens
- `seed/lever_companies.json` — **4,368** tokens
- `seed/ashby_companies.json` — **2,985** tokens
- Total = **15,533 company boards** (vs the ~180 hand-listed before).
`All_Job_Boards_List.txt` = human-readable list of all 15,533 names.

### 12b. Reusable fetcher module: `ats_fetch.py`
- Auto-loads the big `seed/` lists (falls back to small built-in list if absent).
- `fetch_all(content=True/False, limit, progress_every)`; `_TIMEOUT` global (set 6s for fast
  skip of dead/throttled boards); `clean()` + `min_years()` helpers.
- Fetchers: `_gh` (Greenhouse, content toggle), `_lever`, `_ashby`.

### 12c. KEY FINDINGS (important constraints learned)
1. **Rate-limiting:** sweeping all ~15.5k boards rapidly → Greenhouse throttles (HTTP 429)
   after ~4–8k fast requests (job count freezes). Fix for production: **live-token cache**
   (sweep once, keep only tokens that have jobs), gentle pacing, retry-on-429, lean on
   Lever/Ashby (they don't throttle us).
2. **content=False breaks year-matching:** without job descriptions, Greenhouse jobs have no
   text to parse "0-1 / 4-8 yrs", so fresher/experience detection must fall back to TITLE
   signals. Use content=True when years matter (slower); content=False only for title-based.
3. **Niche queries need the big pool:** strict Front-End + React + 2-4yr + remote = ~25 from
   180 boards; broad/common queries (AI, full-stack) easily hit 50–250.
4. **Title filtering must use word boundaries + a blocklist** — "react" matched "reaction",
   "node" matched "lymph nodes"; broad "graduate/associate engineer" caught civil/medical/sales.
   Fixed in `scrape_likhitha.py` (software-only, title-regex + BLOCK list).

### 12d. JOB-LINK FILES generated this session
| File | Spec | Count |
|---|---|---|
| `FullStack_Developer_Jobs.txt` | Full Stack, 4–8yr, US | 60 |
| `DevOps_Engineer_Jobs.txt` | DevOps, 6–8yr, US | 50 |
| `AI_Developer_Jobs.txt` | AI/ML/LLM, 6–8yr, any loc | 259 |
| `FrontEnd_React_Jobs.txt` | React/Front-End, 4–8yr, any loc | 261 |
| `FullStack_Fresher_USA_Jobs.txt` | Full Stack, 0–1yr, US | 4 (degraded light-mode) |
| `FullStack_Fresher_India_Jobs.txt` | Full Stack, 0–1yr, India | 0 (see 12f) |
| `Likhitha_Matching_USA_Jobs.txt` | **per-resume match** (see 12e) | **242** |

### 12e. FIRST REAL CANDIDATE: Likhitha Chinthirala
- Resume: `Likhitha_Chinthirala_page1_only.pdf`. Profile = CS 2026 grad (fresher 0-1yr),
  MERN (React/Node), Python/Java, + AI/ML (CNN, NLP). Open to any US location.
- `scrape_likhitha.py` (software-only, strict title filter, resume checkpoint, incremental save)
  → **242 live software jobs** across all 15,533 boards in ~34 min.
- Analysis: 152 general SWE / 38 AI-ML-Data / 21 Full-Stack / 12 QA-SDET / 10 Backend / 5 Frontend.
  All fresher (0-1yr). 73 remote. ~1 non-US leak (Santo Domingo). Top cos: Speechify, Twitch,
  Veeva, PlayStation, Deepgram, Nuro, Unity.
- Checkpoint at `likhitha_checkpoint.json` (scanned tokens + matches) → re-running RESUMES.
- TODO offered: re-rank into tiers (Tier1 Full-Stack/Frontend/React → Tier2 SWE → Tier3 AI/ML),
  drop the non-US leak.

### 12f. INDIA sourcing = needs aggregator (Adzuna) — PENDING USER KEY
- India fresher jobs aren't on Greenhouse/Lever/Ashby (US-centric) → got 0.
- `adzuna_jobs.py` is READY. User must get a FREE key at developer.adzuna.com and save it as
  `adzuna_key.txt` (format `app_id:app_key`). Then run → fills India (+ bonus US) file.

### 12g. PLATFORM REFERENCE DOCS
- `JobPortals_and_ATS_List.md` + `.txt` — ~84 notable platforms categorized (8 public-API ATS,
  enterprise ATS, SME ATS, job boards, remote boards, India portals, aggregator APIs) with
  🟢/🟡/🔴 automation tags + box-format summary table.
- **Big find: Fantastic.jobs** — one keyed meta-API indexing **54 ATS / 175k+ sites**. Worth
  evaluating instead of maintaining our own 15k-token list for production.

### 12h. CAPTCHA cascade (decided)
Avoid (API-first, no CAPTCHA) → anti-detection browser (stealth + residential IP so reCAPTCHA v3
/ Turnstile never challenge) → keyed solving service (CapSolver/2Captcha for visible puzzles) →
human-in-the-loop fallback. User's own CNN solves only 5-char TEXT captchas (not job boards).

### 12i. UPDATED NEXT STEPS
1. (optional) Re-rank Likhitha's file into tiers + drop non-US leak.
2. India: get Adzuna key → run `adzuna_jobs.py`.
3. Build **M1 resume→profile JSON** (Claude API) — the proper version of what we did by hand for Likhitha.
4. Build **M3 storage** (SQLite + Excel) with status pipeline + **live-token cache** (fixes rate-limit).
5. Build **M4 answer engine** + **M5 submit** for ONE Greenhouse job end-to-end (review→auto).
6. **M7 dashboard** (see Section 13 below for full feature set), then **M6 email**, then multi-candidate + auto-submit.
7. Evaluate **Fantastic.jobs** API as the production discovery source.

### 12j. MEMORY PREFERENCE (important)
User does NOT want any `.claude` memory entries for this project. Keep EVERYTHING in this
handoff doc only. (Memory files were created earlier and deleted at user's request.)

---

## 13. PORTAL / DASHBOARD FEATURE SET (discussed — for M7 build)

Login-protected web app (FastAPI + Postgres + web UI; JWT auth; runs local first, then VPS).
Roles: **Admin/operator**, **Candidate** (own view), optional **Team member**.

Screens:
1. **Dashboard** — live counters (found/applied/review/confirmed/failed), live activity feed,
   charts, bot status (running/paused, next run), alerts.
2. **Candidates** — list + add (upload resume → auto-profile + connect email), per-candidate
   profile (editable, fix visa/work-auth), controls (pause, daily cap, review↔auto toggle, boards).
3. **Jobs** — today's scraped jobs + match score + status; why-this-job reasoning; manual force/skip/blacklist.
4. **Review Queue** ⭐ — filled form + AI answers side-by-side, screenshot, flagged fields,
   Approve/Edit/Reject/Skip, batch-approve.
5. **Applications** — full CRM tracker; status pipeline; email-linked updates; notes/tags; export; funnel view.
6. **Analytics** — apps/day, response & interview rate, best titles/companies/boards, API cost.
7. **Settings** — API keys (encrypted), board seed list, schedule, notifications, templates, users.

Extras: notifications (email/Slack/Telegram), bot control bar (pause/run-now), per-job tailored
resume/cover-letter preview, email inbox view, interview/calendar tracker, answer-library (L2 cache)
editor, knockout-rules editor, company blacklist/whitelist, candidate self-service portal, audit log,
resume versions, in-portal AI assistant, daily/weekly report.

---

## 14. AI MODEL COST & STRATEGY (verified June 2026)

**Workload assumption** (ATS score + tailor, per resume/job): ~3,500 input + ~2,000 output tokens.
**Note:** output costs 5x input on Claude, so OUTPUT LENGTH is the main cost driver. Keep tailored
output tight.

### Pricing per million tokens (input / output)
| Model | Input | Output | Tier |
|---|---|---|---|
| Claude Opus 4.8 | $5.00 | $25.00 | top quality |
| Claude Sonnet 4.6 | $3.00 | $15.00 | balanced (best value) |
| Claude Haiku 4.5 | $1.00 | $5.00 | cheap/fast |
| GPT-5.4 | $2.50 | $15.00 | top quality |
| Gemini 2.5 Flash | $0.30 | $2.50 | cheap/fast |
| Gemini 3.1 Flash-Lite | $0.10 | $0.40 | cheapest proprietary |
| DeepSeek V3 | $0.27 | $1.10 | cheap (PII/China-host risk) |
| Llama 4 Maverick (hosted) | $0.15 | $0.60 | cheap open model |

Discounts (all Claude tiers): **prompt caching -90% on cached input**, **batch API -50%**.
1M context = flat rate, no surcharge.

### Cost for the SAME ATS+tailor job
| Model | Per resume | /candidate/day (50 jobs) | /candidate/month (~1,100 jobs) |
|---|---|---|---|
| Opus 4.8 | $0.068 | $3.38 | ~$74 |
| Sonnet 4.6 | $0.041 | $2.03 | ~$45 |
| Haiku 4.5 | $0.0135 | $0.68 | ~$15 |
| Gemini 2.5 Flash | $0.0061 | $0.30 | ~$6.65 |
| Gemini Flash-Lite | $0.0012 | $0.06 | ~$1.27 |
Opus is ~55x the cheapest option for the same task. Sonnet ~40% cheaper than Opus; Haiku ~80% cheaper.

### STRATEGY = tier the models (don't pick one)
- **Scoring / keyword-gap / form-field mapping** (judgment+extraction) -> **Haiku 4.5** or **Gemini Flash** (cheap).
- **Resume tailoring + free-text screening answers** (quality writing) -> **Sonnet 4.6** default, **Opus 4.8** premium tier only.
- Add **prompt caching** (cache candidate resume + ATS rubric across the day's 50-100 jobs) + **batch API**.

**Blended (Haiku scoring + Sonnet tailoring + caching + batch) ≈ $0.02/job ≈ ~$22/candidate/month**
— a ~70% cut vs pure Opus, with almost no quality loss.

### PRIVACY rule (resumes = PII)
Stay on **Claude / OpenAI / Gemini** (enterprise terms, no training on API data, US/EU hosting).
**Avoid DeepSeek** default (China-hosted) and be careful with open-model hosts for real candidate
PII — the few dollars saved aren't worth the compliance risk.

### DECISION for our build
- Default: **Haiku 4.5 (scoring) + Sonnet 4.6 (tailoring/answers)** + caching + batch.
- Premium tier: swap tailoring to **Opus 4.8** for top candidates.
- API cost is NOT the bottleneck (~$22/candidate/month) — output length + quality are what to tune.

---

## 15. COMPETITOR INSIGHT + VISA-SPONSORSHIP LAYER (for M2)

### 15a. Jobright.ai vs MigrateMate (for Indian students in US)
| | Jobright.ai | MigrateMate |
|---|---|---|
| Type | AI job copilot + **auto-apply (autofill ext)** | **Visa-sponsorship-first** job platform |
| Volume | ~400K postings/day scanned | 500K+ verified sponsorship jobs |
| Sponsorship data | H-1B filter = companies with *history* (coarser) | **LCA/USCIS govt data** — actual sponsor counts; OPT/CPT vs H-1B split |
| Auto-apply | ✅ autofill Chrome ext (100K+ users) | ❌ (gives hiring-manager contacts instead) |
| Extras | AI resume, Orion copilot, referrals | visa guides, employer verification, contacts |
| Price | Free tier; Turbo **$39.99/mo** | 30-day trial then **$29/mo** |
| Reviews | Trustpilot 4.8 (1,708) | 4.4 (40+), Forbes 30U30 |

**Verdict:** MigrateMate = better *targeting* (visa-accurate, cheaper); Jobright = better *applying*
(volume + autofill). Best = use both. **Our portal can do BOTH** (sponsorship-accurate matching +
true auto-apply) — neither competitor does both.
Free bonus data source: Jobright's GitHub repo **jobright-ai/Daily-H1B-Jobs-In-Tech**.

### 15b. HOW MigrateMate works (replicate this as M2 "sponsorship layer")
5 layers:
1. **Job aggregation** — 500K+ US postings from boards/ATS/aggregators.
2. **Sponsorship data (the moat)** — built from FREE US government datasets:
   - **DOL OFLC LCA Disclosure Data** — every H-1B requires a Labor Condition Application filed
     with DOL first; published quarterly as Excel (employer, title, wage, worksite, status).
     Richest signal (who's actively sponsoring + roles/wages).
   - **USCIS H-1B Employer Data Hub** — approved/denied petition counts per employer per year.
   - **PERM data** — green-card sponsorship signal (permanent).
3. **Entity-resolution JOIN** — match each job's company to its sponsorship profile (normalize
   "Google LLC" = "Google Inc"). The hard engineering part.
4. **Filter/classify** — by visa type (H-1B/OPT/CPT/E-3/TN); separate "accepts OPT now" vs
   "sponsors H-1B later"; show sponsor count per company.
5. **Contacts** — hiring manager / immigration coordinator info where available.

**Accuracy** = factual govt record (what actually happened), not "big company so probably sponsors."
**Limitations:** LCA ≠ guaranteed approval; data lags (quarterly); name-matching errors;
multi-location LCAs muddy counts. Best-available evidence, not a promise.

### 15c. ACTION for our M2 (matching)
Add a **sponsorship-data layer**: when we scrape a Greenhouse/Lever/Ashby job, look up the company
in the LCA/USCIS dataset and tag it `sponsors_h1b: yes (N last year)`. Use as a **knockout filter**
for visa-needing candidates (e.g. Indian students F-1/OPT/H-1B). Free data sources:
- dol.gov/agencies/eta/foreign-labor/performance (LCA Excel files)
- USCIS H-1B Employer Data Hub
- pre-parsed: h1bdata.info, h1bgrader.com
This makes us as sponsorship-accurate as MigrateMate PLUS we have auto-apply (which they lack).

---

## 16. TOP-5 COMPETITOR COMPARISON + OUR POSITIONING

### The 5 contenders
1. **Jobright.ai** — commercial copilot + autofill — $39.99/mo — 4.8★ (1,708 reviews)
2. **MigrateMate** — commercial, visa-sponsorship-first — $29/mo — Forbes 30U30
3. **Pickle-Pixel/ApplyPilot** — OSS, fully autonomous (Claude+Playwright) — free+API — new (Feb 2026)
4. **AIHawk** (feder-cr/Jobs_Applier_AI_Agent_AIHawk) — OSS, LinkedIn auto-apply — free+API — **30k+ stars**
5. **career-ops** (santifer) — OSS, Claude-Code, quality-first — free+API — creator got hired with it
(Runner-ups: eliornl/applypilot, neonwatty/job-apply-plugin, LazyApply $99/mo, Ollama job-bot.)

### Feature matrix
| Aspect | Jobright | MigrateMate | ApplyPilot | AIHawk | career-ops |
|---|---|---|---|---|---|
| Discovery | ~400K/day | 500K sponsor jobs | 5 boards+Workday+sites | LinkedIn only | 45 ATS portals |
| Sources | LinkedIn/Indeed | aggregated sponsor | Indeed/LinkedIn/Workday | LinkedIn | GH/Ashby/Lever/Workable |
| AI match/score | yes | filter | 1-10 | preference | reasoning A-F (best) |
| Resume tailoring | yes | no | yes (facts-locked) | yes | yes (ATS PDF) |
| Auto-FILL | yes (ext) | no | yes | yes | prepares |
| Auto-SUBMIT | you click | no | YES full | yes (Easy Apply) | no (human) |
| Visa/sponsorship | coarse H1B filter | YES (LCA/USCIS) | no | no | no |
| Multi-candidate | no | no | no | no | no |
| Ban/ToS risk | low | none | HIGH | HIGH | LOW |
| Self-hosted | no | no | yes | yes | yes |
| Setup | none | none | hard | brutal | hard |

### Scenario winners
- Indian student needs H-1B sponsorship -> **MigrateMate** (only sponsor-accurate)
- US citizen, fast, non-technical -> **Jobright**
- Fully hands-free autonomy -> **ApplyPilot** (but ban risk)
- Free + technical + LinkedIn -> **AIHawk** (ban risk)
- Quality, low ban-risk, human-approved -> **career-ops**
- **Agency applying for MANY candidates -> NONE (the open gap = our opportunity)**

### Key gaps in the market (= our opportunity)
1. **NONE are multi-candidate** (all single-user).
2. **NONE combine sponsorship-targeting + auto-apply** (MigrateMate targets but doesn't apply;
   the auto-appliers apply but ignore sponsorship -> visa candidates get auto-rejected).
3. Auto-appliers (ApplyPilot/AIHawk) lean on LinkedIn/Indeed -> ban risk. career-ops is safe
   (API-first) but won't auto-submit.

### OUR POSITIONING (what we combine that nobody else does)
- **Multi-candidate** scale (none have it)
- **Sponsorship-aware (MigrateMate's LCA data) + auto-apply (Jobright/ApplyPilot's action)** -- the unique combo
- **API-first / low ban-risk** (career-ops' wisdom) -- NOT LinkedIn (AIHawk/ApplyPilot's weakness)
- **Confidence-gated review->auto** (safer than ApplyPilot's blind blast)
What to steal: career-ops reasoning+API-first; ApplyPilot pipeline+facts-lock; Jobright autofill UX +
tracker; MigrateMate sponsorship layer (demo already built, see Section 15 + `us govt data/`);
AIHawk lesson = avoid LinkedIn auto-apply despite its popularity.
