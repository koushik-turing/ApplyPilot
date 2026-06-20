"""
Per-candidate daily pipeline — the whole journey as ONE call, run for every client.

  crawl fresh + fit-score  ->  golden batch-tailor the shortlist  ->  ready to apply

run_candidate_daily() does it for one client; run_all_candidates() does it for everyone
in candidates/. Each client is driven entirely by their own resume + profile.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config
from .discover.daily import scored_fresh_jobs, _save as _save_shortlist
from .models import Job
from .profile.parse import read_pdf_text
from .tailor.batch import batch_tailor

DEFAULT_BOARDS = ["stripe", "databricks", "anthropic", "gitlab"]


def find_resume(candidate: str) -> Path | None:
    """A resume stored in the candidate's folder (added during `add`)."""
    d = config.candidate_dir(candidate)
    for pat in ("*.pdf", "*.docx"):
        hits = sorted(d.glob(pat))
        if hits:
            return hits[0]
    return None


def run_candidate_daily(
    candidate: str,
    boards: list[str] | None = None,
    *,
    max_days: int = 7,
    min_fit: int = 55,
    top_n: int = 10,
    workers: int = 3,
    on_progress=None,
) -> dict:
    """Full daily run for ONE client: fresh+fit shortlist -> golden tailor top N."""
    log = on_progress or (lambda m: None)
    resume = find_resume(candidate)
    if not resume:
        return {"candidate": candidate, "error": "no resume in candidate folder (run `add`)"}
    resume_text = read_pdf_text(resume)

    log(f"[{candidate}] crawling fresh+fit jobs...")
    graded = scored_fresh_jobs(candidate, boards or DEFAULT_BOARDS,
                               max_days=max_days, min_fit=min_fit, on_progress=on_progress)
    # save the day's shortlist
    shortlist = [{
        "fit": r["final"], "confidence": r["confidence"], "days_ago": j.days_ago,
        "posted_on": j.posted_on, "title": j.title, "company": j.board,
        "location": j.location, "min_years_req": r["min_years_req"],
        "red_flags": "; ".join(r["red_flags"]), "url": j.absolute_url,
    } for r, j in graded]
    _save_shortlist(shortlist, candidate)

    top = [j for _, j in graded[:top_n]]
    jobs = [Job(board=j.board, job_id=j.job_id, title=j.title, location=j.location,
                url=j.absolute_url, content=j.content) for j in top]
    log(f"[{candidate}] {len(graded)} fresh+fit jobs; golden-tailoring top {len(jobs)}...")

    out = batch_tailor(resume_text, jobs, candidate, max_workers=workers,
                       fit_threshold=min_fit, on_progress=on_progress)
    golden = sum(1 for r in out["tailored"] if r.get("golden"))
    summary = {
        "candidate": candidate, "fresh_fit_jobs": len(graded),
        "tailored": len(out["tailored"]), "golden": golden,
        "skipped": len(out["skipped"]),
    }
    config.candidate_dir(candidate).joinpath("daily_run.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    log(f"[{candidate}] done: {golden}/{len(out['tailored'])} golden tailored.")
    return summary


def list_candidates() -> list[str]:
    """Every candidate that has a profile in candidates/."""
    if not config.CANDIDATES_DIR.exists():
        return []
    return [d.name for d in config.CANDIDATES_DIR.iterdir()
            if d.is_dir() and (d / "profile.json").exists()]


def run_all_candidates(boards: list[str] | None = None, *, on_progress=None, **kw) -> list[dict]:
    """Run the daily pipeline for EVERY client. (Sequential per client so we don't
    overload the single ATS engine; each client's tailoring is already parallel.)"""
    log = on_progress or (lambda m: None)
    names = list_candidates()
    log(f"Running daily pipeline for {len(names)} client(s): {', '.join(names)}")
    reports = []
    for name in names:
        try:
            reports.append(run_candidate_daily(name, boards, on_progress=on_progress, **kw))
        except Exception as e:
            reports.append({"candidate": name, "error": f"{type(e).__name__}: {e}"})
    return reports
