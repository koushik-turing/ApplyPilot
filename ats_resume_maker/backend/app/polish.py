"""Legitimate, non-fabricating resume clean-up applied before rendering/scoring.

This never invents experience or skills. It standardizes what's already there so
the resume isn't penalized by any ATS for cosmetic/parse issues:
  * canonical, correctly-cased skill names (js -> JavaScript, postgres -> PostgreSQL)
  * de-duplicated skills
  * clean bullet formatting (trimmed, single-spaced, capitalized, consistent periods)
  * tidy summary / contact
"""
from __future__ import annotations
import re

from .schemas import Resume

# Canonical, industry-standard display forms (lowercase key -> display form).
_CANON = {
    "javascript": "JavaScript", "js": "JavaScript", "typescript": "TypeScript", "ts": "TypeScript",
    "python": "Python", "java": "Java", "node": "Node.js", "nodejs": "Node.js", "node.js": "Node.js",
    "react": "React", "reactjs": "React", "react.js": "React", "react native": "React Native",
    "angular": "Angular", "vue": "Vue.js", "vue.js": "Vue.js", "next.js": "Next.js", "nextjs": "Next.js",
    "express": "Express.js", "django": "Django", "flask": "Flask", "fastapi": "FastAPI",
    "spring": "Spring", "spring boot": "Spring Boot", "rails": "Ruby on Rails", "laravel": "Laravel",
    ".net": ".NET", "asp.net": "ASP.NET", "jquery": "jQuery", "bootstrap": "Bootstrap",
    "aws": "AWS", "azure": "Azure", "gcp": "GCP", "google cloud": "Google Cloud", "docker": "Docker",
    "kubernetes": "Kubernetes", "k8s": "Kubernetes", "terraform": "Terraform", "ansible": "Ansible",
    "jenkins": "Jenkins", "ci/cd": "CI/CD", "git": "Git", "github": "GitHub", "gitlab": "GitLab",
    "linux": "Linux", "unix": "Unix", "nginx": "Nginx", "bash": "Bash",
    "sql": "SQL", "nosql": "NoSQL", "mysql": "MySQL", "postgresql": "PostgreSQL", "postgres": "PostgreSQL",
    "mongodb": "MongoDB", "redis": "Redis", "sqlite": "SQLite", "oracle": "Oracle",
    "dynamodb": "DynamoDB", "snowflake": "Snowflake", "bigquery": "BigQuery",
    "rest": "REST", "rest api": "REST API", "graphql": "GraphQL", "grpc": "gRPC",
    "html": "HTML", "css": "CSS", "sass": "Sass",
    "machine learning": "Machine Learning", "ml": "Machine Learning", "deep learning": "Deep Learning",
    "nlp": "NLP", "computer vision": "Computer Vision", "tensorflow": "TensorFlow", "pytorch": "PyTorch",
    "keras": "Keras", "scikit-learn": "scikit-learn", "pandas": "pandas", "numpy": "NumPy",
    "opencv": "OpenCV", "spark": "Apache Spark", "hadoop": "Hadoop", "kafka": "Apache Kafka",
    "airflow": "Apache Airflow", "tableau": "Tableau", "power bi": "Power BI", "looker": "Looker",
    "c++": "C++", "c#": "C#", "c": "C", "go": "Go", "golang": "Go", "php": "PHP", "ruby": "Ruby",
    "swift": "Swift", "kotlin": "Kotlin", "scala": "Scala", "rust": "Rust", "r": "R", "matlab": "MATLAB",
    "agile": "Agile", "scrum": "Scrum", "kanban": "Kanban", "jira": "Jira", "tdd": "TDD",
    "selenium": "Selenium", "cypress": "Cypress", "pytest": "pytest", "junit": "JUnit",
    "figma": "Figma", "sketch": "Sketch", "photoshop": "Photoshop", "illustrator": "Illustrator",
    "ui/ux": "UI/UX", "ux": "UX", "ui": "UI", "seo": "SEO", "crm": "CRM", "erp": "ERP", "etl": "ETL",
    "llm": "LLM", "langchain": "LangChain", "hugging face": "Hugging Face", "ios": "iOS",
    "android": "Android", "flutter": "Flutter", "excel": "Excel", "powerpoint": "PowerPoint",
    "salesforce": "Salesforce", "sap": "SAP", "google analytics": "Google Analytics",
}
_ACRONYMS = {"aws", "gcp", "sql", "html", "css", "php", "rest", "api", "sap", "seo", "crm",
             "erp", "etl", "ui", "ux", "qa", "tdd", "ml", "ai", "nlp", "llm", "ios", "sre",
             "cdn", "jwt", "oop", "cli", "sdk", "ide", "json", "xml", "http", "https"}


def canon_skill(s: str) -> str:
    key = s.strip().lower()
    if key in _CANON:
        return _CANON[key]
    # Otherwise: Title-Case words, but keep known acronyms upper-case.
    out: list[str] = []
    for tok in re.split(r"(\s+|/|-)", s.strip()):
        lw = tok.lower()
        if lw in _ACRONYMS:
            out.append(tok.upper())
        elif tok.strip() in ("", "/", "-"):
            out.append(tok)
        else:
            out.append(tok[:1].upper() + tok[1:])
    return "".join(out)


