"""
Daily fresh-links crawl — the recurring step that runs every day per candidate.

Sweeps the configured ATS boards, keeps only FRESH postings (<= max_days old),
fit-scores each against the candidate (stage-2 personalized score), and writes the
day's ranked shortlist (fresh + good-fit) ready for batch tailoring.
"""
from __future__ import annotations

import csv

from .. import config
from ..profile.complete import load_profile
from ..score.fit import build_matcher, score_job
from ..tailor.client import clean_jd
from . import dates
from .ats_client import GreenhouseClient


def daily_crawl(
    candidate: str,
    boards: list[str],
    *,
    max_days: int = 7,
    min_fit: int = 55,
    on_progress=None,
) -> list[dict]:
    """Return today's ranked shortlist of FRESH, good-fit jobs for the candidate, and
    save it to candidates/<name>/daily_shortlist.csv."""
    matcher = build_matcher(load_profile(candidate))
    client = GreenhouseClient()
    shortlist: list[dict] = []
    try:
        for board in boards:
            try:
                jobs = client.list_jobs(board, content=True)
            except Exception as e:
                if on_progress:
                    on_progress(f"  {board}: fetch failed ({type(e).__name__})")
                continue
            fresh = dates.fresh_only(jobs, max_days)
            kept = 0
            for j in fresh:
                r = score_job(matcher, j.title, clean_jd(j.content))
                if r["final"] >= min_fit:
                    shortlist.append({
                        "fit": r["final"], "confidence": r["confidence"],
                        "days_ago": j.days_ago, "posted_on": j.posted_on,
                        "title": j.title, "company": board, "location": j.location,
                        "min_years_req": r["min_years_req"],
                        "red_flags": "; ".join(r["red_flags"]),
                        "url": j.absolute_url,
                    })
                    kept += 1
            if on_progress:
                on_progress(f"  {board}: {len(jobs)} jobs, {len(fresh)} fresh, {kept} good-fit")
    finally:
        client.close()

    # de-duplicate the same role posted across multiple locations (title+company)
    seen: set = set()
    deduped: list[dict] = []
    for r in sorted(shortlist, key=lambda d: (-d["fit"], d["days_ago"])):
        key = (r["title"].strip().lower(), r["company"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    _save(deduped, candidate)
    return deduped


def _save(shortlist: list[dict], candidate: str):
    path = config.candidate_dir(candidate) / "daily_shortlist.csv"
    cols = ["fit", "confidence", "days_ago", "posted_on", "title", "company",
            "location", "min_years_req", "red_flags", "url"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(shortlist)
    return path
