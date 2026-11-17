/* Start-up: the tabs, the results filter, the sidebar footer, and drawing the page.
   Loaded last, because it uses everything defined before it. */

const TABS = {
  overview: renderOverview,
  algorithms: renderAlgorithms,
  functions: renderFunctions,
  compare: renderCompare,
};
const view = $("#view");

function render() {
  charts.clear();
  hideTooltip();
  if (!TABS[state.tab]) state.tab = "overview";
  document
    .querySelectorAll("#tabs button")
    .forEach((b) =>
      b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)),
    );
  renderFamilies();
  renderMeta();
  renderStats();
  if (!measuredAlgorithms().length) {
    view.innerHTML = `<section class="card empty"><h2>No measurements yet</h2><p>${
      LIVE
        ? "Choose what to measure in the panel on the left and press <b>Run</b>."
        : "Run <code>python -m tools.complexity</code> from the repository root."
    }</p></section>`;
    return;
  }
  TABS[state.tab](view);
  enhanceSelects(view);
}

function renderMeta() {
  const meta = state.data?.meta;
  const pill = $("#mode-pill");
  const running = state.status?.running;
  pill.className = `pill ${LIVE ? (state.serverError ? "" : running ? "running" : "live") : ""}`;
  pill.innerHTML = `<span class="dot"></span>${LIVE ? (state.serverError ? "Offline" : running ? "Measuring" : "Live") : "Snapshot"}`;
  pill.title = meta
    ? `Generated ${new Date(meta.generated).toLocaleString()}`
    : "";
  $("#footer").innerHTML = meta
    ? `Generated ${esc(new Date(meta.generated).toLocaleString())}${LIVE ? "" : "<br>Static snapshot. For live runs: <code>python -m tools.complexity serve</code>"}`
    : "";
}

function renderFamilies() {
  const counts = {};
  for (const i of state.data?.instances || [])
    counts[i.family] = (counts[i.family] || 0) + 1;
  const families = ["all", ...Object.keys(counts)];
  // Families differ in more than size, so fits default to the largest family alone.
  if (!families.includes(state.family) && state.data) {
    // wait for data before choosing
    const biggest = Object.keys(counts).sort(
      (a, b) => counts[b] - counts[a],
    )[0];
    state.family =
      biggest && counts[biggest] >= 3 && families.length > 2 ? biggest : "all";
  }
  $("#family-wrap").hidden = families.length < 3; // only one family: nothing to choose
  const label = (f) =>
    f === "all" ? "All" : /synt/i.test(f) ? "Synthetic" : familyLabel(f);
  $("#family").innerHTML = families
    .map(
      (f) =>
        `<button type="button" data-family="${esc(f)}" aria-pressed="${f === state.family}">${esc(label(f))}</button>`,
    )
    .join("");
}
$("#family").addEventListener("click", (e) => {
  const b = e.target.closest("[data-family]");
  if (!b) return;
  state.family = b.dataset.family;
  store.set("family", state.family);
  render();
});

function setTab(tab) {
  state.tab = tab;
  store.set("tab", tab);
  try {
    history.replaceState(null, "", "#" + tab);
  } catch (_) {}
  render();
  scrollTo({ top: 0 });
}
document
  .querySelectorAll("#tabs button")
  .forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
addEventListener("hashchange", () => {
  const t = location.hash.slice(1);
  if (TABS[t] && t !== state.tab) setTab(t);
});

async function start() {
  const fromHash = location.hash.slice(1);
  if (TABS[fromHash]) state.tab = fromHash;
  render();
  if (!LIVE) return;
  renderRunPanel();
  try {
    const [options, data] = await Promise.all([
      api("/api/options"),
      api("/api/results"),
    ]);
    state.options = options;
    state.data = data;
    initRunSelection();
  } catch (e) {
    state.serverError = e.message;
  }
  renderRunPanel();
  render();
  if (state.options) updateEstimate();
  poll();
}
start();
