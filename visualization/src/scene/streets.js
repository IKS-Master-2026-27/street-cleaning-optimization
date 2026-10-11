// The instance's streets as flat ribbons along their polylines, merged into one
// mesh per street type (M, O, C) so types can be hidden.
//
// Colours are computed in the shader from two numbers per street: when it is
// first cleaned in the replay, and how many times trucks drive it. So moving
// the clock only changes one uniform, a freshly cleaned street can shine "wet"
// for a while, and the same mesh can switch to a heatmap of repeated driving.

import * as THREE from 'three';

const STREET_COLORS = [
  new THREE.Color(0xe53935), // M mandatory: red
  new THREE.Color(0x1e88e5), // O optional: blue
  new THREE.Color(0x8a8f98), // C connector: grey
];
const CLEANED_COLOR = new THREE.Color(0x43d36b);
const WET_COLOR = new THREE.Color(0xc8f7ff);  // fresh water shine, fades into the cleaned green
const WET_SECONDS = 900;                      // simulated seconds the shine takes to dry
// "Times driven" heatmap: one hue (red), from almost white for streets driven
// once to deep red for streets driven 4 times or more (validated on the city
// ground, dataviz ordinal check). Index 0 = never driven, a dim grey.
export const HEAT_COLORS = ['#3a414c', '#fbecea', '#f5a39b', '#e5594f', '#c42a22'];
export const HEAT_LABELS = ['not driven', '1×', '2×', '3×', '4× or more'];
const HEIGHTS = [0.6, 0.4, 0.2];
const NEVER = 1e30; // cleanedAt of a street no truck cleans

// Half width in metres by OSM highway class.
function halfWidth(highway) {
  if (highway.startsWith('motorway')) return 6;
  if (highway.startsWith('trunk')) return 5.5;
  if (highway.endsWith('_link')) return 3.5;
  if (highway === 'primary') return 5;
  if (highway === 'secondary') return 4.5;
  if (highway === 'tertiary') return 4;
  if (highway === 'service' || highway === 'living_street') return 2.2;
  return 3;
}

const vertexShader = /* glsl */ `
  attribute vec2 side;
  attribute float cleanedAt;
  attribute float heat;
  uniform float widthScale;
  varying float vCleanedAt;
  varying float vHeat;
  void main() {
    vCleanedAt = cleanedAt;
    vHeat = heat;
    vec3 p = position + vec3(side.x, 0.0, side.y) * widthScale;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }`;
const fragmentShader = /* glsl */ `
  uniform float time;
  uniform float light;         // overall brightness (time of day)
  uniform float wetSeconds;
  uniform int mode;            // 0 = street type and cleaning, 1 = times driven
  uniform vec3 baseColor;
  uniform vec3 cleanedColor;
  uniform vec3 wetColor;
  uniform vec3 heatColors[5];
  varying float vCleanedAt;
  varying float vHeat;
  void main() {
    vec3 color;
    if (mode == 1) {
      int level = int(clamp(floor(vHeat + 0.5), 0.0, 4.0));
      color = heatColors[0];
      for (int i = 1; i < 5; i++) if (i == level) color = heatColors[i];
    } else if (time >= vCleanedAt) {
      float wet = exp(-(time - vCleanedAt) / wetSeconds);
      color = mix(cleanedColor, wetColor, wet * 0.75);
    } else {
      color = baseColor;
    }
    gl_FragColor = vec4(color * light, 1.0);
  }`;

