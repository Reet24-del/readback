import { Call } from "./call.js";

const $ = (s) => document.querySelector(s);
const state = { templates: {}, customers: [], demo: [], campaignRows: [], campaignSource: "", voices: [], passcode: "", call: null };

// ---------------------------------------------------------------- API

try { state.passcode = sessionStorage.getItem("readback-passcode") || ""; } catch {}

async function api(path, opts = {}) {
  const headers = { "x-passcode": state.passcode, ...(opts.headers || {}) };
  if (opts.body && !(opts.body instanceof FormData)) headers["content-type"] = "application/json";
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) { showGate(); throw new Error("Enter the demo passcode first."); }
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail; } catch {}
    throw new Error(typeof detail === "string" && detail ? detail : `Request failed (${res.status}).`);
  }
  return (res.headers.get("content-type") || "").includes("json") ? res.json() : res.text();
}
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body) });

// ---------------------------------------------------------------- small helpers

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function highlight(text, parts) {
  // parts: [{ str, cls }] in reading order; wrap each first occurrence after the previous one.
  let html = "", at = 0;
  for (const { str, cls } of parts) {
    const i = str ? text.indexOf(str, at) : -1;
    if (i < 0) continue;
    html += esc(text.slice(at, i)) + `<mark class="${cls}">${esc(str)}</mark>`;
    at = i + str.length;
  }
  return html + esc(text.slice(at));
}

const PILL = {
  misread: ["bad", "Misread"], unclear: ["warn", "Check by ear"], correct: ["good", "Correct"], not_checked: ["idle", "No values checked"],
  DO_NOT_SPEAK: ["bad", "Held back"], SPOKEN: ["good", "Verified"], SPOKEN_AFTER_RETRY: ["good", "Verified on retry"],
};
function pill(el, key) {
  const [cls, text] = PILL[key] || ["idle", key];
  el.className = `pill ${cls}`;
  el.textContent = text;
}
function pillHtml(key) {
  const [cls, text] = PILL[key] || ["idle", key];
  return `<span class="pill ${cls}">${esc(text)}</span>`;
}

function checksHtml(checks) {
  if (!checks.length) return `<li><span class="mark-warn">—</span><span>No supported values detected. This reply was not verified.</span></li>`;
  return checks.map((c) => {
    const [m, cls] = c.status === "PASS" ? ["✓", "mark-ok"] : c.status === "FAIL" ? ["✗", "mark-bad"] : ["?", "mark-warn"];
    return `<li><span class="${cls}" aria-label="${esc(c.status)}">${m}</span><span><span class="val">${esc(c.value)}</span><span class="reason">${esc(c.reason)}</span></span></li>`;
  }).join("");
}

let player = null, playerBtn = null;
function stopAudio() {
  if (player) player.pause();
  if (playerBtn) playerBtn.textContent = playerBtn.dataset.label || "▶ Play";
  player = playerBtn = null;
}
async function playAudio(btn, url) {
  if (playerBtn === btn) { stopAudio(); return; }
  stopAudio();
  btn.dataset.label = btn.dataset.label || btn.textContent;
  try {
    const res = await fetch(url, { headers: { "x-passcode": state.passcode } });
    if (!res.ok) throw new Error();
    player = new Audio(URL.createObjectURL(await res.blob()));
  } catch { btn.textContent = "Audio unavailable"; return; }
  playerBtn = btn;
  btn.textContent = "■ Stop";
  player.onended = stopAudio;
  player.play().catch(stopAudio);
}
document.addEventListener("click", (e) => {
  const btn = e.target.closest("button.play");
  if (btn && btn.dataset.audio) playAudio(btn, btn.dataset.audio);
});

