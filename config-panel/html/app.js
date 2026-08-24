// OntoSage Admin Console — tabbed SPA over the orchestrator admin API (same-origin
// via nginx proxy). Tabs: Data Sources · Settings(.env) · Databases · Health.

const state = {
  token: localStorage.getItem("ds_token") || null,
  user: localStorage.getItem("ds_user") || null,
  sources: [],
  mask: "********",
};
const $ = (id) => document.getElementById(id);

function authHeaders() {
  return state.token ? { Authorization: "Bearer " + state.token } : {};
}
async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...(opts.headers || {}) },
  });
  let body = {};
  try { body = await res.json(); } catch (_) {}
  if (res.status === 401 || res.status === 403)
    throw new Error("Not authorised — sign in with an admin account.");
  if (res.status === 429) {
    // The API allows a fixed number of requests per minute per client. Bulk work in
    // the console (deleting many users in a row) can reach it; the old code let the
    // dataless 429 body through and callers crashed on `body.data.roles`.
    const wait = parseInt(res.headers.get("Retry-After") || "60", 10);
    const err = new Error(`Too many requests — the API is rate limited. Retrying in ${wait}s.`);
    err.rateLimited = true;
    err.retryAfter = wait;
    throw err;
  }
  return { status: res.status, body };
}
function toast(msg, kind = "ok") {
  const t = $("toast");
  t.textContent = msg; t.className = "toast " + kind; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 3400);
}
const RECREATE_CMD = "docker compose up -d orchestrator";

// ── Orchestrator restart (self-SIGTERM → Docker restart policy) + live status ──
// Status is mirrored to every per-tab .restart-status span so whichever tab is
// visible shows it. NOTE: a restart reloads code; .env changes need a recreate.
let _restarting = false;
const _restartBtns = () => [...document.querySelectorAll("[data-restart]")];
function setRestartStatus(kind, text) {
  document.querySelectorAll(".restart-status").forEach((el) => {
    el.innerHTML = kind ? `<span class="dot ${kind}"></span>${text}` : "";
  });
}
async function restartOrchestrator() {
  if (_restarting) return;
  if (!state.token) return toast("Sign in as admin first", "err");
  if (!confirm("Restart the orchestrator now? In-flight requests are dropped; it returns in ~30–60s.\n\nNote: .env changes need the recreate command, not a restart.")) return;
  _restarting = true;
  _restartBtns().forEach((b) => (b.disabled = true));
  setRestartStatus("warn", "restarting…");
  try { await api("/api/v1/admin/restart", { method: "POST" }); } catch (_) {}
  setTimeout(pollHealthUntilUp, 3000); // let it go down first
}
async function pollHealthUntilUp() {
  const started = Date.now();
  const done = () => { _restarting = false; _restartBtns().forEach((b) => (b.disabled = false)); };
  const tick = async () => {
    if (Date.now() - started > 150000) { setRestartStatus("bad", "timed out — check the container"); done(); return; }
    let healthy = false;
    try {
      const r = await fetch("/health", { cache: "no-store" });
      if (r.ok) { const b = await r.json().catch(() => ({})); const st = (b.data && b.data.status) || b.status; healthy = /healthy/i.test(String(st)); }
    } catch (_) {}
    if (healthy) {
      setRestartStatus("ok", "healthy ✓"); done(); toast("Orchestrator restarted", "ok");
      // auto-vanish the notice ~90s after it's healthy again
      clearTimeout(_noticeTimer); _noticeTimer = setTimeout(hideNotice, 90000);
      return;
    }
    setRestartStatus("warn", "restarting…");
    setTimeout(tick, 2500);
  };
  tick();
}

// ── Contextual apply notice (only appears after a change that needs action) ──
let _noticeTimer = null;
function showRecreateNotice(msg) {
  $("apply-notice-msg").textContent = msg;
  $("apply-notice").hidden = false;
  setRestartStatus(null, "");
  clearTimeout(_noticeTimer);
  _noticeTimer = setTimeout(hideNotice, 120000); // auto-vanish after 2 min if untouched
}
function hideNotice() { clearTimeout(_noticeTimer); $("apply-notice").hidden = true; }

function setAuthUI() {
  $("who").textContent = state.user ? `signed in · ${state.user}` : "read-only";
  $("login-btn").textContent = state.user ? "Sign out" : "Sign in";
}
const splitCsv = (s) => (s || "").split(",").map((x) => x.trim()).filter(Boolean);

// ── Tabs ─────────────────────────────────────────────────────────────────────
const TAB_META = {
  overview: ["Overview", "System state at a glance."],
  sources: ["Data Sources", "Toggle synthetic sources to unlock question-answering capabilities."],
  ask: ["Ask (test)", "Ask a question against the live pipeline — see the answer, provenance, and routing."],
  ai: ["AI & Models", "Choose the LLM provider/model and the embedding backend."],
  services: ["Services", "Open the attached tools — data browsers, graph, dashboards."],
  integrations: ["Integrations", "Live data feeds and notification channels."],
  settings: ["Settings (.env)", "Edit the backend environment. Secrets are masked; changes apply on restart."],
  databases: ["Databases", "Connections whose credentials are used per-question, routed by sensor UUID."],
  ontology: ["Ontology", "Add building capabilities as triples, upload TTL, and browse the knowledge graph."],
  users: ["Users & Access", "Manage accounts and control which data sources each role may query."],
  health: ["Health", "Live orchestrator status and feature state."],
  audit: ["Audit", "Recent mutating admin actions — who did what, when, and the outcome."],
  guide: ["Guide", "How to use this console."],
};
function switchTab(tab) {
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== "tab-" + tab));
  $("page-title").textContent = TAB_META[tab][0];
  $("page-sub").textContent = TAB_META[tab][1];
  if (tab === "overview") loadOverview();
  if (tab === "ask" && !$("ask-suggestions").innerHTML) renderAskSuggestions();
  if (tab === "ai") loadAiConfig();
  if (tab === "services") loadServices();
  if (tab === "integrations") loadIntegrations();
  if (tab === "settings") loadEnv();
  if (tab === "databases") loadDatabases();
  if (tab === "ontology") loadOntology();
  if (tab === "users") { loadUsers(); loadRoleAccess(); }
  if (tab === "health") loadHealth();
  if (tab === "audit") loadAudit();
}

