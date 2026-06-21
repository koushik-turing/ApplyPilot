"""
Orchestrator CLI — end-to-end, for ANY candidate.

Commands:
  add <name> <resume.pdf>             M1: parse resume -> candidates/<name>/profile.json
  complete <name> <intake.json>       fill extra fields (visa/salary/EEO) from a JSON file
  apply <name> <job_url>              fetch form -> answer -> save review (no browser)
  apply <name> <job_url> --fill       also open the browser and fill it (stops before submit)
  apply <name> <job_url> --submit     fill AND submit (only if nothing needs human review)
  show <name>                         print the candidate's profile summary

Per-candidate data lives in candidates/<name>/ (git-ignored).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config
from .answer.engine import answer_form
from .discover.ats_client import GreenhouseClient, resolve_greenhouse
from .models import Job, FormQuestion
from .profile.complete import complete_profile, load_profile
from .profile.parse import parse_resume, save_profile, read_pdf_text
from .submit.apply import build_review, save_review, fill_form
from .tailor.batch import batch_tailor
from .discover.daily import daily_crawl
from .pipeline import run_candidate_daily, run_all_candidates


def cmd_add(args):
    import shutil
    prof = parse_resume(args.resume)
    path = save_profile(prof, args.name)
    # keep a copy of the resume in the candidate folder so the daily pipeline can find it
    dest = config.candidate_dir(args.name) / Path(args.resume).name
    try:
        shutil.copy(args.resume, dest)
    except Exception:
        pass
    print(f"✓ Parsed resume -> {path}")
    print(f"  {prof.full_name} | {len(prof.skills)} skills | {len(prof.experience)} roles")
    print(f"  Target titles: {', '.join(prof.target_titles)}")
    print(f"  NOTE: run 'complete' to add visa/salary/EEO before applying.")


def cmd_complete(args):
    intake = json.loads(Path(args.intake).read_text(encoding="utf-8"))
    path = complete_profile(args.name, intake)
    p = load_profile(args.name)
    print(f"✓ Profile completed -> {path}")
    print(f"  authorized_us={p.work_auth.authorized_us} "
          f"sponsorship={p.work_auth.requires_sponsorship} salary={p.desired_salary!r}")


def _fetch_job(url: str) -> Job:
    parsed = resolve_greenhouse(url)
    if not parsed:
        raise SystemExit(f"Could not parse board/job_id from URL: {url}\n"
                         "Only Greenhouse URLs are supported so far.")
    board, job_id = parsed
    c = GreenhouseClient()
    try:
        raw = c.get_job_form(board, job_id)
    finally:
        c.close()
    return Job(board=raw.board, job_id=raw.job_id, title=raw.title, location=raw.location,
               url=raw.absolute_url, content=raw.content,
               questions=[FormQuestion(label=q.label, required=q.required,
                                       field_type=q.field_type, field_names=q.field_names,
                                       options=q.options) for q in raw.questions])


def cmd_apply(args):
    prof = load_profile(args.name)
    job = _fetch_job(args.url)
    print(f"Job: {job.title} @ {job.location} ({job.board})")

    sheet = answer_form(job, prof, args.name, test_mode=not args.live)
    if not args.live:
        print("  TEST MODE: using dummy email/phone (no real contact used). Pass --live to use real.")
    resume = _find_resume(args.name, args.resume)
    review_text = build_review(job, sheet, prof, resume or "(no resume set)")
    review_path = save_review(review_text, args.name, job)
    print(f"✓ Review saved -> {review_path}")
    print(f"  needs human review: {sheet.needs_review}")

    if not (args.fill or args.submit):
        print("  (review only — pass --fill to open the browser, --submit to submit)")
        return

    if args.submit and sheet.needs_review:
        print("✗ Refusing to submit: some fields need human input. Resolve them first.")
        return

    result = fill_form(job, sheet, resume or "", submit=args.submit,
                       headless=args.headless)
    print(f"✓ Browser result: {result.get('status')}")
    if result.get("note"):
        print(f"  {result['note']}")
    if result.get("screenshot"):
        print(f"  screenshot: {result['screenshot']}")


def cmd_tailor_all(args):
    """Tailor the candidate's resume to MANY jobs at once (batch, parallel)."""
    resume = _find_resume(args.name, args.resume)
    if not resume:
        raise SystemExit("No resume found. Pass --resume <file> or put a PDF in the candidate folder.")
    resume_text = read_pdf_text(resume)

    # Gather jobs: either explicit URLs, or the first N live jobs from a board.
    jobs: list[Job] = []
    if args.urls:
        for u in args.urls:
            jobs.append(_fetch_job(u))
    else:
        c = GreenhouseClient()
        try:
            live = c.list_jobs(args.board, content=True)
        finally:
            c.close()
        for raw in live[: args.count]:
            jobs.append(Job(board=raw.board, job_id=raw.job_id, title=raw.title,
                            location=raw.location, url=raw.absolute_url, content=raw.content))
    print(f"Fit-scoring + batch tailoring {len(jobs)} job(s) for {args.name} "
          f"({args.workers} workers, fit>={args.fit})...")
    out = batch_tailor(resume_text, jobs, args.name, max_workers=args.workers,
                       fit_threshold=args.fit, on_progress=print)
    results = out["tailored"]
    golden = sum(1 for r in results if r.get("golden"))
    print(f"\n=== {golden}/{len(results)} GOLDEN (ATS>=75) | {len(out['skipped'])} skipped (poor fit) ===")
    print("Ranked by job fit:")
    for i, r in enumerate(results[:15], 1):
        if "error" in r:
            print(f"{i:>2}. FAILED  {r['title'][:46]}")
        else:
            g = "GOLD" if r["golden"] else "----"
            print(f"{i:>2}. [{g}] fit {r['fit_score']:>3.0f}  ATS {r['score_before']:>3}->{r['score_after']:>3}  {r['title'][:42]}")
    print(f"\nSaved per-job resumes + SUMMARY.md in candidates/{_slug(args.name)}/tailored/")


