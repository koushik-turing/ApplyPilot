"""FastAPI app — the ATS Resume Maker backend.

Endpoints
  GET  /api/health           -> service + AI availability
  POST /api/parse            -> upload file, get extracted text + structured resume
  POST /api/score            -> score a resume (file or text) against optional JD
  POST /api/tailor           -> rewrite resume to fit JD, with before/after scores
  POST /api/export           -> render a structured resume to docx/pdf/txt

The browser UI in ../../frontend is served at "/" so there's no CORS to configure.
"""
from __future__ import annotations
import io
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from . import parsing, extract, scoring, tailor, export, llm, polish, claude_client, review
from .schemas import Resume, ScoreReport, TailorResponse

app = FastAPI(title="ATS Resume Maker API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_BYTES = 8 * 1024 * 1024  # 8 MB


async def _read(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large (max 8 MB).")
    return data


@app.get("/api/health")
def health():
    claude = claude_client.claude_available()
    ollama = llm.ollama_running()
    if claude:
        engine, model, note = "claude", settings.claude_model, None
    elif ollama:
        engine, model, note = "ollama", settings.llm_model, None
    else:
        engine, model = "rule-based", None
        note = ("No AI configured. Set ANTHROPIC_API_KEY (best) or start Ollama to enable "
                "AI rewriting. Offline ATS scoring + honest tailoring still work.")
    return {
        "status": "ok",
        "ai_available": claude or ollama,
        "engine": engine,
        "model": model,
        "note": note,
    }


@app.post("/api/parse")
async def parse(file: UploadFile = File(...)):
    data = await _read(file)
    try:
        text = parsing.extract_text(file.filename, data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    resume = extract.parse_resume(text)
    return {"text": text, "resume": resume.model_dump(), "ai_available": llm.ollama_running()}


@app.post("/api/score", response_model=ScoreReport)
async def score(
    file: UploadFile | None = File(None),
    resume_text: str | None = Form(None),
    job_description: str | None = Form(None),
):
    if file is not None:
        data = await _read(file)
        try:
            text = parsing.extract_text(file.filename, data)
        except ValueError as e:
            raise HTTPException(422, str(e))
    elif resume_text:
        text = resume_text
    else:
        raise HTTPException(400, "Provide a resume file or resume_text.")

    resume = extract.parse_resume(text)
    jd = extract.parse_jd(job_description) if job_description and job_description.strip() else None
    report = scoring.score_resume(text, resume, jd, job_description)
    # Add a thorough, recruiter-grade AI review when Claude is available (optional).
    report.ai_review = review.ai_review(text, resume, jd, report)
    return report


@app.post("/api/tailor", response_model=TailorResponse)
async def tailor_endpoint(
    file: UploadFile | None = File(None),
    resume_text: str | None = Form(None),
    job_description: str = Form(...),
):
    if not job_description.strip():
        raise HTTPException(400, "A job description is required for tailoring.")

    if file is not None:
        data = await _read(file)
        try:
            text = parsing.extract_text(file.filename, data)
        except ValueError as e:
            raise HTTPException(422, str(e))
    elif resume_text:
        text = resume_text
    else:
        raise HTTPException(400, "Provide a resume file or resume_text.")

    resume = extract.parse_resume(text)
    jd = extract.parse_jd(job_description)

    before = scoring.score_resume(text, resume, jd, job_description)

    # Scorer the tailoring loop uses to verify/retry — mirrors the FINAL scoring path
    # exactly (polish, then score the rendered text) so "after" matches what we return.
    def _score_candidate(cand: Resume) -> int:
        polished, _ = polish.polish_resume(cand.model_copy(deep=True))
        return scoring.score_resume(export.to_text(polished), polished, jd, job_description).overall

    tailored, changes, engine = tailor.tailor_resume(
        resume, jd, before.missing_keywords, full_text=text,
        scorer=_score_candidate, target=80,
    )
    # Legitimate, non-fabricating standardization so the output is industry-standard
    # and never loses ATS points to cosmetic/parse issues.
    tailored, polish_notes = polish.polish_resume(tailored)
    changes += polish_notes
    after = scoring.score_resume(export.to_text(tailored), tailored, jd, job_description)

    return TailorResponse(
        tailored_resume=tailored, changes=changes,
        score_before=before, score_after=after,
        ai_used=engine != "rule-based", engine=engine,
    )


@app.post("/api/export")
async def export_endpoint(resume: Resume, format: str = "pdf", template: str = "modern"):
    resume, _ = polish.polish_resume(resume)  # guarantee a clean, standard document
    fmt = format.lower()
    if fmt == "docx":
        data = export.to_docx(resume, template=template)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ext = "docx"
    elif fmt == "pdf":
        data = export.to_pdf(resume, template=template)
        media, ext = "application/pdf", "pdf"
    elif fmt == "txt":
        data = export.to_text(resume).encode("utf-8")
        media, ext = "text/plain", "txt"
    else:
        raise HTTPException(400, "format must be one of: pdf, docx, txt")

    base = (resume.name or "resume").strip().replace(" ", "_") or "resume"
    return StreamingResponse(
        io.BytesIO(data),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{base}_tailored.{ext}"'},
    )


# --- serve the browser UI last so it doesn't shadow the /api routes ---
_FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"
if _FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")
