# Master Plan — One Full-Fledged, End-to-End System (industry standard)

> Goal: a single application that, **for each client (candidate)**, runs the WHOLE journey
> automatically — intake → crawl → match → **tailor every job's resume (batch)** → apply →
> track — at **industry-standard quality**, for **many candidates in parallel**.

---

## 1. The unified pipeline (per candidate, runs in parallel across candidates)

```
 INTAKE        CRAWL              MATCH            TAILOR (BATCH)        APPLY            TRACK
 resume +  →   Greenhouse/    →   AI fit score  →  tailor resume    →   auto-fill +  →   status +
 profile       Lever/Ashby/       1-10 +           to EVERY matched     submit           dashboard +
 (visa/$)      Workable +         "why this job"   job at once          (review-gated)   email loop
               sponsor tag        + knockout       (parallel workers)
```

Every candidate = isolated workspace; shared caches (answers, sponsorship, skills) keep it fast.

---

## 2. Current state (assets across both projects)

| Capability | Where | State |
|---|---|---|
| Crawl Greenhouse/Lever/Ashby/Workable | scrapers + `ats_client` | ✅ works |
| Sponsorship tagging (USCIS H-1B) | `us govt data/` | ✅ works |
| Resume → profile (Claude) | `src/profile` | ✅ works |
| Answer engine (visa/salary/free-text) | `src/answer` | ✅ works |
| Auto-fill + submit (review-gated) | `src/submit` | ✅ works |
| **ATS scoring + tailoring** | `ATS_Resume_Maker` | 🟡 **works but below competitor bar** |
| Batch tailoring (all jobs at once) | — | ⬜ not built |
| Orchestrator (per candidate) | `src/run` | 🟡 single-job only |
| Dashboard / tracker / email | — | ⬜ not built |

---

## 3. Four workstreams to raise the standard

### A. Unify into ONE product
Merge `ATS_Resume_Maker` + job-portal into a single app with one config, one data layer,
one CLI/dashboard. No more two-folder split. Industry-standard structure, tests, logging.

### B. ⭐ RAISE THE ATS TAILORING STANDARD (top priority — the disappointment)
Concrete, evidence-based fixes (gaps already found):
1. **Fix JD keyword extraction.** It currently emits junk (`nbsp`, `amp`, `https`, URLs, generic
   prose) as keywords → pollutes score + missing-list. Add HTML/entity/URL/stopword filtering,
   a curated multi-profession skill ontology, and noun-phrase extraction (not bare tokens).
2. **Calibrate score to reality.** Today it scores the *structured object*; real ATS parse the
   *raw exported PDF text* (handoff §15d). Score the actual rendered PDF text so our number
   tracks Jobscan/Resume Worded. Add an optional cross-check vs a real checker.
3. **Upgrade tailoring quality.** Move tailoring to **Opus 4.8**; add a **critic→refine loop**
   (draft → AI critic scores against JD + best practices → revise) beyond the current single
   retry. Target genuine 85+ that holds up on EXTERNAL checkers, not just ours.
4. **Industry-standard output.** Multiple clean ATS-safe templates; perfect formatting;
   strong-verb + quantified bullets; truthful (flag estimates).
5. **Validation harness.** A test set of (resume, JD) pairs + expected score bands, run on every
   change so quality never regresses.

### C. Batch / automatic tailoring (all jobs at once)
For a candidate's matched jobs, tailor **all of them automatically in parallel** (worker pool),
store per-job tailored resume + before/after score + changes, ranked. One command, not one-by-one.

### D. Full pipeline glue: apply + track + dashboard + email
- Status pipeline (`found→…→submitted→confirmed`) in a real store (SQLite→Postgres).
- Multi-candidate **dashboard** (review queue w/ screenshots, per-candidate auto toggle) — the
  Jobright-style UI.
- Email loop (Gmail OAuth: confirmations/OTPs/recruiter replies).

---

## 4. Suggested build order
1. **B1+B2** — fix keyword extraction + calibrate scoring (biggest quality win, fast).
2. **B3** — Opus + critic→refine loop (the visible quality jump vs competitors).
3. **C** — batch tailoring for all matched jobs (the automation you asked for).
4. **A** — unify the codebases cleanly.
5. **D** — store + dashboard + email.

---

## 5. Open questions (need your input to target the quality raise)
- **What did you compare against** that disappointed you — Jobscan score accuracy? Rezi/Teal/
  Jobright *output* quality? Resume formatting/templates? (Tells me where to push hardest.)
- **Volume target** per candidate per day (drives batch sizing + cost).
- **Submit policy** — review-then-submit for all, or auto-submit once a candidate is trusted?
