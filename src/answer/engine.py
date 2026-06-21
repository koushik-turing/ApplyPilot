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

import hashlib
import json
import re
from pathlib import Path

from .. import config, llm
from ..models import Answer, AnswerSheet, AnswerSource, FormQuestion, Job, Profile


# ---------------- TEST MODE: never submit a real person's contact details ----------------
# While testing we must NOT put the candidate's real email/phone on live applications.
# These produce harmless, clearly-fake values so no real inbox/phone is ever contacted.

def dummy_email(email: str) -> str:
    """Append '023' to the username so it's a different, non-delivering address."""
    if "@" not in email:
        return "test.candidate023@example.com"
    local, domain = email.split("@", 1)
    return f"{local}023@{domain}"


def dummy_phone(seed: str = "") -> str:
    """Stable, clearly-fake US number: 555 exchange + the 0100-0199 fictional range."""
    h = int(hashlib.md5((seed or "x").encode()).hexdigest(), 16)
    area = 200 + (h % 800)            # 200-999
    last = 100 + (h // 800 % 100)     # 0100-0199 — reserved for fictional use
    return f"({area}) 555-{last:04d}"


def _sanitize_for_test(sheet: AnswerSheet, profile: Profile) -> None:
    """Replace any email/phone answer with dummy values (in place)."""
    for a in sheet.answers:
        names = " ".join(a.field_names).lower()
        label = a.label.lower()
        if "email" in names or "email" in label:
            a.value = dummy_email(profile.email or "")
        elif "phone" in names or "phone" in label:
            a.value = dummy_phone(profile.full_name or profile.email)


# ---------------- L1: deterministic field matching ----------------

def _opt_value(q: FormQuestion, want: str) -> str | None:
    """For a select question, return the option *value/id* whose label matches `want`."""
    for o in q.options:
        if str(o.get("label", "")).strip().lower() == want.lower():
            return str(o.get("value"))
    return None


def _yesno(q: FormQuestion, yes: bool) -> str | None:
    return _opt_value(q, "Yes" if yes else "No")


# EEO / demographic questions — NEVER AI-guessed. Default to the "decline" option.
_RE_EEO = re.compile(
    r"gender|pronoun|\brace\b|ethnic|hispanic|latino|veteran|disabilit|"
    r"sexual orientation|self.?identif|transgender", re.I)


def _snap_label(q: FormQuestion, text: str) -> str | None:
    """Return the OPTION LABEL matching `text` (exact, else case-insensitive, else
    contains). None if no option matches — so we never put a non-option value in a select."""
    if not q.options:
        return text
    t = str(text or "").strip().lower()
    if not t:
        return None
    for o in q.options:
        if str(o.get("label", "")).strip().lower() == t:
            return o.get("label")
    for o in q.options:
        lab = str(o.get("label", "")).strip().lower()
        if t in lab or lab in t:
            return o.get("label")
    return None


def _decline_label(q: FormQuestion) -> str | None:
    """The 'decline to self-identify' / 'prefer not to say' option label, if present."""
    for o in q.options:
        lab = str(o.get("label", "")).lower()
        if any(k in lab for k in ("decline", "prefer not", "don't wish", "do not wish",
                                  "not to answer", "wish not", "i don't want", "rather not")):
            return o.get("label")
    return None


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

    # Preferred / first name (very common)
    if "preferred" in label and "name" in label:
        return mk(p.full_name.split()[0] if p.full_name else "")

    # Conditional follow-ups ("If you answered Yes above, explain...") — don't blindly
    # answer; leave blank (skipped) and flag only if it's required.
    if re.match(r"\s*if (you |your |applicable|yes|no|selected|the answer|so)", label):
        return mk("", conf=0.0, human=bool(q.required))

    # "How did you hear / first learn about us" (very common) — use the answer-bank value,
    # else a sensible default, snapped to a real option when it's a dropdown.
    if "how did you hear" in label or "how did you first learn" in label or "how were you referred" in label:
        pref = (p.answer_bank or {}).get("how_heard")
        if q.options:
            lab = (_snap_label(q, pref) if pref else None) or _snap_label(q, "LinkedIn") \
                  or _snap_label(q, "Job Board") or _snap_label(q, "Company Website") \
                  or _snap_label(q, "Indeed") or _snap_label(q, "Other")
            return mk(lab) if lab else mk("", conf=0.3, human=True)
        return mk(pref or "Online job board")

    # Country selects (e.g. "country you anticipate working from") — we are US-only.
    if q.options and "country" in label:
        lab = _snap_label(q, "United States") or _snap_label(q, "USA") or _snap_label(q, "US")
        if lab:
            return mk(lab)

    # "Have you previously worked/been employed here" — default No (recruiter can edit).
    if ("previously" in label or "currently" in label) and ("employ" in label or "worked for" in label):
        if q.options:
            lab = _snap_label(q, "No") or next(
                (o.get("label") for o in q.options
                 if any(k in str(o.get("label", "")).lower() for k in ("not ", "never", "no,"))), None)
            if lab:
                return mk(lab)
        else:
            return mk("No")

    # EEO / demographic — NEVER AI-guessed. Use candidate's stated pref, else "Decline".
    if _RE_EEO.search(label):
        pref = p.eeo.get(label) or p.eeo.get("default")
        lab = (_snap_label(q, pref) if pref else None) or _decline_label(q)
        if lab:
            return mk(lab)
        return mk("", conf=0.0, human=True)   # no decline option -> let a human handle it

    # Hard immigration facts — NEVER AI-guessed. Store the LABEL (Yes/No), snapped to the
    # form's actual option text. Flag for human if profile lacks the data.
    if "sponsorship" in label or ("visa" in label and "require" in label):
        v = p.work_auth.requires_sponsorship
        if v is None:
            return mk("", conf=0.0, human=True)
        ans = "Yes" if v else "No"
        return mk(_snap_label(q, ans) or ans if q.options else ans)
    if "authorized to work" in label or "legally authorized" in label:
        v = p.work_auth.authorized_us
        if v is None:
            return mk("", conf=0.0, human=True)
        ans = "Yes" if v else "No"
        return mk(_snap_label(q, ans) or ans if q.options else ans)

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
    "You answer a single job-application question for a specific candidate. You are given "
    "the candidate's profile and an optional ANSWER BANK (things the recruiter knows about "
    "them). Use the answer bank as KNOWLEDGE to understand the candidate — do NOT copy it "
    "verbatim. Intelligently COMPOSE an answer tailored to THIS exact question and THIS "
    "company/job: adapt wording, pick what's relevant, keep it concise and professional. "
    "Stay strictly truthful — never invent facts not supported by the profile or answer bank. "
    "If you don't have enough to answer confidently, say so with low confidence. "
    'Return JSON: {"answer": str, "confidence": 0.0-1.0}'
)


