/* Voice Flow Agent workbench. Vanilla JS, no build step. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const STEPS = ["FETCH_SHEETS", "FILTER_LEADS", "SEND_SMS", "WAIT", "RETELL_CALL", "UPDATE_SHEET"];
const fmt$ = (n) => "$" + Number(n || 0).toFixed(3);
const hhmmss = (iso) => (iso || "").slice(11, 19);
const headers = () => (localStorage.demoKey ? { "X-Demo-Key": localStorage.demoKey } : {});
const jsonHeaders = () => ({ "Content-Type": "application/json", ...headers() });

/* ---------- status / budget ---------- */
async function refreshStatus() {
  const m = await fetch("/mode", { headers: headers() }).then((r) => r.json());
  $("#mode-badge").textContent = m.mode;
  $("#mode-badge").dataset.mode = m.mode;
  $("#sheet-badge").textContent = "sheet=" + m.sheet;
  $("#provider-badge").textContent = "provider=" + m.provider;
  $("#i-mode").textContent = m.mode;
  $("#i-tel").textContent = m.mode === "LIVE" ? "twilio + retell" : "mock";
  $("#i-agent").textContent = m.retell_agent_id;
  $("#keyind").textContent = localStorage.demoKey ? "key ●" : "key ○";
  $("#keyind").classList.toggle("set", !!localStorage.demoKey);
  state.waitSeconds = m.wait_seconds;
}
async function refreshBudget() {
  const b = await fetch("/budget").then((r) => r.json());
  $("#budget-remaining").textContent = fmt$(b.remaining);
}
async function refreshLeads() {
  const pending = $("#pending").checked;
  const d = await fetch("/leads?pending=" + pending).then((r) => r.json());
  $("#count").textContent = d.count + (pending ? " pending" : " total");
  const tb = $("#leads tbody");
  tb.innerHTML = "";
  for (const l of d.leads) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${l.row}</td><td>${l.phone}</td><td>${l.first_name}</td><td>${l.call_made ? "✓ true" : "○"}</td>`;
    tb.appendChild(tr);
  }
}
async function loadTemplate() {
  const c = await fetch("/config").then((r) => r.json());
  $("#tmpl").textContent = c.sms_template;
}

/* ---------- lanes / trace ---------- */
const state = { lanes: [], waitSeconds: 5, startedAt: 0, timer: null, events: 0 };

function laneTemplate(i) {
  const d = document.createElement("div");
  d.className = "lane";
  d.dataset.lane = i;
  d.innerHTML = `<div class="lane-head mono"><span class="lane-id">—</span><span class="lane-status" data-state="idle">○ IDLE</span></div><ol class="timeline"></ol>`;
  return d;
}
function setLanes(n) {
  const wrap = $("#lanes");
  wrap.innerHTML = "";
  wrap.dataset.count = n;
  state.lanes = [];
  for (let i = 0; i < n; i++) {
    wrap.appendChild(laneTemplate(i));
    state.lanes.push({ el: wrap.lastElementChild, nodes: {}, cost: 0, es: null });
  }
  $$("#pipeline li").forEach((li) => (li.dataset.state = ""));
}
function setLaneStatus(lane, st, label) {
  const s = $(".lane-status", lane.el);
  s.dataset.state = st;
  s.textContent = label;
}
function summarize(ev) {
  const d = ev.data || {};
  switch (ev.type) {
    case "step_start":
      if (ev.step === "WAIT") return `wait ${d.seconds}s before call`;
      if (ev.step === "SEND_SMS" || ev.step === "RETELL_CALL") return `${d.lead} · ${d.to} · ${d.provider}`;
      return d.sheet ? `sheet=${d.sheet}` : d.rule || "";
    case "step_payload":
      if (ev.step === "FETCH_SHEETS") return `${d.rows.length} rows`;
      if (ev.step === "FILTER_LEADS") return `${d.pending.length} pending · ${d.skipped.length} skipped`;
      if (ev.step === "SEND_SMS") return `sid ${d.sms.sid}`;
      if (ev.step === "RETELL_CALL") return `call_id ${d.response.call_id}`;
      if (ev.step === "UPDATE_SHEET") return `Call Made=true · ${d.write["Date & Time"]}`;
      return "";
    case "step_complete":
      if (ev.step === "SEND_SMS") return `${d.status} · ${fmt$(d.cost_usd)}`;
      if (ev.step === "RETELL_CALL") return `${d.call_status} · ${fmt$(d.cost_usd)}`;
      if (ev.step === "FETCH_SHEETS") return `${d.rows_fetched} rows fetched`;
      if (ev.step === "FILTER_LEADS") return `${d.pending} pending`;
      if (ev.step === "WAIT") return `waited ${d.waited_s}s`;
      return "done";
    case "step_error": return d.error;
    case "run_finished": return `${d.status} · ${d.leads_processed} lead(s) · ${fmt$(d.cost_usd)} · ${d.duration_s}s`;
  }
  return "";
}
function nodeFor(lane, ev) {
  const key = ev.type === "run_finished" ? "RUN" : `${ev.step}:${ev.data.row || 0}`;
  if (lane.nodes[key]) return lane.nodes[key];
  const li = document.createElement("li");
  li.className = "node mono";
  li.dataset.step = ev.step || "RUN";
  li.dataset.state = "active";
  li.setAttribute("aria-expanded", "false");
  li.innerHTML = `<div class="node-head"><span class="caret">▸</span><span class="step">${ev.step || "RUN_FINISHED"}</span><span class="sum"></span><span class="ts"></span></div><pre class="payload"></pre>`;
  $(".node-head", li).addEventListener("click", () => {
    li.setAttribute("aria-expanded", li.getAttribute("aria-expanded") === "true" ? "false" : "true");
  });
  $(".timeline", lane.el).appendChild(li);
  lane.nodes[key] = li;
  return li;
}
function applyEvent(lane, ev, primary) {
  state.events++;
  const node = nodeFor(lane, ev);
  const sum = summarize(ev);
  if (sum) $(".sum", node).textContent = sum;
  $(".ts", node).textContent = hhmmss(ev.timestamp);
  const payloads = node._payloads || (node._payloads = []);
  payloads.push({ type: ev.type, seq: ev.seq, timestamp: ev.timestamp, ...ev.data });
  $(".payload", node).textContent = JSON.stringify(payloads, null, 2);
  const pipe = ev.step && $(`#pipeline li[data-step="${ev.step}"]`);

  if (ev.type === "step_start") {
    node.dataset.state = "active";
    if (primary && pipe) pipe.dataset.state = "active";
    if (ev.step === "WAIT") {
      node.insertAdjacentHTML("beforeend", `<div class="wait-bar"><i></i></div>`);
      if (primary) $("#i-wait").textContent = `0 / ${ev.data.seconds}s`;
    }
    if (primary && ev.step === "SEND_SMS") { $("#i-sms").textContent = "● SENDING"; $("#i-lead").textContent = `${ev.data.lead} · ${ev.data.to}`; }
    if (primary && ev.step === "RETELL_CALL") $("#i-call").textContent = "● DIALING";
    if (primary && ev.step === "UPDATE_SHEET") $("#i-sheet").textContent = "● WRITING";
    if (ev.step === "SEND_SMS") callbox.onSms(ev);
  } else if (ev.type === "step_payload") {
    if (ev.step === "WAIT") {
      const bar = $(".wait-bar i", node);
      if (bar) bar.style.width = (100 * ev.data.elapsed_s / ev.data.total_s) + "%";
      if (primary) $("#i-wait").textContent = `${ev.data.elapsed_s} / ${ev.data.total_s}s`;
    }
    if (ev.step === "SEND_SMS") callbox.onSmsPayload(ev);
  } else if (ev.type === "step_complete") {
    node.dataset.state = "done";
    if (primary && pipe) pipe.dataset.state = "done";
    if (ev.data.cost_usd) lane.cost += ev.data.cost_usd;
    if (primary) {
      if (ev.step === "SEND_SMS") $("#i-sms").textContent = `✓ ${ev.data.status.toUpperCase()} ${ev.data.sid.slice(0, 14)}…`;
      if (ev.step === "RETELL_CALL") $("#i-call").textContent = `✓ ${ev.data.call_status.toUpperCase()}`;
      if (ev.step === "UPDATE_SHEET") $("#i-sheet").textContent = `✓ ${ev.data.date_time}`;
      $("#i-cost").textContent = fmt$(state.lanes.reduce((a, l) => a + l.cost, 0));
    }
    if (ev.step === "RETELL_CALL") callbox.onCall(ev);
    if (ev.step === "UPDATE_SHEET") callbox.onSheet(ev);
  } else if (ev.type === "step_error") {
    node.dataset.state = "error";
    if (primary && pipe) pipe.dataset.state = "error";
  } else if (ev.type === "run_finished") {
    node.classList.add("final");
    node.dataset.state = ev.data.status === "completed" ? "done" : "error";
    node.dataset.status = ev.data.status;
    setLaneStatus(lane, ev.data.status === "completed" ? "complete" : ev.data.status,
      ev.data.status === "completed" ? "✓ PASSED" : "✕ " + ev.data.status.toUpperCase());
    if (ev.data.status !== "completed") callbox.onFail(ev);
  }
  if (primary) $("#i-events").textContent = state.events;
  $(".timeline", lane.el).parentElement.scrollTop = 1e9;
}
function watch(runId, lane, primary) {
  $(".lane-id", lane.el).textContent = runId;
  setLaneStatus(lane, "running", "● ACTIVE");
  if (primary) { $("#i-run").textContent = runId; $("#trace-sub").textContent = "● ACTIVE"; $("#trace-sub").className = "accent"; }
  const es = new EventSource(`/runs/${runId}/events`);
  lane.es = es;
  const handle = (m) => {
    const ev = JSON.parse(m.data);
    applyEvent(lane, ev, primary);
    if (ev.type === "run_finished") { es.close(); onRunDone(); }
  };
  ["step_start", "step_payload", "step_complete", "step_error", "run_finished"].forEach((t) => es.addEventListener(t, handle));
  es.onerror = () => { es.close(); };
}
function onRunDone() {
  if (state.lanes.every((l) => !l.es || l.es.readyState === 2)) {
    clearInterval(state.timer);
    const allOk = state.lanes.every((l) => $(".lane-status", l.el).dataset.state === "complete");
    $("#trace-sub").textContent = allOk ? "✓ PASSED" : "✕ FINISHED";
    $("#trace-sub").className = allOk ? "ok" : "accent";
    $("#trace-sub").style.color = allOk ? "var(--ok)" : "";
    refreshBudget(); refreshLeads();
    $("#run").disabled = $("#run-batch").disabled = false;
  }
}
function beginRun() {
  state.startedAt = Date.now(); state.events = 0;
  ["#i-sms", "#i-call", "#i-sheet"].forEach((s) => ($(s).textContent = "○ IDLE"));
  $("#i-wait").textContent = "—"; $("#i-cost").textContent = "$0.000"; $("#i-lead").textContent = "—";
  clearInterval(state.timer);
  state.timer = setInterval(() => ($("#i-elapsed").textContent = ((Date.now() - state.startedAt) / 1000).toFixed(1) + "s"), 100);
  $("#run").disabled = $("#run-batch").disabled = true;
  $("#workbench").scrollIntoView({ behavior: "smooth", block: "start" });
}
async function runSingle(body = {}) {
  beginRun(); setLanes(1);
  const r = await fetch("/runs", { method: "POST", headers: jsonHeaders(), body: JSON.stringify(body) });
  if (!r.ok) { setLaneStatus(state.lanes[0], "failed", "✕ " + (await r.text())); $("#run").disabled = $("#run-batch").disabled = false; return null; }
  const d = await r.json();
  watch(d.run_id, state.lanes[0], true);
  return d;
}
async function runBatch() {
  beginRun(); setLanes(3);
  const r = await fetch("/runs/batch", { method: "POST", headers: jsonHeaders(), body: JSON.stringify({ count: 3 }) });
  if (!r.ok) {
    const msg = (await r.json()).detail || r.statusText;
    state.lanes.forEach((l) => setLaneStatus(l, "failed", "✕ " + msg));
    clearInterval(state.timer); $("#run").disabled = $("#run-batch").disabled = false; return;
  }
  const d = await r.json();
  d.run_ids.forEach((id, i) => watch(id, state.lanes[i], i === 0));
}

