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


# ats name -> fetcher
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
