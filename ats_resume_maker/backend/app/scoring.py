"""The ATS scoring engine — calibrated to mirror real checkers (Jobscan etc.).

Principles taken from how production ATS / match-rate tools actually work:
  * HARD skills are weighted far more than soft skills or generic keywords.
  * A keyword only earns FULL credit when it appears in real context (summary or
    experience bullets). A bare skills-list mention earns only PARTIAL credit, and
    a large skills list with little backing in experience is flagged as stuffing.
  * JOB TITLE match is its own heavily-weighted factor.
  * Realistic outcomes: a typical untailored resume lands ~45-60; a genuinely
    well-matched resume ~75-85. You should not be able to reach 90+ by stuffing.

No AI required — fully deterministic.
"""
from __future__ import annotations
import re

from .schemas import Resume, ScoreReport, SubScore, JobDescription
from . import keywords

ACTION_VERBS = {
    "led", "built", "designed", "developed", "created", "implemented", "managed",
    "launched", "improved", "increased", "reduced", "delivered", "drove", "owned",
    "architected", "automated", "optimized", "shipped", "scaled", "migrated",
    "spearheaded", "engineered", "established", "streamlined", "achieved", "boosted",
    "negotiated", "mentored", "coordinated", "analyzed", "researched", "founded",
    # broader, commonly-used resume action verbs so strong bullets aren't undercounted
    "containerized", "deployed", "maintained", "refactored", "integrated", "configured",
    "tested", "debugged", "modernized", "rearchitected", "provisioned", "orchestrated",
    "programmed", "wrote", "produced", "generated", "formulated", "executed", "administered",
    "supervised", "directed", "headed", "oversaw", "facilitated", "enabled", "accelerated",
    "expanded", "grew", "saved", "cut", "eliminated", "resolved", "troubleshot", "collaborated",
    "partnered", "supported", "enhanced", "upgraded", "rolled", "introduced", "pioneered",
    "transformed", "revamped", "consolidated", "standardized", "documented", "trained",
    "led", "guided", "championed", "secured", "won", "drove", "initiated", "launched",
    "redesigned", "deployed", "migrated", "modeled", "forecasted", "audited", "reviewed",
    "authored", "devised", "crafted", "assembled", "constructed", "validated", "benchmarked",
}
# Weak bullet openers real checkers (Resume Worded / Rezi) penalize — they describe
# duties, not achievements. A resume full of these reads junior and scores lower.
WEAK_OPENERS = (
    "responsible for", "worked on", "worked with", "helped", "assisted", "assisted with",
    "involved in", "participated in", "tasked with", "duties included", "in charge of",
    "responsible", "supported", "handled", "contributed to",
)
_NUM = re.compile(r"\d|\b(?:percent|million|thousand|users|customers|hours|x)\b", re.I)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+.#/-]*")


def _bullet_quality(bullets: list[str]) -> tuple[int, str, list[str]]:
    """Content score (0-100) using the dimensions real ATS/resume checkers grade:
    quantification (~60% target), strong action verbs, brevity (15-25 words), depth,
    minus a penalty for weak/duty-style openers. Returns (score, detail, suggestions)."""
    n = len(bullets)
    tips: list[str] = []
    with_num = sum(1 for b in bullets if _NUM.search(b))
    with_verb = sum(1 for b in bullets
                    if b.strip().split() and b.strip().split()[0].lower() in ACTION_VERBS)
    weak = sum(1 for b in bullets if b.strip().lower().startswith(WEAK_OPENERS))
    # brevity: ideal 12-26 words; long padded bullets and one-liners both lose credit.
    good_len = sum(1 for b in bullets if 8 <= len(b.split()) <= 28)

    quant = with_num / n
    quant_score = min(1.0, quant / 0.6)          # 60% quantified == full credit
    verby = with_verb / n
    brevity = good_len / n
    depth = min(1.0, n / 4)
    weak_ratio = weak / n

    raw = 0.40 * quant_score + 0.30 * verby + 0.15 * brevity + 0.15 * depth
    raw *= (1 - 0.30 * weak_ratio)               # weak-opener penalty (up to -30%)
    score = round(100 * raw)

    detail = (f"{with_num}/{n} quantified, {with_verb}/{n} start with a strong action verb, "
              f"{good_len}/{n} well-scoped"
              + (f", {weak} weak/duty-style opener(s)" if weak else "") + ".")
    if quant < 0.55:
        tips.append("Quantify more bullets with real numbers (%, $, scale, time saved, users).")
    if verby < 0.6:
        tips.append("Start more bullets with strong action verbs (Architected, Led, Reduced…).")
    if weak:
        tips.append("Replace weak openers (Responsible for / Helped / Worked on) with achievement verbs.")
    return score, detail, tips


