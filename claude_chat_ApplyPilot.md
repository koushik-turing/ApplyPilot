# ApplyPilot Portal — Handoff Doc

> **Purpose:** Single source of truth + handoff for THIS project (the unified job-application
> portal in `E:\Apply_Pilot_Project_Folder`). If a new terminal / fresh Claude session opens,
> READ THIS FIRST. It records what we're building, every decision, what's done, the learnings,
> and what's next. Keep it updated.
>
> **Last updated:** 2026-06-21
> **Working dir:** `E:\Apply_Pilot_Project_Folder` — ALL work lives here (user's rule).
> **Git:** initialized, ~30 commits. Secrets/PII git-ignored. GitHub acct: `koushik-turing`.

---

## 0. TL;DR — what this is

A **multi-candidate, API-first, AI-powered job-application portal**. For each client (candidate),
**every day** it: reads their resume → finds fresh jobs → scores a **personalized match %** per
job → **tailors their resume per job to a golden ATS standard (≥75%)** → answers the application
form → (review-gated) submits. A **web dashboard** shows it all. Powered by the **Claude API**.

**Two running services:**
- **Portal** (`src/`) — the pipeline + CLI + dashboard.
- **ATS engine** (`ats_resume_maker/`) — FastAPI on **:8000**, does resume scoring + tailoring + export.
- **Dashboard** — FastAPI on **:8050**.

---

## 1. The goal (what the user wants)

For **any candidate**, fully personalized, end-to-end, run **daily**, for **many clients in parallel**:
1. Take their resume (+ extra data: visa/salary).
2. Fetch **fresh** jobs from many job sites (API-first), with "how many days ago posted".
3. Score each job's **match % against THAT resume** (one job 90%, one 40% — accurate & explainable).
4. **Tailor the resume per job** to a golden ATS standard — **≥75% on any external checker** (Jobscan etc.).
5. **Answer the application form** intelligently and **submit** (review first, then auto).
6. Repeat daily; same pipeline for every client; a **dashboard** to see/control it.

**Hard rules the user set:**
- All work in `E:\Apply_Pilot_Project_Folder` (copy code in if needed; don't work elsewhere).
- Use the **Claude API** (the user has a key; it's in env + `ats_resume_maker/backend/.env`).
- **Test mode:** never put a real email/phone on a test application (use dummy contact).
- Git everything so it's trackable.
- Quality bar is high: matching must be accurate; tailored resumes must genuinely hit 75%+ anywhere.

---

## 2. Key decisions (locked)

| Decision | Choice & why |
|---|---|
| Build vs. use ApplyPilot repo | **Build our own.** The public `Pickle-Pixel/ApplyPilot` is Gemini-based, single-candidate, LinkedIn/Indeed (ban risk). We're API-first, multi-candidate, Claude. We took only its one good idea (Claude+browser to fill forms). |
| Job sources | **API-first: Greenhouse / Lever / Ashby / Workable.** NOT LinkedIn/Indeed scraping (ban risk). Public board APIs return jobs AND the application form as structured data. |
| AI brain | **Claude API.** Opus 4.8 = tailoring (the deliverable). Haiku 4.5 = cheap scoring/parsing/AI-match. Offline ATS score = $0. |
| Submit safety | **Review-then-submit by default**, refuse auto-submit while any field needs human. Test-mode dummy contact until going live. |
| Matching | **Two stages.** Stage 1 = fast heuristic filter over all jobs. Stage 2 = **Claude AI match %** (precise, explainable) over the shortlist. |
| Tailoring standard | **Fit-gate first**, then golden tailor. You can't honestly hit 75% on a bad-fit job, so only tailor genuine matches; those reach 75–97 truthfully. |
| Per candidate | **Isolated folder** `candidates/<slug>/` (git-ignored — real PII). |

---

## 3. Architecture / file map

```
E:\Apply_Pilot_Project_Folder\
├─ claude_chat_ApplyPilot.md        ← THIS doc
├─ claude_chat_jobportal.md         ← original portal master-plan (reference)
├─ README.md  requirements.txt  docs/(MASTER_PLAN, FEATURES)
├─ src/                             ← the PORTAL
│  ├─ config.py        paths, ANTHROPIC_API_KEY, model tiers, candidate_dir()
│  ├─ models.py        Profile/WorkAuth/Job/FormQuestion/Answer/Status (pydantic)
│  ├─ llm.py           Claude wrapper: complete()/complete_json(), Haiku/Sonnet/Opus
│  ├─ pipeline.py      run_candidate_daily(), run_all_candidates(), list_candidates()
│  ├─ run.py           CLI: add/complete/show/daily/tailor-all/apply/run-daily/run-all
│  ├─ discover/
│  │  ├─ ats_client.py    Greenhouse public API: list_jobs(), get_job_form() (forms as data)
│  │  ├─ dates.py         posting freshness: first_published->days_ago, fresh_only()
│  │  └─ daily.py         scored_fresh_jobs() (2-stage), daily_crawl(), shortlist_row()
│  ├─ profile/
│  │  ├─ parse.py         M1: resume PDF -> Profile JSON (Claude), freezes resume_facts
│  │  └─ complete.py      fill extra fields (visa/sponsorship/salary/EEO) once
│  ├─ score/
│  │  ├─ fit.py           heuristic fit (A_skill+B_role+C_exp+D_stack-penalties), per-profile
│  │  └─ ai_match.py      AI match %: Claude reads profile vs JD -> %, verdict, strengths, gaps
│  ├─ answer/
│  │  └─ engine.py        M4 3-layer answers (L1 deterministic / L2 cache / L3 Claude) + TEST MODE
│  ├─ submit/
│  │  └─ apply.py         M5: build_review() + Playwright fill_form() (id sel + react-select), review-gated
│  ├─ tailor/
│  │  ├─ client.py        calls the ATS engine /api/tailor, clean_jd()
│  │  └─ batch.py         fit-gated GOLDEN batch tailoring (parallel), {tailored, skipped}
│  └─ dashboard/
│     ├─ app.py           FastAPI :8050 — clients, detail, run buttons, resume PDF download
│     └─ static/          index.html / style.css / app.js (vanilla)
├─ ats_resume_maker/                ← the ATS ENGINE (copied in, git-tracked)
│  ├─ backend/.env                  ← ANTHROPIC_API_KEY (GIT-IGNORED)
│  └─ backend/app/                  main.py, keywords.py, scoring.py, tailor.py, export.py,
│                                    extract.py, polish.py, review.py, claude_client.py, config.py
├─ candidates/<slug>/               ← per-client (GIT-IGNORED): profile.json, resume,
│                                     daily_shortlist.csv, daily_run.json, tailored/*.json+SUMMARY.md,
│                                     reviews/, answer_cache.json
├─ config/  data/  docs/
```

> The original code (scrapers, 15,533-board seed lists, USCIS H-1B data, Sai/Likhitha job lists)
> still lives in `D:\Pallavi_New_Hackathon_Apr_2026\New_Project\` — reference/source for sourcing.

---

## 4. How to run it

```bash
# one-time deps
pip install -r requirements.txt
python -m playwright install chromium      # for the submit step

# start the ATS engine (needed for tailoring) — keep running
cd ats_resume_maker/backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
#   verify:  http://127.0.0.1:8000/api/health  -> {"engine":"claude","model":"claude-opus-4-8"}
#   IMPORTANT (Windows): point tunnels/health at 127.0.0.1, NOT localhost (IPv6 ::1 trap).

# the CLI (from project root)
python -m src.run add "Sai Manikanta" "path\resume.pdf"      # M1 resume->profile (+copies resume in)
python -m src.run complete "Sai Manikanta" intake.json       # visa/salary/EEO once
python -m src.run daily "Sai Manikanta" --boards stripe databricks --days 7 --fit 60
python -m src.run tailor-all "Sai Manikanta" --board gitlab --count 5 --fit 55
python -m src.run run-daily "Sai Manikanta"                  # FULL daily flow, one client
python -m src.run run-all                                    # FULL daily flow, ALL clients
python -m src.run apply "Sai Manikanta" "<job-url>"          # review only
python -m src.run apply "Sai Manikanta" "<url>" --fill       # browser fill, stop before submit
python -m src.run apply "Sai Manikanta" "<url>" --submit --live   # real submit (drops dummy contact)

# the dashboard
python -m uvicorn src.dashboard.app:app --port 8050          # open http://localhost:8050
```

**Model tiers (cost):** Opus for tailoring, Haiku for scoring/match, offline ATS score = $0.
Blended ~ a few cents per candidate per day. Set `CLAUDE_TAILOR_MODEL=claude-sonnet-4-6` to cut cost.

---

## 5. The pipeline, stage by stage

```
add(resume)→profile  →  daily crawl (FRESH + 2-stage MATCH)  →  GOLDEN tailor (fit-gated)
                                                                       →  answer form (test-mode)
                                                                       →  review-gated submit
                                                                       →  dashboard
```

1. **M1 Ingest** (`profile/parse.py`): resume PDF → structured Profile via Claude Haiku; `resume_facts`
   (companies/titles/metrics) frozen so tailoring can reorganize but never fabricate.
2. **Profile complete** (`profile/complete.py`): visa/sponsorship/salary/EEO supplied once (not on a resume).
3. **Discover** (`discover/ats_client.py`): public Greenhouse API → live jobs + each job's exact
   application form (field names, types, option IDs like Yes=1/No=0).
4. **Freshness** (`discover/dates.py`): `first_published` → `days_ago`; keep only fresh (≤N days).
5. **Match — 2 stages** (`discover/daily.py`):
   - Stage 1 `score/fit.py` (heuristic, cheap, all jobs): A_skill + B_role + C_exp + D_stack − penalties.
     Derived **per candidate** from their profile (skills via token+alias matching, role tokens, years,
     known langs, sponsorship-need). Penalizes wrong-stack, sales/pre-sales/support, clearance, no-sponsor.
   - Stage 2 `score/ai_match.py` (Claude Haiku, precise, survivors): reads profile vs JD → **match %**
     + verdict + strengths + gaps. THIS is the headline % shown ("78%, 62%...").
6. **Tailor — golden** (`tailor/batch.py` + ATS engine): fit-gate (only tailor matches), then Opus
   tailoring with a **critic→refine loop**. Each result flags `golden = ATS_after ≥ 75`. Skipped jobs
   reported honestly with reasons.
7. **Answer** (`answer/engine.py`): L1 deterministic (name/email/phone/visa/salary — AI never guesses
   hard facts) / L2 cache / L3 Claude for free-text. **TEST MODE** (default) swaps email→`...023@`, phone→
   fake 555 number so no real person is contacted; `--live` uses real.
8. **Submit** (`submit/apply.py`): review sheet, then Playwright fills (by `id`; react-select dropdowns
   via click), uploads resume, screenshots, **stops before submit** unless `--submit` and nothing needs review.
9. **Orchestrate** (`pipeline.py`): `run_candidate_daily` chains 4→6 per client; `run_all_candidates`
   does every client. **Dashboard** visualizes it.

---

## 6. The ATS engine (`ats_resume_maker/`) — raised to a golden standard

FastAPI app (own handoff: `ats_resume_maker/claude_chat_ats_resume_maker.md`). What we changed here:
- **B1 keywords** (`keywords.py`): strip HTML tags/entities + junk (`nbsp`,`amp`,URLs); multi-word
  domain-phrase extraction (noun bigrams). Junk no longer pollutes keywords/score.
- **B2 scoring** (`scoring.py`): keyword-dominated, calibrated to Jobscan (untailored resume ~45 "Weak",
  not inflated). Richer keyword universe.
- **B3 tailoring** (`tailor.py`): default model **Opus 4.8**; added an **independent critic→refine loop**
  (recruiter critic judges writing quality → one revision). Genuine recruiter-grade bullets.
- **B4 export** (`export.py`): 3 ATS-safe templates (modern/classic/executive); `/api/export?template=`.

**Golden standard rationale (important):** "always ≥75%" and "matches Jobscan" only reconcile by being
HONEST — fit-gate to genuine matches, then genuinely strengthen the resume (keywords woven into real
experience bullets = full ATS credit everywhere). We do NOT fake the number. Verified: fit-90 jobs →
ATS 94–97 golden; bad-fit jobs skipped.

---

## 7. Learnings (so the next person doesn't relearn the hard way)

- **Greenhouse public API = the unlock.** `GET boards-api.greenhouse.io/v1/boards/{board}/jobs` (live
  jobs, `first_published` for freshness) and `.../jobs/{id}?questions=true` (exact form: field names +
  option IDs). No scraping/CAPTCHA to discover jobs OR read forms.
- **Greenhouse forms use `id`, not `name`.** Fill by `#id`. Visa/auth dropdowns are **react-select**
  comboboxes: click to open, click the option by label; the value lives in a display div, not input.value.
- **Skill matching must be token+alias based.** Resumes store "RESTful APIs / Java Spring Boot / Google
  Cloud Platform"; JDs say "REST / Java / GCP". Match on significant tokens + an alias map, not exact phrases.
- **Score must mirror real ATS** (keyword-in-context dominated). Our internal "80" ≈ external "75+".
  Structure/format give few points (real ATS barely count them).
- **Heuristic fit alone over-credits keyword-rich non-eng roles** at tech companies (a Sales/Solutions
  role JD mentions the candidate's skills). Fixed with non-engineering penalties AND the AI match stage.
- **AI match (Haiku) is the accurate %.** It catches seniority gaps, wrong domain, visa friction —
  things keyword heuristics can't. Use heuristic to filter cheaply, AI to score precisely.
- **Greenhouse rate-limits** (HTTP 429) when sweeping thousands of boards fast → need pacing +
  a live-token cache + lean on Lever/Ashby (they don't throttle us). (From the original project.)
- **Windows gotchas:** console can't print emoji under cp1252 (reconfigure stdout to utf-8); point local
  health checks/tunnels at `127.0.0.1` not `localhost` (IPv6 `::1` refuses).

---

## 8. The journey (how we went / what we focused on)

1. **Oriented:** read the ApplyPilot repo + the user's existing job-portal & ATS-maker work (two prior
   handoff docs). Decided to **build our own** (API-first, multi-candidate, Claude), not the repo.
2. **Built the portal spine + flow:** config/models/llm → M1 resume→profile → M4 answer engine →
   M5 review-gated browser submit (got a real Greenhouse form filling live).
3. **User redirected to QUALITY:** "form-filling is commodity; ATS tailoring is the value, and it's not
   up to competitors." Pivoted hard to the ATS engine.
4. **Consolidated** the ATS engine from `D:\...` into THIS folder (user's "all work here" rule) + git-init'd it.
5. **Raised the ATS standard** B1→B4 (keywords, Jobscan calibration, Opus+critic, templates).
6. **Batch tailoring** (all jobs at once) → then **fit-gated golden** (≥75% honestly).
7. **Test mode** dummy contact (user: never use real email/phone while testing).
8. **Personalized matching:** generalized the user's proven `final_score_sai.py` into a per-profile
   heuristic fit scorer (2-stage design); then added **freshness/days-ago** (from `fetch_dates_sai.py`).
9. **Orchestration:** `run-daily` (one client) + `run-all` (every client) — proven on Sai + Likhitha.
10. **Dashboard** (Jobright-style web UI).
11. **AI match %** (precise stage-2) — the "perfect" per-job percentage the user asked for.

Focus throughout: **personalization per candidate, honesty (no faked scores), API-first/low-ban-risk,
multi-client, and keeping everything runnable + git-tracked in one folder.**

---

## 9. Current state

✅ Works end-to-end, multi-client, with the dashboard. Proven live on **Sai Manikanta** (backend, Java/
Python, 4yr) and **Likhitha Chinthirala** (fresher, full-stack/AI-ML). Both: fresh+fit shortlist →
golden tailored resumes. Match % is AI-accurate and explainable.

**Known rough edges:** fit heuristic is tuned for technical candidates (a fully domain-general version
would derive each candidate's domain); a few near-duplicate role variants slip through; sourcing is
currently a handful of Greenhouse boards (see next).

---

## 10. NEXT STEPS (in priority order)

1. **⭐ BIGGER SOURCING (current ask):** fetch from **all** API-friendly job sites, fast, to get far more
   jobs, then filter by match. Specifically:
   - Add **Lever** (`api.lever.co/v0/postings/{org}`) and **Ashby**
     (`api.ashbyhq.com/posting-api/job-board/{org}`) and **Workable** fetchers to `discover/`.
   - Load the **15,533-board seed lists** (`D:\...\New_Project\seed\*.json`) into this folder; sweep with
     pacing + a **live-token cache** (sweep once, keep only boards that have jobs) to beat 429s.
   - Aggregators that give volume + dates: **Adzuna** (`adzuna_jobs.py` ready, needs free key),
     evaluate **Fantastic.jobs** (one API indexing 54 ATS / 175k+ sites).
   - For sources WITHOUT a posting date, fall back to JSON-LD `datePosted` scrape, else mark "unknown"
     (don't drop silently).
   - Then the existing 2-stage match (heuristic → AI %) filters the firehose down per candidate.
2. **Sponsorship layer:** tag each job `sponsors_h1b: yes (N)` from USCIS/LCA data (`D:\...\us govt data\`)
   — critical for visa candidates; use as a knockout for those needing sponsorship.
3. **Daily scheduling:** Windows Task Scheduler runs `run-all` each morning; keep ATS engine + dashboard
   up (as services). Makes it truly hands-free.
4. **Apply automation + tracker:** fold review-gated submit into the daily run; status pipeline
   (found→matched→tailored→review→submitted→confirmed) in SQLite; show in dashboard.
5. **Email loop:** Gmail OAuth — capture confirmations/OTPs/recruiter replies.

---

## 11. Open questions to confirm with the user

- Volume cap per candidate per day (to avoid spam-flagging) and how many boards/sources to sweep.
- When to flip a candidate from review→auto-submit.
- Whether to get the Adzuna key now and/or evaluate Fantastic.jobs for production sourcing.
- Exact required profile fields / visa wording for forms (esp. OPT vs H-1B nuances).
```
