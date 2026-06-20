"""
Multi-ATS job sources — Greenhouse + Lever + Ashby (+ Workable best-effort).

All return ats_client.Job objects (same shape) so the rest of the pipeline (freshness,
match, tailor) doesn't care which board a job came from. Each carries first_published
for "days ago"; sources without a date leave it blank (handled downstream, not dropped).
"""
from __future__ import annotations

import datetime

import httpx

from .ats_client import Job

_UA = {"User-Agent": "job-portal/1.0"}
_TIMEOUT = 10.0


def _epoch_ms_to_iso(ms) -> str:
    try:
        return datetime.datetime.utcfromtimestamp(int(ms) / 1000).isoformat()
    except Exception:
        return ""


def fetch_greenhouse(org: str, *, client: httpx.Client | None = None) -> list[Job]:
    c = client or httpx.Client(timeout=_TIMEOUT, headers=_UA)
    try:
        r = c.get(f"https://boards-api.greenhouse.io/v1/boards/{org}/jobs",
                  params={"content": "true"})
        r.raise_for_status()
        out = []
        for j in r.json().get("jobs", []):
            out.append(Job(
                board=org, job_id=str(j["id"]), title=j.get("title", ""),
                location=(j.get("location") or {}).get("name", ""),
                absolute_url=j.get("absolute_url", ""), content=j.get("content", ""),
                first_published=j.get("first_published") or j.get("updated_at") or "",
                ats="greenhouse"))
        return out
    finally:
        if client is None:
            c.close()


def fetch_lever(org: str, *, client: httpx.Client | None = None) -> list[Job]:
    c = client or httpx.Client(timeout=_TIMEOUT, headers=_UA)
    try:
        r = c.get(f"https://api.lever.co/v0/postings/{org}", params={"mode": "json"})
        r.raise_for_status()
        data = r.json()
        out = []
        for j in (data if isinstance(data, list) else []):
            out.append(Job(
                board=org, job_id=str(j.get("id", "")), title=j.get("text", ""),
                location=(j.get("categories") or {}).get("location", ""),
                absolute_url=j.get("hostedUrl", "") or j.get("applyUrl", ""),
                content=j.get("descriptionPlain", "") or j.get("description", ""),
                first_published=_epoch_ms_to_iso(j.get("createdAt")), ats="lever"))
        return out
    finally:
        if client is None:
            c.close()


def fetch_ashby(org: str, *, client: httpx.Client | None = None) -> list[Job]:
    c = client or httpx.Client(timeout=_TIMEOUT, headers=_UA)
    try:
        r = c.get(f"https://api.ashbyhq.com/posting-api/job-board/{org}",
                  params={"includeCompensation": "false"})
        r.raise_for_status()
        out = []
        for j in r.json().get("jobs", []):
            if j.get("isListed") is False:
                continue
            out.append(Job(
                board=org, job_id=str(j.get("id", "")), title=j.get("title", ""),
                location=j.get("location", ""),
                absolute_url=j.get("jobUrl", "") or j.get("applyUrl", ""),
                content=j.get("descriptionPlain", "") or j.get("descriptionHtml", ""),
                first_published=j.get("publishedAt", ""), ats="ashby"))
        return out
    finally:
        if client is None:
            c.close()


def _strip_html(s: str) -> str:
    import re
    return re.sub(r"<[^>]+>", " ", re.sub(r"&[a-z]+;", " ", s or ""))


def fetch_workable(query: str, *, location: str = "United States", max_pages: int = 3,
                   client: httpx.Client | None = None) -> list[Job]:
    """Workable is a SEARCH API across all Workable companies (not per-org). Query-based,
    so we drive it from the candidate's target titles. Paginated via nextPageToken."""
    c = client or httpx.Client(timeout=_TIMEOUT, headers=_UA)
    out: list[Job] = []
    try:
        token, pages = None, 0
        while pages < max_pages:
            params = {"location": location, "query": query}
            if token:
                params["pageToken"] = token
            r = c.get("https://jobs.workable.com/api/v1/jobs", params=params)
            r.raise_for_status()
            d = r.json()
            for j in d.get("jobs", []):
                url = j.get("url") or ""
                loc = j.get("location") or {}
                loc_str = ", ".join(x for x in [loc.get("city"), loc.get("subregion"),
                                                loc.get("countryName")] if x) or j.get("location", "")
                out.append(Job(
                    board=(j.get("company") or {}).get("title", "") or "workable",
                    job_id=str(j.get("id", "")), title=j.get("title", ""),
                    location=loc_str if isinstance(loc_str, str) else "",
                    absolute_url=url,
                    content=_strip_html(j.get("description", "")) + " "
                            + _strip_html(j.get("requirementsSection", "")),
                    first_published=j.get("created", ""), ats="workable"))
            token = d.get("nextPageToken")
            pages += 1
            if not token:
                break
        return out
    finally:
        if client is None:
            c.close()


def fetch_adzuna(query: str, *, app_id: str, app_key: str, country: str = "us",
                 pages: int = 2, client: httpx.Client | None = None) -> list[Job]:
    """Adzuna aggregator API (needs a free key from developer.adzuna.com). Big volume,
    has 'created' dates. Country code e.g. 'us', 'in'."""
    c = client or httpx.Client(timeout=_TIMEOUT, headers=_UA)
    out: list[Job] = []
    try:
        for page in range(1, pages + 1):
            r = c.get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}",
                      params={"app_id": app_id, "app_key": app_key,
                              "what": query, "results_per_page": 50, "content-type": "application/json"})
            r.raise_for_status()
            for j in r.json().get("results", []):
                out.append(Job(
                    board=(j.get("company") or {}).get("display_name", "") or "adzuna",
                    job_id=str(j.get("id", "")), title=j.get("title", ""),
                    location=(j.get("location") or {}).get("display_name", ""),
                    absolute_url=j.get("redirect_url", ""),
                    content=j.get("description", ""),
                    first_published=j.get("created", ""), ats="adzuna"))
        return out
    finally:
        if client is None:
            c.close()


# ats name -> per-org fetcher (board-token based)
FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}


def fetch_board(ats: str, org: str, *, client: httpx.Client | None = None) -> list[Job]:
    fn = FETCHERS.get(ats)
    if not fn:
        return []
    return fn(org, client=client)
