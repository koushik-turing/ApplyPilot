"""
Daily fresh-links crawl — the recurring step that runs every day per candidate.

Sweeps the configured ATS boards, keeps only FRESH postings (<= max_days old),
fit-scores each against the candidate (stage-2 personalized score), and writes the
day's ranked shortlist (fresh + good-fit) ready for batch tailoring.
"""
from __future__ import annotations

import csv
import json

from concurrent.futures import ThreadPoolExecutor

from .. import config
from ..profile.complete import load_profile
from ..score.fit import build_matcher, score_job
from ..score.ai_match import ai_match
from ..tailor.client import clean_jd
from . import dates
from .ats_client import GreenhouseClient


def rank_jobs(
    candidate: str,
    jobs: list,
    *,
    min_fit: int = 50,
    ai_score: bool = True,
    prefilter: int = 35,
    ai_cap: int = 130,        # AI-score enough survivors to surface ~80-90 matches
    on_progress=None,
) -> list[tuple[dict, object]]:
    """Two-stage scoring over an ALREADY-FETCHED job list. Returns [(score, Job)] ranked
    by the precise match %.
      Stage 1 (heuristic, cheap): keep jobs whose coarse fit >= prefilter; dedup.
      Stage 2 (AI, precise): AI-score only the top `ai_cap` heuristic survivors (bounds cost
                             when the firehose is huge) -> real match %; keep >= min_fit."""
    from ..score.sponsorship import tag_jobs
    from .usfilter import us_only

    profile = load_profile(candidate)
    matcher = build_matcher(profile)
    gate = prefilter if ai_score else min_fit

    # US-only: we target USA jobs; drop everything else up front (saves scoring cost).
    before_us = len(jobs)
    jobs = us_only(jobs)
    if on_progress and before_us != len(jobs):
        on_progress(f"  US filter: kept {len(jobs)}/{before_us} (dropped {before_us - len(jobs)} non-US)")

    # Sponsorship layer: tag every job; for candidates who NEED sponsorship, knock out
    # CONFIRMED non-sponsors (in USCIS data with 0 approvals). Unknown companies are kept.
    tag_jobs(jobs)
    needs_sponsor = bool(profile.work_auth.requires_sponsorship)
    if needs_sponsor:
        before = len(jobs)
        jobs = [j for j in jobs if getattr(j, "sponsors_h1b", None) is not False]
        if on_progress and before != len(jobs):
            on_progress(f"  sponsorship knockout: dropped {before - len(jobs)} confirmed non-sponsors")

    survivors = []
    for j in jobs:
        r = score_job(matcher, j.title, clean_jd(j.content))
        if r["final"] >= gate:
            r["sponsors_h1b"] = getattr(j, "sponsors_h1b", None)
            r["h1b_approvals"] = getattr(j, "h1b_approvals", 0)
            survivors.append((r, j))

    # de-duplicate the same role across locations (title+board)
    seen: set = set()
    deduped: list[tuple[dict, object]] = []
    for r, j in sorted(survivors, key=lambda x: -x[0]["final"]):
        key = (j.title.strip().lower(), j.board)
        if key not in seen:
            seen.add(key)
            deduped.append((r, j))

    if not ai_score:
        return [x for x in sorted(deduped, key=lambda x: (-x[0]["final"], x[1].days_ago or 999))
                if x[0]["final"] >= min_fit]

    # AI-score only the strongest heuristic survivors (cost control on big sweeps)
    top = deduped[:ai_cap]
    if on_progress:
        on_progress(f"  stage-1: {len(deduped)} candidates; AI-scoring top {len(top)} (precise %)...")

    def _ai(item):
        r, j = item
        a = ai_match(profile, j.title, clean_jd(j.content))
        if a["match"] is not None:
            r.update(ai_match=a["match"], verdict=a["verdict"],
                     strengths=a["strengths"], gaps=a["gaps"], final=a["match"])
        return r, j

    with ThreadPoolExecutor(max_workers=6) as ex:
        scored = list(ex.map(_ai, top))

    out = [(r, j) for r, j in scored if r["final"] >= min_fit]
    return sorted(out, key=lambda x: (-x[0]["final"], x[1].days_ago or 999))


