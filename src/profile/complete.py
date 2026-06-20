"""
Fill the EXTRA candidate fields a resume never contains (visa/work-auth, salary, EEO).

These are hard facts the answer engine must have to fill forms deterministically.
Provide them once per candidate via an intake dict (later: a web intake form / dashboard).
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import config
from ..models import Profile, WorkAuth


# Fields the operator/candidate supplies once. Shown in the intake form / dashboard.
INTAKE_FIELDS = {
    "authorized_us": "Legally authorized to work in the US now? (true/false)",
    "requires_sponsorship": "Requires visa sponsorship now or in future? (true/false)",
    "visa_status": "Visa status (e.g. 'US Citizen', 'Green Card', 'F-1 OPT', 'H-1B')",
    "desired_salary": "Desired salary (e.g. '$120,000' or '120000')",
    "preferred_locations": "Preferred work locations (comma-separated)",
    "open_to_remote": "Open to remote? (true/false)",
}

# Optional ANSWER-BANK topics — common application questions. All optional; whatever is
# provided becomes knowledge the AI uses (intelligently, not verbatim) when filling forms.
ANSWER_BANK_TOPICS = {
    "willing_to_relocate": "Open to relocating? Any constraints?",
    "start_date": "Earliest start date / notice period",
    "why_interested": "What kind of role/company excites the candidate (used to compose 'why us')",
    "remote_preference": "Remote / hybrid / onsite preference",
    "work_schedule": "Any schedule constraints (full-time, shifts, travel %)",
    "references": "References available? Any note",
    "linkedin": "LinkedIn URL (if not on resume)",
    "portfolio": "Portfolio / GitHub URL",
    "how_heard": "How did you hear about us (default answer)",
    "criminal_record": "Any disclosures the candidate wants handled a certain way",
    "notes": "Anything else the recruiter knows that helps answer screening questions",
}


def load_profile(candidate: str) -> Profile:
    path = config.candidate_dir(candidate) / "profile.json"
    return Profile(**json.loads(path.read_text(encoding="utf-8")))


def complete_profile(candidate: str, intake: dict) -> Path:
    """Merge intake answers into the candidate's saved profile and re-save."""
    p = load_profile(candidate)

    wa = p.work_auth
    if "authorized_us" in intake:
        wa.authorized_us = _as_bool(intake["authorized_us"])
    if "requires_sponsorship" in intake:
        wa.requires_sponsorship = _as_bool(intake["requires_sponsorship"])
    if "visa_status" in intake:
        wa.visa_status = str(intake["visa_status"])
    p.work_auth = wa

    if "desired_salary" in intake:
        p.desired_salary = str(intake["desired_salary"])
    if "preferred_locations" in intake:
        locs = intake["preferred_locations"]
        p.preferred_locations = [s.strip() for s in locs.split(",")] if isinstance(locs, str) else list(locs)
    if "open_to_remote" in intake:
        p.open_to_remote = _as_bool(intake["open_to_remote"])
    if intake.get("apply_mode") in ("supervised", "automated"):
        p.apply_mode = intake["apply_mode"]
    if "auto_min_match" in intake:
        try:
            p.auto_min_match = int(intake["auto_min_match"])
        except (TypeError, ValueError):
            pass
    if "eeo" in intake and isinstance(intake["eeo"], dict):
        p.eeo.update(intake["eeo"])
    # Optional answer-bank knowledge (partial fine). Accept a nested dict OR flat keys.
    if "answer_bank" in intake and isinstance(intake["answer_bank"], dict):
        p.answer_bank.update({k: str(v) for k, v in intake["answer_bank"].items() if str(v).strip()})
    for topic in ANSWER_BANK_TOPICS:
        if topic in intake and str(intake[topic]).strip():
            p.answer_bank[topic] = str(intake[topic]).strip()

    path = config.candidate_dir(candidate) / "profile.json"
    path.write_text(p.model_dump_json(indent=2), encoding="utf-8")
    return path


def _as_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in {"true", "yes", "y", "1"}:
        return True
    if s in {"false", "no", "n", "0"}:
        return False
    return None
