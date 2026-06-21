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
│  │  ├─ sources.py       multi-ATS fetchers: greenhouse/lever/ashby/workable/adzuna -> unified Job
│  │  ├─ sweep.py         cached multi-source sweep (15k boards): build_live_cache/sweep_targets/sweep
│  │  ├─ usfilter.py      US-ONLY location filter: is_us(), us_only() (drop all non-US jobs)
│  │  ├─ dates.py         posting freshness: first_published->days_ago, fresh_only(), jsonld fallback
│  │  └─ daily.py         rank_jobs() (US filter -> sponsorship -> 2-stage), scored_fresh_jobs/_multi()
│  ├─ profile/
│  │  ├─ parse.py         M1: resume PDF -> Profile JSON (Claude), freezes resume_facts
│  │  └─ complete.py      fill extra fields (visa/sponsorship/salary/EEO) once
│  ├─ score/
│  │  ├─ fit.py           heuristic fit (A_skill+B_role+C_exp+D_stack-penalties), per-profile
│  │  ├─ ai_match.py      AI match %: Claude reads profile vs JD -> %, verdict, strengths, gaps
│  │  └─ sponsorship.py   USCIS H-1B lookup: info(company), tag_jobs(); knockout for visa candidates
│  ├─ answer/
│  │  └─ engine.py        M4 3-layer answers (L1 deterministic / L2 cache / L3 Claude) + TEST MODE
│  ├─ submit/
│  │  └─ apply.py         M5: build_review() + Playwright fill_form() (id sel + react-select), review-gated
│  ├─ tailor/
│  │  ├─ client.py        calls the ATS engine /api/tailor, clean_jd()
│  │  └─ batch.py         fit-gated GOLDEN batch tailoring (parallel), {tailored, skipped}
│  └─ dashboard/          RECRUITER CONSOLE (:8050)
│     ├─ app.py           clients list/detail; POST create (resume upload->profile), PATCH edit,
│     │                   DELETE; run-one/run-all (bg); resume PDF download
│     └─ static/          index.html / style.css / app.js — add-candidate modal, editable profile,
│                         shortlist SORT toggle (match% / most-recent), search, status pills
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

0. **✅ DONE — BIGGER SOURCING:** `sources.py` (Greenhouse+Lever+Ashby+**Workable**+**Adzuna**) +
   `sweep.py` (cached multi-source sweep) + `seed/` (15,533 boards). `--seed` sweeps them; `build-cache`
   finds live tokens; Workable/Adzuna query-driven by target titles; no-date JSON-LD fallback (keeps
   unknowns). Verified: 300 boards → 4,681 jobs; Workable 40/query. STILL TODO: Adzuna key
   (`config/adzuna_key.txt`), evaluate **Fantastic.jobs**, run a FULL `build-cache` over all 15k.
1. **✅ DONE — Sponsorship layer:** `score/sponsorship.py` tags jobs with real USCIS H-1B approvals
   (82,280 employers in `sponsorship/h1b_sponsors.json`); knocks out confirmed non-sponsors for
   candidates needing sponsorship; shown in shortlist + dashboard. FUTURE: add LCA/PERM data; better
   entity resolution for tricky company names.
2. **Daily scheduling:** Windows Task Scheduler runs `run-all` each morning; keep ATS engine + dashboard
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

---

## 12. SESSION UPDATE — 2026-06-21 (sourcing finished, sponsorship, US-only, recruiter console)

What was added/changed after the doc's first draft:

