// Renderer, camera, map controls and the city ground. Projected metres (x east,
// y north) map to Three.js as (x, 0, -y).

import * as THREE from 'three';
import { MapControls } from 'three/examples/jsm/controls/MapControls.js';

const COLORS = {
  ground: 0x1a1f27,
  city: 0x222a35,
  boundary: 0x56657a,
  depot: 0xfdd835,
};

export function toWorld(x, y, height = 0, target = new THREE.Vector3()) {
  return target.set(x, height, -y);
}

export class World {
  constructor(canvas) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(COLORS.ground); // same as the ground: no visible horizon
    this.scene.fog = new THREE.Fog(COLORS.ground, 1, 2); // range follows the zoom, see updateFog
    this.camera = new THREE.PerspectiveCamera(45, 1, 1, 2e6);
    this.controls = new MapControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    this.controls.maxPolarAngle = Math.PI * 0.47;
    this.controls.screenSpacePanning = false;
    // lights: see daylight.js
    this.cityGroup = new THREE.Group();
    this.scene.add(this.cityGroup);
    this.resize();
    window.addEventListener('resize', () => this.resize());
  }

  resize() {
    const canvas = this.renderer.domElement;
    const width = canvas.clientWidth, height = canvas.clientHeight;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / Math.max(height, 1);
    this.camera.updateProjectionMatrix();
  }

  // Remove everything of the previous city and free its GPU memory.
  clearCity() {
    this.cityGroup.traverse((o) => {
      o.geometry?.dispose();
      if (o.material) [].concat(o.material).forEach((m) => m.dispose());
    });
    this.scene.remove(this.cityGroup);
    this.cityGroup = new THREE.Group();
    this.scene.add(this.cityGroup);
  }

  buildGround(city) {
    const [x0, y0, x1, y1] = city.bounds;
    const extent = Math.max(x1 - x0, y1 - y0);
    const plane = new THREE.Mesh(
      new THREE.PlaneGeometry(extent * 6, extent * 6).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ color: COLORS.ground, depthWrite: false }),
    );
    plane.renderOrder = -3;
    plane.position.set((x0 + x1) / 2, -0.6, -(y0 + y1) / 2);
    this.cityGroup.add(plane);

    const shapes = [];
    const outline = [];
    for (const polygon of city.boundary) {
      const [outer, ...holes] = polygon;
      const shape = new THREE.Shape(outer.map(([x, y]) => new THREE.Vector2(x, y)));
      holes.forEach((ring) => shape.holes.push(new THREE.Path(ring.map(([x, y]) => new THREE.Vector2(x, y)))));
      shapes.push(shape);
      for (const ring of polygon) {
        for (let i = 0; i < ring.length - 1; i++) {
          outline.push(ring[i][0], 0, -ring[i][1], ring[i + 1][0], 0, -ring[i + 1][1]);
        }
      }
    }
    const area = new THREE.Mesh(
      new THREE.ShapeGeometry(shapes).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ color: COLORS.city, depthWrite: false }),
    );
    area.renderOrder = -2;
    area.position.y = -0.3;
    this.cityGroup.add(area);
    this.groundMaterials = [plane.material, area.material]; // dimmed at night (daylight.js)
    const lines = new THREE.BufferGeometry();
    lines.setAttribute('position', new THREE.Float32BufferAttribute(outline, 3));
    const border = new THREE.LineSegments(lines, new THREE.LineBasicMaterial({ color: COLORS.boundary, depthWrite: false }));
    border.renderOrder = -1;
    this.cityGroup.add(border);
  }

  buildDepot(city) {
    const depot = new THREE.Group();
    const pillar = new THREE.Mesh(
      new THREE.CylinderGeometry(6, 9, 30, 24),
      new THREE.MeshStandardMaterial({ color: COLORS.depot, emissive: COLORS.depot, emissiveIntensity: 0.35 }),
    );
    pillar.position.y = 15;
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(14, 20, 40).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ color: COLORS.depot, transparent: true, opacity: 0.6 }),
    );
    ring.position.y = 1;
    ring.renderOrder = 4;
    pillar.renderOrder = 5;
    depot.add(pillar, ring);
    toWorld(city.depot.x, city.depot.y, 0, depot.position);
    this.depot = depot;
    this.cityGroup.add(depot);
  }

  frameCity(city) {
    const [x0, y0, x1, y1] = city.bounds;
    const extent = Math.max(x1 - x0, y1 - y0, 200);
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    this.controls.target.set(cx, 0, -cy);
    this.camera.position.set(cx, extent * 1.05, -cy + extent * 0.6);
    this.controls.maxDistance = extent * 4;
    this.controls.minDistance = 15;
    this.controls.update();
  }

  // Zoomed out, streets and trucks are drawn wider so they stay a few pixels wide.
  zoomScale(metresPerUnit = 3000) {
    const distance = this.camera.position.distanceTo(this.controls.target);
    return Math.min(Math.max(distance / metresPerUnit, 1), 80);
  }

  // Distant parts of the city fade into the background, wherever the camera is.
  updateFog() {
    const distance = this.camera.position.distanceTo(this.controls.target);
    this.scene.fog.near = distance * 1.6;
    this.scene.fog.far = distance * 5;
  }

  // Vehicles: close to real size up close (next to buildings), and `size` times
  // larger relative to the view as the camera moves away.
  vehicleScale(size) {
    const distance = this.camera.position.distanceTo(this.controls.target);
    return Math.min(Math.max((distance / 700) * size, 1), 320);
  }
}
