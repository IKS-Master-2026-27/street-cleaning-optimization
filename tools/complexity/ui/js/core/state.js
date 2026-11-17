/* Page state: the data, what the viewer has chosen, and small helpers ($, esc, saved settings). */

const boot = JSON.parse(document.getElementById("boot").textContent);
const LIVE = !!boot.live;
const SLOTS = 8; // validated categorical palette slots (--s1 … --s8)

const store = {
  get(key, fallback) {
    try {
      const v = localStorage.getItem("complexity:" + key);
      return v === null ? fallback : JSON.parse(v);
    } catch (_) {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem("complexity:" + key, JSON.stringify(value));
    } catch (_) {}
  },
};

const state = {
  data: boot.data,
  options: null,
  tab: store.get("tab", "overview"),
  family: store.get("family", null), // null: the family with the most instances
  alg: null,
  metric: {}, // card id -> selected metric
  hidden: {}, // chart id -> Set of hidden series
  tableView: {}, // card id -> showing the table instead of the chart
  fnAlg: null,
  fnQuery: "",
  fnFilter: "own", // own | all
  fnSort: { key: "share", dir: -1 },
  fnLimit: 40,
  expanded: new Set(),
  compare: [null, null],
  run: null,
  status: null,
  eventsNext: 0,
  log: [],
  version: -1,
  serverError: null,
  estimate: null, // the server's plan for the current Run selection
  logOpen: false,
};

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[c],
  );
