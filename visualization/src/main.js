// App controller: loads a city and a solution, wires the scene, the playback
// clock and the side panel together.

import * as THREE from 'three';
import { CAPACITY, TYPE_LETTERS, loadCity, loadIndex, loadSolution, loadSumoTrack, parseSolutionText } from './loaders/data.js';
import { StreetGeometry } from './playback/geometry.js';
import { Replay } from './playback/replay.js';
import { StreetIndex } from './scene/picking.js';
import { buildingsMesh } from './scene/buildings.js';
import { RouteOverlay } from './scene/route.js';
import { Spray } from './scene/spray.js';
import { Trees } from './scene/trees.js';
import { Daylight } from './scene/daylight.js';
import { HEAT_COLORS, HEAT_LABELS, Streets, polylineOverlay } from './scene/streets.js';
import { Vehicles } from './scene/vehicles.js';
import { World, toWorld } from './scene/world.js';
import { analyse } from './playback/analysis.js';
import { AnalysisDrawer } from './ui/analysis.js';
import { $, escapeHtml, hms, percent, renderActions, renderDetails, renderTruckList } from './ui/panel.js';

const TYPE_NAMES = ['Mandatory', 'Optional', 'Connector'];

const world = new World($('#view'));
const daylight = new Daylight(world);
// clicking a bar of the truck timeline selects the truck and jumps to that time
const drawer = new AnalysisDrawer((v, time) => {
  selectTruck(v);
  setTime(time);
});
const app = {
  index: null,
  city: null,
  geometry: null,
  streetIndex: null,
  streets: null,
  solution: null,
  uploads: [],
  replay: null,
  vehicles: null,
  time: 0,
  playing: false,
  speed: 300,
  selection: null,       // { kind: 'street' | 'truck', id }
  follow: false,
  overlay: null,         // outline of the selected street
  route: null,           // RouteOverlay of the selected truck
  streetVisible: [true, true, true],
  vehicleVisible: { S: true, M: true, L: true, car: true },
  mode: 'exact',         // timing: 'exact' (the solver's, what is scored) or 'sumo' (realistic)
  truckSize: 4,
  roadWidth: 2,          // multiplier on the streets' drawn width, set by the Road width slider
  colorMode: 'type',     // street colours: 'type' (and cleaning) or 'heat' (times driven)
  buildings: null,       // mesh of the 3D buildings, when the city has them
  showBuildings: true,
  showTrees: true,
  trees: null,           // decorative trees along the streets
  showSpray: true,
  spray: null,           // water spray particles of cleaning trucks          // multiplier on real vehicle size, set by the Truck size slider
  loadToken: 0,
};

// ---------------------------------------------------------------- loading

function setLoading(message, isError = false) {
  const box = $('#loading');
  box.hidden = !message;
  box.textContent = message || '';
  box.classList.toggle('error', isError);
}

async function init() {
  try {
    app.index = await loadIndex();
  } catch (error) {
    setLoading('No converted cities found. Run: python visualization/pipeline/convert.py data/input/real_instances/Presheva', true);
    return;
  }
  const select = $('#city');
  for (const city of app.index.cities) {
    const option = new Option(
      `${city.name} (${city.country}) · ${city.nodes.toLocaleString()} junctions${city.available ? '' : ' · not converted'}`,
      city.directory,
    );
    option.disabled = !city.available;
    select.add(option);
  }
  const [hashCity, hashSolution] = decodeURIComponent(location.hash.slice(1)).split('/');
  const first = app.index.cities.find((c) => c.available && c.directory === hashCity)
    ?? app.index.cities.find((c) => c.available);
  if (!first) {
    setLoading('No converted cities found. Run visualization/pipeline/convert.py first.', true);
    return;
  }
  select.value = first.directory;
  await openCity(first.directory, hashSolution);
}

