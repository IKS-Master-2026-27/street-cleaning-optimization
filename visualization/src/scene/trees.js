// Decorative low-poly trees along the streets. The dataset has no trees, so they
// are placed procedurally (the same for a city every time): rows on both sides
// of the streets, kept off every road and out of every building footprint.
// Two kinds, round and conifer, one InstancedMesh per part.

import * as THREE from 'three';
import { halfWidth } from './streets.js';

const MAX_TREES = 60000;
const ROAD_WIDTH = 2;         // streets are drawn this many times their real width (Road width slider default)
const CELL = 30;              // metres per cell of the lookup grids
const SHOW_BELOW = 4000;      // camera distance (m) above which trees are hidden: too small to see
const CROWN_COLORS = [0x5aa84a, 0x4b9642, 0x72bb55, 0x3f8746, 0x86c063, 0x67a94f];
const TRUNK_COLOR = 0x8a6a4f;

// Small deterministic random generator (mulberry32).
function random(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const key = (cx, cy) => cx * 1048576 + cy;

function addToGrid(grid, item, x0, y0, x1, y1) {
  for (let cx = Math.floor(x0 / CELL); cx <= Math.floor(x1 / CELL); cx++) {
    for (let cy = Math.floor(y0 / CELL); cy <= Math.floor(y1 / CELL); cy++) {
      const k = key(cx, cy);
      const list = grid.get(k);
      if (list) list.push(item); else grid.set(k, [item]);
    }
  }
}

function insideRing(x, y, points, first, last) {
  let inside = false;
  for (let i = first, j = last; i <= last; j = i++) {
    const xi = points[2 * i], yi = points[2 * i + 1], xj = points[2 * j], yj = points[2 * j + 1];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

// Tree positions, sizes and kinds for a city.
function placeTrees(city) {
  const { s, count } = city;
  const widths = city.highways.map(halfWidth);
  // every street segment in a grid, to keep trees off the roads
  const segments = [];
  const segmentGrid = new Map();
  let total = 0;
  for (let k = 0; k < count; k++) {
    const w = widths[s.highway[k]] * ROAD_WIDTH;
    for (let p = s.offsets[k]; p < s.offsets[k + 1] - 1; p++) {
      const x0 = s.points[2 * p], y0 = s.points[2 * p + 1], x1 = s.points[2 * p + 2], y1 = s.points[2 * p + 3];
      total += Math.hypot(x1 - x0, y1 - y0);
      addToGrid(segmentGrid, segments.length / 5, Math.min(x0, x1) - w, Math.min(y0, y1) - w, Math.max(x0, x1) + w, Math.max(y0, y1) + w);
      segments.push(x0, y0, x1, y1, w);
    }
  }
  const onRoad = (x, y) => {
    for (const i of segmentGrid.get(key(Math.floor(x / CELL), Math.floor(y / CELL))) ?? []) {
      const x0 = segments[5 * i], y0 = segments[5 * i + 1], dx = segments[5 * i + 2] - x0, dy = segments[5 * i + 3] - y0;
      const t = Math.max(0, Math.min(1, ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy || 1)));
      if (Math.hypot(x - x0 - t * dx, y - y0 - t * dy) < segments[5 * i + 4] + 1.5) return true;
    }
    return false;
  };
  // building footprints, to keep trees out of them
  const b = city.b;
  const buildingGrid = new Map();
  if (b) {
    for (let i = 0; i < b.height.length; i++) {
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (let p = b.offsets[i]; p < b.offsets[i + 1]; p++) {
        const x = b.points[2 * p], y = b.points[2 * p + 1];
        x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
      }
      addToGrid(buildingGrid, i, x0 - 2, y0 - 2, x1 + 2, y1 + 2);
    }
  }
  const inBuilding = (x, y) => {
    for (const i of buildingGrid.get(key(Math.floor(x / CELL), Math.floor(y / CELL))) ?? []) {
      const first = b.offsets[i], last = b.offsets[i + 1] - 1;
      // a tree is about 2 m wide: test its centre and four points around it
      for (const [ox, oy] of [[0, 0], [2, 0], [-2, 0], [0, 2], [0, -2]]) {
        if (insideRing(x + ox, y + oy, b.points, first, last)) return true;
      }
    }
    return false;
  };

  const rand = random(count * 2654435761 + city.nodes);
  const spacing = Math.max(14, (total * 2 * 0.6) / MAX_TREES);  // ~60 % of both sides planted
  const taken = new Set();  // one tree per 6 m cell, so crossings do not pile up trees
  const trees = [];         // x, y, scale, rotation, kind (0 round, 1 conifer), colour index
  for (let k = 0; k < count && trees.length / 6 < MAX_TREES; k++) {
    const w = widths[s.highway[k]] * ROAD_WIDTH;
    for (let p = s.offsets[k]; p < s.offsets[k + 1] - 1; p++) {
      const x0 = s.points[2 * p], y0 = s.points[2 * p + 1], x1 = s.points[2 * p + 2], y1 = s.points[2 * p + 3];
      const length = Math.hypot(x1 - x0, y1 - y0);
      if (length < 1) continue;
      const nx = -(y1 - y0) / length, ny = (x1 - x0) / length;
      for (let d = rand() * spacing; d < length; d += spacing * (0.7 + rand() * 0.6)) {
        for (const side of [1, -1]) {
          if (rand() > 0.6) continue;
          const offset = w + 2.5 + rand() * 4;
          const x = x0 + ((x1 - x0) * d) / length + side * nx * offset;
          const y = y0 + ((y1 - y0) * d) / length + side * ny * offset;
          const cell = `${Math.floor(x / 6)},${Math.floor(y / 6)}`;
          if (taken.has(cell) || onRoad(x, y) || inBuilding(x, y)) continue;
          taken.add(cell);
          trees.push(x, y, 0.75 + rand() * 0.6, rand() * Math.PI * 2, rand() < 0.25 ? 1 : 0,
            Math.floor(rand() * CROWN_COLORS.length));
        }
      }
    }
  }
  return trees;
}

export class Trees {
  constructor(city, parent) {
    const trees = placeTrees(city);
    const n = trees.length / 6;
    this.count = n;
    const material = new THREE.MeshStandardMaterial({ flatShading: true, roughness: 0.85 });
    const trunkGeometry = new THREE.CylinderGeometry(0.16, 0.26, 2.4, 6).translate(0, 1.2, 0);
    const roundGeometry = new THREE.IcosahedronGeometry(2.1, 1).scale(1, 1.1, 1).translate(0, 3.9, 0);
    const coneGeometry = new THREE.ConeGeometry(1.7, 5, 7).translate(0, 4.1, 0);
    const conifers = trees.filter((_, i) => i % 6 === 4 && trees[i] === 1).length;
    const trunks = new THREE.InstancedMesh(trunkGeometry, material.clone(), Math.max(n, 1));
    const rounds = new THREE.InstancedMesh(roundGeometry, material.clone(), Math.max(n - conifers, 1));
    const cones = new THREE.InstancedMesh(coneGeometry, material.clone(), Math.max(conifers, 1));
    trunks.material.color.set(TRUNK_COLOR);
    const dummy = new THREE.Object3D();
    const color = new THREE.Color();
    let r = 0, c = 0;
    for (let t = 0; t < n; t++) {
      const [x, y, scale, angle, kind, shade] = trees.slice(6 * t, 6 * t + 6);
      dummy.position.set(x, 0, -y);
      dummy.rotation.set(0, angle, 0);
      dummy.scale.set(scale, scale * (kind ? 1.1 : 1), scale);
      dummy.updateMatrix();
      trunks.setMatrixAt(t, dummy.matrix);
      const crown = kind ? cones : rounds;
      const i = kind ? c++ : r++;
      crown.setMatrixAt(i, dummy.matrix);
      crown.setColorAt(i, color.set(CROWN_COLORS[shade]).multiplyScalar(kind ? 0.8 : 1));
    }
    trunks.count = n;
    rounds.count = r;
    cones.count = c;
    this.group = new THREE.Group();
    for (const mesh of [trunks, rounds, cones]) {
      mesh.castShadow = true;
      mesh.computeBoundingSphere();
      this.group.add(mesh);
    }
    this.enabled = true;
    parent.add(this.group);
  }

  // Hidden when switched off or when the camera is too far for trees to show.
  update(cameraDistance) {
    this.group.visible = this.enabled && this.count > 0 && cameraDistance < SHOW_BELOW;
  }
}
