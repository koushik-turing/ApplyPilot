"""Pydantic data models shared across the API.

The Resume shape is what export.py renders and what extract.py produces, so it
is the single source of truth for a resume in this app.
"""
from __future__ import annotations
from pydantic import BaseModel, Field


class Experience(BaseModel):
    title: str = ""
    company: str = ""
    start_date: str = ""
    end_date: str = ""
    bullets: list[str] = Field(default_factory=list)


class Education(BaseModel):
    degree: str = ""
    institution: str = ""
    year: str = ""


class Resume(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[str] = Field(default_factory=list)
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)


class JobDescription(BaseModel):
    title: str = ""
    raw: str = ""
    keywords: list[str] = Field(default_factory=list)        # all skills/terms (union)
    must_have: list[str] = Field(default_factory=list)        # the most important ones
    hard_skills: list[str] = Field(default_factory=list)      # weighted most by ATS
    soft_skills: list[str] = Field(default_factory=list)      # weighted least
    other_keywords: list[str] = Field(default_factory=list)   # frequent domain terms


class SubScore(BaseModel):
    name: str
    score: int            # 0-100 for this dimension
    weight: float         # contribution to the overall score (0-1)
    detail: str = ""      # human-readable explanation


class AiReview(BaseModel):
    """A professional, Claude-generated qualitative review of the resume."""
    verdict: str = ""                                       # one-line overall assessment
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    fixes: list[str] = Field(default_factory=list)          # prioritized, actionable
    ats_tips: list[str] = Field(default_factory=list)       # formatting / parse-ability


class ScoreReport(BaseModel):
    overall: int                                            # 0-100
    rating: str                                             # Excellent / Strong / Fair / Weak
    has_jd: bool                                            # was a job description supplied
    subscores: list[SubScore] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    ai_review: AiReview | None = None                       # added when Claude is available


class TailorResponse(BaseModel):
    tailored_resume: Resume
    changes: list[str]
    score_before: ScoreReport
    score_after: ScoreReport
    ai_used: bool = False
    engine: str = "rule-based"   # 'claude' | 'ollama' | 'rule-based'