async function openCity(directory, solutionId) {
  const token = ++app.loadToken;
  setLoading(`Loading ${directory}…`);
  app.playing = false;
  clearSelection();
  try {
    const city = await loadCity(directory);
    if (token !== app.loadToken) return;
    // stop the frame loop from drawing the old replay while the new city loads
    app.replay = null;
    app.vehicles = null;
    world.clearCity();
    app.city = city;
    app.uploads = [];
    world.buildGround(city);
    world.buildDepot(city);
    app.spray = new Spray(world.cityGroup);
    app.spray.enabled = app.showSpray;
    app.buildings = city.b ? buildingsMesh(city.b) : null;
    if (app.buildings) {
      app.buildings.visible = app.showBuildings;
      world.cityGroup.add(app.buildings);
    }
    $('#show-buildings').disabled = !app.buildings;
    app.geometry = new StreetGeometry(city);
    app.streets = new Streets(city, world.cityGroup);
    app.trees = new Trees(city, world.cityGroup);
    app.trees.enabled = app.showTrees;
    app.streets.group.renderOrder = 1;
    app.streetVisible.forEach((visible, type) => app.streets.setTypeVisible(type, visible));
    app.streets.setColorMode(app.colorMode);
    daylight.setCity(city, world.groundMaterials, app.streets);
    app.streetIndex = new StreetIndex(city);
    world.frameCity(city);
    $('#city-info').innerHTML =
      `${escapeHtml(city.osmName || city.name)} · ${city.count.toLocaleString()} streets ` +
      `(${city.stats.mandatory.toLocaleString()} M / ${city.stats.optional.toLocaleString()} O / ${city.stats.connector.toLocaleString()} C), ` +
      `${city.stats.km.toLocaleString()} km · ${city.fleet.length} trucks · T = ${hms(city.timeLimit)} · UTM ${city.projection.utm}` +
      (city.silo ? ` · silo: ${escapeHtml(JSON.stringify(city.silo))}` : '') +
      (city.demand ? ' · per-street demand present' : '');
    $('#attribution').innerHTML = (city.osmUrl
      ? `<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">${escapeHtml(city.attribution)}</a>`
      : escapeHtml(city.attribution)) +
      (city.buildings ? ` · Buildings: <a href="https://github.com/microsoft/GlobalMLBuildingFootprints" target="_blank" rel="noopener">${escapeHtml(city.buildings.source)}</a>, heights estimated` : '');
    fillSolutionSelect();
    const id = city.solutions.some((s) => s.id === solutionId) ? solutionId : city.solutions[0]?.id;
    await openSolution(id);
  } catch (error) {
    console.error(error);
    if (token === app.loadToken) setLoading(`Could not load ${directory}: ${error.message}`, true);
  }
}

function fillSolutionSelect() {
  const select = $('#solution');
  select.innerHTML = '';
  for (const s of app.city.solutions) select.add(new Option(s.label, s.id));
  app.uploads.forEach((u, i) => select.add(new Option(`Upload: ${u.meta.label}`, `upload:${i}`)));
}

async function openSolution(id) {
  const token = ++app.loadToken;
  setLoading('Loading solution…');
  try {
    const solution = id.startsWith('upload:')
      ? app.uploads[Number(id.slice(7))]
      : await loadSolution(app.city, id);
    if (token !== app.loadToken) return;
    app.solution = solution;
    $('#solution').value = id;
    history.replaceState(null, '', `#${encodeURIComponent(app.city.directory)}/${encodeURIComponent(id.startsWith('upload:') ? '' : id)}`);
    const meta = solution.meta;
    const score = meta.score;
    let info = `${meta.steps.toLocaleString()} steps · score ${score.value.toFixed(6)} ` +
      `(coverage ${percent(score.coverage, 2)}, efficiency ${percent(score.efficiency, 2)})`;
    if (meta.errors?.length) info += `<br><span class="late">Not valid: ${meta.errors.slice(0, 3).map(escapeHtml).join('; ')}</span>`;
    $('#solution-info').innerHTML = info;
    const sumoAvailable = !!meta.sumo;
    $('#mode-sumo').disabled = !sumoAvailable;
    if (!sumoAvailable) app.mode = 'exact';
    $(`#mode-${app.mode}`).checked = true;
    await startReplay();
  } catch (error) {
    console.error(error);
    if (token === app.loadToken) setLoading(`Could not load the solution: ${error.message}`, true);
  }
}

