# AI Job-Application Portal

A multi-candidate, **API-first** (Greenhouse / Lever / Ashby / Workable) AI agent that
discovers matching US jobs, scores them, tailors resumes, **answers each application
form intelligently**, and submits — with a human-review step before going fully automatic.

> Master plan & full history: see [`claude_chat_jobportal.md`](./claude_chat_jobportal.md).

## Why this over off-the-shelf tools
- **Multi-candidate** (most tools are single-user)
- **Sponsorship-aware** (tags jobs with real USCIS H-1B data) + **auto-apply**
- **API-first → low ban-risk** (not LinkedIn/Indeed scraping)
- **Confidence-gated review → auto** submit

## Pipeline (7 modules)
| Module | Role | Status |
|---|---|---|
| M1 Ingest | resume → profile JSON | 🟡 partial |
| M2 Discover + Score | sweep ATS APIs, AI fit-score | ✅ done |
| Sponsorship layer | tag jobs with H-1B data | ✅ done (1 candidate) |
| M3 Store | DB + status pipeline | ⬜ todo |
| M4 Answer engine | L1 deterministic / L2 cache / L3 Claude | ⬜ **building** |
| M5 Submit | API / Playwright, review→auto | ⬜ **building** |
| M6 Email | Gmail OAuth confirmations | ⬜ todo |
| M7 Dashboard | FastAPI web UI | ⬜ todo |

## Two ways to run
- **Without an API key (start here):** uses the local **Claude Code CLI** to fill & submit forms. Triggered per batch, review-then-submit.
- **With a Claude API key:** runs 24/7 automatically for many candidates (scoring, tailoring, answering at scale).

## Setup
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

## Safety
- Candidate resumes, profiles, and API keys are **git-ignored** — never committed.
- Hard facts (visa / work-auth / salary) come straight from the candidate profile; the AI never guesses them.
