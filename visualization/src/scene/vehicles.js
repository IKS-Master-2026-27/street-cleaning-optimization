// Trucks: one InstancedMesh per S/M/L type.

import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { toWorld } from './world.js';

export const VEHICLE_STYLE = {
  S: { color: 0x4dd0e1, size: [5, 2.6, 2.1] },  // length, height, width in metres
  M: { color: 0xff9800, size: [7, 3.0, 2.4] },
  L: { color: 0xe040fb, size: [9, 3.4, 2.5] },
};
const SELECTED = new THREE.Color(0xffffff);
const FADED = new THREE.Color(0x2a3038);
const dummy = new THREE.Object3D();
const color = new THREE.Color();

// A truck is a cab in front (+x, the driving direction) and a taller tank body behind it.
function truckGeometry([length, height, width]) {
  const box = (l, h, w, x, y) => new THREE.BoxGeometry(l, h, w).translate(x, y + h / 2, 0);
  const cab = length * 0.28, gap = length * 0.04, body = length - cab - gap;
  return mergeGeometries([
    box(cab, height * 0.8, width * 0.95, length / 2 - cab / 2, 0.2),
    box(body, height, width, -length / 2 + body / 2, 0.2),
  ]);
}

export class Vehicles {
  constructor(types, parent) {
    this.group = new THREE.Group();
    parent.add(this.group);
    this.types = types;                       // type of each vehicle
    this.slot = new Uint32Array(types.length);  // its instance index in the type's mesh
    this.meshes = {};
    const counts = {};
    types.forEach((type, v) => { this.slot[v] = counts[type] = (counts[type] ?? -1) + 1; });
    for (const [type, n] of Object.entries(counts)) {
      const style = VEHICLE_STYLE[type];
      const geometry = truckGeometry(style.size);
      const material = new THREE.MeshStandardMaterial({ roughness: 0.55, metalness: 0.1 });
      const mesh = new THREE.InstancedMesh(geometry, material, n + 1);
      mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      mesh.frustumCulled = false;
      mesh.renderOrder = 5;
      mesh.castShadow = true;
      for (let i = 0; i <= n; i++) mesh.setColorAt(i, color.set(style.color));
      mesh.count = n + 1;
      this.meshes[type] = mesh;
      this.group.add(mesh);
    }
    this.selected = -1;
    this.state = { x: 0, y: 0, heading: 0, state: 'depot', step: -1 };
    this.positions = new Float32Array(2 * types.length);
    this.headings = new Float32Array(types.length);  // radians, 0 = east
    this.states = new Uint8Array(types.length);      // 0 at depot, 1 driving, 2 cleaning
  }

  setTypeVisible(type, visible) {
    if (this.meshes[type]) this.meshes[type].visible = visible;
  }

  // Place every vehicle at time t. Trucks that are at the depot (not left yet,
  // or done) are parked at the depot.
  update(replay, time, zoomScale) {
    const out = this.state;
    for (let v = 0; v < this.types.length; v++) {
      const type = this.types[v];
      const mesh = this.meshes[type];
      replay.vehicleAt(v, time, out);
      this.positions[2 * v] = out.x;
      this.positions[2 * v + 1] = out.y;
      this.headings[v] = out.heading;
      this.states[v] = out.state === 'clean' ? 2 : out.state === 'drive' ? 1 : 0;
      const scale = zoomScale * (v === this.selected ? 1.3 : 1);
      toWorld(out.x, out.y, 0.8, dummy.position);
      dummy.rotation.set(0, out.heading, 0);
      dummy.scale.setScalar(scale);
      dummy.updateMatrix();
      mesh.setMatrixAt(this.slot[v], dummy.matrix);
      // bright while cleaning, dimmed while only driving, grey once back at the depot
      color.set(VEHICLE_STYLE[type].color);
      if (out.state === 'drive') color.multiplyScalar(0.5);
      else if (out.state !== 'clean') color.setRGB(0.35, 0.35, 0.38);
      if (v === this.selected) color.copy(SELECTED);
      else if (this.selected >= 0) color.lerp(FADED, 0.75); // focus on the selected truck
      mesh.setColorAt(this.slot[v], color);
    }
    for (const mesh of Object.values(this.meshes)) {
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }
  }

  // Nearest visible truck to (x, y) within radius metres, or -1.
  pick(x, y, radius) {
    let best = -1, bestDistance = radius;
    for (let v = 0; v < this.types.length; v++) {
      if (!this.meshes[this.types[v]].visible) continue;
      const d = Math.hypot(this.positions[2 * v] - x, this.positions[2 * v + 1] - y);
      if (d < bestDistance) { best = v; bestDistance = d; }
    }
    return best;
  }

  dispose() {
    for (const mesh of Object.values(this.meshes)) {
      mesh.geometry.dispose();
      mesh.material.dispose();
      mesh.dispose();
    }
    this.group.removeFromParent();
  }
}
