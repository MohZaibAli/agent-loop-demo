/* Sandbox Agents — single-page client. No framework, no build step. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const STAGGER_MS = 40;

  let storedKey = "", storedLive = false, storedNotes = true;
  try {
    storedKey = localStorage.getItem("demoKey") || "";
    storedLive = localStorage.getItem("liveMode") === "1";
    storedNotes = localStorage.getItem("stackNotes") !== "0";
  } catch (_) { /* private mode */ }
  const state = {
    scenario: "listing_parser",
    scenarios: [],
    realAvailable: false,
    sandboxProvider: "",
    router: "",
    notes: storedNotes,
    follow: true,       // auto-scroll to the newest event while the user stays near it
    programmatic: false,
    demoKey: storedKey,
    liveMode: storedLive,   // send the demo key (pay for a real model) or not
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

  // ---------- follow the live step ----------
  const trace = document.querySelector(".trace");
  function nearBottom() {
    return trace.scrollHeight - trace.scrollTop - trace.clientHeight < 160;
  }
  trace.addEventListener("scroll", () => {
    if (state.programmatic) return;
    state.follow = nearBottom();
  }, { passive: true });
  function reveal() {
    if (!state.follow) return;
    state.programmatic = true;
    requestAnimationFrame(() => {
      trace.scrollTo({ top: trace.scrollHeight, behavior: reduceMotion ? "auto" : "smooth" });
      clearTimeout(reveal.t);
      reveal.t = setTimeout(() => { state.programmatic = false; }, reduceMotion ? 50 : 500);
    });
  }
  function collapseAll(list) {
    list.querySelectorAll(".ev-detail.open").forEach((d) => d.classList.remove("open"));
    list.querySelectorAll(".ev-toggle").forEach((t) => { t.setAttribute("aria-expanded", "false"); t.textContent = "expand"; });
  }
  function setActive(list, row) {
    list.querySelectorAll(".ev.active").forEach((r) => r.classList.remove("active"));
    if (row) row.classList.add("active");
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
      state.sandboxProvider = s.sandbox_provider;
      state.router = s.router || "";
      state.realAvailable = !!s.real_available;
      $("foot-meta").textContent = `sandbox: ${s.sandbox_provider} · model: ${s.model}`;
      syncMode();
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
  $("demo-key").value = state.demoKey;
  $("demo-key").addEventListener("input", (e) => {
    state.demoKey = e.target.value.trim();
    try { localStorage.setItem("demoKey", state.demoKey); } catch (_) { /* ignore */ }
    if (state.demoKey && !state.liveMode) { state.liveMode = true; try { localStorage.setItem("liveMode", "1"); } catch (_) { /* ignore */ } }
    syncMode();
  });

  function headers() {
    const h = { "Content-Type": "application/json" };
    if (state.demoKey && state.liveMode) h["X-Demo-Key"] = state.demoKey;
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
        collapseAll(list);
        const row = makeRow("tool_call", `TOOL · ${toolLabel(ev.name)} <span class="res">running…</span> ${ts}`,
          describeCall(ev), null, false, delay);
        pending.set(ev.id, row);
        list.appendChild(row);
        setActive(list, row);
        return row;
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
      case "model_routed":
        return list.appendChild(makeRow("model_routed", `ROUTED ${ts}`,
          `<div class="ev-cmd">${esc(ev.model)}</div>`, null, false, delay));
      case "run_finished": {
        setActive(list, null);
        const label = ev.status === "complete" ? "RUN COMPLETE" : `RUN ${esc(ev.status).toUpperCase()}`;
        return list.appendChild(makeRow("run_finished", `${label} <span class="t">${ev.turns} turns · ${fmtCost(ev.cost)}</span>`,
          null, null, false, delay));
      }
      default:
        return null; // usage events update instrumentation only
    }
  }

  // ---------- overlays ----------
  function openOverlay(id) {
    $("live").hidden = id !== "live";
    $("parallel").hidden = id !== "parallel";
    document.body.classList.toggle("has-overlay", !!id);
  }
  document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => openOverlay(null)));
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!$("key-modal").hidden) { closeKeyDialog(false); return; }
    if (!state.live) openOverlay(null);
  });

  // ---------- stage notes: what each step used, from facts the events already carry ----------
  function syncNotes() {
    document.body.classList.toggle("notes-off", !state.notes);
    $("notes-toggle").setAttribute("aria-pressed", String(state.notes));
  }
  $("notes-toggle").addEventListener("click", () => {
    state.notes = !state.notes;
    try { localStorage.setItem("stackNotes", state.notes ? "1" : "0"); } catch (_) { /* ignore */ }
    syncNotes();
  });
  syncNotes();

  const TOOL_NOTES = {
    bash: "<b>bash</b> runs in the sandbox shell with a 60s timeout; output over 10k chars is truncated head+tail.",
    search: "<b>search</b> uses ripgrep inside the sandbox (grep -rn fallback); nothing is installed at runtime.",
    read_file: "<b>read_file</b> returns numbered lines; paths are resolved and confined to /home/user/workspace.",
    edit_file: "<b>edit_file</b> replaces exactly one match and refuses 0 or 2+; the unified diff you see is the real change.",
    write_file: "<b>write_file</b> creates or replaces a file inside the workspace only.",
  };
  function stageNote(ev) {
    const e2b = state.sandboxProvider === "e2b";
    switch (ev.type) {
      case "run_started": {
        const sb = e2b
          ? `<b>E2B</b> microVM from template <b>agent-loop-py312</b> (Python 3.12, pytest, ripgrep), internet off, seeded with the repo`
          : `<b>LocalSandbox</b> temp directory (test mode)`;
        const route = ev.provider === "mock"
          ? `Provider: <b>scripted replay</b>, no model call, $0.`
          : ev.router
            ? `First turn goes to <b>OpenRouter Jev Router</b> (<span class="hl">${esc(ev.router)}</span>), which picks a model for this prompt.`
            : `Model: <b>${esc(ev.model)}</b> via OpenRouter.`;
        return `Sandbox: ${sb}. ${route}`;
      }
      case "model_routed":
        return `<b>Jev</b> chose <span class="hl">${esc(ev.model)}</span> for this task, balancing quality, speed and cost. The pick is pinned for the rest of the run so the cached system prompt and tools keep hitting.`;
      case "tool_call":
        return TOOL_NOTES[ev.name] || "";
      case "tool_result": {
        if (ev.name === "bash" && /pytest/.test(ev.arguments?.command || "")) return "";
        return "";
      }
      case "run_finished":
        return `Sandbox killed in <b>finally</b>; usage priced from OpenRouter's accounted cost and written to the spend ledger (${fmtCost(ev.cost)}).`;
      default:
        return "";
    }
  }
  function usageNote(ev) {
    if (!ev.cached_tokens) return "";
    return `Prompt cache hit: <b>${fmtInt(ev.cached_tokens)}</b> of ${fmtInt(ev.prompt_tokens)} prompt tokens read from cache at 10% of input price.`;
  }
  function attachNote(row, html) {
    if (!row || !html) return;
    row.insertAdjacentHTML("beforeend", `<p class="ev-note">${html}</p>`);
  }

  // ---------- pending indicator ("what is it doing right now") ----------
  function setPending(list, text) {
    let row = list.querySelector(".ev.pending");
    if (!text) { if (row) row.remove(); return; }
    if (!row) {
      row = document.createElement("li");
      row.className = "ev pending";
      row.dataset.kind = "pending";
      row.innerHTML = `<div class="ev-head">AGENT</div><div class="ev-body"></div>`;
    }
    row.querySelector(".ev-body").textContent = text;
    list.appendChild(row); // always last
  }
  function pendingTextAfter(ev) {
    switch (ev.type) {
      case "run_started": return "Reading the task…";
      case "tool_call": return null;            // the tool row itself shows "running…"
      case "tool_result": return "Thinking about the result…";
      case "assistant_text": return null;
      case "model_routed": return "Thinking…";
      case "usage": return undefined;           // leave as is
      default: return null;
    }
  }

  // ---------- SSE ----------
  function subscribe(runId, onEvent, onDone) {
    const es = new EventSource(`/runs/${runId}/events`);
    let lastSeq = -1;
    let finished = false;
    const handler = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.seq <= lastSeq) return; // replayed after a reconnect
      lastSeq = ev.seq;
      onEvent(ev);
      if (ev.type === "run_finished") { finished = true; es.close(); onDone(ev); }
    };
    for (const t of ["run_started", "assistant_text", "tool_call", "tool_result", "usage", "model_routed", "run_finished", "error"]) {
      es.addEventListener(t, handler);
    }
    // On a dropped connection EventSource reconnects by itself and the server replays
    // history (deduped above). Only give up when the run no longer exists: a restart.
    es.onerror = async () => {
      if (finished) return;
      try {
        const r = await fetch(`/runs/${runId}`);
        if (r.status === 404) { es.close(); onDone({ interrupted: true }); }
      } catch (_) { /* server unreachable: keep EventSource retrying */ }
    };
    return es;
  }

  // ---------- single run ----------
  function setStatus(s) {
    $("m-status").dataset.state = s;
    $("m-status-text").textContent = s.replace("_", " ").toUpperCase();
  }

  async function startRun(task) {
    openOverlay("live");
    $("live-task").textContent = task;
    $("timeline").innerHTML = "";
    $("report").hidden = true;
    counterCache.clear();
    ["m-turns", "m-tokens"].forEach((id) => ($(id).textContent = id === "m-turns" ? "00" : "0"));
    $("m-cost").textContent = "$0.000";
    $("m-cached").textContent = "0";
    $("m-router").textContent = "—";
    $("m-sandbox").textContent = "—";
    $("m-provider").textContent = "—";
    setStatus("queued");
    state.follow = true;
    setPending($("timeline"), "Provisioning an isolated sandbox…");

    let res;
    try {
      res = await fetch("/runs", { method: "POST", headers: headers(), body: JSON.stringify(runBody({ task })) });
    } catch (err) { setStatus("error"); return; }
    if (res.status === 403 && currentNeedsLive()) {
      // Wrong or stale password: ask again and retry once accepted.
      openOverlay(null);
      forgetKey();
      if (await askForKey("That password was not accepted. Try again.")) startRun(task);
      return;
    }
    if (!res.ok) {
      setStatus("error");
      $("m-run").textContent = `HTTP ${res.status}`;
      let detail = `HTTP ${res.status}`;
      try { detail = (await res.json()).detail || detail; } catch (_) { /* keep */ }
      showError(typeof detail === "string" ? detail : JSON.stringify(detail));
      openOverlay(null);
      return;
    }
    clearError();
    const { run_id, provider } = await res.json();
    $("m-run").textContent = run_id;
    $("m-provider").textContent = provider;
    setProviderLabel(provider);
    setLive(+1);

    const pending = new Map();
    subscribe(run_id, (ev) => {
      if (ev.type === "run_started") {
        $("m-sandbox").textContent = ev.sandbox_id;
        $("m-router").textContent = ev.provider === "mock" ? "— (scripted)" : (ev.router || "— (fixed)");
        $("m-model").textContent = ev.router && ev.provider !== "mock" ? "routing…" : ev.model;
        setStatus("running");
      }
      if (ev.type === "model_routed") $("m-model").textContent = ev.model;
      if (ev.type === "usage") {
        setCounter("m-turns", ev.turn, (v) => pad2(Math.round(v)));
        setCounter("m-tokens", ev.cumulative.total_tokens, (v) => fmtInt(Math.round(v)));
        setCounter("m-cached", ev.cumulative.cached_tokens, (v) => fmtInt(Math.round(v)));
        setCounter("m-cost", ev.cumulative.cost, fmtCost);
      }
      const list = $("timeline");
      const next = pendingTextAfter(ev);
      if (next !== undefined) setPending(list, null);
      const row = appendEvent(list, ev, pending, false);
      if (ev.type === "usage") { const last = list.querySelector(".ev:not(.pending):last-of-type"); if (ev.turn === 1) attachNote(last, usageNote(ev)); }
      else if (ev.type !== "tool_result") attachNote(row, stageNote(ev));
      if (next) setPending(list, next);
      else if (ev.type === "assistant_text" && !list.querySelector(".ev.active")) setPending(list, "Deciding the next step…");
      reveal();
    }, (fin) => {
      setPending($("timeline"), null);
      setLive(-1);
      refreshBudget();
      if (!fin || fin.interrupted) {
        setStatus("interrupted");
        $("m-status-text").textContent = "INTERRUPTED · SERVER RESTARTED";
        $("timeline").appendChild(makeRow("error", `<span class="fail">INTERRUPTED</span>`,
          `<div class="ev-body">The service restarted during this run (a deploy or crash). The sandbox was discarded. Run it again.</div>`, null, false, 0));
        reveal();
        return;
      }
      setStatus(fin.status);
      setCounter("m-turns", fin.turns, (v) => pad2(Math.round(v)));
      setCounter("m-tokens", fin.tokens, (v) => fmtInt(Math.round(v)));
      setCounter("m-cost", fin.cost, fmtCost);
      showReport(fin);
      // Final pin: a burst of smooth scrolls can stop short, so settle at the bottom once.
      if (state.follow) setTimeout(() => { trace.scrollTop = trace.scrollHeight; }, reduceMotion ? 0 : 320);
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
    openOverlay("parallel");
    const lanes = $("lanes");
    lanes.innerHTML = "";

    const res = await fetch("/runs/batch", { method: "POST", headers: headers(), body: JSON.stringify(runBody({ task, count: 3 })) });
    if (res.status === 403 && currentNeedsLive()) {
      openOverlay(null);
      forgetKey();
      if (await askForKey("That password was not accepted. Try again.")) startParallel(task);
      return;
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { detail = (await res.json()).detail || detail; } catch (_) { /* keep */ }
      showError(typeof detail === "string" ? detail : JSON.stringify(detail));
      openOverlay(null);
      return;
    }
    clearError();
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
        <div class="lane-body"><ol class="timeline"></ol><div class="lane-result" hidden></div></div>`;
      lanes.appendChild(lane);
      setLive(+1);
      const list = lane.querySelector(".timeline");
      const body = lane.querySelector(".lane-body");
      const status = lane.querySelector(".status");
      const pending = new Map();
      let follow = true;
      body.addEventListener("scroll", () => { follow = body.scrollHeight - body.scrollTop - body.clientHeight < 120; }, { passive: true });
      const pin = () => { if (follow) requestAnimationFrame(() => body.scrollTo({ top: body.scrollHeight, behavior: reduceMotion ? "auto" : "smooth" })); };
      setPending(list, "Provisioning an isolated sandbox…");
      subscribe(runId, (ev) => {
        if (ev.type === "run_started") {
          lane.querySelector(".sbx").textContent = ev.sandbox_id;
          status.dataset.state = "running";
          status.querySelector(".st").textContent = "RUNNING";
        }
        if (ev.type === "usage") lane.querySelector(".cost").textContent = fmtCost(ev.cumulative.cost);
        const next = pendingTextAfter(ev);
        if (next !== undefined) setPending(list, null);
        appendEvent(list, ev, pending, true);
        if (next) setPending(list, next);
        pin();
      }, (fin) => {
        setPending(list, null);
        pin();
        setLive(-1);
        refreshBudget();
        const s = !fin || fin.interrupted ? "interrupted" : fin.status;
        if (fin && fin.interrupted) fin = null;
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

  // ---------- scenarios ----------
  const liveReady = () => state.realAvailable && !!state.demoKey && state.liveMode;
  function syncMode() {
    const btn = $("mode");
    btn.hidden = !(state.realAvailable && state.demoKey);
    btn.setAttribute("aria-pressed", String(liveReady()));
    setProviderLabel(liveReady() ? "openrouter" : "mock");
    renderScenarios();
  }
  $("mode").addEventListener("click", () => {
    state.liveMode = !state.liveMode;
    try { localStorage.setItem("liveMode", state.liveMode ? "1" : "0"); } catch (_) { /* ignore */ }
    syncMode();
  });
  async function loadScenarios() {
    try { state.scenarios = await (await fetch("/scenarios")).json(); } catch (_) { state.scenarios = []; }
    renderScenarios();
  }
  function renderScenarios() {
    const box = $("scenarios");
    box.innerHTML = "";
    for (const sc of state.scenarios) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "scenario";
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(state.scenario === sc.id));
      b.dataset.id = sc.id;
      b.innerHTML = `<span class="mark">${state.scenario === sc.id ? "●" : "○"}</span>
        <span class="name">${esc(sc.title)}${sc.mock ? "" : '<span class="live">LIVE DEMO</span>'}</span>
        <span class="shape">${esc(sc.shape)}</span>`;
      b.addEventListener("click", () => {
        state.scenario = sc.id;
        taskEl.value = sc.task;
        autosize();
        renderScenarios();
        clearError();
      });
      box.appendChild(b);
    }
    const current = state.scenarios.find((sc) => sc.id === state.scenario);
    const note = $("scenario-note");
    if (current && !current.mock) {
      note.innerHTML = liveReady()
        ? "<b>Live model.</b> This run uses the real model and is metered against the budget."
        : "<b>Live model.</b> This scenario needs the demo password; you will be asked for it when you run.";
      note.hidden = false;
    } else if (current) {
      note.innerHTML = liveReady()
        ? "Prototype scenario. Runs on the live model while LIVE is on."
        : "Prototype scenario. Runs on the free scripted replay.";
      note.hidden = false;
    } else {
      note.hidden = true;
    }
  }
  function currentNeedsLive() {
    const sc = state.scenarios.find((x) => x.id === state.scenario);
    return !!sc && !sc.mock;
  }
  // Jev may route to a premium model; give the live demos headroom under the global ceiling.
  const LIVE_RUN_CAP = 0.75;
  const runBody = (extra) => ({ task: extra.task, scenario: state.scenario,
    ...(liveReady() ? { max_cost_usd: LIVE_RUN_CAP } : {}), ...extra });

  // ---------- demo password dialog ----------
  let keyResolve = null;
  function askForKey(error) {
    $("key-error").hidden = !error;
    $("key-error").textContent = error || "";
    $("key-input").value = "";
    $("key-modal").hidden = false;
    $("key-input").focus();
    return new Promise((resolve) => { keyResolve = resolve; });
  }
  function closeKeyDialog(value) {
    $("key-modal").hidden = true;
    const r = keyResolve; keyResolve = null;
    if (r) r(value);
  }
  $("key-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = $("key-input").value.trim();
    if (!v) { $("key-input").focus(); return; }
    state.demoKey = v;
    state.liveMode = true;
    try { localStorage.setItem("demoKey", v); localStorage.setItem("liveMode", "1"); } catch (_) { /* ignore */ }
    syncMode();
    closeKeyDialog(true);
  });
  document.querySelector("[data-cancel-key]").addEventListener("click", () => closeKeyDialog(false));
  /** Make sure a live scenario has a password before starting; returns false if the user cancelled. */
  async function ensureAccess() {
    if (!currentNeedsLive() || (state.demoKey && state.liveMode)) return true;
    return askForKey(null);
  }
  function forgetKey() {
    state.demoKey = "";
    state.liveMode = false;
    try { localStorage.removeItem("demoKey"); localStorage.setItem("liveMode", "0"); } catch (_) { /* ignore */ }
    syncMode();
  }

  function showError(msg) {
    let el = document.querySelector(".workbench-error");
    if (!el) { el = document.createElement("p"); el.className = "workbench-error"; $("task-form").appendChild(el); }
    el.textContent = msg;
  }
  function clearError() { const el = document.querySelector(".workbench-error"); if (el) el.remove(); }

  // ---------- wiring ----------
  const taskEl = $("task");
  const autosize = () => { taskEl.style.height = "auto"; taskEl.style.height = taskEl.scrollHeight + "px"; };
  taskEl.addEventListener("input", autosize);
  taskEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("task-form").requestSubmit(); }
  });
  $("task-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const task = taskEl.value.trim();
    if (task && !state.live && await ensureAccess()) startRun(task);
  });
  $("run-parallel").addEventListener("click", async () => {
    const task = taskEl.value.trim();
    if (task && !state.live && await ensureAccess()) startParallel(task);
  });

  autosize();
  refreshBudget();
  refreshStatus();
  loadScenarios();
})();
