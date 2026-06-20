"""
Personalized job-fit scorer — UNIQUE per candidate, driven by their profile.

Generalizes the proven Sai scorer (A_skill + B_role + C_exp + D_stack - penalties) so the
weights/skills come from EACH candidate's profile.json instead of being hardcoded.

Two stages (as designed):
  * Stage 1 (coarse, while crawling): quick keyword relevance to shortlist candidates' jobs.
  * Stage 2 (final, after fetching full JD): the multi-signal Final_Matching_Score below.

    Final_Matching_Score = clamp(0, 100, A_skill + B_role + C_exp + D_stack - penalties)
      A_skill (0-50)  coverage of the CANDIDATE'S skills the JD asks for
      B_role  (0-22)  JD title fit to the candidate's target titles / role history
      C_exp   (0-13)  JD required years vs the candidate's years
      D_stack (-15..+15) JD's primary language is one the candidate knows (else penalty)
      penalties        clearance/citizenship, no-sponsorship, seniority-creep, domain mismatch
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Profile

# Known programming languages (to judge stack fit). Lowercase canonical.
_LANGS = {
    "python", "java", "javascript", "typescript", "go", "golang", "rust", "ruby",
    "php", "scala", "kotlin", "swift", "c#", "c++", "elixir", "perl", "r",
}
# Languages that, if they dominate a JD the candidate doesn't know, signal wrong-stack.
_LANG_PATTERNS = {
    "go": r"\bgolang\b|\bgo\b(?=.{0,40}(developer|engineer|services|backend))",
    "rust": r"\brust\b", "ruby": r"\bruby\b|rails", "elixir": r"\belixir\b|phoenix",
    "php": r"\bphp\b|laravel", "scala": r"\bscala\b", "c#": r"\bc#\b|\.net\b|asp\.net",
    "c++": r"\bc\+\+\b", "kotlin": r"\bkotlin\b", "swift": r"\bswift\b(?! ?ui app)",
    "perl": r"\bperl\b",
}

_RE_CLEARANCE = re.compile(
    r"security clearance|active clearance|ts/sci|secret clearance|polygraph|"
    r"must be a u\.?s\.? citizen|u\.?s\.? citizenship (is )?required|requires? u\.?s\.? citizenship", re.I)
_RE_NO_SPONSOR = re.compile(
    r"(will not|cannot|unable to|do not|does not|no)\s+(provide|offer|sponsor).{0,30}sponsor|"
    r"without (the need for )?sponsorship|not (able|eligible) to sponsor|no visa sponsorship", re.I)
_RE_SENIOR = re.compile(r"\b(staff|principal|distinguished|architect)\b|\b(8|9|10|11|12)\+?\s*years|\b1[0-5]\s*years", re.I)
_RE_ROLE_HEAD = re.compile(
    r"engineer|developer|manager|analyst|designer|scientist|architect|consultant|"
    r"specialist|administrator|coordinator|director|programmer|recruiter|marketer|"
    r"accountant|nurse|teacher|writer|strategist", re.I)
# Titles that LOOK technical (contain engineer/specialist/architect) but are actually
# sales / pre-sales / non-engineering — a wrong role family for a software candidate.
_RE_NONTECH = re.compile(
    r"\b(sales|account executive|account manager|business development|customer success|"
    r"solutions engineer|sales engineer|pre[- ]?sales|sales specialist|partner|"
    r"recruiter|recruiting|marketing|support engineer)\b", re.I)


# Generic words inside a skill phrase that shouldn't be matched alone (too common in JDs).
_GENERIC = {
    "apis", "api", "platform", "oriented", "architecture", "security", "cloud", "services",
    "service", "framework", "tools", "tool", "management", "development", "design", "systems",
    "system", "data", "web", "software", "engineering", "programming", "advanced", "modern",
}
# Common alias expansions so a candidate's phrasing matches the JD's phrasing.
_ALIASES = {
    "restful apis": ["rest", "restful", "rest api"], "rest": ["rest", "restful"],
    "node.js": ["node", "node.js", "nodejs"], "express.js": ["express"],
    "google cloud platform": ["gcp", "google cloud"], "kubernetes": ["kubernetes", "k8s"],
    "ci/cd": ["ci/cd", "cicd", "continuous integration"], "java spring boot": ["java", "spring", "spring boot"],
    "spring security": ["spring security", "spring"], "aws sns/sqs": ["sns", "sqs"],
    "swagger/openapi": ["swagger", "openapi"], "service-oriented architecture": ["soa", "microservices"],
    "angular material": ["angular material", "angular"], "amazon web services": ["aws"],
}


@dataclass
class CandidateMatcher:
    """Pre-compiled, profile-derived signals used to score any job for this candidate."""
    skill_patterns: dict[str, re.Pattern] = field(default_factory=dict)
    role_tokens: set[str] = field(default_factory=set)     # e.g. {full, stack, backend, software}
    role_heads: set[str] = field(default_factory=set)      # e.g. {engineer, developer}
    years: float | None = None
    langs: set[str] = field(default_factory=set)           # languages the candidate knows
    needs_sponsorship: bool | None = None
    skill_target: int = 8                                  # finding this many skills = full A


def _skill_tokens(skill: str) -> list[str]:
    """Matchable tokens for a skill phrase: aliases, the full phrase, and significant words."""
    low = skill.lower().strip()
    toks = set(_ALIASES.get(low, []))
    toks.add(low)
    for w in re.split(r"[\s/]+", low):
        w = w.strip(".")
        if len(w) >= 3 and w not in _GENERIC:
            toks.add(w)
    return [t for t in toks if t]


def _skill_pattern(skill: str) -> re.Pattern:
    """A regex that matches the skill via any of its tokens (word-boundaried)."""
    alts = sorted({re.escape(t) for t in _skill_tokens(skill)}, key=len, reverse=True)
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(alts) + r")(?![A-Za-z0-9])")


def build_matcher(profile: Profile) -> CandidateMatcher:
    """Derive a per-candidate matcher from their profile (skills, titles, years, auth)."""
    patterns: dict[str, re.Pattern] = {}
    for s in profile.skills:
        s = s.strip()
        if not s:
            continue
        patterns[s.lower()] = _skill_pattern(s)

    role_tokens: set[str] = set()
    role_heads: set[str] = set()
    titles = list(profile.target_titles) + [e.title for e in profile.experience]
    for t in titles:
        for w in re.findall(r"[a-z]+", t.lower()):
            if _RE_ROLE_HEAD.fullmatch(w):
                role_heads.add(w)
            elif len(w) > 2 and w not in {"and", "the", "for"}:
                role_tokens.add(w)

    skill_toks = {tok for s in profile.skills for tok in _skill_tokens(s)}
    langs = {l for l in _LANGS if l in skill_toks}
    # Finding ~6 of the candidate's skills in a JD = full skill credit (more skills in the
    # profile should NOT make a good match harder to reach).
    target = 6
    return CandidateMatcher(
        skill_patterns=patterns, role_tokens=role_tokens, role_heads=role_heads,
        years=profile.years_experience, langs=langs,
        needs_sponsorship=profile.work_auth.requires_sponsorship, skill_target=target,
    )


def _min_years(text: str) -> int | None:
    mins = []
    for p in (r'(\d+)\s*\+\s*years', r'(\d+)\s*[-–to]+\s*(\d+)\s*years',
              r'at least\s*(\d+)\s*years', r'minimum\s*of\s*(\d+)\s*years',
              r'(\d+)\s*years', r'(\d+)\s*yrs'):
        for m in re.finditer(p, text, re.I):
            ns = [int(g) for g in m.groups() if g]
            if ns:
                mins.append(min(ns))
    return min(mins) if mins else None


def _a_skill(m: CandidateMatcher, text: str) -> tuple[float, list[str], list[str]]:
    hit = [s for s, pat in m.skill_patterns.items() if pat.search(text)]
    cov = min(1.0, len(hit) / m.skill_target) if m.skill_target else 0.0
    missing = []  # JD-required skills the candidate lacks are computed at the JD level elsewhere
    return round(cov * 50, 1), hit, missing


def _b_role(m: CandidateMatcher, title: str) -> int:
    t = title.lower()
    if _RE_NONTECH.search(t):
        return 2                      # sales/pre-sales/support — wrong role family
    head_hit = any(h in t for h in m.role_heads)
    tok_hits = sum(1 for tok in m.role_tokens if re.search(r"(?<![a-z])" + re.escape(tok) + r"(?![a-z])", t))
    if not head_hit and tok_hits == 0:
        return 6                      # unrelated role
    score = 9 if head_hit else 7      # base for a matching role family
    score += min(13, tok_hits * 5)    # specialty tokens (full/stack/backend/frontend...)
    return min(22, score)


def _c_exp(m: CandidateMatcher, jd_min: int | None) -> int:
    if m.years is None or jd_min is None:
        return 8
    y = m.years
    if jd_min <= y + 1 and jd_min >= y - 3:      # comfortably within band
        return 13
    if jd_min <= y + 3:                           # slightly stretches up
        return 10
    if jd_min <= y + 5:
        return 6
    return 3                                       # JD wants far more years


def _d_stack(m: CandidateMatcher, text: str) -> tuple[int, list[str]]:
    foreign = [l for l, p in _LANG_PATTERNS.items() if l not in m.langs and re.search(p, text, re.I)]
    knows = sum(1 for l in m.langs if re.search(r"(?<![A-Za-z0-9])" + re.escape(l) + r"(?![A-Za-z0-9])", text))
    if knows >= 2 and not foreign:
        return 15, foreign
    if knows >= 1 and len(foreign) <= 1:
        return 8, foreign
    if knows == 0 and foreign:
        return -15, foreign
    if foreign:
        return -6, foreign
    return 4, foreign


def score_job(m: CandidateMatcher, title: str, jd_text: str | None) -> dict:
    """Final_Matching_Score for one job, personalized to the candidate. Works in both
    stages: a short/empty jd_text just yields lower confidence."""
    text = (title + "\n" + (jd_text or "")).lower()
    A, hit, _ = _a_skill(m, text)
    B = _b_role(m, title)
    jd_min = _min_years(text)
    C = _c_exp(m, jd_min)
    D, foreign = _d_stack(m, text)

    flags, pen = [], 0
    if _RE_NONTECH.search(title.lower()):
        # tech-company sales/support JDs name the candidate's skills (high A_skill) but the
        # ROLE is wrong — penalize hard so keyword overlap can't carry a non-engineering job.
        flags.append("non-engineering role (sales/pre-sales/support)"); pen += 28
    if _RE_CLEARANCE.search(text):
        flags.append("clearance/US-citizen required"); pen += 35
    if m.needs_sponsorship and _RE_NO_SPONSOR.search(text):
        flags.append("no visa sponsorship (candidate needs it)"); pen += 30
    elif _RE_NO_SPONSOR.search(text):
        flags.append("no visa sponsorship"); pen += 8
    if _RE_SENIOR.search(text):
        flags.append("senior/8+yr signals in JD"); pen += 12
    if foreign and not m.langs.intersection({"python", "java", "javascript", "typescript"}):
        flags.append("primary stack: " + ",".join(foreign))

    final = max(0.0, min(100.0, round(A + B + C + D - pen, 1)))
    n = len(jd_text or "")
    conf = "high" if n >= 600 else "med" if n >= 150 else "low"
    return {
        "final": final, "A_skill": A, "B_role": B, "C_exp": C, "D_stack": D, "penalty": pen,
        "min_years_req": jd_min, "skills_hit": hit, "red_flags": flags,
        "confidence": conf, "jd_chars": n,
    }


def coarse_match(m: CandidateMatcher, title: str, snippet: str = "") -> int:
    """Stage-1 fast filter: a quick 0-100 relevance from title + any available text,
    cheap enough to run on thousands of jobs during the crawl."""
    return int(score_job(m, title, snippet or None)["final"])
