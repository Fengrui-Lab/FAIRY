/** One deterministic display path shared by the HIT 2D and 3D views.
 * Coordinates are relative to the satellite image (top left = 0, 0).
 * Equipment movement, altitude and fixed display homes are illustrations, not
 * flight telemetry. They never update recorded frames, tool state or resources.
 */
import { droneScanRoute } from './scene-layout.js';

const clamp = value => Math.max(0, Math.min(1, Number(value) || 0));
const point = value => Array.isArray(value) && value.length >= 2 && value.slice(0, 2).every(Number.isFinite);
export const HIT_HOMES = { Satellite: [1.15, .12], Drone: [1.13, .85] };
export const HIT_MOTION_NOTE = 'Equipment motion, altitude and fixed home positions are display illustrations. They do not change recorded tool state, world time or resources.';

export function hitBounds(points = []) {
  const rows = points.filter(point);
  return rows.length ? [Math.min(...rows.map(p => p[0])), Math.min(...rows.map(p => p[1])), Math.max(...rows.map(p => p[0])), Math.max(...rows.map(p => p[1]))] : [.08, .12, .92, .88];
}

function fallbackRoute(data, type) {
  const polygon = type === 'Satellite' ? data.farm?.boundary : data.roi?.polygon;
  let [left, top, right, bottom] = hitBounds(polygon);
  if (type === 'Satellite') { left -= .06; top -= .06; right += .06; bottom += .06; }
  const route = [];
  const rows = type === 'Satellite' ? 4 : 5;
  for (let index = 0; index < rows; index++) {
    const y = top + (bottom - top) * (index + .5) / rows;
    route.push([index % 2 ? right : left, y], [index % 2 ? left : right, y]);
  }
  return route;
}

export function hitRoute(data = {}, type = 'Drone') {
  if (type === 'Drone' && data.assets?.orthomosaic && data.roi?.bounds?.length === 4) {
    const [left, top, right, bottom] = data.roi.bounds;
    return droneScanRoute().map(p => [left + p[0] * (right - left), top + p[1] * (bottom - top)]);
  }
  const route = data.routes?.[type === 'Satellite' ? 'satellite' : 'drone'];
  return Array.isArray(route) && route.filter(point).length > 1 ? route.filter(point).map(p => p.slice(0, 2)) : fallbackRoute(data, type);
}

function atPath(path, fraction, ratio) {
  const distances = path.slice(1).map((p, i) => Math.hypot(p[0] - path[i][0], (p[1] - path[i][1]) * ratio));
  const total = distances.reduce((sum, value) => sum + value, 0);
  let remaining = total * fraction;
  const trail = [path[0]];
  for (let index = 0; index < distances.length; index++) {
    const a = path[index], b = path[index + 1], distance = distances[index];
    if (remaining <= distance || index === distances.length - 1) {
      const t = distance ? Math.max(0, Math.min(1, remaining / distance)) : 1;
      const position = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      trail.push(position);
      return { position, trail, heading: Math.atan2((b[1] - a[1]) * ratio, b[0] - a[0]) };
    }
    remaining -= distance; trail.push(b);
  }
  return { position: path[0], trail, heading: 0 };
}

export function getHitMotion(data = {}, step = 0, progress = 1) {
  const ratio = (Number(data.farm?.height_m) || 160) / (Number(data.farm?.width_m) || 280);
  return ['Satellite', 'Drone'].map(id => {
    const missionStep = id === 'Satellite' ? 1 : 5;
    const route = hitRoute(data, id), home = HIT_HOMES[id];
    const active = Number(step) === missionStep;
    const p = active ? clamp(progress) : 1;
    const shown = Number(step) >= missionStep;
    const cruise = id === 'Satellite' ? 55 : 15;
    const phases = [
      { start: 0, end: .16, path: [home, route[0]], name: 'departing' },
      { start: .16, end: .84, path: route, name: 'scanning' },
      { start: .84, end: 1, path: [route.at(-1), home], name: 'returning' },
    ];
    const phaseIndex = p >= 1 ? 2 : phases.findIndex(phase => p < phase.end);
    const phase = phases[phaseIndex];
    const movement = atPath(phase.path, (p - phase.start) / (phase.end - phase.start), ratio);
    movement.trail = [...phases.slice(0, phaseIndex).flatMap(segment => segment.path), ...movement.trail];
    const inMotion = active && p > 0 && p < 1;
    // Satellite stays above the scene; the drone takes off and lands.
    const altitude = id === 'Satellite' ? cruise : inMotion ? cruise * Math.min(1, p / .08, (1 - p) / .08) : 0;
    return {
      id, active: inMotion, missionStep, shown, route,
      position: inMotion ? movement.position : home,
      trail: active && p > 0 ? movement.trail : [],
      heading: active ? movement.heading : 0,
      altitude, progress: p,
      phase: !active || p === 0 || p === 1 ? id === 'Satellite' ? 'standby' : 'docked' : phase.name,
    };
  });
}