function fillSelect(sel, items, valueOf, labelOf, selected) {
  sel.innerHTML = items.map((it) => `<option value="${esc(valueOf(it))}">${esc(labelOf(it))}</option>`).join("");
  if (selected !== undefined) sel.value = selected;
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function showError(el, err) {
  el.textContent = err ? String(err.message || err) : "";
  el.hidden = !err;
}

// ---------------------------------------------------------------- tabs

const TABS = ["compose", "campaign", "call", "evidence"];
function selectTab(name) {
  if (!TABS.includes(name)) name = "compose";
  for (const t of TABS) {
    $(`#t-${t}`).setAttribute("aria-selected", String(t === name));
    $(`#tab-${t}`).hidden = t !== name;
  }
  if (name === "evidence") loadEvidence();
  try { history.replaceState(null, "", `#${name}`); } catch {}
}
for (const t of TABS) $(`#t-${t}`).addEventListener("click", () => selectTab(t));

// ---------------------------------------------------------------- compose

const compose = { text: "", preview: null };

function selectedRow(sel) {
  return state.customers.find((c) => c.id === sel.value) || state.customers[0];
}

function renderFields() {
  const row = selectedRow($("#c-customer"));
  const used = new Set(($("#c-text").value.match(/{(\w+)}/g) || []).map((p) => p.slice(1, -1)));
  $("#c-fields").innerHTML = Object.entries(row)
    .filter(([k]) => used.has(k))
    .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
}

const updatePreview = debounce(async () => {
  renderFields();
  showError($("#c-error"), null);
  $("#c-result").hidden = true;
  try {
    const p = await post("/api/preview", { template: $("#c-text").value, row: selectedRow($("#c-customer")) });
    compose.preview = p;
    $("#c-message").innerHTML = highlight(p.text, p.values.map((v) => ({ str: v.written, cls: v.risk ? "risk" : "" })));
    $("#c-spoken").innerHTML = highlight(p.spoken_text, p.values.map((v) => ({ str: v.safespeak, cls: "" })));
    $("#c-values").innerHTML = p.values.length
      ? p.values.map((v) => `<li><span class="written">${esc(v.written)}</span><span>${v.risk
          ? `<span class="pill bad">${esc(v.risk.bug)}</span> <span class="why">${esc(v.risk.why)}</span>`
          : `<span class="pill good">Low risk</span>`}<br><span class="why">SafeSpeak: “${esc(v.safespeak)}”</span></span></li>`).join("")
      : `<li><span class="why">No amounts, codes or dates in this message.</span></li>`;
    $("#c-alerts").innerHTML = p.alerts.filter((a) => a.severity === "critical")
      .map((a) => `<p class="alert"><strong>Hidden content:</strong> ${esc(a.detail)}</p>`).join("");
  } catch (err) {
    compose.preview = null;
    $("#c-message").textContent = "";
    $("#c-spoken").textContent = "";
    $("#c-values").innerHTML = "";
    showError($("#c-error"), err);
  }
}, 250);

async function runCheck() {
  if (!compose.preview) return;
  const btn = $("#c-check");
  btn.disabled = true;
  btn.textContent = "Checking… (about 15 s)";
  showError($("#c-error"), null);
  try {
    const r = await post("/api/check", { text: compose.preview.text, voice: $("#c-voice").value });
    pill($("#c-plain-pill"), r.plain.verdict);
    pill($("#c-safe-pill"), r.safespeak.status === "DO_NOT_SPEAK" ? "DO_NOT_SPEAK" : r.safespeak.verdict);
    $("#c-plain-heard").textContent = r.plain.heard;
    $("#c-safe-heard").textContent = r.safespeak.heard;
    $("#c-plain-checks").innerHTML = checksHtml(r.plain.checks);
    $("#c-safe-checks").innerHTML = checksHtml(r.safespeak.checks);
    $("#c-plain-play").dataset.audio = r.plain.audio;
    $("#c-safe-play").dataset.audio = r.safespeak.audio;
    $("#c-result").hidden = false;
    $("#c-result").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    showError($("#c-error"), err);
  } finally {
    btn.disabled = false;
    btn.textContent = "Check by voice";
  }
}

$("#c-template").addEventListener("change", () => { $("#c-text").value = state.templates[$("#c-template").value].text; updatePreview(); });
$("#c-text").addEventListener("input", updatePreview);
$("#c-customer").addEventListener("change", updatePreview);
$("#c-check").addEventListener("click", runCheck);

// ---------------------------------------------------------------- campaign

function setCampaignRows(rows, source) {
  state.campaignRows = rows;
  $("#k-source").textContent = source;
  $("#k-demo").hidden = rows === state.demo;
}

$("#k-file").addEventListener("change", async () => {
  const file = $("#k-file").files[0];
  if (!file) return;
  showError($("#k-error"), null);
  const form = new FormData();
  form.append("file", file);
  try {
    const rows = await api("/api/customers/upload", { method: "POST", body: form });
    setCampaignRows(rows, `${rows.length} customers from ${file.name}`);
  } catch (err) {
    showError($("#k-error"), err);
  }
  $("#k-file").value = "";
});
$("#k-demo").addEventListener("click", () => setCampaignRows(state.demo, `${state.demo.length} demo customers`));

function campaignRowHtml(r) {
  const chk = r.check;
  const audio = (url, label) => (url ? `<button class="play mini" data-audio="${esc(url)}">${label}</button>` : "");
  let plain = `<span class="pill idle">${r.error ? "—" : "Checking…"}</span>`, safe = plain;
  if (chk) {
    const fails = chk.plain.checks.filter((c) => c.status === "FAIL");
    plain = pillHtml(chk.plain.verdict)
      + (fails.length ? `<ul class="misreads">${fails.map((f) => `<li><b>${esc(f.value)}</b> ${esc(f.reason)}</li>`).join("")}</ul>` : "")
      + audio(chk.plain.audio, "▶ Plain");
    safe = pillHtml(chk.safespeak.status === "DO_NOT_SPEAK" ? "DO_NOT_SPEAK" : chk.safespeak.verdict) + "<br>" + audio(chk.safespeak.audio, "▶ SafeSpeak");
  }
  const act = r.action.startsWith("Ready") ? "good" : r.action.startsWith("Held") || r.action.startsWith("Review") ? "warn" : r.action === "Error" ? "bad" : "idle";
  return `<tr>
    <td><div class="who">${esc(r.name || "(no name)")}</div><div class="text">${esc(r.text || r.error || "")}</div></td>
    <td>${plain}</td><td>${safe}</td>
    <td><span class="pill ${act}">${esc(r.action)}</span>${r.sms ? `<p>SMS: <strong>${esc(r.sms.status.replaceAll("_", " "))}</strong></p>${r.sms.error ? `<p class="error">${esc(r.sms.error)}</p>` : ""}` : "<p>SMS not requested</p>"}</td></tr>`;
}

function renderSummary(s) {
  if (!s.checked && !s.errors) { $("#k-summary").hidden = true; return; }
  $("#k-summary").innerHTML = `
    <div class="bad"><strong>${s.plain_misread} / ${s.checked}</strong><span>calls plain TTS would misread</span></div>
    <div class="bad"><strong>${s.plain_values_misread}</strong><span>values it would get wrong</span></div>
    <div class="good"><strong>${s.ready}</strong><span>ready to call with SafeSpeak</span></div>
    <div class="warn"><strong>${s.held_back + (s.review || 0)}</strong><span>${s.held_back} held back; ${s.review || 0} need review</span></div>
    <div><strong>${s.sms_delivered || 0}</strong><span>SMS delivered; ${s.sms_pending || 0} awaiting delivery confirmation, ${s.sms_failed || 0} failed or not sent</span></div>`;
  $("#k-summary").hidden = false;
}

// Retain the same request ID after a network failure or a page reload. A repeat
// click for the same input returns the existing campaign instead of sending again.
async function campaignRequestId(payload) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(payload)));
  const fingerprint = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
  let previous = state.campaignRequest;
  try { previous ||= JSON.parse(sessionStorage.getItem("readback-campaign-request")); } catch {}
  if (!previous || previous.fingerprint !== fingerprint) {
    previous = { fingerprint, id: crypto.randomUUID() };
  }
  state.campaignRequest = previous;
  try { sessionStorage.setItem("readback-campaign-request", JSON.stringify(previous)); } catch {}
  return previous.id;
}