def scored_fresh_jobs(
    candidate: str,
    boards: list[str],
    *,
    max_days: int = 7,
    min_fit: int = 55,
    ai_score: bool = True,
    on_progress=None,
) -> list[tuple[dict, object]]:
    """Greenhouse-only path (a fixed board list): fetch -> fresh -> rank."""
    client = GreenhouseClient()
    fresh_jobs: list = []
    try:
        for board in boards:
            try:
                jobs = client.list_jobs(board, content=True)
            except Exception as e:
                if on_progress:
                    on_progress(f"  {board}: fetch failed ({type(e).__name__})")
                continue
            fresh = dates.fresh_only(jobs, max_days)
            fresh_jobs.extend(fresh)
            if on_progress:
                on_progress(f"  {board}: {len(jobs)} jobs, {len(fresh)} fresh")
    finally:
        client.close()
    return rank_jobs(candidate, fresh_jobs, min_fit=min_fit, ai_score=ai_score, on_progress=on_progress)


def scored_fresh_multi(
    candidate: str,
    ats_orgs: dict[str, list[str]],
    *,
    max_days: int = 7,
    min_fit: int = 55,
    ai_score: bool = True,
    max_workers: int = 12,
    include_workable: bool = True,
    on_progress=None,
) -> list[tuple[dict, object]]:
    """Multi-source path: sweep ATS boards + query Workable/Adzuna -> freshness -> rank.
    The firehose. Workable/Adzuna are query-driven by the candidate's target titles."""
    from .sweep import sweep
    from .sources import fetch_workable, fetch_adzuna

    all_jobs, _live = sweep(ats_orgs, max_workers=max_workers, on_progress=on_progress)

    profile = load_profile(candidate)
    queries = (profile.target_titles or ["software engineer"])[:3]

    if include_workable:
        for q in queries:
            try:
                wk = fetch_workable(q, max_pages=2)
                all_jobs.extend(wk)
                if on_progress:
                    on_progress(f"  Workable '{q}': +{len(wk)} jobs")
            except Exception:
                pass

    aid, akey = _adzuna_key()
    if aid and akey:
        for q in queries:
            try:
                az = fetch_adzuna(q, app_id=aid, app_key=akey, pages=2)
                all_jobs.extend(az)
                if on_progress:
                    on_progress(f"  Adzuna '{q}': +{len(az)} jobs")
            except Exception:
                pass

    fresh = dates.fresh_only(all_jobs, max_days)   # keeps unknown-date jobs (not dropped)
    if on_progress:
        on_progress(f"  {len(all_jobs)} jobs total -> {len(fresh)} fresh/unknown (<= {max_days}d)")
    return rank_jobs(candidate, fresh, min_fit=min_fit, ai_score=ai_score, on_progress=on_progress)


def _adzuna_key() -> tuple[str | None, str | None]:
    """Adzuna app_id:app_key from config/adzuna_key.txt or env ADZUNA_APP_ID/ADZUNA_APP_KEY."""
    import os
    f = config.CONFIG_DIR / "adzuna_key.txt"
    if f.exists():
        raw = f.read_text(encoding="utf-8").strip()
        if ":" in raw:
            a, b = raw.split(":", 1)
            return a.strip(), b.strip()
    return os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")


def shortlist_row(r: dict, j) -> dict:
    """One shortlist record: the precise match % + reasoning + freshness for a job."""
    spons = r.get("sponsors_h1b", getattr(j, "sponsors_h1b", None))
    appr = r.get("h1b_approvals", getattr(j, "h1b_approvals", 0))
    return {
        "match": r.get("ai_match", r["final"]),
        "verdict": r.get("verdict", ""),
        "days_ago": j.days_ago, "posted_on": j.posted_on,
        "title": j.title, "company": j.board, "location": j.location,
        "sponsors_h1b": ("yes" if spons else "no" if spons is False else "unknown"),
        "h1b_approvals": appr,
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
    _save_jobs_cache(graded, candidate)
    return shortlist


def _save_jobs_cache(graded, candidate: str):
    """Store each shortlisted job's JD content (keyed by URL) so on-demand tailoring has the
    JD without re-fetching. Keeps the shortlist CSV small."""
    cache = {j.absolute_url: {"title": j.title, "board": j.board, "ats": getattr(j, "ats", ""),
                              "location": j.location, "content": j.content}
             for _, j in graded if j.absolute_url}
    (config.candidate_dir(candidate) / "jobs_cache.json").write_text(
        json.dumps(cache), encoding="utf-8")


def _save(shortlist: list[dict], candidate: str):
    path = config.candidate_dir(candidate) / "daily_shortlist.csv"
    cols = ["match", "verdict", "sponsors_h1b", "h1b_approvals", "days_ago", "posted_on",
            "title", "company", "location", "strengths", "gaps", "min_years_req",
            "red_flags", "url"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(shortlist)
    return path
