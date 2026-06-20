"""
Batch tailoring — tailor a candidate's resume to MANY jobs automatically, in parallel.

For each matched job we crawl its JD, tailor the resume to it (Opus + critic loop via
the ATS engine), and record the before/after ATS score + changes. Results are ranked by
after-score and saved per-job under the candidate's folder. This is the automation that
turns "tailor one resume" into "tailor for the whole day's matches at once."
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .. import config
from ..models import Job
from ..profile.complete import load_profile
from ..score.fit import build_matcher, score_job
from . import client

GOLDEN_MIN = 75   # the standard: a tailored resume must reach this to count as golden


def _tailor_one(resume_text: str, job: Job, fit: dict) -> dict:
    """Crawl-aware single tailor: uses the job's JD (with real title prepended)."""
    jd = f"Job Title: {job.title}\n\n{client.clean_jd(job.content)}"
    res = client.tailor_for_job(resume_text, jd)
    after = res["score_after"]
    return {
        "board": job.board, "job_id": job.job_id, "title": job.title,
        "url": job.url, "location": job.location,
        "fit_score": fit["final"], "fit_confidence": fit["confidence"],
        "red_flags": fit["red_flags"],
        "score_before": res["score_before"], "score_after": after,
        "golden": after >= GOLDEN_MIN,           # met the 75+ standard?
        "tailored_resume": res["tailored_resume"], "changes": res["changes"],
        "engine": res["engine"],
    }


def batch_tailor(
    resume_text: str,
    jobs: list[Job],
    candidate: str,
    *,
    max_workers: int = 3,
    fit_threshold: int = 55,    # only tailor jobs the candidate genuinely fits
    on_progress=None,
) -> dict:
    """Fit-gate, then tailor only good-fit jobs in parallel. Returns
    {tailored: [...ranked by fit...], skipped: [...low-fit...]} and saves per-job
    resumes + a ranked summary. This is how we keep tailored output at a golden
    standard: we don't waste effort (or fake scores) on jobs that aren't a real fit."""
    if not client.engine_available():
        raise RuntimeError("ATS engine not running. Start ats_resume_maker backend on :8000.")

    profile = load_profile(candidate)
    matcher = build_matcher(profile)

    # ---- Stage 2: personalized fit score for every job, then gate ----
    graded = [(score_job(matcher, j.title, client.clean_jd(j.content)), j) for j in jobs]
    to_tailor = [(f, j) for f, j in graded if f["final"] >= fit_threshold]
    skipped = [{"title": j.title, "url": j.url, "fit_score": f["final"],
                "red_flags": f["red_flags"]}
               for f, j in graded if f["final"] < fit_threshold]
    if on_progress:
        on_progress(f"Fit-gate: {len(to_tailor)}/{len(jobs)} jobs pass (>= {fit_threshold}); "
                    f"{len(skipped)} skipped as poor fit.")

    out_dir = config.candidate_dir(candidate) / "tailored"
    out_dir.mkdir(exist_ok=True)
    results: list[dict] = []
    done = 0

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_tailor_one, resume_text, j, f): (f, j) for f, j in to_tailor}
        for fut in as_completed(futs):
            f, job = futs[fut]
            done += 1
            try:
                r = fut.result()
                results.append(r)
                (out_dir / f"{_safe(job.board)}_{job.job_id}.json").write_text(
                    json.dumps(r, indent=2), encoding="utf-8")
                gold = "GOLDEN" if r["golden"] else f"below {GOLDEN_MIN}"
                msg = (f"[{done}/{len(to_tailor)}] fit {f['final']:.0f}  "
                       f"{job.title[:36]}  ATS {r['score_before']}->{r['score_after']} ({gold})")
            except Exception as e:
                results.append({"board": job.board, "job_id": job.job_id, "title": job.title,
                                "fit_score": f["final"], "error": str(e)})
                msg = f"[{done}/{len(to_tailor)}] {job.title[:36]}  FAILED: {type(e).__name__}"
            if on_progress:
                on_progress(msg)

    # rank by FIT first (true job suitability), then by tailored ATS
    results.sort(key=lambda r: (r.get("fit_score", -1), r.get("score_after", -1)), reverse=True)
    _save_summary(results, skipped, out_dir)
    return {"tailored": results, "skipped": skipped}


def _save_summary(results: list[dict], skipped: list[dict], out_dir: Path) -> Path:
    golden = sum(1 for r in results if r.get("golden"))
    lines = ["# Batch Tailoring Summary", "",
             f"**{golden}/{len(results)}** tailored resumes met the golden standard "
             f"(ATS >= {GOLDEN_MIN}). {len(skipped)} job(s) skipped as poor fit.", "",
             "## Tailored (ranked by job fit)",
             "| Rank | Fit | ATS After | Before | Golden | Job | Location |",
             "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        if "error" in r:
            lines.append(f"| {i} | {r.get('fit_score','')} | — | — | — | {r['title'][:42]} | FAILED |")
            continue
        gold = "✅" if r["golden"] else "⚠️"
        lines.append(f"| {i} | {r['fit_score']:.0f} | **{r['score_after']}** | {r['score_before']} "
                     f"| {gold} | {r['title'][:42]} | {r.get('location','')[:22]} |")
    if skipped:
        lines += ["", "## Skipped (below fit threshold — not a strong match)",
                  "| Fit | Job | Red flags |", "|---|---|---|"]
        for s in sorted(skipped, key=lambda x: -x["fit_score"]):
            lines.append(f"| {s['fit_score']:.0f} | {s['title'][:48]} | {'; '.join(s['red_flags'])[:40]} |")
    path = out_dir / "SUMMARY.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s).strip("_")
