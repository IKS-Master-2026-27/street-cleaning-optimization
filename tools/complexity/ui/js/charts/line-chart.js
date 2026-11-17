/* The line chart: hand-written SVG with one y-axis, a hover tooltip and a
   clickable legend. Charts are redrawn when their width changes. */

function logTicks(min, max) {
  const lo = Math.floor(Math.log10(min)),
    hi = Math.ceil(Math.log10(max));
  const decades = hi - lo;
  const mult = decades <= 1 ? [1, 2, 5] : decades <= 3 ? [1, 3] : [1];
  const ticks = [];
  for (let e = lo; e <= hi; e++)
    for (const m of mult) {
      const v = m * 10 ** e;
      if (v >= min * 0.999 && v <= max * 1.001) ticks.push(v);
    }
  return ticks.length < 2 ? [min, max] : ticks;
}
function linearTicks(min, max, count = 5) {
  const span = max - min || 1;
  const pow = 10 ** Math.floor(Math.log10(span / count));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => span / s <= count) ||
    pow * 10;
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step)
    ticks.push(+v.toFixed(10));
  return ticks;
}

// element -> {render, width}. A chart is redrawn only when its width really
// changes; redrawing on height changes would make it jump back and forth.
const charts = new Map();
const resizer = new ResizeObserver((entries) => {
  for (const entry of entries) {
    const chart = charts.get(entry.target);
    if (!chart || !entry.target.isConnected) continue;
    const width = Math.round(entry.contentRect.width);
    if (Math.abs(width - chart.width) < 2) continue;
    chart.width = width;
    chart.render();
  }
});
function mountChart(el, render) {
  charts.set(el, { render, width: Math.round(el.clientWidth) });
  resizer.observe(el);
  render();
}

/**
 * cfg: { id, series:[{name, color, dash, ref, points:[{x,y,label,title,sub}]}],
 *        xLog, yLog, xTitle, yFormat, xFormat, yMin, yMax, height, legend, aria }
 */
