// Loads the files written by pipeline/convert.py and pipeline/buildings.py, and
// parses uploaded solution files directly in the browser.

const BASE = 'data/';
const VIEWS = { uint8: Uint8Array, uint32: Uint32Array, int32: Int32Array, float32: Float32Array };
export const CAPACITY = { S: 10, M: 20, L: 30 };
export const TYPE_LETTERS = 'MOC';
export const REVERSE = 1;
export const CLEANS = 2;

function openBuffers(buffer, descriptor) {
  const arrays = {};
  for (const [name, { type, offset, length }] of Object.entries(descriptor)) {
    arrays[name] = new VIEWS[type](buffer, offset, length);
  }
  return arrays;
}

async function fetchOk(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response;
}
const fetchJSON = async (url) => (await fetchOk(url)).json();
const fetchBuffer = async (url) => (await fetchOk(url)).arrayBuffer();

export function loadIndex() {
  return fetchJSON(`${BASE}index.json`);
}

export async function loadCity(directory) {
  const root = `${BASE}${encodeURIComponent(directory)}/`;
  const meta = await fetchJSON(`${root}city.json`);
  const buffer = await fetchBuffer(root + meta.streets.file);
  // buildings are optional (pipeline/buildings.py); the city works without them
  const b = meta.buildings
    ? openBuffers(await fetchBuffer(root + meta.buildings.file), meta.buildings.buffers)
    : null;
  return { ...meta, root, s: openBuffers(buffer, meta.streets.buffers), b, count: meta.streets.count };
}

// A track is what the replay plays: steps of every vehicle plus when each one ends.
function exactTrack(arrays, vehicles) {
  return {
    ...arrays,
    end: Float32Array.from(vehicles, (v) => v.end),
    types: vehicles.map((v) => v.type),
  };
}

export async function loadSolution(city, id) {
  const root = `${city.root}solutions/`;
  const meta = await fetchJSON(`${root}${encodeURIComponent(id)}.json`);
  const exact = exactTrack(openBuffers(await fetchBuffer(root + meta.file), meta.buffers), meta.vehicles);
  return { meta, exact, sumo: null };
}

// The realistic (SUMO) timeline of a solution, loaded on first use: the trucks
// in fleet order, then the background cars.
export async function loadSumoTrack(city, solution) {
  const info = solution.meta.sumo;
  if (!info) return null;
  if (!solution.sumo) {
    const arrays = openBuffers(await fetchBuffer(`${city.root}solutions/${info.file}`), info.buffers);
    const trucks = solution.meta.vehicles.length;
    const types = Array.from({ length: arrays.end.length }, (_, v) => (v < trucks ? city.fleet[v] : 'car'));
    solution.sumo = { ...arrays, types };
  }
  return solution.sumo;
}

