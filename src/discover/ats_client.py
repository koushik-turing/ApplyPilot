"""
ATS API client — reads jobs and their exact application forms from public ATS APIs.

This is the foundation of the whole portal: because Greenhouse/Ashby/Lever expose
public board APIs, we can read each application form *as structured data*
(field names, types, required flags, dropdown option IDs) instead of guessing the DOM.

No auth, no scraping, no CAPTCHA needed to discover jobs and read their forms.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

GREENHOUSE_BASE = "https://boards-api.greenhouse.io/v1/boards"
DEFAULT_TIMEOUT = 15.0


@dataclass
class FormQuestion:
    """One field on an application form, read straight from the ATS API."""
    label: str
    required: bool
    field_type: str                       # input_text, textarea, multi_value_single_select, ...
    field_names: list[str] = field(default_factory=list)   # real POST field name(s)
    options: list[dict[str, Any]] = field(default_factory=list)  # [{label, value(id)}]

    def __str__(self) -> str:
        req = "REQUIRED" if self.required else "optional"
        opts = ""
        if self.options:
            shown = ", ".join(f"{o.get('label')}={o.get('value')}" for o in self.options[:6])
            opts = f"  options[{len(self.options)}]: {shown}"
        names = ",".join(self.field_names)
        return f"  - [{req}] ({self.field_type}) {self.label!r}  field={names}{opts}"


@dataclass
class Job:
    board: str
    job_id: str
    title: str
    location: str
    absolute_url: str
    content: str = ""
    first_published: str = ""        # ISO timestamp from the ATS (for freshness)
    ats: str = "greenhouse"          # greenhouse | lever | ashby | workable
    questions: list[FormQuestion] = field(default_factory=list)


class GreenhouseClient:
    """Public Greenhouse Job Board API — no key required."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": "job-portal/0.1"})

    def close(self) -> None:
        self._client.close()

    def list_jobs(self, board: str, *, content: bool = False) -> list[Job]:
        """List all LIVE jobs for a board token (only active jobs are returned)."""
        url = f"{GREENHOUSE_BASE}/{board}/jobs"
        r = self._client.get(url, params={"content": str(content).lower()})
        r.raise_for_status()
        jobs = []
        for j in r.json().get("jobs", []):
            loc = (j.get("location") or {}).get("name", "")
            jobs.append(Job(
                board=board, job_id=str(j["id"]), title=j.get("title", ""),
                location=loc, absolute_url=j.get("absolute_url", ""),
                content=j.get("content", ""),
                first_published=j.get("first_published") or j.get("updated_at") or "",
            ))
        return jobs

    def get_job_form(self, board: str, job_id: str) -> Job:
        """Fetch a single job WITH its full application form (every question + field names)."""
        url = f"{GREENHOUSE_BASE}/{board}/jobs/{job_id}"
        r = self._client.get(url, params={"questions": "true"})
        r.raise_for_status()
        data = r.json()
        loc = (data.get("location") or {}).get("name", "")
        job = Job(
            board=board, job_id=str(data["id"]), title=data.get("title", ""),
            location=loc, absolute_url=data.get("absolute_url", ""),
            content=data.get("content", ""),
        )
        for q in data.get("questions", []):
            fields = q.get("fields", [])
            field_names = [f.get("name", "") for f in fields]
            ftype = fields[0].get("type", "") if fields else ""
            options = []
            for f in fields:
                for o in f.get("values", []) or []:
                    options.append({"label": o.get("label"), "value": o.get("value")})
            job.questions.append(FormQuestion(
                label=q.get("label", ""),
                required=bool(q.get("required", False)),
                field_type=ftype,
                field_names=[n for n in field_names if n],
                options=options,
            ))
        return job


def parse_greenhouse_url(url: str) -> tuple[str, str] | None:
    """Extract (board_token, job_id) from any Greenhouse URL form."""
    # custom domain with ?gh_jid=JOBID  (board token unknown from URL alone)
    m = re.search(r"[?&]gh_jid=(\d+)", url)
    if m and "greenhouse.io" not in url:
        return None  # need board token from elsewhere; caller handles
    # /embed/job_app?for=BOARD&token=JOBID
    m = re.search(r"[?&]for=([^&]+)&token=(\d+)", url)
    if m:
        return m.group(1), m.group(2)
    # job-boards.greenhouse.io/BOARD/jobs/JOBID  or  boards.greenhouse.io/BOARD/jobs/JOBID
    m = re.search(r"greenhouse\.io/(?:embed/)?([^/]+)/jobs/(\d+)", url)
    if m:
        return m.group(1), m.group(2)
    return None


def _extract_job_id(url: str) -> str | None:
    """A Greenhouse job id from any URL: gh_jid=, or a long numeric path segment."""
    m = re.search(r"[?&]gh_jid=(\d+)", url)
    if m:
        return m.group(1)
    nums = re.findall(r"/(\d{5,})(?=/|$|\?|#)", url)
    return nums[-1] if nums else None


def _candidate_boards(url: str) -> list[str]:
    """Likely Greenhouse board tokens from a custom-domain URL (e.g. stripe.com -> 'stripe',
    careers.brex.com -> 'brex'). We verify each against the API before trusting it."""
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower().split(":")[0]
    if not host:
        return []
    drop = {"www", "jobs", "careers", "boards", "apply", "job-boards", "recruiting",
            "talent", "work", "job-boards-api", "eu"}
    labels = [p for p in host.split(".") if p not in drop]
    if len(labels) >= 2:                      # drop the TLD (.com/.io/.ai/...)
        labels = labels[:-1]
    return [l for l in dict.fromkeys(labels)
            if l and l not in ("greenhouse", "lever", "ashbyhq", "workable")]


def resolve_greenhouse(url: str, *, client: httpx.Client | None = None) -> tuple[str, str] | None:
    """Resolve ANY url to (board, job_id) if it's Greenhouse-backed — including custom domains
    (stripe.com, brex.com/careers, ...). Verifies candidate board tokens against the public API
    so we never false-positive. Returns None for genuinely non-Greenhouse sites."""
    direct = parse_greenhouse_url(url)
    if direct:
        return direct
    job_id = _extract_job_id(url)
    if not job_id:
        return None
    own = client or httpx.Client(timeout=8.0, headers={"User-Agent": "job-portal/1.0"})
    try:
        for board in _candidate_boards(url):
            try:
                r = own.get(f"{GREENHOUSE_BASE}/{board}/jobs/{job_id}")
                if r.status_code == 200 and str(r.json().get("id", "")) == str(job_id):
                    return board, job_id
            except Exception:
                continue
    finally:
        if client is None:
            own.close()
    return None


if __name__ == "__main__":
    # Live smoke test — reads a real job's application form via the public API.
    client = GreenhouseClient()
    try:
        board, job_id = "navtechnologies", "5985843004"
        job = client.get_job_form(board, job_id)
        print(f"JOB: {job.title}  @ {job.location}")
        print(f"URL: {job.absolute_url}")
        print(f"Application form has {len(job.questions)} questions:")
        for q in job.questions:
            print(q)
    finally:
        client.close()