function lineChart(el, cfg) {
  const hidden = state.hidden[cfg.id] || (state.hidden[cfg.id] = new Set());
  const render = () => {
    const width = Math.max(260, el.clientWidth || 600);
    const height = cfg.height || 300;
    const visible = cfg.series.filter(
      (s) => !hidden.has(s.name) && s.points.length,
    );
    const usable = (p) => !cfg.yLog || p.y > 0;
    const pts = visible.flatMap((s) => s.points).filter(usable);
    const labelled = visible.filter((s) => !s.ref);
    const endLabels = labelled.length <= 4 && width > 420;
    const m = {
      l: 60,
      r: endLabels ? 100 : 16,
      t: 10,
      b: cfg.xTitle ? 40 : 26,
    };
    const iw = width - m.l - m.r,
      ih = height - m.t - m.b;
    let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(cfg.aria || "chart")}">`;
    if (!pts.length) {
      el.innerHTML =
        svg +
        `<text x="${width / 2}" y="${height / 2}" text-anchor="middle" class="tick">No data for this selection</text></svg>` +
        legendHtml();
      bindLegend();
      return;
    }
    let [x0, x1] = [
      Math.min(...pts.map((p) => p.x)),
      Math.max(...pts.map((p) => p.x)),
    ];
    let [y0, y1] = [
      Math.min(...pts.map((p) => p.y)),
      Math.max(...pts.map((p) => p.y)),
    ];
    if (cfg.xLog) {
      x0 /= 1.25;
      x1 *= 1.25;
    } else {
      const pad = (x1 - x0 || 1) * 0.05;
      x0 -= pad;
      x1 += pad;
    }
    if (cfg.yLog) {
      y0 /= 1.6;
      y1 *= 1.6;
    } else {
      const pad = (y1 - y0 || Math.abs(y1) || 1) * 0.12;
      y0 -= pad;
      y1 += pad;
      if (cfg.yMin !== undefined) y0 = Math.max(cfg.yMin, y0);
      if (cfg.yMax !== undefined) y1 = Math.min(cfg.yMax, y1);
    }
    const sx = cfg.xLog
      ? (v) =>
          m.l +
          ((Math.log(v) - Math.log(x0)) / (Math.log(x1) - Math.log(x0))) * iw
      : (v) => m.l + ((v - x0) / (x1 - x0 || 1)) * iw;
    const sy = cfg.yLog
      ? (v) =>
          m.t +
          ih -
          ((Math.log(v) - Math.log(y0)) / (Math.log(y1) - Math.log(y0))) * ih
      : (v) => m.t + ih - ((v - y0) / (y1 - y0 || 1)) * ih;
    const yf = cfg.yFormat || String,
      xf = cfg.xFormat || fmtCompact;
    for (const t of cfg.yLog ? logTicks(y0, y1) : linearTicks(y0, y1, 4)) {
      const y = sy(t);
      svg += `<line class="gridline" x1="${m.l}" x2="${m.l + iw}" y1="${y}" y2="${y}"/>`;
      svg += `<text class="tick" x="${m.l - 8}" y="${y + 4}" text-anchor="end">${esc(yf(t))}</text>`;
    }
    svg += `<line class="axisline" x1="${m.l}" x2="${m.l + iw}" y1="${m.t + ih}" y2="${m.t + ih}"/>`;
    let lastX = -1e9;
    for (const t of cfg.xLog
      ? logTicks(x0, x1)
      : linearTicks(x0, x1, Math.max(3, Math.floor(iw / 90)))) {
      const x = sx(t);
      if (x - lastX < 40) continue;
      lastX = x;
      svg += `<text class="tick" x="${x}" y="${m.t + ih + 16}" text-anchor="middle">${esc(xf(t))}</text>`;
    }
    if (cfg.xTitle)
      svg += `<text class="axis-title" x="${m.l + iw / 2}" y="${height - 4}" text-anchor="middle">${esc(cfg.xTitle)}</text>`;

    const sorted = (s) => s.points.filter(usable).sort((a, b) => a.x - b.x);
    for (const s of visible) {
      const d = sorted(s)
        .map(
          (p, i) =>
            `${i ? "L" : "M"}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`,
        )
        .join("");
      svg += s.ref
        ? `<path class="ref-line" d="${d}"/>`
        : `<path class="series-line" d="${d}" style="stroke:${s.color}"${s.dash ? ' stroke-dasharray="6 4"' : ""}/>`;
    }
    for (const s of labelled)
      for (const p of sorted(s)) {
        svg += `<circle class="series-dot" cx="${sx(p.x).toFixed(1)}" cy="${sy(p.y).toFixed(1)}" r="4" style="fill:${s.color}"/>`;
      }
    if (endLabels) {
      // label line ends; drop labels that would collide (the legend still names them)
      const ends = labelled
        .map((s) => {
          const p = sorted(s).pop();
          return p && { s, x: sx(p.x), y: sy(p.y) };
        })
        .filter(Boolean);
      ends.forEach((e, i) => {
        if (!ends.some((o, j) => j !== i && Math.abs(o.y - e.y) < 13))
          svg += `<text class="end-label" x="${e.x + 9}" y="${e.y + 4}">${esc(e.s.name)}</text>`;
      });
    }
    svg += `<line class="crosshair" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}" visibility="hidden"/>`;
    svg += `<rect class="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/></svg>`;
    el.innerHTML = svg + legendHtml();
    bindLegend();

    // hover: snap to the nearest instance and list every series there
    const svgEl = el.querySelector("svg"),
      cross = svgEl.querySelector(".crosshair"),
      hit = svgEl.querySelector(".hit");
    const xsUnique = [...new Set(pts.map((p) => p.x))].sort((a, b) => a - b);
    const move = (ev) => {
      const box = svgEl.getBoundingClientRect();
      const px = (ev.clientX - box.left) * (width / box.width);
      let best = xsUnique[0];
      for (const x of xsUnique)
        if (Math.abs(sx(x) - px) < Math.abs(sx(best) - px)) best = x;
      cross.setAttribute("x1", sx(best));
      cross.setAttribute("x2", sx(best));
      cross.setAttribute("visibility", "visible");
      const rows = visible
        .map((s) => ({ s, p: s.points.find((q) => q.x === best) }))
        .filter((r) => r.p)
        .sort((a, b) => b.p.y - a.p.y);
      const head = rows.find((r) => r.p.title)?.p;
      showTooltip(
        `<div class="tt-title">${esc(head?.title || xf(best))}</div>${head?.sub ? `<div class="tt-sub">${esc(head.sub)}</div>` : ""}` +
          rows
            .map(
              ({ s, p }) =>
                `<div class="tt-row"><span>${s.ref ? '<span class="sw ref"></span>' : `<span class="sw" style="background:${s.color}"></span>`}${esc(s.name)}</span><b>${esc(p.label ?? yf(p.y))}</b></div>`,
            )
            .join(""),
        ev.clientX,
        ev.clientY,
      );
    };
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", () => {
      cross.setAttribute("visibility", "hidden");
      hideTooltip();
    });
  };
  function legendHtml() {
    const shown = cfg.series.filter((s) => s.points.length);
    if (cfg.legend === false || shown.length < 2) return "";
    return `<div class="legend">${shown
      .map(
        (s) =>
          `<button type="button" data-series="${esc(s.name)}" aria-pressed="${!hidden.has(s.name)}">` +
          `<span class="key${s.dash || s.ref ? " dash" : ""}" style="border-color:${s.ref ? "var(--muted)" : s.color}"></span>${esc(s.name)}</button>`,
      )
      .join("")}</div>`;
  }
  function bindLegend() {
    el.querySelectorAll(".legend button").forEach((b) =>
      b.addEventListener("click", () => {
        const n = b.dataset.series;
        hidden.has(n) ? hidden.delete(n) : hidden.add(n);
        render();
      }),
    );
  }
  mountChart(el, render);
}
