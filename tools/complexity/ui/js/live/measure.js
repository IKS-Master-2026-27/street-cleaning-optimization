/* Live mode (`python -m tools.complexity serve`): the Measure panel (algorithm,
   instances, how much to measure) and its duration estimate. */

async function api(path, body) {
  const res = await fetch(
    path,
    body === undefined
      ? { cache: "no-store" }
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.error || res.statusText);
  return json;
}

const ALL = "__all__";
const INSTANCE_SETS = {
  small: { label: "Small · fast" },
  default: { label: "Small + medium · recommended" },
  large: { label: "All, with big cities · very slow" },
};
const DEPTHS = {
  quick: {
    label: "Time and memory only · quickest",
    modes: ["time", "memory"],
  },
  standard: {
    label: "Time, memory, functions · recommended",
    modes: ["time", "memory", "profile"],
  },
  full: {
    label: "Also memory per function · slowest",
    modes: ["time", "memory", "profile", "fmemory"],
  },
};

function initRunSelection() {
  const saved = store.get("run2", null) || {};
  const names = state.options.algorithms.map((a) => a.name);
  const paths = state.options.instances.map((i) => i.path);
  state.run = {
    algorithm:
      saved.algorithm === ALL || names.includes(saved.algorithm)
        ? saved.algorithm
        : names[0],
    instances:
      INSTANCE_SETS[saved.instances] || paths.includes(saved.instances)
        ? saved.instances
        : "default",
    depth: DEPTHS[saved.depth] ? saved.depth : "standard",
    repeat: saved.repeat || state.options.defaults.repeat,
    timeout: saved.timeout || state.options.defaults.timeout,
    fresh: false,
  };
}
function saveRun() {
  const { algorithm, instances, depth, repeat, timeout } = state.run;
  store.set("run2", { algorithm, instances, depth, repeat, timeout });
}

function selectedInstances() {
  const all = state.options.instances,
    choice = state.run.instances;
  if (INSTANCE_SETS[choice])
    return all.filter((i) => i.sets.includes(choice)).map((i) => i.path);
  return [choice];
}
function runRequest() {
  const r = state.run;
  return {
    algorithms:
      r.algorithm === ALL
        ? state.options.algorithms.map((a) => a.name)
        : [r.algorithm],
    instances: selectedInstances(),
    modes: DEPTHS[r.depth].modes,
    repeat: r.repeat,
    timeout: r.timeout,
    fresh: r.fresh,
  };
}

function fmtDuration(s) {
  if (s < 60) return `${Math.max(1, Math.round(s))} seconds`;
  if (s < 3600)
    return `${Math.round(s / 60)} minute${Math.round(s / 60) === 1 ? "" : "s"}`;
  const h = s / 3600;
  return `${h < 10 ? h.toFixed(1) : Math.round(h)} hours`;
}