async function runCampaign() {
  const btn = $("#k-run");
  btn.disabled = true;
  $("#k-report").hidden = true;
  $("#k-refresh").hidden = true;
  showError($("#k-error"), null);
  try {
    const payload = {
      template: state.templates[$("#k-template").value].text,
      rows: state.campaignRows,
      voice: $("#k-voice").value,
      send_sms: $("#k-sms").checked,
    };
    let view = await post("/api/campaigns", { ...payload, request_id: await campaignRequestId(payload) });
    $("#k-progress").hidden = false;
    $("#k-table").hidden = false;
    while (true) {
      $("#k-bar").style.width = `${(100 * view.done) / view.total}%`;
      $("#k-count").textContent = `${view.done} of ${view.total} checked`;
      $("#k-table tbody").innerHTML = view.results.map(campaignRowHtml).join("");
      renderSummary(view.summary);
      if (view.status !== "running") {
        if (view.status === "interrupted") showError($("#k-error"), "This campaign was interrupted by a server restart. It will not resend automatically; review its report and Twilio before creating another campaign.");
        break;
      }
      await new Promise((r) => setTimeout(r, 1200));
      view = await api(`/api/campaigns/${view.id}`);
    }
    $("#k-report").dataset.id = view.id;
    $("#k-report").hidden = false;
    $("#k-refresh").hidden = false;
  } catch (err) {
    showError($("#k-error"), err);
  } finally {
    btn.disabled = false;
  }
}
$("#k-run").addEventListener("click", runCampaign);
$("#k-refresh").addEventListener("click", async () => {
  try {
    const view = await api(`/api/campaigns/${$("#k-report").dataset.id}`);
    $("#k-table tbody").innerHTML = view.results.map(campaignRowHtml).join("");
    renderSummary(view.summary);
  } catch (err) { showError($("#k-error"), err); }
});
$("#k-report").addEventListener("click", async (e) => {
  e.preventDefault();
  try {
    const csv = await api(`/api/campaigns/${$("#k-report").dataset.id}/report.csv`);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "readback-campaign.csv";
    a.click();
  } catch (err) {
    showError($("#k-error"), err);
  }
});

