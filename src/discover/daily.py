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


def scored_fresh_jobs(
    candidate: str,
    boards: list[str],
    *,
    max_days: int = 7,
    min_fit: int = 55,
    on_progress=None,
) -> list[tuple[dict, object]]:
    """Sweep boards, keep FRESH + good-fit jobs, return [(fit_result, Job)] ranked by fit
    and de-duplicated. The Job objects carry full JD content (ready for tailoring)."""
    matcher = build_matcher(load_profile(candidate))
    client = GreenhouseClient()
    graded: list[tuple[dict, object]] = []
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
                    graded.append((r, j))
                    kept += 1
            if on_progress:
                on_progress(f"  {board}: {len(jobs)} jobs, {len(fresh)} fresh, {kept} good-fit")
    finally:
        client.close()

    # rank by fit, de-duplicate the same role across locations (title+board)
    seen: set = set()
    out: list[tuple[dict, object]] = []
    for r, j in sorted(graded, key=lambda x: (-x[0]["final"], x[1].days_ago or 999)):
        key = (j.title.strip().lower(), j.board)
        if key in seen:
            continue
        seen.add(key)
        out.append((r, j))
    return out


def daily_crawl(
    candidate: str,
    boards: list[str],
    *,
    max_days: int = 7,
    min_fit: int = 55,
    on_progress=None,
) -> list[dict]:
    """Return today's ranked shortlist (dicts) and save candidates/<name>/daily_shortlist.csv."""
    graded = scored_fresh_jobs(candidate, boards, max_days=max_days,
                               min_fit=min_fit, on_progress=on_progress)
    shortlist = [{
        "fit": r["final"], "confidence": r["confidence"],
        "days_ago": j.days_ago, "posted_on": j.posted_on,
        "title": j.title, "company": j.board, "location": j.location,
        "min_years_req": r["min_years_req"], "red_flags": "; ".join(r["red_flags"]),
        "url": j.absolute_url,
    } for r, j in graded]
    _save(shortlist, candidate)
    return shortlist


def _save(shortlist: list[dict], candidate: str):
    path = config.candidate_dir(candidate) / "daily_shortlist.csv"
    cols = ["fit", "confidence", "days_ago", "posted_on", "title", "company",
            "location", "min_years_req", "red_flags", "url"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(shortlist)
    return path
