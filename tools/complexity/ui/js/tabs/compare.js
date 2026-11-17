/* The Compare tab: two algorithms side by side. */

function renderCompare(view) {
  const list = measuredAlgorithms();
  if (list.length < 2) {
    view.innerHTML = `<section class="card empty"><h2>Measure at least two algorithms to compare them</h2></section>`;
    return;
  }
  let [x, y] = state.compare;
  if (!getAlg(x)) x = list[0].name;
  if (!getAlg(y) || y === x) y = list.find((a) => a.name !== x).name;
  state.compare = [x, y];
  const A = getAlg(x),
    B = getAlg(y);
  const rows = familyInstances()
    .map((i) => ({
      i,
      ra: A.runs.find((r) => r.path === i.path) || {},
      rb: B.runs.find((r) => r.path === i.path) || {},
    }))
    .filter(({ ra, rb }) => ra.status || rb.status);
  const common = rows.filter(({ ra, rb }) => ra.seconds && rb.seconds).pop();
  let headline = "Not measured on a common instance yet.";
  if (common) {
    const ratio = common.rb.seconds / common.ra.seconds;
    const [fast, slow, k] =
      ratio > 1 ? [A.name, B.name, ratio] : [B.name, A.name, 1 / ratio];
    headline =
      k < 1.1
        ? `On <b>${esc(common.i.name)}</b> (${fmtInt(common.i.streets)} streets), ${algName(fast)} and ${algName(slow)} take about the same time.`
        : `On <b>${esc(common.i.name)}</b> (${fmtInt(common.i.streets)} streets), ${algName(fast)} is <b>${k.toFixed(k < 10 ? 1 : 0)}× faster</b> than ${algName(slow)}.`;
  }
  const pick = (idx, cur) =>
    `<select class="input" data-cmp="${idx}" aria-label="Algorithm ${idx + 1}">${list.map((a) => `<option value="${esc(a.name)}" ${a.name === cur ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</select>`;
  const cell = (r, field, fmt) =>
    r[field] != null ? fmt(r[field]) : r.status ? statusText(r.status) : "–";

  view.innerHTML = `<section class="card">
      <div class="controls">${pick(0, x)}<span class="muted">vs.</span>${pick(1, y)}</div>
      <p class="headline">${headline}</p>
      <div class="table-wrap">${growthTable([A, B])}</div>
    </section>
    ${chartCard({ id: "compare", metrics: ["time", "memory", "score"] })}
    <section class="card"><div class="card-head"><div><h2>Instance by instance</h2></div></div>
      <div class="table-wrap"><table><thead><tr><th>Instance</th><th class="num">Streets</th>
        <th class="num">${algName(A.name)}</th><th class="num">${algName(B.name)}</th><th class="num">Score ${esc(A.name)}</th><th class="num">Score ${esc(B.name)}</th></tr></thead><tbody>
      ${rows
        .map(
          ({
            i,
            ra,
            rb,
          }) => `<tr><td>${esc(i.name)}</td><td class="num">${fmtInt(i.streets)}</td>
        <td class="num">${cell(ra, "seconds", fmtTime)}</td><td class="num">${cell(rb, "seconds", fmtTime)}</td>
        <td class="num">${fmtScore(ra.score)}</td><td class="num">${fmtScore(rb.score)}</td></tr>`,
        )
        .join("")}
      </tbody></table></div></section>`;
  view.querySelectorAll("[data-cmp]").forEach((s) =>
    s.addEventListener("change", () => {
      state.compare[+s.dataset.cmp] = s.value;
      render();
    }),
  );
  bindChartCard(
    view,
    "compare",
    (el, metric) => drawMetric(el, metric, "compare", [A.name, B.name]),
    (metric) =>
      instanceTable(METRICS[metric].field, METRICS[metric].fmt, [
        A.name,
        B.name,
      ]),
  );
  bindAlgorithmLinks(view);
}
