// ATS Resume Maker — frontend logic (vanilla JS, no build step).
const $ = (s) => document.querySelector(s);
const API = ""; // same origin — backend serves this page

const state = { tailorFile: null, scoreFile: null, lastTailoredResume: null };

// ---------- AI availability badge ----------
fetch(API + "/api/health").then(r => r.json()).then(h => {
  const b = $("#ai-badge");
  if (h.engine === "claude") { b.textContent = "AI on · Claude"; b.className = "badge badge-on"; }
  else if (h.engine === "ollama") { b.textContent = "AI on · Ollama"; b.className = "badge badge-on"; }
  else { b.textContent = "Offline mode (no AI) — scoring works"; b.className = "badge badge-off"; }
}).catch(() => { $("#ai-badge").textContent = "API offline"; $("#ai-badge").className = "badge badge-off"; });

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
  t.classList.add("active");
  $("#tab-tailor").classList.toggle("hidden", t.dataset.tab !== "tailor");
  $("#tab-score").classList.toggle("hidden", t.dataset.tab !== "score");
  hide($("#results")); hide($("#error"));
}));

// ---------- dropzones ----------
function wireDrop(dzId, inputId, fnId, key) {
  const dz = $(dzId), input = $(inputId), fn = $(fnId);
  dz.addEventListener("click", () => input.click());
  input.addEventListener("change", () => setFile(input.files[0]));
  ["dragover", "dragenter"].forEach(e => dz.addEventListener(e, ev => { ev.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach(e => dz.addEventListener(e, ev => { ev.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", ev => setFile(ev.dataTransfer.files[0]));
  function setFile(f) { if (!f) return; state[key] = f; fn.textContent = "✓ " + f.name; }
}
wireDrop("#dz-tailor", "#file-tailor", "#fn-tailor", "tailorFile");
wireDrop("#dz-score", "#file-score", "#fn-score", "scoreFile");

// ---------- helpers ----------
const show = (el) => el.classList.remove("hidden");
const hide = (el) => el.classList.add("hidden");
function busy(on, msg) { $("#loading-text").textContent = msg || "Working…"; on ? show($("#loading")) : hide($("#loading")); document.querySelectorAll(".primary").forEach(b => b.disabled = on); }
function fail(msg) { const e = $("#error"); e.textContent = "⚠ " + msg; show(e); }
const color = (v) => v >= 70 ? "var(--good)" : v >= 50 ? "var(--warn)" : "var(--bad)";
const esc = (s) => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// ---------- SCORE ----------
$("#btn-score").addEventListener("click", async () => {
  hide($("#error")); hide($("#results"));
  if (!state.scoreFile) return fail("Please upload a resume first.");
  const fd = new FormData();
  fd.append("file", state.scoreFile);
  const jd = $("#jd-score").value.trim();
  if (jd) fd.append("job_description", jd);
  busy(true, "Analyzing your resume with AI… this can take 10–20 seconds.");
  try {
    const r = await fetch(API + "/api/score", { method: "POST", body: fd });
    if (!r.ok) throw new Error((await r.json()).detail || "Scoring failed");
    renderScoreOnly(await r.json());
  } catch (e) { fail(e.message); } finally { busy(false); }
});

// ---------- TAILOR ----------
$("#btn-tailor").addEventListener("click", async () => {
  hide($("#error")); hide($("#results"));
  if (!state.tailorFile) return fail("Please upload a resume first.");
  const jd = $("#jd-tailor").value.trim();
  if (!jd) return fail("Please paste the job description to tailor against.");
  const fd = new FormData();
  fd.append("file", state.tailorFile);
  fd.append("job_description", jd);
  busy(true, "AI is tailoring your resume… this can take 10–30 seconds.");
  try {
    const r = await fetch(API + "/api/tailor", { method: "POST", body: fd });
    if (!r.ok) throw new Error((await r.json()).detail || "Tailoring failed");
    renderTailor(await r.json());
  } catch (e) { fail(e.message); } finally { busy(false); }
});

// ---------- renderers ----------
function gauge(v) {
  return `<div class="gauge" style="--val:${v}; --gc:${color(v)}">
    <div class="inner"><div><div class="num">${v}</div><div class="lbl">/100</div></div></div></div>`;
}
function subBars(report) {
  return report.subscores.map(s => `
    <div class="sub">
      <div class="sub-top"><span>${esc(s.name)}</span><span>${s.score}</span></div>
      <div class="bar"><i style="width:${s.score}%; background:${color(s.score)}"></i></div>
      <div class="sub-detail">${esc(s.detail)}</div>
    </div>`).join("");
}
function keywordBlock(report) {
  if (!report.has_jd) return "";
  const ok = report.matched_keywords.slice(0, 30).map(k => `<span class="chip ok">${esc(k)}</span>`).join("");
  const miss = report.missing_keywords.slice(0, 30).map(k => `<span class="chip miss">${esc(k)}</span>`).join("");
  return `<div class="card"><h3>Keyword match</h3>
    <p class="sub-detail" style="margin:0 0 6px">✓ Found (${report.matched_keywords.length})</p>
    <div class="chips">${ok || "<span class='sub-detail'>none</span>"}</div>
    <p class="sub-detail" style="margin:14px 0 6px">✗ Missing — add if genuinely true (${report.missing_keywords.length})</p>
    <div class="chips">${miss || "<span class='sub-detail'>none — great!</span>"}</div></div>`;
}
function scoreCard(report, title) {
  return `<div class="card"><h3>${title}</h3>
    <div class="score-hero">${gauge(report.overall)}
      <div><div class="rating" style="color:${color(report.overall)}">${esc(report.rating)}
      <small>${report.has_jd ? "scored against the job description" : "general ATS readiness (no JD)"}</small></div></div></div>
    <div style="margin-top:16px">${subBars(report)}</div></div>`;
}
function suggCard(report) {
  return `<div class="card"><h3>How to improve</h3>
    <ul class="sugg">${report.suggestions.map(s => `<li>${esc(s)}</li>`).join("")}</ul></div>`;
}
function ulist(arr) { return `<ul class="sugg">${arr.map(x => `<li>${esc(x)}</li>`).join("")}</ul>`; }
function aiReviewCard(report) {
  const a = report.ai_review;
  if (!a) return "";
  return `<div class="card">
    <h3>🧠 Professional review <span class="ai-pill">AI · Claude</span></h3>
    ${a.verdict ? `<p style="font-weight:600;margin:0 0 6px">${esc(a.verdict)}</p>` : ""}
    ${a.strengths.length ? `<div class="rev-h" style="color:var(--good)">✓ Strengths</div>${ulist(a.strengths)}` : ""}
    ${a.weaknesses.length ? `<div class="rev-h" style="color:var(--bad)">✗ Weaknesses</div>${ulist(a.weaknesses)}` : ""}
    ${a.fixes.length ? `<div class="rev-h" style="color:var(--brand)">🛠 Prioritized fixes</div>${ulist(a.fixes)}` : ""}
    ${a.ats_tips.length ? `<div class="rev-h">🧱 ATS formatting tips</div>${ulist(a.ats_tips)}` : ""}
  </div>`;
}

function renderScoreOnly(report) {
  $("#results").innerHTML = scoreCard(report, "Your ATS score") + aiReviewCard(report) + keywordBlock(report) + suggCard(report);
  show($("#results"));
}

function renderTailor(res) {
  state.lastTailoredResume = res.tailored_resume;
  const before = res.score_before.overall, after = res.score_after.overall;
  const diff = after - before;
  const engineTag = res.engine === "claude" ? "· ✨ AI-tailored (Claude)"
                  : res.engine === "ollama" ? "· ✨ AI-tailored (Ollama)"
                  : "· rule-based (no fabrication)";
  let deltaBadge, note = "";
  if (diff > 0) {
    deltaBadge = `<span class="up">▲ +${diff} points</span>`;
  } else {
    deltaBadge = `<span style="color:var(--muted)">no automatic gain</span>`;
    note = `<p class="sub-detail" style="margin:12px 0 0">Honest result: the safe, no-fabrication
      changes didn't raise the score for this resume — the remaining gap is <b>real content</b>.
      See <b>What changed</b> below for the exact skills to add to your experience (only if true).</p>`;
  }
  const deltaCard = `<div class="card"><h3>Result ${engineTag}</h3>
    <div class="delta">
      <span>Before <b style="color:${color(before)}">${before}</b></span>
      <span>→</span>
      <span>After <b style="color:${color(after)}">${after}</b></span>
      ${deltaBadge}
    </div>${note}
    <div class="downloads" style="margin-top:18px">
      <button class="btn-dl" data-fmt="pdf">⬇ Download PDF</button>
      <button class="btn-dl" data-fmt="docx">⬇ Download DOCX</button>
      <button class="btn-dl" data-fmt="txt">⬇ Download TXT</button>
    </div></div>`;
  const changesCard = `<div class="card"><h3>What changed</h3>
    <ul class="changes">${res.changes.map(c => `<li>${esc(c)}</li>`).join("")}</ul></div>`;
  $("#results").innerHTML = deltaCard + changesCard +
    scoreCard(res.score_after, "New score breakdown") + keywordBlock(res.score_after);
  show($("#results"));
  document.querySelectorAll(".btn-dl").forEach(b => b.addEventListener("click", () => download(b.dataset.fmt)));
}

async function download(fmt) {
  if (!state.lastTailoredResume) return;
  try {
    const r = await fetch(API + "/api/export?format=" + fmt, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.lastTailoredResume),
    });
    if (!r.ok) throw new Error("Export failed");
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = (state.lastTailoredResume.name || "resume").replace(/\s+/g, "_") + "_tailored." + fmt;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) { fail(e.message); }
}