// Build the replay of the open solution, in the chosen timing, and everything drawn from it.
async function startReplay() {
  const { solution } = app;
  const track = app.mode === 'sumo' ? await loadSumoTrack(app.city, solution) : solution.exact;
  if (!track) return;
  const keepTime = app.time;
  app.replay = new Replay(app.city, track, app.geometry);
  app.vehicles?.dispose();
  app.vehicles = new Vehicles(track.types, world.cityGroup);
  for (const [type, visible] of Object.entries(app.vehicleVisible)) app.vehicles.setTypeVisible(type, visible);
  app.streets.setReplay(app.replay);
  drawer.setData(app.replay, analyse(app.replay), app.city);

  // SUMO timing, or an uploaded solution, may run past the time limit T: the yellow mark shows T
  const duration = Math.ceil(app.replay.duration);
  $('#time').max = duration;
  $('#duration').textContent = hms(duration);
  const mark = $('#limit-mark');
  mark.style.display = duration > app.city.timeLimit ? 'block' : 'none';
  mark.style.left = `${(app.city.timeLimit / duration) * 100}%`;

  showModeInfo();
  $('#delay-head').style.visibility = solution.meta.sumo ? 'visible' : 'hidden';
  $('#st-final').textContent = solution.meta.score.value.toFixed(4);
  $('#truck-count').textContent = `(${app.city.fleet.length})`;
  renderTruckList($('#trucks'), app, selectTruck);
  setLoading(null);
  setTime(Math.min(keepTime, duration));
  if (app.selection?.kind === 'truck') selectTruck(app.selection.id, false);
}

function showModeInfo() {
  const { meta } = app.solution;
  const sumo = meta.sumo;
  if (app.mode === 'sumo' && sumo) {
    const delays = sumo.trucks
      .map((t, v) => (t.steps && meta.vehicles[v].end ? t.end / meta.vehicles[v].end - 1 : null))
      .filter((d) => d !== null)
      .sort((a, b) => a - b);
    const median = delays.length ? delays[delays.length >> 1] : 0;
    $('#mode-info').innerHTML =
      `${escapeHtml(sumo.sumoVersion?.replace('Eclipse SUMO sumo ', 'SUMO ') ?? 'SUMO')}, ${escapeHtml(sumo.profile)} profile` +
      `${sumo.cars ? `, ${sumo.cars.toLocaleString()} background cars` : ''}. ` +
      `Median truck delay <b>${median >= 0 ? '+' : ''}${percent(median, 1)}</b>; ` +
      `<span class="${sumo.late ? 'late' : 'ok'}">${sumo.late} of ${sumo.trucks.length} trucks over T</span>` +
      `${sumo.incomplete ? `, ${sumo.incomplete} incomplete` : ''}${sumo.teleports ? `, ${sumo.teleports} teleports` : ''}.`;
  } else {
    $('#mode-info').innerHTML = sumo
      ? "The solver's timing: what the validator scores. Realistic shows the same routes driven in Eclipse SUMO."
      : "The solver's timing: what the validator scores. Realistic mode: <code>build.py &lt;City&gt; --sumo</code>.";
  }
}

// ---------------------------------------------------------------- time

let lastPanelUpdate = 0;

function setTime(t, fromSlider = false) {
  app.time = Math.max(0, Math.min(t, app.replay.duration));
  app.streets.setTime(app.time);
  drawer.setTime(app.time);
  if (!fromSlider) $('#time').value = app.time;
  $('#clock').textContent = hms(app.time);
  const now = performance.now();
  if (now - lastPanelUpdate > 120 || !app.playing) {
    lastPanelUpdate = now;
    updateStats();
    if (app.selection) refreshDetails();
  }
}