// ---------------------------------------------------------------- live call

function logItem(role, html) {
  const log = $("#v-log");
  log.querySelector(".empty")?.remove();
  const li = document.createElement("li");
  li.className = `msg-${role}`;
  li.innerHTML = `<span class="who">${role === "agent" ? "Agent" : "Customer"}</span>${html}`;
  log.appendChild(li);
  li.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return li;
}

function setCallStatus(text, kind) {
  $("#v-status").textContent = text;
  $("#v-status").className = `status ${kind === "live" ? "live" : ""}`;
}

function setCallButtons(live) {
  $("#v-start").hidden = live;
  $("#v-stop").hidden = !live;
  for (const id of ["#v-customer", "#v-template", "#v-voice", "#v-safe"]) $(id).disabled = live;
}

$("#v-safe").addEventListener("change", () => { $("#v-safe-state").textContent = $("#v-safe").checked ? "on" : "off"; });

async function startCall() {
  if (!navigator.mediaDevices?.getUserMedia) {
    setCallStatus("This browser can't use the microphone here. Open the app in Chrome at http://localhost.");
    return;
  }
  const row = selectedRow($("#v-customer"));
  const templateId = $("#v-template").value;
  const safespeak = $("#v-safe").checked;
  $("#v-log").innerHTML = "";
  let lastAgent = null, config;
  try {
    config = await post("/api/call/config", { template: state.templates[templateId].text, template_id: templateId, row, safespeak, voice: $("#v-voice").value });
  } catch (err) { setCallStatus(String(err.message || err)); return; }

  const note = (li, html) => {
    const old = li.querySelector(".check-note");
    const el = Object.assign(document.createElement("div"), { className: "check-note" });
    el.innerHTML = html;
    old ? old.replaceWith(el) : li.appendChild(el);
  };

  const call = new Call({
    getToken: async () => (await api("/api/call/token")).token,
    runTool: async (name) => (await post("/api/call/tool", { name, row, safespeak })).result,
    onStatus: (text, kind) => { setCallStatus(text, kind); if (kind === "ended") setCallButtons(false); },
    onError: (text) => setCallStatus(text),
    onTranscript: (role, text) => {
      const li = logItem(role, `<span>${esc(text)}</span>`);
      if (role === "agent") lastAgent = li;
    },
    // Every agent reply: compare what it meant to say (its text) with what the caller heard (its audio).
    onReplyAudio: async ({ audio, text, isGreeting, interrupted }) => {
      const li = lastAgent || logItem("agent", `<span>${esc(text)}</span>`);
      if (interrupted || !audio) { if (isGreeting) note(li, `<span class="note">Interrupted before the end, so it wasn't checked.</span>`); return; }
      note(li, `<span class="note">Checking what the caller heard…</span>`);
      const body = isGreeting
        ? { audio, rendered: config.rendered, greeting: config.greeting, safespeak }
        : { audio, rendered: text, greeting: text, safespeak: false };
      try {
        const r = await post("/api/call/check", body);
        note(li, `<span class="note">What the caller heard: ${pillHtml(r.verdict)}</span><ul class="checks">${checksHtml(r.checks)}</ul>`);
      } catch (err) {
        note(li, `<span class="note">Couldn't check this reply: ${esc(err.message || err)}</span>`);
      }
    },
  });
  state.call = call;
  setCallButtons(true);
  try {
    await call.start(config.session);
  } catch (err) {
    setCallStatus(err?.name === "NotAllowedError" ? "Microphone blocked. Allow it for this site, or open http://localhost:8000 in Chrome." : String(err.message || err));
    await call.hangup();
    setCallButtons(false);
  }
}