def cmd_daily(args):
    """Daily fresh-links crawl: fresh + good-fit jobs for the candidate, ranked."""
    boards = args.boards or ["stripe", "databricks", "anthropic", "gitlab"]
    print(f"Daily crawl for {args.name}: {len(boards)} boards, fresh<={args.days}d, fit>={args.fit}")
    shortlist = daily_crawl(args.name, boards, max_days=args.days,
                            min_fit=args.fit, on_progress=print)
    print(f"\n=== {len(shortlist)} fresh + matching jobs today ===")
    for r in shortlist[:20]:
        print(f"  {r['match']:>3}% [{r.get('verdict','')[:9]:<9}] {r['days_ago']:>2}d ago  {r['title'][:40]} ({r['company']})")
    print(f"\nSaved -> candidates/{_slug(args.name)}/daily_shortlist.csv")


def cmd_run_daily(args):
    """Full daily pipeline for ONE client: crawl fresh+fit -> golden tailor top N."""
    s = run_candidate_daily(args.name, args.boards, max_days=args.days, min_fit=args.fit,
                            top_n=args.top, workers=args.workers, use_seed=args.seed,
                            seed_limit=args.seed_limit, on_progress=print)
    print(f"\n=== {args.name}: {s.get('golden',0)}/{s.get('tailored',0)} golden, "
          f"from {s.get('fresh_fit_jobs',0)} fresh+fit jobs ===")


def cmd_run_all(args):
    """Run the daily pipeline for EVERY client."""
    reports = run_all_candidates(args.boards, max_days=args.days, min_fit=args.fit,
                                 top_n=args.top, workers=args.workers, use_seed=args.seed,
                                 seed_limit=args.seed_limit, on_progress=print)
    print("\n=== ALL CLIENTS — daily report ===")
    for r in reports:
        if "error" in r:
            print(f"  {r['candidate']:<20} ERROR: {r['error'][:40]}")
        else:
            print(f"  {r['candidate']:<20} {r['golden']}/{r['tailored']} golden "
                  f"({r['fresh_fit_jobs']} fresh+fit)")


def cmd_build_cache(args):
    """Sweep the seed boards once to find which have jobs (the live-token cache)."""
    from .discover.sweep import build_live_cache
    live = build_live_cache(limit_per_ats=args.limit, max_workers=args.workers, on_progress=print)
    total = sum(len(v) for v in live.values())
    print(f"\nLive-token cache built: {total} live boards "
          f"({', '.join(f'{a}:{len(v)}' for a,v in live.items())}) -> seed/live_tokens.json")


