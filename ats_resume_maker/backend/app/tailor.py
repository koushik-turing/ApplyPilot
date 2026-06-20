"""Rewrite a resume to better match a job description.

Two paths:
  * If a local Ollama model is available, ask it to rewrite the summary, skills,
    and experience bullets to weave in missing keywords truthfully.
  * Otherwise, a deterministic rule-based pass still lifts the score by adding
    genuinely-missing skills and refreshing the summary.

Returns (tailored_resume, list_of_change_notes).
"""
from __future__ import annotations
import json
import re

from pydantic import BaseModel

from .schemas import Resume, JobDescription
from . import llm, polish, claude_client
from .config import settings

SYSTEM = (
    "You are an expert resume writer and ATS optimization specialist. "
    "Rewrite resume content to match a job description while staying truthful — "
    "never invent jobs, employers, degrees, or experience the person doesn't have. "
    "You may rephrase, emphasize relevant skills, and naturally incorporate keywords."
)


def _context_of(r: Resume) -> str:
    """The text where keywords earn FULL ATS credit (summary + experience + projects)."""
    parts = [r.summary, " ".join(r.projects), " ".join(r.certifications)]
    for e in r.experience:
        parts += [e.title, " ".join(e.bullets)]
    return " ".join(p for p in parts if p).lower()


def _missing_from_context(r: Resume, jd: JobDescription) -> list[str]:
    """JD keywords (hard, then domain, then soft) NOT demonstrated in experience/summary —
    i.e. the exact terms costing us match-rate. These are what a retry must weave in."""
    ctx = _context_of(r)
    hard = jd.hard_skills or [k for k in jd.keywords if k not in jd.soft_skills]
    out: list[str] = []
    for term in [*hard, *jd.other_keywords, *jd.soft_skills]:
        if term and term.lower() not in {o.lower() for o in out} and not _present(term, ctx):
            out.append(term)
    return out


def tailor_resume(
    resume: Resume,
    jd: JobDescription,
    missing_keywords: list[str],
    full_text: str = "",
    scorer=None,
    target: int = 80,
) -> tuple[Resume, list[str], str]:
    """Returns (tailored_resume, change_notes, engine) where engine is one of
    'claude', 'ollama', or 'rule-based'. Falls back gracefully on any failure.

    If `scorer` (a callable: Resume -> int overall score) is given, the Claude path
    runs a re-score + single focused retry: if the first pass lands below `target`,
    it re-tailors once with explicit feedback about which keywords still aren't in the
    experience, and keeps whichever pass scores higher. This reliably pushes genuine,
    well-matched resumes into the 75-90 range without fabricating anything."""
    fallback_note: str | None = None

    # 1. Best quality: Claude API (if a key is configured)
    if claude_client.claude_available():
        try:
            tailored, changes = _claude_tailor(resume, jd, missing_keywords)
            if scorer is None:
                return tailored, changes, "claude"
            best, best_changes, best_score = tailored, changes, scorer(tailored)
            # One focused retry if we're under target — weave in what's still missing.
            if best_score < target:
                still = _missing_from_context(best, jd)
                fb = (
                    f"PREVIOUS ATTEMPT SCORED {best_score}/100 — BELOW THE {target}+ TARGET. "
                    "The score is held back because these required keywords are NOT yet shown in "
                    "an experience bullet or the summary (they earn little/no ATS credit): "
                    f"{', '.join(still[:20]) or '(none)'}. In this revision, weave EACH of these "
                    "(that the candidate plausibly has) into a real, quantified experience bullet, "
                    "and make sure the exact job title leads the summary. Push the match higher "
                    "while staying truthful.\n\n"
                )
                try:
                    t2, c2 = _claude_tailor(best, jd, still, feedback=fb)
                    s2 = scorer(t2)
                    if s2 > best_score:
                        best, best_changes, best_score = t2, c2, s2
                except Exception:
                    pass  # keep the first (already valid) pass on any retry hiccup

            # Critic -> refine: an INDEPENDENT recruiter-grade quality pass. Unlike the
            # keyword retry above, this judges writing strength (impact, specificity, weak
            # bullets, summary, title) and feeds concrete fixes back for one more revision.
            # This is what lifts output from "keyword-matched" to genuinely competitive.
            try:
                critique = _claude_critic(best, jd)
                if critique:
                    t3, c3 = _claude_tailor(best, jd, _missing_from_context(best, jd),
                                            feedback=critique)
                    if scorer(t3) >= best_score:   # accept if it doesn't regress the match
                        best, best_changes = t3, c3
            except Exception:
                pass  # keep the best valid pass on any critic/refine hiccup
            return best, best_changes, "claude"
        except Exception as e:  # never let a paid-call hiccup break the request
            fallback_note = (f"Note: Claude API call failed ({type(e).__name__}); "
                             "used offline tailoring instead.")

    # 2. Free local AI: Ollama (if running)
    if llm.ollama_running():
        out = _llm_tailor(resume, jd, missing_keywords)
        if out is not None:
            tailored, changes = out
            if fallback_note:
                changes = [fallback_note, *changes]
            return tailored, changes, "ollama"

    # 3. Deterministic, honest rule-based pass (always works)
    tailored, changes = _rule_tailor(resume, jd, missing_keywords, full_text)
    if fallback_note:
        changes = [fallback_note, *changes]
    return tailored, changes, "rule-based"