$("#v-start").addEventListener("click", startCall);
$("#v-stop").addEventListener("click", async () => {
  await state.call?.hangup();
  setCallStatus("Call ended.");
  setCallButtons(false);
});

// ---------------------------------------------------------------- evidence

const BUGS = [
  ["BUG-001", "Indian digit grouping is misread on every voice", "₹10,00,000 → “ten zero rupees” · ₹1,50,000 → “one fifty thousand rupees”"],
  ["BUG-002", "OTPs, PNRs, pincodes and phone numbers are read as amounts", "OTP 482910 → “four hundred eighty two thousand nine hundred ten”"],
  ["BUG-003", "DD/MM dates are read in US order", "03/04/2026 → “March fourth”"],
  ["BUG-004", "Letter runs in codes may be pronounced as words (needs ear check)", "IFSC WYXK0992832 → “Wix zero nine…”"],
  ["BUG-005", "Hidden characters make the voice and the screen disagree", "screen ₹500 → voice “five” (right-to-left override)"],
];
let evidenceLoaded = false;
async function loadEvidence() {
  if (evidenceLoaded) return;
  try {
    const e = await api("/api/evidence");
    evidenceLoaded = true;
    const pct = (x) => `${Math.round(x * 100)}%`;
    $("#e-scope").textContent = `${e.cases} hard Indian cases × ${e.voices.length} voices (${e.voices.join(", ")}) = ${e.results} results, each scored on a word-for-word transcript of the audio. These misreads hit text the voice reads word for word, like an outbound call's opening line. The agent's own AI spells out values it looks up, but it copies digits it has already seen: a raw “₹10,00,000” in the opening line comes back as “ten zero rupees” in its follow-up answers too.`;
    $("#e-scope").textContent += " Historical snapshot: these measurements predate the stricter field alignment and uncertain-result handling and have not been rerun for this revision.";
    $("#e-metrics").innerHTML = `
      <div class="bad"><strong>${pct(e.before)}</strong><span>correct with plain TTS</span></div>
      <div class="good"><strong>${pct(e.after)}</strong><span>correct or safely held back with SafeSpeak</span></div>
      <div class="bad"><strong>${e.misreads_before} → ${e.misreads_after}</strong><span>critical values misread</span></div>
      <div><strong>${e.hidden}</strong><span>misreads a formatted transcript would hide</span></div>`;
    $("#e-bars").innerHTML = Object.entries(e.categories)
      .sort((a, b) => a[1].plain - b[1].plain)
      .map(([name, c]) => `<div class="bar-row"><span class="name">${esc(name)}</span>
        <span class="track2" role="img" aria-label="${esc(name)}: ${pct(c.plain)} plain, ${pct(c.safespeak)} with SafeSpeak"><i class="b" style="width:${c.plain * 100}%"></i><i class="a" style="width:${c.safespeak * 100}%"></i></span>
        <span class="nums">${pct(c.plain)}→${pct(c.safespeak)}</span></div>`).join("");
  } catch (err) {
    $("#e-metrics").innerHTML = `<p class="error">${esc(err.message || err)}</p>`;
  }
  $("#e-bugs").innerHTML = BUGS.map(([id, title, ex]) => `<li><span class="id">${id}</span><div><strong>${esc(title)}</strong><div class="ex">${esc(ex)}</div></div></li>`).join("");
}

