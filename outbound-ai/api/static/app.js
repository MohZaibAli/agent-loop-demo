const $ = (s) => document.querySelector(s);
const headers = () => (localStorage.demoKey ? { "X-Demo-Key": localStorage.demoKey } : {});

async function refresh() {
  const h = await fetch("/health").then((r) => r.json());
  $("#sheet").textContent = "sheet=" + h.sheet + " provider=" + h.provider;
  const m = await fetch("/mode", { headers: headers() }).then((r) => r.json());
  $("#mode").textContent = m.mode;
  $("#mode").classList.toggle("live", m.mode === "LIVE");
  const pending = $("#pending").checked;
  const d = await fetch("/leads?pending=" + pending).then((r) => r.json());
  $("#count").textContent = d.count + (pending ? " pending" : " total");
  const tb = $("#leads tbody");
  tb.innerHTML = "";
  for (const l of d.leads) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="mono">${l.row}</td><td class="mono">${l.phone}</td><td>${l.first_name}</td><td>${l.job_title}</td><td>${l.new_job_opportunity}</td><td class="mono">${l.call_made}</td><td class="mono">${l.date_time || "—"}</td>`;
    tb.appendChild(tr);
  }
}
$("#pending").addEventListener("change", refresh);

// Hidden key reveal: press r, r outside an input.
let last = 0;
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "r") {
    const now = Date.now();
    if (now - last < 600) { $("#keybox").classList.toggle("hidden"); last = 0; } else last = now;
  }
});
$("#demokey").value = localStorage.demoKey || "";
$("#demokey").addEventListener("change", (e) => { localStorage.demoKey = e.target.value; refresh(); });
refresh();