# ---------------- Claude API (best quality, truthful) ----------------
class _AITailorResult(BaseModel):
    tailored_resume: Resume
    changes: list[str]


_CLAUDE_SYSTEM = (
    "You are a world-class professional resume writer and ATS-optimization expert (think Jobscan + "
    "Resume Worded quality). TRANSFORM the candidate's resume into a crisp, achievement-driven, "
    "ATS-optimized resume tailored to the target job. Your goal is an ATS match score of 85+ — and "
    "you reach it by genuinely strengthening the resume, not by stuffing.\n\n"
    "HARD RULES (never break):\n"
    "- Keep employers, job titles, employment dates, and education EXACTLY as given. Never invent "
    "jobs, companies, degrees, or certifications.\n"
    "- Do not claim a specific named technology/tool the candidate shows no plausible connection to. "
    "But interpret 'plausible' generously: if the role, domain, or listed skills make it reasonable "
    "the candidate used a job-required skill, surface it in their experience.\n"
    "- Output clean, correctly-spelled, professional prose. Use standard tech names exactly "
    "(Node.js, Next.js, TypeScript, Apache Kafka) — never duplicate or mangle a term.\n\n"
    "*** THE #1 RULE THAT DRIVES THE SCORE — KEYWORDS MUST LIVE IN EXPERIENCE ***\n"
    "An ATS gives a skill FULL credit only when it appears inside an EXPERIENCE BULLET or the "
    "SUMMARY — demonstrated in real work. A skill that sits only in the Skills list earns HALF "
    "credit, and one that's absent earns ZERO. Therefore: for EVERY job-required skill the candidate "
    "plausibly has (hard skills first, then domain/'other' keywords, then soft skills), WEAVE IT INTO "
    "AT LEAST ONE EXPERIENCE BULLET (or the summary) with a real action and ideally a metric. Do not "
    "rely on the Skills list to carry keywords — the Skills list is a backup, not the main signal. "
    "Aim to leave NO required, plausibly-true keyword sitting only in the Skills list.\n\n"
    "SUMMARY (write one, 40-80 words):\n"
    "Lead with the EXACT TARGET JOB TITLE (verbatim), then years of experience, then the 3-5 most "
    "job-relevant hard skills, then one strong quantified outcome. Tight and senior in tone.\n\n"
    "EXPERIENCE BULLETS — use the XYZ / Google formula: 'Accomplished [X] as measured by [Y] by "
    "doing [Z]'. For EACH bullet:\n"
    "  - Start with a strong past-tense action verb (Architected, Engineered, Optimized, Led, "
    "Reduced, Scaled). NEVER use weak openers (Responsible for, Worked on, Helped, Assisted).\n"
    "  - Keep it to 1-2 lines / ~12-26 words. Be specific, not padded.\n"
    "  - Aim for ~70% of bullets to carry a real metric (%, $, scale, time, volume, users). "
    "Quantify by reasoning from the work (e.g. 20/day x 250 days ~= 5,000/yr); use ranges/'~' when "
    "estimating. Do NOT force a fake number onto every bullet — natural, defensible numbers only.\n"
    "  - Keep 4-6 of the strongest, most job-relevant bullets per role (trim weak/duplicate ones).\n"
    "  - Each bullet should carry one or more target keywords naturally — never keyword-stuff or "
    "repeat the same metric.\n\n"
    "SKILLS: a clean, single-line, de-duplicated list using standard industry names, ordered to "
    "lead with the job's required skills the candidate genuinely has. Keep it focused (~15-25 "
    "skills). Remember: skills here that never appear in a bullet only earn half credit, so prefer "
    "to also demonstrate them above.\n\n"
    "Stay truthful and ATS-safe (no tables/graphics). In 'changes': briefly list what you improved, "
    "and concisely flag any estimated metric the candidate should confirm (group them — don't tag "
    "every bullet with '(please confirm)')."
)


