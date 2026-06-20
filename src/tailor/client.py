"""
Tailor integration — reuse the existing ATS Resume Maker engine (Jobright-style).

Rather than rebuild scoring/tailoring, we call the battle-tested ATS_Resume_Maker
backend (Claude-powered, Jobscan-calibrated). For each crawled job we get:
  - before/after ATS score
  - a resume rewritten to that exact JD (keywords woven into real experience)
  - the list of changes (with estimated-metric flags)

Start the engine first:
  cd <ATS_Resume_Maker>/backend && python -m uvicorn app.main:app --port 8000
"""
from __future__ import annotations

import os
import re

import httpx

ATS_API = os.getenv("ATS_API_URL", "http://127.0.0.1:8000")


def engine_available() -> bool:
    try:
        r = httpx.get(f"{ATS_API}/api/health", timeout=4)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except Exception:
        return False


def clean_jd(html_or_text: str) -> str:
    """Strip HTML tags/entities from a crawled job description."""
    t = re.sub(r"<[^>]+>", " ", html_or_text or "")
    t = re.sub(r"&[a-z]+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tailor_for_job(resume_text: str, jd_text: str, *, timeout: float = 200.0) -> dict:
    """
    Tailor a resume to a job description. Returns:
      {score_before, score_after, tailored_resume, changes, engine}
    Raises RuntimeError if the engine isn't running.
    """
    if not engine_available():
        raise RuntimeError(
            f"ATS engine not reachable at {ATS_API}. Start it: "
            "cd ATS_Resume_Maker/backend && python -m uvicorn app.main:app --port 8000"
        )
    r = httpx.post(
        f"{ATS_API}/api/tailor",
        data={"resume_text": resume_text, "job_description": clean_jd(jd_text)},
        timeout=timeout,
    )
    r.raise_for_status()
    d = r.json()
    return {
        "score_before": d["score_before"]["overall"],
        "score_after": d["score_after"]["overall"],
        "missing_before": d["score_before"].get("missing_keywords", []),
        "tailored_resume": d["tailored_resume"],
        "changes": d.get("changes", []),
        "engine": d.get("engine", "unknown"),
    }


def export_resume(structured_resume: dict, fmt: str = "pdf", *, timeout: float = 60.0) -> bytes:
    """Render a tailored (structured) resume to pdf/docx/txt via the engine."""
    r = httpx.post(f"{ATS_API}/api/export", params={"format": fmt},
                   json=structured_resume, timeout=timeout)
    r.raise_for_status()
    return r.content
