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

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import config
from ..models import Profile
from ..pipeline import list_candidates, run_candidate_daily, run_all_candidates
from ..profile.parse import parse_resume, save_profile
from ..profile.complete import complete_profile, load_profile

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


@app.post("/api/clients")
async def create_client(
    file: UploadFile = File(...),
    name: str = Form(""),
    email: str = Form(""),
    visa_status: str = Form(""),
    requires_sponsorship: str = Form(""),
    authorized_us: str = Form(""),
    desired_salary: str = Form(""),
    locations: str = Form(""),
):
    """Add a candidate: parse their resume into a personalized profile + intake details."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty resume file")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.DATA_DIR / f"_upload_{file.filename}"
    tmp.write_bytes(data)
    try:
        prof = parse_resume(str(tmp))
    except Exception as e:
        raise HTTPException(422, f"could not parse resume: {e}")
    finally:
        tmp.unlink(missing_ok=True)

    if email.strip():
        prof.email = email.strip()
    cand_name = name.strip() or prof.full_name or "candidate"
    if name.strip():
        prof.full_name = name.strip()    # recruiter-provided name is also the display name
    save_profile(prof, cand_name)
    # keep the resume in the candidate folder (the pipeline needs it)
    (config.candidate_dir(cand_name) / file.filename).write_bytes(data)

    intake: dict = {}
    if visa_status.strip():
        intake["visa_status"] = visa_status.strip()
    if requires_sponsorship:
        intake["requires_sponsorship"] = requires_sponsorship
    if authorized_us:
        intake["authorized_us"] = authorized_us
    if desired_salary.strip():
        intake["desired_salary"] = desired_salary.strip()
    if locations.strip():
        intake["preferred_locations"] = locations.strip()
    if intake:
        complete_profile(cand_name, intake)

    return {"slug": _slug(cand_name), "card": _client_card(_slug(cand_name))}


@app.patch("/api/clients/{slug}")
def edit_client(slug: str, payload: dict):
    """Edit a candidate's profile fields (visa/salary/skills/titles/email...)."""
    d = config.CANDIDATES_DIR / slug
    if not (d / "profile.json").exists():
        raise HTTPException(404, "unknown client")
    prof = load_profile_by_slug(slug)
    for k in ("full_name", "email", "location", "desired_salary"):
        if k in payload and isinstance(payload[k], str):
            setattr(prof, k, payload[k])
    if "years_experience" in payload:
        try:
            prof.years_experience = float(payload["years_experience"])
        except (TypeError, ValueError):
            pass
    if "skills" in payload and isinstance(payload["skills"], list):
        prof.skills = [str(s) for s in payload["skills"]]
    if "target_titles" in payload and isinstance(payload["target_titles"], list):
        prof.target_titles = [str(t) for t in payload["target_titles"]]
    wa = payload.get("work_auth") or {}
    if "visa_status" in wa:
        prof.work_auth.visa_status = str(wa["visa_status"])
    if "requires_sponsorship" in wa:
        prof.work_auth.requires_sponsorship = _as_bool(wa["requires_sponsorship"])
    if "authorized_us" in wa:
        prof.work_auth.authorized_us = _as_bool(wa["authorized_us"])
    if "answer_bank" in payload and isinstance(payload["answer_bank"], dict):
        # replace with the provided set (drop blanks) so the recruiter can edit/remove entries
        prof.answer_bank = {k: str(v).strip() for k, v in payload["answer_bank"].items() if str(v).strip()}
    (d / "profile.json").write_text(prof.model_dump_json(indent=2), encoding="utf-8")
    return {"ok": True, "card": _client_card(slug)}


@app.delete("/api/clients/{slug}")
def delete_client(slug: str):
    import shutil
    d = config.CANDIDATES_DIR / slug
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


def load_profile_by_slug(slug: str) -> Profile:
    return Profile(**json.loads((config.CANDIDATES_DIR / slug / "profile.json").read_text(encoding="utf-8")))


def _as_bool(v):
    s = str(v).strip().lower()
    return True if s in {"true", "yes", "1", "y"} else False if s in {"false", "no", "0", "n"} else None


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
                     "target_titles", "work_auth", "desired_salary", "answer_bank")},
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