// ---------------------------------------------------------------- passcode gate & start-up

function showGate() { $("#gate").hidden = false; $("#gate-code").focus(); }
$("#gate-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  state.passcode = $("#gate-code").value;
  try { sessionStorage.setItem("readback-passcode", state.passcode); } catch {}
  try {
    await api("/api/templates");
    $("#gate").hidden = true;
    await init();
  } catch {
    $("#gate-error").textContent = "That passcode didn't work.";
    $("#gate-error").hidden = false;
  }
});

async function init() {
  const [templates, customers, cfg] = await Promise.all([api("/api/templates"), api("/api/customers"), api("/api/config")]);
  state.templates = templates;
  state.customers = state.demo = customers;
  state.voices = cfg.voices;
  $("#k-sms").disabled = !cfg.sms_available;
  if (!cfg.sms_available) $("#k-sms").checked = false;
  $("#k-sms-status").textContent = cfg.sms_available ? "Twilio configured. Enabling this sends real SMS for held messages." : "SMS unavailable. Configure Twilio and a public delivery callback URL on the server.";
  const tplIds = Object.keys(templates);
  for (const sel of ["#c-template", "#k-template", "#v-template"]) fillSelect($(sel), tplIds, (id) => id, (id) => templates[id].label, "emi");
  for (const sel of ["#c-customer", "#v-customer"]) fillSelect($(sel), customers, (c) => c.id, (c) => c.name, "1");
  for (const sel of ["#c-voice", "#k-voice", "#v-voice"]) fillSelect($(sel), cfg.voices, (v) => v, (v) => v, cfg.default_voice);
  $("#c-text").value = templates.emi.text;
  setCampaignRows(customers, `${customers.length} demo customers`);
  updatePreview();
  selectTab(location.hash.slice(1));
}

(async () => {
  const cfg = await fetch("/api/config").then((r) => r.json()).catch(() => ({}));
  if (cfg.passcode_required && !state.passcode) showGate();
  else init().catch((err) => { document.querySelector("main").insertAdjacentHTML("afterbegin", `<p class="error">${esc(err.message || err)}</p>`); });
})();
