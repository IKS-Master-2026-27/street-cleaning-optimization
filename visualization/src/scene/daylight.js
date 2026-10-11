// Time of day: the sun, sky and light follow the shift clock, and buildings and
// trucks cast shadows near the camera. The instances have no wall-clock time, so
// the shift is assumed to start at START_HOUR. Off = the fixed default lighting.

import * as THREE from 'three';

const START_HOUR = 6;

// sky: background and fog; hemi/sun: light intensities; land: ground brightness;
// street: brightness of the street colours (they are not lit by the lights)
const KEYS = [
  [0, { sky: 0x0d1320, sunColor: 0x9fb4ff, hemi: 0.6, sun: 0, land: 0.3, street: 0.55 }],
  [4.5, { sky: 0x121a2a, sunColor: 0x9fb4ff, hemi: 0.7, sun: 0, land: 0.34, street: 0.58 }],
  [5.5, { sky: 0xc2b7bb, sunColor: 0xffc08f, hemi: 1.6, sun: 1.3, land: 0.78, street: 0.85 }],  // summer sunrise
  [7.5, { sky: 0xd6dbe1, sunColor: 0xfff4e0, hemi: 1.8, sun: 2.2, land: 1, street: 1 }],
  [17, { sky: 0xd6dbe1, sunColor: 0xfff4e0, hemi: 1.8, sun: 2.2, land: 1, street: 1 }],
  [19.5, { sky: 0xc9b6ae, sunColor: 0xffa66a, hemi: 1.6, sun: 1.3, land: 0.78, street: 0.85 }],
  [21, { sky: 0x121a2a, sunColor: 0x9fb4ff, hemi: 0.7, sun: 0, land: 0.34, street: 0.58 }],
  [24, { sky: 0x0d1320, sunColor: 0x9fb4ff, hemi: 0.6, sun: 0, land: 0.3, street: 0.55 }],
];
const FIXED = { sky: 0xd6dbe1, sunColor: 0xffffff, hemi: 1.8, sun: 2.0, land: 1, street: 1 };

const ca = new THREE.Color(), cb = new THREE.Color();

function lightAt(hour) {
  let i = 0;
  while (i < KEYS.length - 2 && KEYS[i + 1][0] <= hour) i++;
  const [h0, a] = KEYS[i], [h1, b] = KEYS[i + 1];
  const f = (hour - h0) / (h1 - h0);
  const mix = (x, y) => x + (y - x) * f;
  return {
    sky: ca.set(a.sky).lerp(cb.set(b.sky), f).getHex(),
    sunColor: ca.set(a.sunColor).lerp(cb.set(b.sunColor), f).getHex(),
    hemi: mix(a.hemi, b.hemi), sun: mix(a.sun, b.sun), land: mix(a.land, b.land), street: mix(a.street, b.street),
  };
}

export class Daylight {
  constructor(world) {
    this.world = world;
    const { scene, renderer } = world;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.hemi = new THREE.HemisphereLight(0xeef3ff, 0x9aa3ad, FIXED.hemi);
    this.sun = new THREE.DirectionalLight(0xffffff, FIXED.sun);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    this.sun.shadow.bias = -0.0005;
    this.sun.shadow.normalBias = 0.5;
    scene.add(this.hemi, this.sun, this.sun.target);
    this.south = 1;          // +z is south in world coordinates; -1 for southern-hemisphere cities
    this.shadowPlane = null;
    this.land = [];          // [material, base colour] of the ground meshes
    this.streets = null;
    this.enabled = true;
  }

  // per city: the ground materials to dim, a plane that receives shadows, the streets
  setCity(city, groundMaterials, streets) {
    this.south = city.projection.utm.endsWith('S') ? -1 : 1;
    this.land = groundMaterials.map((m) => [m, m.color.clone()]);
    this.streets = streets;
    const [x0, y0, x1, y1] = city.bounds;
    const plane = new THREE.Mesh(
      new THREE.PlaneGeometry(x1 - x0 + 400, y1 - y0 + 400).rotateX(-Math.PI / 2),
      new THREE.ShadowMaterial({ opacity: 0.22, depthWrite: false }),
    );
    plane.position.set((x0 + x1) / 2, 0.05, -(y0 + y1) / 2);
    plane.receiveShadow = true;
    plane.renderOrder = -1; // over the ground, under the streets
    this.shadowPlane = plane;
    this.world.cityGroup.add(plane);
  }

  // shiftSeconds: the replay clock; returns the assumed local hour, or null when off
  update(shiftSeconds) {
    const hour = this.enabled ? (START_HOUR + shiftSeconds / 3600) % 24 : null;
    const look = hour === null ? FIXED : lightAt(hour);
    const { scene, camera, controls } = this.world;
    scene.background.setHex(look.sky);
    scene.fog.color.setHex(look.sky);
    this.hemi.intensity = look.hemi;
    this.sun.intensity = look.sun;
    this.sun.color.setHex(look.sunColor);
    for (const [material, base] of this.land) material.color.copy(base).multiplyScalar(look.land);
    if (this.land[0]) this.land[0][0].color.setHex(look.sky); // the far ground blends into the sky
    this.streets?.setLight(look.street);

    // sun path: rises in the east, highest towards the equator at noon, sets in the west
    const target = controls.target;
    const distance = camera.position.distanceTo(target);
    let dir;
    if (hour === null) dir = new THREE.Vector3(0.4, 1, 0.3).normalize();
    else {
      const a = Math.PI * ((hour - 6) / 12);
      dir = new THREE.Vector3(Math.cos(a), Math.max(Math.sin(a), 0.05) * 1.2 + 0.1, 0.55 * this.south).normalize();
    }
    // shadows only where they stay sharp: daytime and not zoomed far out
    const shadows = hour !== null && look.sun > 0.3 && distance < 5000;
    this.sun.castShadow = shadows;
    if (this.shadowPlane) this.shadowPlane.visible = shadows;
    const half = THREE.MathUtils.clamp(distance * 0.9, 120, 3000);
    this.sun.position.copy(target).addScaledVector(dir, half * 3);
    this.sun.target.position.copy(target);
    const cam = this.sun.shadow.camera;
    if (cam.right !== half) {
      cam.left = -half; cam.right = half; cam.top = half; cam.bottom = -half;
      cam.near = 1; cam.far = half * 6;
      cam.updateProjectionMatrix();
    }
    return hour;
  }

  dispose() {
    this.shadowPlane?.removeFromParent();
    this.shadowPlane?.geometry.dispose();
    this.shadowPlane?.material.dispose();
    this.shadowPlane = null;
  }
}
