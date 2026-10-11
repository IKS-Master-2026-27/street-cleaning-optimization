// Small DOM helpers: formatting, the truck list and the details card.

import { CAPACITY, CLEANS, REVERSE } from '../loaders/data.js';

export const $ = (selector) => document.querySelector(selector);

export function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

export function hms(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
}

export const percent = (x, digits = 1) => `${(x * 100).toFixed(digits)} %`;

const signed = (x) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(1)} %`;

export function renderTruckList(container, app, onSelect) {
  const { city, replay, solution } = app;
  const limit = city.timeLimit;
  const sumo = solution.meta.sumo;
  const rows = [];
  for (let v = 0; v < city.fleet.length; v++) {
    const end = replay.track.end[v];
    // Δ SUMO: how much longer the truck takes in SUMO than in the solver's timing
    let delay = '';
    if (sumo) {
      const exactEnd = solution.meta.vehicles[v].end, t = sumo.trucks[v];
      delay = t.steps && exactEnd ? `<span class="${t.end > limit ? 'late' : ''}">${signed(t.end / exactEnd - 1)}</span>` : '–';
    }
    rows.push(
      `<div class="truck-row" data-v="${v}"><span>${v}</span><span>${city.fleet[v]}</span>` +
      `<span>${hms(end)}</span><span class="${end > limit ? 'late' : ''}">${((end / limit) * 100).toFixed(0)} %</span>` +
      `<span>${delay}</span></div>`,
    );
  }
  container.innerHTML = rows.join('');
  container.onclick = (event) => {
    const row = event.target.closest('.truck-row');
    if (row) onSelect(Number(row.dataset.v));
  };
}

function streetName(city, k) {
  return city.s.name[k] >= 0 ? city.names[city.s.name[k]] : 'Unnamed street';
}

export function renderDetails(app, selection, typeNames) {
  const { city, replay } = app;
  const { s } = city;
  if (selection.kind === 'street') {
    const k = selection.id;
    const cleanedAt = replay.firstClean[k];
    const by = replay.firstCleaner[k];
    let status = 'Not cleaned in this solution';
    if (by >= 0) {
      status = `${app.time >= cleanedAt ? 'Cleaned' : 'Will be cleaned'} at ${hms(cleanedAt)} by truck #${by} (${city.fleet[by]})`;
    }
    return `<h3>${escapeHtml(streetName(city, k))}</h3><dl>
      <dt>Street</dt><dd>#${k} · ${typeNames[s.type[k]]}</dd>
      <dt>Road class</dt><dd>${escapeHtml(city.highways[s.highway[k]])}</dd>
      <dt>Requirement</dt><dd>capacity ≥ ${s.req[k]}</dd>
      <dt>Length</dt><dd>${s.length[k] || s.meters[k].toFixed(0)} m</dd>
      <dt>Time</dt><dd>${s.time[k]} s</dd>
      <dt>Direction</dt><dd>${s.way[k] === 2 ? 'two-way' : 'one-way'} · junctions ${s.a[k]} → ${s.b[k]}</dd>
      <dt>Status</dt><dd>${status}</dd></dl>`;
  }

  const v = selection.id;
  const t = replay.track;
  const type = t.types[v];
  const end = t.end[v];
  const state = { x: 0, y: 0, heading: 0 };
  replay.vehicleAt(v, app.time, state);
  const doing = {
    depot: 'At the depot, not left yet',
    done: 'Back at the depot',
    clean: `Cleaning ${escapeHtml(streetName(city, t.street[state.step] ?? 0))}`,
    drive: `Driving on ${escapeHtml(streetName(city, t.street[state.step] ?? 0))}`,
  }[state.state];
  const steps = t.offsets[v + 1] - t.offsets[v];
  let total = 0;
  for (let i = t.offsets[v]; i < t.offsets[v + 1]; i++) if (t.flags[i] & CLEANS) total++;
  const step = state.step >= 0
    ? `<dt>Step</dt><dd>${(state.step - t.offsets[v] + 1).toLocaleString()} of ${steps.toLocaleString()}${t.flags[state.step] & REVERSE ? ' · against street order' : ''}</dd>`
    : '';
  const depart = steps ? t.enter[t.offsets[v]] : 0;
  const routeDone = steps ? Math.min(Math.max((app.time - depart) / Math.max(end - depart, 1), 0), 1) : 1;
  const cleanedNow = replay.cleanedBy(v, app.time);
  const shiftEnd = Math.max(city.timeLimit, replay.duration);
  const left = Math.max(end - Math.max(app.time, depart), 0);
  const progress = `<div class="progress">
      ${bar('Route', routeDone, routeDone >= 1 ? 'done' : `${hms(left)} left`)}
      ${bar('Cleaned', total ? cleanedNow / total : 1, `${cleanedNow.toLocaleString()} / ${total.toLocaleString()} streets`, 'clean')}
      <div class="bar-label"><span>Shift</span><span>${hms(app.time)} of ${hms(city.timeLimit)}</span></div>
      <div class="shift" title="The truck's working time within the shift; the line is now">
        <i style="left:${(depart / shiftEnd) * 100}%;width:${((end - depart) / shiftEnd) * 100}%"></i>
        <b style="left:${Math.min(app.time / shiftEnd, 1) * 100}%"></b>
        ${shiftEnd > city.timeLimit ? `<u style="left:${(city.timeLimit / shiftEnd) * 100}%"></u>` : ''}
      </div>
    </div>`;
  return `<h3>Truck #${v} · ${type}</h3>${progress}<dl>
    <dt>Capacity</dt><dd>${CAPACITY[type]}</dd>
    <dt>Route time</dt><dd class="${end > city.timeLimit ? 'late' : ''}">${hms(end)} · ${((end / city.timeLimit) * 100).toFixed(1)} % of T</dd>
    ${sumoRows(app, v)}
    <dt>Now</dt><dd>${doing}</dd>
    ${step}
    </dl>`;
}

function bar(label, fraction, text, kind = '') {
  return `<div class="bar-label"><span>${label}</span><span>${text}</span></div>
    <div class="bar ${kind}"><i style="width:${(fraction * 100).toFixed(1)}%"></i></div>`;
}

// Buttons are rendered apart from the live fields so a click is never lost to a refresh.
export function renderActions(app, selection) {
  if (selection.kind !== 'truck') return '';
  const t = app.replay.track;
  const v = selection.id;
  const steps = t.offsets[v + 1] - t.offsets[v];
  return `<button id="follow">${app.follow ? 'Stop following' : 'Follow (F)'}</button>` +
    (steps ? `<button id="jump-start" data-t="${t.enter[t.offsets[v]]}">Go to departure</button>` : '');
}

// In the details card: the other timing of the same truck (SUMO or the solver's).
function sumoRows(app, v) {
  const { meta } = app.solution;
  const sumo = meta.sumo?.trucks[v];
  if (!sumo || !sumo.steps) return '';
  const exactEnd = meta.vehicles[v].end;
  if (app.mode === 'sumo') return `<dt>Solver time</dt><dd>${hms(exactEnd)}</dd>`;
  return `<dt>SUMO time</dt><dd class="${sumo.end > app.city.timeLimit ? 'late' : ''}">${hms(sumo.end)} (${signed(sumo.end / exactEnd - 1)})</dd>` +
    (sumo.complete ? '' : '<dt></dt><dd class="late">did not finish its route in SUMO</dd>');
}
