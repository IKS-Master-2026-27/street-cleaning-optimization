/* The Overview tab, the growth table, and the sidebar summary. */

function renderOverview(view) {
  view.innerHTML = `
    ${chartCard({ id: "overview", metrics: ["time", "memory", "score"] })}
    <section class="card">
      <div class="card-head"><div><h2>How each algorithm grows</h2><p class="card-sub">Measured Big O: the growth that best fits the measurements; n is the number of streets. Click an algorithm for its charts and functions.</p></div></div>
      <div class="table-wrap">${growthTable(algorithms())}</div>
    </section>`;
  bindChartCard(
    view,
    "overview",
    (el, metric) => drawMetric(el, metric, "overview"),
    (metric) => instanceTable(METRICS[metric].field, METRICS[metric].fmt),
  );
  bindAlgorithmLinks(view);
}

// Sidebar Stats: fastest and best score on the largest instance that the most
// algorithms finished, how many algorithms are measured, and the instances.
function renderStats() {
  const wrap = $("#stats-wrap");
  const algs = measuredAlgorithms();
  wrap.hidden = !algs.length;
  if (!algs.length) return;
  const insts = familyInstances();
  const finished = (i) =>
    algs.filter((a) =>
      a.runs.some((r) => r.path === i.path && r.status === "ok"),
    ).length;
  const largest = [...insts].sort(
    (a, b) => finished(b) - finished(a) || b.streets - a.streets,
  )[0];
  let fastest = null,
    best = null;
  if (largest)
    for (const a of algs) {
      const r = a.runs.find((x) => x.path === largest.path);
      if (r?.seconds != null && (!fastest || r.seconds < fastest.v))
        fastest = { a: a.name, v: r.seconds };
      if (r?.score != null && r.status === "ok" && (!best || r.score > best.v))
        best = { a: a.name, v: r.score };
    }
  const sizes = insts.map((i) => i.streets);
  const tile = (label, value, sub, cls = "") =>
    `<div><span title="${esc(label)}">${esc(label)}</span><b class="${cls}">${value}</b>${sub ? `<span>${sub}</span>` : ""}</div>`;
  $("#stats").innerHTML =
    tile(
      `Fastest on ${largest?.name || "–"}`,
      fastest ? fmtTime(fastest.v) : "–",
      fastest ? esc(fastest.a) : "",
    ) +
    tile(
      `Best score on ${largest?.name || "–"}`,
      best ? best.v.toFixed(4) : "–",
      best ? esc(best.a) : "",
    ) +
    tile("Algorithms measured", `${algs.length} / ${algorithms().length}`, "") +
    tile(
      "Instances",
      String(insts.length),
      sizes.length
        ? `${fmtCompact(Math.min(...sizes))} – ${fmtCompact(Math.max(...sizes))} streets`
        : "",
    );
}

function growthTable(list) {
  return (
    `<table class="growth-table"><thead><tr><th>Algorithm</th><th>Time grows like</th><th>Memory grows like</th></tr></thead><tbody>` +
    list
      .map((a) => {
        const note = a.stale
          ? ` ${staleTag("outdated")}`
          : a.runs.length
            ? ""
            : profiledFunctions(a.name).length
              ? ' <span class="tag">profiled only</span>'
              : ' <span class="tag">not measured</span>';
        return `<tr class="clickable" data-alg="${esc(a.name)}" tabindex="0">
        <td>${algName(a.name)}${note}</td>
        <td>${growthCell(a.time)}</td>
        <td>${growthCell(a.memory)}</td></tr>`;
      })
      .join("") +
    "</tbody></table>"
  );
}

function bindAlgorithmLinks(root) {
  root.querySelectorAll("tr[data-alg]").forEach((tr) => {
    const open = () => {
      state.alg = tr.dataset.alg;
      setTab("algorithms");
    };
    tr.addEventListener("click", open);
    tr.addEventListener("keydown", (e) => {
      if (e.key === "Enter") open();
    });
  });
}
