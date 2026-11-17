/* Data helpers: reading algorithms, runs and instances, and the chart lines and
   tables built from them. */

const algorithms = () => state.data?.algorithms || [];
const getAlg = (name) => algorithms().find((a) => a.name === name);
const inFamily = (run) => state.family === "all" || run.family === state.family;
const profiledFunctions = (name) => state.data?.functions?.[name] || [];
// measured in any mode: a profile-only run still has functions to show
const measuredAlgorithms = () =>
  algorithms().filter((a) => a.runs.length || profiledFunctions(a.name).length);
const FUNCTION_MODES = ["profile", "fmemory"];
const functionsStale = (name) =>
  (getAlg(name)?.stale_modes || []).some((m) => FUNCTION_MODES.includes(m));
const staleTag = (text) =>
  `<span class="tag warn" title="The code or the instance changed since this was measured">${text}</span>`;
const familyInstances = () =>
  (state.data?.instances || []).filter(
    (i) => state.family === "all" || i.family === state.family,
  );

const METRICS = {
  time: {
    field: "seconds",
    fmt: fmtTime,
    label: "Time",
    log: true,
    title: "Solve time",
    sub: "Median wall-clock time of solve(), log–log. A steeper line grows faster.",
  },
  memory: {
    field: "peak_bytes",
    fmt: fmtBytes,
    label: "Memory",
    log: true,
    title: "Peak memory",
    sub: "Most memory Python allocated while solving (tracemalloc), log–log.",
  },
  score: {
    field: "score",
    fmt: fmtScore,
    label: "Score",
    log: false,
    title: "Solution score",
    sub: "Score of the returned solution; higher is better.",
  },
};

function seriesFor(field, fmt, names = null) {
  return algorithms()
    .filter((a) => !names || names.includes(a.name))
    .map((a) => {
      const { color, dash } = seriesStyle(a.name);
      return {
        name: a.name,
        color,
        dash,
        points: a.runs
          .filter(
            (r) =>
              inFamily(r) &&
              r[field] !== null &&
              r[field] !== undefined &&
              (field !== "score" || r.status === "ok"),
          )
          .map((r) => ({
            x: r.streets,
            y: r[field],
            label: fmt(r[field]),
            title: r.instance,
            sub: `${familyLabel(r.family)} · ${fmtInt(r.streets)} streets`,
          })),
      };
    });
}

function instanceTable(field, fmt, names = null) {
  const algs = measuredAlgorithms().filter(
    (a) => !names || names.includes(a.name),
  );
  return (
    `<table><thead><tr><th>Instance</th><th class="num">Streets</th>${algs.map((a) => `<th class="num">${algName(a.name)}</th>`).join("")}</tr></thead><tbody>` +
    familyInstances()
      .map(
        (i) =>
          `<tr><td>${esc(i.name)}</td><td class="num">${fmtInt(i.streets)}</td>` +
          algs
            .map((a) => {
              const r = a.runs.find((x) => x.path === i.path);
              if (!r) return `<td class="num muted">–</td>`;
              if (r[field] === null || r[field] === undefined)
                return `<td class="num">${statusText(r.status)}</td>`;
              return `<td class="num">${esc(fmt(r[field]))}</td>`;
            })
            .join("") +
          "</tr>",
      )
      .join("") +
    "</tbody></table>"
  );
}
