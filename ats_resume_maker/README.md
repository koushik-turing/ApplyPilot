# ATS Resume Maker

Upload a resume, paste a job description, and get a **tailored, ATS-optimized resume**
with a **before/after ATS score** — plus a standalone **ATS score checker**.
Think *iLovePDF, but for job resumes.*

## Features
- 📎 Upload resume in **PDF, DOCX, or TXT**
- 📊 **ATS score** (0–100) with a breakdown: keyword match, section structure,
  formatting/parse-ability, content quality
- ✨ **Tailor to a job** — rewrites your summary/skills/bullets to match the JD and
  shows the score lift
- ✅ Matched vs. missing keyword chips
- ⬇ Download the improved resume as **ATS-safe PDF / DOCX / TXT**
- 🔒 Runs **fully offline** — scoring needs no AI. AI tailoring is optional via local Ollama.

## Run it

```powershell
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Then open **http://localhost:8000** in your browser. That's it — the backend serves
the frontend, so there's nothing else to start.

## AI tailoring (optional, recommended for best results)
The app works without AI (honest rule-based tailoring). For the high-impact,
truthful rewriting of your experience bullets, enable one of:

### Option A — Claude API (best quality)
1. Get an API key at **https://console.anthropic.com** → API Keys.
2. Copy `backend/.env.example` to `backend/.env` and paste your key:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   CLAUDE_MODEL=claude-opus-4-8     # or claude-sonnet-4-6 / claude-haiku-4-5 to cut cost
   ```
3. Restart the app — the badge turns **"AI on · Claude"**.

Cost is pay-per-use and small — roughly **$0.05 per resume on Opus 4.8** (~1¢ on Haiku).
The key stays on the backend and is never sent to the browser. `.env` is git-ignored.

### Option B — Ollama (free, local, private)
1. Install [Ollama](https://ollama.com) and run `ollama pull llama3.1`.
2. Start Ollama (serves on `http://localhost:11434`).
3. Restart the app — the badge turns **"AI on · Ollama"**.

**Engine priority:** Claude (if a key is set) → Ollama (if running) → rule-based.
All three keep the same rule: **never fabricate** skills or experience you don't have.

## Project layout
```
backend/
  app/
    main.py       FastAPI routes + serves the frontend
    schemas.py    Pydantic models (Resume, ScoreReport, …)
    parsing.py    PDF/DOCX/TXT -> text
    extract.py    text -> structured Resume; JD -> keywords
    keywords.py   skills gazetteer + keyword extraction
    scoring.py    the ATS scoring engine
    tailor.py     rewrite resume to fit a JD (rule-based + optional AI)
    export.py     render to ATS-safe PDF/DOCX/TXT
    llm.py        optional local Ollama client
  requirements.txt
frontend/
  index.html  style.css  app.js   (vanilla, no build step)
```

## API
| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/api/health` | service + AI availability |
| POST | `/api/parse`  | file -> extracted text + structured resume |
| POST | `/api/score`  | resume (+ optional JD) -> ATS score report |
| POST | `/api/tailor` | resume + JD -> rewritten resume + before/after scores |
| POST | `/api/export?format=pdf\|docx\|txt` | structured resume -> downloadable file |

## How the ATS score works
Calibrated to mirror real checkers like **Jobscan** and **Resume Worded** — not a
generous keyword counter. With a job description:

| Dimension | Weight | What it measures |
|-----------|--------|------------------|
| Keyword match (hard-skill weighted) | 45% | hard skills count most; a keyword earns **full credit only when it appears in your experience/summary**, half credit if it's only in the skills list, zero if absent |
| Job title match | 12% | does the target role appear in your roles/summary (a major real-ATS factor) |
| Section structure | 10% | standard Summary/Skills/Experience/Education headings |
| Formatting & parse-ability | 13% | contact info, clean single-column text, sane length |
| Content quality | 20% | bullets with metrics + action verbs |

**Anti-stuffing:** a long skills list that isn't backed by your experience is penalized
— exactly as production ATS engines do. You cannot inflate the score by dumping keywords.

**Realistic ranges:** a typical untailored resume scores ~45–60; a genuinely
well-matched resume ~75–85. Reaching 90+ generally requires keyword stuffing, so the
engine resists it. Aim for **75+**, and make sure every keyword reflects real experience.

Without a JD, weights shift to structure, formatting, content, and skills breadth
(general ATS readiness).