def _rating(score: int) -> str:
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Strong"
    if score >= 50:
        return "Fair"
    return "Weak"


def _context_text(resume: Resume) -> str:
    """The 'substance' of a resume — where keywords genuinely earn credit."""
    parts = [resume.summary, " ".join(resume.projects), " ".join(resume.certifications)]
    for e in resume.experience:
        parts += [e.title, e.company, " ".join(e.bullets)]
    for ed in resume.education:
        parts += [ed.degree, ed.institution]
    return " ".join(p for p in parts if p).lower()


def _credit(term: str, context: str, skills_list: str, full_text: str = "") -> float:
    """How much credit a keyword earns based on WHERE it appears — calibrated to
    mirror real ATS (Jobscan/Jobright), which reward skills DEMONSTRATED in
    experience far more than ones merely listed:
      1.0  used in real context (experience bullets / summary) — the strong signal
      0.5  only in the Skills list, never shown in experience (half credit)
      0.0  not present where it counts (a stray mention elsewhere doesn't count)
    """
    pat = r"(?<![A-Za-z0-9])" + re.escape(term.lower()) + r"(?![A-Za-z0-9])"
    if re.search(pat, context):
        return 1.0
    if skills_list and re.search(pat, skills_list):
        return 0.5
    return 0.0


def score_resume(
    text: str,
    resume: Resume,
    jd: JobDescription | None,
    jd_raw: str | None = None,
) -> ScoreReport:
    has_jd = jd is not None
    subs: list[SubScore] = []
    suggestions: list[str] = []
    matched: list[str] = []
    missing: list[str] = []

    low_text = text.lower()
    context = _context_text(resume)
    skills_list = ", ".join(resume.skills).lower()

    # ===================== WITH a job description =====================
    if has_jd:
        raw = jd.raw or jd_raw or ""

        # ---- hard skills: frequency-weighted, context-aware (the dominant factor) ----
        hard = jd.hard_skills or [k for k in jd.keywords if k not in jd.soft_skills]
        hard_num = hard_den = 0.0
        partial: list[str] = []
        for kw in hard:
            w = 1 + min(keywords.count_occurrences(raw, kw), 3)   # high-freq matters more
            c = _credit(kw, context, skills_list, low_text)
            hard_num += w * c
            hard_den += w
            if c >= 1.0:
                matched.append(kw)
            elif c > 0:
                partial.append(kw); matched.append(kw)
            else:
                missing.append(kw)
        hard_score = hard_num / hard_den if hard_den else None

        # ---- soft skills: presence, much lighter ----
        def _bucket(terms: list[str]) -> float | None:
            if not terms:
                return None
            got = 0.0
            for t in terms:
                c = _credit(t, context, skills_list, low_text)
                got += c
                (matched if c > 0 else missing).append(t)
            return got / len(terms)

        soft_score = _bucket(jd.soft_skills)
        # "Other" JD keywords (domain terms the JD emphasizes that aren't in our skill
        # gazetteer). Real ATS like Jobscan DO count these (~15%): a resume that misses
        # them shouldn't score a perfect match. We weight them lightly, like Jobscan.
        other_score = _bucket(jd.other_keywords)

        # ---- combine, mirroring Jobscan's match-rate emphasis ----
        #   hard skills 70% · soft skills 15% · other JD keywords 15%
        Wh, Ws, Wo = 0.70, 0.15, 0.15
        num = den = 0.0
        for sc, w in ((hard_score, Wh), (soft_score, Ws), (other_score, Wo)):
            if sc is not None:
                num += sc * w
                den += w
        kw_component = round(100 * num / den) if den else 0

        # ---- keyword-stuffing penalty (mirrors real engines) ----
        listed = len(resume.skills)
        backed = sum(1 for s in resume.skills
                     if re.search(r"(?<![A-Za-z0-9])" + re.escape(s.lower()) + r"(?![A-Za-z0-9])", context))
        stuffed = listed >= 8 and (backed / listed) < 0.35
        if stuffed:
            kw_component = round(kw_component * 0.82)
            suggestions.append(
                "Many listed skills don't appear in your experience — real ATS flags this "
                "as keyword stuffing. Work the key skills into your bullet points instead.")

        detail = (f"{len([m for m in matched if m in hard])}/{len(hard)} hard skills matched"
                  + (f" ({len(partial)} only in your skills list — move these into experience)" if partial else "")
                  + ".")
        subs.append(SubScore(name="Keyword match (hard skills weighted)",
                             score=kw_component, weight=0.58, detail=detail))
        if missing:
            suggestions.append("Add these missing job keywords where genuinely true: "
                               + ", ".join([m for m in missing if m in hard][:6] or missing[:6]) + ".")

        # ---- job title match ----
        title_words = [w for w in _WORD.findall((jd.title or "").lower())
                       if w not in keywords.STOPWORDS and len(w) > 2]
        if title_words:
            resume_titles = (resume.summary + " " + " ".join(e.title for e in resume.experience)).lower()
            hit = sum(1 for w in title_words if re.search(r"(?<![A-Za-z0-9])" + re.escape(w) + r"(?![A-Za-z0-9])", resume_titles))
            title_score = round(100 * hit / len(title_words))
            subs.append(SubScore(name="Job title match", score=title_score, weight=0.14,
                                 detail=f"'{jd.title[:50]}' — {hit}/{len(title_words)} title words found in your roles/summary."))
            if title_score < 60:
                suggestions.append(f"Mirror the target job title ('{jd.title[:40]}') in your summary or a recent role.")

    # ===================== structure / format / content (always) =====================
    present = {
        "summary": bool(resume.summary),
        "skills": bool(resume.skills),
        "experience": bool(resume.experience),
        "education": bool(resume.education),
    }
    struct_score = round(100 * sum(present.values()) / len(present))
    subs.append(SubScore(name="Section structure", score=struct_score,
                         weight=0.03 if has_jd else 0.30,
                         detail="Detected: " + (", ".join(s for s, ok in present.items() if ok) or "none")))
    miss_sec = [s for s, ok in present.items() if not ok]
    if miss_sec:
        suggestions.append("Add standard section(s): " + ", ".join(miss_sec) + ".")

    fmt = 100
    notes: list[str] = []
    if not resume.email:
        fmt -= 25; notes.append("no email")
    if not resume.phone:
        fmt -= 15; notes.append("no phone")
    if not resume.name:
        fmt -= 15; notes.append("name unclear")
    words = len(low_text.split())
    if words < 130:
        fmt -= 18; notes.append("very short (<130 words)")
    elif words > 1200:
        fmt -= 10; notes.append("very long (>1200 words)")
    if text.count("\t") > 20:
        fmt -= 10; notes.append("tabs/columns may break parsing")
    fmt = max(0, fmt)
    subs.append(SubScore(name="Formatting & parse-ability", score=fmt,
                         weight=0.07 if has_jd else 0.30,
                         detail="; ".join(notes) if notes else "Contact info present, clean single-column text."))
    if not resume.email:
        suggestions.append("Add a professional email near the top.")

    bullets = [b for e in resume.experience for b in e.bullets]
    if bullets:
        content, cdetail, ctips = _bullet_quality(bullets)
        suggestions.extend(ctips)
    else:
        content, cdetail = 25, "No experience bullet points detected."
        suggestions.append("Describe each role with bullet points focused on impact.")
    subs.append(SubScore(name="Content quality", score=content,
                         weight=0.18 if has_jd else 0.25, detail=cdetail))

    if not has_jd:
        n = len(resume.skills)
        skill_score = min(100, round(n / 12 * 100))
        subs.append(SubScore(name="Skills breadth", score=skill_score, weight=0.15,
                             detail=f"{n} distinct skills detected."))
        if n < 6:
            suggestions.append("List more relevant hard skills/tools in a Skills section.")

    # ---- weighted overall ----
    total_w = sum(s.weight for s in subs) or 1
    overall = round(sum(s.score * s.weight for s in subs) / total_w)

    if not suggestions:
        suggestions.append("Strong match — make sure each claim is backed by real experience.")

    # de-dup keyword lists, preserve order
    matched = list(dict.fromkeys(matched))
    missing = list(dict.fromkeys(m for m in missing if m not in matched))

    return ScoreReport(
        overall=overall, rating=_rating(overall), has_jd=has_jd, subscores=subs,
        matched_keywords=matched, missing_keywords=missing,
        suggestions=list(dict.fromkeys(suggestions))[:8],
    )
