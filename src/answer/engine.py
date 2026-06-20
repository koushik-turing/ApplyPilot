"""
M4 — Answer Engine. For ANY application form, produce a personalized answer per field.

Three layers (master plan §5):
  L1 deterministic  — name/email/phone/visa/auth/salary/years come STRAIGHT from the
                      profile. The AI is NEVER allowed to guess these hard facts.
  L2 cache          — recurring questions ("How did you hear about us?") reused per candidate.
  L3 Claude         — only new / free-text questions hit the API, tailored to the JD.

Every answer carries a source + confidence + needs_human flag for the review gate.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import config, llm
from ..models import Answer, AnswerSheet, AnswerSource, FormQuestion, Job, Profile


# ---------------- L1: deterministic field matching ----------------

def _opt_value(q: FormQuestion, want: str) -> str | None:
    """For a select question, return the option *value/id* whose label matches `want`."""
    for o in q.options:
        if str(o.get("label", "")).strip().lower() == want.lower():
            return str(o.get("value"))
    return None


def _yesno(q: FormQuestion, yes: bool) -> str | None:
    return _opt_value(q, "Yes" if yes else "No")


def _l1_answer(q: FormQuestion, p: Profile) -> Answer | None:
    """Return a deterministic answer if this is a known hard field, else None."""
    label = q.label.lower()
    fn = q.field_names

    def mk(value: str, conf: float = 1.0, human: bool = False) -> Answer:
        return Answer(label=q.label, field_names=fn, value=value,
                      source=AnswerSource.DETERMINISTIC, confidence=conf, needs_human=human)

    # Identity
    if "first_name" in fn or re.search(r"\bfirst name\b", label):
        return mk(p.full_name.split()[0] if p.full_name else "")
    if "last_name" in fn or re.search(r"\blast name\b", label):
        return mk(p.full_name.split()[-1] if len(p.full_name.split()) > 1 else "")
    if "email" in fn or "email" in label:
        return mk(p.email)
    if "phone" in fn or "phone" in label:
        return mk(p.phone)
    if "linkedin" in label:
        return mk(p.linkedin)
    if "github" in label:
        return mk(p.github)
    if ("website" in label or "portfolio" in label):
        return mk(p.website)

    # Hard immigration facts — NEVER AI-guessed. Flag for human if profile lacks the data.
    if "sponsorship" in label or ("visa" in label and "require" in label):
        v = p.work_auth.requires_sponsorship
        if v is None:
            return mk("", conf=0.0, human=True)
        mapped = _yesno(q, v) if q.options else ("Yes" if v else "No")
        return mk(mapped or ("Yes" if v else "No"))
    if "authorized to work" in label or "legally authorized" in label:
        v = p.work_auth.authorized_us
        if v is None:
            return mk("", conf=0.0, human=True)
        mapped = _yesno(q, v) if q.options else ("Yes" if v else "No")
        return mk(mapped or ("Yes" if v else "No"))

    # Compensation
    if "salary" in label or "compensation" in label or "desired pay" in label:
        return mk(p.desired_salary, human=not bool(p.desired_salary))

    # Location working from
    if ("city" in label and "state" in label) or "where will you be working" in label:
        loc = p.preferred_locations[0] if p.preferred_locations else p.location
        return mk(loc, human=not bool(loc))

    # Years of experience
    if "years of experience" in label or "years' experience" in label:
        if p.years_experience is not None:
            return mk(str(int(p.years_experience)))

    return None


# ---------------- L2: per-candidate answer cache ----------------

def _cache_path(candidate: str) -> Path:
    return config.candidate_dir(candidate) / "answer_cache.json"


def _load_cache(candidate: str) -> dict[str, str]:
    p = _cache_path(candidate)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _save_cache(candidate: str, cache: dict[str, str]) -> None:
    _cache_path(candidate).write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _cache_key(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip().lower())


# ---------------- L3: Claude reasoning for free-text ----------------

L3_SYSTEM = (
    "You answer a single job-application question for a specific candidate, using ONLY "
    "their profile and the job description. Be concise, professional, truthful. "
    "Never invent facts not supported by the profile. Return JSON: "
    '{"answer": str, "confidence": 0.0-1.0}'
)


def _l3_answer(q: FormQuestion, p: Profile, job: Job) -> Answer:
    prompt = f"""\
CANDIDATE PROFILE (truth — do not contradict):
{p.model_dump_json(indent=2)}

JOB: {job.title} at {job.board}
JOB DESCRIPTION (first 2000 chars):
{(job.content or '')[:2000]}

QUESTION: {q.label}
{"OPTIONS: " + ", ".join(o.get("label","") for o in q.options) if q.options else ""}

Answer the question for this candidate. If it's multiple-choice, return the exact option label.
"""
    try:
        data = llm.complete_json(prompt, system=L3_SYSTEM, model=config.MODEL_SMART, max_tokens=600)
        ans_text = str(data.get("answer", "")).strip()
        conf = float(data.get("confidence", 0.6))
    except Exception:
        return Answer(label=q.label, field_names=q.field_names, value="",
                      source=AnswerSource.CLAUDE, confidence=0.0, needs_human=True)

    value = ans_text
    if q.options:  # map chosen label back to its option value/id
        mapped = _opt_value(q, ans_text)
        value = mapped if mapped is not None else ans_text
    return Answer(label=q.label, field_names=q.field_names, value=value,
                  source=AnswerSource.CLAUDE, confidence=conf,
                  needs_human=conf < 0.5 or q.required and not value)


# ---------------- Orchestration ----------------

def answer_form(job: Job, profile: Profile, candidate: str) -> AnswerSheet:
    """Produce a full answer sheet for one job's form, for one candidate."""
    cache = _load_cache(candidate)
    sheet = AnswerSheet(job_id=job.job_id)

    for q in job.questions:
        if q.field_type == "input_file":   # resume/cover-letter handled by M5 upload
            continue

        # L1 — deterministic hard fields
        a = _l1_answer(q, profile)
        if a is not None:
            sheet.answers.append(a)
            continue

        # L2 — cached recurring answer
        key = _cache_key(q.label)
        if key in cache and cache[key]:
            val = cache[key]
            if q.options:
                val = _opt_value(q, val) or val
            sheet.answers.append(Answer(label=q.label, field_names=q.field_names,
                                        value=val, source=AnswerSource.CACHE, confidence=0.9))
            continue

        # L3 — Claude reasoning for new/free-text
        a = _l3_answer(q, profile, job)
        sheet.answers.append(a)
        if a.value and a.confidence >= 0.7:   # remember confident free-text answers
            cache[key] = next((o["label"] for o in q.options
                               if str(o.get("value")) == a.value), a.value)

    _save_cache(candidate, cache)
    return sheet
