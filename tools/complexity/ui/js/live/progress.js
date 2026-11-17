/* Live mode: starting a run, the progress bar and log, and checking the server for news. */

// The bottom bar under the content
function renderProgress() {
  const el = $("#runbar");
  if (!el) return;
  const s = state.status;
  if (!s || (!s.running && !state.log.length)) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  el.hidden = false;
  const p = s.progress || {};
  const pct = p.total
    ? Math.round((p.done / p.total) * 100)
    : s.running
      ? 0
      : 100;
  el.innerHTML = `<div class="progress-row">
    <span class="muted">${s.running ? (p.current ? `Measuring ${esc(p.current)}` : "Starting…") : "Last run"}</span>
    <div class="progress-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><div style="width:${pct}%"></div></div>
    <span class="progress-text">${p.done || 0} / ${p.total || 0}</span>
    <button type="button" class="link" id="log-toggle">${state.logOpen ? "hide log" : "show log"}</button></div>
    <div class="log" id="run-log" ${state.logOpen ? "" : "hidden"}>${state.log.slice(-80).map(logLine).join("")}</div>`;
  $("#log-toggle").addEventListener("click", () => {
    state.logOpen = !state.logOpen;
    renderProgress();
  });
  const log = $("#run-log");
  log.scrollTop = log.scrollHeight;
}
function logLine(e) {
  let text = "",
    cls = "";
  if (e.type === "start") text = `▶ ${e.label}`;
  else if (e.type === "done") {
    text = `${e.status === "ok" ? "✓" : "✗"} ${e.label} · ${e.status} · ${e.wall_seconds.toFixed(1)} s`;
    cls = e.status === "ok" ? "ok" : "bad";
  } else if (e.type === "skip") text = `↷ ${e.label} skipped: ${e.reason}`;
  else if (e.type === "finished") {
    text = "Run finished.";
    cls = "ok";
  } else if (e.type === "cancelled") {
    text = "Run stopped.";
    cls = "bad";
  } else if (e.type === "plan")
    text = `Planned ${e.total} measurement${e.total === 1 ? "" : "s"}.`;
  else text = e.message || e.type;
  return `<div><span class="t">${esc(e.at || "")}</span><span class="${cls}">${esc(text)}</span></div>`;
}
function addLog(e) {
  state.log.push({ at: new Date().toTimeString().slice(0, 8), ...e });
  state.logOpen = true;
  renderProgress();
}

async function startRun() {
  const p = state.estimate;
  if (p && p.jobs && estimateLevel(p) === "danger") {
    const msg = p.big_instances.length
      ? `This includes big cities (${p.big_instances.join(", ")}) and can take hours. Start anyway?`
      : `This will take roughly ${fmtDuration(p.seconds)}. Start anyway?`;
    if (!confirm(msg)) return;
  }
  const request = runRequest();
  try {
    const res = await api("/api/run", request);
    if (!res.jobs) {
      addLog({
        type: "info",
        message: "Everything selected is already measured.",
      });
      return;
    }
    if (request.algorithms.length === 1) state.alg = request.algorithms[0]; // show it when done
    await poll();
  } catch (e) {
    addLog({ type: "info", message: `Could not start: ${e.message}` });
  }
}

let pollTimer = null;
async function poll() {
  clearTimeout(pollTimer);
  try {
    const s = await api(`/api/status?since=${state.eventsNext}`);
    const wasRunning = state.status?.running;
    state.status = s;
    state.serverError = null;
    if (s.events.length) {
      state.log.push(...s.events);
      state.eventsNext = s.next;
    }
    if (s.version !== state.version) {
      const first = state.version === -1;
      state.version = s.version;
      if (!first) await refreshData();
    }
    if (wasRunning !== s.running) {
      renderRunPanel();
      if (!s.running) updateEstimate();
    } else renderProgress();
  } catch (e) {
    state.serverError = e.message;
  }
  renderMeta();
  pollTimer = setTimeout(poll, state.status?.running ? 1000 : 4000);
}

async function refreshData() {
  const scroll = scrollY;
  state.data = await api("/api/results");
  view.style.minHeight = `${view.offsetHeight}px`; // no collapse while redrawing
  render();
  scrollTo(0, scroll);
  requestAnimationFrame(() => {
    view.style.minHeight = "";
  });
}
