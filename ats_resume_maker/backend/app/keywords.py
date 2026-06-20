"""Shared keyword + skill extraction used by both the parser and the scorer.

A real ATS leans heavily on a skills taxonomy. We keep a curated gazetteer of
common hard skills/tools plus a generic noun-phrase extractor so we still catch
domain terms that aren't in the list.
"""
from __future__ import annotations
import re

# A pragmatic, multi-domain gazetteer. Lowercase. Multi-word entries are matched
# as phrases. Extend freely — bigger list = better keyword recall.
SKILLS: set[str] = {
    # programming languages
    "python", "java", "javascript", "typescript", "c", "c++", "c#", "go", "golang",
    "rust", "ruby", "php", "swift", "kotlin", "scala", "r", "matlab", "perl", "dart",
    "objective-c", "bash", "shell", "powershell", "sql", "nosql", "html", "css",
    # web / frameworks
    "react", "react native", "angular", "vue", "vue.js", "next.js", "nuxt", "svelte",
    "node", "node.js", "express", "django", "flask", "fastapi", "spring", "spring boot",
    "rails", "laravel", ".net", "asp.net", "jquery", "bootstrap", "tailwind", "redux",
    "graphql", "rest", "rest api", "grpc", "websocket", "microservices",
    # data / ml / ai
    "machine learning", "deep learning", "nlp", "natural language processing",
    "computer vision", "data science", "data analysis", "data engineering",
    "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "keras", "opencv",
    "spark", "hadoop", "kafka", "airflow", "etl", "tableau", "power bi", "looker",
    "statistics", "regression", "classification", "clustering", "llm", "generative ai",
    "prompt engineering", "langchain", "hugging face", "transformers",
    # cloud / devops
    "aws", "azure", "gcp", "google cloud", "docker", "kubernetes", "terraform",
    "ansible", "jenkins", "ci/cd", "github actions", "gitlab", "git", "linux", "unix",
    "nginx", "redis", "rabbitmq", "elasticsearch", "prometheus", "grafana", "helm",
    "serverless", "lambda", "ec2", "s3", "cloudformation", "devops", "sre",
    # databases
    "mysql", "postgresql", "postgres", "mongodb", "sqlite", "oracle", "sql server",
    "dynamodb", "cassandra", "firebase", "snowflake", "bigquery", "redshift",
    # mobile
    "android", "ios", "flutter", "xamarin",
    # testing / methods
    "agile", "scrum", "kanban", "jira", "tdd", "unit testing", "selenium", "cypress",
    "pytest", "junit", "playwright", "qa", "automation testing", "jest", "vitest",
    "mocha", "jasmine", "enzyme", "testing library", "webpack", "vite", "babel",
    "eslint", "prettier", "storybook", "sass", "less", "tailwind css", "material ui",
    "mui", "styled-components", "webdriver",
    # design / product
    "figma", "sketch", "adobe xd", "photoshop", "illustrator", "ui/ux", "ux", "ui",
    "wireframing", "prototyping", "user research",
    # business / general
    "project management", "product management", "stakeholder management",
    "communication", "leadership", "teamwork", "problem solving", "analytical",
    "time management", "negotiation", "presentation", "budgeting", "forecasting",
    "salesforce", "sap", "excel", "powerpoint", "word", "google analytics", "seo",
    "marketing", "digital marketing", "content marketing", "crm", "erp",
    "accounting", "finance", "auditing", "business analysis", "operations",
    # ---- cross-domain professional skills (so ANY profession scores well) ----
    # marketing / sales
    "sem", "google ads", "facebook ads", "social media marketing", "email marketing",
    "copywriting", "brand management", "market research", "hubspot", "marketo",
    "mailchimp", "canva", "wordpress", "shopify", "lead generation", "cold calling",
    "account management", "b2b", "b2c", "pipeline management", "upselling", "ppc",
    "campaign management", "go-to-market", "public relations", "influencer marketing",
    # finance / accounting
    "financial modeling", "financial analysis", "financial reporting", "bookkeeping",
    "quickbooks", "gaap", "ifrs", "taxation", "accounts payable", "accounts receivable",
    "payroll", "variance analysis", "valuation", "investment analysis", "risk management",
    "fp&a", "reconciliation", "cost accounting", "treasury", "tally",
    # hr / recruiting
    "recruiting", "talent acquisition", "onboarding", "employee relations", "hris",
    "workday", "performance management", "compensation", "benefits administration",
    "sourcing", "applicant tracking", "succession planning",
    # healthcare
    "patient care", "ehr", "emr", "hipaa", "clinical", "nursing", "phlebotomy",
    "medical coding", "icd-10", "cpr", "patient assessment", "medication administration",
    # operations / supply chain / pm
    "six sigma", "lean", "supply chain", "logistics", "inventory management",
    "procurement", "vendor management", "process improvement", "kpi", "okrs",
    "change management", "risk assessment", "quality assurance", "iso", "pmp",
    # design / creative
    "indesign", "after effects", "premiere pro", "ux research", "user testing",
    "branding", "typography", "motion graphics", "video editing", "3d modeling",
    # data / analytics / general office
    "data visualization", "reporting", "dashboards", "data entry", "google workspace",
    "microsoft office", "outlook", "sharepoint", "visio", "notion", "asana", "trello",
    "slack", "zoom", "customer service", "client relations", "training", "coaching",
    "writing", "editing", "research", "public speaking", "event management",
}

