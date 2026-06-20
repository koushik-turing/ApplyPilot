"""Claude-powered professional resume review for the ATS Score Checker.

Adds a thorough, recruiter-grade qualitative analysis on top of the deterministic
score. Optional — only runs when a Claude API key is configured; the numeric score
works fully offline without it.
"""
from __future__ import annotations
import json
import re

from .schemas import Resume, ScoreReport, AiReview, JobDescription
from . import claude_client
from .config import settings

_SYSTEM = (
    "You are a professional resume reviewer and ATS (applicant tracking system) expert "
    "with years of experience helping candidates across every industry. You give specific, "
    "honest, actionable feedback — never generic filler, never fabrication. You judge the "
    "resume on impact, clarity, quantified achievements, keyword relevance, and ATS parse-ability."
)


def _extract_json(s: str) -> dict | None:
    s = re.sub(r"```(?:json)?", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i == -1 or j <= i:
        return None
    try:
        out = json.loads(s[i:j + 1])
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


def ai_review(text: str, resume: Resume, jd: JobDescription | None,
              report: ScoreReport) -> AiReview | None:
    """Return a Claude-generated review, or None if AI is unavailable / fails."""
    if not claude_client.claude_available():
        return None
    try:
        client = claude_client.get_client()
        jd_block = (f"TARGET JOB DESCRIPTION:\n{(jd.raw if jd else '')[:2500]}\n\n"
                    if jd else "No job description provided — review for general ATS readiness.\n\n")
        miss = ", ".join(report.missing_keywords[:12]) or "(none detected)"
        user = (
            f"{jd_block}"
            f"COMPUTED ATS SCORE: {report.overall}/100 ({report.rating}).\n"
            f"KEYWORDS THE JOB WANTS THAT ARE MISSING: {miss}\n\n"
            f"RESUME TEXT:\n{text[:6000]}\n\n"
            "Review this resume like a professional reviewer. Return ONLY a JSON object "
            "(no markdown, no commentary) with these keys:\n"
            '  "verdict": one honest sentence summarizing the resume\'s ATS readiness,\n'
            '  "strengths": 3-5 short specific strengths,\n'
            '  "weaknesses": 3-5 short specific weaknesses,\n'
            '  "fixes": 4-6 prioritized, concrete improvements the candidate should make '
            "(most impactful first; reference real lines where possible),\n"
            '  "ats_tips": 2-4 formatting/parse-ability tips specific to this resume.\n'
            "Be specific to THIS resume. Do not invent experience the candidate doesn't have."
        )
        resp = client.messages.create(
            model=settings.claude_review_model, max_tokens=2000,
            system=_SYSTEM, messages=[{"role": "user", "content": user}],
        )
        if resp.stop_reason == "max_tokens":
            return None
        data = _extract_json("".join(b.text for b in resp.content if b.type == "text"))
        if not data:
            return None
        return AiReview(
            verdict=str(data.get("verdict", "")).strip(),
            strengths=[str(x).strip() for x in data.get("strengths", []) if str(x).strip()][:6],
            weaknesses=[str(x).strip() for x in data.get("weaknesses", []) if str(x).strip()][:6],
            fixes=[str(x).strip() for x in data.get("fixes", []) if str(x).strip()][:8],
            ats_tips=[str(x).strip() for x in data.get("ats_tips", []) if str(x).strip()][:5],
        )
    except Exception:
        return None
