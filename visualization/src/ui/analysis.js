// Analysis drawer: efficiency numbers of the solution and a timeline chart with
// one row per truck over the shift (cleaning, driving without cleaning, or at
// the depot). Hover a bar for its times; click to select the truck and jump there.

import { CLEANS } from '../loaders/data.js';
import { hms } from './panel.js';

// Series colours, validated as a pair on the panel surface (dataviz check).
// Driving bars are also thinner, so the two never rely on colour alone.
const CLEANING = '#22a65a';
const DRIVING = '#3987e5';
const TRACK = '#1d232c';     // empty track = at the depot
const GRID = '#262d38';
const MUTED = '#8e98a8';
const LIMIT = '#fdd835';
const ROW = 18, BAR = 12, THIN = 6, LABEL = 58, PAD = 10;

const hhmm = (t) => hms(t).slice(0, 5);

function tickStep(duration) {
  for (const hours of [0.5, 1, 2, 3, 6, 12, 24, 48, 72, 168]) {
    if (duration / (hours * 3600) <= 10) return hours * 3600;
  }
  return 336 * 3600;
}

export class AnalysisDrawer {
  constructor(onPick) {
    this.onPick = onPick;
    this.root = document.querySelector('#analysis');
    this.chart = document.querySelector('#gantt');
    this.overlay = document.querySelector('#gantt-overlay');
    this.axis = document.querySelector('#gantt-axis');
    this.scroll = document.querySelector('#gantt-scroll');
    this.tip = document.querySelector('#gantt-tip');
    this.time = 0;
    this.hover = null;
    this.selected = -1;
    this.overlay.addEventListener('pointermove', (e) => this.pointer(e));
    this.overlay.addEventListener('pointerleave', () => { this.hover = null; this.tip.hidden = true; this.drawOverlay(); });
    this.overlay.addEventListener('click', (e) => {
      const hit = this.hit(e);
      if (hit) this.onPick(hit.v, hit.time);
    });
    window.addEventListener('resize', () => this.isOpen() && this.draw());
  }

  isOpen() {
    return !this.root.hidden;
  }

  toggle(open = !this.isOpen()) {
    this.root.hidden = !open;
    if (open) this.draw();
  }

  // stats: from analyse(); replay: the replay the chart shows
  setData(replay, stats, city) {
    this.replay = replay;
    this.stats = stats;
    this.city = city;
    // merge consecutive steps with the same state into segments [start, end, cleaning]
    const t = replay.track;
    this.segments = [];
    for (let v = 0; v < replay.trucks; v++) {
      const rows = [];
      for (let i = t.offsets[v]; i < t.offsets[v + 1]; i++) {
        const cleaning = (t.flags[i] & CLEANS) !== 0;
        const start = t.enter[i], end = replay.exitTime(v, i);
        const lastRow = rows[rows.length - 1];
        if (lastRow && lastRow[2] === cleaning && Math.abs(lastRow[1] - start) < 1e-3) lastRow[1] = end;
        else rows.push([start, end, cleaning]);
      }
      this.segments.push(rows);
    }
    this.renderKpis();
    if (this.isOpen()) this.draw();
  }

  setTime(time) {
    this.time = time;
    if (this.isOpen()) this.drawOverlay();
  }

  setSelected(v) {
    this.selected = v;
    if (this.isOpen()) {
      this.drawOverlay();
      if (v >= 0) {
        const top = v * ROW, view = this.scroll;
        if (top < view.scrollTop || top + ROW > view.scrollTop + view.clientHeight) {
          view.scrollTop = top - view.clientHeight / 2;
        }
      }
    }
  }

  renderKpis() {
    const s = this.stats;
    const pct = (x) => `${(x * 100).toFixed(1)} %`;
    const tiles = [
      ['Distance driven', `${s.km.toFixed(1)} km`, `${s.cleanKm.toFixed(1)} km of it cleaning`],
      ['Driving without cleaning', pct(s.driveShare), 'of the trucks’ working time'],
      ['Fleet busy', pct(s.utilisation), 'of all trucks’ shift time'],
      ['Waiting at the depot', `${s.idleHours.toFixed(1)} h`, 'truck-hours not used'],
      ['Repeated driving', pct(s.repeatedShare), 'of drives go over a street again'],
      s.lastMandatory === null
        ? ['Mandatory streets', `${s.mandatoryLeft} left`, 'not cleaned in this solution']
        : ['All mandatory done', hms(s.lastMandatory).slice(0, 5), 'time the last one is cleaned'],
    ];
    const box = document.querySelector('#kpis');
    box.replaceChildren(...tiles.map(([label, value, note]) => {
      const tile = document.createElement('div');
      for (const [tag, text] of [['span', label], ['b', value], ['small', note]]) {
        const el = document.createElement(tag);
        el.textContent = text;
        tile.append(el);
      }
      return tile;
    }));
  }

