"""
Crawl a candidate's fresh US matches from ALL live boards (uses the live-token cache) and
write the shortlist + jobs cache + an Excel. No upfront tailoring (that's on-demand).

Usage: python tools/crawl_candidate.py "<Candidate Name>" [max_days] [min_fit] [workers]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from openpyxl import Workbook

from src import config
from src.discover.sweep import sweep_targets
from src.discover.daily import scored_fresh_multi, shortlist_row, _save, _save_jobs_cache


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "Sai Manikanta"
    max_days = int(sys.argv[2]) if len(sys.argv) > 2 else 14
    min_fit = int(sys.argv[3]) if len(sys.argv) > 3 else 45
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 24
    slug = "".join(c if c.isalnum() else "_" for c in name).strip("_").lower()

    targets = sweep_targets(limit_per_ats=99999, use_cache=True)
    print("Sweeping live boards:", {a: len(v) for a, v in targets.items()}, flush=True)

    graded = scored_fresh_multi(name, targets, max_days=max_days, min_fit=min_fit,
                                max_workers=workers, on_progress=print)
    shortlist = [shortlist_row(r, j) for r, j in graded]
    _save(shortlist, name)
    _save_jobs_cache(graded, name)
    print(f"\nSHORTLIST SIZE: {len(shortlist)}", flush=True)

    # Excel into the workspace (manikanta/ for Sai, else candidate folder)
    ws_dir = (config.ROOT / "manikanta") if slug == "sai_manikanta" else config.candidate_dir(name)
    ws_dir.mkdir(parents=True, exist_ok=True)
    wb = Workbook(); ws = wb.active; ws.title = "Matches"
    ws.append(["Match %", "Verdict", "Days Ago", "Posted On", "Sponsors H-1B", "H-1B Approvals",
               "Job Title", "Company", "Location", "Job Link"])
    keys = ["match", "verdict", "days_ago", "posted_on", "sponsors_h1b", "h1b_approvals",
            "title", "company", "location", "url"]
    for r in sorted(shortlist, key=lambda x: -float(x.get("match") or 0)):
        ws.append([r.get(k, "") for k in keys])
    xlsx = ws_dir / f"{slug}_job_matches.xlsx"
    wb.save(str(xlsx))
    print(f"Excel saved -> {xlsx}", flush=True)

    print("TOP 12:")
    for r in sorted(shortlist, key=lambda x: -float(x.get("match") or 0))[:12]:
        print(f"  {r['match']}%  {r['days_ago']}d  {r['title'][:42]}  [{r['company']}]")


if __name__ == "__main__":
    main()