// ── Data Sources tab ───────────────────────────────────────────────────────────
function prettify(t) { return t.replace(/_/g, " "); }
function sourceCard(s) {
  const canWrite = !!state.token;
  const unlocks = (s.unlocks || []).map((u) => `<li>${prettify(u)}</li>`).join("");
  const lastGen = s.last_generated_at ? new Date(s.last_generated_at).toLocaleString() : "never";
  const el = document.createElement("div");
  el.className = "card" + (s.enabled ? " enabled" : "");
  if (s.enabled) el.style.borderLeftColor = s.color;
  el.innerHTML = `
    <div class="card-head">
      <div><h3>${s.label}</h3><div class="modality">${s.modality} · ${s.kind === "text_reports" ? "text corpus" : "time-series"}</div></div>
      <label class="switch" title="${canWrite ? "Toggle" : "Sign in to toggle"}">
        <input type="checkbox" ${s.enabled ? "checked" : ""} ${canWrite ? "" : "disabled"} data-toggle="${s.id}" />
        <span class="track"></span>
      </label>
    </div>
    <div class="badges">
      <span class="chip" style="border-color:${s.color};color:${s.color}">${s.provenance_system}</span>
      ${s.synthetic ? '<span class="chip sim">simulated</span>' : ""}
      <span class="chip">${s.points} point${s.points === 1 ? "" : "s"}</span>
      ${s.row_count ? `<span class="chip">${Number(s.row_count).toLocaleString()} rows</span>` : ""}
      ${(s.match_keywords && s.match_keywords.length) ? '<span class="chip lock">locks when off</span>' : ""}
    </div>
    <details class="unlocks"><summary>Unlocks ${(s.unlocks || []).length} capabilit${(s.unlocks || []).length === 1 ? "y" : "ies"}</summary><ul>${unlocks || "<li>—</li>"}</ul></details>
    <div class="card-foot">
      <button class="btn small primary" data-details="${s.id}">ⓘ Capabilities &amp; questions</button>
      <button class="btn small ghost" data-preview="${s.id}" ${s.kind === "text_reports" ? "disabled" : ""}>Preview</button>
      <button class="btn small ghost" data-regen="${s.id}" ${canWrite && s.kind !== "text_reports" ? "" : "disabled"}>Regenerate</button>
    </div>
    <div class="meta">Last generated: ${lastGen}</div>`;
  return el;
}
function renderSources() {
  const box = $("cards"); box.innerHTML = "";
  state.sources.forEach((s) => box.appendChild(sourceCard(s)));
  loadProvenance();
  const legend = $("legend-list"); legend.innerHTML = "";
  state.sources.forEach((s) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="swatch" style="background:${s.color}"></span> ${s.provenance_system} ${s.synthetic ? '<span class="chip sim" style="margin-left:auto" title="This demo source is synthetic. The building may still have real sensors for this modality — see Live data provenance.">demo</span>' : ""}`;
    legend.appendChild(li);
  });
}
async function loadProvenance() {
  const box = $("prov-summary");
  if (!box) return;
  if (!state.token) { box.innerHTML = '<p class="hint">Sign in as admin to see the live split.</p>'; return; }
  try {
    const { body } = await api("/api/v1/admin/provenance");
    if (!body || !body.data) throw new Error(body?.error || "unavailable");
    const { backends, totals, building_nature: bn, building_note: bnote } = body.data;
    const pct = totals.total ? Math.round((totals.real / totals.total) * 100) : 0;
    // Building-level declaration first: a fixture building's ONTOLOGY and sensors are
    // invented too, which a per-source real/synthetic split cannot convey on its own.
    const NATURE_LABEL = {
      synthetic: ["sim", "Fully synthetic building"],
      mixed: ["real", "Real building · some generated sources"],
      real: ["real", "Real building"],
    };
    const nat = NATURE_LABEL[bn];
    const banner = nat
      ? `<div class="prov-building ${bn}">
           <span class="chip ${nat[0]}">${esc(bn)}</span>
           <div><b>${esc(nat[1])}</b>${bnote ? `<div class="hint">${esc(bnote)}</div>` : ""}</div>
         </div>`
      : "";
    const rows = backends.map((b) => `
      <li class="prov-row">
        <span class="chip ${b.nature === "real" ? "real" : "sim"}">${b.nature}</span>
        <span class="prov-key" title="${esc(b.note || "")}">${esc(b.key)}</span>
        <span class="prov-n">${b.sensors.toLocaleString()}</span>
      </li>`).join("");
    box.innerHTML = `
      ${banner}
      <div class="prov-bar" title="${totals.real} real / ${totals.total} total sensors">
        <span style="width:${pct}%"></span>
      </div>
      <p class="prov-tot"><b>${totals.real.toLocaleString()}</b> real ·
        <b>${totals.simulated.toLocaleString()}</b> simulated sensors (${pct}% real)</p>
      <ul class="prov-list">${rows}</ul>`;
  } catch (e) {
    box.innerHTML = `<p class="hint">${esc(e.message)}</p>`;
    if (e.rateLimited) setTimeout(loadProvenance, (e.retryAfter || 60) * 1000);
  }
}

async function loadSources() {
  try {
    const { body } = await api("/api/v1/datasources");
    const on = body?.data?.enabled;
    $("feature-pill").textContent = on ? "feature: on" : "feature: OFF";
    $("feature-pill").className = "pill " + (on ? "on" : "off");
    state.sources = body?.data?.sources || [];
    renderSources();
  } catch (e) { toast(e.message, "err"); }
}
async function toggle(id, checked) {
  const verb = checked ? "enable" : "disable";
  try {
    const { body } = await api(`/api/v1/datasources/${id}/${verb}`, { method: "POST" });
    toast(body.success ? `${id} ${verb}d` : (body.error || "failed"), body.success ? "ok" : "err");
  } catch (e) { toast(e.message, "err"); }
  loadSources();
}
async function regenerate(id) {
  toast(`Generating ${id}…`);
  try {
    const { body } = await api(`/api/v1/datasources/${id}/regenerate`, { method: "POST" });
    toast(body.success ? `${id}: ${body.data.rows} rows` : (body.error || body.data?.error || "failed"), body.success ? "ok" : "err");
  } catch (e) { toast(e.message, "err"); }
  loadSources();
}
async function enableAll() {
  if (!state.token) return toast("Sign in first", "err");
  const off = state.sources.filter((s) => !s.enabled);
  if (!off.length) return toast("All sources already enabled", "ok");
  if (!confirm(`Enable all ${off.length} disabled source(s)? Each writes Brick triples to GraphDB.`)) return;
  toast(`Enabling ${off.length} source(s)…`);
  for (const s of off) {
    try { await api(`/api/v1/datasources/${s.id}/enable`, { method: "POST" }); } catch (_) {}
  }
  toast("Enabled all sources", "ok");
  loadSources();
}
async function resetDemo() {
  if (!state.token) return toast("Sign in first", "err");
  if (!confirm("Reset to a clean slate? Disables every enabled source and flushes the response cache.")) return;
  try {
    const { body } = await api("/api/v1/datasources/reset-demo", { method: "POST" });
    toast(body.success ? `Reset — disabled ${body.data.count} source(s)` : (body.error || "failed"), body.success ? "ok" : "err");
  } catch (e) { toast(e.message, "err"); }
  loadSources();
}
async function preview(id) {
  try {
    const { body } = await api(`/api/v1/datasources/${id}/preview?limit=96`);
    const d = body.data || {};
    $("preview-title").textContent = `Preview · ${id}`;
    $("preview-body").innerHTML = `<div class="preview-stats"><span>${d.total_rows ?? 0} rows</span><span>${d.rows_per_point ?? 0}/point</span><span>table: ${d.ts_table ?? "—"}</span></div>${sparkline(d.sample || [])}`;
    open("preview-modal");
  } catch (e) { toast(e.message, "err"); }
}
function sparkline(sample) {
  if (!sample.length) return '<p class="hint">No sample — enable/regenerate first.</p>';
  const vals = sample.map((p) => p.v), min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const W = 600, H = 120, pad = 6;
  const pts = sample.map((p, i) => `${(pad + (i / (sample.length - 1)) * (W - 2 * pad)).toFixed(1)},${(H - pad - ((p.v - min) / span) * (H - 2 * pad)).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><polyline fill="none" stroke="#5b8cff" stroke-width="2" points="${pts}" /></svg>`;
}

// ── Capabilities & example questions (Details modal) ─────────────────────────
let capCatalog = null;
async function loadCatalog() {
  if (capCatalog) return capCatalog;
  try { const r = await fetch("capabilities.json", { cache: "no-store" }); capCatalog = await r.json(); }
  catch (_) { capCatalog = {}; }
  return capCatalog;
}
function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }
// Short label for an embedding model URI/name, e.g. "BAAI/bge-large-en-v1.5" -> "bge-large-en-v1.5".
const embModelShort = (m) => { const s = String(m || "").split("/").pop().trim(); return s || "local model"; };
const embName = (d) => (d.embedding_provider === "openai" ? "OpenAI" : (d.embedding_model_local ? embModelShort(d.embedding_model_local) : "Local"));
const embDim = (d) => (d.embedding_provider === "openai" ? d.embedding_dimension_openai : d.embedding_dimension_local);

// ── Theme (light / dark) ─────────────────────────────────────────────────────
// Default follows the OS (prefers-color-scheme); an explicit choice is stored in
// localStorage and wins in both directions via <html data-theme>.
function effectiveTheme() {
  const set = document.documentElement.getAttribute("data-theme");
  if (set === "light" || set === "dark") return set;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}
function syncThemeBtn() {
  const b = document.getElementById("theme-btn");
  if (b) b.textContent = effectiveTheme() === "light" ? "☾ Dark" : "☀ Light";
}
function applyTheme(t) {
  if (t !== "light" && t !== "dark") return;
  document.documentElement.setAttribute("data-theme", t);
  try { localStorage.setItem("cp-theme", t); } catch (_) {}
  syncThemeBtn();
}
function toggleTheme() { applyTheme(effectiveTheme() === "light" ? "dark" : "light"); }
(function initTheme() {
  let s = null;
  try { s = localStorage.getItem("cp-theme"); } catch (_) {}
  if (s === "light" || s === "dark") document.documentElement.setAttribute("data-theme", s);
  syncThemeBtn();
})();
async function showDetails(sourceId) {
  const s = state.sources.find((x) => x.id === sourceId);
  if (!s) return;
  const cat = await loadCatalog();
  const c = cat[s.modality] || null;
  $("details-title").innerHTML = `${esc(c ? c.title : s.label)} <span class="chip" style="border-color:${s.color};color:${s.color}">${esc(s.provenance_system)}</span> ${s.synthetic ? '<span class="chip sim">simulated</span>' : ""}`;
  $("details-summary").textContent = c ? c.summary : "";
  const state_txt = s.enabled ? '<span class="dot ok"></span>enabled' : '<span class="dot warn"></span>disabled';
  const unlockTags = (s.unlocks || []).map((u) => `<span class="ulock">${esc(u.replace(/_/g, " "))}</span>`).join("");
  $("details-unlocks").innerHTML = `<div class="det-state">${state_txt} · ${s.points} point${s.points === 1 ? "" : "s"} · gates: <b>${(s.match_keywords || []).length ? "yes" : "no"}</b></div>
    <div class="ulocks">${unlockTags || '<span class="hint">—</span>'}</div>`;
  if (!c || !c.groups) {
    $("details-groups").innerHTML = '<p class="hint">No extended capability catalogue for this modality yet — the tags above show what it unlocks. (Add an entry keyed by the source modality in <code>capabilities.json</code>.)</p>';
  } else {
    $("details-groups").innerHTML = c.groups.map((g) => `
      <div class="det-group">
        <h4>${esc(g.stakeholder)}</h4>
        <div class="det-cols">
          <div class="det-caps"><div class="det-lbl">Capabilities unlocked</div><ul>${(g.capabilities || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
          <div class="det-qs"><div class="det-lbl">Example questions</div><ul>${(g.questions || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
        </div>
      </div>`).join("");
  }
  open("details-modal");
}

// ── Add source ─────────────────────────────────────────────────────────────────
function addPointRow(p = {}) {
  const row = document.createElement("div");
  row.className = "point-row";
  row.innerHTML = `
    <input placeholder="local" value="${p.local || ""}" data-f="local" />
    <input placeholder="brick:Class" value="${p.brick_class || ""}" data-f="brick_class" />
    <input placeholder="bldg:Location" value="${p.location || ""}" data-f="location" />
    <input placeholder="unit:X" value="${p.unit || ""}" data-f="unit" />
    <button class="rm">✕</button>`;
  row.querySelector(".rm").addEventListener("click", () => row.remove());
  $("points").appendChild(row);
}
function collectPoints() {
  return [...document.querySelectorAll("#points .point-row")].map((row) => {
    const pt = {};
    row.querySelectorAll("input").forEach((i) => { if (i.value.trim()) pt[i.dataset.f] = i.value.trim(); });
    return pt;
  }).filter((pt) => pt.local);
}
async function createSource() {
  const kind = $("f-kind").value;
  const spec = {
    id: $("f-id").value.trim(), label: $("f-label").value.trim(),
    modality: $("f-modality").value.trim() || "custom", kind,
    provenance_system: $("f-prov").value.trim() || $("f-label").value.trim(),
    color: $("f-color").value, unlocks: splitCsv($("f-unlocks").value),
    match_keywords: splitCsv($("f-keywords").value).map((k) => k.toLowerCase()),
  };
  if (kind === "timeseries") {
    spec.ts_table = $("f-table").value.trim(); spec.points = collectPoints();
    spec.generator = { kind: $("f-gen").value, window_days: +$("f-window").value || 30, interval_minutes: +$("f-interval").value || 15, params: {} };
  }
  if (!spec.id || !spec.label) { return err("add-err", "ID and Label are required."); }
  try {
    const { body } = await api("/api/v1/datasources", { method: "POST", body: JSON.stringify(spec) });
    if (body.success) { closeModals(); toast(`Created ${spec.id}`, "ok"); loadSources(); }
    else err("add-err", body.error || body.data?.error || "Create failed");
  } catch (e) { err("add-err", e.message); }
}

// ── Settings (.env) tab ──────────────────────────────────────────────────────
let envRows = [];
async function loadEnv() {
  if (!state.token) { $("env-table").innerHTML = '<p class="hint">Sign in as admin to view .env.</p>'; return; }
  try {
    const { body } = await api("/api/v1/admin/env");
    state.mask = body.data.mask || "********";
    $("mask-hint").textContent = state.mask;
    envRows = body.data.env || [];
    renderEnv();
  } catch (e) { $("env-table").innerHTML = `<p class="err">${e.message}</p>`; }
}
function renderEnv() {
  const filter = ($("env-filter").value || "").toLowerCase();
  const box = $("env-table"); box.innerHTML = "";
  envRows.filter((r) => r.key.toLowerCase().includes(filter)).forEach((r) => {
    const row = document.createElement("div");
    row.className = "env-row";
    row.innerHTML = `<div class="k">${r.key}</div>
      <input value="${(r.value ?? "").replace(/"/g, "&quot;")}" data-k="${r.key}" ${r.is_secret ? 'type="password"' : ""} />
      <div class="tag">${r.is_secret ? "secret" : ""}</div>`;
    const inp = row.querySelector("input");
    inp.addEventListener("input", () => inp.classList.add("dirty"));
    box.appendChild(row);
  });
}
async function saveEnv() {
  const changes = {};
  document.querySelectorAll("#env-table input.dirty").forEach((i) => (changes[i.dataset.k] = i.value));
  if (!Object.keys(changes).length) return toast("No changes", "ok");
  try {
    const { body } = await api("/api/v1/admin/env", { method: "PUT", body: JSON.stringify({ changes }) });
    if (body.success) { toast(`Saved ${body.data.updated.length + body.data.added.length} key(s)`, "ok"); showRecreateNotice(".env saved — a recreate is needed to apply it (env is read only at container start)."); loadEnv(); }
    else toast(body.error || "save failed", "err");
  } catch (e) { toast(e.message, "err"); }
}
// ── Config backup / restore ──────────────────────────────────────────────────
async function downloadBackup() {
  if (!state.token) return toast("Sign in as admin first", "err");
  try {
    const { body } = await api("/api/v1/admin/config/backup");
    if (!body.success) return toast(body.error || "backup failed", "err");
    const blob = new Blob([JSON.stringify(body.data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    a.href = url; a.download = `ontosage-config-backup-${ts}.json`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    toast("Backup downloaded", "ok");
  } catch (e) { toast(e.message, "err"); }
}
async function restoreBackupFile(file) {
  if (!file) return;
  const st = $("restore-status");
  st.innerHTML = `<span class="dot warn"></span>reading…`;
  let bundle;
  try { bundle = JSON.parse(await file.text()); }
  catch (_) { st.innerHTML = `<span class="dot bad"></span>not valid JSON`; return; }
  if (!confirm("Restore this config bundle? It overwrites the current console-managed config files.")) {
    st.innerHTML = ""; return;
  }
  try {
    const { body } = await api("/api/v1/admin/config/restore", { method: "POST", body: JSON.stringify({ bundle }) });
    if (body.success) {
      const r = body.data.restored || [];
      st.innerHTML = `<span class="dot ok"></span>restored ${r.length} file(s)`;
      toast(`Restored: ${r.join(", ") || "nothing"}`, "ok");
      showRecreateNotice("Config restored — recreate the orchestrator to reload registries.");
    } else {
      st.innerHTML = `<span class="dot bad"></span>${esc((body.error || "failed")).slice(0, 90)}`;
      toast(body.error || "restore failed", "err");
    }
  } catch (e) { st.innerHTML = `<span class="dot bad"></span>${esc(e.message)}`; }
  finally { $("restore-file").value = ""; }
}
async function addEnvRow() {
  const key = $("new-env-key").value.trim(), val = $("new-env-val").value;
  if (!key) return toast("Key required", "err");
  try {
    const { body } = await api("/api/v1/admin/env", { method: "PUT", body: JSON.stringify({ changes: { [key]: val } }) });
    if (body.success) { $("new-env-key").value = ""; $("new-env-val").value = ""; toast(`Added ${key}`, "ok"); showRecreateNotice(`Added ${key} to .env — a recreate is needed to apply it.`); loadEnv(); }
    else toast(body.error || "failed", "err");
  } catch (e) { toast(e.message, "err"); }
}

// ── Databases tab ──────────────────────────────────────────────────────────────
let dbCache = [];
let dbActiveOnly = false;
let dbAnswerability = {}; // key -> {declared, with_data, level}; cached so filter toggles don't re-probe
let answerabilityData = null; // full batch result (counts + building-wide totals) for the coverage badge
async function loadDatabases() {
  if (!state.token) { $("db-list").innerHTML = '<p class="hint">Sign in as admin to view connections.</p>'; return; }
  try {
    const { body } = await api("/api/v1/admin/databases");
    dbCache = body.data.databases || [];
    renderDbCards();
    loadAnswerability(); // fill the ✓/◐/✗ per-card coverage (one batch request, active DBs only)
  } catch (e) { $("db-list").innerHTML = `<p class="err">${e.message}</p>`; }
}
// One batch request → answerability for every active datasource; cached + applied to the cards
// and the Ontology coverage badge.
async function loadAnswerability() {
  try {
    const { body } = await api("/api/v1/admin/databases/answerability");
    answerabilityData = body.data || {};
    dbAnswerability = answerabilityData.counts || {};
    applyAnswerability();
    renderOntoCoverage(answerabilityData);
  } catch (_) { /* non-fatal — cards just show no coverage badge */ }
}
function applyAnswerability() {
  Object.entries(dbAnswerability).forEach(([k, a]) => {
    if (a) setStatus(`verify-${k}`, a.level || "warn", answerabilityLabel(a));
  });
}
// "8/10 answerable · 3 live" — coverage and freshness in one line (CAVEAT-233). `reporting`
// is null when the freshness probe could not run against that datasource, and an unmeasured
// store must not be labelled "0 live": that would make a broken connection look like a
// building whose sensors went quiet, and those need different fixes.
function answerabilityLabel(a) {
  const base = `${a.with_data}/${a.declared} answerable`;
  return (a.reporting === null || a.reporting === undefined) ? base : `${base} · ${a.reporting} live`;
}
// Building-wide declared-vs-populated coverage on the Ontology tab: declaring sensors as
// triples isn't enough — their datasource must actually hold the data.
function renderOntoCoverage(data) {
  const el = $("onto-coverage");
  if (!el) return;
  const dec = data?.total_declared || 0, wd = data?.total_with_data || 0, ds = data?.datasources || 0;
  if (!dec) { el.hidden = true; return; }
  const level = wd === dec ? "ok" : wd === 0 ? "bad" : "warn";
  el.hidden = false;
  // CAVEAT-233: "answerable" means rows EXIST, which is what a historical question needs.
  // Shown alone next to a green dot it reads as "the building is live", and it is routinely
  // not: bldg1 had every declared sensor answerable while ~7% were still streaming. The
  // freshness number is stated beside it, and deliberately does NOT change the dot —
  // an archived snapshot answers historical questions correctly.
  const rep = data?.total_reporting, win = data?.reporting_window_h || 24;
  const fresh = (rep === null || rep === undefined)
    ? ""
    : (rep === 0
        ? ` <b>None</b> of those reported in the last ${win} h — the building answers historical questions only.`
        : ` <b>${rep}</b> of those reported in the last ${win} h${rep < wd ? "; the rest answer historical questions only." : "."}`);
  el.innerHTML = `<span class="dot ${level}"></span><b>Sensor data coverage:</b> ${wd} of ${dec} datasource-linked sensor(s) are answerable (their UUIDs have data) across ${ds} active datasource(s).${fresh} Declaring a sensor as a triple isn't enough — its datasource must hold the readings; use a datasource's <b>Verify</b> to see which are missing data.`;
}
function renderDbCards() {
  const shown = dbActiveOnly ? dbCache.filter((d) => d.active) : dbCache;
  const nActive = dbCache.filter((d) => d.active).length;
  if ($("db-counts")) $("db-counts").textContent = `${nActive} active · ${dbCache.length - nActive} dormant`;
  $("db-list").innerHTML = shown.map((d) => {
    const rows = Object.entries(d.fields || {}).map(([k, v]) => `<div class="kv"><span>${k}</span><span>${v}</span></div>`).join("");
    const table = (d.fields || {}).table;
    const actBadge = d.active
      ? '<span class="src-badge act" title="Initialized by this building (building.yaml storage.databases)">active</span>'
      : '<span class="src-badge dormant" title="Template — not initialized. Add its key to building.yaml storage.databases to activate.">dormant</span>';
    // Real vs synthetic DATA SOURCE, declared per connection in the ACTIVE building's
    // database_registry.yaml (`nature:` + `note:`). The console must not assert which
    // source is real — that differs per building, and hardcoding one building's answer
    // mislabels every other one.
    const natBadge = d.nature === "real"
      ? `<span class="src-badge real" title="${esc(d.note || "Real measured data source")}">real</span>`
      : `<span class="src-badge sim" title="${esc(d.note || "Generated demo data source")}">synthetic</span>`;
    return `<div class="db-card${d.active ? "" : " is-dormant"}">
      <h4>${d.key} <span class="src-badge ${d.source}">${d.source}</span> ${natBadge} ${actBadge}</h4>
      <div class="kv"><span>type</span><span>${d.type}</span></div>${rows}
      <div class="db-status"><span class="count" data-count-for="${d.key}">sensors: …</span><span class="probe" id="probe-${d.key}"></span><span class="probe" id="verify-${d.key}"></span></div>
      <div class="db-actions">
        <button class="btn ghost small" data-test-db="${d.key}">Test</button>
        ${table ? `<button class="btn ghost small" data-data-db="${d.key}" data-table="${table}">Data</button>` : ""}
        <button class="btn ghost small" data-sensors="${d.key}">Register sensors</button>
        <button class="btn ghost small" data-verify-db="${d.key}" title="Check this datasource is actually answerable: declared sensors (ref:storedAt) whose UUIDs have data">Verify</button>
        ${d.source === "custom" ? `<button class="btn small danger" data-del-db="${d.key}">Delete</button>` : ""}
      </div>
    </div>`;
  }).join("") || '<p class="hint">No connections match the filter.</p>';
  // sensor triple counts — ONE batch request for all cards (a per-card probe used
  // to fire N requests and trip the rate limiter when many DBs were registered).
  (async () => {
    let counts = {};
    try {
      const { body } = await api("/api/v1/admin/databases/sensor-counts");
      counts = body.data?.counts || {};
    } catch (_) {}
    shown.forEach((d) => {
      const el = document.querySelector(`[data-count-for="${d.key}"]`);
      if (el) el.textContent = `sensors: ${counts[d.key] ?? 0} triples`;
    });
  })();
  applyAnswerability(); // re-apply cached ✓/◐/✗ (a filter toggle rebuilds the cards)
}
// Verify a datasource is actually answerable end-to-end: are its sensors DECLARED in the
// ontology (ref:storedAt), and do those UUIDs have real data? Shows a persistent ✓/◐/✗
// verdict on the card and a toast with detail.
async function verifyDatasource(key) {
  setStatus(`verify-${key}`, "warn", "verifying…");
  try {
    const { body } = await api(`/api/v1/admin/databases/${encodeURIComponent(key)}/answerability`);
    if (!body.success) {
      setStatus(`verify-${key}`, "bad", "unreachable");
      return toast(body.error || "verify failed", "err");
    }
    const d = body.data || {};
    const dot = d.level === "ok" ? "ok" : d.level === "bad" ? "bad" : "warn";
    setStatus(`verify-${key}`, dot, answerabilityLabel(d));
    dbAnswerability[key] = { declared: d.declared, with_data: d.with_data, level: d.level, reporting: d.reporting }; // persist across re-renders
    toast(d.verdict || "checked", d.level === "ok" ? "ok" : d.level === "bad" ? "err" : "");
  } catch (e) {
    setStatus(`verify-${key}`, "bad", "error");
    toast(e.message, "err");
  }
}
async function testDatabase(key) {
  const el = document.getElementById(`probe-${key}`);
  if (el) el.innerHTML = `<span class="dot warn"></span>testing…`;
  try {
    const { body } = await api("/api/v1/admin/databases/test", { method: "POST", body: JSON.stringify({ key }) });
    if (el) el.innerHTML = body.success
      ? `<span class="dot ok"></span>ok · ${body.data.latency_ms ?? "?"}ms`
      : `<span class="dot bad"></span>${(body.error || "failed").slice(0, 70)}`;
  } catch (e) { if (el) el.innerHTML = `<span class="dot bad"></span>${e.message}`; }
}
async function deleteDatabaseConn(key) {
  if (!confirm(`Delete connection "${key}"?\nIts sensor graph is cleared; its .env credentials are left (harmless). Recreate to fully drop it.`)) return;
  try {
    const { body } = await api(`/api/v1/admin/databases/${encodeURIComponent(key)}`, { method: "DELETE" });
    if (body.success) { toast(`Deleted ${key}`, "ok"); loadDatabases(); }
    else toast(body.error || "failed", "err");
  } catch (e) { toast(e.message, "err"); }
}
async function showDataPreview(key, table) {
  try {
    const { body } = await api(`/api/v1/admin/databases/${encodeURIComponent(key)}/data?table=${encodeURIComponent(table)}`);
    if (!body.success) return toast(body.error || "failed", "err");
    const d = body.data;
    const rows = (d.sample || []).map((r) => `<div class="kv"><span>${r.datetime}</span><span>${r.value} <em style="color:var(--muted)">${(r.uuid || "").slice(0, 8)}…</em></span></div>`).join("");
    $("preview-title").textContent = `${key} · ${table}`;
    $("preview-body").innerHTML = `<div class="preview-stats"><span>${d.rows ?? 0} rows</span><span>${d.sensors ?? "?"} sensors</span></div>${rows || '<p class="hint">no rows</p>'}`;
    open("preview-modal");
  } catch (e) { toast(e.message, "err"); }
}
async function testNewConnection() {
  const spec = {
    type: $("db-type").value, host: $("db-host").value.trim(), port: $("db-port").value.trim() || "3306",
    user: $("db-user").value.trim(), password: $("db-pass").value, database: $("db-name").value.trim(),
  };
  if (!spec.host) return err("db-err", "Enter a host to test.");
  $("db-err").hidden = true;
  const s = $("db-test-status"); s.innerHTML = `<span class="dot warn"></span>testing…`;
  try {
    const { body } = await api("/api/v1/admin/databases/test", { method: "POST", body: JSON.stringify(spec) });
    s.innerHTML = body.success
      ? `<span class="dot ok"></span>connected · ${body.data.latency_ms ?? "?"}ms`
      : `<span class="dot bad"></span>${(body.error || "failed").slice(0, 90)}`;
  } catch (e) { s.innerHTML = `<span class="dot bad"></span>${e.message}`; }
}

let sensorsDbKey = null;
function addSensorPointRow(p = {}, containerId = "sensor-points") {
  const row = document.createElement("div");
  row.className = "point-row";
  row.innerHTML = `
    <input placeholder="local name" value="${p.local || ""}" data-f="local" />
    <input placeholder="brick:Class" list="dl-classes" autocomplete="off" value="${p.brick_class || ""}" data-f="brick_class" />
    <input placeholder="bldg:Location" list="dl-locations" autocomplete="off" value="${p.location || ""}" data-f="location" />
    <input placeholder="UUID (from DB)" list="dl-uuids" autocomplete="off" value="${p.uuid || ""}" data-f="uuid" />
    <input placeholder="unit:X" value="${p.unit || ""}" data-f="unit" />
    <button class="rm">✕</button>`;
  row.querySelector(".rm").addEventListener("click", () => row.remove());
  $(containerId).appendChild(row);
}
function openSensors(dbKey) {
  sensorsDbKey = dbKey;
  $("sensors-dbkey").textContent = dbKey;
  $("sensors-key2").textContent = dbKey;
  $("sensors-err").hidden = true;
  $("sensor-points").innerHTML = "";
  addSensorPointRow();
  $("ttl-text").value = "";
  if ($("csv-text")) $("csv-text").value = "";
  // For the demo connection, prefill the CSV mode with the seeded sensors so the
  // "register sensors" half is one click (UUIDs match demo_readings).
  if (dbKey === "demo_external" && demoSensorsCsv && $("csv-text")) {
    $("csv-text").value = demoSensorsCsv;
    setSensorMode("csv");
  } else {
    setSensorMode("points");
  }
  open("sensors-modal");
  fillSensorSuggestions(dbKey);
}
// Populate the guided-form suggestions: Brick classes + locations from the graph, and the
// REAL UUIDs already present in this datasource — so an admin selects instead of typing.
// Non-fatal; free-text entry still works if a lookup is unavailable.
async function fillSensorSuggestions(dbKey) {
  const setOpts = (id, vals) => {
    const el = $(id);
    if (el) el.innerHTML = (vals || []).map((v) => `<option value="${esc(v)}"></option>`).join("");
  };
  try {
    const { body } = await api("/api/v1/admin/onboarding/vocab");
    setOpts("dl-classes", (body.data?.sensor_classes || []).map((c) => "brick:" + c));
    setOpts("dl-locations", (body.data?.locations || []).map((l) => "bldg:" + l));
  } catch (_) { /* graph vocab unavailable — free-text still works */ }
  try {
    const { body } = await api(`/api/v1/admin/databases/${encodeURIComponent(dbKey)}/uuids`);
    setOpts("dl-uuids", body.data?.uuids || []);
  } catch (_) { /* datasource unreachable — free-text still works */ }
}

// ── Guided "Connect a data source" wizard ───────────────────────────────────────
// One self-contained flow: pick/add a connection → describe its sensors as triples →
// verify OntoSage can answer. Reuses the same endpoints + datalists as the tabs; kept in
// a single modal so cancelling a step never tears down the whole flow.
let wizKey = null; // the datasource being onboarded this run
let wizIsNew = false; // true when a brand-new connection was created this run
let wizHotApplied = false; // true when the new connection was hot-applied (no restart needed)
function openConnectWizard() {
  if (!state.token) return toast("Sign in as admin first", "err");
  wizKey = null;
  wizIsNew = false;
  wizHotApplied = false;
  const keys = (dbCache || []).map((d) => d.key);
  $("wiz-key").innerHTML = keys.map((k) => `<option>${esc(k)}</option>`).join("");
  $("wiz-existing-empty").hidden = keys.length > 0;
  const startMode = keys.length ? "existing" : "new";
  const radio = document.querySelector(`input[name="wiz-src"][value="${startMode}"]`);
  if (radio) radio.checked = true;
  wizSyncSrc();
  ["wiz-err-1", "wiz-err-2"].forEach((id) => { const e = $(id); if (e) e.hidden = true; });
  wizGoto(1);
  open("wiz-modal");
}
function wizSyncSrc() {
  const mode = (document.querySelector('input[name="wiz-src"]:checked') || {}).value || "existing";
  $("wiz-existing").hidden = mode !== "existing";
  $("wiz-new").hidden = mode !== "new";
}
function wizGoto(step) {
  [1, 2, 3].forEach((n) => { $(`wiz-p${n}`).hidden = n !== step; });
  document.querySelectorAll("#wiz-modal .wiz-steps li").forEach((li) => {
    const n = Number(li.dataset.wstep);
    li.classList.toggle("active", n === step);
    li.classList.toggle("done", n < step);
  });
}
async function wizStep1Next() {
  const mode = (document.querySelector('input[name="wiz-src"]:checked') || {}).value || "existing";
  if (mode === "existing") {
    wizKey = $("wiz-key").value;
    wizIsNew = false;
    if (!wizKey) return err("wiz-err-1", "Pick a connection or add a new one.");
  } else {
    const spec = {
      key: $("wiz-nkey").value.trim(), type: $("wiz-ntype").value, host: $("wiz-nhost").value.trim(),
      port: $("wiz-nport").value.trim() || "3306", user: $("wiz-nuser").value.trim(),
      password: $("wiz-npass").value, database: $("wiz-ndb").value.trim(),
      table: $("wiz-ntable").value.trim(),
    };
    if (!spec.key || !spec.host) return err("wiz-err-1", "Key and Host are required.");
    if (spec.type === "mysql_narrow" && !spec.table) return err("wiz-err-1", "mysql_narrow needs a Narrow table.");
    try {
      const { body } = await api("/api/v1/admin/databases", { method: "POST", body: JSON.stringify(spec) });
      if (!body.success) return err("wiz-err-1", body.error || "failed");
      wizKey = spec.key;
      wizIsNew = true;
      wizHotApplied = !!(body.data && body.data.hot_applied); // false → reload failed, restart needed
      loadDatabases();
    } catch (e) { return err("wiz-err-1", e.message); }
  }
  $("wiz-key2").textContent = wizKey;
  $("wiz-key3").textContent = wizKey;
  $("wiz-points").innerHTML = "";
  addSensorPointRow({}, "wiz-points");
  if ($("wiz-csv-text")) $("wiz-csv-text").value = "";
  fillSensorSuggestions(wizKey);
  wizGoto(2);
}
async function wizStep2Next() {
  const base = `/api/v1/admin/databases/${encodeURIComponent(wizKey)}`;
  const csv = ($("wiz-csv-text").value || "").trim();
  try {
    let resp;
    if (csv) {
      resp = await api(`${base}/sensors/csv`, { method: "POST", body: JSON.stringify({ csv }) });
    } else {
      const points = [...document.querySelectorAll("#wiz-points .point-row")].map((row) => {
        const pt = {};
        row.querySelectorAll("input").forEach((i) => { if (i.value.trim()) pt[i.dataset.f] = i.value.trim(); });
        return pt;
      }).filter((pt) => pt.local);
      if (!points.length) return err("wiz-err-2", "Add at least one sensor (local name required), or paste CSV.");
      resp = await api(`${base}/sensors`, { method: "POST", body: JSON.stringify({ points }) });
    }
    const body = resp.body;
    if (!body.success) return err("wiz-err-2", body.error || "failed");
    if ((body.data?.warnings || []).length) toast(body.data.warnings[0], "err");
    loadDatabases();
    wizGoto(3);
    wizVerify();
  } catch (e) { err("wiz-err-2", e.message); }
}
async function wizVerify() {
  const v = $("wiz-verdict");
  v.className = "wiz-verdict";
  v.textContent = "Checking…";
  $("wiz-restart").hidden = true;
  try {
    const { body } = await api(`/api/v1/admin/databases/${encodeURIComponent(wizKey)}/answerability`);
    if (!body.success) {
      v.classList.add("bad");
      v.textContent = body.error || "Could not verify.";
      if (wizIsNew && !wizHotApplied) $("wiz-restart").hidden = false;
      return;
    }
    const d = body.data || {};
    v.classList.add(d.level === "ok" ? "ok" : d.level === "bad" ? "bad" : "warn");
    v.innerHTML = `<b>${esc(d.verdict || "checked")}</b>` +
      `<div class="hint">${d.with_data}/${d.declared} declared sensors return data` +
      ((d.reporting === null || d.reporting === undefined)
        ? "."
        : `; ${d.reporting} reported in the last ${d.reporting_window_h || 24} h.`) +
      `</div>`;
    dbAnswerability[wizKey] = { declared: d.declared, with_data: d.with_data, level: d.level, reporting: d.reporting };
    // Only surface the restart shortcut if the hot-reload actually failed; a hot-applied
    // connection with no data is a data/UUID problem a restart won't fix.
    if (wizIsNew && !wizHotApplied && (d.with_data || 0) === 0) $("wiz-restart").hidden = false;
  } catch (e) {
    v.classList.add("bad");
    v.textContent = e.message;
    if (wizIsNew && !wizHotApplied) $("wiz-restart").hidden = false;
  }
}

// ── "Load demo database" — prefill a connection to the profile-gated demo-mysql ─
let demoSensorsCsv = null;
async function loadDemoDatabase() {
  if (!state.token) return toast("Sign in as admin first", "err");
  try {
    const { body } = await api("/api/v1/admin/databases/demo-template");
    if (!body.success) return toast(body.error || "failed", "err");
    const c = body.data.connection || {};
    demoSensorsCsv = body.data.sensors_csv || null;
    $("db-key").value = c.key || "";
    $("db-type").value = c.type || "mysql_narrow";
    $("db-host").value = c.host || "";
    $("db-port").value = c.port || "3306";
    $("db-user").value = c.user || "";
    $("db-pass").value = c.password || "";
    $("db-name").value = c.database || "";
    if ($("db-table")) $("db-table").value = c.table || "";
    $("db-err").hidden = true;
    $("db-test-status").innerHTML = "";
    open("db-modal");
    toast("Prefilled demo connection — Test → Add → Register sensors → recreate", "ok");
  } catch (e) { toast(e.message, "err"); }
}
function setSensorMode(mode) {
  document.querySelectorAll(".mode-tab").forEach((t) => t.classList.toggle("active", t.dataset.mode === mode));
  $("mode-points").hidden = mode !== "points";
  $("mode-ttl").hidden = mode !== "ttl";
  if ($("mode-csv")) $("mode-csv").hidden = mode !== "csv";
}
async function submitSensors() {
  const ttlMode = !$("mode-ttl").hidden;
  const csvMode = $("mode-csv") && !$("mode-csv").hidden;
  const base = `/api/v1/admin/databases/${encodeURIComponent(sensorsDbKey)}`;
  try {
    let resp;
    if (csvMode) {
      const csv = $("csv-text").value.trim();
      if (!csv) return err("sensors-err", "Paste CSV rows.");
      resp = await api(`${base}/sensors/csv`, { method: "POST", body: JSON.stringify({ csv }) });
    } else if (ttlMode) {
      const ttl = $("ttl-text").value.trim();
      if (!ttl) return err("sensors-err", "Paste a TTL document.");
      resp = await api(`${base}/sensors/ttl`, { method: "POST", body: JSON.stringify({ ttl }) });
    } else {
      const points = [...document.querySelectorAll("#sensor-points .point-row")].map((row) => {
        const pt = {};
        row.querySelectorAll("input").forEach((i) => { if (i.value.trim()) pt[i.dataset.f] = i.value.trim(); });
        return pt;
      }).filter((pt) => pt.local);
      if (!points.length) return err("sensors-err", "Add at least one point.");
      resp = await api(`${base}/sensors`, { method: "POST", body: JSON.stringify({ points }) });
    }
    const body = resp.body;
    if (body.success) {
      closeModals();
      toast(`Registered sensors for ${sensorsDbKey}`, "ok");
      if ((body.data?.warnings || []).length) toast(body.data.warnings[0], "err");
      loadDatabases();
    } else err("sensors-err", body.error || "failed");
  } catch (e) { err("sensors-err", e.message); }
}
async function createDatabase() {
  const spec = {
    key: $("db-key").value.trim(), type: $("db-type").value, host: $("db-host").value.trim(),
    port: $("db-port").value.trim() || "3306", user: $("db-user").value.trim(),
    password: $("db-pass").value, database: $("db-name").value.trim(),
    table: $("db-table") ? $("db-table").value.trim() : "",
  };
  if (!spec.key || !spec.host) return err("db-err", "Key and Host are required.");
  if (spec.type === "mysql_narrow" && !spec.table) return err("db-err", "mysql_narrow needs a Narrow table.");
  try {
    const { body } = await api("/api/v1/admin/databases", { method: "POST", body: JSON.stringify(spec) });
    if (body.success) {
      closeModals();
      toast(`Added ${spec.key}`, "ok");
      // Add now hot-applies (adapter pool reloaded live). Only fall back to the
      // recreate prompt if the server reported the hot-apply failed.
      if (body.data && body.data.hot_applied === false) {
        showRecreateNotice(`Connection '${spec.key}' added but not applied live — recreate to load its credentials, then register its sensors.`);
      } else {
        toast(`'${spec.key}' is live — register its sensors to make it answerable`, "ok");
      }
      loadDatabases();
    }
    else err("db-err", body.error || "failed");
  } catch (e) { err("db-err", e.message); }
}

// ── Users & Access tab ──────────────────────────────────────────────────────
let allRoles = [];
async function loadUsers() {
  if (!state.token) { $("users-list").innerHTML = '<p class="hint">Sign in as admin to manage users.</p>'; return; }
  try {
    const { body } = await api("/api/v1/admin/users");
    if (!body || !body.data) throw new Error(body?.error || "No data returned by the server.");
    allRoles = body.data.roles || [];
    const opts = (sel) => allRoles.map((r) => `<option ${r === sel ? "selected" : ""}>${r}</option>`).join("");
    $("users-list").innerHTML = (body.data.users || []).map((u) => `
      <div class="user-row">
        <div><div class="uname">${u.username}</div><div class="uemail">${u.email || ""}</div></div>
        <select data-role-for="${u.username}">${opts(u.role)}</select>
        <button class="btn ghost small" data-pw-for="${esc(u.username)}">Password</button>
        <button class="del" data-del-user="${u.username}">Delete</button>
      </div>`).join("") || '<p class="hint">No users.</p>';
  } catch (e) {
    $("users-list").innerHTML = `<p class="err">${esc(e.message)}</p>`;
    if (e.rateLimited) setTimeout(loadUsers, (e.retryAfter || 60) * 1000);
  }
}
async function changeRole(username, role) {
  try {
    const { body } = await api(`/api/v1/admin/users/${encodeURIComponent(username)}/role`, { method: "PUT", body: JSON.stringify({ role }) });
    toast(body.success ? `${username} → ${role}` : (body.error || "failed"), body.success ? "ok" : "err");
  } catch (e) { toast(e.message, "err"); }
}
async function deleteUser(username) {
  if (!confirm(`Delete user "${username}"?`)) return;
  try {
    const { body } = await api(`/api/v1/admin/users/${encodeURIComponent(username)}`, { method: "DELETE" });
    toast(body.success ? `deleted ${username}` : (body.error || "failed"), body.success ? "ok" : "err");
    loadUsers();
  } catch (e) { toast(e.message, "err"); }
}
// ── Passwords ────────────────────────────────────────────────────────────────
// Reveal toggle: an admin typing a password into a masked field has no way to
// confirm what they entered, which is how mistyped credentials get created.
// Standard eye / eye-off glyphs (inline SVG — no icon font or external asset, so the
// console keeps working with no network and nothing to version).
const PW_ICON = {
  show: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
  hide: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20C5 20 1 12 1 12a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>',
};

// Render the eye icon into every password toggle (and keep them masked to start).
function initPasswordToggles(root) {
  (root || document).querySelectorAll("[data-pw-toggle]").forEach((b) => {
    b.innerHTML = PW_ICON.show;
    b.setAttribute("aria-label", "Show password");
  });
}

function setPasswordIcon(btn, revealed) {
  if (!btn) return;
  btn.innerHTML = revealed ? PW_ICON.hide : PW_ICON.show;
  btn.setAttribute("aria-label", revealed ? "Hide password" : "Show password");
  btn.setAttribute("aria-pressed", revealed ? "true" : "false");
}

function togglePassword(inputId, btn) {
  const el = $(inputId);
  if (!el) return;
  const reveal = el.type === "password";
  el.type = reveal ? "text" : "password";
  setPasswordIcon(btn, reveal);
}

function openPasswordModal(username) {
  $("pw-user").textContent = username;
  $("pw-new").value = "";
  $("pw-new").type = "password";
  setPasswordIcon(document.querySelector('[data-pw-toggle="pw-new"]'), false);
  state._pwUser = username;
  open("pw-modal");
  setTimeout(() => $("pw-new").focus(), 50);
}

async function submitPassword() {
  const username = state._pwUser;
  const password = $("pw-new").value;
  // Mirror the server's floor so the admin gets an instant, specific message.
  if (!password || password.length < 12) {
    toast("Password must be at least 12 characters", "err");
    return;
  }
  try {
    const { body } = await api(`/api/v1/admin/users/${encodeURIComponent(username)}/password`, {
      method: "PUT",
      body: JSON.stringify({ password }),
    });
    if (body.success) {
      const n = body.data?.sessions_revoked || 0;
      toast(
        `Password updated for ${username}` +
          (n ? ` · ${n} active session${n > 1 ? "s" : ""} signed out` : "") +
          " · effective immediately, no restart",
        "ok"
      );
      closeModals();
    } else {
      toast(body.error || "Password update failed", "err");
    }
  } catch (e) {
    toast(e.message, "err");
  }
}

async function createUser() {
  const spec = { username: $("nu-name").value.trim(), password: $("nu-pass").value, role: $("nu-role").value, email: $("nu-email").value.trim() || null };
  if (!spec.username || !spec.password) return err("user-err", "Username and password required.");
  try {
    const { body } = await api("/api/v1/admin/users", { method: "POST", body: JSON.stringify(spec) });
    if (body.success) { closeModals(); toast(`Created ${spec.username}`, "ok"); loadUsers(); }
    else err("user-err", body.error || "failed");
  } catch (e) { err("user-err", e.message); }
}

let accessState = { sources: [], roles: [], access: {} };
async function loadRoleAccess() {
  if (!state.token) { $("access-matrix").innerHTML = ""; return; }
  try {
    const { body } = await api("/api/v1/admin/role-access");
    accessState = body && body.data;
    if (!accessState || !accessState.sources) {
      throw new Error(body?.error || "No access matrix returned by the server.");
    }
    const { sources, roles, access } = accessState;
    const head = `<tr><th>Role</th><th>All (*)</th>${sources.map((s) => `<th>${s}</th>`).join("")}</tr>`;
    const rows = roles.map((role) => {
      if (role === "admin") return `<tr><td>admin</td><td class="role-admin" colspan="${sources.length + 1}">full access (always)</td></tr>`;
      const val = access[role];
      const star = val === "*";
      const allowed = Array.isArray(val) ? val : [];
      const cells = sources.map((s) => `<td><input type="checkbox" data-role="${role}" data-src="${s}" ${star || allowed.includes(s) ? "checked" : ""} ${star ? "disabled" : ""} /></td>`).join("");
      return `<tr><td>${role}</td><td><input type="checkbox" data-role="${role}" data-star="1" ${star ? "checked" : ""} /></td>${cells}</tr>`;
    }).join("");
    $("access-matrix").innerHTML = `<table><thead>${head}</thead><tbody>${rows}</tbody></table>`;
  } catch (e) {
    $("access-matrix").innerHTML = `<p class="err">${esc(e.message)}</p>`;
    if (e.rateLimited) setTimeout(loadRoleAccess, (e.retryAfter || 60) * 1000);
  }
}
async function saveRoleAccess() {
  // collect per role from the matrix
  const perRole = {};
  document.querySelectorAll('#access-matrix input[data-star="1"]').forEach((star) => {
    const role = star.dataset.role;
    if (star.checked) { perRole[role] = "*"; return; }
    perRole[role] = [...document.querySelectorAll(`#access-matrix input[data-role="${role}"][data-src]`)]
      .filter((c) => c.checked).map((c) => c.dataset.src);
  });
  try {
    for (const [role, sources] of Object.entries(perRole)) {
      await api("/api/v1/admin/role-access", { method: "PUT", body: JSON.stringify({ role, sources }) });
    }
    toast("Access saved — applies immediately (no restart needed)", "ok");
    loadRoleAccess();
  } catch (e) { toast(e.message, "err"); }
}

// ── Health tab ─────────────────────────────────────────────────────────────────
let _healthTimer = null;
async function loadHealth() {
  try {
    const res = await fetch("/health", { cache: "no-store" });
    const body = await res.json().catch(() => ({}));
    const d = body.data || body || {};
    const services = d.services || {};
    const overallKind = d.status === "healthy" ? "ok" : d.status === "degraded" ? "warn" : "bad";
    const cards = [
      `<div class="hcard"><div class="name">Overall</div><div class="val"><span class="dot ${overallKind}"></span>${esc(d.status || "?")}</div></div>`,
      `<div class="hcard"><div class="name">Latency</div><div class="val">${d.duration_ms != null ? esc(String(d.duration_ms)) + " ms" : "—"}</div></div>`,
      `<div class="hcard"><div class="name">Building</div><div class="val">${esc(d.building || "—")}</div></div>`,
    ];
    for (const [k, v] of Object.entries(services)) {
      if (k === "circuit_breakers") continue; // rendered separately below
      const s = typeof v === "object" ? v.status : v;
      const ok = /ok|healthy|up|connected/i.test(String(s));
      const extra = v && Array.isArray(v.backends) ? ` <span class="hint">(${v.backends.length})</span>` : "";
      cards.push(`<div class="hcard"><div class="name">${esc(k)}</div><div class="val"><span class="dot ${ok ? "ok" : "bad"}"></span>${esc(String(s))}${extra}</div></div>`);
    }
    $("health-body").innerHTML = cards.join("");
    // Circuit breakers (payload nests them under services.circuit_breakers).
    const breakers = services.circuit_breakers || d.circuit_breakers || [];
    $("health-breakers").innerHTML = breakers.length
      ? `<h3 class="breaker-title">Circuit breakers</h3><div class="health-body">` +
        breakers.map((b) => {
          const kind = b.state === "closed" ? "ok" : b.state === "half_open" ? "warn" : "bad";
          return `<div class="hcard"><div class="name">${esc(b.name)}</div>
            <div class="val"><span class="dot ${kind}"></span>${esc(b.state)}</div>
            <div class="hint">${b.failure_count ?? 0}/${b.failure_threshold ?? "?"} failures</div></div>`;
        }).join("") + `</div>`
      : "";
  } catch (e) { $("health-body").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}
function toggleHealthAuto(on) {
  clearInterval(_healthTimer); _healthTimer = null;
  if (on) _healthTimer = setInterval(() => { if (!$("tab-health").hidden) loadHealth(); }, 5000);
}

// ── Overview tab ─────────────────────────────────────────────────────────────
function ovTile(name, val, sub, icon, kind, goto) {
  // A tile with a `goto` is a real button: clicking (or Enter/Space) opens the tab
  // that owns those numbers, so the summary and the detail never disagree.
  const tag = goto ? "button" : "div";
  const attrs = goto
    ? ` type="button" data-goto="${esc(goto)}" title="Open ${esc(TAB_META[goto] ? TAB_META[goto][0] : goto)}"` +
      ` aria-label="${esc(name)}: ${esc(String(val))}. Open ${esc(TAB_META[goto] ? TAB_META[goto][0] : goto)}"`
    : "";
  return `<${tag} class="ov-tile${goto ? " ov-link" : ""}"${attrs}><div class="ov-icon">${icon || ""}</div><div class="ov-meta">
    <div class="ov-name">${esc(name)}</div><div class="ov-val ${kind || ""}">${esc(String(val))}</div>
    <div class="ov-sub">${esc(sub || "")}</div></div>${goto ? '<span class="ov-go" aria-hidden="true">→</span>' : ""}</${tag}>`;
}
async function loadOverview() {
  const grid = $("overview-grid");
  const tiles = [];
  try {
    const { body } = await api("/api/v1/datasources");
    const srcs = body?.data?.sources || [];
    const on = srcs.filter((s) => s.enabled).length;
    tiles.push(ovTile("Data sources", `${on}/${srcs.length}`, `enabled · feature ${body?.data?.enabled ? "on" : "OFF"}`, "◧", "", "sources"));
  } catch (_) { tiles.push(ovTile("Data sources", "—", "unavailable", "◧", "bad", "sources")); }
  try {
    const r = await fetch("/health", { cache: "no-store" });
    const b = await r.json().catch(() => ({}));
    const d = b.data || b || {};
    const svcAll = d.services || {};
    // Only real services count. /health also carries diagnostics (e.g. circuit_breakers,
    // an array) which have no status and would otherwise be tallied as a failing service —
    // that is why this tile read "7/8" on a completely healthy stack.
    const svc = Object.fromEntries(
      Object.entries(svcAll).filter(([, v]) =>
        typeof v === "string" || (v && typeof v === "object" && !Array.isArray(v) && "status" in v)
      )
    );
    const total = Object.keys(svc).length;
    const okc = Object.values(svc).filter((v) => /ok|healthy|up|connected/i.test(String(typeof v === "object" ? v.status : v))).length;
    const kind = d.status === "healthy" ? "ok" : d.status === "degraded" ? "warn" : "bad";
    tiles.push(ovTile("Services", `${okc}/${total}`, `status: ${d.status || "?"}`, "♥", kind, "services"));
    tiles.push(ovTile("Building", d.building || "—", "active building", "▤", "", "ontology"));
  } catch (_) { tiles.push(ovTile("Services", "—", "health unavailable", "♥", "bad", "health")); }
  if (state.token) {
    try {
      const { body } = await api("/api/v1/admin/ai-config");
      const d = body.data || {};
      const model = d.model_provider === "openai" ? d.openai_model : d.model_provider === "cloud" ? d.ollama_cloud_model : d.ollama_model;
      const provLabel = d.model_provider === "local" ? "Local Ollama" : d.model_provider === "cloud" ? "Ollama Cloud" : "OpenAI";
      tiles.push(ovTile("LLM provider", provLabel, model || "", "⚛", "", "ai"));
      tiles.push(ovTile("Embeddings", embName(d), embDim(d) ? `${embDim(d)}-d` : "local", "▦", "", "ai"));
    } catch (_) {}
    try {
      const { body } = await api("/api/v1/admin/users");
      tiles.push(ovTile("Users", (body.data?.users || []).length, `${(body.data?.roles || []).length} roles`, "◐", "", "users"));
    } catch (_) {}
  } else {
    tiles.push(ovTile("Session", "read-only", "sign in for AI + user info", "◐", "warn"));
  }
  grid.innerHTML = tiles.join("");
}

// Keep the summary honest: re-read it whenever the Overview becomes visible again
// (switchTab already reloads on navigation; this covers returning to the browser
// tab after changing something, so the tiles never disagree with the detail tabs).
window.addEventListener("focus", () => {
  const ov = $("tab-overview");
  if (ov && !ov.hidden) loadOverview();
});

// ── Ask (query tester) tab ───────────────────────────────────────────────────
const ASK_SUGGESTIONS = [
  "What is the noise level on floor 5?",
  "What is the current occupancy on floor 3?",
  "What is the energy consumption today?",
  "How many temperature sensors are there?",
];
function renderAskSuggestions() {
  $("ask-suggestions").innerHTML = ASK_SUGGESTIONS.map((q) => `<button class="chip-btn" data-ask-q="${esc(q)}">${esc(q)}</button>`).join("");
}
function mdLite(s) {
  return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>");
}
async function askQuestion(q) {
  q = (q || $("ask-input").value || "").trim();
  if (!q) return;
  if (!state.token) return toast("Sign in first to ask", "err");
  $("ask-input").value = q;
  const box = $("ask-result");
  box.innerHTML = '<p class="hint">Thinking… (real pipeline — can take a few seconds)</p>';
  try {
    const { body } = await api("/chat", { method: "POST", body: JSON.stringify({ message: q, session_id: "console-ask-" + Date.now() }) });
    const d = body.data || {};
    const resp = d.response || d.message || "(no response)";
    const chips = (d.sources || []).map((s) =>
      `<span class="prov-chip" style="border-color:${s.color || "#888"};color:${s.color || "#888"}">${esc(s.label || s.source_id)}${s.synthetic ? " · sim" : ""}</span>`).join("");
    box.innerHTML = `<div class="ask-answer">${mdLite(resp)}</div>
      <div class="ask-meta">
        <div class="ask-prov">${chips || '<span class="hint">no provenance tags</span>'}</div>
        <div class="hint">routed intent: <b>${esc(d.intent || "—")}</b></div>
      </div>`;
  } catch (e) { box.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}

// ── AI & Models tab ──────────────────────────────────────────────────────────
let aiCfg = null;
async function loadAiConfig() {
  if (!state.token) { $("ai-body").innerHTML = '<p class="hint">Sign in as admin to view.</p>'; return; }
  try {
    const { body } = await api("/api/v1/admin/ai-config");
    aiCfg = body.data || {};
    renderAiConfig();
  } catch (e) { $("ai-body").innerHTML = `<p class="err">${e.message}</p>`; }
}
function renderAiConfig() {
  const c = aiCfg;
  const provLabel = (p) => (p === "local" ? "Local Ollama" : p === "cloud" ? "Ollama Cloud" : "OpenAI");
  const providerRadios = (c.providers || []).map((p) =>
    `<label class="radio"><input type="radio" name="ai-provider" value="${p}" ${p === c.model_provider ? "checked" : ""}/> ${provLabel(p)}</label>`).join("");
  const embLabel = (p) => {
    if (p === "openai") return `OpenAI${c.embedding_dimension_openai ? ` (${c.embedding_dimension_openai}-d)` : ""}`;
    const name = c.embedding_model_local ? ` — ${esc(embModelShort(c.embedding_model_local))}` : "";
    return `Local${name}${c.embedding_dimension_local ? ` (${c.embedding_dimension_local}-d)` : ""}`;
  };
  const embRadios = (c.embedding_providers || []).map((p) =>
    `<label class="radio"><input type="radio" name="ai-emb" value="${p}" ${p === c.embedding_provider ? "checked" : ""}/> ${embLabel(p)}</label>`).join("");
  const dimSwap = c.embedding_dimension_local && c.embedding_dimension_openai
    ? ` (${c.embedding_dimension_local} ↔ ${c.embedding_dimension_openai})` : "";
  $("ai-body").innerHTML = `
    <div class="ai-card">
      <h3>LLM provider</h3>
      <div class="ai-radios">${providerRadios}</div>
      <div id="ai-provider-fields" class="ai-fields"></div>
      <div class="ai-actions">
        <button class="btn small" id="ai-test">Test connection</button>
        <span class="restart-status" id="ai-test-status"></span>
      </div>
    </div>
    <div class="ai-card">
      <h3>Embedding backend</h3>
      <div class="ai-radios">${embRadios}</div>
      <p class="warn-inline">⚠ Switching the embedding provider changes vector dimensions${dimSwap} and
        <b>invalidates the existing Qdrant index</b>. Re-index after changing this.</p>
    </div>
    <div class="ai-save">
      <button class="btn primary" id="ai-save">Save to .env</button>
      <span class="hint">Applies after an orchestrator recreate.</span>
    </div>`;
  renderProviderFields(c.model_provider);
  document.querySelectorAll('input[name="ai-provider"]').forEach((r) =>
    r.addEventListener("change", () => renderProviderFields(r.value)));
}
function renderProviderFields(prov) {
  const c = aiCfg;
  const keyChip = (set) => (set ? '<span class="chip ok-chip">set ✓</span>' : '<span class="chip">not set</span>');
  const keyPh = (set) => (set ? "leave blank to keep current" : "paste key");
  let html = "";
  if (prov === "local") {
    html = `
      <label>Ollama base URL <input id="ai-ollama-url" value="${esc(c.ollama_base_url || "")}" /></label>
      <label>Model
        <span class="model-row">
          <input id="ai-ollama-model" list="ai-model-list" value="${esc(c.ollama_model || "")}" />
          <button class="btn ghost small" id="ai-fetch-models" type="button">Fetch installed</button>
        </span>
      </label>
      <datalist id="ai-model-list"></datalist>`;
  } else if (prov === "cloud") {
    html = `
      <label>Ollama Cloud base URL <input id="ai-cloud-url" value="${esc(c.ollama_cloud_base_url || "")}" /></label>
      <label>Model <input id="ai-cloud-model" value="${esc(c.ollama_cloud_model || "")}" /></label>
      <label>Cloud API key ${keyChip(c.ollama_cloud_api_key_set)}
        <input id="ai-cloud-key" type="password" placeholder="${keyPh(c.ollama_cloud_api_key_set)}" /></label>`;
  } else {
    html = `
      <label>Model
        <input id="ai-openai-model" list="ai-model-list" value="${esc(c.openai_model || "")}" />
      </label>
      <datalist id="ai-model-list"><option>gpt-4o</option><option>gpt-4o-mini</option><option>gpt-4.1</option><option>gpt-4.1-mini</option></datalist>
      <label>Fast model <input id="ai-openai-model-fast" value="${esc(c.openai_model_fast || "")}" /></label>
      <label>OpenAI API key ${keyChip(c.openai_api_key_set)}
        <input id="ai-openai-key" type="password" placeholder="${keyPh(c.openai_api_key_set)}" /></label>`;
  }
  $("ai-provider-fields").innerHTML = html;
}
async function testAiProvider() {
  const prov = document.querySelector('input[name="ai-provider"]:checked')?.value;
  if (!prov) return;
  const st = $("ai-test-status");
  st.innerHTML = `<span class="dot warn"></span>testing…`;
  const payload = { provider: prov };
  if (prov === "local" && $("ai-ollama-url")) payload.base_url = $("ai-ollama-url").value.trim();
  if (prov === "cloud") { if ($("ai-cloud-url")) payload.base_url = $("ai-cloud-url").value.trim(); const k = $("ai-cloud-key")?.value; if (k) payload.api_key = k; }
  if (prov === "openai") { const k = $("ai-openai-key")?.value; if (k) payload.api_key = k; }
  try {
    const { body } = await api("/api/v1/admin/ai-config/test", { method: "POST", body: JSON.stringify(payload) });
    const d = body.data || {};
    if (body.success && d.ok) {
      st.innerHTML = `<span class="dot ok"></span>ok · ${d.latency_ms ?? "?"}ms · ${(d.models || []).length} model(s)`;
      const dl = $("ai-model-list");
      if (dl && (d.models || []).length) dl.innerHTML = d.models.map((m) => `<option>${esc(m)}</option>`).join("");
    } else {
      st.innerHTML = `<span class="dot bad"></span>${esc((body.error || "unreachable")).slice(0, 90)}`;
    }
  } catch (e) { st.innerHTML = `<span class="dot bad"></span>${esc(e.message)}`; }
}
async function saveAiConfig() {
  const prov = document.querySelector('input[name="ai-provider"]:checked')?.value;
  const emb = document.querySelector('input[name="ai-emb"]:checked')?.value;
  const changes = { MODEL_PROVIDER: prov, EMBEDDING_PROVIDER: emb };
  if (prov === "local") {
    if ($("ai-ollama-url")) changes.OLLAMA_BASE_URL = $("ai-ollama-url").value.trim();
    if ($("ai-ollama-model")) changes.OLLAMA_MODEL = $("ai-ollama-model").value.trim();
  } else if (prov === "cloud") {
    if ($("ai-cloud-url")) changes.OLLAMA_CLOUD_BASE_URL = $("ai-cloud-url").value.trim();
    if ($("ai-cloud-model")) changes.OLLAMA_CLOUD_MODEL = $("ai-cloud-model").value.trim();
    const k = $("ai-cloud-key")?.value; if (k) changes.OLLAMA_CLOUD_API_KEY = k;
  } else if (prov === "openai") {
    if ($("ai-openai-model")) changes.OPENAI_MODEL = $("ai-openai-model").value.trim();
    if ($("ai-openai-model-fast")) changes.OPENAI_MODEL_FAST = $("ai-openai-model-fast").value.trim();
    const k = $("ai-openai-key")?.value; if (k) changes.OPENAI_API_KEY = k;
  }
  try {
    const { body } = await api("/api/v1/admin/env", { method: "PUT", body: JSON.stringify({ changes }) });
    if (body.success) {
      toast("AI config saved to .env", "ok");
      showRecreateNotice("AI provider/model saved — recreate the orchestrator to apply (clients are built at boot).");
    } else toast(body.error || "save failed", "err");
  } catch (e) { toast(e.message, "err"); }
}

// ── Integrations tab (feeds + notification channels) ─────────────────────────
// ── Services launcher: cards that open each attached tool's web UI ──────────────
// Open URL is built from the viewer's own hostname so links work via localhost OR a
// remote IP. Status (online/offline/optional) is probed server-side.
function serviceOpenUrl(s) {
  const proto = location.protocol === "https:" ? "https:" : "http:";
  return `${proto}//${location.hostname}:${s.port}${s.path || "/"}`;
}
async function loadServices() {
  const grid = $("services-grid");
  if (!state.token) { grid.innerHTML = '<p class="hint">Sign in as admin to view.</p>'; return; }
  grid.innerHTML = '<p class="hint">Probing services…</p>';
  try {
    const { body } = await api("/api/v1/admin/services");
    if (!body.success) { grid.innerHTML = `<p class="hint">${esc(body.error || "failed")}</p>`; return; }
    renderServiceCards(body.data?.services || []);
  } catch (e) { grid.innerHTML = `<p class="hint">${esc(e.message)}</p>`; }
}
function renderServiceCards(services) {
  const grid = $("services-grid");
  if (!services.length) { grid.innerHTML = '<p class="hint">No services configured.</p>'; return; }
  // group by category, preserving catalog order
  const cats = [];
  const byCat = {};
  services.forEach((s) => {
    const c = s.category || "Other";
    if (!byCat[c]) { byCat[c] = []; cats.push(c); }
    byCat[c].push(s);
  });
  grid.innerHTML = cats.map((c) => `
    <h3 class="svc-cat">${esc(c)}</h3>
    <div class="svc-grid">${byCat[c].map(serviceCard).join("")}</div>`).join("");
}
function serviceCard(s) {
  const dot = s.status === "online" ? "ok" : s.status === "optional" ? "warn" : "bad";
  const statusText = s.status === "online" ? "online" : s.status === "optional" ? "optional" : "offline";
  const url = serviceOpenUrl(s);
  const openable = s.status === "online";
  const openBtn = openable
    ? `<a class="btn small primary" href="${esc(url)}" target="_blank" rel="noopener">Open ↗</a>`
    : `<button class="btn small" disabled title="${esc(s.note || "Service is not running")}">Open ↗</button>`;
  return `<div class="svc-card${openable ? "" : " svc-off"}">
    <div class="svc-icon">${s.icon || "◇"}</div>
    <div class="svc-body">
      <div class="svc-name">${esc(s.name)} <span class="dot ${dot}"></span><span class="svc-status">${statusText}</span></div>
      <div class="svc-desc">${esc(s.desc || "")}</div>
      ${s.status === "optional" && s.note ? `<div class="svc-note">${esc(s.note)}</div>` : ""}
      <div class="svc-actions">${openBtn}<span class="svc-url">:${s.port}${esc(s.path || "/")}</span></div>
    </div>
  </div>`;
}

async function loadIntegrations() {
  if (!state.token) {
    $("feeds-list").innerHTML = '<p class="hint">Sign in as admin to view.</p>';
    $("channels-list").innerHTML = "";
    return;
  }
  try {
    const { body } = await api("/api/v1/admin/integrations");
    const d = body.data || {};
    const feeds = d.feeds || [];
    $("feeds-list").innerHTML = feeds.length
      ? feeds.map((f) => `
        <div class="int-card">
          <div class="int-head">
            <b>${esc(f.id || "?")}</b>
            <span class="chip">${esc(f.type || "")}</span>
            <span class="dot ${f.enabled ? "ok" : "bad"}"></span><span class="hint">${f.enabled ? "enabled" : "disabled"}</span>
          </div>
          <div class="int-meta">
            ${f.brick_class ? `<span>${esc(f.brick_class)}</span>` : ""}
            ${f.interval_s ? `<span>every ${esc(String(f.interval_s))}s</span>` : ""}
            ${f.storage ? `<span>→ ${esc(f.storage)}</span>` : ""}
          </div>
          ${f.url ? `<div class="int-url">${esc(f.url)}</div>` : ""}
        </div>`).join("")
      : '<p class="hint">No feeds configured (input/feeds.yaml).</p>';

    const channels = d.channels || [];
    $("channels-list").innerHTML = channels.length
      ? channels.map((c) => `
        <div class="int-card">
          <div class="int-head">
            <b>${esc(c.id || "?")}</b>
            <span class="chip">${esc(c.type || "")}</span>
            <span class="dot ${c.enabled ? "ok" : "bad"}"></span><span class="hint">${c.enabled ? "enabled" : "disabled"}</span>
            <button class="btn ghost small" data-test-channel="${esc(c.id)}" style="margin-left:auto">Test send</button>
          </div>
          ${c.target ? `<div class="int-url">${esc(c.target)}</div>` : ""}
          <span class="test-channel-status" id="chstat-${esc(c.id)}"></span>
        </div>`).join("")
      : '<p class="hint">No channels configured (input/channels.yaml).</p>';
  } catch (e) {
    $("feeds-list").innerHTML = `<p class="err">${esc(e.message)}</p>`;
  }
}
async function testChannel(id) {
  const st = $("chstat-" + id);
  if (st) st.innerHTML = `<span class="dot warn"></span>sending…`;
  try {
    const { body } = await api(`/api/v1/admin/channels/${encodeURIComponent(id)}/test`, { method: "POST" });
    if (st) st.innerHTML = body.success
      ? `<span class="dot ok"></span>sent ✓`
      : `<span class="dot bad"></span>${esc((body.error || "not sent")).slice(0, 80)}`;
    toast(body.success ? `Test sent via ${id}` : (body.error || "not sent"), body.success ? "ok" : "err");
  } catch (e) { if (st) st.innerHTML = `<span class="dot bad"></span>${esc(e.message)}`; }
}

// ── Audit tab ────────────────────────────────────────────────────────────────
async function loadAudit() {
  if (!state.token) { $("audit-body").innerHTML = '<p class="hint">Sign in as admin to view.</p>'; return; }
  try {
    const { body } = await api("/api/v1/admin/audit?limit=200");
    const entries = body.data?.entries || [];
    if (!entries.length) { $("audit-body").innerHTML = '<p class="hint">No admin actions recorded yet.</p>'; return; }
    const rows = entries.map((e) => {
      const ok = (e.status || 0) < 400;
      const ts = e.ts ? new Date(e.ts).toLocaleString() : "—";
      return `<tr>
        <td class="mono">${esc(ts)}</td>
        <td>${esc(e.username || "anonymous")}${e.role ? ` <span class="hint">(${esc(e.role)})</span>` : ""}</td>
        <td><span class="chip">${esc(e.method || "")}</span></td>
        <td class="mono">${esc(e.path || "")}</td>
        <td><span class="dot ${ok ? "ok" : "bad"}"></span>${esc(String(e.status ?? "—"))}</td>
      </tr>`;
    }).join("");
    $("audit-body").innerHTML = `<div class="audit-scroll"><table class="audit-table"><thead><tr>
      <th>When</th><th>User</th><th>Method</th><th>Path</th><th>Status</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  } catch (e) { $("audit-body").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}

// ── Auth ─────────────────────────────────────────────────────────────────────
async function login(u, p) {
  const res = await fetch("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: u, password: p }) });
  const body = await res.json().catch(() => ({}));
  const token = body?.data?.session_token;
  if (!token) throw new Error(body?.error || "Login failed");
  // This console only does admin work: ontology, .env, databases, users. A non-admin
  // could sign in and then hit 403 on every action — refuse here with a clear reason
  // instead. (Server-side RBAC still gates every endpoint independently; this is the
  // explanation, not the enforcement.)
  const role = body?.data?.role;
  // Confirm admin rights against the SERVER, not just the role field in the login
  // response: this console only performs admin work, and a non-admin who got past a
  // client-side check would simply hit 403 on every action with no explanation.
  // The API is the real gate (every admin route requires system:admin); this probe
  // makes the console agree with it instead of showing an empty, broken shell.
  const probe = await fetch("/api/v1/admin/capabilities", {
    headers: { "Content-Type": "application/json", Authorization: token },
  });
  if (probe.status === 401 || probe.status === 403) {
    throw new Error(
      `This console requires an admin account${role ? ` — '${u}' has the '${role}' role` : ""}. ` +
        `Use the chat interface on port 3000 instead.`
    );
  }
  state.token = token; state.user = u; state.role = role || "admin";
  localStorage.setItem("ds_token", token); localStorage.setItem("ds_user", u);
}
function logout() {
  state.token = null; state.user = null;
  localStorage.removeItem("ds_token"); localStorage.removeItem("ds_user");
  setAuthUI(); loadSources(); loadOverview();
}
// Open the admin sign-in modal (optionally with a message) and focus the username field.
function promptLogin(msg) {
  if (msg) { $("login-err").textContent = msg; $("login-err").hidden = false; }
  else { $("login-err").hidden = true; }
  // Always reopen masked: a password left revealed from a previous attempt would sit
  // in plain sight on a shared screen.
  const pw = $("p");
  if (pw) pw.type = "password";
  setPasswordIcon(document.querySelector('[data-pw-toggle="p"]'), false);
  open("login-modal");
  setTimeout(() => $("u") && $("u").focus(), 60);
}
// On load / bfcache restore: prompt admin sign-in if there is no session, or if the stored
// token has expired (sessions are server-side and can lapse or be revoked between visits, so
// a persisted ds_token can look "signed in" while every API call 401s).
async function ensureAdminSession() {
  if (!state.token) { promptLogin(); return; }
  try {
    const res = await fetch("/api/v1/admin/capabilities", { headers: authHeaders() });
    if (res.status === 401 || res.status === 403) {
      state.token = null; state.user = null;
      localStorage.removeItem("ds_token"); localStorage.removeItem("ds_user");
      setAuthUI();
      promptLogin("Your admin session has expired — please sign in again.");
    }
  } catch (_) { /* network hiccup — leave the session as-is */ }
}

// ── Modals + events ────────────────────────────────────────────────────────────
function open(id) { $(id).hidden = false; }
// ── Ontology tab (capabilities + named graphs + TTL upload + SPARQL) ─────────────
let capTypes = ["Facility"];
const localName = (uri) => { const s = String(uri || ""); const i = Math.max(s.lastIndexOf("#"), s.lastIndexOf("/")); return i >= 0 ? s.slice(i + 1) : s; };
const localOk = (s) => /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(s || "");

function loadOntology() {
  loadBuildingConfig();
  loadSimStatus();
  loadCapabilities();
  loadGraphs();
  loadDocuments();
  loadFloorPlanFiles();
  if (answerabilityData) renderOntoCoverage(answerabilityData);
  else if (state.token) loadAnswerability();
}

// ── Building identity (ontology namespace / prefix) ────────────────────────────
async function loadBuildingConfig() {
  if (!state.token) { setStatus("bldg-status", "", ""); return; }
  try {
    const { body } = await api("/api/v1/admin/building/config");
    const d = body.data || {};
    if ($("bldg-id")) $("bldg-id").value = d.building_id || "";
    if ($("bldg-name")) $("bldg-name").value = d.building_name || "";
    if ($("bldg-ns")) $("bldg-ns").value = d.ontology_namespace || "";
    if ($("bldg-prefix")) $("bldg-prefix").value = d.ontology_prefix || "bldg";
  } catch (e) { setStatus("bldg-status", "bad", e.message); }
}

async function saveBuildingConfig() {
  if (!state.token) return toast("Sign in as admin first", "err");
  const ns = $("bldg-ns").value.trim();
  const prefix = $("bldg-prefix").value.trim() || "bldg";
  const name = $("bldg-name").value.trim();
  if (!ns) return toast("Ontology namespace is required", "err");
  setStatus("bldg-status", "warn", "saving…");
  try {
    const { body } = await api("/api/v1/admin/building/config", {
      method: "PUT",
      body: JSON.stringify({ ontology_namespace: ns, ontology_prefix: prefix, building_name: name }),
    });
    if (body.success) {
      setStatus("bldg-status", "ok", "saved ✓");
      showRecreateNotice("Building namespace/prefix saved to building.yaml — restart the orchestrator to apply it.");
    } else {
      setStatus("bldg-status", "bad", body.error || "save failed");
      toast(body.error || "Save failed", "err");
    }
  } catch (e) { setStatus("bldg-status", "bad", e.message); toast(e.message, "err"); }
}

// ── Semantic search index status ───────────────────────────────────────────────
async function loadSimStatus() {
  if (!state.token) { $("sim-state").innerHTML = "Sign in as admin to view."; return; }
  try {
    const { body } = await api("/api/v1/admin/reindex/similarity-status");
    const d = body.data || {};
    const busy = !d.ready || d.graphdb_building || d.state === "pending" || d.state === "rebuilding";
    const gs = d.graphdb_status ? ` · GraphDB: ${esc(d.graphdb_status)}` : "";
    const dot = busy ? '<span class="dot warn"></span>' : '<span class="dot ok"></span>';
    $("sim-state").innerHTML = busy
      ? `${dot}Rebuilding — newly-added sensors/triples will be searchable shortly${gs}.`
      : `${dot}Up to date — ask OntoSage your questions${gs}.`;
    if ($("sim-rebuild")) $("sim-rebuild").disabled = busy;
    if (busy) { clearTimeout(loadSimStatus._t); loadSimStatus._t = setTimeout(loadSimStatus, 3000); }
  } catch (e) { $("sim-state").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
}

async function rebuildSim() {
  if (!state.token) return toast("Sign in as admin first", "err");
  try {
    await api("/api/v1/admin/reindex", { method: "POST", body: JSON.stringify({ targets: ["ontology_similarity"] }) });
    toast("Rebuild started", "ok"); loadSimStatus();
  } catch (e) { toast(e.message, "err"); }
}

async function loadCapabilities() {
  if (!state.token) { $("cap-list").innerHTML = '<p class="hint">Sign in as admin to view capabilities.</p>'; return; }
  try {
    const { body } = await api("/api/v1/admin/capabilities");
    const rows = body.data?.amenities || [];
    if (body.data?.types?.length) capTypes = body.data.types;
    $("cap-count").textContent = `${rows.length} capabilit${rows.length === 1 ? "y" : "ies"}`;
    $("cap-list").innerHTML = rows.map((a) => {
      const loc = a.loc ? ` · ${esc(a.loc)}` : "";
      return `<div class="db-card">
        <h4>${esc(a.label || "(no label)")}</h4>
        <div class="kv"><span>id</span><span>${esc(localName(a.a))}</span></div>
        ${a.loc ? `<div class="kv"><span>location</span><span>${esc(a.loc)}</span></div>` : ""}
        <div class="db-actions"><button class="btn small danger" data-del-cap="${esc(localName(a.a))}">Delete</button></div>
      </div>`;
    }).join("") || '<p class="hint">No capabilities yet. Click “+ Add capability”.</p>';
  } catch (e) { $("cap-list").innerHTML = `<p class="err">${e.message}</p>`; }
}

function openCapModal() {
  if (!state.token) return toast("Sign in as admin first", "err");
  $("cap-err").hidden = true;
  $("cap-type").innerHTML = capTypes.map((t) => `<option>${esc(t)}</option>`).join("");
  ["id", "label", "location", "floor", "category", "lay", "note", "answer", "url", "email", "phone", "reportto", "steps"].forEach((f) => { if ($("cap-" + f)) $("cap-" + f).value = ""; });
  open("cap-modal");
}

async function createCapability() {
  const payload = {
    id: $("cap-id").value.trim(), type: $("cap-type").value, label: $("cap-label").value.trim(),
    location: $("cap-location").value.trim(), floor: $("cap-floor").value.trim(),
    category: $("cap-category").value.trim(), lay_terms: $("cap-lay").value.trim(),
    note: $("cap-note").value.trim(),
    answer_text: $("cap-answer").value.trim(), info_url: $("cap-url").value.trim(),
    contact_email: $("cap-email").value.trim(), contact_phone: $("cap-phone").value.trim(),
    report_to: $("cap-reportto").value.trim(), steps: $("cap-steps").value.trim(),
  };
  if (!payload.id || !localOk(payload.id)) return err("cap-err", "ID must be a simple local name (letters, digits, _ . -), starting with a letter.");
  if (!payload.label) return err("cap-err", "Label is required.");
  try {
    const { body } = await api("/api/v1/admin/capabilities", { method: "POST", body: JSON.stringify(payload) });
    if (!body.success) return err("cap-err", body.error || "Failed to add capability.");
    closeModals(); toast(`Added capability: ${localName(body.data?.subject)}`, "ok"); loadCapabilities();
  } catch (e) { err("cap-err", e.message); }
}

async function deleteCapability(name) {
  if (!confirm(`Delete capability "${name}"?\n\nRemoved from the building's capability TTL (a backup is saved to input/.trash/ first) and re-synced, so the deletion persists across restarts.`)) return;
  try {
    const { body } = await api(`/api/v1/admin/capabilities/${encodeURIComponent(name)}`, { method: "DELETE" });
    toast(body.success ? `Deleted: ${name}` : (body.error || "Delete failed"), body.success ? "ok" : "err");
    loadCapabilities();
  } catch (e) { toast(e.message, "err"); }
}

async function loadGraphs() {
  if (!state.token) { $("graph-list").innerHTML = '<p class="hint">Sign in as admin to view named graphs.</p>'; return; }
  try {
    const { body } = await api("/api/v1/admin/ontology/graphs");
    const graphs = body.data?.graphs || {};
    const entries = Object.entries(graphs).sort((a, b) => b[1] - a[1]);
    $("graph-list").innerHTML = entries.map(([g, n]) => {
      const isFile = g.startsWith("urn:ontosage:ttl:");
      return `<div class="db-card">
        <h4 class="onto-guri">${esc(g)}</h4>
        <div class="kv"><span>triples</span><span>${Number(n).toLocaleString()}</span>${isFile ? '<span class="src-badge custom" title="Backed by an input/ file">file</span>' : ""}</div>
        <div class="db-actions"><button class="btn small danger" data-drop-graph="${esc(g)}">Drop</button></div>
      </div>`;
    }).join("") || '<p class="hint">No named graphs found (GraphDB empty or unreachable).</p>';
  } catch (e) { $("graph-list").innerHTML = `<p class="err">${e.message}</p>`; }
}

async function dropGraph(uri) {
  const isFile = uri.startsWith("urn:ontosage:ttl:");
  const extra = isFile ? "\n\nIts input/ file is moved to input/.trash/ (reversible) so the drop survives a restart." : "\n\nThis removes the triples from GraphDB only.";
  if (!confirm(`Drop named graph:\n${uri}${extra}`)) return;
  try {
    const { body } = await api(`/api/v1/admin/ontology/graphs/${encodeURIComponent(uri)}`, { method: "DELETE" });
    toast(body.data?.dropped ? `Dropped: ${uri}` : (body.error || "Drop failed"), body.data?.dropped ? "ok" : "err");
    loadGraphs();
  } catch (e) { toast(e.message, "err"); }
}

async function validateOntoTtl() {
  const ttl = $("onto-ttl").value.trim();
  if (!ttl) return toast("Paste some Turtle first", "err");
  try {
    const { body } = await api("/api/v1/admin/ontology/validate", { method: "POST", body: JSON.stringify({ ttl }) });
    if (body.success) toast(`Valid — ${body.data?.triple_count} triples, ${Object.keys(body.data?.prefixes || {}).length} prefixes`, "ok");
    else toast(body.error || body.data?.error || "Invalid Turtle", "err");
  } catch (e) { toast(e.message, "err"); }
}

async function uploadOntoTtl() {
  if (!state.token) return toast("Sign in as admin first", "err");
  const ttl = $("onto-ttl").value.trim(); const graph_uri = $("onto-graph").value.trim();
  if (!ttl || !graph_uri) return toast("Named graph and Turtle are both required", "err");
  setStatus("onto-upload-status", "warn", "uploading…");
  try {
    const { body } = await api("/api/v1/admin/ontology/upload", { method: "POST", body: JSON.stringify({ ttl, graph_uri }) });
    if (body.success) {
      const persisted = body.data?.persisted ? ` · saved to ${localName(body.data?.file || "")}` : " · GraphDB only";
      setStatus("onto-upload-status", "ok", "uploaded ✓"); toast(`Uploaded${persisted}`, "ok"); loadGraphs();
    } else { setStatus("onto-upload-status", "bad", "failed"); toast(body.error || "Upload failed", "err"); }
  } catch (e) { setStatus("onto-upload-status", "bad", "failed"); toast(e.message, "err"); }
}

async function runSparql() {
  const query = $("onto-sparql").value.trim();
  if (!query) return toast("Enter a SELECT/ASK query", "err");
  $("onto-sparql-result").innerHTML = '<p class="hint">Running…</p>';
  try {
    const { body } = await api("/api/v1/admin/ontology/sparql", { method: "POST", body: JSON.stringify({ query, limit: 100 }) });
    if (!body.success) { $("onto-sparql-result").innerHTML = `<p class="err">${esc(body.error || "query failed")}</p>`; return; }
    const cols = body.data?.columns || []; const rows = body.data?.rows || [];
    const head = cols.map((c) => `<th>${esc(c)}</th>`).join("");
    const trs = rows.map((r) => `<tr>${cols.map((c) => `<td>${esc(r[c] ?? "")}</td>`).join("")}</tr>`).join("");
    $("onto-sparql-result").innerHTML = `<table class="onto-table"><thead><tr>${head}</tr></thead><tbody>${trs}</tbody></table><p class="hint">${body.data?.count} rows</p>`;
  } catch (e) { $("onto-sparql-result").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}
// ── Knowledge files: document + floor-plan uploads (pure-GUI onboarding) ─────────
async function apiUpload(path, formData) {
  // multipart POST — no JSON Content-Type so the browser sets the boundary
  const res = await fetch(path, { method: "POST", headers: { ...authHeaders() }, body: formData });
  let body = {};
  try { body = await res.json(); } catch (_) {}
  if (res.status === 401 || res.status === 403)
    throw new Error("Not authorised — sign in with an admin account.");
  return { status: res.status, body };
}

async function loadDocuments() {
  const box = $("doc-list"); if (!box) return;
  try {
    const { body } = await api("/api/v1/admin/documents");
    const items = body.data?.documents || [];
    box.innerHTML = items.length
      ? items.map((d) => `<div class="db-row"><span>📄 ${esc(d.filename)}</span><span class="hint">${(d.bytes / 1024).toFixed(1)} KB</span><button class="btn tiny ghost" data-del-doc="${esc(d.filename)}">Delete</button></div>`).join("")
      : '<p class="hint">No documents yet — upload a .md / .txt / .pdf policy or manual.</p>';
  } catch (e) { box.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}

async function uploadDocument() {
  if (!state.token) return toast("Sign in as admin first", "err");
  const f = $("doc-file").files[0];
  if (!f) return toast("Choose a .md / .txt / .pdf file first", "err");
  setStatus("doc-upload-status", "warn", "uploading…");
  const fd = new FormData(); fd.append("file", f);
  try {
    const { body } = await apiUpload("/api/v1/admin/documents/upload", fd);
    if (body.success) {
      setStatus("doc-upload-status", "ok", "uploaded ✓");
      toast(`Uploaded ${body.data?.filename} · reindexing document KB`, "ok");
      $("doc-file").value = ""; loadDocuments();
    } else { setStatus("doc-upload-status", "bad", "failed"); toast(body.error || "Upload failed", "err"); }
  } catch (e) { setStatus("doc-upload-status", "bad", "failed"); toast(e.message, "err"); }
}

async function deleteDocument(name) {
  if (!confirm(`Delete document "${name}"?`)) return;
  try {
    const { body } = await api(`/api/v1/admin/documents/${encodeURIComponent(name)}`, { method: "DELETE" });
    if (body.success) { toast(`Deleted ${name}`, "ok"); loadDocuments(); }
    else toast(body.error || "Delete failed", "err");
  } catch (e) { toast(e.message, "err"); }
}

async function loadFloorPlanFiles() {
  const box = $("fp-list"); if (!box) return;
  try {
    const { body } = await api("/api/v1/admin/floor-plans/files");
    const items = body.data?.floor_plans || [];
    box.innerHTML = items.length
      ? items.map((d) => `<div class="db-row"><span>🗺️ ${esc(d.filename)}</span><span class="hint">${(d.bytes / 1024).toFixed(1)} KB</span></div>`).join("")
      : '<p class="hint">No floor plans yet — upload a PDF or DWG per floor.</p>';
  } catch (e) { box.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}

async function uploadFloorPlan() {
  if (!state.token) return toast("Sign in as admin first", "err");
  const f = $("fp-file").files[0];
  const floor = $("fp-floor").value.trim();
  if (!f) return toast("Choose a PDF / DWG file first", "err");
  if (floor === "") return toast("Enter the floor number", "err");
  setStatus("fp-upload-status", "warn", "uploading…");
  const fd = new FormData(); fd.append("file", f); fd.append("floor", floor);
  const label = $("fp-label").value.trim(); if (label) fd.append("label", label);
  try {
    const { body } = await apiUpload("/api/v1/admin/floor-plans/upload", fd);
    if (body.success) {
      const m = body.data?.manifest || {};
      setStatus("fp-upload-status", "ok", "ingested ✓");
      toast(`Uploaded ${body.data?.filename}${m.spaces ? ` · ${m.spaces} spaces` : ""}`, "ok");
      $("fp-file").value = ""; loadFloorPlanFiles();
    } else { setStatus("fp-upload-status", "bad", "failed"); toast(body.error || "Upload failed", "err"); }
  } catch (e) { setStatus("fp-upload-status", "bad", "failed"); toast(e.message, "err"); }
}

function setStatus(id, kind, text) { const el = $(id); if (el) el.innerHTML = kind ? `<span class="dot ${kind}"></span>${text}` : ""; }

function closeModals() { document.querySelectorAll(".modal-backdrop").forEach((m) => (m.hidden = true)); }
function err(id, msg) { $(id).textContent = msg; $(id).hidden = false; }

$("nav").addEventListener("click", (e) => { const b = e.target.closest(".nav-item"); if (b) switchTab(b.dataset.tab); });
document.addEventListener("click", (e) => {
  const t = e.target;
  if (t.dataset.close !== undefined || t.classList.contains("modal-backdrop")) closeModals();
  if (t.dataset.preview) preview(t.dataset.preview);
  if (t.dataset.regen) regenerate(t.dataset.regen);
  if (t.dataset.details) showDetails(t.dataset.details);
  if (t.dataset.delUser) deleteUser(t.dataset.delUser);
  if (t.dataset.pwFor) openPasswordModal(t.dataset.pwFor);
  const pwBtn = e.target.closest && e.target.closest("[data-pw-toggle]");
  if (pwBtn) togglePassword(pwBtn.dataset.pwToggle, pwBtn);
  if (t.dataset.sensors) openSensors(t.dataset.sensors);
  if (t.dataset.verifyDb) verifyDatasource(t.dataset.verifyDb);
  if (t.dataset.testDb) testDatabase(t.dataset.testDb);
  if (t.dataset.dataDb) showDataPreview(t.dataset.dataDb, t.dataset.table);
  if (t.dataset.delDb) deleteDatabaseConn(t.dataset.delDb);
  if (t.dataset.delCap) deleteCapability(t.dataset.delCap);
  if (t.dataset.delDoc) deleteDocument(t.dataset.delDoc);
  if (t.dataset.dropGraph) dropGraph(t.dataset.dropGraph);
  if (t.classList.contains("mode-tab")) setSensorMode(t.dataset.mode);
  // Resolve through ancestors: a tile's clickable area contains child nodes (icon,
  // value, caption), and `e.target` is whichever of those was actually hit — so a
  // click on the big number must still reach the element carrying data-goto.
  const gotoEl = e.target.closest && e.target.closest("[data-goto]");
  if (gotoEl) switchTab(gotoEl.dataset.goto);
  if (t.dataset.wizard !== undefined) openConnectWizard();
  if (t.dataset.askQ) askQuestion(t.dataset.askQ);
  if (t.id === "ai-test" || t.id === "ai-fetch-models") testAiProvider();
  if (t.id === "ai-save") saveAiConfig();
  if (t.dataset.testChannel) testChannel(t.dataset.testChannel);
});
document.addEventListener("change", (e) => {
  const t = e.target;
  if (t.dataset.toggle) toggle(t.dataset.toggle, t.checked);
  if (t.dataset.roleFor) changeRole(t.dataset.roleFor, t.value);
  if (t.dataset.star) {
    // toggling "All (*)" enables/disables that role's per-source checkboxes live
    document.querySelectorAll(`#access-matrix input[data-role="${t.dataset.role}"][data-src]`)
      .forEach((c) => { c.disabled = t.checked; if (t.checked) c.checked = true; });
  }
});

$("login-btn").addEventListener("click", () => { if (state.user) return logout(); $("login-err").hidden = true; open("login-modal"); });
$("do-login").addEventListener("click", async () => {
  try { await login($("u").value.trim(), $("p").value); closeModals(); setAuthUI(); toast("Signed in", "ok"); loadSources(); loadOverview(); }
  catch (e) { err("login-err", e.message); }
});
$("refresh-src").addEventListener("click", loadSources);
$("enable-all").addEventListener("click", enableAll);
$("reset-demo").addEventListener("click", resetDemo);
$("ask-send").addEventListener("click", () => askQuestion());
$("ask-input").addEventListener("keydown", (e) => { if (e.key === "Enter") askQuestion(); });
$("ai-refresh").addEventListener("click", loadAiConfig);
$("int-refresh").addEventListener("click", loadIntegrations);
$("services-refresh").addEventListener("click", loadServices);
$("refresh-audit").addEventListener("click", loadAudit);
$("add-src").addEventListener("click", () => { if (!state.token) return toast("Sign in first", "err"); $("add-err").hidden = true; $("points").innerHTML = ""; addPointRow(); open("add-modal"); });
$("add-point").addEventListener("click", () => addPointRow());
$("do-create").addEventListener("click", createSource);
$("env-save").addEventListener("click", saveEnv);
$("env-filter").addEventListener("input", renderEnv);
$("add-env-row").addEventListener("click", addEnvRow);
$("backup-download").addEventListener("click", downloadBackup);
$("restore-pick").addEventListener("click", () => { if (!state.token) return toast("Sign in first", "err"); $("restore-file").click(); });
$("restore-file").addEventListener("change", (e) => restoreBackupFile(e.target.files[0]));
$("add-db").addEventListener("click", () => { if (!state.token) return toast("Sign in first", "err"); $("db-err").hidden = true; $("db-test-status").innerHTML = ""; open("db-modal"); });
$("load-demo-db").addEventListener("click", loadDemoDatabase);
$("do-db").addEventListener("click", createDatabase);
$("do-db-test").addEventListener("click", testNewConnection);
$("db-active-only").addEventListener("change", (e) => { dbActiveOnly = e.target.checked; renderDbCards(); });
$("add-cap").addEventListener("click", openCapModal);
$("do-cap").addEventListener("click", createCapability);
$("refresh-cap").addEventListener("click", loadCapabilities);
$("refresh-graphs").addEventListener("click", loadGraphs);
$("onto-validate").addEventListener("click", validateOntoTtl);
$("onto-upload").addEventListener("click", uploadOntoTtl);
$("onto-run").addEventListener("click", runSparql);
$("doc-upload")?.addEventListener("click", uploadDocument);
$("fp-upload")?.addEventListener("click", uploadFloorPlan);
$("bldg-save").addEventListener("click", saveBuildingConfig);
$("sim-rebuild").addEventListener("click", rebuildSim);
$("sim-refresh").addEventListener("click", loadSimStatus);
$("refresh-health").addEventListener("click", loadHealth);
$("health-auto").addEventListener("change", (e) => toggleHealthAuto(e.target.checked));
$("theme-btn").addEventListener("click", toggleTheme);
$("help-btn").addEventListener("click", () => switchTab("guide"));
$("add-user").addEventListener("click", () => {
  if (!state.token) return toast("Sign in first", "err");
  $("user-err").hidden = true;
  $("nu-role").innerHTML = (allRoles.length ? allRoles : ["readonly", "occupant", "operator", "analyst", "facility_manager", "admin"]).map((r) => `<option>${r}</option>`).join("");
  open("user-modal");
});
$("do-user").addEventListener("click", createUser);
$("do-pw").addEventListener("click", submitPassword);
initPasswordToggles();  // render eye icons on load
$("pw-new").addEventListener("keydown", (e) => { if (e.key === "Enter") submitPassword(); });
$("save-access").addEventListener("click", saveRoleAccess);
$("add-sensor-point").addEventListener("click", () => addSensorPointRow());
$("do-sensors").addEventListener("click", submitSensors);
// Guided "Connect a data source" wizard
$("wiz-open").addEventListener("click", openConnectWizard);
$("wiz-next-1").addEventListener("click", wizStep1Next);
$("wiz-back-2").addEventListener("click", () => wizGoto(1));
$("wiz-next-2").addEventListener("click", wizStep2Next);
$("wiz-add-point").addEventListener("click", () => addSensorPointRow({}, "wiz-points"));
$("wiz-again").addEventListener("click", () => {
  $("wiz-points").innerHTML = "";
  addSensorPointRow({}, "wiz-points");
  if ($("wiz-csv-text")) $("wiz-csv-text").value = "";
  $("wiz-err-2").hidden = true;
  wizGoto(2);
});
$("wiz-finish").addEventListener("click", () => loadDatabases());
document.querySelectorAll('input[name="wiz-src"]').forEach((r) => r.addEventListener("change", wizSyncSrc));
$("apply-close").addEventListener("click", hideNotice);
// apply-notice buttons (delegated): Copy the recreate command / Restart service
document.addEventListener("click", (e) => {
  const t = e.target;
  if (t.dataset && t.dataset.copy !== undefined) { navigator.clipboard?.writeText(RECREATE_CMD); toast("Copied recreate command", "ok"); }
  if (t.dataset && t.dataset.restart !== undefined) restartOrchestrator();
});

closeModals(); // clear any stale / bfcache-restored open modal on first paint
setAuthUI();
loadSources();
renderAskSuggestions();
loadOverview();
ensureAdminSession(); // validate the stored session; prompt admin sign-in if absent/expired
// A page restored from the back/forward cache keeps its old DOM (a modal may be open) and a
// possibly-expired token — re-sync on show so an operator never lands on a stale modal.
window.addEventListener("pageshow", (e) => { if (e.persisted) { closeModals(); ensureAdminSession(); } });
