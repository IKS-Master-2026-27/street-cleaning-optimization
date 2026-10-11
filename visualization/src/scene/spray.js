// Water spray from trucks while they clean: a fixed pool of particles shot
// sideways from the front corners of each cleaning truck, falling under gravity
// and fading out. Animated in real time, so it looks alive at any playback speed.

import * as THREE from 'three';
import { VEHICLE_STYLE } from './vehicles.js';

const vertexShader = /* glsl */ `
  attribute float alpha;
  attribute float size;
  uniform float pixels;   // viewport height / (2 tan(fov / 2))
  varying float vAlpha;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    // drops right in front of the camera would tint the whole view: fade them out
    vAlpha = alpha * smoothstep(4.0, 25.0, -mv.z);
    gl_PointSize = clamp(size * pixels / -mv.z, 1.5, 48.0);
    gl_Position = projectionMatrix * mv;
  }`;
const fragmentShader = /* glsl */ `
  uniform vec3 color;
  varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    gl_FragColor = vec4(color, vAlpha * (1.0 - d * 2.0));
    #include <colorspace_fragment>
  }`;

export class Spray {
  constructor(parent, capacity = 5000) {
    this.capacity = capacity;
    this.position = new Float32Array(3 * capacity);
    this.velocity = new Float32Array(3 * capacity);
    this.life = new Float32Array(capacity);     // seconds left
    this.span = new Float32Array(capacity).fill(1);
    this.alpha = new Float32Array(capacity);
    this.size = new Float32Array(capacity);
    this.next = 0;          // next pool slot to reuse
    this.debt = new Map();  // fractional particles owed per truck
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(this.position, 3).setUsage(THREE.DynamicDrawUsage));
    geometry.setAttribute('alpha', new THREE.BufferAttribute(this.alpha, 1).setUsage(THREE.DynamicDrawUsage));
    geometry.setAttribute('size', new THREE.BufferAttribute(this.size, 1).setUsage(THREE.DynamicDrawUsage));
    this.uniforms = { pixels: { value: 500 }, color: { value: new THREE.Color(0x4fb6f0) } };
    this.points = new THREE.Points(geometry, new THREE.ShaderMaterial({
      uniforms: this.uniforms, vertexShader, fragmentShader,
      transparent: true, depthWrite: false, // normal blending: additive white vanishes on the light ground
    }));
    this.points.frustumCulled = false;
    this.points.renderOrder = 6;
    parent.add(this.points);
    this.enabled = true;
    this.flip = false;
  }

  emit(x, y, z, vx, vy, vz, life, size) {
    const i = this.next;
    this.next = (this.next + 1) % this.capacity;
    this.position.set([x, y, z], 3 * i);
    this.velocity.set([vx, vy, vz], 3 * i);
    this.life[i] = life;
    this.span[i] = life;
    this.size[i] = size;
  }

  // dt: real seconds since the last frame; scale: the vehicles' drawing scale
  update(dt, vehicles, scale, camera, viewportHeight) {
    this.uniforms.pixels.value = viewportHeight / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2));
    const cleaning = [];
    if (this.enabled) {
      for (let v = 0; v < vehicles.types.length; v++) {
        const type = vehicles.types[v];
        if (vehicles.states[v] === 2 && type !== 'car' && vehicles.meshes[type].visible) cleaning.push(v);
      }
    }
    // share the pool between the cleaning trucks (about 0.9 s of life each)
    const rate = cleaning.length ? Math.min(160, this.capacity / (1.1 * cleaning.length)) : 0;
    for (const v of cleaning) {
      const [length, , width] = VEHICLE_STYLE[vehicles.types[v]].size;
      const owed = (this.debt.get(v) ?? 0) + rate * dt;
      const count = Math.floor(owed);
      this.debt.set(v, owed - count);
      const heading = vehicles.headings[v];
      const dx = Math.cos(heading), dy = Math.sin(heading);   // forward, map coordinates
      const sx = -dy, sy = dx;                                 // left
      const px = vehicles.positions[2 * v], py = vehicles.positions[2 * v + 1];
      for (let n = 0; n < count; n++) {
        this.flip = !this.flip;            // alternate left and right nozzles
        const side = this.flip ? 1 : -1;
        const fx = px + dx * length * 0.42 * scale + sx * side * width * 0.5 * scale;
        const fy = py + dy * length * 0.42 * scale + sy * side * width * 0.5 * scale;
        const out = (4 + Math.random() * 4) * scale;
        const back = (Math.random() - 0.6) * 1.5 * scale;
        // world = (x, height, -y)
        this.emit(
          fx, 0.6 * scale, -fy,
          sx * side * out + dx * back, (1.5 + Math.random() * 2) * scale, -(sy * side * out + dy * back),
          0.7 + Math.random() * 0.6, (0.9 + Math.random() * 0.9) * scale,
        );
      }
    }
    for (const v of this.debt.keys()) if (!cleaning.includes(v)) this.debt.delete(v);
    const gravity = 9.8 * scale;
    for (let i = 0; i < this.capacity; i++) {
      if (this.life[i] <= 0) { this.alpha[i] = 0; continue; }
      this.life[i] -= dt;
      this.velocity[3 * i + 1] -= gravity * dt;
      for (let a = 0; a < 3; a++) this.position[3 * i + a] += this.velocity[3 * i + a] * dt;
      if (this.position[3 * i + 1] < 0.3) { this.position[3 * i + 1] = 0.3; this.velocity[3 * i + 1] = 0; }
      this.alpha[i] = Math.max(this.life[i] / this.span[i], 0) * 0.55;
    }
    const attributes = this.points.geometry.attributes;
    attributes.position.needsUpdate = true;
    attributes.alpha.needsUpdate = true;
    attributes.size.needsUpdate = true;
  }

  clear() {
    this.life.fill(0);
    this.alpha.fill(0);
    this.debt.clear();
  }

  dispose() {
    this.points.removeFromParent();
    this.points.geometry.dispose();
    this.points.material.dispose();
  }
}
