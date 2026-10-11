// Efficiency numbers of one solution, computed from the replayed timeline.
// They show where an algorithm spends the trucks' time: cleaning, driving
// without cleaning, or waiting at the depot.

import { CLEANS } from '../loaders/data.js';

export function analyse(replay) {
  const { city, track: t } = replay;
  const s = city.s;
  const shift = city.timeLimit;
  const trucks = [];
  let cleanSeconds = 0, driveSeconds = 0, metres = 0, cleanMetres = 0, traversals = 0;
  for (let v = 0; v < replay.trucks; v++) {
    const first = t.offsets[v], last = t.offsets[v + 1];
    let clean = 0, drive = 0, dist = 0;
    for (let i = first; i < last; i++) {
      const span = replay.exitTime(v, i) - t.enter[i];
      const m = s.meters[t.street[i]];
      dist += m;
      if (t.flags[i] & CLEANS) { clean += span; cleanMetres += m; } else drive += span;
    }
    cleanSeconds += clean;
    driveSeconds += drive;
    metres += dist;
    traversals += last - first;
    trucks.push({
      depart: last > first ? t.enter[first] : 0,
      end: t.end[v],
      clean,
      drive,
      km: dist / 1000,
    });
  }
  let repeated = 0, lastMandatory = 0, mandatoryLeft = 0;
  for (let k = 0; k < city.count; k++) {
    repeated += Math.max(replay.timesDriven[k] - 1, 0);
    if (s.type[k] === 0) {
      if (replay.firstCleaner[k] >= 0) lastMandatory = Math.max(lastMandatory, replay.firstClean[k]);
      else mandatoryLeft++;
    }
  }
  const working = cleanSeconds + driveSeconds;
  return {
    trucks,
    km: metres / 1000,
    cleanKm: cleanMetres / 1000,
    driveShare: working ? driveSeconds / working : 0,          // of working time, not cleaning
    utilisation: replay.trucks ? working / (replay.trucks * shift) : 0,  // of the fleet's shift
    idleHours: Math.max(replay.trucks * shift - working, 0) / 3600,
    repeatedShare: traversals ? repeated / traversals : 0,       // traversals of an already driven street
    lastMandatory: mandatoryLeft ? null : lastMandatory,
    mandatoryLeft,
  };
}
