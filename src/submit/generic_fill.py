"""
Generic ATS form filler — for Lever / Ashby / Workable / custom sites that DON'T expose a
questions API (unlike Greenhouse). We can't read the fields as structured data, so we
detect the UNIVERSAL fields (name, email, phone, links) by their attributes/labels and fill
them, upload the resume, and screenshot the page. Custom questions are left for the recruiter
(flagged) — honest about the limits of schema-less filling.
"""
from __future__ import annotations

from pathlib import Path

from .. import config
from ..models import Profile

# Standard fields -> candidate selectors (tried in order). Case-insensitive attr matches.
_FIELD_SELECTORS = {
    "first_name": ['input[autocomplete="given-name"]', 'input[name*="first" i]',
                   'input[id*="first" i]', 'input[name*="given" i]'],
    "last_name": ['input[autocomplete="family-name"]', 'input[name*="last" i]',
                  'input[id*="last" i]', 'input[name*="family" i]'],
    "full_name": ['input[name="name" i]', 'input[id="name" i]', 'input[name*="full" i]',
                  'input[autocomplete="name"]', 'input[aria-label*="full name" i]'],
    "email": ['input[type="email"]', 'input[name*="email" i]', 'input[id*="email" i]',
              'input[autocomplete="email"]'],
    "phone": ['input[type="tel"]', 'input[name*="phone" i]', 'input[id*="phone" i]',
              'input[autocomplete="tel"]'],
    "linkedin": ['input[name*="linkedin" i]', 'input[id*="linkedin" i]',
                 'input[aria-label*="linkedin" i]'],
}


def _dummy_email(email: str) -> str:
    if "@" not in email:
        return "test.candidate023@example.com"
    local, domain = email.split("@", 1)
    return f"{local}023@{domain}"


def fill_generic(url: str, profile: Profile, *, resume_path: str = "", submit: bool = False,
                 headless: bool = True, screenshot_dir=None, test_mode: bool = True) -> dict:
    """Best-effort fill of the standard fields on any ATS application page. Returns a result
    dict incl. screenshot. Does NOT submit unless submit=True (and even then only after the
    standard fields are placed — custom questions remain the recruiter's responsibility)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"status": "error", "reason": "Playwright not installed."}

    email = _dummy_email(profile.email) if test_mode else profile.email
    phone = "(256) 555-0176" if test_mode else profile.phone
    first = profile.full_name.split()[0] if profile.full_name else ""
    last = profile.full_name.split()[-1] if len(profile.full_name.split()) > 1 else ""
    values = {"first_name": first, "last_name": last, "full_name": profile.full_name,
              "email": email, "phone": phone, "linkedin": profile.linkedin}

    result = {"status": "filling", "filled": [], "ats": "generic", "note":
              "Standard fields auto-filled. Custom questions on non-Greenhouse forms need "
              "recruiter review/manual completion."}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1800)
            # reveal the form if it's behind an Apply button
            if not page.locator('input[type="email"], input[type="text"]').count():
                for name in ("Apply", "Apply for this job", "Apply Now", "I'm interested", "Submit application"):
                    btn = page.get_by_role("button", name=name)
                    if not btn.count():
                        btn = page.get_by_role("link", name=name)
                    if btn.count():
                        try:
                            btn.first.click(); page.wait_for_timeout(1500)
                        except Exception:
                            pass
                        break

            placed_full = False
            for field, sels in _FIELD_SELECTORS.items():
                val = values.get(field)
                if not val:
                    continue
                if field in ("first_name", "last_name") and placed_full:
                    continue
                for sel in sels:
                    try:
                        loc = page.locator(sel).first
                        if loc.count() and loc.is_visible():
                            loc.fill(val)
                            result["filled"].append(field)
                            if field == "full_name":
                                placed_full = True
                            break
                    except Exception:
                        continue

            # resume upload
            if resume_path and Path(resume_path).exists():
                for sel in ('input[type="file"][name*="resume" i]', 'input[type="file"][id*="resume" i]',
                            'input[type="file"]'):
                    try:
                        fi = page.locator(sel).first
                        if fi.count():
                            fi.set_input_files(str(resume_path))
                            result["resume_uploaded"] = True
                            break
                    except Exception:
                        continue

            sdir = Path(screenshot_dir) if screenshot_dir else Path(config.DATA_DIR)
            sdir.mkdir(parents=True, exist_ok=True)
            shot = sdir / f"generic_{abs(hash(url)) % 10**8}.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
                result["screenshot"] = str(shot)
            except Exception:
                pass

            # We do NOT auto-submit non-Greenhouse forms — custom required questions are
            # unknown to us, so a recruiter must complete + submit those.
            result["status"] = "filling"
            result["note"] += " (auto-submit disabled for schema-less forms — review & submit manually.)"
        finally:
            if not headless:
                page.wait_for_timeout(1000)
            browser.close()
    return result