# Canonicalizing tech terms INSIDE prose (bullets/summary) is great for looks, but
# it's dangerous: some skill tokens are ordinary English words, and some canonical
# forms CONTAIN their own trigger (node -> "Node.js" re-introduces ".js"; kafka ->
# "Apache Kafka" re-introduces "kafka"). Applied repeatedly that produced garbage
# like "Node.JavaScript.JavaScript.JavaScript" and "Apache Apache Kafka".
#
# Two safeguards below make canonicalization correct and idempotent:
#   1. Only standalone terms of length >= 3 (drops ambiguous js/ts/go/ml/ai/r/c).
#   2. A FIXED-POINT filter: a term is kept only if applying the whole map to its
#      own canonical value leaves it unchanged. This automatically drops every
#      self-referential / compound-fragmenting term (node, vue, kafka, airflow, …),
#      so the pass can never cascade or duplicate.
_DENY_IN_TEXT = {"go", "c", "r", "d", "rest", "spring", "spark", "rust", "ml", "ai"}
_PROSE_RAW = {k: v for k, v in _CANON.items() if k not in _DENY_IN_TEXT and len(k) >= 3}
_PROSE_RAW.update({"apis": "APIs", "api": "API",
                   "rest apis": "REST APIs", "rest api": "REST API"})  # unambiguous bigrams


def _bounded(keys: list[str]) -> re.Pattern:
    # '.' counts as a boundary so compounds like "node.js" match as a whole.
    return re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(k) for k in keys) +
                      r")(?![A-Za-z0-9])", re.IGNORECASE)


def _build_prose_map(raw: dict[str, str]) -> dict[str, str]:
    """Keep only idempotent, non-fragmenting terms (see note above)."""
    terms = dict(raw)
    for _ in range(6):
        keys = sorted(terms, key=len, reverse=True)
        pat = _bounded(keys)
        bad = [k for k, v in terms.items()
               if pat.sub(lambda m: terms[m.group(0).lower()], v) != v]
        if not bad:
            break
        for k in bad:
            terms.pop(k, None)
    return terms


_PROSE_MAP = _build_prose_map(_PROSE_RAW)
_PROSE_RE = _bounded(sorted(_PROSE_MAP, key=len, reverse=True))


def canonicalize_text(text: str) -> str:
    """Capitalize clearly-technical terms in free text (django -> Django, aws -> AWS),
    in a SINGLE idempotent pass. Skips ambiguous English words and any term whose
    canonical form would re-trigger, so it never corrupts compounds like Node.js."""
    if not text:
        return text
    return _PROSE_RE.sub(lambda m: _PROSE_MAP[m.group(0).lower()], text)


def normalize_phone(raw: str) -> str:
    """Render a phone number in a clean, ATS-safe format.

    Recovers from upstream parse glitches (e.g. extra leading digits captured from
    an address) by formatting the canonical US 10-digit number. Keeps explicit
    international (+CC) numbers intact.
    """
    if not raw:
        return raw
    s = raw.strip()
    has_plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)

    if not has_plus:
        # US/Canada: format the last 10 digits (drops junk leading digits if any).
        if len(digits) >= 10:
            d = digits[-10:]
            return f"({d[0:3]}) {d[3:6]}-{d[6:]}"
    else:
        if len(digits) == 11 and digits[0] == "1":          # +1 (US/Canada)
            d = digits[1:]
            return f"+1 ({d[0:3]}) {d[3:6]}-{d[6:]}"
        if 11 <= len(digits) <= 15:                          # generic international
            cc, rest = digits[:len(digits) - 10], digits[-10:]
            return f"+{cc} {rest[0:3]} {rest[3:6]} {rest[6:]}"

    # Fallback: just tidy whatever we have (don't guess).
    cleaned = re.sub(r"\s+", " ", re.sub(r"[^\d+().\- ]", "", s)).strip()
    return cleaned or s


def clean_bullet(b: str) -> str:
    t = re.sub(r"\s+", " ", b.strip().lstrip("-*•·").strip())
    if not t:
        return ""
    t = canonicalize_text(t)
    t = t[0].upper() + t[1:]
    if t[-1] not in ".!?":
        t += "."
    return t


def polish_resume(r: Resume) -> tuple[Resume, list[str]]:
    p = r.model_copy(deep=True)
    notes: list[str] = []

    # --- skills: canonical names, de-duplicated (case-insensitive) ---
    seen: set[str] = set()
    skills: list[str] = []
    for s in p.skills:
        c = canon_skill(s)
        if c and c.lower() not in seen:
            seen.add(c.lower())
            skills.append(c)
    if skills != p.skills:
        notes.append("Standardized skill names to industry-recognized forms and removed duplicates.")
    p.skills = skills

    # --- contact tidy ---
    if p.email:
        p.email = p.email.strip().lower()
    if p.phone:
        p.phone = normalize_phone(p.phone)
    if p.name:
        p.name = re.sub(r"\s+", " ", p.name).strip()

    # --- bullets / summary / lists ---
    bullets_changed = False
    for e in p.experience:
        cleaned = [clean_bullet(b) for b in e.bullets if b.strip()]
        if cleaned != e.bullets:
            bullets_changed = True
        e.bullets = cleaned
        e.title = e.title.strip()
        e.company = e.company.strip()
    if bullets_changed:
        notes.append("Cleaned bullet formatting (spacing, capitalization, consistent punctuation).")

    if p.summary:
        p.summary = canonicalize_text(re.sub(r"\s+", " ", p.summary).strip())
    p.certifications = [re.sub(r"\s+", " ", c).strip() for c in p.certifications if c.strip()]
    p.projects = [re.sub(r"\s+", " ", x).strip() for x in p.projects if x.strip()]

    return p, notes
