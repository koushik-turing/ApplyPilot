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
from .discover.ats_client import GreenhouseClient, parse_greenhouse_url
from .models import Job, FormQuestion
from .profile.complete import complete_profile, load_profile
from .profile.parse import parse_resume, save_profile, read_pdf_text
from .submit.apply import build_review, save_review, fill_form
from .tailor.batch import batch_tailor


def cmd_add(args):
    prof = parse_resume(args.resume)
    path = save_profile(prof, args.name)
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
    parsed = parse_greenhouse_url(url)
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
    print(f"Batch tailoring {len(jobs)} job(s) for {args.name} with {args.workers} workers...")
    results = batch_tailor(resume_text, jobs, args.name,
                           max_workers=args.workers, on_progress=print)
    print("\n=== RANKED (best match first) ===")
    for i, r in enumerate(results[:15], 1):
        if "error" in r:
            print(f"{i:>2}. FAILED  {r['title'][:50]}  ({r['error'][:30]})")
        else:
            print(f"{i:>2}. {r['score_after']:>3} (was {r['score_before']:>3})  {r['title'][:50]}")
    print(f"\nSaved per-job resumes + SUMMARY.md in candidates/{_slug(args.name)}/tailored/")


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
    ta.set_defaults(func=cmd_tailor_all)
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
