"""
M1 — Resume PDF -> personalized Profile JSON (Claude API).

Works for ANY candidate. Extracts the standard fields the resume contains, and leaves
placeholders for the EXTRA fields a resume usually lacks (visa/work-auth, sponsorship,
salary, EEO) so the operator can fill them once. resume_facts freezes exact
companies/titles/metrics so later tailoring can never fabricate them.
"""
from __future__ import annotations

import json
from pathlib import Path

import pdfplumber

from .. import config, llm
from ..models import Profile

SYSTEM = (
    "You are an expert resume parser. Extract ONLY what is present in the resume text. "
    "Never invent employers, dates, titles, or metrics. If a field is absent, leave it empty."
)

PROMPT_TEMPLATE = """\
Extract this resume into JSON with EXACTLY these keys:

{{
  "full_name": str,
  "email": str,
  "phone": str,
  "location": str,
  "linkedin": str,
  "github": str,
  "website": str,
  "years_experience": number or null,   // best estimate of total professional years
  "target_titles": [str],               // roles this candidate fits, inferred from content
  "skills": [str],                      // concrete technologies/skills listed
  "experience": [
    {{"company": str, "title": str, "start": str, "end": str, "bullets": [str]}}
  ],
  "education": [str],
  "resume_facts": {{                    // FROZEN ground truth, copied verbatim
     "companies": str,                  // comma-joined employer names exactly as written
     "titles": str,                     // comma-joined job titles exactly as written
     "metrics": str                     // any quantified achievements, verbatim
  }}
}}

Rules:
- Copy names/dates/metrics EXACTLY as written. Do not paraphrase resume_facts.
- target_titles: infer 2-5 realistic roles from the actual experience/skills.
- Output JSON only.

RESUME TEXT:
\"\"\"
{resume_text}
\"\"\"
"""


def read_pdf_text(pdf_path: str | Path) -> str:
    """Extract plain text from a resume PDF."""
    parts = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def parse_resume(pdf_path: str | Path, *, model: str | None = None) -> Profile:
    """Parse a resume PDF into a Profile. Uses the cheap model (extraction task)."""
    text = read_pdf_text(pdf_path)
    if not text:
        raise ValueError(f"No text extracted from {pdf_path} (scanned image PDF?).")
    data = llm.complete_json(
        PROMPT_TEMPLATE.format(resume_text=text[:18000]),
        system=SYSTEM,
        model=model or config.MODEL_CHEAP,
        max_tokens=3000,
    )
    return Profile(**_clean(data))


def _clean(data: dict) -> dict:
    """Drop unexpected keys / coerce types so Profile() never crashes on model quirks."""
    allowed = set(Profile.model_fields.keys())
    out = {k: v for k, v in data.items() if k in allowed}
    if isinstance(out.get("years_experience"), str):
        try:
            out["years_experience"] = float("".join(c for c in out["years_experience"] if c.isdigit() or c == "."))
        except ValueError:
            out["years_experience"] = None
    return out


def save_profile(profile: Profile, candidate_name: str) -> Path:
    """Save profile.json into the candidate's isolated folder."""
    d = config.candidate_dir(candidate_name)
    path = d / "profile.json"
    path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    import sys

    pdf = sys.argv[1] if len(sys.argv) > 1 else None
    name = sys.argv[2] if len(sys.argv) > 2 else "test_candidate"
    if not pdf:
        print("usage: python -m src.profile.parse <resume.pdf> <candidate_name>")
        raise SystemExit(1)
    prof = parse_resume(pdf)
    out = save_profile(prof, name)
    print(f"Parsed -> {out}")
    print(json.dumps(json.loads(prof.model_dump_json())["resume_facts"], indent=2))
    print(f"Name: {prof.full_name} | {len(prof.skills)} skills | {len(prof.experience)} roles")
    print(f"Target titles: {prof.target_titles}")
