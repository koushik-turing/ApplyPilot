"""
Daily fresh-links crawl — the recurring step that runs every day per candidate.

Sweeps the configured ATS boards, keeps only FRESH postings (<= max_days old),
fit-scores each against the candidate (stage-2 personalized score), and writes the
day's ranked shortlist (fresh + good-fit) ready for batch tailoring.
"""
from __future__ import annotations

import csv

from concurrent.futures import ThreadPoolExecutor

from .. import config
from ..profile.complete import load_profile
from ..score.fit import build_matcher, score_job
from ..score.ai_match import ai_match
from ..tailor.client import clean_jd
from . import dates
from .ats_client import GreenhouseClient


def scored_fresh_jobs(
    candidate: str,
    boards: list[str],
    *,
    max_days: int = 7,
    min_fit: int = 55,
    ai_score: bool = True,
    prefilter: int = 35,
    on_progress=None,
) -> list[tuple[dict, object]]:
    """Two-stage scoring, returns [(score, Job)] ranked by the precise match %.

    Stage 1 (heuristic, cheap): keep FRESH jobs whose coarse fit >= `prefilter`.
    Stage 2 (AI, precise): Claude scores each survivor resume-vs-JD -> the real match %
    ('ai_match' + strengths/gaps); keep those >= `min_fit`, rank by it. With ai_score=False
    it ranks by the heuristic alone (no API cost)."""
    profile = load_profile(candidate)
    matcher = build_matcher(profile)
    client = GreenhouseClient()
    survivors: list[tuple[dict, object]] = []
    gate = prefilter if ai_score else min_fit
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
                if r["final"] >= gate:
                    survivors.append((r, j))
                    kept += 1
            if on_progress:
                on_progress(f"  {board}: {len(jobs)} jobs, {len(fresh)} fresh, {kept} pass stage-1")
    finally:
        client.close()

    # de-duplicate the same role across locations (title+board)
    seen: set = set()
    deduped: list[tuple[dict, object]] = []
    for r, j in sorted(survivors, key=lambda x: -x[0]["final"]):
        key = (j.title.strip().lower(), j.board)
        if key not in seen:
            seen.add(key)
            deduped.append((r, j))

    if not ai_score:
        return sorted(deduped, key=lambda x: (-x[0]["final"], x[1].days_ago or 999))

    # ---- Stage 2: precise AI match % on the survivors (parallel) ----
    if on_progress:
        on_progress(f"  AI-scoring {len(deduped)} shortlisted jobs (precise match %)...")

    def _ai(item):
        r, j = item
        a = ai_match(profile, j.title, clean_jd(j.content))
        if a["match"] is not None:
            r["ai_match"] = a["match"]
            r["verdict"] = a["verdict"]
            r["strengths"] = a["strengths"]
            r["gaps"] = a["gaps"]
            r["final"] = a["match"]      # the precise match % becomes the headline score
        return r, j

    with ThreadPoolExecutor(max_workers=6) as ex:
        scored = list(ex.map(_ai, deduped))

    out = [(r, j) for r, j in scored if r["final"] >= min_fit]
    return sorted(out, key=lambda x: (-x[0]["final"], x[1].days_ago or 999))


def shortlist_row(r: dict, j) -> dict:
    """One shortlist record: the precise match % + reasoning + freshness for a job."""
    return {
        "match": r.get("ai_match", r["final"]),
        "verdict": r.get("verdict", ""),
        "days_ago": j.days_ago, "posted_on": j.posted_on,
        "title": j.title, "company": j.board, "location": j.location,
        "strengths": " | ".join(r.get("strengths", [])),
        "gaps": " | ".join(r.get("gaps", [])),
        "min_years_req": r.get("min_years_req"),
        "red_flags": "; ".join(r.get("red_flags", [])),
        "url": j.absolute_url,
    }


def daily_crawl(
    candidate: str,
    boards: list[str],
    *,
    max_days: int = 7,
    min_fit: int = 55,
    ai_score: bool = True,
    on_progress=None,
) -> list[dict]:
    """Return today's ranked shortlist (dicts) and save candidates/<name>/daily_shortlist.csv."""
    graded = scored_fresh_jobs(candidate, boards, max_days=max_days, min_fit=min_fit,
                               ai_score=ai_score, on_progress=on_progress)
    shortlist = [shortlist_row(r, j) for r, j in graded]
    _save(shortlist, candidate)
    return shortlist


def _save(shortlist: list[dict], candidate: str):
    path = config.candidate_dir(candidate) / "daily_shortlist.csv"
    cols = ["match", "verdict", "days_ago", "posted_on", "title", "company",
            "location", "strengths", "gaps", "min_years_req", "red_flags", "url"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(shortlist)
    return path
