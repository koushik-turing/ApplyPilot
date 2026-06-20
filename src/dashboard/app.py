"""
Dashboard — the web UI over the whole portal (Jobright-style, multi-client).

Shows every client, their daily fresh+fit shortlist, golden tailored resumes, and lets
you trigger a daily run per client or for everyone. Reads the candidates/ data the
pipeline produces. Serves its own frontend at "/".

Run:  python -m uvicorn src.dashboard.app:app --port 8050
"""
from __future__ import annotations

import csv
import json
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import config
from ..models import Profile
from ..pipeline import list_candidates, run_candidate_daily, run_all_candidates

app = FastAPI(title="Job Portal Dashboard")

# In-memory run status so the UI can show "running…" without a database.
_runs: dict[str, str] = {}     # candidate (or "__all__") -> "running" | "done" | "error: ..."
_lock = threading.Lock()


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_").lower()


def _read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _read_shortlist(d: Path) -> list[dict]:
    f = d / "daily_shortlist.csv"
    if not f.exists():
        return []
    with open(f, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _client_card(slug: str) -> dict:
    d = config.CANDIDATES_DIR / slug
    prof = _read_json(d / "profile.json") or {}
    run = _read_json(d / "daily_run.json") or {}
    shortlist = _read_shortlist(d)
    tailored = list((d / "tailored").glob("*.json")) if (d / "tailored").exists() else []
    return {
        "slug": slug,
        "name": prof.get("full_name") or slug,
        "titles": prof.get("target_titles", [])[:3],
        "skills_count": len(prof.get("skills", [])),
        "years": prof.get("years_experience"),
        "shortlist_count": len(shortlist),
        "golden": run.get("golden", 0),
        "tailored": run.get("tailored", len(tailored)),
        "status": _runs.get(slug, "idle"),
    }


@app.get("/api/clients")
def clients():
    return {"clients": [_client_card(s) for s in list_candidates()],
            "all_status": _runs.get("__all__", "idle")}


@app.get("/api/clients/{slug}")
def client_detail(slug: str):
    d = config.CANDIDATES_DIR / slug
    if not (d / "profile.json").exists():
        raise HTTPException(404, "unknown client")
    prof = _read_json(d / "profile.json") or {}
    tailored = []
    tdir = d / "tailored"
    if tdir.exists():
        for f in sorted(tdir.glob("*.json")):
            r = _read_json(f) or {}
            tailored.append({
                "title": r.get("title"), "url": r.get("url"),
                "fit_score": r.get("fit_score"), "score_before": r.get("score_before"),
                "score_after": r.get("score_after"), "golden": r.get("golden"),
                "location": r.get("location"), "file": f.name,
                "changes": (r.get("changes") or [])[:6],
            })
    tailored.sort(key=lambda r: (r.get("fit_score") or 0, r.get("score_after") or 0), reverse=True)
    return {
        "card": _client_card(slug),
        "profile": {k: prof.get(k) for k in
                    ("full_name", "email", "location", "years_experience", "skills",
                     "target_titles", "work_auth", "desired_salary")},
        "shortlist": _read_shortlist(d)[:50],
        "tailored": tailored,
    }


@app.get("/api/clients/{slug}/resume/{fname}")
def download_resume(slug: str, fname: str, fmt: str = "pdf"):
    """Render a tailored resume to PDF via the ATS engine and stream it."""
    import httpx
    f = config.CANDIDATES_DIR / slug / "tailored" / fname
    r = _read_json(f)
    if not r or "tailored_resume" not in r:
        raise HTTPException(404, "tailored resume not found")
    try:
        resp = httpx.post("http://127.0.0.1:8000/api/export", params={"format": fmt, "template": "modern"},
                          json=r["tailored_resume"], timeout=60)
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(503, f"ATS engine not available for export: {e}")
    base = (r.get("title") or "resume").replace(" ", "_")[:40]
    return StreamingResponse(iter([resp.content]), media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{base}.{fmt}"'})


def _bg_run(key: str, fn, *args, **kw):
    with _lock:
        _runs[key] = "running"
    try:
        fn(*args, **kw)
        _runs[key] = "done"
    except Exception as e:
        _runs[key] = f"error: {type(e).__name__}"


@app.post("/api/clients/{slug}/run")
def run_one(slug: str, days: int = 7, fit: int = 55, top: int = 5):
    name = (_read_json(config.CANDIDATES_DIR / slug / "profile.json") or {}).get("full_name", slug)
    threading.Thread(target=_bg_run, args=(slug, run_candidate_daily, name),
                     kwargs={"max_days": days, "min_fit": fit, "top_n": top}, daemon=True).start()
    return {"status": "started"}


@app.post("/api/run-all")
def run_everyone(days: int = 7, fit: int = 55, top: int = 5):
    threading.Thread(target=_bg_run, args=("__all__", run_all_candidates),
                     kwargs={"max_days": days, "min_fit": fit, "top_n": top}, daemon=True).start()
    return {"status": "started"}


# serve the frontend last
_STATIC = Path(__file__).resolve().parent / "static"
if _STATIC.is_dir():
    app.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="static")