function updateStats() {
  const r = app.replay;
  const s = r.statsAt(app.time);
  $('#st-mandatory').textContent = `${s.mandatory.toLocaleString()} / ${r.mandatory.toLocaleString()}`;
  $('#st-optional').textContent = `${s.optional.toLocaleString()} / ${r.optional.toLocaleString()}`;
  $('#st-length').textContent = `${(s.length / 1000).toFixed(1)} km`;
  $('#st-coverage').textContent = percent(s.coverage, 2);
  $('#st-efficiency').textContent = percent(s.efficiency, 2);
  $('#st-score').textContent = s.score.toFixed(4);
  let active = 0;
  const t = r.track;
  for (let v = 0; v < r.trucks; v++) {
    if (t.offsets[v + 1] > t.offsets[v] && app.time >= t.enter[t.offsets[v]] && app.time < t.end[v]) active++;
  }
  $('#st-active').textContent = `${active} / ${r.trucks}`;
}

function setPlaying(playing) {
  app.playing = playing;
  if (playing && app.time >= app.replay.duration) setTime(0);
  $('#play').textContent = playing ? '❚❚' : '▶';
  $('#play').setAttribute('aria-label', playing ? 'Pause' : 'Play');
}

// ---------------------------------------------------------------- selection

function clearOverlay() {
  if (app.overlay) {
    app.overlay.removeFromParent();
    app.overlay.geometry.dispose();
    app.overlay.material.dispose();
    app.overlay = null;
  }
  app.route?.dispose();
  app.route = null;
}

function clearSelection() {
  app.selection = null;
  app.follow = false;
  clearOverlay();
  if (app.vehicles) app.vehicles.selected = -1;
  drawer.setSelected(-1);
  $('#details').hidden = true;
  document.querySelectorAll('.truck-row.selected').forEach((row) => row.classList.remove('selected'));
}

function selectTruck(v, scroll = true) {
  clearOverlay();
  app.selection = { kind: 'truck', id: v };
  app.vehicles.selected = v;
  drawer.setSelected(v);
  // focus: the route split into driven (bright) and still ahead (faint); other trucks fade
  app.route = new RouteOverlay(app.city, app.replay, app.geometry, v);
  world.cityGroup.add(app.route.mesh);
  document.querySelectorAll('.truck-row').forEach((row) => {
    row.classList.toggle('selected', Number(row.dataset.v) === v);
    if (scroll && Number(row.dataset.v) === v) {
      // scroll only the list, not the whole panel
      const list = row.parentElement;
      if (row.offsetTop < list.scrollTop || row.offsetTop + row.offsetHeight > list.scrollTop + list.clientHeight) {
        list.scrollTop = row.offsetTop - list.clientHeight / 2;
      }
    }
  });
  refreshDetails(true);
}

function selectStreet(k) {
  clearSelection();
  app.selection = { kind: 'street', id: k };
  app.overlay = polylineOverlay(app.city, [k], 0xff6a00, 2);
  world.cityGroup.add(app.overlay);
  refreshDetails(true);
}

function refreshDetails(withActions = false) {
  const sel = app.selection;
  if (!sel) return;
  $('#details').hidden = false;
  $('#details-body').innerHTML = renderDetails(app, sel, TYPE_NAMES);
  if (!withActions) return;
  $('#details-actions').innerHTML = renderActions(app, sel);
  const followButton = $('#follow');
  if (followButton) followButton.onclick = toggleFollow;
  const startButton = $('#jump-start');
  if (startButton) startButton.onclick = () => setTime(Number(startButton.dataset.t));
}

function toggleFollow() {
  app.follow = !app.follow;
  refreshDetails(true);
}

// Back to the whole city seen from above (stops following a truck).
function topView() {
  if (!app.city) return;
  if (app.follow) toggleFollow();
  world.frameCity(app.city);
}

// ---------------------------------------------------------------- picking

const raycaster = new THREE.Raycaster();
const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
const hit = new THREE.Vector3();