// Same rules as pipeline/timeline.py: map junction pairs to streets, add street
// times to a clock, clean a listed street on the vehicle's first traversal.
export function parseSolutionText(text, city, label) {
  const lines = text.split(/\r?\n/);
  const s = city.s;
  const n = city.nodes;
  const lookup = new Map();
  for (let k = 0; k < city.count; k++) {
    lookup.set(s.a[k] * n + s.b[k], k);
    if (s.way[k] === 2 && !lookup.has(s.b[k] * n + s.a[k])) lookup.set(s.b[k] * n + s.a[k], k);
  }
  const count = parseInt(lines[0], 10);
  if (count !== city.fleet.length) {
    throw new Error(`The file has ${lines[0]} vehicles; ${city.name} has ${city.fleet.length}.`);
  }
  const street = [], enter = [], flags = [], offsets = [0], vehicles = [], cleanedLists = [];
  const errors = [];
  for (let v = 0, pos = 1; v < count; v++, pos += 3) {
    const steps = parseInt(lines[pos], 10);
    const junctions = (lines[pos + 1] || '').trim().split(/\s+/).filter(Boolean).map(Number);
    const cleaned = (lines[pos + 2] || '').trim().split(/\s+/).filter(Boolean).map(Number);
    if (Number.isNaN(steps) || junctions.length !== steps + 1) {
      throw new Error(`Vehicle ${v}: ${lines[pos]} steps but ${junctions.length} junctions.`);
    }
    if (junctions[0] !== city.depot.node || junctions[junctions.length - 1] !== city.depot.node) {
      errors.push(`vehicle ${v} does not start and end at the depot`);
    }
    const toClean = new Set(cleaned);
    let clock = 0;
    for (let i = 0; i < steps; i++) {
      const k = lookup.get(junctions[i] * n + junctions[i + 1]);
      if (k === undefined) {
        throw new Error(`Vehicle ${v}: no street from junction ${junctions[i]} to ${junctions[i + 1]}.`);
      }
      let flag = s.a[k] === junctions[i] ? 0 : REVERSE;
      if (toClean.delete(k)) flag |= CLEANS;
      street.push(k); enter.push(clock); flags.push(flag);
      clock += s.time[k];
    }
    if (toClean.size) errors.push(`vehicle ${v} lists ${toClean.size} cleaned streets it never drives`);
    if (clock > city.timeLimit) errors.push(`vehicle ${v} takes ${clock} s, over the limit of ${city.timeLimit} s`);
    const capacity = CAPACITY[city.fleet[v]];
    const tooSmall = cleaned.filter((k) => k < city.count && s.req[k] > capacity);
    if (tooSmall.length) errors.push(`vehicle ${v} (capacity ${capacity}) cleans ${tooSmall.length} streets needing more`);
    offsets.push(street.length);
    vehicles.push({ type: city.fleet[v], steps, end: clock, cleans: cleaned.length });
    cleanedLists.push(cleaned);
  }
  const cleanedByAny = new Set(cleanedLists.flat());
  let uncleaned = 0;
  for (let k = 0; k < city.count; k++) if (s.type[k] === 0 && !cleanedByAny.has(k)) uncleaned++;
  if (uncleaned) errors.push(`${uncleaned} mandatory streets are not cleaned`);
  const meta = {
    id: 'upload', label, steps: street.length, vehicles,
    score: scoreSolution(city, cleanedLists), errors,
  };
  const arrays = {
    offsets: Uint32Array.from(offsets), street: Uint32Array.from(street),
    enter: Float32Array.from(enter), flags: Uint8Array.from(flags),
  };
  return { meta, exact: exactTrack(arrays, vehicles), sumo: null };
}

// The CLIPP score (same as clipp/scoring.py and the external validator).
function scoreSolution(city, cleanedLists) {
  const s = city.s;
  let maxLength = 0, maxWaste = 0, mandatory = 0, optional = 0;
  for (let k = 0; k < city.count; k++) {
    if (s.type[k] === 2) continue;
    maxLength += s.length[k];
    maxWaste += ((30 - s.req[k]) * s.length[k]) / 1000;
    if (s.type[k] === 0) mandatory++; else optional++;
  }
  const cleaned = new Set();
  let waste = 0;
  cleanedLists.forEach((list, v) => {
    for (const k of list) {
      if (k < 0 || k >= city.count || s.type[k] === 2) continue;
      cleaned.add(k);
      waste += ((CAPACITY[city.fleet[v]] - s.req[k]) * s.length[k]) / 1000;
    }
  });
  let length = 0, cleanedMandatory = 0, cleanedOptional = 0;
  for (const k of cleaned) {
    length += s.length[k];
    if (s.type[k] === 0) cleanedMandatory++; else cleanedOptional++;
  }
  const coverage = maxLength ? length / maxLength : 0;
  const efficiency = maxWaste ? 1 - waste / maxWaste : 1;
  return {
    value: city.alpha * coverage + (1 - city.alpha) * efficiency,
    coverage, efficiency, cleanedLength: length, maxLength, waste, maxWaste,
    cleanedMandatory, mandatory, cleanedOptional, optional,
  };
}