### 12a. Bigger sourcing (DONE)
- `sources.py`: **Workable** (search API, query-driven by the candidate's target titles, paginated)
  and **Adzuna** (aggregator; needs a free key at `config/adzuna_key.txt` as `app_id:app_key` or env
  `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`) added alongside Greenhouse/Lever/Ashby.
- `sweep.py`: cached multi-source sweep + `build-cache` CLI to find live tokens (beats 429s).
- `seed/`: 15,533 board tokens copied in (`live_tokens.json` git-ignored).
- `dates.py`: `jsonld_date()` + `enrich_missing_dates()`; `fresh_only` now KEEPS unknown-date jobs
  (marked None) instead of dropping. Verified: 300 boards → 4,681 jobs; Workable 40/query.

### 12b. Sponsorship layer (DONE)
- `score/sponsorship.py`: USCIS H-1B Data Hub (FY21-23) → `sponsorship/h1b_sponsors.json` (82,280
  employers, normalized name → max Initial Approvals). `info(company)`, `tag_jobs()`. Distinguishes
  UNKNOWN (not in data) from CONFIRMED non-sponsor (in data, 0). For candidates needing sponsorship,
  `rank_jobs` KNOCKS OUT confirmed non-sponsors (keeps unknowns). Shown in shortlist + console.
  Raw CSVs git-ignored; compact json tracked.

### 12c. US-ONLY filter (DONE)
- `discover/usfilter.py` `is_us()`: explicit US / US state / "City, ST" / bare remote / multi-loc
  incl. US → keep; known non-US country/region/city → drop. Applied FIRST in `rank_jobs` (before
  scoring, so non-US costs no AI). Verified: gitlab 90 fresh → 62 US kept, 28 dropped.
  **We target USA jobs ONLY.**

### 12d. Freshness / volume tuning (DONE)
- Default freshness window **7 days** (user OK'd up to 7), recency-ranked (today-first as tiebreak).
- `rank_jobs` `ai_cap=130` so the shortlist can surface **~80-90 matches/candidate**. Hitting 80-90
  reliably needs the FULL `build-cache` over all 15k boards (still TODO) — the ~230k live-job pool.

### 12e. RECRUITER CONSOLE (DONE) — the big UI upgrade
- Dashboard is now a full management console so ONE recruiter handles ALL candidates:
  **+ Add candidate** (drop a resume → auto-build personalized profile + optional visa/salary/
  sponsorship/location), **editable profile** (skills/titles/visa/salary — re-drives matching),
  **delete**, **search**, per-candidate **Run daily** + **Run all**, status pills, golden-resume PDF
  downloads, and the matched-jobs **SORT toggle (Match % / Most recent)** with sponsorship + days-ago
  tags. Backend: `POST/PATCH/DELETE /api/clients`. Verified end-to-end (create from resume, screenshots).

### 12f. Match scoring = 2-stage + AI (DONE earlier this session, recap)
- Stage 1 heuristic (`score/fit.py`, per-profile) → Stage 2 **AI match %** (`score/ai_match.py`,
  Claude reads resume vs JD) → the precise "90% / 40%" with verdict + strengths + gaps. Non-eng roles
  (sales/pre-sales/support) penalized so keyword-rich JDs can't carry a wrong-role job.

### 12g. STILL TODO (priority)
1. **Full `build-cache`** over all 15,533 boards → daily `--seed` then hits 80-90 US matches fast.
2. **Application tracker** — status pipeline (found→applied→interview→offer) in the console + SQLite.
3. **Cover-letter generator** + **"Why this job" report** (quick, high-value; ATS engine can do letters).
4. Daily **scheduling** (Task Scheduler), **email loop**, Adzuna key, Fantastic.jobs eval.
5. Ideas vs Jobright (brainstormed): referral/hiring-manager finder, interview prep, company research
   card, AI copilot chat, analytics/funnel, A/B resume variants, daily digest email.

### 12i. FORM-AUDIT HARDENING (DONE) — `tools/audit_forms.py`
Ran the engine against ~180 REAL forms across ~140 multi-industry boards (fintech/data/AI/
consumer/SaaS/health) to find real question types + issues, then evolved it. Results:
- **98% of answers are no-AI** (deterministic + cache), ~2% Claude — fast, cheap, consistent.
- Fixed the GRAVE dropdown bug (was typing raw option IDs like 163595155003 / '1'): the engine
  now stores/selects the human LABEL for every dropdown; never types a non-option value (skips).
- **EEO/pronouns/gender/race/veteran/disability are NEVER guessed** -> "Decline to self-identify"
  (or candidate's stated pref); if no decline option, flagged for the recruiter.
- Added deterministic handlers (discovered from the audit): how-did-you-hear, country->US,
  preferred/first name, (ever/prev/current) worked-at-X -> No, age 18+ -> Yes, consent/privacy-
  notice -> affirm, government-official/PEP -> No, preferred office location, optional social links
  -> blank, conditional "If you answered..." -> blank (checked last so specific Qs win).
- DOUBTS to recruiter are now ONLY genuine required questions the engine shouldn't guess
  (pronouns w/o decline option, contextual conditionals, candidate-specific multi-selects, hybrid
  willingness). They surface as "⚠ check" in the Review modal and can be pre-answered in the
  answer bank. Re-run `python tools/audit_forms.py` anytime to keep hardening.

### 12j. EDGE-CASE HARDENING + MULTI-SELECT + NON-GREENHOUSE (DONE)
Self-audit + probing found and fixed real failure modes:
- `_snap_label` substring bug ('No'->'Not applicable', 'India'->'Indiana') -> word-boundary match.
- Required-empty fields now flag + block auto-submit; required non-resume files (cover letter) flagged.
- Robust submit button (multiple names) + resume upload targets the resume input (not cover-letter).
- **Live-apply safety gate** (`config.LIVE_APPLY`, env APPLYPILOT_LIVE, default OFF): real submits are
  BLOCKED while testing so we never fire a real app with dummy contact; preview always dummy.
- Fixed candidate cache key (was full_name -> stray folders); now the slug.
- **Multi-select** questions supported (`multi_value_multi_select`): pick multiple labels (country->US,
  experience->matching skills); `Answer.values` + fill selects each.
- **Custom-domain Greenhouse** (`resolve_greenhouse`): many companies host Greenhouse on their OWN
  domain (stripe.com/jobs/.../<id>/apply, brex.com/careers...). The old parser only matched
  greenhouse.io -> these were wrongly sent to the generic filler, missing the real questions. Now we
  extract the job id + candidate board tokens from the domain and VERIFY against the Greenhouse API
  (no false positives). Verified: stripe.com URL -> structured 17-question fill. Lesson: always
  resolve+verify the ATS, don't assume from the hostname.
- **Non-Greenhouse fill** (`submit/generic_fill.py`): Lever/Ashby/Workable/custom have no questions API,
  so a generic DOM filler does the universal fields (name/email/phone/links) + resume + screenshot;
  custom questions left for the recruiter (auto-submit disabled for schema-less forms). Verified on
  a live 15five (Lever) form.

### 12h. JOBRIGHT-INSPIRED FEATURES (DONE) — researched their flow + best practices, then built
Research takeaways (sources in chat): prefill screening answers once & reuse; QUALITY beats volume
(11-20 targeted apps ~9.25% interview vs 100+ at 2.58% → validates our fit-gating); keyword sweet
spot ~65-75% (don't over-optimize); human-review/edit beats blind auto-submit; learn from edits.
We're already ahead on multi-candidate + sponsorship + golden tailoring + true submit.
1. **Answer knowledge bank** (`Profile.answer_bank`, optional/partial): recruiter-provided knowledge
   (relocation/start-date/why-interested/how-heard/references/notes). The answer engine L3 feeds it to
   Claude as KNOWLEDGE to COMPOSE each form answer intelligently (adapt to the question/company, NEVER
   paste verbatim, NEVER fabricate). Editable in the console ("Application answers" section).
2. **Apply mode** (`Profile.apply_mode` supervised|automated + `auto_min_match`): per-candidate toggle in
   the console (pill on cards). Supervised = review+edit+approve each; Automated = auto-submit matches
   >= threshold (safety gate still blocks unresolved hard fields).
3. **Application review** (`GET/POST /api/clients/{slug}/application/{file}` + "Review" modal): edit the
   tailored resume (summary + per-role bullets — PDF reflects edits), edit each generated form answer,
   add recruiter comments, see "what the AI changed", then Save / Download PDF / Approve & submit. Sets
   status (pending/approved/submitted/skipped); status pill on the golden-resume row. Edits+comments are
   stored (foundation for the "learn from edits" loop — feeding back into tailoring is still TODO).

---

## 13. SESSION UPDATE — 2026-06-22 (custom-domain Greenhouse, full cache, Manikanta workspace)

### 13a. CUSTOM-DOMAIN GREENHOUSE (fixed — user caught it)
`stripe.com/jobs/listing/.../7923209/apply` (and brex.com/careers, etc.) are Greenhouse-backed but the
old parser only matched `greenhouse.io` → wrongly routed to the generic filler, missing the 17 real
questions. New `resolve_greenhouse(url)` (`discover/ats_client.py`): extracts the job id (gh_jid or a
long numeric path segment) + candidate board tokens from the domain, and VERIFIES against the Greenhouse
API before trusting (no false positives). All apply/preview callers use it. **Lesson: resolve+verify the
ATS from the API, never assume from the hostname.**

### 13b. EDGE-CASE / SELF-AUDIT FIXES (probe-and-fix, high standard)
- `_snap_label` was loose substring → 'No' matched 'Not applicable', 'India'→'Indiana'. Now whole-word/
  phrase match (else None — never a wrong dropdown value). Verified with a probe suite.
- **Required-empty** fields now flag needs_human + block auto-submit; **required non-resume file**
  (cover letter) flagged too. **Submit button** tries several names; **resume upload** targets the
  resume input (not the cover-letter slot).
- **LIVE-APPLY GATE** (`config.LIVE_APPLY`, env `APPLYPILOT_LIVE`, default OFF): real submits are BLOCKED
  while testing so we never fire a real app with dummy contact; preview always dummy; live submit uses
  real contact. Fixed cache key (was full_name → stray folders; now slug).
- **Multi-select** (`multi_value_multi_select`): pick multiple labels (country→US, experience→matching
  skills); `Answer.values`; fill selects each.
- **Non-Greenhouse fill** (`submit/generic_fill.py`): Lever/Ashby/Workable/custom have no questions API →
  generic DOM filler does the universal fields (name/email/phone/links) + resume + screenshot; custom Qs
  left for the recruiter (auto-submit disabled for schema-less forms). Verified on a live 15five (Lever).

### 13c. FORM-ANSWER ENGINE — now 95-98% no-AI (audited on ~180 real forms)
`tools/audit_forms.py` ran the engine over ~180 real forms across ~140 multi-industry boards.
- Fixed the GRAVE dropdown bug (was typing raw option IDs like 163595155003 / '1'): the engine now
  stores/selects the human LABEL for every select; never a non-option value (skips instead).
- EEO/pronouns/gender/race/veteran/disability NEVER guessed → 'Decline to self-identify' (or candidate
  pref); flagged if no decline option.
- Deterministic handlers added from the audits: how-did-you-hear, country→US, preferred name,
  (ever/prev/current) worked-at-X→No, age 18+→Yes, consent/privacy-notice→affirm, gov-official/PEP→No,
  preferred office location, optional social links→blank, conditional 'If you answered...'→blank.
  Location/city → candidate's real location (NEVER an AI-guessed city — caught 'Atlanta' for a Charlotte
  candidate on a live Datadog form).
- DOUBTS to recruiter are now only genuine required Qs the engine shouldn't guess (pronouns w/o decline,
  contextual conditionals, candidate-specific multi-selects). Re-run the audit anytime.
- L2 cache: do NOT cache company/role-specific answers ('why this company') — re-reason per job; only
  generic recurring answers cache. (Was risking one company's "why" answer reused for another.)
- **HOW ANSWERING WORKS:** facts (name/visa/salary) = profile (deterministic, no AI); 'why fit / why
  company / free-text' = **Claude reasons** over resume + that JD + answer bank (composed, truthful, not
  a template); sensitive/unknown = recruiter (flagged) or answer bank.

### 13d. FULL BOARD CACHE (the firehose)
`python -m src.run build-cache` swept ALL 15,533 seed boards → **255,946 jobs**, **8,625 LIVE boards**
(Greenhouse 4,776 · Lever 1,669 · Ashby 2,180) → `seed/live_tokens.json`. Daily `--seed` then sweeps only
live boards. `tools/crawl_candidate.py` = full live-board crawl → shortlist + jobs_cache + Excel (no
upfront tailoring). NOTE: sweeping 8,625 boards with JD content takes ~10-15 min — run in the background
without a `timeout` wrapper (a 10-min timeout killed it once).

### 13e. MANIKANTA WORKSPACE (the user's main ask — DONE)
A dedicated workspace + UI for Sai (and a general tool for anyone):
- **General tailoring tool** = the ATS Resume Maker (`:8000`): upload any resume + paste any JD → golden
  tailored resume + ATS score. (Unchanged, golden engine.)
- **Sai specifically:** re-added from the OFFICIAL resume `Sai_Manikanta_Karnati_Resume.pdf` (50 skills).
  **IMPORTANT FACT: Sai needs NO sponsorship** (`requires_sponsorship=False`, authorized) — corrected
  mid-session; this also widened his pool (no sponsorship knockout).
- Crawl (full cache, US-only, 14d, fit>=45) → **92 fresh US matches** with Match % + Days Ago.
- **Excel** in `manikanta/sai_manikanta_job_matches.xlsx` (Match %, Days Ago, Sponsorship, Company, Link).
- **Deliverables live in `manikanta/`** (Excel + `tailored_resumes/`); shared engine stays in `src/`.
  `_workspace(slug)` → `manikanta/` for sai_manikanta, else `candidates/<slug>/deliverables/`.
- **UI (dashboard → candidate):** all matches listed, **sortable Match% / Most Recent**, **Export Excel**.
  Each job row:
  - `↗ Open` (real posting)
  - **📄 Tailored Resume** button → on click golden-tailors that JD (once, cached) → reveals **PDF** + **DOC**
    download links + a `✓ tailored` marker (so you can tell which are done). Files are named after the
    CANDIDATE (`Sai_Manikanta_Karnati_Resume.pdf` / `.docx`) — no 'tailored' in the name.
  - **Status dropdown** (Not completed / Completed / Error, default Not completed) persisted to
    `candidates/<slug>/app_status.json` → recruiter tracks each application.
- Endpoints: `GET /api/clients/{slug}/tailor-now?url=&fmt=pdf|docx&prepare=` (caches structured golden
  resume once, exports either format; re-fetches the JD if not in `jobs_cache.json`),
  `GET /api/clients/{slug}/excel`, `POST /api/clients/{slug}/job-status?url=&status=`.
- Bug fixed: `daily.py` was missing `import json` (crashed `_save_jobs_cache` at the END of the long
  crawl — the shortlist had already saved). Also shortlist display cap 50→200 to show all ~100.

### 13f. STILL TODO (priority)
1. Daily **scheduling** (Task Scheduler) of `run-all --seed`; keep ATS engine + dashboard up.
2. **Application tracker** is now partly here (per-job status) — extend to a funnel/CRM view + email loop.
3. **Cover-letter generator** (would also let us auto-fill required cover-letter fields).
4. Optimize the big crawl (sweep content=false → fetch content only for survivors) to cut the ~15 min.
5. Likhitha (and other candidates) the same workspace treatment; bump Sai's match cap toward 100.
