"""
AI match score (stage 2) — the precise, explainable per-job match percentage.

The heuristic fit score (fit.py) is a fast filter over many jobs. For the shortlist we
ask Claude to actually read the candidate's profile against the job and return a real
match % (0-100) with reasoning — like Jobright's AI matching. This is the number we
show the user ("this job 90%, that one 45%").

Cheap model (Haiku) — ~$0.001/job — so scoring a day's shortlist costs cents.
"""
from __future__ import annotations

from .. import config, llm
from ..models import Profile

_SYSTEM = (
    "You are an expert technical recruiter. You score how well a specific candidate matches a "
    "specific job, honestly and consistently. You consider: required hard skills the candidate "
    "has vs lacks, seniority/years fit, role/domain alignment, and any disqualifiers (wrong tech "
    "stack, visa/clearance, far-off seniority). You are calibrated: 85-100 = excellent fit apply "
    "now; 70-84 = strong; 55-69 = possible with tailoring; 40-54 = weak; <40 = not a fit."
)


def ai_match(profile: Profile, job_title: str, jd_text: str, *, model: str | None = None) -> dict:
    """Return {match, verdict, strengths, gaps} for this candidate vs this job."""
    prompt = f"""\
CANDIDATE:
  Titles: {', '.join(profile.target_titles) or '(n/a)'}
  Years: {profile.years_experience}
  Skills: {', '.join(profile.skills)}
  Work auth: {profile.work_auth.visa_status or 'n/a'}{' (needs sponsorship)' if profile.work_auth.requires_sponsorship else ''}

JOB TITLE: {job_title}
JOB DESCRIPTION (truncated):
{(jd_text or '')[:3500]}

Score this candidate's match for THIS job as a percentage 0-100. Return ONLY JSON:
{{"match": int, "verdict": "excellent|strong|possible|weak|not a fit",
  "strengths": [str, str, str], "gaps": [str, str]}}
- strengths: the candidate's skills/experience this job specifically wants.
- gaps: required things the candidate lacks or that disqualify (wrong stack, seniority, visa).
Be honest and consistent — a wrong-stack or far-too-senior role must score low even if some
keywords overlap."""
    try:
        data = llm.complete_json(prompt, system=_SYSTEM,
                                 model=model or config.MODEL_CHEAP, max_tokens=500)
        match = int(round(float(data.get("match", 0))))
        return {
            "match": max(0, min(100, match)),
            "verdict": str(data.get("verdict", "")),
            "strengths": [str(s) for s in data.get("strengths", [])][:4],
            "gaps": [str(g) for g in data.get("gaps", [])][:4],
        }
    except Exception as e:
        return {"match": None, "verdict": f"error: {type(e).__name__}", "strengths": [], "gaps": []}