# Sort longest-first so multi-word skills match before their single-word parts.
_SKILLS_SORTED = sorted(SKILLS, key=len, reverse=True)

STOPWORDS: set[str] = {
    "the", "a", "an", "and", "or", "but", "for", "to", "of", "in", "on", "at", "by",
    "with", "as", "is", "are", "be", "been", "being", "this", "that", "these", "those",
    "we", "you", "your", "our", "their", "they", "it", "its", "will", "shall", "can",
    "must", "should", "would", "may", "have", "has", "had", "do", "does", "from", "up",
    "out", "if", "then", "else", "than", "so", "such", "into", "over", "under", "about",
    "who", "what", "which", "when", "where", "how", "all", "any", "both", "each", "more",
    "most", "other", "some", "no", "not", "only", "own", "same", "very", "just", "also",
    "work", "working", "experience", "years", "year", "team", "role", "job", "company",
    "ability", "strong", "good", "excellent", "knowledge", "skills", "skill", "etc",
    "including", "across", "within", "plus", "preferred", "required", "requirements",
    "responsibilities", "looking", "candidate", "candidates", "ideal", "join", "help",
    # generic JD responsibility verbs — not useful ATS keywords on their own
    "build", "building", "builds", "write", "writing", "writes", "create", "creating",
    "develop", "developing", "manage", "managing", "mentor", "mentoring", "collaborate",
    "collaborating", "optimize", "optimizing", "ensure", "ensuring", "deliver", "delivering",
    "drive", "driving", "support", "supporting", "maintain", "maintaining", "implement",
    "implementing", "responsible", "essential", "strong", "proven", "hands", "using", "use",
    "new", "well", "able", "like", "great", "best", "key", "various", "related", "etc.",
}

# Soft skills are a SUBSET of SKILLS above. Real ATS engines (e.g. Jobscan) weight
# these far less than hard skills, so we classify them separately for scoring.
SOFT_SKILLS: set[str] = {
    "communication", "leadership", "teamwork", "problem solving", "analytical",
    "time management", "negotiation", "presentation", "collaboration",
    "adaptability", "creativity", "interpersonal", "organization", "attention to detail",
    "critical thinking", "decision making", "work ethic", "self-motivated",
}

# Words that signal a job title — used to pull the role out of a JD and to match it
# against the candidate's experience titles (a heavily weighted ATS factor).
ROLE_WORDS: set[str] = {
    "engineer", "developer", "manager", "analyst", "designer", "scientist",
    "architect", "consultant", "lead", "specialist", "administrator", "coordinator",
    "director", "intern", "associate", "officer", "executive", "accountant",
    "technician", "programmer", "strategist", "recruiter", "marketer", "researcher",
    "writer", "editor", "nurse", "teacher", "advisor", "representative", "agent",
}

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+.#/-]*")