def cmd_show(args):
    p = load_profile(args.name)
    print(json.dumps(json.loads(p.model_dump_json()), indent=2)[:2000])


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_").lower()


def _find_resume(name: str, override: str | None) -> str | None:
    if override:
        return override
    d = config.candidate_dir(name)
    for pat in ("*.pdf", "*.docx"):
        hits = sorted(d.glob(pat))
        if hits:
            return str(hits[0])
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="applyportal", description="End-to-end job-apply for any candidate")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="parse resume -> profile"); a.add_argument("name"); a.add_argument("resume"); a.set_defaults(func=cmd_add)
    c = sub.add_parser("complete", help="fill extra fields from intake.json"); c.add_argument("name"); c.add_argument("intake"); c.set_defaults(func=cmd_complete)
    s = sub.add_parser("show", help="print profile"); s.add_argument("name"); s.set_defaults(func=cmd_show)
    ta = sub.add_parser("tailor-all", help="batch-tailor resume to many jobs at once")
    ta.add_argument("name")
    ta.add_argument("--resume", help="resume file (defaults to one in candidate folder)")
    ta.add_argument("--board", default="", help="Greenhouse board token to pull jobs from")
    ta.add_argument("--count", type=int, default=5, help="how many jobs from the board")
    ta.add_argument("--urls", nargs="*", help="explicit job URLs instead of a board")
    ta.add_argument("--workers", type=int, default=3, help="parallel tailoring workers")
    ta.add_argument("--fit", type=int, default=55, help="min fit score to tailor a job (0-100)")
    ta.set_defaults(func=cmd_tailor_all)
    dl = sub.add_parser("daily", help="daily fresh-links crawl: fresh + good-fit jobs")
    dl.add_argument("name")
    dl.add_argument("--boards", nargs="*", help="ATS board tokens (default: a few)")
    dl.add_argument("--days", type=int, default=7, help="max posting age in days (freshness)")
    dl.add_argument("--fit", type=int, default=50, help="min fit score (0-100)")
    dl.set_defaults(func=cmd_daily)

    bc = sub.add_parser("build-cache", help="sweep seed boards to find live ones (run periodically)")
    bc.add_argument("--limit", type=int, default=None, help="max boards per ATS (default: all)")
    bc.add_argument("--workers", type=int, default=12, help="parallel fetch workers")
    bc.set_defaults(func=cmd_build_cache)

    for cmd, fn, helptxt in (("run-daily", cmd_run_daily, "full daily pipeline for ONE client"),
                             ("run-all", cmd_run_all, "full daily pipeline for ALL clients")):
        p = sub.add_parser(cmd, help=helptxt)
        if cmd == "run-daily":
            p.add_argument("name")
        p.add_argument("--boards", nargs="*", help="ATS board tokens (default: a few)")
        p.add_argument("--days", type=int, default=7, help="max posting age in days (freshness)")
        p.add_argument("--fit", type=int, default=55, help="min fit score")
        p.add_argument("--top", type=int, default=8, help="how many top-fit jobs to tailor")
        p.add_argument("--workers", type=int, default=3, help="parallel tailoring workers")
        p.add_argument("--seed", action="store_true", help="sweep the big multi-ATS seed lists (15k boards)")
        p.add_argument("--seed-limit", type=int, default=400, help="max boards per ATS when using --seed")
        p.set_defaults(func=fn)
    ap_ = sub.add_parser("apply", help="answer + review (+optional fill/submit) one job URL")
    ap_.add_argument("name"); ap_.add_argument("url")
    ap_.add_argument("--resume", help="resume file to upload (defaults to one in candidate folder)")
    ap_.add_argument("--fill", action="store_true", help="open browser and fill (no submit)")
    ap_.add_argument("--submit", action="store_true", help="fill AND submit (if nothing needs review)")
    ap_.add_argument("--headless", action="store_true")
    ap_.add_argument("--live", action="store_true",
                     help="use the candidate's REAL email/phone (default: dummy test contact)")
    ap_.set_defaults(func=cmd_apply)

    try:  # ensure unicode output works on the Windows console
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
