// Distance along each street polyline, so a vehicle can be placed at any
// fraction of the street it is driving.

export class StreetGeometry {
  constructor(city) {
    this.points = city.s.points;
    this.offsets = city.s.offsets;
    const pointCount = this.points.length / 2;
    this.along = new Float32Array(pointCount); // distance from the street's first point
    for (let k = 0; k < city.count; k++) {
      let total = 0;
      for (let p = this.offsets[k] + 1; p < this.offsets[k + 1]; p++) {
        total += Math.hypot(
          this.points[2 * p] - this.points[2 * p - 2],
          this.points[2 * p + 1] - this.points[2 * p - 1],
        );
        this.along[p] = total;
      }
    }
  }

  length(k) {
    return this.along[this.offsets[k + 1] - 1];
  }

  // Writes x, y (projected metres) and heading (radians, 0 = east) into out.
  pointAt(k, fraction, reverse, out) {
    const first = this.offsets[k];
    const last = this.offsets[k + 1] - 1;
    const total = this.along[last];
    const f = Math.min(Math.max(fraction, 0), 1);
    const d = (reverse ? 1 - f : f) * total;
    // binary search for the segment containing distance d
    let lo = first, hi = last;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (this.along[mid] <= d) lo = mid; else hi = mid;
    }
    const seg = this.along[hi] - this.along[lo];
    const t = seg > 0 ? (d - this.along[lo]) / seg : 0;
    const x0 = this.points[2 * lo], y0 = this.points[2 * lo + 1];
    const x1 = this.points[2 * hi], y1 = this.points[2 * hi + 1];
    out.x = x0 + (x1 - x0) * t;
    out.y = y0 + (y1 - y0) * t;
    out.heading = reverse ? Math.atan2(y0 - y1, x0 - x1) : Math.atan2(y1 - y0, x1 - x0);
    return out;
  }
}
