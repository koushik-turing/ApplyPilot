const $ = (s) => document.querySelector(s);
const api = (p, opt) => fetch(p, opt).then(r => r.json());

let pollTimer = null;

async function loadClients() {
  const data = await api("/api/clients");
  const all = $("#allStatus");
  all.textContent = data.all_status === "running" ? "running daily for all…"
                  : data.all_status === "done" ? "last run: done" : "";
  all.className = "status " + (data.all_status || "");

  const grid = $("#clients");
  grid.innerHTML = "";
  data.clients.forEach(c => {
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = `
      <h3>${c.name}</h3>
      <div class="titles">${(c.titles || []).join(" · ") || "—"}</div>
      <div class="stats">
        <div class="stat"><b>${c.shortlist_count}</b><span>fresh+fit</span></div>
        <div class="stat"><b>${c.golden}</b><span>golden</span></div>
        <div class="stat"><b>${c.skills_count}</b><span>skills</span></div>
      </div>
      <div class="row">
        <span class="badge ${c.golden ? "gold" : ""}">${c.status}</span>
        <button class="btn" data-run="${c.slug}">Run daily</button>
      </div>`;
    el.querySelector("h3").onclick = () => openDetail(c.slug);
    el.querySelector(".titles").onclick = () => openDetail(c.slug);
    el.querySelector(".stats").onclick = () => openDetail(c.slug);
    el.querySelector("[data-run]").onclick = async (e) => {
      e.stopPropagation();
      await api(`/api/clients/${c.slug}/run`, { method: "POST" });
      startPolling();
    };
    grid.appendChild(el);
  });

  const anyRunning = data.all_status === "running" || data.clients.some(c => c.status === "running");
  if (!anyRunning && pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function startPolling() {
  loadClients();
  if (!pollTimer) pollTimer = setInterval(loadClients, 4000);
}

async function openDetail(slug) {
  const d = await api(`/api/clients/${slug}`);
  $("#clientsView").classList.add("hidden");
  $("#detailView").classList.remove("hidden");
  const p = d.profile;
  const wa = p.work_auth || {};
  const rows = (d.shortlist || []).map(j => `
    <tr>
      <td class="fit ${(+j.match) >= 75 ? "hi" : ""}">${Math.round(j.match)}%</td>
      <td>${j.verdict || ""}</td>
      <td>${j.days_ago}d ago</td>
      <td>
        <a class="joblink" href="${j.url}" target="_blank">${j.title}</a>
        ${j.strengths ? `<div class="changes">✓ ${j.strengths}</div>` : ""}
        ${j.gaps ? `<div class="changes" style="color:#b45309">△ ${j.gaps}</div>` : ""}
      </td>
      <td>${j.company}</td>
    </tr>`).join("");
  const tail = (d.tailored || []).map(t => `
    <tr>
      <td class="fit ${(+t.fit_score) >= 75 ? "hi" : ""}">${Math.round(t.fit_score)}</td>
      <td>${t.score_before} → <b>${t.score_after}</b></td>
      <td>${t.golden ? '<span class="gold-pill">✓ golden</span>' : '<span class="warn-pill">below 75</span>'}</td>
      <td><a class="joblink" href="${t.url}" target="_blank">${t.title}</a></td>
      <td><a class="btn" href="/api/clients/${slug}/resume/${t.file}" >PDF</a></td>
    </tr>`).join("");

  $("#detail").innerHTML = `
    <h2>${p.full_name || slug}</h2>
    <div class="profile">
      <div><span>email</span>${p.email || "—"}</div>
      <div><span>location</span>${p.location || "—"}</div>
      <div><span>experience</span>${p.years_experience ?? "—"} yrs</div>
      <div><span>work auth</span>${wa.visa_status || "—"}${wa.requires_sponsorship ? " (needs sponsor)" : ""}</div>
      <div><span>salary</span>${p.desired_salary || "—"}</div>
      <div><span>top skills</span>${(p.skills || []).slice(0,8).join(", ")}</div>
    </div>
    <h3 class="section">Golden tailored resumes (${(d.tailored||[]).filter(t=>t.golden).length})</h3>
    ${tail ? `<table><thead><tr><th>Fit</th><th>ATS</th><th>Standard</th><th>Job</th><th>Resume</th></tr></thead><tbody>${tail}</tbody></table>`
           : `<p style="color:#6b7280">No tailored resumes yet — click “Run daily”.</p>`}
    <h3 class="section">Today's fresh + fit shortlist (${(d.shortlist||[]).length})</h3>
    ${rows ? `<table><thead><tr><th>Match</th><th>Verdict</th><th>Posted</th><th>Job (✓ strengths / △ gaps)</th><th>Company</th></tr></thead><tbody>${rows}</tbody></table>`
           : `<p style="color:#6b7280">No shortlist yet — click “Run daily”.</p>`}
  `;
}

$("#back").onclick = () => {
  $("#detailView").classList.add("hidden");
  $("#clientsView").classList.remove("hidden");
  loadClients();
};
$("#runAll").onclick = async () => {
  await api("/api/run-all", { method: "POST" });
  startPolling();
};

loadClients();
