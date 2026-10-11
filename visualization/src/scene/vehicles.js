// Trucks (S/M/L street cleaners) and SUMO background cars, drawn as glossy toy
// models. Each vehicle type is three InstancedMeshes sharing the same matrices:
// the body (coloured per instance), the trim (wheels, windows, lights; fixed
// colours) and a soft round shadow on the road.

import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { toWorld } from './world.js';

export const VEHICLE_STYLE = {
  S: { color: 0x22c3d6, size: [5, 2.6, 2.1], axles: 2 },  // length, height, width in metres
  M: { color: 0xff9314, size: [7, 3.0, 2.4], axles: 3 },
  L: { color: 0xd94ff0, size: [9, 3.4, 2.5], axles: 3 },
  car: { color: 0xa9b1bc, size: [4.4, 1.75, 1.9], axles: 2 },  // background traffic of the realistic mode
};
const TRIM = {
  tyre: new THREE.Color(0x24272d),
  glass: new THREE.Color(0x1b2633),
  chassis: new THREE.Color(0x3a3f47),
  metal: new THREE.Color(0xb7bec7),
  beacon: new THREE.Color(0xffb300),
  light: new THREE.Color(0xfff6d8),
};
const FADED = new THREE.Color(0xc9ced5);  // other trucks while one is selected
const PALE = new THREE.Color(0xe6e9ed);   // trucks driving without cleaning are washed out
const dummy = new THREE.Object3D();
const color = new THREE.Color();

// Geometry with every vertex painted one colour (for the merged trim mesh).
function painted(geometry, paint) {
  const g = geometry.index ? geometry.toNonIndexed() : geometry;
  for (const name of Object.keys(g.attributes)) if (!['position', 'normal'].includes(name)) g.deleteAttribute(name);
  const colors = new Float32Array(g.attributes.position.count * 3);
  for (let i = 0; i < colors.length; i += 3) colors.set([paint.r, paint.g, paint.b], i);
  g.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  return g;
}

function plain(geometry) {
  const g = geometry.index ? geometry.toNonIndexed() : geometry;
  for (const name of Object.keys(g.attributes)) if (!['position', 'normal'].includes(name)) g.deleteAttribute(name);
  return g;
}

function wheels(xs, radius, width, trackWidth) {
  const parts = [];
  for (const x of xs) {
    for (const side of [1, -1]) {
      parts.push(new THREE.CylinderGeometry(radius, radius, width, 12).rotateX(Math.PI / 2)
        .translate(x, radius, side * (trackWidth / 2 - width / 2)));
    }
  }
  return parts;
}

// Street cleaner: rounded cab in front (+x, the driving direction) and a
// water tank behind it, on 2 or 3 axles, with a spray bar and a roof beacon.
function truckParts([length, height, width], axles) {
  const r = height * 0.17;                       // wheel radius
  const floor = r * 1.15;                         // bottom of cab and tank
  const cabL = length * 0.3, cabH = height - floor;
  const cabX = length / 2 - cabL / 2;
  const tankR = Math.min((height - floor) * 0.45, width * 0.47);
  const tankL = length - cabL - 0.25;
  const tankX = -length / 2 + tankL / 2;
  const body = [
    new RoundedBoxGeometry(cabL, cabH, width * 0.96, 2, Math.min(cabL, cabH) * 0.22).translate(cabX, floor + cabH / 2, 0),
    new THREE.CapsuleGeometry(tankR, Math.max(tankL - 2 * tankR, 0.1), 4, 14).rotateZ(Math.PI / 2)
      .translate(tankX, floor + 0.12 + tankR, 0),
  ];
  const wheelXs = axles === 3
    ? [cabX, -length / 2 + r * 1.3, -length / 2 + r * 3.5]
    : [cabX, -length / 2 + r * 1.6];
  const glassH = cabH * 0.36, glassY = floor + cabH * 0.68;
  const trim = [
    ...wheels(wheelXs, r, width * 0.2, width).map((g) => painted(g, TRIM.tyre)),
    painted(new THREE.BoxGeometry(length * 0.94, r * 0.7, width * 0.7).translate(0, floor - r * 0.2, 0), TRIM.chassis),
    painted(new THREE.BoxGeometry(0.06, glassH, width * 0.8).translate(length / 2 + 0.005, glassY, 0), TRIM.glass),
    painted(new THREE.BoxGeometry(cabL * 0.55, glassH * 0.9, width * 0.98).translate(cabX + cabL * 0.12, glassY, 0), TRIM.glass),
    painted(new THREE.CylinderGeometry(0.09, 0.09, width * 1.15, 8).rotateX(Math.PI / 2)
      .translate(length / 2 + 0.1, r * 0.55, 0), TRIM.metal),
    painted(new RoundedBoxGeometry(0.28, 0.22, 0.5, 2, 0.08).translate(cabX, floor + cabH + 0.1, 0), TRIM.beacon),
    ...[1, -1].map((side) => painted(new THREE.BoxGeometry(0.05, 0.18, 0.32)
      .translate(length / 2 + 0.01, floor + cabH * 0.22, side * width * 0.33), TRIM.light)),
  ];
  return { body, trim };
}

