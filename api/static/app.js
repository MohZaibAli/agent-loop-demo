/* Sandbox Agents — single-page client. No framework, no build step. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const STAGGER_MS = 40;

  const state = {
    demoKey: "",
    provider: "mock",
    live: 0,          // number of in-flight runs
    counters: { turns: 0, tokens: 0, cost: 0 },
    lastSandbox: "—",
    lastModel: "—",
  };

  // ---------- formatting ----------
  const fmtCost = (v) => "$" + (Number(v) || 0).toFixed(3);
  const fmtInt = (v) => (Number(v) || 0).toLocaleString("en-US");
  const pad2 = (v) => String(v).padStart(2, "0");
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const shortId = (id) => (id && id.length > 14 ? id.slice(0, 12) + "…" : id || "—");

  // ---------- counters ----------
  const counterCache = new Map();
  function setCounter(id, target, format) {
    const el = $(id);
    const from = counterCache.get(id) || 0;
    counterCache.set(id, target);
    if (reduceMotion || from === target) { el.textContent = format(target); return; }
    const t0 = performance.now();
    const dur = 400;
    const step = (now) => {
      const p = Math.min(1, (now - t0) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = format(from + (target - from) * eased);
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // ---------- budget / status ----------
  async function refreshBudget() {
    try {
      const b = await (await fetch("/budget")).json();
      $("budget-remaining").textContent = fmtCost(Math.min(4, b.remaining));
    } catch (_) { /* leave previous value */ }
  }
  async function refreshStatus() {
    try {
      const s = await (await fetch("/status")).json();
      state.lastModel = s.model;
      $("foot-meta").textContent = `sandbox: ${s.sandbox_provider} · model: ${s.model}`;
      setProviderLabel(s.llm_provider === "openrouter" ? "openrouter" : "mock");
    } catch (_) { /* ignore */ }
  }
  function setProviderLabel(p) {
    state.provider = p;
    const el = $("provider-label");
    el.dataset.provider = p;
    el.textContent = p === "mock" ? "MOCK" : "LIVE · OPENROUTER";
  }
  function setLive(delta) {
    state.live = Math.max(0, state.live + delta);
    $("progress").classList.toggle("live", state.live > 0);
    $("run").disabled = $("run-parallel").disabled = state.live > 0;
  }

  // ---------- hidden demo key (press r, r) ----------
  let lastR = 0;
  document.addEventListener("keydown", (e) => {
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key !== "r") { lastR = 0; return; }
    const now = performance.now();
    if (lastR && now - lastR < 700) {
      const field = $("demo-key");
      field.hidden = !field.hidden;
      if (!field.hidden) field.focus();
      lastR = 0;
    } else {
      lastR = now;
    }
  });
  $("demo-key").addEventListener("input", (e) => { state.demoKey = e.target.value.trim(); });

  function headers() {
    const h = { "Content-Type": "application/json" };
    if (state.demoKey) h["X-Demo-Key"] = state.demoKey;
    return h;
  }

  // ---------- event rendering ----------
  function toolLabel(name) {
    return ({ bash: "BASH", read_file: "READ", write_file: "WRITE", edit_file: "EDIT", search: "SEARCH" })[name] || name.toUpperCase();
  }

  function describeCall(ev) {
    const a = ev.arguments || {};
    switch (ev.name) {
      case "bash": return `<div class="ev-cmd"><span class="k">$ </span>${esc(a.command)}</div>`;
      case "read_file": return `<div class="ev-cmd">${esc(a.path)}${a.offset ? ` <span class="k">from line ${a.offset + 1}</span>` : ""}</div>`;
      case "write_file": return `<div class="ev-cmd">${esc(a.path)} <span class="k">(${(a.content || "").length} chars)</span></div>`;
      case "edit_file": return `<div class="ev-cmd">${esc(a.path)}</div>`;
      case "search": return `<div class="ev-cmd"><span class="k">/</span>${esc(a.pattern)}<span class="k">/</span> in ${esc(a.path || ".")}${a.glob ? ` <span class="k">(${esc(a.glob)})</span>` : ""}</div>`;
      default: return `<div class="ev-cmd">${esc(JSON.stringify(a))}</div>`;
    }
  }

  function pytestSummary(stdout) {
    const m = /(?:(\d+) failed, )?(\d+) passed/.exec(stdout || "");
    return m ? { failed: Number(m[1] || 0), passed: Number(m[2]) } : null;
  }

  function renderDiff(diff) {
    const rows = [];
    let oldN = 0, newN = 0;
    for (const raw of diff.split("\n")) {
      if (!raw && rows.length) continue;
      if (raw.startsWith("--- ")) continue;
      if (raw.startsWith("+++ ")) { rows.push(`<tr class="file"><td colspan="3">${esc(raw.slice(6))}</td></tr>`); continue; }
      const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(raw);
      if (hunk) { oldN = Number(hunk[1]); newN = Number(hunk[2]); rows.push(`<tr class="hunk"><td colspan="3">${esc(raw)}</td></tr>`); continue; }
      const sign = raw[0];
      const text = esc(raw.slice(1));
      if (sign === "+") rows.push(`<tr class="add"><td class="n"></td><td class="n">${newN++}</td><td class="c">+${text}</td></tr>`);
      else if (sign === "-") rows.push(`<tr class="del"><td class="n">${oldN++}</td><td class="n"></td><td class="c">-${text}</td></tr>`);
      else rows.push(`<tr><td class="n">${oldN++}</td><td class="n">${newN++}</td><td class="c"> ${text}</td></tr>`);
    }
    return `<div class="diff"><table>${rows.join("")}</table></div>`;
  }

  function describeResult(ev) {
    const r = ev.result || {};
    if (r.error) return { head: `<span class="fail">ERROR</span>`, body: `<pre class="out err">${esc(r.error)}</pre>`, open: true };
    switch (ev.name) {
      case "bash": {
        const ok = r.exit_code === 0;
        const t = pytestSummary(r.stdout);
        const head = t
          ? `<span class="${t.failed ? "fail" : "ok"}">${t.passed} passed${t.failed ? ` · ${t.failed} failed` : ""}</span>`
          : `<span class="${ok ? "ok" : "fail"}">exit ${r.exit_code}</span>`;
        const out = [r.stdout, r.stderr].filter(Boolean).join("\n");
        return { head, body: out ? `<pre class="out">${esc(out.trim())}</pre>` : "", open: !!t };
      }
      case "read_file":
        return { head: `${r.total_lines} lines`, body: `<pre class="out">${esc(r.content)}</pre>`, open: false };
      case "write_file":
        return { head: `${r.bytes} bytes written`, body: "", open: false };
      case "edit_file":
        return { head: `<span class="ok">1 replacement</span>`, body: renderDiff(r.diff || ""), open: true };
      case "search":
        return { head: `${r.count} match${r.count === 1 ? "" : "es"}`, body: r.matches ? `<pre class="out">${esc(r.matches)}</pre>` : "", open: r.count > 0 && r.count <= 8 };
      default:
        return { head: "", body: `<pre class="out">${esc(JSON.stringify(r, null, 2))}</pre>`, open: false };
    }
  }

  function makeRow(kind, head, body, detail, open, delayMs) {
    const li = document.createElement("li");
    li.className = "ev";
    li.dataset.kind = kind;
    if (!reduceMotion) li.style.animationDelay = `${delayMs}ms`;
    let html = `<div class="ev-head">${head}</div>`;
    if (body) html += body;
    if (detail) {
      html += `<button class="ev-toggle" type="button" aria-expanded="${open}">${open ? "collapse" : "expand"}</button>
               <div class="ev-detail${open ? " open" : ""}"><div>${detail}</div></div>`;
    }
    li.innerHTML = html;
    const toggle = li.querySelector(".ev-toggle");
    if (toggle) {
      toggle.addEventListener("click", () => {
        const d = li.querySelector(".ev-detail");
        const isOpen = d.classList.toggle("open");
        toggle.setAttribute("aria-expanded", String(isOpen));
        toggle.textContent = isOpen ? "collapse" : "expand";
      });
    }
    return li;
  }

  /** Append an event to a timeline list. Returns the row (or null if nothing is drawn). */
  function appendEvent(list, ev, pending, compact) {
    const seq = list.children.length;
    const delay = (seq % 4) * STAGGER_MS;
    const ts = `<span class="t">#${pad2(ev.turn ?? 0)}</span>`;
    switch (ev.type) {
      case "run_started":
        return list.appendChild(makeRow("run_started", `RUN STARTED ${ts}`,
          `<div class="ev-body text">${esc(ev.task)}</div>`, null, false, delay));
      case "assistant_text":
        return list.appendChild(makeRow("assistant_text", `AGENT ${ts}`,
          `<div class="ev-body text">${esc(ev.text)}</div>`, null, false, delay));
      case "tool_call": {
        const row = makeRow("tool_call", `TOOL · ${toolLabel(ev.name)} <span class="res"></span> ${ts}`,
          describeCall(ev), null, false, delay);
        pending.set(ev.id, row);
        return list.appendChild(row);
      }
      case "tool_result": {
        const row = pending.get(ev.id);
        const r = describeResult(ev);
        if (!row) return null;
        row.querySelector(".res").innerHTML = r.head;
        if (r.body && !compact) {
          row.insertAdjacentHTML("beforeend",
            `<button class="ev-toggle" type="button" aria-expanded="${r.open}">${r.open ? "collapse" : "expand"}</button>
             <div class="ev-detail${r.open ? " open" : ""}"><div>${r.body}</div></div>`);
          const toggle = row.querySelector(".ev-toggle");
          toggle.addEventListener("click", () => {
            const d = row.querySelector(".ev-detail");
            const isOpen = d.classList.toggle("open");
            toggle.setAttribute("aria-expanded", String(isOpen));
            toggle.textContent = isOpen ? "collapse" : "expand";
          });
        }
        return row;
      }
      case "error":
        return list.appendChild(makeRow("error", `<span class="fail">ERROR</span>`,
          `<div class="ev-body">${esc(ev.message)}</div>`, null, false, delay));
      case "run_finished": {
        const label = ev.status === "complete" ? "RUN COMPLETE" : `RUN ${esc(ev.status).toUpperCase()}`;
        return list.appendChild(makeRow("run_finished", `${label} <span class="t">${ev.turns} turns · ${fmtCost(ev.cost)}</span>`,
          null, null, false, delay));
      }
      default:
        return null; // usage events update instrumentation only
    }
  }

  // ---------- SSE ----------
  function subscribe(runId, onEvent, onDone) {
    const es = new EventSource(`/runs/${runId}/events`);
    const handler = (e) => {
      const ev = JSON.parse(e.data);
      onEvent(ev);
      if (ev.type === "run_finished") { es.close(); onDone(ev); }
    };
    for (const t of ["run_started", "assistant_text", "tool_call", "tool_result", "usage", "run_finished", "error"]) {
      es.addEventListener(t, handler);
    }
    es.onerror = () => { es.close(); onDone(null); };
    return es;
  }

  // ---------- single run ----------
  function setStatus(s) {
    $("m-status").dataset.state = s;
    $("m-status-text").textContent = s.replace("_", " ").toUpperCase();
  }

  async function startRun(task) {
    $("live").hidden = false;
    $("parallel").hidden = true;
    $("timeline").innerHTML = "";
    $("report").hidden = true;
    counterCache.clear();
    ["m-turns", "m-tokens"].forEach((id) => ($(id).textContent = id === "m-turns" ? "00" : "0"));
    $("m-cost").textContent = "$0.000";
    $("m-sandbox").textContent = "—";
    $("m-provider").textContent = "—";
    setStatus("queued");
    $("live").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });

    let res;
    try {
      res = await fetch("/runs", { method: "POST", headers: headers(), body: JSON.stringify({ task }) });
    } catch (err) { setStatus("error"); return; }
    if (!res.ok) { setStatus("error"); $("m-run").textContent = `HTTP ${res.status}`; return; }
    const { run_id, provider } = await res.json();
    $("m-run").textContent = run_id;
    $("m-provider").textContent = provider;
    setProviderLabel(provider);
    setLive(+1);

    const pending = new Map();
    subscribe(run_id, (ev) => {
      if (ev.type === "run_started") {
        $("m-sandbox").textContent = ev.sandbox_id;
        $("m-model").textContent = ev.model;
        setStatus("running");
      }
      if (ev.type === "usage") {
        setCounter("m-turns", ev.turn, (v) => pad2(Math.round(v)));
        setCounter("m-tokens", ev.cumulative.total_tokens, (v) => fmtInt(Math.round(v)));
        setCounter("m-cost", ev.cumulative.cost, fmtCost);
      }
      appendEvent($("timeline"), ev, pending, false);
    }, (fin) => {
      setLive(-1);
      refreshBudget();
      if (!fin) { setStatus("error"); return; }
      setStatus(fin.status);
      setCounter("m-turns", fin.turns, (v) => pad2(Math.round(v)));
      setCounter("m-tokens", fin.tokens, (v) => fmtInt(Math.round(v)));
      setCounter("m-cost", fin.cost, fmtCost);
      showReport(fin);
    });
  }

  function showReport(fin) {
    const total = (fin.tests_passed ?? 0) + (fin.tests_failed ?? 0);
    $("report-tests").textContent = fin.tests_passed == null ? "—" : `${fin.tests_passed}/${total}`;
    $("report-summary").textContent = fin.summary || "";
    $("report-diff").innerHTML = fin.diff ? renderDiff(fin.diff) : "";
    $("report").hidden = false;
  }

  // ---------- parallel ----------
  async function startParallel(task) {
    $("parallel").hidden = false;
    $("live").hidden = true;
    const lanes = $("lanes");
    lanes.innerHTML = "";
    $("parallel").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });

    const res = await fetch("/runs/batch", { method: "POST", headers: headers(), body: JSON.stringify({ task, count: 3 }) });
    if (!res.ok) return;
    const { run_ids, provider } = await res.json();
    setProviderLabel(provider);

    run_ids.forEach((runId, i) => {
      const lane = document.createElement("article");
      lane.className = "lane";
      lane.dataset.run = runId;
      lane.innerHTML = `
        <div class="lane-head">
          <div class="row"><span class="k">LANE ${i + 1}</span><span class="k status" data-state="queued"><span class="dot"></span><span class="st">QUEUED</span></span></div>
          <div class="row"><span class="k">SANDBOX</span><span class="sbx">—</span></div>
          <div class="row"><span class="k">COST</span><span class="cost">$0.000</span></div>
        </div>
        <ol class="timeline"></ol>
        <div class="lane-result" hidden></div>`;
      lanes.appendChild(lane);
      setLive(+1);
      const list = lane.querySelector(".timeline");
      const status = lane.querySelector(".status");
      const pending = new Map();
      subscribe(runId, (ev) => {
        if (ev.type === "run_started") {
          lane.querySelector(".sbx").textContent = ev.sandbox_id;
          status.dataset.state = "running";
          status.querySelector(".st").textContent = "RUNNING";
        }
        if (ev.type === "usage") lane.querySelector(".cost").textContent = fmtCost(ev.cumulative.cost);
        appendEvent(list, ev, pending, true);
      }, (fin) => {
        setLive(-1);
        refreshBudget();
        const s = fin ? fin.status : "error";
        status.dataset.state = s;
        status.querySelector(".st").textContent = s.replace("_", " ").toUpperCase();
        if (fin) {
          lane.querySelector(".cost").textContent = fmtCost(fin.cost);
          const total = (fin.tests_passed ?? 0) + (fin.tests_failed ?? 0);
          const r = lane.querySelector(".lane-result");
          r.innerHTML = `<b>${fin.tests_passed == null ? "—" : `${fin.tests_passed}/${total}`}</b>TESTS PASSED · ${fin.turns} turns`;
          r.hidden = false;
        }
      });
    });
  }

  // ---------- wiring ----------
  const taskEl = $("task");
  const autosize = () => { taskEl.style.height = "auto"; taskEl.style.height = taskEl.scrollHeight + "px"; };
  taskEl.addEventListener("input", autosize);
  taskEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("task-form").requestSubmit(); }
  });
  $("task-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const task = taskEl.value.trim();
    if (task && !state.live) startRun(task);
  });
  $("run-parallel").addEventListener("click", () => {
    const task = taskEl.value.trim();
    if (task && !state.live) startParallel(task);
  });

  autosize();
  refreshBudget();
  refreshStatus();
})();