  scale() {
    const width = this.scroll.clientWidth;
    const duration = this.replay.duration;
    const plot = width - LABEL - PAD;
    return { width, plot, x: (time) => LABEL + (time / duration) * plot, duration };
  }

  draw() {
    if (!this.replay) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const { width, plot, x, duration } = this.scale();
    const height = this.replay.trucks * ROW + 4;
    for (const canvas of [this.chart, this.overlay]) {
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
    }
    const ctx = this.chart.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const step = tickStep(duration);
    ctx.fillStyle = GRID;
    for (let t = 0; t <= duration; t += step) ctx.fillRect(Math.round(x(t)), 0, 1, height);
    ctx.font = '11px system-ui, sans-serif';
    ctx.textBaseline = 'middle';
    this.segments.forEach((rows, v) => {
      const y = v * ROW + (ROW - BAR) / 2;
      ctx.fillStyle = MUTED;
      ctx.fillText(`#${v} ${this.city.fleet[v]}`, 4, y + BAR / 2);
      ctx.fillStyle = TRACK;
      roundRect(ctx, LABEL, y, plot, BAR, 3);
      for (const [start, end, cleaning] of rows) {
        const x0 = x(start), w = Math.max(x(end) - x0, 1);
        ctx.fillStyle = cleaning ? CLEANING : DRIVING;
        if (cleaning) ctx.fillRect(x0, y, w, BAR);
        else ctx.fillRect(x0, y + (BAR - THIN) / 2, w, THIN);
      }
    });
    if (duration > this.city.timeLimit) {
      ctx.fillStyle = LIMIT;
      ctx.fillRect(Math.round(x(this.city.timeLimit)), 0, 2, height);
    }
    // axis (stays visible while the rows scroll)
    const axis = this.axis;
    axis.width = width * dpr;
    axis.height = 18 * dpr;
    axis.style.width = `${width}px`;
    const actx = axis.getContext('2d');
    actx.setTransform(dpr, 0, 0, dpr, 0, 0);
    actx.clearRect(0, 0, width, 18);
    actx.font = '11px system-ui, sans-serif';
    actx.fillStyle = MUTED;
    actx.textBaseline = 'middle';
    for (let t = 0; t <= duration; t += step) {
      const label = hhmm(t);
      const w = actx.measureText(label).width;
      actx.fillText(label, Math.min(Math.max(x(t) - w / 2, LABEL), width - w - 2), 9);
    }
    this.drawOverlay();
  }

  drawOverlay() {
    if (!this.replay) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const ctx = this.overlay.getContext('2d');
    const { width, x } = this.scale();
    const height = this.overlay.height / dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    if (this.selected >= 0) {
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1;
      ctx.strokeRect(1.5, this.selected * ROW + 0.5, width - 3, ROW - 1);
    }
    if (this.hover) {
      ctx.fillStyle = 'rgba(255,255,255,0.06)';
      ctx.fillRect(0, this.hover.v * ROW, width, ROW);
    }
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(Math.round(x(Math.min(this.time, this.replay.duration))) - 1, 0, 2, height);
  }

  hit(event) {
    if (!this.replay) return null;
    const rect = this.overlay.getBoundingClientRect();
    const px = event.clientX - rect.left, py = event.clientY - rect.top;
    const { plot, duration } = this.scale();
    const v = Math.floor(py / ROW);
    if (v < 0 || v >= this.replay.trucks || px < LABEL) return null;
    const time = Math.min(Math.max(((px - LABEL) / plot) * duration, 0), duration);
    const segment = this.segments[v].find(([start, end]) => time >= start && time < end) || null;
    return { v, time, segment, x: event.clientX, y: event.clientY };
  }

  pointer(event) {
    const hit = this.hit(event);
    this.hover = hit;
    this.drawOverlay();
    if (!hit) { this.tip.hidden = true; return; }
    // value first (times), then what and who
    const [start, end, cleaning] = hit.segment ?? [];
    const strong = hit.segment ? `${hhmm(start)}–${hhmm(end)}` : hhmm(hit.time);
    const state = hit.segment ? (cleaning ? 'cleaning' : 'driving, not cleaning') : 'at the depot';
    const key = hit.segment ? (cleaning ? CLEANING : DRIVING) : TRACK;
    this.tip.replaceChildren();
    const value = document.createElement('b');
    value.textContent = strong;
    const line = document.createElement('i');
    line.style.background = key;
    const text = document.createElement('span');
    text.textContent = `${state} · truck #${hit.v} (${this.city.fleet[hit.v]}) · click to jump`;
    this.tip.append(value, line, text);
    this.tip.hidden = false;
    this.tip.style.left = `${Math.min(hit.x + 12, window.innerWidth - this.tip.offsetWidth - 8)}px`;
    this.tip.style.top = `${hit.y - 34}px`;
  }
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.fill();
}
