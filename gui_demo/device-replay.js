/**
 * Deterministic display projection of executed tool events, not GPS telemetry.
 * Moving poses use field-relative x/z, including out-of-bounds base transit.
 * Docked poses have farmId=null and x=z=.5 within their fixed hub slot.
 * siteX/siteY always identify the same point in the overview's schematic map.
 * heading is radians from +x toward +z; altitude is schematic metres. Departure
 * and return are display phases, not extra simulation actions, time or fuel.
 */
const DEVICE_IDS = ['Tractor', 'Mavic3M', 'Matrice4T', 'Robot0'];

export function homePoint(id) {
  const index = DEVICE_IDS.indexOf(id);
  if (index < 0) throw new RangeError(`Unknown shared device: ${id}`);
  return { siteX: 970 + index * 90, siteY: 275 };
}

export function createDeviceReplay(events = [], farms = []) {
  const ids = DEVICE_IDS;
  const farmMap = new Map(farms.map(farm => [farm.id || farm.farm_id, farm]));
  const hubMethods = new Set(['charge', 'refuel', 'load_seeds', 'load_fertilizer', 'load_pesticide', 'load_fungicide', 'load_herbicide', 'return_supplies', 'unload_grain', 'attach_implement', 'detach_implement']);
  const tractorMethods = new Set(['level', 'base_fertilize', 'form_ridges', 'till', 'plant_seeds', 'apply_fertilizer', 'apply_fungicide', 'spray_pesticide', 'apply_herbicide', 'mechanical_weeding', 'mechanical_weed_control', 'incorporate_residue', 'harvest']);
  const wholeFieldMethods = new Set(['level', 'base_fertilize', 'form_ridges', 'till']);
  const initial = ids.map(id => ({ id, farmId: null, missionFarmId: null, active: false, mode: 'docked', phase: 'docked', x: .5, z: .5, ...homePoint(id), altitude: 0, heading: 0, trail: [], eventSequence: null, toolName: null, range: null, lastSurveySequence: null, positionSource: 'event_schematic' }));
  const records = [];
  let latest = initial;
  const numeric = value => typeof value === 'number' && Number.isFinite(value);
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const clone = pose => ({ ...pose, range: pose.range ? [...pose.range] : null, trail: pose.trail.map(point => ({ ...point })) });

  function executedRidges(event, farm, method) {
    const args = event.arguments || event.tool_args || {}, result = event.result || {};
    const n = Math.max(1, Number(farm.num_ridges) || 64);
    // Partial missions use actual coverage, never the unvisited requested tail.
    const coverage = ['covered_ridges', 'surveyed_ridges', 'planted_ridges', 'harvested_ridges', 'sprayed_ridges', 'fertilized_ridges', 'treated_ridges', 'weeded_ridges', 'incorporated_ridges', 'ridge_ids'].find(key => Array.isArray(result[key]));
    let rows;
    if (coverage) rows = result[coverage];
    else if (result.status === 'partial' || event.status === 'partial') return [];
    else if (Array.isArray(args.ridge_ids)) rows = args.ridge_ids;
    else if (Number.isInteger(args.ridge_id)) rows = [args.ridge_id];
    else {
      const start = args.start_ridge ?? args.start, end = args.end_ridge ?? args.end;
      if (Number.isInteger(start) && Number.isInteger(end) && end >= start) {
        rows = Array.from({ length: Math.min(n, end - start + 1) }, (_, index) => start + index);
      } else rows = wholeFieldMethods.has(method) ? Array.from({ length: n }, (_, index) => index) : [];
    }
    return [...new Set(rows.map(Number).filter(ridge => Number.isInteger(ridge) && ridge >= 0 && ridge < n))].sort((a, b) => a - b);
  }

  function projection(farm) {
    const id = farm.id || farm.farm_id;
    const length = Number(farm.field_length_m) || 268;
    const width = (Number(farm.num_ridges) || 64) * (Number(farm.ridge_width_m) || 1);
    // These are the existing overview layout anchors, never geographic data.
    const origin = id === 'soybean_field' ? [155, 123] : [655, 408];
    return { origin, length, width, pixelLength: 560, pixelWidth: width / length * 560 };
  }

  function fieldPoint(x, z, altitude, farm) {
    const map = projection(farm);
    return { x, z, altitude, siteX: map.origin[0] + x * map.pixelLength, siteY: map.origin[1] + z * map.pixelWidth };
  }

  function basePoint(id, farm, altitude = 0) {
    const base = homePoint(id), map = projection(farm);
    return { ...base, x: (base.siteX - map.origin[0]) / map.pixelLength, z: (base.siteY - map.origin[1]) / map.pixelWidth, altitude };
  }

  function missionPath(id, rows, farm, altitude) {
    const count = Math.max(1, Number(farm.num_ridges) || 64);
    const path = [];
    rows.forEach((rid, index) => {
      const z = (rid + .5) / count;
      const from = index % 2 ? .96 : .04, to = index % 2 ? .04 : .96;
      path.push(fieldPoint(from, z, altitude, farm), fieldPoint(to, z, altitude, farm));
      // Walking inspections traverse the ridge out and back before moving on.
      if (id === 'Robot0') path.push(fieldPoint(from, z, altitude, farm));
    });
    return path.filter((point, i) => !i || point.x !== path[i - 1].x || point.z !== path[i - 1].z);
  }

  function positionOnPath(path, fraction, farm) {
    if (!path.length) return { ...fieldPoint(.5, .5, 0, farm), heading: 0, trail: [] };
    const length = Number(farm.field_length_m) || 268;
    const width = (Number(farm.num_ridges) || 64) * (Number(farm.ridge_width_m) || 1);
    const distances = path.slice(1).map((point, i) => Math.hypot((point.x - path[i].x) * length, (point.z - path[i].z) * width, point.altitude - path[i].altitude));
    const total = distances.reduce((sum, value) => sum + value, 0);
    let remaining = total * fraction;
    const trail = [{ ...path[0] }];
    let current = path[0], heading = 0;
    for (let index = 0; index < distances.length; index++) {
      const start = path[index], end = path[index + 1], distance = distances[index];
      heading = Math.atan2((end.z - start.z) * width, (end.x - start.x) * length);
      if (remaining < distance || index === distances.length - 1) {
        const t = distance ? clamp(remaining / distance, 0, 1) : 1;
        current = fieldPoint(start.x + (end.x - start.x) * t, start.z + (end.z - start.z) * t, start.altitude + (end.altitude - start.altitude) * t, farm);
        trail.push(current); break;
      }
      remaining -= distance; current = end; trail.push({ ...end });
    }
    return { ...current, heading, trail };
  }

  function phasesFor(id, farm, rows, flying) {
    const altitude = flying ? (id === 'Matrice4T' ? 14 : 11) : 0;
    const base = basePoint(id, farm), elevated = basePoint(id, farm, altitude);
    const work = missionPath(id, rows, farm, altitude);
    if (flying) return [
      { start: 0, end: .08, name: 'takeoff', path: [base, elevated] },
      { start: .08, end: .22, name: 'departing', path: [elevated, work[0]] },
      { start: .22, end: .78, name: 'survey', path: work },
      { start: .78, end: .93, name: 'returning', path: [work.at(-1), elevated] },
      { start: .93, end: 1, name: 'landing', path: [elevated, base] },
    ];
    return [
      { start: 0, end: .18, name: 'departing', path: [base, work[0]] },
      { start: .18, end: .82, name: 'working', path: work },
      { start: .82, end: 1, name: 'returning', path: [work.at(-1), base] },
    ];
  }

  function missionPosition(transition, fraction) {
    const { phases, farm } = transition;
    const currentIndex = Math.max(0, phases.findIndex(phase => fraction < phase.end));
    const index = fraction >= 1 ? phases.length - 1 : currentIndex;
    const phase = phases[index];
    const current = positionOnPath(phase.path, clamp((fraction - phase.start) / (phase.end - phase.start), 0, 1), farm);
    const visited = [...phases.slice(0, index).flatMap(segment => segment.path), ...current.trail];
    const unique = visited.filter((point, i) => !i || point.x !== visited[i - 1].x || point.z !== visited[i - 1].z || point.altitude !== visited[i - 1].altitude);
    const trail = unique.length > 512 ? unique.filter((_, i) => i % Math.ceil(unique.length / 511) === 0 || i === unique.length - 1) : unique;
    return { ...current, phase: phase.name, mode: phase.name, trail };
  }

  const ordered = events.map((event, index) => ({ event, sequence: Number(event.sequence) || index + 1 })).sort((a, b) => a.sequence - b.sequence);
  for (const { event, sequence } of ordered) {
    const toolName = String(event.tool_name || event.toolName || '');
    const actor = String(event.scope?.actor_app || toolName.split('__')[0]);
    const method = toolName.split('__').slice(1).join('__');
    const index = ids.indexOf(actor), result = event.result || {}, args = event.arguments || event.tool_args || {};
    let transition = null;
    let after = latest;
    const failed = !!event.error || !!result.error || ['error', 'failed'].includes(String(event.status)) || ['error', 'failed'].includes(String(result.status));
    if (index >= 0 && !failed) {
      const previous = latest[index];
      if (hubMethods.has(method)) {
        const pose = { ...previous, farmId: null, ...homePoint(actor), x: .5, z: .5, altitude: 0, heading: 0, active: false, trail: [], phase: 'docked', mode: 'docked', eventSequence: sequence, toolName };
        after = latest.map((value, i) => i === index ? pose : value);
        transition = { index, type: 'hub' };
      } else {
        const farmId = args.farm_id || result.farm_id || (event.scope?.farm_ids?.length === 1 ? event.scope.farm_ids[0] : null);
        const farm = farmMap.get(farmId);
        const isSurvey = ['Mavic3M', 'Matrice4T'].includes(actor) && method === 'fly_survey';
        const isInspection = actor === 'Robot0' && /^inspect_/.test(method);
        const isFieldWork = actor === 'Tractor' && tractorMethods.has(method);
        if (farm && (isSurvey || isInspection || isFieldWork)) {
          const rows = executedRidges(event, farm, method);
          if (rows.length) {
            transition = { index, type: 'mission', phases: phasesFor(actor, farm, rows, isSurvey), farm, previousSurvey: previous.lastSurveySequence, isSurvey };
            const completed = missionPosition(transition, 1);
            const pose = { ...previous, farmId: null, missionFarmId: farmId, ...homePoint(actor), x: .5, z: .5, altitude: 0, heading: 0, active: false,
              mode: 'docked', phase: 'docked', trail: completed.trail, range: [rows[0], rows.at(-1)],
              eventSequence: sequence, toolName, lastSurveySequence: isSurvey ? sequence : previous.lastSurveySequence };
            after = latest.map((value, i) => i === index ? pose : value);
          }
        }
      }
    }
    records.push({ sequence, after, transition }); latest = after;
  }

  return {
    at(step, progress = 1) {
      const target = Math.max(0, Number.isFinite(Number(step)) ? Math.floor(Number(step)) : 0);
      const fraction = clamp(numeric(progress) ? progress : 1, 0, 1);
      let lo = 0, hi = records.length - 1, found = -1;
      while (lo <= hi) { const mid = (lo + hi) >> 1; if (records[mid].sequence <= target) { found = mid; lo = mid + 1; } else hi = mid - 1; }
      if (found < 0) return initial.map(clone);
      const record = records[found], poses = record.after.map(clone);
      if (record.sequence === target && record.transition) {
        const transition = record.transition, pose = poses[transition.index];
        if (transition.type === 'mission' && fraction < 1) {
          pose.lastSurveySequence = transition.previousSurvey;
          if (fraction === 0) pose.trail = [];
          else {
            Object.assign(pose, missionPosition(transition, fraction));
            pose.farmId = pose.missionFarmId;
            pose.active = true;
          }
        }
      }
      return poses;
    },
  };
}
