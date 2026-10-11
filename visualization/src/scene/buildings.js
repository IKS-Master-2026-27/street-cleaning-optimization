// 3D buildings: each footprint extruded to its height (walls + flat roof),
// all merged into one mesh so thousands of buildings cost one draw call.

import * as THREE from 'three';

const WALL = new THREE.Color(0x56627a);
const ROOF = new THREE.Color(0x8794a8);

export function buildingsMesh(buildings) {
  const { offsets, points, height } = buildings;
  const positions = [], normals = [], colors = [];
  const tint = new THREE.Color();
  const push = (x, y, z, nx, ny, nz, c) => {
    positions.push(x, y, z);
    normals.push(nx, ny, nz);
    colors.push(c.r, c.g, c.b);
  };
  for (let b = 0; b < height.length; b++) {
    const first = offsets[b], count = offsets[b + 1] - first;
    const h = height[b];
    let ring = [];
    for (let i = 0; i < count; i++) {
      ring.push(new THREE.Vector2(points[2 * (first + i)], points[2 * (first + i) + 1]));
    }
    if (THREE.ShapeUtils.isClockWise(ring)) ring = ring.reverse(); // counter-clockwise: walls face out
    // a little variation in shade, stable per building
    const shade = 0.88 + ((Math.sin(b * 12.9898) * 43758.5453) % 1 + 1) % 1 * 0.24;
    const wall = tint.copy(WALL).multiplyScalar(shade).clone();
    for (let i = 0; i < ring.length; i++) {
      const a = ring[i], c = ring[(i + 1) % ring.length];
      const dx = c.x - a.x, dy = c.y - a.y;
      const l = Math.hypot(dx, dy) || 1;
      const nx = dy / l, nz = dx / l; // outward normal in world (x, -y) coordinates
      // two triangles per wall, world = (x, height, -y)
      push(a.x, 0, -a.y, nx, 0, nz, wall); push(c.x, 0, -c.y, nx, 0, nz, wall); push(c.x, h, -c.y, nx, 0, nz, wall);
      push(a.x, 0, -a.y, nx, 0, nz, wall); push(c.x, h, -c.y, nx, 0, nz, wall); push(a.x, h, -a.y, nx, 0, nz, wall);
    }
    const roof = tint.copy(ROOF).multiplyScalar(shade).clone();
    for (const [i, j, k] of THREE.ShapeUtils.triangulateShape(ring, [])) {
      // a triangle counter-clockwise in (x, y) faces up in world (x, h, -y)
      const [p, q, r] = [ring[i], ring[j], ring[k]];
      const ccw = (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x) > 0;
      for (const v of ccw ? [p, q, r] : [p, r, q]) push(v.x, h, -v.y, 0, 1, 0, roof);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  geometry.computeBoundingSphere();
  const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
    vertexColors: true, roughness: 0.9, metalness: 0,
  }));
  mesh.renderOrder = 0; // before the streets, so streets behind buildings are hidden
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}
