// Plays the solution's timeline: where each truck is at time t, which streets
// are cleaned by then, and the live score.

import { CAPACITY, CLEANS, REVERSE } from '../loaders/data.js';

// index of the last element <= value in arr[lo..hi), or lo - 1 if none
function lastAtMost(arr, value, lo, hi) {
  let a = lo, b = hi;
  while (a < b) {
    const mid = (a + b) >> 1;
    if (arr[mid] <= value) a = mid + 1; else b = mid;
  }
  return a - 1;
}

export class Replay {
  constructor(city, track, geometry) {
    this.city = city;
    this.track = track;
    this.geometry = geometry;
    this.trucks = city.fleet.length;
    this.duration = track.end.reduce((a, b) => Math.max(a, b), city.timeLimit);
    this.buildEvents();
    // how many times trucks drive each street (for the heatmap and the analysis)
    this.timesDriven = new Uint16Array(city.count);
    for (let i = 0; i < track.offsets[this.trucks]; i++) {
      if (this.timesDriven[track.street[i]] < 65535) this.timesDriven[track.street[i]]++;
    }
  }

  exitTime(v, i) {
    const t = this.track;
    return i + 1 < t.offsets[v + 1] ? t.enter[i + 1] : t.end[v];
  }

  // A cleaning event happens when a truck finishes a cleaning traversal.
  buildEvents() {
    const { track: t, city } = this;
    const s = city.s;
    const times = [], streets = [], vehicles = [];
    for (let v = 0; v < this.trucks; v++) {
      for (let i = t.offsets[v]; i < t.offsets[v + 1]; i++) {
        if (t.flags[i] & CLEANS) {
          times.push(this.exitTime(v, i));
          streets.push(t.street[i]);
          vehicles.push(v);
        }
      }
    }
    const order = times.map((_, i) => i).sort((x, y) => times[x] - times[y]);
    const n = order.length;
    this.evTime = new Float64Array(n);
    this.cumLength = new Float64Array(n + 1);
    this.cumWaste = new Float64Array(n + 1);
    this.cumMandatory = new Uint32Array(n + 1);
    this.cumOptional = new Uint32Array(n + 1);
    this.firstClean = new Float64Array(city.count).fill(Infinity);
    this.firstCleaner = new Int32Array(city.count).fill(-1);
    let length = 0, waste = 0, mandatory = 0, optional = 0;
    this.maxLength = 0; this.maxWaste = 0; this.mandatory = 0; this.optional = 0;
    for (let k = 0; k < city.count; k++) {
      if (s.type[k] === 2) continue;
      this.maxLength += s.length[k];
      this.maxWaste += ((30 - s.req[k]) * s.length[k]) / 1000;
      if (s.type[k] === 0) this.mandatory++; else this.optional++;
    }
    order.forEach((e, j) => {
      const k = streets[e];
      this.evTime[j] = times[e];
      if (s.type[k] !== 2) {
        waste += ((CAPACITY[city.fleet[vehicles[e]]] - s.req[k]) * s.length[k]) / 1000;
        if (this.firstCleaner[k] < 0) {
          length += s.length[k];
          if (s.type[k] === 0) mandatory++; else optional++;
        }
      }
      if (this.firstCleaner[k] < 0) {
        this.firstClean[k] = times[e];
        this.firstCleaner[k] = vehicles[e];
      }
      this.cumLength[j + 1] = length;
      this.cumWaste[j + 1] = waste;
      this.cumMandatory[j + 1] = mandatory;
      this.cumOptional[j + 1] = optional;
    });
  }

  eventsUntil(time) {
    return lastAtMost(this.evTime, time, 0, this.evTime.length) + 1;
  }

  statsAt(time) {
    const n = this.eventsUntil(time);
    const coverage = this.maxLength ? this.cumLength[n] / this.maxLength : 0;
    const efficiency = this.maxWaste ? 1 - this.cumWaste[n] / this.maxWaste : 1;
    return {
      events: n,
      length: this.cumLength[n],
      mandatory: this.cumMandatory[n],
      optional: this.cumOptional[n],
      coverage,
      efficiency,
      score: this.city.alpha * coverage + (1 - this.city.alpha) * efficiency,
    };
  }

  // Fills out with x, y, heading and state: 'depot' (not left yet), 'done',
  // 'clean' or 'drive'.
  vehicleAt(v, time, out) {
    const t = this.track;
    const lo = t.offsets[v], hi = t.offsets[v + 1];
    const i = lo < hi ? lastAtMost(t.enter, time, lo, hi) : lo - 1;
    if (i < lo || time >= t.end[v]) {
      out.x = this.city.depot.x;
      out.y = this.city.depot.y;
      out.heading = 0;
      out.state = i < lo ? 'depot' : 'done';
      out.step = -1;
      return out;
    }
    const exit = this.exitTime(v, i);
    const span = exit - t.enter[i];
    const fraction = span > 0 ? (time - t.enter[i]) / span : 1;
    this.geometry.pointAt(t.street[i], fraction, (t.flags[i] & REVERSE) !== 0, out);
    out.state = t.flags[i] & CLEANS ? 'clean' : 'drive';
    out.step = i;
    return out;
  }

  // Streets a truck cleans up to time (for the details panel).
  cleanedBy(v, time) {
    const t = this.track;
    let count = 0;
    for (let i = t.offsets[v]; i < t.offsets[v + 1] && this.exitTime(v, i) <= time; i++) {
      if (t.flags[i] & CLEANS) count++;
    }
    return count;
  }
}
