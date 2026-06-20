"""
Multi-source board sweep with a LIVE-TOKEN CACHE (beats rate limits).

Sweeping all 15,533 seed boards every day is wasteful and triggers Greenhouse 429s.
So: sweep once, remember which tokens actually had jobs (the "live" set), and on later
runs only hit those. Lever/Ashby rarely throttle; Greenhouse does, so we pace it.

  build_live_cache()  -> one-time/periodic full sweep, saves seed/live_tokens.json
  sweep_targets()     -> {ats: [orgs]} to crawl (cached live set, else a capped seed slice)
  sweep()             -> fetch all jobs from those targets (parallel), returns [Job]
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from .. import config
from .sources import fetch_board

SEED_DIR = config.ROOT / "seed"
CACHE_FILE = SEED_DIR / "live_tokens.json"
ATS_FILES = {
    "greenhouse": "greenhouse_companies.json",
    "lever": "lever_companies.json",
    "ashby": "ashby_companies.json",
}


def load_seed() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ats, fname in ATS_FILES.items():
        p = SEED_DIR / fname
        out[ats] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    return out


def load_live_cache() -> dict[str, list[str]]:
    return json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}


def _save_live_cache(cache: dict[str, list[str]]):
    SEED_DIR.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=0), encoding="utf-8")


def sweep(ats_orgs: dict[str, list[str]], *, max_workers: int = 12,
          on_progress=None) -> tuple[list, dict[str, list[str]]]:
    """Fetch jobs from every (ats, org). Returns (all_jobs, live_tokens) where live_tokens
    are the orgs that returned >=1 job (for caching). Dead/throttled boards are skipped."""
    tasks = [(ats, org) for ats, orgs in ats_orgs.items() for org in orgs]
    all_jobs: list = []
    live: dict[str, list[str]] = {a: [] for a in ats_orgs}
    done = throttled = 0

    with httpx.Client(timeout=10.0, headers={"User-Agent": "job-portal/1.0"}) as client:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(_safe_fetch, ats, org, client): (ats, org) for ats, org in tasks}
            for fut in as_completed(futs):
                ats, org = futs[fut]
                done += 1
                jobs, status = fut.result()
                if status == 429:
                    throttled += 1
                if jobs:
                    all_jobs.extend(jobs)
                    live[ats].append(org)
                if on_progress and done % 200 == 0:
                    on_progress(f"  swept {done}/{len(tasks)} boards, {len(all_jobs)} jobs, "
                                f"{throttled} throttled")
    if on_progress:
        on_progress(f"  sweep done: {len(tasks)} boards -> {len(all_jobs)} jobs "
                    f"({sum(len(v) for v in live.values())} live, {throttled} throttled)")
    return all_jobs, live


def _safe_fetch(ats: str, org: str, client: httpx.Client):
    """Fetch one board; return (jobs, status). status 429 => throttled, 0 => other miss."""
    try:
        return fetch_board(ats, org, client=client), 200
    except httpx.HTTPStatusError as e:
        return [], e.response.status_code
    except Exception:
        return [], 0


def build_live_cache(*, limit_per_ats: int | None = None, max_workers: int = 12,
                     on_progress=None) -> dict[str, list[str]]:
    """One-time/periodic full sweep to find the live tokens. Saves seed/live_tokens.json."""
    seed = load_seed()
    targets = {ats: (orgs[:limit_per_ats] if limit_per_ats else orgs)
               for ats, orgs in seed.items()}
    _, live = sweep(targets, max_workers=max_workers, on_progress=on_progress)
    _save_live_cache(live)
    return live


def sweep_targets(*, limit_per_ats: int = 400, use_cache: bool = True) -> dict[str, list[str]]:
    """Which boards to crawl now: the cached LIVE set if present, else a capped seed slice
    (so the first run is bounded and you can build the cache progressively)."""
    cache = load_live_cache() if use_cache else {}
    if cache and any(cache.values()):
        return {ats: orgs[:limit_per_ats] if limit_per_ats else orgs
                for ats, orgs in cache.items()}
    seed = load_seed()
    return {ats: orgs[:limit_per_ats] for ats, orgs in seed.items()}