# HTML entity names + web/markup noise that leak in from scraped JDs and must NEVER
# be treated as keywords (e.g. "nbsp", "amp", "https", "www.nav.com").
_JUNK_TOKENS: set[str] = {
    "nbsp", "amp", "lt", "gt", "quot", "apos", "copy", "reg", "trade", "mdash",
    "ndash", "hellip", "rsquo", "lsquo", "rdquo", "ldquo", "bull", "middot", "deg",
    "http", "https", "www", "com", "org", "net", "io", "html", "htm", "php", "aspx",
    "href", "src", "div", "span", "br", "li", "ul", "ol", "utm", "url", "jpg", "png",
    "gif", "svg", "pdf", "css", "js", "json", "xml", "api",  # web noise as bare words
}
_HTML_TAG = re.compile(r"<[^>]+>")
_HTML_ENTITY = re.compile(r"&[#A-Za-z0-9]+;?")
_URL_LIKE = re.compile(r"https?://|www\.|\.com|\.org|\.net|\.io|@")


def strip_markup(text: str) -> str:
    """Remove HTML tags + entities from a (possibly scraped) JD so they can't pollute keywords."""
    t = _HTML_TAG.sub(" ", text or "")
    t = _HTML_ENTITY.sub(" ", t)
    return re.sub(r"\s+", " ", t)


def _is_junk(token: str) -> bool:
    """True if a token is markup/url noise rather than a real keyword."""
    if token in _JUNK_TOKENS:
        return True
    if _URL_LIKE.search(token):           # www.nav.com, careers/, mailto, etc.
        return True
    if "." in token and token.rsplit(".", 1)[-1] in {"com", "org", "net", "io", "co", "html"}:
        return True
    if not any(ch.isalpha() for ch in token):   # all punctuation/digits
        return True
    return False


def count_occurrences(text: str, term: str) -> int:
    pat = r"(?<![A-Za-z0-9])" + re.escape(term.lower()) + r"(?![A-Za-z0-9])"
    return len(re.findall(pat, text.lower()))


# A title phrase: optional seniority + up to 2 capitalized words + a role word.
_TITLE_RE = re.compile(
    r"\b((?:(?:Senior|Junior|Lead|Principal|Staff|Sr\.?|Jr\.?|Chief|Head|Associate)\s+)?"
    r"(?:[A-Z][A-Za-z0-9.+#/&-]*\s+){0,2}"
    r"(?:Engineer|Developer|Manager|Analyst|Designer|Scientist|Architect|Consultant|"
    r"Specialist|Administrator|Coordinator|Director|Officer|Executive|Accountant|"
    r"Technician|Programmer|Strategist|Recruiter|Marketer|Researcher|Writer|Editor|"
    r"Nurse|Teacher|Advisor|Representative|Agent|Intern))\b"
)


def extract_job_title(text: str) -> str:
    """Best-effort job title from a JD.

    First try a clean title phrase ('Senior Backend Engineer') anywhere near the top,
    even inside a longer sentence; then a short heading line with a role word; else the
    first non-empty line."""
    head = text[:600]
    m = _TITLE_RE.search(head)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:55]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines[:6]:
        low = ln.lower()
        if len(ln) <= 60 and any(f" {w} " in f" {low} " or low.endswith(w) for w in ROLE_WORDS):
            return re.sub(r"^(job title|title|role|position)\s*[:\-]\s*", "", ln, flags=re.I)[:55]
    return lines[0][:60] if lines else ""


