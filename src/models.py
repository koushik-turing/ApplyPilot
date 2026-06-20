"""Data models for the portal — the shared vocabulary across all modules."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ---------------- Candidate profile (output of M1) ----------------

class WorkAuth(BaseModel):
    """Hard immigration/work facts — answered deterministically, NEVER AI-guessed."""
    authorized_us: bool | None = None          # legally authorized to work in US now?
    requires_sponsorship: bool | None = None   # needs visa sponsorship now/future?
    visa_status: str = ""                       # e.g. "F-1 OPT", "H-1B", "US Citizen", "GC"
    needs_relocation_ok: bool | None = None


class Experience(BaseModel):
    company: str
    title: str
    start: str = ""
    end: str = ""
    bullets: list[str] = Field(default_factory=list)


class Profile(BaseModel):
    """Structured candidate profile. resume_facts are frozen to prevent hallucination."""
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""

    years_experience: float | None = None
    target_titles: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)

    work_auth: WorkAuth = Field(default_factory=WorkAuth)
    desired_salary: str = ""
    preferred_locations: list[str] = Field(default_factory=list)
    open_to_remote: bool | None = None

    # EEO / voluntary self-id defaults (candidate's stated preference, else "Decline")
    eeo: dict[str, str] = Field(default_factory=dict)

    # Optional answer KNOWLEDGE bank — whatever the recruiter knows about the candidate
    # (relocation, start date, why-interested notes, references, etc.). Partial is fine.
    # The answer engine uses this as KNOWLEDGE to compose form answers intelligently
    # (adapt to the question/company) — it is NOT copy-pasted verbatim.
    answer_bank: dict[str, str] = Field(default_factory=dict)

    # Frozen ground-truth: exact companies/titles/metrics the AI must never alter.
    resume_facts: dict[str, str] = Field(default_factory=dict)


# ---------------- Jobs & forms (M2 / ATS) ----------------

class FormQuestion(BaseModel):
    label: str
    required: bool = False
    field_type: str = ""                       # input_text, textarea, multi_value_single_select...
    field_names: list[str] = Field(default_factory=list)
    options: list[dict] = Field(default_factory=list)   # [{label, value}]


class Job(BaseModel):
    board: str
    job_id: str
    title: str = ""
    location: str = ""
    url: str = ""
    content: str = ""
    questions: list[FormQuestion] = Field(default_factory=list)
    fit_score: int | None = None               # 1-10 (M3)
    sponsors_h1b: bool | None = None           # from USCIS data layer


# ---------------- Answers (output of M4) ----------------

class AnswerSource(str, Enum):
    DETERMINISTIC = "deterministic"   # L1 — straight from profile
    CACHE = "cache"                   # L2 — reused
    CLAUDE = "claude"                 # L3 — AI reasoning


class Answer(BaseModel):
    label: str
    field_names: list[str]
    value: str                        # for selects, this is the option *value/id*
    source: AnswerSource
    confidence: float = 1.0
    needs_human: bool = False


class AnswerSheet(BaseModel):
    job_id: str
    answers: list[Answer] = Field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return any(a.needs_human for a in self.answers)


# ---------------- Application status pipeline (M3) ----------------

class Status(str, Enum):
    FOUND = "found"
    MATCHED = "matched"
    QUEUED = "queued"
    FILLING = "filling"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CAPTCHA = "captcha"
    SKIPPED = "skipped"