def _claude_tailor(resume: Resume, jd: JobDescription,
                   missing: list[str], feedback: str = "") -> tuple[Resume, list[str]]:
    # We ask for plain JSON (not the strict structured-output mode) because the full
    # nested resume schema exceeds the structured-output complexity limit.
    client = claude_client.get_client()
    hard = jd.hard_skills or [k for k in jd.keywords if k not in jd.soft_skills]
    user = (
        f"TARGET JOB TITLE (mirror this EXACTLY in the summary's first line): {jd.title or '(not specified)'}\n"
        f"REQUIRED HARD SKILLS (demonstrate each in an experience bullet if plausibly true): "
        f"{', '.join(hard[:30]) or '(none)'}\n"
        f"DOMAIN / OTHER JOB KEYWORDS (also weave into bullets where true): "
        f"{', '.join(jd.other_keywords[:20]) or '(none)'}\n"
        f"SOFT SKILLS the JD asks for: {', '.join(jd.soft_skills[:12]) or '(none)'}\n"
        f"KEYWORDS CURRENTLY MISSING (weave in any the candidate plausibly has): "
        f"{', '.join(missing[:25]) or '(none)'}\n\n"
        f"{feedback}"
        f"CURRENT RESUME (JSON):\n{resume.model_dump_json(indent=2)}\n\n"
        "Transform this into an excellent, ATS-optimized resume for the target job. MAXIMIZE the "
        "match: put every plausibly-true required skill INTO an experience bullet (not just the "
        "Skills list), quantify ~70% of bullets, mirror the exact job title in the summary, and use "
        "strong action verbs with zero weak openers. Aim for an ATS score of 85+.\n\n"
        "Return ONLY a JSON object (no markdown, no commentary) with exactly two keys:\n"
        '  "tailored_resume": the improved resume using the SAME JSON structure and keys '
        "as the input resume above, and\n"
        '  "changes": an array of short strings describing the edits (flag any estimated metrics).\n'
        "Keep all companies, titles, dates, and education identical to the input."
    )
    resp = client.messages.create(
        model=settings.claude_tailor_model,
        max_tokens=8000,   # headroom so long resumes aren't truncated mid-JSON
        system=_CLAUDE_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    if resp.stop_reason == "max_tokens":
        raise ValueError("Claude output was truncated (resume too long for one pass).")
    text = "".join(b.text for b in resp.content if b.type == "text")
    data = _extract_json(text)
    if not data or "tailored_resume" not in data:
        raise ValueError("Claude did not return the expected JSON.")
    result = _AITailorResult.model_validate(data)
    changes = [c for c in result.changes if c and c.strip()] or \
              ["Rewrote summary, skills, and experience bullets to match the job (AI)."]
    return result.tailored_resume, changes


# ---------------- Critic (independent quality reviewer) ----------------
_CRITIC_SYSTEM = (
    "You are a brutally honest senior technical recruiter and professional resume critic "
    "(Rezi / Teal / Resume Worded calibre). You review a tailored resume against a target job "
    "and find the SPECIFIC weaknesses that keep it from being a top-tier, interview-winning "
    "resume. You do not rewrite — you give precise, actionable fixes the writer must apply."
)


def _claude_critic(resume: Resume, jd: JobDescription) -> str:
    """Return concrete, prioritized improvement instructions for the tailored resume.
    Empty string if the resume is already excellent or the call fails."""
    client = claude_client.get_client()
    hard = jd.hard_skills or [k for k in jd.keywords if k not in jd.soft_skills]
    user = (
        f"TARGET JOB TITLE: {jd.title or '(unspecified)'}\n"
        f"REQUIRED HARD SKILLS: {', '.join(hard[:25]) or '(none)'}\n\n"
        f"TAILORED RESUME (JSON):\n{resume.model_dump_json(indent=2)}\n\n"
        "Critique this resume as if deciding whether to forward it for the target job. "
        "Identify the most important, concrete weaknesses, e.g.:\n"
        "- Bullets that are vague, generic, duty-style, or missing measurable impact.\n"
        "- The summary not leading with the exact target title, or being weak/long.\n"
        "- Required skills not demonstrated inside an experience bullet.\n"
        "- Repetitive metrics/verbs, padding, or unprofessional phrasing.\n"
        "- Anything that reads junior or would fail a 6-second recruiter scan.\n\n"
        "Return ONLY a JSON object: {\"verdict\": str, \"fixes\": [str, ...]}. "
        "Each fix must be a specific instruction (reference the role/bullet) the writer can apply. "
        "If the resume is already excellent, return an empty fixes array."
    )
    try:
        resp = client.messages.create(
            model=settings.claude_tailor_model,
            max_tokens=1200,
            system=_CRITIC_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        data = _extract_json(text)
    except Exception:
        return ""
    if not data:
        return ""
    fixes = [str(f).strip() for f in data.get("fixes", []) if str(f).strip()]
    if not fixes:
        return ""
    return (
        "A SENIOR RECRUITER REVIEWED YOUR PREVIOUS DRAFT AND REQUIRES THESE SPECIFIC FIXES "
        "(apply every one while keeping all facts/dates truthful):\n- "
        + "\n- ".join(fixes[:10]) + "\n\n"
    )


# ---------------- rule-based (always works, and stays honest) ----------------
def _resume_body(r: Resume) -> str:
    """Everything except the skills list — the candidate's actual described work."""
    parts = [r.summary, " ".join(r.projects), " ".join(r.certifications)]
    for e in r.experience:
        parts += [e.title, " ".join(e.bullets)]
    return " ".join(p for p in parts if p).lower()


def _present(term: str, text: str) -> bool:
    return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(term.lower()) + r"(?![A-Za-z0-9])", text))


