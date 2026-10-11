// Find the street under the mouse with a uniform grid over all polyline
// segments, instead of raycasting millions of triangles.

export class StreetIndex {
  constructor(city, cell = 80) {
    const { s, count } = city;
    this.city = city;
    this.cell = cell;
    const [x0, y0, x1, y1] = city.bounds;
    this.x0 = x0; this.y0 = y0;
    this.cols = Math.max(1, Math.ceil((x1 - x0) / cell) + 1);
    this.rows = Math.max(1, Math.ceil((y1 - y0) / cell) + 1);
    // two passes (count, fill) into flat arrays: cell -> list of segment start points
    const cellCount = new Uint32Array(this.cols * this.rows + 1);
    const visit = (fn) => {
      for (let k = 0; k < count; k++) {
        for (let p = s.offsets[k]; p < s.offsets[k + 1] - 1; p++) {
          const ax = s.points[2 * p], ay = s.points[2 * p + 1];
          const bx = s.points[2 * p + 2], by = s.points[2 * p + 3];
          const c0 = this.col(Math.min(ax, bx)), c1 = this.col(Math.max(ax, bx));
          const r0 = this.row(Math.min(ay, by)), r1 = this.row(Math.max(ay, by));
          for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) fn(r * this.cols + c, k, p);
        }
      }
    };
    visit((cellId) => cellCount[cellId + 1]++);
    for (let i = 1; i < cellCount.length; i++) cellCount[i] += cellCount[i - 1];
    this.start = cellCount;
    const fill = cellCount.slice();
    this.segStreet = new Uint32Array(cellCount[cellCount.length - 1]);
    this.segPoint = new Uint32Array(this.segStreet.length);
    visit((cellId, k, p) => {
      const i = fill[cellId]++;
      this.segStreet[i] = k;
      this.segPoint[i] = p;
    });
  }

  col(x) { return Math.min(this.cols - 1, Math.max(0, Math.floor((x - this.x0) / this.cell))); }
  row(y) { return Math.min(this.rows - 1, Math.max(0, Math.floor((y - this.y0) / this.cell))); }

  // Nearest street to (x, y) within radius metres, among the visible types, or -1.
  nearest(x, y, radius, visibleTypes) {
    const { s } = this.city;
    let best = -1, bestDistance = radius;
    const c0 = this.col(x - radius), c1 = this.col(x + radius);
    const r0 = this.row(y - radius), r1 = this.row(y + radius);
    for (let r = r0; r <= r1; r++) {
      for (let c = c0; c <= c1; c++) {
        const id = r * this.cols + c;
        for (let i = this.start[id]; i < this.start[id + 1]; i++) {
          const k = this.segStreet[i];
          if (!visibleTypes[s.type[k]]) continue;
          const p = this.segPoint[i];
          const d = segmentDistance(x, y, s.points[2 * p], s.points[2 * p + 1],
            s.points[2 * p + 2], s.points[2 * p + 3]);
          if (d < bestDistance) { best = k; bestDistance = d; }
        }
      }
    }
    return best;
  }
}

function segmentDistance(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay;
  const length2 = dx * dx + dy * dy;
  const t = length2 ? Math.min(1, Math.max(0, ((px - ax) * dx + (py - ay) * dy) / length2)) : 0;
  return Math.hypot(px - ax - t * dx, py - ay - t * dy);
}
