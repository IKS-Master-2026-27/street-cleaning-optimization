/* The Algorithms tab: one algorithm in detail. */

function renderAlgorithms(view) {
  const list = algorithms();
  if (!state.alg || !getAlg(state.alg))
    state.alg = (measuredAlgorithms()[0] || list[0])?.name;
  const a = getAlg(state.alg);
  view.innerHTML = a ? algorithmDetail(a, list) : "";
  $("#alg-pick")?.addEventListener("change", (e) => {
    state.alg = e.target.value;
    render();
  });
  if (!a) return;

  bindChartCard(
    view,
    "alg",
    (el, metric) => drawMetric(el, metric, "alg-" + a.name, [a.name]),
    () => runsTable(a),
  );

  const hot = (state.data.functions[a.name] || [])
    .filter((f) => !f.helper)
    .map((f) => ({ f, share: shareOf(a.name, f) }))
    .filter((x) => x.share != null)
    .sort((x, y) => y.share - x.share)
    .slice(0, 8);
  const hotEl = view.querySelector("[data-hot]");
  if (hotEl && hot.length) {
    barChart(
      hotEl,
      hot.map(({ f, share }) => ({
        label: f.qualname,
        sub: f.file,
        value: share,
        text: fmtPct(share),
        color: seriesStyle(a.name).color,
        key: f.key,
        rows: [
          [
            "Time per call grows like",
            fitOf(f.per_call)?.model ? prettyO(fitOf(f.per_call).model) : "–",
          ],
        ],
      })),
      {
        aria: "Share of solve time per function",
        onClick: (it) => openFunction(a.name, it.key),
      },
    );
  }
  view
    .querySelector("[data-open-functions]")
    ?.addEventListener("click", () => openFunction(a.name, null));
}

function openFunction(alg, key) {
  state.fnAlg = alg;
  state.fnQuery = "";
  state.expanded = new Set(key ? [alg + "|" + key] : []);
  setTab("functions");
}

function bigOFact(title, block) {
  const fit = fitOf(block);
  return `<div class="fact">
    <div class="k">${esc(title)} grows like</div>
    <div class="measured">${growthCell(block)}</div>
    ${
      fit?.model
        ? `<p class="n">Fitted exponent n<sup>${fit.slope.toFixed(2)}</sup> on ${fit.points} instances (R² ${fit.r2}).</p>`
        : `<p class="n">${esc(fit?.reason || "No data")}: needs 3 or more instance sizes.</p>`
    }
  </div>`;
}

function algorithmDetail(a, list) {
  const failures = a.runs.filter((r) => r.status !== "ok");
  return `<section class="card">
      <div class="alg-head">${swatch(a.name)}
        <select id="alg-pick" aria-label="Algorithm">${list.map((x) => `<option value="${esc(x.name)}" ${x.name === a.name ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>
        <span class="card-sub mono">${esc(a.location || "")}${a.source === "extra" ? " · listed in EXTRA" : ""}</span>
        ${a.stale ? staleTag(`outdated: ${esc(a.stale_modes.join(", "))} measured on older code or input`) : ""}</div>
      <div class="facts">
        ${bigOFact("Time", a.time)}
        ${bigOFact("Memory", a.memory)}
      </div>
    </section>
    ${chartCard({ id: "alg", metrics: ["time", "memory"] })}
    <section class="card">
      <div class="card-head"><div><h2>Where the time goes ${functionsStale(a.name) ? staleTag("outdated") : ""}</h2><p class="card-sub">Share of solve time spent in each function (including what it calls) on the largest profiled instance. Click a bar for details.</p></div>
        <button class="btn ghost small" type="button" data-open-functions>All functions →</button></div>
      <div class="chart" data-hot>${(state.data.functions[a.name] || []).length ? "" : '<p class="muted">Not profiled yet.</p>'}</div>
    </section>
    ${failures.length ? `<section class="card"><h2>Problems</h2>${failures.map((r) => `<p class="problem"><b>${esc(r.instance)}</b> ${statusText(r.status)}<br><span class="mono">${esc(r.error || "")}</span></p>`).join("")}</section>` : ""}`;
}

function runsTable(a) {
  return (
    `<table><thead><tr><th>Instance</th><th class="num">Streets</th><th>Status</th><th class="num">Time</th><th class="num">Memory</th><th class="num">Score</th></tr></thead><tbody>` +
    a.runs
      .filter(inFamily)
      .map((r) => {
        const spread =
          r.runs && r.runs.length > 1
            ? `${r.runs.length} runs: ${fmtTime(Math.min(...r.runs))} – ${fmtTime(Math.max(...r.runs))}`
            : "";
        return `<tr><td>${esc(r.instance)}</td><td class="num">${fmtInt(r.streets)}</td><td>${statusText(r.status)}</td>
        <td class="num" title="${esc(spread)}">${fmtTime(r.seconds)}</td>
        <td class="num" title="Process max RSS ${esc(fmtBytes(r.max_rss_bytes))}">${fmtBytes(r.peak_bytes)}</td>
        <td class="num">${fmtScore(r.score)}</td></tr>`;
      })
      .join("") +
    "</tbody></table>"
  );
}
