/* Formatting: times, bytes and numbers, instance group names, colors per algorithm,
   Big O in words, and run status. */

function fmtTime(s) {
  if (s === null || s === undefined || !isFinite(s)) return "–";
  if (s < 1e-3) return `${(s * 1e6).toFixed(s < 1e-5 ? 1 : 0)} µs`;
  if (s < 1) return `${(s * 1e3).toFixed(s < 0.01 ? 2 : 1)} ms`;
  if (s < 120) return `${s.toFixed(2)} s`;
  return `${(s / 60).toFixed(1)} min`;
}
function fmtBytes(b) {
  if (b === null || b === undefined || !isFinite(b)) return "–";
  const units = ["B", "kB", "MB", "GB"];
  let i = 0;
  while (Math.abs(b) >= 1000 && i < units.length - 1) {
    b /= 1000;
    i++;
  }
  return i === 0
    ? `${Math.round(b)} B`
    : `${b.toFixed(b < 10 ? 2 : 1)} ${units[i]}`;
}
const fmtInt = (n) =>
  n === null || n === undefined ? "–" : Math.round(n).toLocaleString("en-US");
function fmtCompact(n) {
  if (n === null || n === undefined) return "–";
  if (Math.abs(n) >= 1e6) return `${+(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e4) return `${+(n / 1e3).toFixed(1)}K`;
  return fmtInt(n);
}
const fmtScore = (v) => (v === null || v === undefined ? "–" : v.toFixed(4));
const fmtPct = (v) =>
  v === null || v === undefined
    ? "–"
    : `${(v * 100).toFixed(v < 0.1 ? 1 : 0)}%`;

function familyLabel(f) {
  if (f === "all") return "All instances";
  if (/synt/i.test(f)) return "Synthetic";
  if (/real_instances_8h/.test(f)) return "Real cities (8 h)";
  if (/real/i.test(f)) return "Real cities";
  return f.replace(/_/g, " ");
}

/* ---------------------------------------------------------------- colors */
// Color follows the algorithm's position in main.py, never its rank on screen.
function algorithmOrder() {
  const names = [];
  for (const a of state.data?.algorithms || []) names.push(a.name);
  for (const a of state.options?.algorithms || [])
    if (!names.includes(a.name)) names.push(a.name);
  return names;
}
function seriesStyle(name) {
  const i = Math.max(0, algorithmOrder().indexOf(name));
  return { color: `var(--s${(i % SLOTS) + 1})`, dash: i >= SLOTS };
}
const swatch = (name, cls = "sw") =>
  `<span class="${cls}" style="background:${seriesStyle(name).color}"></span>`;
const algName = (name) =>
  `<span class="alg-name">${swatch(name)}${esc(name)}</span>`;

/* ------------------------------------------------------- Big O in words */
// "O(n^2 log n)" -> "n² log n"; used wherever a measured class is shown.
function prettyO(model) {
  if (!model) return "";
  let body = model.replace(/^O\((.*)\)$/, "$1");
  if (body === "1") return "constant";
  body = body
    .replace(/sqrt n/g, "√n")
    .replace(/\^2/g, "²")
    .replace(/\^3/g, "³")
    .replace(/\^([\d.]+)/g, "<sup>$1</sup>");
  return body;
}
function fitOf(block) {
  return block?.[state.family]?.fit || block?.all?.fit;
}

function growthCell(block) {
  const fit = fitOf(block);
  if (!fit || !fit.model)
    return `<span class="muted" title="${esc(fit?.reason || "no data")}">–</span>`;
  return `<span class="growth" title="Fitted on ${esc(familyLabel(state.family).toLowerCase())}: grows as n^${fit.slope.toFixed(2)} (R² ${fit.r2})">${prettyO(fit.model)}</span>`;
}
const ICONS = {
  critical:
    '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M7 2h2v8H7zM7 12h2v2H7z"/></svg>',
};
function statusText(status) {
  const cls =
    status === "ok"
      ? "ok"
      : status === "invalid" || status === "error" || status === "timeout"
        ? "bad"
        : "other";
  return `<span class="status ${cls}">${esc(status)}</span>`;
}