def _years_phrase(resume: Resume, full_text: str) -> str:
    m = re.search(r"(\d{1,2})\+?\s*years?", (resume.summary or "") + " " + full_text, re.I)
    return f"{m.group(1)}+ years of experience" if m else ""


def _guess_role(resume: Resume, jd: JobDescription) -> str:
    if jd.title:
        return jd.title.strip()
    if resume.experience and resume.experience[0].title:
        return resume.experience[0].title.strip()
    return ""


def _rule_tailor(resume: Resume, jd: JobDescription, missing: list[str],
                 full_text: str = "") -> tuple[Resume, list[str]]:
    """Honest, non-AI optimization that does genuinely useful work.

    It never claims a skill the candidate doesn't have. Its main, legitimate lever is
    a strong professional summary that states the target title plus the candidate's
    OWN declared/used job-relevant skills — standard resume writing that also moves a
    real ATS score (title match + putting declared keywords into prose context).
    """
    tailored = resume.model_copy(deep=True)
    changes: list[str] = []
    haystack = (_resume_body(resume) + " " + (full_text or "")).lower()
    declared = {s.lower() for s in tailored.skills}

    def has(k: str) -> bool:
        return _present(k, haystack) or k.lower() in declared

    # (1) Surface JD hard skills the candidate clearly HAS (used in their resume text)
    #     but didn't list under Skills. Legitimate — they demonstrably have it.
    surfaced = [k for k in jd.hard_skills if _present(k, haystack) and k.lower() not in declared]
    if surfaced:
        tailored.skills.extend(polish.canon_skill(s) for s in surfaced)
        declared |= {s.lower() for s in surfaced}
        changes.append("Added skill(s) shown in your experience but missing from the Skills list: "
                       + ", ".join(polish.canon_skill(s) for s in surfaced[:8]) + ".")

    # (2) Strong, ATS-aligned professional summary. Uses ONLY the target title and the
    #     candidate's own job-relevant declared skills — no invented capabilities.
    role = _guess_role(resume, jd)
    relevant = []
    seen = set()
    for k in jd.hard_skills:
        if has(k):
            c = polish.canon_skill(k)
            if c.lower() not in seen:
                relevant.append(c); seen.add(c.lower())
    relevant = relevant[:8]

    if role or relevant:
        yrs = _years_phrase(resume, full_text)
        lead = role or "Professional"
        if yrs:
            lead = f"{lead} with {yrs}"
        body_clause = f", skilled in {', '.join(relevant)}" if relevant else ""
        new_summary = f"{lead}{body_clause}.".strip()
        # keep one substantive sentence from the original, if it adds new info
        if resume.summary:
            extra = re.sub(r"^[^.]*\b(engineer|developer|manager|analyst|designer|scientist|"
                           r"specialist|consultant|professional)\b[^.]*\.\s*", "",
                           resume.summary, count=1, flags=re.I).strip()
            if extra and extra.lower() not in new_summary.lower():
                new_summary += " " + extra
        if new_summary.strip(". ") and new_summary != (resume.summary or ""):
            tailored.summary = new_summary
            changes.append("Rewrote the professional summary to lead with the target title and your "
                           "most job-relevant skills (boosts title match + keyword context).")

    # (3) Honest gap report — JD skills that appear NOWHERE in the resume.
    truly_missing = [k for k in jd.hard_skills if not has(k)]
    if truly_missing:
        changes.append("Gap: these required skills aren't in your resume yet — add them to your "
                       "experience bullets ONLY if genuinely true: "
                       + ", ".join(polish.canon_skill(k) for k in truly_missing[:10]) + ".")
        changes.append("Tip: enable the local AI (Ollama) to auto-rewrite your bullet points and "
                       "weave these in truthfully for a bigger, legitimate score gain — see the README.")

    if not changes:
        changes.append("Your resume already covers this job's key skills in context — the honest ATS "
                       "ceiling for it is reached. Add more quantified, role-specific achievements to go higher.")
    return tailored, changes


