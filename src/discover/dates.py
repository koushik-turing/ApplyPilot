"""
Posting freshness — "how many days ago was this job posted?".

Generalizes fetch_dates_sai.py: reads the real posting date the ATS exposes
(Greenhouse first_published, Ashby publishedAt, Lever createdAt; JSON-LD datePosted
as a fallback) and computes Days Ago. Used to keep the DAILY crawl to fresh links only.
"""
from __future__ import annotations

import datetime
import re

import httpx

_UA = {"User-Agent": "Mozilla/5.0 (compatible; freshness/1.0)"}


def today() -> datetime.date:
    return datetime.date.today()


def parse_iso_date(s) -> datetime.date | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):                 # epoch ms (Ashby/Lever sometimes)
        return datetime.datetime.utcfromtimestamp(s / 1000).date()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s).strip())
    if m:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def days_ago(date_obj: datetime.date | None, ref: datetime.date | None = None) -> int | None:
    if date_obj is None:
        return None
    return ((ref or today()) - date_obj).days


def annotate(jobs, ref: datetime.date | None = None) -> list:
    """Attach .posted_on (date) + .days_ago to a list of ats_client.Job objects that
    already carry first_published. Returns the same list (mutated for convenience)."""
    ref = ref or today()
    for j in jobs:
        d = parse_iso_date(getattr(j, "first_published", "") or "")
        setattr(j, "posted_on", d.isoformat() if d else "")
        setattr(j, "days_ago", (ref - d).days if d else None)
    return jobs


def fresh_only(jobs, max_days: int = 7, ref: datetime.date | None = None) -> list:
    """Keep only jobs posted within `max_days` (unknown dates are dropped)."""
    annotate(jobs, ref)
    return [j for j in jobs if getattr(j, "days_ago", None) is not None
            and j.days_ago <= max_days]


def freshness_summary(jobs) -> dict:
    """Counts by recency for a quick report (today / <=1 / <=3 / <=7 / unknown)."""
    annotate(jobs)
    known = [j.days_ago for j in jobs if getattr(j, "days_ago", None) is not None]
    return {
        "total": len(jobs),
        "dated": len(known),
        "unknown": len(jobs) - len(known),
        "today": sum(1 for d in known if d == 0),
        "<=1_day": sum(1 for d in known if d <= 1),
        "<=3_days": sum(1 for d in known if d <= 3),
        "<=7_days": sum(1 for d in known if d <= 7),
    }


# ---- other ATS bulk date fetchers (for URLs not from Greenhouse list_jobs) ----

def fetch_ashby(org: str) -> dict:
    out = {}
    try:
        r = httpx.get(f"https://api.ashbyhq.com/posting-api/job-board/{org}",
                      params={"includeCompensation": "false"}, headers=_UA, timeout=20)
        for j in r.json().get("jobs", []):
            out[str(j.get("id"))] = parse_iso_date(j.get("publishedAt"))
    except Exception:
        pass
    return out


def fetch_lever(org: str) -> dict:
    out = {}
    try:
        r = httpx.get(f"https://api.lever.co/v0/postings/{org}",
                      params={"mode": "json"}, headers=_UA, timeout=20)
        for j in r.json():
            out[str(j.get("id"))] = parse_iso_date(j.get("createdAt"))
    except Exception:
        pass
    return out