/* ---------- callbox (get a call) ---------- */
const callbox = {
  row: null,
  stage(n) { $("#callbox").dataset.stage = n; $$("#callbox .stage").forEach((s) => s.classList.toggle("hidden", s.dataset.stage !== String(n))); },
  onSms(ev) { if (ev.data.row === this.row) { this.stage(2); $("#s2-row").textContent = ev.data.row; $("#s2-status").textContent = "● SEND_SMS"; } },
  onSmsPayload(ev) { if (ev.data.row === this.row) { $("#s2-sms").textContent = ev.data.sms.body; $("#s2-status").textContent = "● WAIT"; } },
  onCall(ev) { if (ev.data.row === this.row) { $("#s3-call").textContent = ev.data.call_id; $("#s3-status").textContent = "● " + ev.data.call_status.toUpperCase(); $("#s2-status").textContent = "● RETELL_CALL"; } },
  onSheet(ev) { if (ev.data.row === this.row) { this.stage(3); $("#s3-sheet").textContent = `row ${ev.data.row} · Call Made=true`; } },
  onFail(ev) { if (this.row !== null) { $("#f-err").textContent = "run " + ev.data.status + (ev.data.error ? ": " + ev.data.error : ""); $("#f-err").classList.remove("hidden"); this.stage(1); } },
};
function validateForm() {
  const ok = $("#f-name").value.trim().length > 0 && $("#f-phone").value.replace(/\D/g, "").length >= 7 && $("#f-consent").checked;
  $("#get-call").disabled = !ok;
}
["#f-name", "#f-phone", "#f-consent"].forEach((s) => $(s).addEventListener("input", validateForm));
$("#get-call").addEventListener("click", async () => {
  $("#f-err").classList.add("hidden");
  const r = await fetch("/leads", { method: "POST", headers: jsonHeaders(),
    body: JSON.stringify({ first_name: $("#f-name").value.trim(), phone: $("#f-phone").value.trim() }) });
  if (!r.ok) { $("#f-err").textContent = "could not add lead: " + r.status; $("#f-err").classList.remove("hidden"); return; }
  const lead = await r.json();
  callbox.row = lead.row;
  $("#s2-row").textContent = lead.row;
  callbox.stage(2);
  $("#s2-status").textContent = "● FETCH_SHEETS";
  refreshLeads();
  await runSingle({ lead_row: lead.row });
});
$("#again").addEventListener("click", () => { callbox.row = null; $("#f-name").value = ""; $("#f-phone").value = ""; $("#f-consent").checked = false; validateForm(); callbox.stage(1); });
$$("#callbox .tab").forEach((t) => t.addEventListener("click", () => {
  $$("#callbox .tab").forEach((x) => x.classList.toggle("active", x === t));
  if (t.dataset.tab === "sheet") { callbox.stage("sheet"); refreshLeads(); } else callbox.stage(callbox.row ? $("#callbox").dataset.prevStage || 1 : 1);
}));

/* ---------- wiring ---------- */
$("#run").addEventListener("click", () => { callbox.row = null; runSingle({}); });
$("#run-batch").addEventListener("click", () => { callbox.row = null; runBatch(); });
$("#reset").addEventListener("click", async () => { await fetch("/leads/reset", { method: "POST" }); refreshLeads(); });
$("#pending").addEventListener("change", refreshLeads);

// Hidden key reveal: r, r outside an input.
let lastR = 0;
document.addEventListener("keydown", (e) => {
  if (["INPUT", "TEXTAREA"].includes(e.target.tagName)) return;
  if (e.key === "r") {
    const now = Date.now();
    if (now - lastR < 600) { $("#keybox").classList.toggle("hidden"); $("#demokey").focus(); lastR = 0; } else lastR = now;
  }
});
$("#demokey").value = localStorage.demoKey || "";
$("#demokey").addEventListener("change", (e) => { localStorage.demoKey = e.target.value; refreshStatus(); });

refreshStatus(); refreshBudget(); refreshLeads(); loadTemplate(); validateForm();