def _l3_answer(q: FormQuestion, p: Profile, job: Job) -> Answer:
    bank = "\n".join(f"  - {k}: {v}" for k, v in (p.answer_bank or {}).items()) or "  (none provided)"
    prompt = f"""\
CANDIDATE PROFILE (truth — do not contradict):
{p.model_dump_json(indent=2)}

ANSWER BANK (recruiter-provided knowledge — use intelligently, adapt to the question,
NEVER paste verbatim, NEVER fabricate beyond it):
{bank}

JOB: {job.title} at {job.board}
JOB DESCRIPTION (first 2000 chars):
{(job.content or '')[:2000]}

QUESTION: {q.label}
{"OPTIONS: " + ", ".join(o.get("label","") for o in q.options) if q.options else ""}

Compose the best answer for THIS candidate and THIS specific job/company. Draw on the
answer bank where relevant but tailor it — don't repeat it word-for-word. If multiple-choice,
return the exact option label.
"""
    try:
        data = llm.complete_json(prompt, system=L3_SYSTEM, model=config.MODEL_SMART, max_tokens=600)
        ans_text = str(data.get("answer", "")).strip()
        conf = float(data.get("confidence", 0.6))
    except Exception:
        return Answer(label=q.label, field_names=q.field_names, value="",
                      source=AnswerSource.CLAUDE, confidence=0.0, needs_human=True)

    value = ans_text
    if q.options:
        # store the OPTION LABEL (snapped to a real choice) — never a raw value/id, and
        # never free text that isn't an option.
        snapped = _snap_label(q, ans_text)
        value = snapped if snapped is not None else ""
    # Raise a DOUBT for the recruiter only when a REQUIRED question can't be answered
    # confidently. Optional fields we can't fill are just left blank (not a doubt).
    needs_human = bool(q.required) and (not value or conf < 0.5)
    return Answer(label=q.label, field_names=q.field_names, value=value,
                  source=AnswerSource.CLAUDE, confidence=conf, needs_human=needs_human)


# ---------------- Orchestration ----------------

def answer_form(job: Job, profile: Profile, candidate: str,
                *, test_mode: bool = True) -> AnswerSheet:
    """Produce a full answer sheet for one job's form, for one candidate.

    test_mode=True (default while testing) swaps the candidate's real email/phone for
    harmless dummy values so no real inbox/phone is ever contacted. Set False to go live.
    """
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

        # L2 — cached recurring answer (cache stores the LABEL; snap to a valid option)
        key = _cache_key(q.label)
        if key in cache and cache[key]:
            val = cache[key]
            if q.options:
                val = _snap_label(q, val)
            if val:
                sheet.answers.append(Answer(label=q.label, field_names=q.field_names,
                                            value=val, source=AnswerSource.CACHE, confidence=0.9))
                continue

        # L3 — Claude reasoning for new/free-text
        a = _l3_answer(q, profile, job)
        sheet.answers.append(a)
        if a.value and a.confidence >= 0.7:   # remember confident answers (as the label)
            cache[key] = a.value

    _save_cache(candidate, cache)
    if test_mode:
        _sanitize_for_test(sheet, profile)   # never expose real email/phone while testing
    return sheet
