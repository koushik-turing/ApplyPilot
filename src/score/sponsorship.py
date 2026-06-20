"""
H-1B sponsorship layer — tag each job with whether the employer actually sponsors H-1B,
from real USCIS H-1B Employer Data Hub records (not "big company so probably").

This is the moat for visa candidates (like MigrateMate): we match a job's company to its
USCIS record and attach the recent H-1B approval count. For a candidate who needs
sponsorship, jobs at non-sponsors are a knockout.

  build_lookup()  -> process the USCIS CSVs into sponsorship/h1b_sponsors.json (run once)
  info(company)   -> {sponsors: bool, approvals: int, matched: str}
  tag_jobs(jobs)  -> set job.sponsors_h1b on each (in place)
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .. import config

DATA_DIR = config.ROOT / "sponsorship"
LOOKUP_FILE = DATA_DIR / "h1b_sponsors.json"
_CSV_GLOB = "USCIS_H1B_Employer_DataHub_*.csv"

# Corporate suffixes/noise to strip so "Google LLC" == "Google Inc" == "google".
_SUFFIX = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c|corp|corporation|ltd|limited|co|company|lp|llp|pllc|"
    r"plc|gmbh|pvt|private|technologies|technology|labs|software|solutions|systems|group|"
    r"holdings|usa|na|the)\b", re.I)
_DBA = re.compile(r"\bdba\b.*$", re.I)        # drop "DBA ..." trailing alias


def normalize(name: str) -> str:
    s = (name or "").lower()
    s = _DBA.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


_lookup: dict[str, int] | None = None


def build_lookup(*, on_progress=None) -> dict[str, int]:
    """Aggregate normalized employer -> max single-year Initial Approvals across all CSVs."""
    out: dict[str, int] = {}
    files = sorted(DATA_DIR.glob(_CSV_GLOB))
    for f in files:
        with open(f, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                emp = (row.get("Employer") or "").strip()
                if not emp:
                    continue
                try:
                    approvals = int(float(row.get("Initial Approval", 0) or 0))
                except ValueError:
                    approvals = 0
                key = normalize(emp)
                if key:
                    out[key] = max(out.get(key, 0), approvals)
        if on_progress:
            on_progress(f"  processed {f.name}: {len(out)} employers so far")
    DATA_DIR.mkdir(exist_ok=True)
    LOOKUP_FILE.write_text(json.dumps(out), encoding="utf-8")
    return out


def load() -> dict[str, int]:
    global _lookup
    if _lookup is None:
        if LOOKUP_FILE.exists():
            _lookup = json.loads(LOOKUP_FILE.read_text(encoding="utf-8"))
        else:
            _lookup = build_lookup()
    return _lookup


def info(company: str) -> dict:
    """Sponsor lookup for a company name. Tries exact normalized match, then a
    first-significant-token match (so 'stripe' matches 'STRIPE INC')."""
    table = load()
    key = normalize(company)
    if not key:
        return {"sponsors": None, "approvals": 0, "matched": ""}
    if key in table:
        return {"sponsors": table[key] > 0, "approvals": table[key], "matched": key}
    # fallback: the company's first token is a unique employer key
    head = key.split()[0] if key.split() else ""
    if len(head) >= 4 and head in table:
        return {"sponsors": table[head] > 0, "approvals": table[head], "matched": head}
    # not in the USCIS data at all -> UNKNOWN (None), not a confirmed non-sponsor.
    return {"sponsors": None, "approvals": 0, "matched": ""}


def tag_jobs(jobs) -> list:
    """Set job.sponsors_h1b (bool|None) + job.h1b_approvals on each job (in place)."""
    for j in jobs:
        company = getattr(j, "board", "") or ""
        i = info(company)
        setattr(j, "sponsors_h1b", i["sponsors"])
        setattr(j, "h1b_approvals", i["approvals"])
    return jobs
