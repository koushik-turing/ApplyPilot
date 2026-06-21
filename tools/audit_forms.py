"""
Form audit — fetch many REAL job forms, categorize every question, run the answer engine,
and surface real issues so we can evolve the engine. Run: python tools/audit_forms.py

Phase 1 (fast, no AI): gather ~N forms, categorize questions, frequency report.
Phase 2 (AI): run answer_form on a sample for a candidate; record fills / needs_human /
select-skips / low-confidence / doubts.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")   # job titles can contain non-latin chars
except Exception:
    pass

from src.discover.ats_client import GreenhouseClient
from src.models import Job, FormQuestion
from src.profile.complete import load_profile
from src.answer.engine import answer_form

# Boards known to have live jobs + rich forms (mix of domains).
BOARDS = ["affirm", "stripe", "databricks", "anthropic", "gitlab", "discord", "robinhood",
          "coinbase", "airtable", "instacart", "doordash", "reddit", "plaid", "brex",
          "scaleai", "ramp", "figma", "notion", "asana", "datadog"]

FORMS_TARGET = 70
ANSWER_SAMPLE = 12          # how many forms to run the full answer engine on


def categorize(q: FormQuestion) -> str:
    lab = q.label.lower()
    fn = " ".join(q.field_names).lower()
    if q.field_type == "input_file" or "resume" in fn or "cover_letter" in fn:
        return "file"
    if any(k in fn or re.search(rf"\b{k}\b", lab) for k in ("first_name", "last_name", "email", "phone")):
        return "identity"
    if any(k in lab for k in ("linkedin", "github", "portfolio", "website", "twitter")):
        return "links"
    if re.search(r"gender|pronoun|\brace\b|ethnic|hispanic|veteran|disabilit|self.?identif|orientation", lab):
        return "eeo"
    if "sponsorship" in lab or ("visa" in lab) or "authorized to work" in lab or "work authorization" in lab:
        return "work_auth"
    if any(k in lab for k in ("salary", "compensation", "desired pay", "expected pay", "rate")):
        return "compensation"
    if any(k in lab for k in ("location", "city", "state", "reside", "based", "relocat", "remote")):
        return "location"
    if q.options:
        opts = {str(o.get("label", "")).strip().lower() for o in q.options}
        if opts <= {"yes", "no"} or opts == {"yes", "no"}:
            return "select_yesno"
        return "select_multi"
    if q.field_type == "textarea":
        return "free_text_long"
    return "free_text_short"


def gather_forms(target: int) -> list[Job]:
    c = GreenhouseClient()
    forms: list[Job] = []
    try:
        for board in BOARDS:
            if len(forms) >= target:
                break
            try:
                jobs = c.list_jobs(board)
            except Exception:
                continue
            for j in jobs[:5]:
                if len(forms) >= target:
                    break
                try:
                    raw = c.get_job_form(board, j.job_id)
                    forms.append(Job(board=raw.board, job_id=raw.job_id, title=raw.title,
                                     location=raw.location, url=raw.absolute_url, content=raw.content,
                                     questions=[FormQuestion(label=q.label, required=q.required,
                                                field_type=q.field_type, field_names=q.field_names,
                                                options=q.options) for q in raw.questions]))
                except Exception:
                    continue
            print(f"  {board}: gathered (total forms={len(forms)})", flush=True)
    finally:
        c.close()
    return forms


def main():
    print("Gathering real job forms...", flush=True)
    forms = gather_forms(FORMS_TARGET)
    print(f"\nGathered {len(forms)} forms.\n")

    # ---- Phase 1: question-type frequency across ALL forms ----
    cat_counter: Counter = Counter()
    label_counter: Counter = Counter()
    multi_examples: list[str] = []
    for job in forms:
        for q in job.questions:
            cat = categorize(q)
            cat_counter[cat] += 1
            label_counter[re.sub(r"\s+", " ", q.label.strip())[:70]] += 1
            if cat == "select_multi" and len(multi_examples) < 25:
                multi_examples.append(f"{q.label.strip()[:55]}  ({len(q.options)} opts)")

    total_q = sum(cat_counter.values())
    print("=" * 64)
    print(f"QUESTION TYPES across {len(forms)} forms ({total_q} questions):")
    for cat, n in cat_counter.most_common():
        print(f"  {cat:18} {n:>4}  ({100*n/total_q:.0f}%)")
    print("\nMOST COMMON QUESTION LABELS:")
    for lab, n in label_counter.most_common(25):
        print(f"  {n:>3}x  {lab}")
    print("\nSAMPLE multi-option (non-yes/no) selects (these are the tricky ones):")
    for ex in multi_examples:
        print(f"  - {ex}")

    # ---- Phase 2: run the answer engine on a sample, collect issues ----
    prof = load_profile("Sai Manikanta")
    print("\n" + "=" * 64)
    print(f"ANSWER-ENGINE RUN on {ANSWER_SAMPLE} forms (candidate: {prof.full_name}):")
    src_counter: Counter = Counter()
    needs_human: list[str] = []
    skipped_selects: list[str] = []
    low_conf: list[str] = []
    for job in forms[:ANSWER_SAMPLE]:
        try:
            sheet = answer_form(job, prof, "Sai Manikanta")
        except Exception as e:
            print(f"  [{job.board}] answer_form FAILED: {type(e).__name__}")
            continue
        qmap = {a.label: q for q in job.questions for a in [type("o", (), {"label": q.label})()]}
        for a in sheet.answers:
            src_counter[a.source.value] += 1
            q = next((qq for qq in job.questions if qq.label == a.label), None)
            is_sel = bool(q and q.options)
            if a.needs_human:
                needs_human.append(f"[{job.board}] {a.label.strip()[:60]}")
            elif is_sel and not a.value:
                skipped_selects.append(f"[{job.board}] {a.label.strip()[:60]}")
        print(f"  [{job.board}] {job.title[:34]}: {len(sheet.answers)} Qs, "
              f"needs_human={sum(1 for a in sheet.answers if a.needs_human)}", flush=True)

    print("\nANSWER SOURCES:", dict(src_counter))
    print(f"\nNEEDS-HUMAN (doubts to raise to recruiter) — {len(needs_human)}:")
    for x in needs_human[:30]:
        print(f"  ? {x}")
    if skipped_selects:
        print(f"\nSELECTS WITH NO ANSWER — {len(skipped_selects)}:")
        for x in skipped_selects[:20]:
            print(f"  - {x}")


if __name__ == "__main__":
    main()