// Bubble car: a rounded body with a dome cabin; the dome is dark glass with a
// body-coloured roof on top, so the windows show as a band around it.
function carParts([length, height, width]) {
  const r = height * 0.2, floor = r * 0.9;
  const bodyH = height * 0.45;
  const dome = (sx, sy, sz) => new THREE.SphereGeometry(1, 16, 6, 0, Math.PI * 2, 0, Math.PI / 2)
    .scale(sx, sy, sz).translate(-length * 0.06, floor + bodyH * 0.9, 0);
  const body = [
    new RoundedBoxGeometry(length, bodyH, width, 2, bodyH * 0.45).translate(0, floor + bodyH / 2, 0),
    dome(length * 0.3, (height - floor - bodyH * 0.9) * 1.15, width * 0.4),
  ];
  const trim = [
    ...wheels([length * 0.3, -length * 0.3], r, width * 0.2, width * 1.02).map((g) => painted(g, TRIM.tyre)),
    painted(dome(length * 0.335, (height - floor - bodyH * 0.9) * 0.95, width * 0.455), TRIM.glass),
    ...[1, -1].map((side) => painted(new THREE.SphereGeometry(0.13, 6, 4).scale(0.5, 1, 1)
      .translate(length / 2 - 0.02, floor + bodyH * 0.6, side * width * 0.3), TRIM.light)),
  ];
  return { body, trim };
}

// A soft dark disc texture for the shadow under each vehicle.
let shadowTexture = null;
function blobTexture() {
  if (shadowTexture) return shadowTexture;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 64;
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  gradient.addColorStop(0, 'rgba(0,0,0,1)');
  gradient.addColorStop(0.55, 'rgba(0,0,0,0.6)');
  gradient.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 64, 64);
  shadowTexture = new THREE.CanvasTexture(canvas);
  return shadowTexture;
}