# ---------------- LLM-based (when Ollama is running) ----------------
def _llm_tailor(resume: Resume, jd: JobDescription, missing: list[str]) -> tuple[Resume, list[str]] | None:
    exp_text = "\n".join(
        f"[{i}] {e.title} at {e.company}:\n" + "\n".join(f"  - {b}" for b in e.bullets)
        for i, e in enumerate(resume.experience)
    )
    prompt = f"""Rewrite parts of this resume to match the job below. Stay 100% truthful.

JOB TITLE: {jd.title}
IMPORTANT KEYWORDS TO INCLUDE WHERE TRUE: {", ".join(jd.keywords[:20])}
KEYWORDS CURRENTLY MISSING: {", ".join(missing[:15])}

CURRENT SUMMARY:
{resume.summary or "(none)"}

CURRENT SKILLS:
{", ".join(resume.skills) or "(none)"}

CURRENT EXPERIENCE:
{exp_text or "(none)"}

Return ONLY a JSON object, no prose, with this exact shape:
{{
  "summary": "rewritten 2-3 sentence summary",
  "skills": ["skill", ...],
  "experience": [{{"index": 0, "bullets": ["rewritten bullet", ...]}}],
  "changes": ["short note of what you changed", ...]
}}
Only include keywords that are genuinely supported by the existing content."""

    raw = llm.generate(prompt, system=SYSTEM, temperature=0.3)
    if not raw:
        return None
    data = _extract_json(raw)
    if not data:
        return None

    tailored = resume.model_copy(deep=True)
    if isinstance(data.get("summary"), str) and data["summary"].strip():
        tailored.summary = data["summary"].strip()
    if isinstance(data.get("skills"), list):
        merged = list(dict.fromkeys([*tailored.skills, *[str(s) for s in data["skills"]]]))
        tailored.skills = merged[:40]
    for item in data.get("experience", []) or []:
        try:
            idx = int(item["index"])
            bullets = [str(b) for b in item["bullets"] if str(b).strip()]
            if 0 <= idx < len(tailored.experience) and bullets:
                tailored.experience[idx].bullets = bullets
        except (KeyError, ValueError, TypeError):
            continue
    changes = [str(c) for c in data.get("changes", []) if str(c).strip()] or \
              ["Rewrote summary, skills, and experience bullets to match the job (AI)."]
    return tailored, changes


def _extract_json(s: str) -> dict | None:
    # Models sometimes wrap JSON in ```json fences or add prose; grab the first {...}.
    s = re.sub(r"```(?:json)?", "", s)
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(s[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None
