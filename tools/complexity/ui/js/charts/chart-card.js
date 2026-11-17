/* Chart cards: a card with one chart, a Time / Memory / Score switch and a Table button. */

function segmented(name, options, current) {
  return `<div class="segmented" role="group">${options
    .map(
      ([value, label]) =>
        `<button type="button" data-${name}="${esc(value)}" aria-pressed="${value === current}">${esc(label)}</button>`,
    )
    .join("")}</div>`;
}

/** A card holding one chart, an optional metric switch and a chart/table toggle. */
function chartCard({ id, title, sub, metrics = null }) {
  const metric = metrics ? (state.metric[id] ||= metrics[0]) : null;
  const tableOn = !!state.tableView[id];
  const meta = metric ? METRICS[metric] : null;
  return `<section class="card" data-card="${id}">
    <div class="card-head"><div><h2 data-title>${esc(meta?.title || title)}</h2><p class="card-sub" data-sub>${esc(meta?.sub || sub || "")}</p></div>
      <div class="chart-tools">${
        metrics
          ? segmented(
              "metric",
              metrics.map((m) => [m, METRICS[m].label]),
              metric,
            )
          : ""
      }
        <button class="btn ghost small" type="button" data-table-toggle aria-pressed="${tableOn}">Table</button></div></div>
    <div class="chart" data-chart ${tableOn ? "hidden" : ""}></div>
    <div class="table-wrap" data-table ${tableOn ? "" : "hidden"}></div>
  </section>`;
}
function bindChartCard(root, id, draw, table) {
  const card = root.querySelector(`[data-card="${id}"]`);
  if (!card) return;
  const chartEl = card.querySelector("[data-chart]"),
    tableEl = card.querySelector("[data-table]");
  const fill = () => {
    const metric = state.metric[id];
    if (metric) {
      card.querySelector("[data-title]").textContent = METRICS[metric].title;
      card.querySelector("[data-sub]").textContent = METRICS[metric].sub;
    }
    chartEl.hidden = !!state.tableView[id];
    tableEl.hidden = !state.tableView[id];
    if (state.tableView[id]) tableEl.innerHTML = table(metric);
    else draw(chartEl, metric);
  };
  card.querySelector("[data-table-toggle]").addEventListener("click", (ev) => {
    state.tableView[id] = !state.tableView[id];
    ev.currentTarget.setAttribute("aria-pressed", String(state.tableView[id]));
    fill();
  });
  card.querySelectorAll("[data-metric]").forEach((b) =>
    b.addEventListener("click", () => {
      state.metric[id] = b.dataset.metric;
      card
        .querySelectorAll("[data-metric]")
        .forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      fill();
    }),
  );
  fill();
}

/** The standard "metric against instance size" chart for a set of algorithms. */
function drawMetric(el, metric, id, names = null, extra = []) {
  const meta = METRICS[metric];
  lineChart(el, {
    id: `${id}-${metric}`,
    series: [...seriesFor(meta.field, meta.fmt, names), ...extra],
    xLog: true,
    yLog: meta.log,
    yMin: meta.log ? undefined : 0,
    yMax: meta.log ? undefined : 1,
    xTitle: "streets (n)",
    yFormat: meta.log ? meta.fmt : (v) => v.toFixed(2),
    height: metric === "score" ? 240 : 290,
    aria: `${meta.title} by instance size`,
  });
}