function groundPoint(event) {
  const rect = world.renderer.domElement.getBoundingClientRect();
  const ndc = new THREE.Vector2(
    ((event.clientX - rect.left) / rect.width) * 2 - 1,
    -((event.clientY - rect.top) / rect.height) * 2 + 1,
  );
  raycaster.setFromCamera(ndc, world.camera);
  return raycaster.ray.intersectPlane(groundPlane, hit) ? { x: hit.x, y: -hit.z } : null;
}

function pickAt(event) {
  const p = groundPoint(event);
  if (!p || !app.replay) return null;
  // about 8 pixels around the cursor, whatever the zoom
  const radius = (8 * world.camera.position.distanceTo(world.controls.target) * 0.83) / canvas.clientHeight;
  // a truck can be picked anywhere on its (scaled) body
  const truckRadius = 5 * world.vehicleScale(app.truckSize);
  const truck = app.vehicles.pick(p.x, p.y, Math.max(radius, truckRadius));
  if (truck >= 0) return { kind: 'truck', id: truck };
  // anywhere on the (widened) street ribbon counts
  const roadRadius = 3 * world.zoomScale(3000) * app.roadWidth;
  const street = app.streetIndex.nearest(p.x, p.y, Math.max(radius, roadRadius, 4), app.streetVisible);
  return street >= 0 ? { kind: 'street', id: street } : null;
}

function tooltipText(target) {
  if (target.kind === 'truck') {
    const type = app.replay.track.types[target.id];
    return `Truck #${target.id} · ${type} (capacity ${CAPACITY[type]})`;
  }
  const { s, names } = app.city;
  const k = target.id;
  const name = s.name[k] >= 0 ? names[s.name[k]] : 'Unnamed street';
  const cleaned = app.replay.firstClean[k] <= app.time ? ' · cleaned' : '';
  const driven = app.colorMode === 'heat' ? ` · driven ${app.replay.timesDriven[k]}×` : '';
  return `${name} · ${TYPE_LETTERS[s.type[k]]} · ${app.city.highways[s.highway[k]]}${cleaned}${driven}`;
}

let hoverPending = false;
const canvas = world.renderer.domElement;
canvas.addEventListener('pointermove', (event) => {
  if (hoverPending || event.buttons) {
    $('#tooltip').hidden = true;
    return;
  }
  hoverPending = true;
  requestAnimationFrame(() => {
    hoverPending = false;
    const target = pickAt(event);
    const tip = $('#tooltip');
    tip.hidden = !target;
    canvas.style.cursor = target ? 'pointer' : '';
    if (target) {
      tip.textContent = tooltipText(target);
      tip.style.left = `${event.clientX + 14}px`;
      tip.style.top = `${event.clientY + 12}px`;
    }
  });
});
canvas.addEventListener('pointerleave', () => { $('#tooltip').hidden = true; });

let downAt = null;
canvas.addEventListener('pointerdown', (event) => { downAt = { x: event.clientX, y: event.clientY }; });
canvas.addEventListener('pointerup', (event) => {
  if (!downAt || Math.hypot(event.clientX - downAt.x, event.clientY - downAt.y) > 4) return;
  const target = pickAt(event);
  if (!target) clearSelection();
  else if (target.kind === 'truck') selectTruck(target.id);
  else selectStreet(target.id);
});

// ---------------------------------------------------------------- uploads

async function loadUpload(file) {
  if (!app.city) return;
  setLoading(`Reading ${file.name}…`);
  try {
    const text = await file.text();
    const solution = parseSolutionText(text, app.city, file.name);
    app.uploads.push(solution);
    fillSolutionSelect();
    await openSolution(`upload:${app.uploads.length - 1}`);
  } catch (error) {
    setLoading(`${file.name}: ${error.message}`, true);
    setTimeout(() => setLoading(null), 6000);
  }
}

