/* The Functions tab: every project function an algorithm calls. Four columns;
   the rest (calls, memory, per-instance numbers, charts) opens when a row is clicked. */

function largestOf(f) {
  const insts = state.data.instances.filter((i) => f.per_instance[i.name]);
  return insts.length ? f.per_instance[insts[insts.length - 1].name] : null;
}
// Share of total solve time, on the largest profiled instance of the selected family.
function shareOf(alg, f) {
  const totals = state.data.profiled?.[alg] || {};
  const inst = familyInstances()
    .filter((i) => totals[i.name])
    .pop();
  if (!inst) return f.share;
  const cum = f.per_instance[inst.name]?.cum;
  return cum == null ? null : Math.min(1, cum / totals[inst.name]);
}
const FN_SORTS = {
  key: (f) => f.qualname.toLowerCase(),
  share: (f) => shareOf(state.fnAlg, f) ?? -1,
  per_call: (f) => fitOf(f.per_call)?.slope ?? -1,
  memory: (f) => fitOf(f.memory)?.slope ?? -1,
};
const FN_FILTERS = [
  ["own", "Named functions"],
  ["all", "Everything, incl. lambdas"],
];

function renderFunctions(view) {
  const names = Object.keys(state.data.functions || {}).filter(
    (n) => (state.data.functions[n] || []).length,
  );
  if (!names.length) {
    view.innerHTML = `<section class="card empty"><h2>No functions profiled yet</h2><p>Run with the Profile measurement.</p></section>`;
    return;
  }
  if (!state.fnAlg || !names.includes(state.fnAlg))
    state.fnAlg = names.includes(state.alg) ? state.alg : names[0];
  const all = state.data.functions[state.fnAlg] || [];
  const q = state.fnQuery.trim().toLowerCase();
  let rows = all.filter(
    (f) =>
      (state.fnFilter === "all" || !f.helper) &&
      (!q || f.key.toLowerCase().includes(q)),
  );
  const sorter = FN_SORTS[state.fnSort.key] || FN_SORTS.share;
  rows.sort((x, y) => {
    const a = sorter(x),
      b = sorter(y);
    return (a < b ? -1 : a > b ? 1 : 0) * state.fnSort.dir;
  });
  const total = rows.length;
  rows = rows.slice(0, state.fnLimit);
  const th = (key, label, cls = "") => {
    const on = state.fnSort.key === key;
    return `<th class="sortable ${cls}" data-sort="${key}" aria-sort="${on ? (state.fnSort.dir > 0 ? "ascending" : "descending") : "none"}">${label}${on ? ` <span class="arrow">${state.fnSort.dir > 0 ? "↑" : "↓"}</span>` : ""}</th>`;
  };

  view.innerHTML = `<section class="card">
    <div class="controls">
      <select class="input" id="fn-alg" aria-label="Algorithm">${names.map((n) => `<option value="${esc(n)}" ${n === state.fnAlg ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
      <input class="input search" id="fn-q" type="search" placeholder="Search functions" value="${esc(state.fnQuery)}" aria-label="Search functions">
      <select class="input" id="fn-filter" aria-label="Which functions">${FN_FILTERS.map(([v, l]) => `<option value="${v}" ${v === state.fnFilter ? "selected" : ""}>${l}</option>`).join("")}</select>
      ${functionsStale(state.fnAlg) ? staleTag("outdated: profiled on older code or input; run Profile again") : ""}
    </div>
    <div class="table-wrap"><table class="fn-table"><thead><tr>
      ${th("key", "Function")}${th("share", "Share of time", "num")}${th("per_call", "Time per call grows like")}${th("memory", "Memory per call grows like")}
    </tr></thead><tbody>${rows.map(functionRow).join("")}</tbody></table></div>
    <div class="table-foot"><span class="muted">${total} function${total === 1 ? "" : "s"}${total > rows.length ? `, showing ${rows.length}` : ""}</span>
      ${total > rows.length ? `<button class="btn ghost small" id="fn-more" type="button">Show more</button>` : ""}</div>
  </section>`;

  $("#fn-alg").addEventListener("change", (e) => {
    state.fnAlg = e.target.value;
    state.expanded.clear();
    render();
  });
  $("#fn-filter").addEventListener("change", (e) => {
    state.fnFilter = e.target.value;
    render();
  });
  $("#fn-q").addEventListener("input", (e) => {
    state.fnQuery = e.target.value;
    const pos = e.target.selectionStart;
    render();
    const box = $("#fn-q");
    box.focus();
    box.setSelectionRange(pos, pos);
  });
  $("#fn-more")?.addEventListener("click", () => {
    state.fnLimit += 40;
    render();
  });
  view.querySelectorAll("th[data-sort]").forEach((h) =>
    h.addEventListener("click", () => {
      const key = h.dataset.sort;
      state.fnSort = {
        key,
        dir:
          state.fnSort.key === key ? -state.fnSort.dir : key === "key" ? 1 : -1,
      };
      render();
    }),
  );
  view.querySelectorAll("tr[data-fn]").forEach((tr) => {
    const toggle = () => {
      const id = state.fnAlg + "|" + tr.dataset.fn;
      state.expanded.has(id)
        ? state.expanded.delete(id)
        : state.expanded.add(id);
      render();
    };
    tr.addEventListener("click", toggle);
    tr.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggle();
      }
    });
  });
  rows
    .filter((f) => state.expanded.has(state.fnAlg + "|" + f.key))
    .forEach(drawFunctionDetail);
}

function functionRow(f) {
  const id = state.fnAlg + "|" + f.key;
  const open = state.expanded.has(id);
  const sh = shareOf(state.fnAlg, f);
  const share =
    sh != null
      ? `<span class="share"><span class="share-bar" style="width:${Math.max(2, Math.round(sh * 60))}px"></span>${fmtPct(sh)}</span>`
      : '<span class="muted" title="Not called on this instance">–</span>';
  const tr = `<tr class="clickable ${open ? "expanded" : ""}" data-fn="${esc(f.key)}" aria-expanded="${open}" tabindex="0">
    <td><span class="chev" aria-hidden="true">${open ? "▾" : "▸"}</span><span class="fn-name">${esc(f.qualname)}</span><div class="fn-file">${esc(f.file)}${f.line ? ":" + f.line : ""}</div></td>
    <td class="num">${share}</td><td>${growthCell(f.per_call)}</td><td>${growthCell(f.memory)}</td></tr>`;
  return open ? tr + functionDetail(f, id) : tr;
}

function functionDetail(f, id) {
  const safe = cssId(id);
  const last = largestOf(f);
  const insts = state.data.instances.filter((i) => f.per_instance[i.name]);
  const fact = (k, v) =>
    `<div class="kv"><span>${k}</span><span>${v}</span></div>`;
  return `<tr class="detail"><td colspan="4">
    <div class="detail-grid">
      <div class="kvs">
        ${fact("Calls on largest instance", fmtInt(last?.calls))}
        ${fact("Calls grow like", growthCell(f.calls))}
        ${fact("Time per call grows like", growthCell(f.per_call))}
        ${fact("Memory per call grows like", growthCell(f.memory))}
      </div>
      <div class="mini"><h4>Time per call</h4><div class="chart" data-mini="t-${safe}"></div></div>
      <div class="mini"><h4>Peak memory per call</h4><div class="chart" data-mini="m-${safe}"></div></div>
    </div>
    <details class="raw"><summary>Numbers per instance</summary><div class="table-wrap"><table><thead><tr><th>Instance</th><th class="num">Streets</th><th class="num">Calls</th><th class="num">Own time</th><th class="num">With callees</th><th class="num">Per call</th><th class="num">Memory / call</th></tr></thead><tbody>
    ${insts
      .map((i) => {
        const p = f.per_instance[i.name];
        return `<tr><td>${esc(i.name)}</td><td class="num">${fmtInt(i.streets)}</td><td class="num">${fmtInt(p.calls)}</td><td class="num">${fmtTime(p.own)}</td><td class="num">${fmtTime(p.cum)}</td><td class="num">${p.calls ? fmtTime(p.cum / p.calls) : "–"}</td><td class="num">${fmtBytes(p.peak)}</td></tr>`;
      })
      .join("")}
    </tbody></table></div></details></td></tr>`;
}
const cssId = (s) => s.replace(/[^a-zA-Z0-9]/g, "_");

function drawFunctionDetail(f) {
  const id = cssId(state.fnAlg + "|" + f.key);
  const { color } = seriesStyle(state.fnAlg);
  const insts = state.data.instances.filter(
    (i) =>
      f.per_instance[i.name] &&
      (state.family === "all" || i.family === state.family),
  );
  const series = (getter, fmt) => {
    const pts = insts
      .map((i) => ({ i, y: getter(f.per_instance[i.name]) }))
      .filter((p) => p.y > 0)
      .map(({ i, y }) => ({
        x: i.streets,
        y,
        label: fmt(y),
        title: i.name,
        sub: `${fmtInt(i.streets)} streets`,
      }));
    return [{ name: f.qualname, color, points: pts }];
  };
  const opts = { xLog: true, yLog: true, height: 170, legend: false };
  const t = $(`[data-mini="t-${id}"]`),
    m = $(`[data-mini="m-${id}"]`);
  if (t)
    lineChart(t, {
      ...opts,
      id: "t" + id,
      yFormat: fmtTime,
      series: series((p) => (p.calls ? p.cum / p.calls : null), fmtTime),
    });
  if (m)
    lineChart(m, {
      ...opts,
      id: "m" + id,
      yFormat: fmtBytes,
      series: series((p) => p.peak, fmtBytes),
    });
}
