/* The bar chart: horizontal bars with the value at the tip ("Where the time goes"). */

function barChart(el, items, cfg = {}) {
  const render = () => {
    const width = Math.max(260, el.clientWidth || 600);
    const row = 32,
      thick = 14;
    const labelW = Math.min(260, Math.max(120, width * 0.34));
    const iw = width - labelW - 70;
    const max = Math.max(...items.map((i) => i.value), 1e-12);
    let svg = `<svg viewBox="0 0 ${width} ${items.length * row + 4}" role="img" aria-label="${esc(cfg.aria || "bar chart")}">`;
    items.forEach((it, i) => {
      const y = i * row + 2,
        w = Math.max(2, (it.value / max) * iw),
        r = Math.min(4, w / 2);
      const top = y + (row - thick) / 2;
      svg += `<text class="cat-label" x="${labelW - 10}" y="${y + row / 2 + 4}" text-anchor="end">${esc(truncate(it.label, Math.floor(labelW / 7)))}</text>`;
      svg += `<path d="M${labelW},${top} h${w - r} a${r},${r} 0 0 1 ${r},${r} v${thick - 2 * r} a${r},${r} 0 0 1 -${r},${r} h-${w - r} z" style="fill:${it.color || "var(--accent)"}"/>`;
      svg += `<text class="bar-label" x="${labelW + w + 6}" y="${y + row / 2 + 4}">${esc(it.text)}</text>`;
      svg += `<rect class="hitbar" data-i="${i}" x="0" y="${y}" width="${width}" height="${row}" fill="transparent"/>`;
    });
    el.innerHTML = svg + "</svg>";
    el.querySelectorAll(".hitbar").forEach((rect) => {
      const it = items[+rect.dataset.i];
      const show = (ev) =>
        showTooltip(
          `<div class="tt-title mono">${esc(it.label)}</div>${it.sub ? `<div class="tt-sub">${esc(it.sub)}</div>` : ""}` +
            (it.rows || [])
              .map(
                ([k, v]) =>
                  `<div class="tt-row"><span>${esc(k)}</span><b>${v}</b></div>`,
              )
              .join(""),
          ev.clientX,
          ev.clientY,
        );
      rect.addEventListener("pointermove", show);
      rect.addEventListener("pointerleave", hideTooltip);
      if (cfg.onClick) {
        rect.style.cursor = "pointer";
        rect.addEventListener("click", () => cfg.onClick(it));
      }
    });
  };
  mountChart(el, render);
}
const truncate = (s, n) => (s.length > n ? "…" + s.slice(-(n - 1)) : s);