$('#upload').addEventListener('change', (event) => {
  const file = event.target.files[0];
  if (file) loadUpload(file);
  event.target.value = '';
});
let dragDepth = 0;
window.addEventListener('dragenter', (event) => { event.preventDefault(); dragDepth++; $('#drop').hidden = false; });
window.addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; $('#drop').hidden = true; } });
window.addEventListener('dragover', (event) => event.preventDefault());
window.addEventListener('drop', (event) => {
  event.preventDefault();
  dragDepth = 0;
  $('#drop').hidden = true;
  const file = event.dataTransfer.files[0];
  if (file) loadUpload(file);
});

// ---------------------------------------------------------------- controls

$('#city').addEventListener('change', (event) => openCity(event.target.value));
$('#solution').addEventListener('change', (event) => openSolution(event.target.value));
$('#play').addEventListener('click', () => setPlaying(!app.playing));
document.querySelectorAll('input[name="mode"]').forEach((radio) => {
  radio.addEventListener('change', () => {
    app.mode = radio.value;
    startReplay();
  });
});
$('#analysis-toggle').addEventListener('click', () => drawer.toggle());
$('#top-view').addEventListener('click', topView);
// Zoom control: the view's width in metres, presets, and - / + (halve or double the width)
function zoomBy(factor) {
  if (!app.city) return;
  world.setViewWidth(world.viewWidth() * factor);
  showViewWidth(); // right away, not only at the next frame
}
$('#zoom-in').addEventListener('click', () => zoomBy(0.5));
$('#zoom-out').addEventListener('click', () => zoomBy(2));
$('#zoom-width').addEventListener('change', (event) => {
  const value = event.target.value;
  if (value === 'city') topView();
  else if (value && app.city) world.setViewWidth(Number(value));
  showViewWidth();
  event.target.value = ''; // show the current width again
});
$('#analysis-close').addEventListener('click', () => drawer.toggle(false));
$('#time').addEventListener('input', (event) => setTime(Number(event.target.value), true));
$('#speed').addEventListener('change', (event) => { app.speed = Number(event.target.value); });
$('#details-close').addEventListener('click', clearSelection);
// Size sliders (truck size, road width): remembered per browser; storage may be
// unavailable (e.g. private windows), then the defaults are used.
function bindSlider(id, key) {
  const input = $(`#${id}`);
  const show = (value) => {
    app[key] = value;
    input.value = value;
    $(`#${id}-value`).textContent = `×${value}`;
  };
  try {
    const saved = Number(localStorage.getItem(key));
    if (saved >= Number(input.min) && saved <= Number(input.max)) show(saved);
  } catch { /* keep the default */ }
  input.addEventListener('input', () => {
    show(Number(input.value));
    try { localStorage.setItem(key, String(app[key])); } catch { /* not saved */ }
  });
}
bindSlider('truck-size', 'truckSize');
bindSlider('road-width', 'roadWidth');
document.querySelectorAll('[data-street]').forEach((box) => {
  box.addEventListener('change', () => {
    app.streetVisible[Number(box.dataset.street)] = box.checked;
    app.streets?.setTypeVisible(Number(box.dataset.street), box.checked);
  });
});
$('#heat-legend').innerHTML = HEAT_COLORS
  .map((color, i) => `<i class="sw" style="background:${color}"></i>${HEAT_LABELS[i]}`).join(' ');
