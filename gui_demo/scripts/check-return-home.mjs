#!/usr/bin/env node
/** Return-to-base regression checks using recorded events, without a DOM or writes. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(process.argv[2] || resolve(dirname(fileURLToPath(import.meta.url)), '..'));
const readJSON = async name => JSON.parse(await readFile(resolve(root, 'data', name), 'utf8'));
const [manifest, events, frames, catalog] = await Promise.all([
  readJSON('manifest.json'), readJSON('events.json'), readJSON('frames.json'), readJSON('tool-catalog.json'),
]);
const [{ createDeviceReplay }, { createDataModel }] = await Promise.all([
  import(pathToFileURL(resolve(root, 'device-replay.js')).href),
  import(pathToFileURL(resolve(root, 'data-model.js')).href),
]);
const deviceIds = ['Tractor', 'Robot0', 'Mavic3M', 'Matrice4T'];
const droneIds = new Set(['Mavic3M', 'Matrice4T']);
const farmById = Object.fromEntries(manifest.farms.map(farm => [farm.id, farm]));
const originalInputs = JSON.stringify([events, manifest]);
const deepFreeze = object => {
  if (object && typeof object === 'object' && !Object.isFrozen(object)) {
    Object.freeze(object);
    for (const value of Object.values(object)) deepFreeze(value);
  }
  return object;
};
deepFreeze(events);
deepFreeze(manifest);
const replay = createDeviceReplay(events, manifest.farms);
const model = createDataModel(manifest, events, frames, catalog);
const poseOf = (poses, id) => poses.find(pose => pose.id === id);
const initial = replay.at(0);
const baseOf = id => poseOf(initial, id);
const sitePosition = pose => [pose.siteX, pose.siteY, pose.altitude];
const activePhases = new Set(['takeoff', 'departing', 'working', 'survey', 'returning', 'landing']);
let sampledPoses = 0, boundaryChecks = 0;

function assertDocked(pose, message) {
  assert.equal(pose.phase, 'docked', message);
  assert.equal(pose.active, false, message);
  assert.equal(pose.farmId, null, message);
  assert.equal(pose.altitude, 0, 'Completed devices must not hover');
  assert.deepEqual(sitePosition(pose), sitePosition(baseOf(pose.id)), 'The home slot is independent of the target farm');
  assert.deepEqual([pose.x, pose.z], [baseOf(pose.id).x, baseOf(pose.id).z]);
}

function assertFinitePose(pose, step) {
  sampledPoses++;
  assert.ok([pose.x, pose.z, pose.siteX, pose.siteY, pose.altitude, pose.heading].every(Number.isFinite),
    `Finite coordinates at event ${step}`);
  assert.ok(pose.altitude >= 0);
  assert.ok(pose.farmId === null || farmById[pose.farmId]);
  assert.ok(pose.missionFarmId === null || farmById[pose.missionFarmId]);
  assert.ok(pose.eventSequence === null || pose.eventSequence <= step);
  assert.ok(pose.lastSurveySequence === null || pose.lastSurveySequence <= step);
  assert.equal(pose.positionSource, 'event_schematic');
  for (const point of pose.trail) {
    assert.ok([point.x, point.z, point.siteX, point.siteY, point.altitude].every(Number.isFinite));
    assert.ok(point.altitude >= 0);
  }
  if (pose.range) {
    const farm = farmById[pose.missionFarmId];
    assert.ok(farm, 'Coverage retains its target even after the device returns');
    assert.ok(pose.range.every(Number.isInteger));
    assert.ok(pose.range[0] >= 0 && pose.range[0] <= pose.range[1] && pose.range[1] < farm.num_ridges);
  }
}

assert.deepEqual(initial.map(pose => pose.id).sort(), [...deviceIds].sort());
assert.equal(new Set(initial.map(pose => `${pose.siteX},${pose.siteY}`)).size, 4,
  'Shared devices have four distinct base slots');
for (const pose of initial) {
  assertDocked(pose, 'Initial devices are docked');
  assert.equal(pose.missionFarmId, null);
  assert.equal(pose.lastSurveySequence, null);
  assert.equal(pose.eventSequence, null);
}

// These are actual field operations in this fixture, selected independently of motion output.
const missions = events.filter(event => deviceIds.includes(event.scope.actor_app)
  && event.arguments.farm_id && event.status === 'ok');
const missionCounts = Object.fromEntries(deviceIds.map(id => [id,
  missions.filter(event => event.scope.actor_app === id).length]));
assert.deepEqual(missionCounts, { Tractor: 86, Robot0: 9, Mavic3M: 3, Matrice4T: 2 });
const completed = [];
for (let step = 0; step <= events.length; step++) {
  const poses = replay.at(step);
  assert.equal(new Set(poses.map(pose => pose.id)).size, 4);
  for (const pose of poses) {
    assertFinitePose(pose, step);
    assertDocked(pose, `No device remains in a field after event ${step}`);
    if (droneIds.has(pose.id)) {
      const latestSurvey = events.slice(0, step).findLast(event => event.scope.actor_app === pose.id
        && event.tool_name.endsWith('__fly_survey') && event.status === 'ok');
      assert.equal(pose.lastSurveySequence, latestSurvey?.sequence ?? null,
        'Returning and later service events retain the latest acquired survey');
    }
  }
  completed.push(poses);
}

function actualRange(event) {
  const arrays = ['covered_ridges', 'surveyed_ridges', 'planted_ridges', 'harvested_ridges',
    'fertilized_ridges', 'sprayed_ridges'].map(key => event.result[key]).filter(Array.isArray);
  if (arrays.length) return [Math.min(...arrays[0]), Math.max(...arrays[0])];
  if (Number.isInteger(event.arguments.start_ridge)) return [event.arguments.start_ridge, event.arguments.end_ridge];
  return [0, farmById[event.arguments.farm_id].num_ridges - 1];
}

for (const event of missions) {
  const step = event.sequence, actor = event.scope.actor_app, farmId = event.arguments.farm_id;
  const n = farmById[farmId].num_ridges, range = actualRange(event);
  const before = poseOf(replay.at(step, 0), actor), after = poseOf(replay.at(step, 1), actor);
  assertDocked(before, 'Every field mission starts from base');
  assertDocked(after, 'Every field mission ends at base');
  assert.equal(before.trail.length, 0, 'Starting a mission cannot expose its future path');
  assert.equal(after.missionFarmId, farmId);
  assert.deepEqual(after.range, range);
  assert.equal(after.eventSequence, step);
  assert.equal(after.toolName, event.tool_name);
  const phases = new Set(), samples = [];
  const previousSurvey = poseOf(replay.at(step - 1), actor).lastSurveySequence;
  for (let i = 0; i <= 100; i++) {
    const progress = i / 100, poses = replay.at(step, progress), pose = poseOf(poses, actor);
    assertFinitePose(pose, step);
    samples.push({ progress, pose }); phases.add(pose.phase);
    assert.deepEqual(pose.range, range, 'Return animation does not erase mission coverage');
    assert.equal(pose.missionFarmId, farmId);
    for (const other of poses.filter(item => item.id !== actor)) assertDocked(other, 'Other devices stay at base');
    if (progress > 0 && progress < 1) {
      assert.ok(activePhases.has(pose.phase));
      assert.equal(pose.active, true);
      assert.equal(pose.farmId, farmId);
    }
    if (['working', 'survey'].includes(pose.phase)) {
      assert.ok(pose.x >= 0 && pose.x <= 1);
      assert.ok(pose.z >= range[0] / n && pose.z <= (range[1] + 1) / n,
        `Working position stays in executed coverage at event ${step}`);
    }
    if (!droneIds.has(actor)) assert.equal(pose.altitude, 0, 'Ground machinery never flies');
    if (droneIds.has(actor)) assert.equal(pose.lastSurveySequence, progress < 1 ? previousSurvey : step,
      'Survey results become available on completion and survive docking');
  }
  for (const phase of ['docked', 'departing', droneIds.has(actor) ? 'survey' : 'working', 'returning']) {
    assert.ok(phases.has(phase), `Mission ${step} must include ${phase}`);
  }
  if (droneIds.has(actor)) for (const phase of ['takeoff', 'landing']) assert.ok(phases.has(phase));

  // Discover phase boundaries from observable output; test continuity in site coordinates,
  // since local field coordinates intentionally switch reference frames at departure/docking.
  for (let i = 1; i < samples.length; i++) {
    if (samples[i - 1].pose.phase === samples[i].pose.phase) continue;
    let lo = samples[i - 1].progress, hi = samples[i].progress;
    const phase = samples[i - 1].pose.phase;
    for (let j = 0; j < 30; j++) {
      const mid = (lo + hi) / 2;
      if (poseOf(replay.at(step, mid), actor).phase === phase) lo = mid; else hi = mid;
    }
    const left = poseOf(replay.at(step, Math.max(0, lo - 1e-8)), actor);
    const right = poseOf(replay.at(step, Math.min(1, hi + 1e-8)), actor);
    const delta = Math.hypot(...sitePosition(left).map((value, axis) => value - sitePosition(right)[axis]));
    assert.ok(delta < .05, `No positional jump at ${phase} → ${right.phase} in event ${step}: ${delta}`);
    boundaryChecks++;
  }

  if (droneIds.has(actor)) {
    const row = event.result.observations[0];
    const observed = model.observations(step)[farmId][row.ridge_id].ndvi;
    assert.equal(observed.value, row.ndvi);
    assert.equal(observed.sequence, step, 'Docking does not clear acquired survey evidence');
    if (step < events.length && !events[step].result?.observations) {
      assert.deepEqual(model.observations(step + 1)[farmId][row.ridge_id].ndvi, observed);
    }
  }
}

// Cross-farm missions, partial completion, and failures use the same home for every device.
let syntheticCases = 0;
for (const actor of deviceIds) {
  const tool = droneIds.has(actor) ? 'fly_survey' : actor === 'Robot0' ? 'inspect_crop_health' : 'apply_fertilizer';
  const key = droneIds.has(actor) ? 'surveyed_ridges' : actor === 'Robot0' ? 'covered_ridges' : 'fertilized_ridges';
  const mission = (sequence, farmId, status, coverage) => ({ sequence, tool_name: `${actor}__${tool}`,
    scope: { actor_app: actor, farm_ids: [farmId] }, status: 'ok',
    arguments: { farm_id: farmId, start_ridge: 20, end_ridge: 39 },
    result: { farm_id: farmId, status, ...(coverage ? { [key]: coverage } : {}) } });
  const source = [mission(1, manifest.farms[0].id, 'partial', [20, 21]),
    mission(2, manifest.farms[1].id, 'ok', [20, 21, 22]),
    { ...mission(3, manifest.farms[0].id, 'ok', [20, 21]), status: 'failed' },
    mission(4, manifest.farms[0].id, 'partial', null)];
  const unchanged = JSON.stringify(source), synthetic = createDeviceReplay(source, manifest.farms);
  for (const step of [1, 2]) {
    assertDocked(poseOf(synthetic.at(step), actor), 'Both farm targets return to the identical home');
    const expectedRange = step === 1 ? [20, 21] : [20, 22];
    assert.deepEqual(poseOf(synthetic.at(step), actor).range, expectedRange);
    for (const progress of [.3, .5, .7]) {
      const pose = poseOf(synthetic.at(step, progress), actor);
      assert.ok(pose.z >= 20 / 64 && pose.z <= (expectedRange[1] + 1) / 64,
        'Partial work never reaches the unvisited requested tail');
    }
  }
  for (const step of [3, 4]) for (const progress of [0, .1, .5, .9, 1]) {
    assert.deepEqual(synthetic.at(step, progress), synthetic.at(2),
      'Failed or unlocated partial actions cannot invent movement or new results');
  }
  assert.equal(JSON.stringify(source), unchanged);
  syntheticCases += 4;
}

// Seeking and caller mutation must not change later playback or original recorded data.
for (let i = 0; i < 500; i++) {
  const step = (i * 83 + 31) % completed.length;
  replay.at((step + 77) % completed.length, .875);
  assert.deepEqual(replay.at(step), completed[step]);
}
const modified = replay.at(missions[0].sequence, .5), altered = poseOf(modified, 'Tractor');
altered.siteX = -999;
altered.range[0] = -999;
if (altered.trail.length) altered.trail[0].siteX = -999;
assert.notEqual(poseOf(replay.at(missions[0].sequence, .5), 'Tractor').siteX, -999);
assert.deepEqual(replay.at(events.length), completed.at(-1));
assert.equal(JSON.stringify([events, manifest]), originalInputs, 'Original event data and farm metadata remain unchanged');

console.log(JSON.stringify({ status: 'passed', events: events.length, field_missions: missions.length,
  mission_counts: missionCounts, sampled_poses: sampledPoses, continuous_phase_boundaries: boundaryChecks,
  synthetic_cases: syntheticCases, random_access_queries: 500,
  no_browser: true, no_file_writes: true }, null, 2));
