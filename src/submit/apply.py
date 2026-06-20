"""
M5 — Fill + submit an application. REVIEW-FIRST by default (never submits without approval).

Flow:
  1. build_review() -> human-readable review of every answer + flagged fields + resume path.
  2. fill_form()    -> open the real Greenhouse form in a browser, fill text fields, upload
                       resume, screenshot. Stops BEFORE submit unless submit=True.

Safety: submit=False is the default everywhere. Hard facts flagged needs_human block
auto-submit until a human resolves them.
"""
from __future__ import annotations

from pathlib import Path

from .. import config
from ..models import AnswerSheet, Job, Profile, Status


# ---------------- Review sheet (no browser needed) ----------------

def build_review(job: Job, sheet: AnswerSheet, profile: Profile, resume_path: str) -> str:
    """Return a readable review of what WILL be submitted. Written to candidate folder."""
    lines = [
        f"# Application Review — {job.title}",
        f"**Company/board:** {job.board}   **Location:** {job.location}",
        f"**URL:** {job.url}",
        f"**Resume to upload:** {resume_path}",
        f"**Fit score:** {job.fit_score if job.fit_score is not None else 'n/a'}"
        f"   **Sponsors H-1B:** {job.sponsors_h1b}",
        "",
        "## Answers",
        "| Status | Question | Answer | Source |",
        "|---|---|---|---|",
    ]
    blockers = 0
    for a in sheet.answers:
        mark = "⚠️ REVIEW" if a.needs_human else "✅"
        if a.needs_human:
            blockers += 1
        val = (a.value or "—").replace("\n", " ")
        if len(val) > 80:
            val = val[:77] + "..."
        lines.append(f"| {mark} | {a.label[:60]} | {val} | {a.source.value} |")

    lines += [
        "",
        f"**{blockers} field(s) need human input before this can auto-submit.**"
        if blockers else "**All fields filled — ready to submit.**",
    ]
    return "\n".join(lines)


def save_review(text: str, candidate: str, job: Job) -> Path:
    d = config.candidate_dir(candidate) / "reviews"
    d.mkdir(exist_ok=True)
    path = d / f"{_safe(job.board)}_{job.job_id}.md"
    path.write_text(text, encoding="utf-8")
    return path


# ---------------- Browser fill (Playwright) ----------------

def fill_form(
    job: Job,
    sheet: AnswerSheet,
    resume_path: str,
    *,
    submit: bool = False,        # SAFETY: default never submits
    headless: bool = False,
    screenshot_dir: str | Path | None = None,
) -> dict:
    """
    Open the application form and fill it. Returns a result dict.
    With submit=False (default) it fills + screenshots and STOPS before submitting.
    """
    if sheet.needs_review and submit:
        return {"status": Status.NEEDS_REVIEW.value,
                "reason": "Flagged fields unresolved; refusing to auto-submit."}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"status": "error",
                "reason": "Playwright not installed. Run: pip install playwright && playwright install chromium"}

    result = {"status": "filled", "filled": [], "skipped": [], "screenshot": None}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(job.url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        for a in sheet.answers:
            if not a.value:
                result["skipped"].append(a.label)
                continue
            placed = False
            for name in a.field_names:
                sel = f'[name="{name}"]'
                try:
                    if page.locator(sel).count():
                        el = page.locator(sel).first
                        tag = el.evaluate("e => e.tagName.toLowerCase()")
                        if tag == "select":
                            el.select_option(a.value)
                        else:
                            el.fill(a.value)
                        placed = True
                        break
                except Exception:
                    continue
            (result["filled"] if placed else result["skipped"]).append(a.label)

        # Upload resume to the file input
        if resume_path and Path(resume_path).exists():
            try:
                fi = page.locator('input[type="file"]').first
                if fi.count():
                    fi.set_input_files(str(resume_path))
                    result["resume_uploaded"] = True
            except Exception as e:
                result["resume_error"] = str(e)

        # Screenshot for the review queue
        sdir = Path(screenshot_dir) if screenshot_dir else Path(config.DATA_DIR)
        sdir.mkdir(parents=True, exist_ok=True)
        shot = sdir / f"{_safe(job.board)}_{job.job_id}.png"
        try:
            page.screenshot(path=str(shot), full_page=True)
            result["screenshot"] = str(shot)
        except Exception:
            pass

        if submit and not sheet.needs_review:
            try:
                page.get_by_role("button", name="Submit Application").click()
                page.wait_for_timeout(2500)
                result["status"] = Status.SUBMITTED.value
            except Exception as e:
                result["status"] = Status.FAILED.value
                result["reason"] = str(e)
        else:
            result["status"] = Status.FILLING.value
            result["note"] = "Filled and stopped before submit (review-first)."

        if not headless:
            page.wait_for_timeout(1500)
        browser.close()

    return result


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s).strip("_")