export class Vehicles {
  constructor(types, parent) {
    this.group = new THREE.Group();
    parent.add(this.group);
    this.types = types;                       // type of each vehicle
    this.meshes = {};                         // a Group per type (its visibility = the type's)
    this.parts = {};                          // [body, trim, shadow] InstancedMeshes per type
    const counts = {};
    types.forEach((type) => { counts[type] = (counts[type] ?? 0) + 1; });
    for (const [type, n] of Object.entries(counts)) {
      const style = VEHICLE_STYLE[type];
      const [length, , width] = style.size;
      const { body, trim } = type === 'car' ? carParts(style.size) : truckParts(style.size, style.axles);
      const bodyMesh = new THREE.InstancedMesh(
        mergeGeometries(body.map(plain)),
        new THREE.MeshPhysicalMaterial({ roughness: 0.32, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.12 }),
        n,
      );
      const trimMesh = new THREE.InstancedMesh(
        mergeGeometries(trim),
        new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.45, metalness: 0.1 }),
        n,
      );
      const shadowMesh = new THREE.InstancedMesh(
        new THREE.PlaneGeometry(length * 1.3, width * 1.9).rotateX(-Math.PI / 2),
        new THREE.MeshBasicMaterial({ color: 0x000000, alphaMap: blobTexture(), transparent: true, opacity: 0.32, depthWrite: false }),
        n,
      );
      for (const mesh of [bodyMesh, trimMesh, shadowMesh]) {
        mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        mesh.frustumCulled = false;
      }
      bodyMesh.renderOrder = trimMesh.renderOrder = 5;
      shadowMesh.renderOrder = 4;
      // thousands of SUMO cars would make the shadow pass slow: they keep only the soft disc
      bodyMesh.castShadow = trimMesh.castShadow = type !== 'car';
      for (let i = 0; i < n; i++) bodyMesh.setColorAt(i, color.set(style.color));
      const typeGroup = new THREE.Group();
      typeGroup.add(shadowMesh, bodyMesh, trimMesh);
      this.meshes[type] = typeGroup;
      this.parts[type] = [bodyMesh, trimMesh, shadowMesh];
      this.group.add(typeGroup);
    }
    this.selected = -1;
    this.state = { x: 0, y: 0, heading: 0, state: 'depot', step: -1 };
    this.positions = new Float32Array(2 * types.length);
    this.headings = new Float32Array(types.length);  // radians, 0 = east
    this.states = new Uint8Array(types.length);      // 0 at depot, 1 driving, 2 cleaning
    this.visible = new Uint8Array(types.length);     // cars are hidden outside their trip
  }

  setTypeVisible(type, visible) {
    if (this.meshes[type]) this.meshes[type].visible = visible;
  }

  // Place every vehicle at time t. Trucks that are at the depot (not left yet,
  // or done) are parked at the depot; cars outside their trip are hidden.
  // Only vehicles on the map are drawn: they fill the first instances of their
  // type's meshes, so cars waiting for their trip cost nothing on the GPU.
  update(replay, time, zoomScale) {
    const out = this.state;
    const used = {};
    for (const type of Object.keys(this.parts)) used[type] = 0;
    for (let v = 0; v < this.types.length; v++) {
      const type = this.types[v];
      const [body, trim, shadow] = this.parts[type];
      replay.vehicleAt(v, time, out);
      const hidden = type === 'car' && out.state !== 'clean' && out.state !== 'drive';
      this.visible[v] = hidden ? 0 : 1;
      this.positions[2 * v] = out.x;
      this.positions[2 * v + 1] = out.y;
      this.headings[v] = out.heading;
      this.states[v] = out.state === 'clean' ? 2 : out.state === 'drive' ? 1 : 0;
      if (hidden) continue;
      const slot = used[type]++;
      toWorld(out.x, out.y, 0.8, dummy.position);
      dummy.rotation.set(0, out.heading, 0);
      dummy.scale.setScalar(zoomScale * (v === this.selected ? 1.3 : 1));
      dummy.updateMatrix();
      body.setMatrixAt(slot, dummy.matrix);
      trim.setMatrixAt(slot, dummy.matrix);
      dummy.position.y = 0.75;
      dummy.updateMatrix();
      shadow.setMatrixAt(slot, dummy.matrix);
      if (type !== 'car') {
        // bright while cleaning, paler while only driving, grey once back at the depot
        color.set(VEHICLE_STYLE[type].color);
        if (out.state === 'drive') color.lerp(PALE, 0.35);
        else if (out.state !== 'clean') color.setRGB(0.55, 0.57, 0.6);
        if (v === this.selected) color.set(VEHICLE_STYLE[type].color);  // in full colour
        else if (this.selected >= 0) color.lerp(FADED, 0.85);          // the others turn grey
        body.setColorAt(slot, color);
      }
    }
    for (const [type, parts] of Object.entries(this.parts)) {
      for (const mesh of parts) {
        mesh.count = used[type];
        mesh.instanceMatrix.needsUpdate = true;
      }
      if (parts[0].instanceColor) parts[0].instanceColor.needsUpdate = true;
    }
  }

  // Nearest visible truck to (x, y) within radius metres, or -1.
  pick(x, y, radius) {
    let best = -1, bestDistance = radius;
    for (let v = 0; v < this.types.length; v++) {
      if (!this.visible[v] || this.types[v] === 'car') continue;  // only trucks can be selected
      if (!this.meshes[this.types[v]].visible) continue;
      const d = Math.hypot(this.positions[2 * v] - x, this.positions[2 * v + 1] - y);
      if (d < bestDistance) { best = v; bestDistance = d; }
    }
    return best;
  }

  dispose() {
    for (const parts of Object.values(this.parts)) {
      for (const mesh of parts) {
        mesh.geometry.dispose();
        mesh.material.dispose();
        mesh.dispose();
      }
    }
    this.group.removeFromParent();
  }
}
