const $ = (s) => document.querySelector(s);
const api = (p, opt) => fetch(p, opt).then(r => r.json());
const initials = (n) => (n || "?").split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();

let pollTimer = null;
let allClients = [];
let detailData = null;
let sortMode = "match";          // "match" | "recent"

/* ---------------- clients grid ---------------- */
async function loadClients() {
  const data = await api("/api/clients");
  allClients = data.clients;
  const all = $("#allStatus");
  all.textContent = data.all_status === "running" ? "running daily for all…"
                  : data.all_status === "done" ? "all clients: done" : "";
  all.className = "status " + (data.all_status || "");
  renderClients();
  const anyRunning = data.all_status === "running" || allClients.some(c => c.status === "running");
  if (!anyRunning && pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function renderClients() {
  const q = ($("#search").value || "").toLowerCase();
  const list = allClients.filter(c => c.name.toLowerCase().includes(q));
  $("#emptyState").classList.toggle("hidden", allClients.length > 0);
  const grid = $("#clients");
  grid.innerHTML = "";
  list.forEach(c => {
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = `
      <div class="top">
        <div class="avatar">${initials(c.name)}</div>
        <span class="pill ${c.status}">${c.status}</span>
      </div>
      <h3>${c.name}</h3>
      <div style="margin:2px 0 4px"><span class="mode ${c.apply_mode}">${c.apply_mode === "automated" ? "⚡ Automated" : "👁 Supervised"}</span></div>
      <div class="titles">${(c.titles || []).join(" · ") || "—"}</div>
      <div class="stats">
        <div class="stat"><b>${c.shortlist_count}</b><span>matches</span></div>
        <div class="stat"><b>${c.golden}</b><span>golden</span></div>
        <div class="stat"><b>${c.skills_count}</b><span>skills</span></div>
        <div class="stat"><b>${c.years ?? "—"}</b><span>yrs</span></div>
      </div>
      <div class="row" style="display:flex;gap:8px;margin-top:14px">
        <button class="btn sm primary" data-run="${c.slug}">▶ Run daily</button>
        <button class="btn sm" data-open="${c.slug}">Open</button>
      </div>`;
    el.querySelector(".avatar").onclick = () => openDetail(c.slug);
    el.querySelector("h3").onclick = () => openDetail(c.slug);
    el.querySelector("[data-open]").onclick = (e) => { e.stopPropagation(); openDetail(c.slug); };
    el.querySelector("[data-run]").onclick = async (e) => {
      e.stopPropagation();
      await api(`/api/clients/${c.slug}/run`, { method: "POST" });
      startPolling();
    };
    grid.appendChild(el);
  });
}

function startPolling() { loadClients(); if (!pollTimer) pollTimer = setInterval(loadClients, 4000); }

/* ---------------- detail ---------------- */
async function openDetail(slug) {
  detailData = await api(`/api/clients/${slug}`);
  detailData.slug = slug;
  $("#clientsView").classList.add("hidden");
  $("#detailView").classList.remove("hidden");
  renderDetail();
}

function renderDetail() {
  const d = detailData, p = d.profile, wa = p.work_auth || {};
  const golden = (d.tailored || []).filter(t => t.golden).length;
  const tail = (d.tailored || []).map(t => `
    <tr>
      <td class="fit ${t.fit_score >= 75 ? "hi" : "mid"}">${Math.round(t.fit_score)}%</td>
      <td>${t.score_before} → <b>${t.score_after}</b></td>
      <td>${t.golden ? '<span class="gold-pill">✓ golden</span>' : '<span class="warn-pill">below 75</span>'}</td>
      <td><a class="joblink" href="${t.url}" target="_blank">${t.title}</a>
        ${t.status && t.status !== "pending" ? `<span class="statepill ${t.status}">${t.status}</span>` : ""}</td>
      <td><button class="btn sm primary" data-review="${t.file}">Review</button></td>
    </tr>`).join("");

  $("#detail").innerHTML = `
    <h2 class="name">${p.full_name || d.slug}</h2>
    <div class="profile">
      <div class="editbar">
        <strong style="font-size:13px;color:#475569">Profile (driven by their resume — editable)</strong>
        <div style="display:flex;align-items:center;gap:12px">
          <span style="font-size:12px;color:#6b7280">Apply mode:</span>
          <div class="seg">
            <button id="mode_supervised" class="${p.apply_mode!=='automated'?'active':''}">👁 Supervised</button>
            <button id="mode_automated" class="${p.apply_mode==='automated'?'active':''}">⚡ Automated</button>
          </div>
          <span id="autoWrap" style="font-size:12px;color:#6b7280;${p.apply_mode==='automated'?'':'display:none'}">
            auto-submit ≥ <input id="e_automin" value="${p.auto_min_match ?? 80}" style="width:46px;border:1px solid var(--line);border-radius:6px;padding:3px 5px">%</span>
          <button class="btn sm primary" id="saveProfile">Save changes</button>
          <button class="btn sm danger" id="delClient">Delete</button>
        </div>
      </div>
      <div class="row">
        <div class="fld"><span>Email</span><input id="e_email" value="${p.email || ""}"></div>
        <div class="fld"><span>Location</span><input id="e_location" value="${p.location || ""}"></div>
        <div class="fld"><span>Experience (yrs)</span><input id="e_years" value="${p.years_experience ?? ""}" style="min-width:80px"></div>
        <div class="fld"><span>Visa status</span><input id="e_visa" value="${wa.visa_status || ""}"></div>
        <div class="fld"><span>Needs sponsorship</span><input id="e_sponsor" value="${wa.requires_sponsorship ?? ""}" style="min-width:90px"></div>
        <div class="fld"><span>Desired salary</span><input id="e_salary" value="${p.desired_salary || ""}"></div>
      </div>
      <div class="row" style="margin-top:12px">
        <div class="fld" style="flex:1"><span>Target titles</span><input id="e_titles" value="${(p.target_titles||[]).join(", ")}" style="width:100%"></div>
      </div>
      <div class="row" style="margin-top:12px">
        <div class="fld" style="flex:1"><span>Skills</span><input id="e_skills" value="${(p.skills||[]).join(", ")}" style="width:100%"></div>
      </div>
    </div>

    <div class="profile">
      <strong style="font-size:13px;color:#475569">Application answers (optional knowledge — the AI uses these intelligently, never pasted)</strong>
      <div class="row" style="margin-top:10px">
        ${bankFields(p.answer_bank || {})}
      </div>
    </div>

    <div class="section-head">
      <h3>Golden tailored resumes <span style="color:#6b7280;font-weight:400">(${golden})</span></h3>
    </div>
    ${tail ? `<table><thead><tr><th>Fit</th><th>ATS</th><th>Standard</th><th>Job</th><th>Resume</th></tr></thead><tbody>${tail}</tbody></table>`
           : `<p style="color:#6b7280">No tailored resumes yet — click “Run daily”.</p>`}

    <div class="section-head">
      <h3>Matched jobs <span style="color:#6b7280;font-weight:400">(${(d.shortlist||[]).length})</span></h3>
      <div class="sortwrap">Sort:
        <div class="seg">
          <button data-sort="match" class="${sortMode==='match'?'active':''}">Match %</button>
          <button data-sort="recent" class="${sortMode==='recent'?'active':''}">Most recent</button>
        </div>
      </div>
    </div>
    <div id="shortlistTable"></div>`;

  renderShortlist();
  detailData._mode = p.apply_mode || "supervised";
  const setMode = (m) => {
    detailData._mode = m;
    $("#mode_supervised").classList.toggle("active", m !== "automated");
    $("#mode_automated").classList.toggle("active", m === "automated");
    $("#autoWrap").style.display = m === "automated" ? "" : "none";
  };
  $("#mode_supervised").onclick = () => setMode("supervised");
  $("#mode_automated").onclick = () => setMode("automated");
  $("#saveProfile").onclick = saveProfile;
  $("#delClient").onclick = deleteClient;
  document.querySelectorAll("[data-sort]").forEach(b => b.onclick = () => { sortMode = b.dataset.sort; renderDetail(); });
  document.querySelectorAll("[data-review]").forEach(b => b.onclick = () => openApp(b.dataset.review));
}

function renderShortlist() {
  const rows = [...(detailData.shortlist || [])];
  const da = (j) => (j.days_ago === "" || j.days_ago == null) ? 999 : +j.days_ago;
  rows.sort((a, b) => sortMode === "recent" ? (da(a) - da(b)) || (b.match - a.match)
                                            : (b.match - a.match) || (da(a) - da(b)));
  const spons = (s, n) => s === "yes" ? `<span class="gold-pill">H-1B ✓ (${n})</span>`
                        : s === "no" ? `<span class="warn-pill">no H-1B</span>`
                        : `<span style="color:#9ca3af">H-1B ?</span>`;
  const dtag = (j) => { const n = da(j); return n === 999 ? `<span class="daytag">unknown</span>`
    : n === 0 ? `<span class="daytag today">today</span>` : `<span class="daytag">${n}d ago</span>`; };
  const html = `<table><thead><tr><th>Match</th><th>Verdict</th><th>Sponsorship</th><th>Posted</th><th>Job (✓ strengths / △ gaps)</th><th>Company</th></tr></thead><tbody>${
    rows.map(j => `
      <tr>
        <td class="fit ${j.match>=75?"hi":j.match>=60?"mid":"lo"}">${Math.round(j.match)}%</td>
        <td>${j.verdict || ""}</td>
        <td>${spons(j.sponsors_h1b, j.h1b_approvals)}</td>
        <td>${dtag(j)}</td>
        <td><a class="joblink" href="${j.url}" target="_blank">${j.title}</a>
          ${j.strengths ? `<div class="changes">✓ ${j.strengths}</div>` : ""}
          ${j.gaps ? `<div class="changes" style="color:#b45309">△ ${j.gaps}</div>` : ""}</td>
        <td>${j.company}</td>
      </tr>`).join("")}</tbody></table>`;
  $("#shortlistTable").innerHTML = rows.length ? html : `<p style="color:#6b7280">No matches yet — click “Run daily”.</p>`;
}

const BANK_TOPICS = [
  ["why_interested", "Why interested (role/company fit)"],
  ["willing_to_relocate", "Willing to relocate?"],
  ["start_date", "Start date / notice period"],
  ["remote_preference", "Remote / hybrid / onsite"],
  ["how_heard", "How did you hear about us"],
  ["references", "References"],
  ["portfolio", "Portfolio / GitHub"],
  ["notes", "Other notes for screening Qs"],
];
function bankFields(bank) {
  return BANK_TOPICS.map(([k, label]) =>
    `<div class="fld" style="flex:1 1 300px"><span>${label}</span>
       <input id="bank_${k}" value="${(bank[k] || "").replace(/"/g, "&quot;")}" style="width:100%"></div>`).join("");
}

async function saveProfile() {
  const v = (id) => $(id).value.trim();
  const list = (id) => v(id) ? v(id).split(",").map(s => s.trim()).filter(Boolean) : [];
  const bank = {};
  BANK_TOPICS.forEach(([k]) => { const el = $("#bank_" + k); if (el && el.value.trim()) bank[k] = el.value.trim(); });
  const payload = {
    email: v("#e_email"), location: v("#e_location"), desired_salary: v("#e_salary"),
    years_experience: v("#e_years"), skills: list("#e_skills"), target_titles: list("#e_titles"),
    work_auth: { visa_status: v("#e_visa"), requires_sponsorship: v("#e_sponsor") },
    answer_bank: bank,
    apply_mode: detailData._mode || "supervised",
    auto_min_match: v("#e_automin") || 80,
  };
  await fetch(`/api/clients/${detailData.slug}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  $("#saveProfile").textContent = "Saved ✓";
  setTimeout(() => { if ($("#saveProfile")) $("#saveProfile").textContent = "Save changes"; }, 1500);
}

async function deleteClient() {
  if (!confirm(`Delete ${detailData.profile.full_name || detailData.slug}? This removes their data.`)) return;
  await fetch(`/api/clients/${detailData.slug}`, { method: "DELETE" });
  backToClients();
}

/* ---------------- add candidate ---------------- */
function openAdd() { $("#addModal").classList.remove("hidden"); }
function closeAdd() { $("#addModal").classList.add("hidden"); $("#addForm").reset(); $("#dropText").textContent = "📄 Drop a resume here, or click to choose (PDF/DOCX)"; $("#drop").classList.remove("has"); $("#addStatus").textContent = ""; }
window.closeAdd = closeAdd;

$("#addBtn").onclick = openAdd;
$("#drop").onclick = () => $("#resumeFile").click();
$("#resumeFile").onchange = () => {
  const f = $("#resumeFile").files[0];
  if (f) { $("#dropText").textContent = "📄 " + f.name; $("#drop").classList.add("has"); }
};
$("#addForm").onsubmit = async (e) => {
  e.preventDefault();
  const f = $("#resumeFile").files[0];
  if (!f) { $("#addStatus").textContent = "Choose a resume first."; return; }
  const fd = new FormData();
  fd.append("file", f);
  fd.append("name", $("#f_name").value);
  fd.append("email", $("#f_email").value);
  fd.append("visa_status", $("#f_visa").value);
  fd.append("desired_salary", $("#f_salary").value);
  fd.append("requires_sponsorship", $("#f_sponsor").value);
  fd.append("authorized_us", $("#f_auth").value);
  fd.append("locations", $("#f_locs").value);
  $("#addSubmit").disabled = true; $("#addStatus").textContent = "Reading resume…";
  try {
    const r = await fetch("/api/clients", { method: "POST", body: fd });
    if (!r.ok) throw new Error((await r.json()).detail || "failed");
    closeAdd();
    await loadClients();
  } catch (err) {
    $("#addStatus").className = "status error"; $("#addStatus").textContent = String(err.message || err);
  } finally { $("#addSubmit").disabled = false; }
};

/* ---------------- application review (edit + comments + submit) ---------------- */
let appData = null;
async function openApp(file) {
  appData = await api(`/api/clients/${detailData.slug}/application/${file}`);
  appData.file = file;
  $("#appTitle").textContent = appData.title || "Application review";
  $("#appMeta").innerHTML = `Fit <b>${Math.round(appData.fit_score||0)}%</b> · ATS ${appData.score_before} → <b>${appData.score_after}</b>
     ${appData.golden ? '<span class="gold-pill">✓ golden</span>' : ''} · <a class="joblink" href="${appData.url}" target="_blank">job ↗</a>`;
  const r = appData.resume;
  const ans = (appData.answers || []).map((a, i) => `
    <div class="ansrow">
      <label>${a.label}${a.needs_human ? ' <span class="warn-pill">⚠ check</span>' : ''}</label>
      <input id="ans_${i}" value="${(a.value || "").replace(/"/g, "&quot;")}">
    </div>`).join("");
  const roles = r.experience.map((e, i) => `
    <div class="role-edit">
      <div class="role-h">${e.title}${e.company ? " — " + e.company : ""}</div>
      <textarea id="bul_${i}" rows="${Math.max(3, e.bullets.length)}">${e.bullets.join("\n")}</textarea>
    </div>`).join("");

  $("#appBody").innerHTML = `
    <div class="app-grid">
      <div>
        <h4>Tailored resume <small>(edit freely — PDF reflects your edits)</small></h4>
        <label class="lbl">Summary</label>
        <textarea id="app_summary" rows="4">${r.summary || ""}</textarea>
        <label class="lbl">Experience bullets (one per line)</label>
        ${roles}
        ${appData.changes && appData.changes.length ? `<details class="changes-d"><summary>What the AI changed (${appData.changes.length})</summary><ul>${appData.changes.map(c => `<li>${c}</li>`).join("")}</ul></details>` : ""}
      </div>
      <div>
        <h4>Application answers <small>(edit any)</small></h4>
        ${ans || '<p style="color:#6b7280;font-size:13px">No form answers (non-Greenhouse or none generated).</p>'}
        <h4 style="margin-top:18px">Recruiter comments</h4>
        <textarea id="app_comments" rows="4" placeholder="Notes / instructions — saved with this application">${appData.comments || ""}</textarea>
      </div>
    </div>`;
  $("#appPdf").href = `/api/clients/${detailData.slug}/resume/${file}`;
  $("#appStatus").textContent = appData.status !== "pending" ? `status: ${appData.status}` : "";
  $("#appSubmit").textContent = detailData._mode === "automated" ? "✓ Mark submitted" : "✓ Approve & submit";
  $("#appModal").classList.remove("hidden");
}
function collectApp() {
  const exp = (appData.resume.experience || []).map((e, i) => ({
    bullets: ($("#bul_" + i).value || "").split("\n").map(s => s.trim()).filter(Boolean) }));
  const answers = (appData.answers || []).map((a, i) => ({ ...a, value: $("#ans_" + i)?.value ?? a.value }));
  return { summary: $("#app_summary").value, experience: exp, answers, comments: $("#app_comments").value };
}
async function saveApp(status) {
  const payload = collectApp();
  if (status) payload.status = status;
  $("#appStatus").textContent = "saving…";
  await fetch(`/api/clients/${detailData.slug}/application/${appData.file}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  $("#appStatus").textContent = status ? `status: ${status}` : "saved ✓";
}
function closeApp() { $("#appModal").classList.add("hidden"); $("#appPreviewArea").classList.add("hidden"); appData = null; }
window.openApp = openApp; window.closeApp = closeApp;
$("#appSave").onclick = () => saveApp(null);

// Preview: fill the REAL form in a browser and show the screenshot for verification.
$("#appPreview").onclick = async () => {
  await saveApp(null);                 // persist edits first so the fill uses them
  const area = $("#appPreviewArea");
  area.classList.remove("hidden");
  area.innerHTML = `<div class="preview-load">⏳ Opening the real job form and filling it… (10-20s)</div>`;
  try {
    const res = await api(`/api/clients/${detailData.slug}/application/${appData.file}/fill?submit=false`, { method: "POST" });
    if (res.screenshot) {
      area.innerHTML = `
        <div class="preview-head">📸 This is the AI filling the <b>real</b> application form. Verify, then Approve & submit.
          <span class="muted"> · filled ${res.filled.length}, skipped ${res.skipped.length}${res.needs_review ? ' · ⚠ some fields need your input' : ''}</span></div>
        <img class="preview-img" src="${res.screenshot}?t=${Date.now()}" alt="filled form">`;
    } else {
      area.innerHTML = `<div class="preview-load">Couldn't preview: ${res.reason || res.note || "only Greenhouse forms supported"}.</div>`;
    }
  } catch (e) {
    area.innerHTML = `<div class="preview-load">Preview failed: ${e.message || e}. (Is the ATS engine running on :8000?)</div>`;
  }
};

// Approve & submit: actually submit the real form (supervised approval).
$("#appSubmit").onclick = async () => {
  await saveApp(null);
  if (!confirm("Submit this application on the real job site now?")) return;
  $("#appStatus").textContent = "submitting on the real form…";
  try {
    const res = await api(`/api/clients/${detailData.slug}/application/${appData.file}/fill?submit=true`, { method: "POST" });
    if (res.status === "submitted") { $("#appStatus").textContent = "submitted ✓"; setTimeout(() => { closeApp(); openDetail(detailData.slug); }, 900); }
    else { $("#appStatus").textContent = res.reason || res.note || `status: ${res.status}`; }
  } catch (e) { $("#appStatus").textContent = "submit failed: " + (e.message || e); }
};

/* ---------------- nav / global ---------------- */
function backToClients() {
  $("#detailView").classList.add("hidden");
  $("#clientsView").classList.remove("hidden");
  loadClients();
}
$("#back").onclick = backToClients;
$("#search").oninput = renderClients;
$("#runAll").onclick = async () => { await api("/api/run-all", { method: "POST" }); startPolling(); };

loadClients();
