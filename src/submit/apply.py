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

        # Map field_name -> its question, so we know type + options (label<->value).
        qmap = {fn: q for q in job.questions for fn in q.field_names}

        for a in sheet.answers:
            q = next((qmap[fn] for fn in a.field_names if fn in qmap), None)

            # MULTI-SELECT: pick each value (e.g. country=United States, several skills).
            if q and q.field_type == "multi_value_multi_select":
                vals = a.values or ([a.value] if a.value else [])
                if not vals:
                    result["skipped"].append(a.label)
                    continue
                placed = False
                for name in a.field_names:
                    el = _find_field(page, name)
                    if el is None:
                        continue
                    picked = [_select_option(page, el, v) for v in vals]
                    placed = any(picked)
                    if placed:
                        break
                (result["filled"] if placed else result["skipped"]).append(a.label)
                continue

            if not a.value:
                result["skipped"].append(a.label)
                continue
            is_select = bool(q and q.options)

            label_value = a.value
            if is_select:
                # a.value should be the option LABEL. Verify it matches a real option;
                # if it's a legacy value/id, map id->label. If it still isn't a valid
                # option, SKIP — never type a raw id/garbage into a dropdown.
                opt_labels = {str(o.get("label", "")).strip().lower(): o.get("label")
                              for o in q.options}
                if label_value.strip().lower() not in opt_labels:
                    mapped = next((o.get("label") for o in q.options
                                   if str(o.get("value")) == str(a.value)), None)
                    label_value = mapped or label_value
                if label_value.strip().lower() not in opt_labels:
                    result["skipped"].append(a.label + " (no matching option)")
                    continue

            placed = False
            for name in a.field_names:
                el = _find_field(page, name)
                if el is None:
                    continue
                try:
                    if is_select:
                        placed = _select_option(page, el, label_value)
                    else:
                        el.fill(label_value)
                        placed = True
                except Exception:
                    placed = False
                if placed:
                    break
            (result["filled"] if placed else result["skipped"]).append(a.label)

        # Upload resume — target the RESUME file input specifically (not the cover-letter one).
        if resume_path and Path(resume_path).exists():
            uploaded = False
            for sel in ('input[type="file"]#resume', 'input[type="file"][name="resume"]',
                        'input[type="file"][id*="resume" i]', 'input[type="file"][name*="resume" i]'):
                try:
                    loc = page.locator(sel).first
                    if loc.count():
                        loc.set_input_files(str(resume_path))
                        uploaded = True
                        break
                except Exception:
                    continue
            if not uploaded:   # fallback: first file input (most forms put resume first)
                try:
                    fi = page.locator('input[type="file"]').first
                    if fi.count():
                        fi.set_input_files(str(resume_path))
                        uploaded = True
                except Exception as e:
                    result["resume_error"] = str(e)
            result["resume_uploaded"] = uploaded

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
                clicked = False
                for name in ("Submit Application", "Submit application", "Submit",
                             "Apply", "Apply for this job", "Send Application"):
                    btn = page.get_by_role("button", name=name)
                    if btn.count():
                        btn.first.click()
                        clicked = True
                        break
                if not clicked:        # fallback: a submit-type input/button
                    sub = page.locator('button[type="submit"], input[type="submit"]').first
                    if sub.count():
                        sub.click()
                        clicked = True
                if not clicked:
                    raise RuntimeError("could not find a submit button")
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


def _find_field(page, name: str):
    """Locate a form control by name OR id (Greenhouse uses id). Returns a locator or None."""
    for sel in (f'[name="{name}"]', f'[id="{name}"]', f'#{name}'):
        try:
            loc = page.locator(sel).first
            if loc.count():
                return loc
        except Exception:
            continue
    return None


def _select_option(page, el, label: str) -> bool:
    """Handle native <select> and Greenhouse custom dropdowns. Picks the option by label."""
    try:
        tag = el.evaluate("e => e.tagName.toLowerCase()")
    except Exception:
        tag = ""
    if tag == "select":
        try:
            el.select_option(label=label)
            return True
        except Exception:
            return False
    # Custom combobox: click to open, then click the matching option.
    try:
        el.click()
        page.wait_for_timeout(300)
        option = page.get_by_role("option", name=label, exact=True)
        if not option.count():
            option = page.locator(f'text="{label}"').last
        if option.count():
            option.click()
            page.wait_for_timeout(200)
            return True
    except Exception:
        pass
    # Fallback: type the label and press Enter (filterable comboboxes).
    try:
        el.fill(label)
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        return True
    except Exception:
        return False


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s).strip("_")
