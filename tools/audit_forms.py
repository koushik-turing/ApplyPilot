"""
Form audit — fetch many REAL job forms, categorize every question, run the answer engine,
and surface real issues so we can evolve the engine. Run: python tools/audit_forms.py

Phase 1 (fast, no AI): gather ~N forms, categorize questions, frequency report.
Phase 2 (AI): run answer_form on a sample for a candidate; record fills / needs_human /
select-skips / low-confidence / doubts.
"""
from __future__ import annotations

import json
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

# Broad, multi-industry board list + a sample from the seed lists for variety.
_CURATED = [
    # fintech / finance
    "affirm", "stripe", "robinhood", "coinbase", "plaid", "brex", "ramp", "sofi", "chime",
    "marqeta", "mercury", "gusto", "betterment", "wealthsimple",
    # data / dev / infra
    "databricks", "snowflake", "datadog", "gitlab", "hashicorp", "confluent", "cockroachlabs",
    "temporal", "fivetran", "vercel", "retool", "cribl", "samsara", "benchling",
    # ai
    "anthropic", "openai", "scaleai", "huggingface", "cohere", "runwayml",
    # consumer / marketplace
    "discord", "reddit", "instacart", "doordash", "airtable", "notion", "asana", "figma",
    "duolingo", "grammarly", "faire", "whatnot", "warbyparker", "thredup",
    # hr / ops / saas
    "rippling", "deel", "lattice", "webflow", "zapier", "calendly", "loom",
    # health
    "oscar", "devoted", "included-health", "hims", "ro",
]

FORMS_TARGET = 180
ANSWER_SAMPLE = 25          # how many forms to run the full answer engine on
SEED_SAMPLE = 60            # extra boards sampled from the seed list for variety


def _boards() -> list[str]:
    out = list(dict.fromkeys(_CURATED))
    try:
        seed = json.loads((Path(__file__).resolve().parent.parent / "seed" /
                           "greenhouse_companies.json").read_text(encoding="utf-8"))
        step = max(1, len(seed) // SEED_SAMPLE)
        out += [seed[i] for i in range(0, len(seed), step)]
    except Exception:
        pass
    return list(dict.fromkeys(out))


BOARDS = None  # set in main()


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


def gather_forms(boards: list[str], target: int) -> list[Job]:
    c = GreenhouseClient()
    forms: list[Job] = []
    try:
        for board in boards:
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
    boards = _boards()
    print(f"Gathering real job forms from {len(boards)} boards...", flush=True)
    forms = gather_forms(boards, FORMS_TARGET)
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
    doubts: Counter = Counter()            # distinct REQUIRED questions flagged needs_human
    claude_qs: Counter = Counter()         # distinct questions that fell to Claude (L3)
    for job in forms[:ANSWER_SAMPLE]:
        try:
            sheet = answer_form(job, prof, "Sai Manikanta")
        except Exception as e:
            print(f"  [{job.board}] answer_form FAILED: {type(e).__name__}")
            continue
        for a in sheet.answers:
            src_counter[a.source.value] += 1
            lab = re.sub(r"\s+", " ", a.label.strip())[:70]
            if a.needs_human:
                doubts[lab] += 1
            if a.source.value == "claude":
                claude_qs[lab] += 1
        print(f"  [{job.board}] {job.title[:30]}: {len(sheet.answers)} Qs, "
              f"doubts={sum(1 for a in sheet.answers if a.needs_human)}", flush=True)

    print("\nANSWER SOURCES:", dict(src_counter))
    tot = sum(src_counter.values()) or 1
    print(f"  -> {100*(src_counter['deterministic']+src_counter['cache'])/tot:.0f}% no-AI, "
          f"{100*src_counter['claude']/tot:.0f}% Claude")
    print(f"\nGENUINE DOUBTS to raise to recruiter (distinct required Qs) — {len(doubts)}:")
    for lab, n in doubts.most_common(30):
        print(f"  ?{n:>2}x  {lab}")
    print(f"\nQUESTIONS THAT FELL TO CLAUDE (candidates for new deterministic handlers) — {len(claude_qs)}:")
    for lab, n in claude_qs.most_common(30):
        print(f"  {n:>2}x  {lab}")


if __name__ == "__main__":
    main()
