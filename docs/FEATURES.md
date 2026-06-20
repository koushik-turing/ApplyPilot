# Feature Roadmap — match the competitors, then beat them

Goal: combine the best features of every competitor into one product, and add the
things **none** of them have (multi-candidate, sponsorship + auto-apply together).

## What each competitor does well (and we will match)

| Competitor | Their strong feature | Our plan |
|---|---|---|
| **Jobright.ai** | AI job matching, "why this job" insights, AI resume tailoring, **autofill**, application tracker, AI copilot (Orion) | Match all — plus *true* auto-submit, not just autofill |
| **MigrateMate** | **Visa-sponsorship-accurate** matching (LCA/USCIS govt data), employer verification, hiring-manager contacts | Already have USCIS H-1B data → tag every job `sponsors_h1b: yes (N)` |
| **ApplyPilot** | Full autonomous pipeline, `resume_facts` anti-hallucination lock | Match — with API-first (lower ban-risk) |
| **career-ops** | Reasoning-based fit scoring (A–F), reusable STAR stories | Match — Claude scoring + story library |
| **AIHawk** | Persistent answer cache (reuse answers across jobs) | Match — L2 cache in answer engine |

## Our differentiators (NO competitor has these)
1. **Multi-candidate** — run for many people at once (agencies). *Everyone else is single-user.*
2. **Sponsorship-aware + auto-apply together** — MigrateMate targets but won't apply; the appliers ignore visas. We do both.
3. **API-first → low ban-risk** — Greenhouse/Lever/Ashby APIs, not LinkedIn scraping.
4. **Confidence-gated review → auto** — safe by default, full-auto once trusted per candidate.
5. **Email loop** — captures confirmations, OTPs, recruiter replies automatically.

## Feature checklist (build order)
- [x] API-first job discovery (Greenhouse/Lever/Ashby) ✅ have
- [x] AI fit scoring 1–10 ✅ have
- [x] Sponsorship tagging (USCIS H-1B) ✅ have (1 candidate)
- [x] Resume tailoring (ATS_Resume_Maker) ✅ have
- [ ] **Personalized answer engine** (visa/salary deterministic, free-text via Claude) ← building
- [ ] **Auto-fill + submit** (review-then-auto) ← building
- [ ] Application tracker + status pipeline (CRM view)
- [ ] "Why this job" reasoning per match
- [ ] Answer cache (reuse across jobs)
- [ ] Reusable STAR story library per candidate
- [ ] Email loop (Gmail OAuth: confirmations/OTPs/replies)
- [ ] Dashboard (multi-candidate, review queue with screenshots, auto toggle)
- [ ] Hiring-manager / referral contacts (MigrateMate-style)
- [ ] Analytics (response rate, best boards/titles, cost)

## Positioning one-liner
> The only **multi-candidate**, **sponsorship-aware** job agent that **actually submits**
> applications — safely (API-first, review-gated), powered by Claude.
