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
from . import client


def _tailor_one(resume_text: str, job: Job) -> dict:
    """Crawl-aware single tailor: uses the job's JD (with real title prepended)."""
    jd = f"Job Title: {job.title}\n\n{client.clean_jd(job.content)}"
    res = client.tailor_for_job(resume_text, jd)
    return {
        "board": job.board, "job_id": job.job_id, "title": job.title,
        "url": job.url, "location": job.location,
        "score_before": res["score_before"], "score_after": res["score_after"],
        "tailored_resume": res["tailored_resume"], "changes": res["changes"],
        "engine": res["engine"],
    }


def batch_tailor(
    resume_text: str,
    jobs: list[Job],
    candidate: str,
    *,
    max_workers: int = 3,
    on_progress=None,
) -> list[dict]:
    """Tailor `resume_text` to every job in parallel. Returns results ranked by
    after-score (best first). Saves each tailored resume + a ranked summary to the
    candidate's folder."""
    if not client.engine_available():
        raise RuntimeError("ATS engine not running. Start ats_resume_maker backend on :8000.")

    out_dir = config.candidate_dir(candidate) / "tailored"
    out_dir.mkdir(exist_ok=True)
    results: list[dict] = []
    done = 0

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_tailor_one, resume_text, j): j for j in jobs}
        for fut in as_completed(futs):
            job = futs[fut]
            done += 1
            try:
                r = fut.result()
                results.append(r)
                # persist this job's tailored resume + scores
                (out_dir / f"{_safe(job.board)}_{job.job_id}.json").write_text(
                    json.dumps(r, indent=2), encoding="utf-8")
                msg = f"[{done}/{len(jobs)}] {job.title[:40]}  {r['score_before']}->{r['score_after']}"
            except Exception as e:
                results.append({"board": job.board, "job_id": job.job_id,
                                "title": job.title, "error": str(e)})
                msg = f"[{done}/{len(jobs)}] {job.title[:40]}  FAILED: {type(e).__name__}"
            if on_progress:
                on_progress(msg)

    # rank by after-score (failures last)
    results.sort(key=lambda r: r.get("score_after", -1), reverse=True)
    _save_summary(results, out_dir)
    return results


def _save_summary(results: list[dict], out_dir: Path) -> Path:
    lines = ["# Batch Tailoring Summary", "",
             "| Rank | After | Before | Lift | Job | Location |",
             "|---|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        if "error" in r:
            lines.append(f"| {i} | — | — | — | {r['title'][:45]} | FAILED: {r['error'][:30]} |")
            continue
        lift = r["score_after"] - r["score_before"]
        lines.append(f"| {i} | **{r['score_after']}** | {r['score_before']} | +{lift} "
                     f"| {r['title'][:45]} | {r.get('location','')[:24]} |")
    path = out_dir / "SUMMARY.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s).strip("_")