def analyze_jd(text: str) -> dict:
    """Categorize a job description the way an ATS does.

    Returns hard skills (with JD frequency), soft skills, other frequent keywords,
    and the detected job title.
    """
    text = strip_markup(text)   # defensively de-HTML scraped JDs
    skills = find_skills(text)

    freq: dict[str, int] = {}
    for m in _WORD.finditer(text.lower()):
        w = m.group(0).strip(".,;:")  # drop trailing punctuation (next.js. -> next.js)
        if len(w) < 3 or w in STOPWORDS or w.isdigit() or _is_junk(w):
            continue
        freq[w] = freq.get(w, 0) + 1

    hard = [s for s in skills if s not in SOFT_SKILLS]
    soft = [s for s in skills if s in SOFT_SKILLS]
    hard.sort(key=lambda s: -count_occurrences(text, s))

    skill_words = {w for s in skills for w in s.split()}
    title = extract_job_title(text)
    title_words = {w for w in _WORD.findall(title.lower()) if w not in STOPWORDS and len(w) > 2}

    # Multi-word domain phrases the JD emphasizes ("distributed systems", "financial
    # reporting", "data pipelines"). Real ATS (Jobscan) extract many of these, which
    # widens the keyword universe and keeps the match rate honest — you must demonstrate
    # them, not just hit a handful of single words.
    phrases = _noun_phrases(text, skill_words | title_words)
    phrase_words = {w for p in phrases for w in p.split()}

    # Single-word domain terms: emphasized (freq>=2), not already a skill/title/phrase word.
    singles = [w for w, c in sorted(freq.items(), key=lambda kv: -kv[1])
               if w not in skill_words and w not in title_words and w not in phrase_words
               and c >= 2]

    other = list(dict.fromkeys([*phrases, *singles]))[:20]
    return {"hard": hard, "soft": soft, "other": other, "title": title}


def _noun_phrases(text: str, exclude_words: set[str]) -> list[str]:
    """Frequent content-bearing 2-word phrases — a lightweight noun-phrase signal so we
    score real domain terms ('data pipelines', 'distributed systems'), not just tokens."""
    toks = [m.group(0) for m in _WORD.finditer(text.lower())]
    freq: dict[str, int] = {}
    for a, b in zip(toks, toks[1:]):
        if (len(a) < 3 or len(b) < 3 or a in STOPWORDS or b in STOPWORDS
                or _is_junk(a) or _is_junk(b) or a.isdigit() or b.isdigit()):
            continue
        phrase = f"{a} {b}"
        freq[phrase] = freq.get(phrase, 0) + 1
    out = [p for p, c in sorted(freq.items(), key=lambda kv: -kv[1])
           if c >= 2 and not all(w in exclude_words for w in p.split())]
    return out[:10]


def _norm(text: str) -> str:
    return f" {text.lower()} "


def find_skills(text: str) -> list[str]:
    """Return gazetteer skills present in the text, preserving canonical form."""
    hay = _norm(text)
    found: list[str] = []
    consumed = hay
    for skill in _SKILLS_SORTED:
        # word-ish boundaries so 'r' doesn't match inside 'react'
        pattern = r"(?<![A-Za-z0-9])" + re.escape(skill) + r"(?![A-Za-z0-9])"
        if re.search(pattern, consumed):
            found.append(skill)
            # blank out the match so shorter sub-skills don't double count
            consumed = re.sub(pattern, " ", consumed)
    return found


def keywords_from_jd(text: str, limit: int = 30) -> tuple[list[str], list[str]]:
    """Extract (all_keywords, must_have) from a job description.

    all_keywords = gazetteer skills + frequent meaningful terms.
    must_have    = the top skills, ranked by how often they appear.
    """
    text = strip_markup(text)
    skills = find_skills(text)

    # Frequency of non-stopword tokens, to surface domain terms not in the list.
    freq: dict[str, int] = {}
    for m in _WORD.finditer(text.lower()):
        w = m.group(0).strip(".,;:")  # drop trailing punctuation (next.js. -> next.js)
        if len(w) < 3 or w in STOPWORDS or w.isdigit() or _is_junk(w):
            continue
        freq[w] = freq.get(w, 0) + 1

    # Rank skills by their frequency in the JD (mentioned often = more important).
    skill_rank = sorted(skills, key=lambda s: -freq.get(s.split()[0], 1))

    # Extra frequent terms not already covered by a skill.
    skill_words = {w for s in skills for w in s.split()}
    extra = [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])
             if w not in skill_words][:15]

    all_keywords: list[str] = []
    for k in skill_rank + extra:
        if k not in all_keywords:
            all_keywords.append(k)
        if len(all_keywords) >= limit:
            break

    must_have = skill_rank[:8] if skill_rank else all_keywords[:8]
    return all_keywords, must_have
