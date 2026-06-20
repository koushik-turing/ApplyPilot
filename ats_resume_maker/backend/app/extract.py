"""Heuristic parser: raw resume text -> structured Resume; JD text -> JobDescription.

No AI required. It splits the resume into standard sections by detecting headings,
then pulls contact details with regex and skills via the shared gazetteer.
"""
from __future__ import annotations
import re

from .schemas import Resume, Experience, Education, JobDescription
from . import keywords

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Standard phone shape: optional +country, then 3-3-4 with spaces/dots/dashes/parens.
# Anchored to the digit groups so it can't swallow stray leading digits from an address.
PHONE = re.compile(
    r"(?<![\d.])(?:\+?\d{1,3}[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?![\d])"
)
URL = re.compile(r"((?:https?://|www\.)[^\s,]+|(?:linkedin\.com|github\.com)/[^\s,]+)", re.I)

# Heading text -> canonical section name.
SECTION_ALIASES = {
    "summary": ("summary", "objective", "profile", "professional summary", "about me", "about"),
    "skills": ("skills", "technical skills", "core competencies", "technologies",
               "technical proficiencies", "areas of expertise"),
    "experience": ("experience", "work experience", "professional experience",
                   "employment", "employment history", "work history", "career history"),
    "education": ("education", "academic background", "academics"),
    "certifications": ("certifications", "certification", "certificates", "licenses",
                       "courses", "training"),
    "projects": ("projects", "personal projects", "academic projects", "key projects"),
}

_HEADING_LOOKUP = {alias: canon for canon, aliases in SECTION_ALIASES.items() for alias in aliases}
_DATE = re.compile(
    r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{4}|\d{4}|present|current)",
    re.I,
)


def _is_heading(line: str) -> str | None:
    s = line.strip().lower().rstrip(":")
    if not s or len(s) > 40:
        return None
    return _HEADING_LOOKUP.get(s)


def _split_sections(text: str) -> tuple[list[str], dict[str, list[str]]]:
    """Return (header_lines_before_first_section, {section: [lines]})."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    header: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for ln in lines:
        canon = _is_heading(ln)
        if canon:
            current = canon
            sections.setdefault(current, [])
            continue
        if current is None:
            header.append(ln)
        else:
            sections[current].append(ln)
    return header, sections


def parse_resume(text: str) -> Resume:
    header, sections = _split_sections(text)
    r = Resume()

    # --- contact details: search the whole document, prefer the header block ---
    whole = "\n".join([*header, *(l for v in sections.values() for l in v)])
    if m := EMAIL.search(whole):
        r.email = m.group(0)
    if m := PHONE.search(whole):
        r.phone = m.group(0).strip()
    r.links = list(dict.fromkeys(URL.findall(text)))[:4]

    # --- name: first non-empty header line that isn't contact info ---
    for ln in header:
        s = ln.strip()
        if s and not EMAIL.search(s) and not PHONE.search(s) and not URL.search(s):
            if 2 <= len(s) <= 50 and "," not in s[:3]:
                r.name = s
                break

    # --- location: a header line with a comma that isn't the name/contact ---
    for ln in header:
        s = ln.strip()
        if s and s != r.name and "," in s and not EMAIL.search(s) and not URL.search(s):
            if len(s) <= 60:
                r.location = s
                break

    # --- summary ---
    if "summary" in sections:
        r.summary = " ".join(l.strip() for l in sections["summary"] if l.strip()).strip()

    # --- skills: gazetteer hits in the skills section, else across whole resume ---
    skills_text = "\n".join(sections.get("skills", [])) or whole
    found = keywords.find_skills(skills_text)
    # also keep explicit comma/bullet separated items from a skills section
    if "skills" in sections:
        for line in sections["skills"]:
            # split on commas / bullets / pipes / 2+ spaces — but NOT on '/', so
            # compound skills like CI/CD, UI/UX, TCP/IP stay intact.
            for part in re.split(r"[,•|·]|\s{2,}", line):
                p = part.strip(" .\t-")
                if 2 <= len(p) <= 30 and p.lower() not in (s.lower() for s in found):
                    if p and not p.isdigit():
                        found.append(p)
    r.skills = list(dict.fromkeys(found))[:40]

    # --- experience ---
    r.experience = _parse_experience(sections.get("experience", []))

    # --- education: split degree | institution | year so nothing is duplicated ---
    for line in sections.get("education", []):
        s = line.strip(" -•\t")
        if not s:
            continue
        year = ""
        if m := _DATE.search(s):
            year = m.group(0)
        rest = re.sub(r"\s{2,}", " ", _DATE.sub("", s)).strip(" -–—,|")
        parts = re.split(r"\s+[—–-]\s+|,\s+", rest, maxsplit=1)
        degree = parts[0].strip()
        institution = parts[1].strip() if len(parts) > 1 else ""
        r.education.append(Education(degree=degree, institution=institution, year=year))

    # --- certifications / projects ---
    r.certifications = [l.strip(" -•\t") for l in sections.get("certifications", []) if l.strip()]
    r.projects = [l.strip(" -•\t") for l in sections.get("projects", []) if l.strip()]

    return r


def _parse_experience(lines: list[str]) -> list[Experience]:
    exps: list[Experience] = []
    current: Experience | None = None
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        is_bullet = bool(re.match(r"^[\s]*[-•*•]", line))
        if is_bullet and current is not None:
            current.bullets.append(stripped.lstrip("-•*• ").strip())
            continue
        # A non-bullet line starts a new role. Try to split "Title — Company   dates".
        if current is not None:
            exps.append(current)
        title, company, start, end = _split_role(stripped)
        current = Experience(title=title, company=company, start_date=start, end_date=end)
    if current is not None:
        exps.append(current)
    return exps


def _split_role(s: str) -> tuple[str, str, str, str]:
    dates = _DATE.findall(s)
    start = dates[0] if dates else ""
    end = dates[1] if len(dates) > 1 else ""
    head = _DATE.sub("", s).strip(" -–—,|")
    parts = re.split(r"\s+[—–-]\s+|\s+\|\s+|\s+at\s+|,\s+", head, maxsplit=1)
    title = parts[0].strip() if parts else head
    company = parts[1].strip() if len(parts) > 1 else ""
    return title, company, start, end


def parse_jd(text: str) -> JobDescription:
    a = keywords.analyze_jd(text)
    union = list(dict.fromkeys([*a["hard"], *a["soft"], *a["other"]]))
    return JobDescription(
        title=a["title"], raw=text,
        keywords=union, must_have=a["hard"][:8],
        hard_skills=a["hard"], soft_skills=a["soft"], other_keywords=a["other"],
    )
