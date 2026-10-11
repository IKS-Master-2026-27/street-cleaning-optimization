// The selected truck's route as a ribbon. Every vertex carries the time the
// truck passes it, so the shader splits the route exactly at the truck:
// dark where it has already driven, faint blue where it is still going.

import * as THREE from 'three';
import { REVERSE } from '../loaders/data.js';

const HALF_WIDTH = 2.5; // metres, before the zoom scale

const vertexShader = /* glsl */ `
  attribute vec2 side;
  attribute float stamp;
  uniform float widthScale;
  varying float vStamp;
  void main() {
    vStamp = stamp;
    vec3 p = position + vec3(side.x, 0.0, side.y) * widthScale;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }`;
const fragmentShader = /* glsl */ `
  uniform float time;
  uniform vec3 drivenColor;
  uniform vec3 aheadColor;
  varying float vStamp;
  void main() {
    bool driven = vStamp <= time;
    gl_FragColor = driven ? vec4(drivenColor, 0.6) : vec4(aheadColor, 0.4);
    #include <colorspace_fragment>
  }`;

export class RouteOverlay {
  constructor(city, replay, geometry, v) {
    const { s } = city;
    const t = replay.track;
    const positions = [], sides = [], stamps = [], index = [];
    for (let i = t.offsets[v]; i < t.offsets[v + 1]; i++) {
      const k = t.street[i];
      const reverse = (t.flags[i] & REVERSE) !== 0;
      const enter = t.enter[i];
      const span = replay.exitTime(v, i) - enter;
      const total = geometry.length(k) || 1;
      const first = s.offsets[k], last = s.offsets[k + 1] - 1;
      for (let p = first; p < last; p++) {
        const ax = s.points[2 * p], ay = s.points[2 * p + 1];
        const bx = s.points[2 * p + 2], by = s.points[2 * p + 3];
        const length = Math.hypot(bx - ax, by - ay) || 1;
        const nx = (-(by - ay) / length) * HALF_WIDTH, ny = ((bx - ax) / length) * HALF_WIDTH;
        // time the truck passes each end of this segment, in its driving direction
        const fa = geometry.along[p] / total, fb = geometry.along[p + 1] / total;
        const ta = enter + span * (reverse ? 1 - fa : fa);
        const tb = enter + span * (reverse ? 1 - fb : fb);
        const base = positions.length / 3;
        for (const [x, y, stamp] of [[ax, ay, ta], [bx, by, tb]]) {
          for (const sign of [1, -1]) {
            positions.push(x, 0.9, -y);
            sides.push(sign * nx, -sign * ny);
            stamps.push(stamp);
          }
        }
        index.push(base, base + 1, base + 2, base + 2, base + 1, base + 3);
      }
    }
    const shape = new THREE.BufferGeometry();
    shape.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    shape.setAttribute('side', new THREE.Float32BufferAttribute(sides, 2));
    shape.setAttribute('stamp', new THREE.Float32BufferAttribute(stamps, 1));
    shape.setIndex(index); // three.js picks 16- or 32-bit indices
    this.uniforms = {
      time: { value: 0 },
      widthScale: { value: 1 },
      drivenColor: { value: new THREE.Color(0x1d2633) },
      aheadColor: { value: new THREE.Color(0x3d78c2) },
    };
    this.mesh = new THREE.Mesh(shape, new THREE.ShaderMaterial({
      uniforms: this.uniforms, vertexShader, fragmentShader,
      transparent: true, depthWrite: false, side: THREE.DoubleSide, // hidden behind buildings
    }));
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = 4; // above the streets, below the trucks
  }

  update(time, widthScale) {
    this.uniforms.time.value = time;
    this.uniforms.widthScale.value = widthScale;
  }

  dispose() {
    this.mesh.removeFromParent();
    this.mesh.geometry.dispose();
    this.mesh.material.dispose();
  }
}