export class Streets {
  constructor(city, parent) {
    const { s, count } = city;
    this.city = city;
    this.shared = {  // uniforms shared by the three meshes
      widthScale: { value: 1 },
      time: { value: 0 },
      light: { value: 1 },
      wetSeconds: { value: WET_SECONDS },
      mode: { value: 0 },
      cleanedColor: { value: CLEANED_COLOR },
      wetColor: { value: WET_COLOR },
      heatColors: { value: HEAT_COLORS.map((c) => new THREE.Color(c)) },
    };
    this.group = new THREE.Group();
    parent.add(this.group);
    this.vertexStart = new Uint32Array(count);   // first vertex of street k in its type's mesh
    this.meshes = [];

    const halfWidths = city.highways.map(halfWidth);
    for (let type = 0; type < 3; type++) {
      let vertices = 0, indices = 0;
      for (let k = 0; k < count; k++) {
        if (s.type[k] !== type) continue;
        const n = s.offsets[k + 1] - s.offsets[k];
        vertices += 2 * n;
        indices += 6 * (n - 1);
      }
      const position = new Float32Array(3 * vertices);
      const side = new Float32Array(2 * vertices);
      const index = new Uint32Array(indices);
      let vi = 0, ii = 0;
      for (let k = 0; k < count; k++) {
        if (s.type[k] !== type) continue;
        this.vertexStart[k] = vi;
        const first = s.offsets[k], last = s.offsets[k + 1] - 1;
        const w = halfWidths[s.highway[k]];
        for (let p = first; p <= last; p++) {
          const x = s.points[2 * p], y = s.points[2 * p + 1];
          // miter normal: average of the normals of the segments meeting here
          let nx = 0, ny = 0;
          if (p > first) {
            const dx = x - s.points[2 * p - 2], dy = y - s.points[2 * p - 1];
            const l = Math.hypot(dx, dy) || 1;
            nx += -dy / l; ny += dx / l;
          }
          if (p < last) {
            const dx = s.points[2 * p + 2] - x, dy = s.points[2 * p + 3] - y;
            const l = Math.hypot(dx, dy) || 1;
            nx += -dy / l; ny += dx / l;
          }
          const nl = Math.hypot(nx, ny) || 1;
          const inner = p > first && p < last ? nl / 2 : 1; // cos of half the turn angle
          const scale = w / Math.max(inner, 0.4) / nl;
          for (const sign of [1, -1]) {
            position.set([x, HEIGHTS[type], -y], 3 * vi);
            side.set([sign * nx * scale, -sign * ny * scale], 2 * vi);
            vi++;
          }
          if (p < last) {
            const v = vi - 2;
            index.set([v, v + 1, v + 2, v + 2, v + 1, v + 3], ii);
            ii += 6;
          }
        }
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.BufferAttribute(position, 3));
      geometry.setAttribute('side', new THREE.BufferAttribute(side, 2));
      geometry.setAttribute('cleanedAt', new THREE.BufferAttribute(new Float32Array(vertices).fill(NEVER), 1));
      geometry.setAttribute('heat', new THREE.BufferAttribute(new Float32Array(vertices), 1));
      geometry.setIndex(new THREE.BufferAttribute(index, 1));
      geometry.computeBoundingSphere();
      const material = new THREE.ShaderMaterial({
        uniforms: { ...this.shared, baseColor: { value: STREET_COLORS[type] } },
        vertexShader, fragmentShader, side: THREE.DoubleSide,
        depthWrite: false, // layers are ordered by renderOrder, so they never z-fight
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.frustumCulled = false; // vertices move with widthScale
      mesh.renderOrder = type === 0 ? 3 : type === 1 ? 2 : 1;
      this.meshes.push(mesh);
      this.group.add(mesh);
    }
  }

  setWidthScale(scale) {
    this.shared.widthScale.value = scale;
  }

  setTime(time) {
    this.shared.time.value = time;
  }

  setLight(brightness) {
    this.shared.light.value = brightness;
  }

  // 'type' (red/blue/grey, green once cleaned) or 'heat' (times driven)
  setColorMode(mode) {
    this.shared.mode.value = mode === 'heat' ? 1 : 0;
  }

  setTypeVisible(type, visible) {
    this.meshes[type].visible = visible;
  }

  // Load when each street is cleaned and how often it is driven, for a replay.
  setReplay(replay) {
    const { s, count } = this.city;
    const timesDriven = replay.timesDriven;
    for (const mesh of this.meshes) {
      mesh.geometry.attributes.cleanedAt.array.fill(NEVER);
      mesh.geometry.attributes.heat.array.fill(0);
    }
    for (let k = 0; k < count; k++) {
      const { cleanedAt, heat } = this.meshes[s.type[k]].geometry.attributes;
      const start = this.vertexStart[k];
      const end = start + 2 * (s.offsets[k + 1] - s.offsets[k]);
      if (replay.firstCleaner[k] >= 0) cleanedAt.array.fill(replay.firstClean[k], start, end);
      heat.array.fill(Math.min(timesDriven[k], 4), start, end);
    }
    for (const mesh of this.meshes) {
      mesh.geometry.attributes.cleanedAt.needsUpdate = true;
      mesh.geometry.attributes.heat.needsUpdate = true;
    }
  }
}

// A thin line along a set of streets, used to outline a selected street.
export function polylineOverlay(city, streets, color, height) {
  const { s } = city;
  const positions = [];
  for (const k of streets) {
    for (let p = s.offsets[k]; p < s.offsets[k + 1] - 1; p++) {
      positions.push(s.points[2 * p], height, -s.points[2 * p + 1],
        s.points[2 * p + 2], height, -s.points[2 * p + 3]);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  const line = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({
    color, transparent: true, opacity: 0.9, depthTest: false,
  }));
  line.renderOrder = 10;
  return line;
}