function renderRunPanel() {
  const panel = $("#run-panel");
  panel.hidden = false;
  if (!state.options) {
    panel.innerHTML = `<h2>Measure</h2><p class="muted">${
      state.serverError
        ? `Cannot reach the local server (${esc(state.serverError)}). Is <code>python -m tools.complexity serve</code> still running?`
        : "Loading…"
    }</p>`;
    return;
  }
  const r = state.run,
    o = state.options;
  const running = !!state.status?.running;
  const sizes = (set) => {
    const list = o.instances.filter((i) => i.sets.includes(set));
    return list.length ? ` (${list.length})` : "";
  };
  panel.innerHTML = `
    <h2>Measure</h2>
    <div class="run-form">
      <label class="step">1 · Algorithm
        <select class="input" id="run-alg" ${running ? "disabled" : ""}>
          ${o.algorithms.map((a) => `<option value="${esc(a.name)}" ${a.name === r.algorithm ? "selected" : ""}>${esc(a.name)}</option>`).join("")}
          <option value="${ALL}" ${r.algorithm === ALL ? "selected" : ""}>All ${o.algorithms.length} algorithms · slower</option>
        </select></label>
      <label class="step">2 · Instances
        <select class="input" id="run-inst" ${running ? "disabled" : ""}>
          <optgroup label="Groups">${Object.entries(INSTANCE_SETS)
            .map(
              ([k, v]) =>
                `<option value="${k}" ${k === r.instances ? "selected" : ""}>${esc(v.label + sizes(k))}</option>`,
            )
            .join("")}</optgroup>
          <optgroup label="One instance">${o.instances
            .map(
              (i) =>
                `<option value="${esc(i.path)}" ${i.path === r.instances ? "selected" : ""}>${esc(i.name)} · ${fmtCompact(i.streets)} streets${i.sets.includes("default") ? "" : " · slow"}</option>`,
            )
            .join("")}</optgroup>
        </select></label>
      <label class="step">3 · Measure
        <select class="input" id="run-depth" ${running ? "disabled" : ""}>
          ${Object.entries(DEPTHS)
            .map(
              ([k, v]) =>
                `<option value="${k}" ${k === r.depth ? "selected" : ""}>${esc(v.label)}</option>`,
            )
            .join("")}
        </select></label>
      <div class="step run-go">
        ${
          running
            ? `<button class="btn danger" type="button" id="run-stop"><svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="3" width="10" height="10" rx="2"/></svg>Stop</button>`
            : `<button class="btn primary" type="button" id="run-go"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5v11l9-5.5z"/></svg>Run</button>`
        }
      </div>
    </div>
    <div id="run-estimate" class="estimate" aria-live="polite"></div>
    <details class="advanced"><summary>Advanced</summary>
      <div class="run-row">
        <label>Repeats <input class="input" type="number" min="1" max="20" id="run-repeat" value="${r.repeat}"></label>
        <label>Time limit (s) <input class="input" type="number" min="5" max="7200" id="run-timeout" value="${r.timeout}"></label>
        <label class="check"><input type="checkbox" id="run-fresh" ${r.fresh ? "checked" : ""}>Measure again even if nothing changed</label>
      </div>
    </details>`;
  renderEstimate();
  renderProgress();
  enhanceSelects(panel);

  const change =
    (key, parse = (v) => v) =>
    (e) => {
      r[key] = parse(e.target.value);
      saveRun();
      updateEstimate();
    };
  $("#run-alg").addEventListener("change", change("algorithm"));
  $("#run-inst").addEventListener("change", change("instances"));
  $("#run-depth").addEventListener("change", change("depth"));
  $("#run-repeat").addEventListener(
    "change",
    change("repeat", (v) => Math.max(1, +v || 1)),
  );
  $("#run-timeout").addEventListener(
    "change",
    change("timeout", (v) => Math.max(5, +v || 300)),
  );
  $("#run-fresh").addEventListener("change", (e) => {
    r.fresh = e.target.checked;
    updateEstimate();
  });
  $("#run-go")?.addEventListener("click", startRun);
  $("#run-stop")?.addEventListener("click", async () => {
    try {
      await api("/api/cancel", {});
    } catch (e) {
      addLog({ type: "info", message: e.message });
    }
  });
}

/* ------------------------------------------------------------ estimate */
let estimateTimer = null,
  estimateSeq = 0;
function updateEstimate() {
  clearTimeout(estimateTimer);
  estimateTimer = setTimeout(async () => {
    const seq = ++estimateSeq;
    try {
      const plan = await api("/api/plan", runRequest());
      if (seq === estimateSeq) {
        state.estimate = plan;
        renderEstimate();
      }
    } catch (e) {
      state.estimate = { error: e.message };
      renderEstimate();
    }
  }, 150);
}

function estimateLevel(p) {
  if (!p || p.error) return "info";
  if (p.big_instances.length || p.seconds > 1800 || p.likely_timeouts > 0)
    return "danger";
  if (p.seconds > 300 || p.unknown > 0) return "warn";
  return "info";
}

function renderEstimate() {
  const el = $("#run-estimate");
  if (!el) return;
  const p = state.estimate;
  if (!p) {
    el.innerHTML = "";
    return;
  }
  if (p.error) {
    el.className = "estimate info";
    el.textContent = p.error;
    return;
  }
  const level = estimateLevel(p);
  const parts = [];
  if (!p.jobs) {
    parts.push(
      `<b>Already measured.</b> Nothing new to run${p.cached ? ` (${p.cached} results are reused)` : ""}. To repeat it, open Advanced and tick “Measure again”.`,
    );
  } else {
    const time =
      p.unknown === p.jobs
        ? "an unknown time (never measured before)"
        : `roughly <b>${fmtDuration(p.seconds)}</b>${p.unknown ? `, plus ${p.unknown} measurement${p.unknown === 1 ? "" : "s"} never timed before` : ""}`;
    parts.push(
      `${p.jobs} measurement${p.jobs === 1 ? "" : "s"} to run${p.cached ? `, ${p.cached} reused` : ""}: ${time}.`,
    );
    if (p.big_instances.length)
      parts.push(
        `Includes big cities (${esc(p.big_instances.join(", "))}): some algorithms may run for hours or stop at the time limit.`,
      );
    else if (p.likely_timeouts)
      parts.push(
        `${p.likely_timeouts} measurement${p.likely_timeouts === 1 ? "" : "s"} hit the time limit last time and will probably stop at it again.`,
      );
    if (level !== "info")
      parts.push(
        "You can keep using the dashboard while it runs, and Stop cancels it.",
      );
  }
  el.className = `estimate ${level}`;
  el.innerHTML = `${level === "info" ? "" : `<span class="estimate-icon" aria-hidden="true">${ICONS.critical}</span>`}<span>${parts.join(" ")}</span>`;
}