document.querySelectorAll('input[name="color-mode"]').forEach((radio) => {
  radio.addEventListener('change', () => {
    app.colorMode = radio.value;
    app.streets?.setColorMode(app.colorMode);
    $('#heat-legend').hidden = app.colorMode !== 'heat';
    $('#type-legend').hidden = app.colorMode === 'heat';
  });
});
$('#show-daylight').addEventListener('change', (event) => {
  daylight.enabled = event.target.checked;
});
$('#show-spray').addEventListener('change', (event) => {
  app.showSpray = event.target.checked;
  if (app.spray) app.spray.enabled = app.showSpray;
});
$('#show-trees').addEventListener('change', (event) => {
  app.showTrees = event.target.checked;
  if (app.trees) app.trees.enabled = app.showTrees;
});
$('#show-buildings').addEventListener('change', (event) => {
  app.showBuildings = event.target.checked;
  if (app.buildings) app.buildings.visible = app.showBuildings;
});
document.querySelectorAll('[data-vehicle]').forEach((box) => {
  box.addEventListener('change', () => {
    app.vehicleVisible[box.dataset.vehicle] = box.checked;
    app.vehicles?.setTypeVisible(box.dataset.vehicle, box.checked);
  });
});
window.addEventListener('keydown', (event) => {
  if (event.target.tagName === 'INPUT' && event.target.type !== 'range') return;
  if (event.target.tagName === 'SELECT') return;
  if (event.code === 'Space') { event.preventDefault(); if (app.replay) setPlaying(!app.playing); }
  if (event.code === 'Escape') clearSelection();
  if (event.code === 'KeyR') topView();
  if (event.code === 'KeyA' && app.replay) drawer.toggle();
  if (event.code === 'Equal' || event.code === 'NumpadAdd') zoomBy(0.5);
  if (event.code === 'Minus' || event.code === 'NumpadSubtract') zoomBy(2);
  if (event.code === 'KeyF' && app.selection?.kind === 'truck') toggleFollow();
});

// ---------------------------------------------------------------- frame loop

const followTarget = new THREE.Vector3();
let last = performance.now();
function frame(now) {
  const dt = Math.min((now - last) / 1000, 0.25);
  last = now;
  if (app.replay) {
    if (app.playing) {
      const next = app.time + dt * app.speed;
      setTime(next);
      if (next >= app.replay.duration) setPlaying(false);
    }
    const roadScale = world.zoomScale(3000) * app.roadWidth;
    app.streets.setWidthScale(roadScale);
    app.route?.update(app.time, roadScale);
    const vehicleScale = world.vehicleScale(app.truckSize);
    app.vehicles.update(app.replay, app.time, vehicleScale);
    app.spray.update(dt, app.vehicles, vehicleScale, world.camera, world.renderer.domElement.height);
    world.depot.scale.setScalar(world.zoomScale(700));
    if (app.follow && app.selection?.kind === 'truck') {
      const v = app.selection.id;
      const p = app.vehicles.positions;
      toWorld(p[2 * v], p[2 * v + 1], 0, followTarget);
      const delta = followTarget.sub(world.controls.target).multiplyScalar(0.25);
      world.controls.target.add(delta);
      world.camera.position.add(delta);
    }
  }
  world.controls.update();
  world.updateFog();
  showViewWidth();
  app.trees?.update(world.camera.position.distanceTo(world.controls.target));
  const hour = daylight.update(app.replay ? app.time : 0);
  const clockText = hour === null ? '' : `${String(Math.floor(hour)).padStart(2, '0')}:${String(Math.floor((hour % 1) * 60)).padStart(2, '0')}`;
  if ($('#daytime').textContent !== clockText) $('#daytime').textContent = clockText;
  world.renderer.render(world.scene, world.camera);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
init();

// The current view width, rounded the way a map scale is ("≈ 850 m", "≈ 2.4 km").
let shownWidth = '';
function showViewWidth() {
  const m = world.viewWidth();
  const text = m < 1000
    ? `≈ ${m < 100 ? Math.round(m / 5) * 5 : Math.round(m / 10) * 10} m`
    : `≈ ${m < 10000 ? (m / 1000).toFixed(1) : Math.round(m / 1000)} km`;
  if (text !== shownWidth) {
    shownWidth = text;
    $('#zoom-current').textContent = text;
  }
}

// Typing another city or solution after '#' in the address bar switches to it.
window.addEventListener('hashchange', () => {
  if (!app.index || !app.city) return;
  const [city, solution] = decodeURIComponent(location.hash.slice(1)).split('/');
  const entry = app.index.cities.find((c) => c.available && c.directory === city);
  if (entry && city !== app.city.directory) {
    $('#city').value = city;
    openCity(city, solution);
  } else if (city === app.city.directory && solution && solution !== app.solution?.meta.id
    && app.city.solutions.some((s) => s.id === solution)) {
    openSolution(solution);
  }
});
