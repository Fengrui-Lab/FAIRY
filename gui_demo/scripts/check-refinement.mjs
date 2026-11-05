#!/usr/bin/env node
/** Behavioral checks for replay motion and evidence presentation; no DOM or writes. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(process.argv[2] || resolve(dirname(fileURLToPath(import.meta.url)), '..'));
const readJSON = async name => JSON.parse(await readFile(resolve(root, name), 'utf8'));
const [manifest, events, frames, catalog] = await Promise.all([
  readJSON('data/manifest.json'), readJSON('data/events.json'),
  readJSON('data/frames.json'), readJSON('data/tool-catalog.json'),
]);
const [{ createDeviceReplay }, { createDataModel }, evidence] = await Promise.all([
  import(pathToFileURL(resolve(root, 'device-replay.js')).href),
  import(pathToFileURL(resolve(root, 'data-model.js')).href),
  import(pathToFileURL(resolve(root, 'evidence-views.js')).href),
]);
const { plantEvidence, surveyEvidence } = evidence;
const replay = createDeviceReplay(events, manifest.farms);
const model = createDataModel(manifest, events, frames, catalog);
const deviceIds = ['Matrice4T', 'Mavic3M', 'Robot0', 'Tractor'];
const farmIds = manifest.farms.map(farm => farm.id);
const poseOf = (poses, id) => poses.find(pose => pose.id === id);
const position = pose => [pose.farmId, pose.x, pose.z, pose.altitude];
const hubMethods = new Set(['charge', 'refuel', 'load_seeds', 'load_fertilizer', 'load_fungicide',
  'load_pesticide', 'return_supplies', 'unload_grain', 'attach_implement', 'detach_implement']);
let poseChecks = 0;

function assertPoses(poses, step) {
  assert.deepEqual(poses.map(pose => pose.id).sort(), deviceIds, 'Each shared device appears exactly once');
  for (const pose of poses) {
    poseChecks++;
    assert.ok(pose.farmId === null || farmIds.includes(pose.farmId));
    assert.ok([pose.x, pose.z, pose.altitude, pose.heading].every(Number.isFinite));
    if (['working', 'survey'].includes(pose.phase)) {
      assert.ok(pose.x >= 0 && pose.x <= 1 && pose.z >= 0 && pose.z <= 1,
        'Working positions stay inside the target field; transit can leave its bounds');
    }
    assert.ok(pose.altitude >= 0);
    assert.ok(pose.eventSequence === null || pose.eventSequence <= step, 'No future device action');
    assert.ok(pose.lastSurveySequence === null || pose.lastSurveySequence <= step, 'No future survey result');
    assert.equal(pose.positionSource, 'event_schematic', 'Never present synthesized positions as GPS');
    assert.ok(pose.trail.every(point => Number.isFinite(point.x) && Number.isFinite(point.z)));
    if (pose.range) {
      assert.ok(pose.range[0] >= 0 && pose.range[1] <= 63 && pose.range[0] <= pose.range[1]);
    }
  }
}

assert.ok(replay.at(0).every(pose => pose.farmId === null && pose.eventSequence === null
  && pose.lastSurveySequence === null && !pose.active));
const completedPoses = [];
for (let step = 0; step <= events.length; step++) {
  const before = replay.at(step, 0), middle = replay.at(step, .5), after = replay.at(step, 1);
  for (const poses of [before, middle, after]) assertPoses(poses, step);
  assert.deepEqual(after, replay.at(step), 'Default query is the deterministic post-operation pose');
  for (const pose of after) {
    assert.equal(pose.farmId, null, 'Completed operations leave shared devices at base');
    assert.equal(pose.phase, 'docked');
    assert.equal(pose.altitude, 0, 'A completed survey must not leave a drone hovering');
    assert.equal(pose.active, false);
    assert.deepEqual(position(pose), position(poseOf(replay.at(0), pose.id)),
      'Each device returns to the same base after either farm');
  }
  completedPoses.push(after);
  if (step === 0) continue;
  const event = events[step - 1], actor = event.scope.actor_app;
  const method = event.tool_name.split('__').at(-1);
  if (!deviceIds.includes(actor)) {
    assert.deepEqual(after, replay.at(step - 1).map(pose => ({ ...pose, active: false })),
      'Fixed-facility and world events must not move shared devices');
    continue;
  }
  const current = poseOf(after, actor);
  for (const id of deviceIds.filter(id => id !== actor)) {
    assert.deepEqual(position(poseOf(before, id)), position(poseOf(after, id)), 'Only the acting shared device moves');
  }
  if (hubMethods.has(method)) {
    assert.equal(current.farmId, null, 'Shared loading/service belongs to the hub');
    continue;
  }
  if (current.eventSequence !== step || current.range === null) continue;
  const expectedFarm = event.arguments.farm_id || event.result?.farm_id;
  assert.equal(current.missionFarmId, expectedFarm, 'Completed missions retain their actual target');
  assert.equal(poseOf(middle, actor).farmId, expectedFarm, 'Work uses the actual target farm');
  const coverage = event.result?.surveyed_ridges || event.result?.covered_ridges
    || event.result?.planted_ridges || event.result?.harvested_ridges
    || event.result?.fertilized_ridges || event.result?.sprayed_ridges;
  if (coverage?.length) assert.deepEqual(current.range, [Math.min(...coverage), Math.max(...coverage)]);
  else if (Number.isInteger(event.arguments.start_ridge)) {
    assert.deepEqual(current.range, [event.arguments.start_ridge, event.arguments.end_ridge]);
  }
  if (method === 'fly_survey') {
    const previousSurvey = poseOf(replay.at(step - 1), actor).lastSurveySequence;
    assert.equal(poseOf(before, actor).lastSurveySequence, previousSurvey);
    assert.equal(poseOf(middle, actor).lastSurveySequence, previousSurvey);
    assert.equal(current.lastSurveySequence, step, 'The new survey completes only at progress 1');
    assert.notDeepEqual(position(poseOf(before, actor)), position(poseOf(middle, actor)), 'Survey progresses along a route');
    assert.notDeepEqual(position(poseOf(middle, actor)), position(current));
  }
}

// Skipping forward, reverse seeking and interleaving progress queries cannot affect a later query.
for (let i = 0; i < 700; i++) {
  const step = (i * 137 + 19) % (events.length + 1);
  replay.at((step + 53) % (events.length + 1), .37);
  assert.deepEqual(replay.at(step), completedPoses[step]);
}
const callerCopy = replay.at(159);
callerCopy[0].x = -500;
if (callerCopy[0].trail.length) callerCopy[0].trail[0].x = -500;
assert.deepEqual(replay.at(159), completedPoses[159], 'Caller mutation cannot corrupt the replay cache');

// A partial mission can traverse its actual coverage only; a refused action cannot move a device.
const sample = [{ sequence: 1, tool_name: 'Mavic3M__fly_survey',
  arguments: { farm_id: 'soybean_field', start_ridge: 20, end_ridge: 39 },
  scope: { actor_app: 'Mavic3M', farm_ids: ['soybean_field'] }, status: 'ok',
  result: { status: 'partial', farm_id: 'soybean_field', surveyed_ridges: [20, 21] } },
{ sequence: 2, tool_name: 'Mavic3M__fly_survey',
  arguments: { farm_id: 'maize_field', start_ridge: 30, end_ridge: 35 },
  scope: { actor_app: 'Mavic3M', farm_ids: ['maize_field'] }, status: 'error',
  result: { error: 'Battery too low' } }];
const partial = createDeviceReplay(sample, manifest.farms);
const actualPartial = poseOf(partial.at(1), 'Mavic3M');
assert.deepEqual(actualPartial.range, [20, 21]);
const partialWorking = poseOf(partial.at(1, .5), 'Mavic3M');
assert.equal(partialWorking.phase, 'survey');
assert.ok(partialWorking.z >= 20 / 64 && partialWorking.z <= 22 / 64);
assert.equal(actualPartial.farmId, null, 'Partial operations also return to base');
assert.deepEqual(position(poseOf(partial.at(2), 'Mavic3M')), position(actualPartial));
assert.equal(poseOf(partial.at(2), 'Mavic3M').lastSurveySequence, 1);

// The probe value in the ridge panel must remain the latest past zone observation.
for (const step of [0, 159, 188, 189, 190, 191, 192, 193, 201, 202, 203, 204, 205, 206, 374]) {
  for (const farm of manifest.farms) {
    const candidates = events.slice(0, step).filter(event => event.result?.farm_id === farm.id
      && event.result.soil_sensors?.some(sensor => sensor.ridge_start <= 28 && sensor.ridge_end >= 28));
    const source = candidates.at(-1), observed = model.observations(step)[farm.id][28].moisture;
    if (!source) { assert.equal(observed, undefined); continue; }
    const sensor = source.result.soil_sensors.find(sensor => sensor.ridge_start <= 28 && sensor.ridge_end >= 28);
    assert.equal(observed.sequence, source.sequence);
    assert.equal(observed.value, sensor.vwc);
    assert.equal(observed.datetime, source.datetime_after);
    assert.deepEqual(observed.range, [sensor.ridge_start, sensor.ridge_end]);
    assert.ok(observed.sequence <= step);
  }
}
assert.equal(model.observations(189).maize_field[28].moisture.sequence, 181,
  'Irrigation must not invent the following probe observation');
assert.equal(model.observations(190).maize_field[28].moisture.sequence, 190);
assert.notEqual(frames[193].farms.maize_field.ridges[28].root_vwc,
  model.observations(193).maize_field[28].moisture.value, 'Root-zone truth and surface probes remain separate values');

// Evidence-view checks are below; these functions return HTML without a browser.
assert.equal(typeof plantEvidence, 'function');
assert.equal(typeof surveyEvidence, 'function');
const soy = manifest.farms.find(farm => farm.id === 'soybean_field');
const maize = manifest.farms.find(farm => farm.id === 'maize_field');
const initialPlant = { farm: soy, ridge: frames[0].farms.soybean_field.ridges[28], observations: {}, step: 0 };
const initialHTML = plantEvidence(initialPlant);
assert.equal(initialHTML, plantEvidence(initialPlant), 'Evidence illustrations are deterministic');
assert.ok(/illustrat|schematic|simulat/i.test(initialHTML), 'Generated plant graphics disclose their source');
assert.ok(!/\b(?:CV confidence|vision confidence|model confidence)\b/i.test(initialHTML), 'No invented computer-vision confidence');
assert.ok(!/Confidence\s+\d/.test(initialHTML), 'No invented detection confidence before an observation');
assert.ok(!initialHTML.includes('Recorded ground detection'));
assert.ok(!initialHTML.includes('Acquired evidence'), 'Simulation truth does not become an acquired observation');
assert.ok(initialHTML.includes('data-growth="unplanted"'));

const stageCases = [
  ['bare', false, false, 'unplanted'], ['SOWN', true, false, 'sown'],
  ['VE', true, false, 'seedling'], ['V4', true, false, 'vegetative'],
  ['R3', true, false, 'reproductive'], ['R8', true, false, 'maturity'],
  ['R8', true, true, 'harvested'],
];
const silhouettes = new Set();
for (const [growth_stage, planted, harvested, expected] of stageCases) {
  const input = { farm: soy, ridge: { ...initialPlant.ridge, growth_stage, planted, harvested }, observations: {}, step: 100 };
  const unchanged = JSON.stringify(input);
  const html = plantEvidence(input);
  assert.ok(html.includes(`data-growth="${expected}"`));
  assert.equal(html, plantEvidence(input));
  assert.equal(JSON.stringify(input), unchanged, 'Plant evidence must not modify source values');
  const shapePaths = [...html.matchAll(/<path\b[^>]*\sd="([^"]+)"/g)].map(match => match[1]);
  silhouettes.add(JSON.stringify(shapePaths));
}
assert.ok(silhouettes.size >= 6, 'Plant geometry changes across growth stages, not just its text label');
const maizeMature = plantEvidence({ farm: maize, ridge: { ...initialPlant.ridge,
  planted: true, growth_stage: 'R6_MATURE' }, step: 300 });
assert.ok(maizeMature.includes('data-growth="maturity"'));
assert.notEqual(maizeMature, plantEvidence({ farm: soy, ridge: { ...initialPlant.ridge,
  planted: true, growth_stage: 'R8' }, step: 300 }), 'The two crops have distinct illustrations');
const unknownPlant = plantEvidence({ farm: soy, ridge: { ridge_id: 28, planted: true }, step: 0 });
assert.ok(unknownPlant.includes('data-growth="unknown"'));
assert.ok(unknownPlant.includes('Unknown'));
assert.ok(unknownPlant.includes('not rendered as confirmed healthy'));

const diseaseSource = events.find(event => event.step_id === 'disease_confirm_32');
const diseaseRidge = 32;
const preDisease = model.observations(diseaseSource.sequence - 1).soybean_field[diseaseRidge];
const postDisease = model.observations(diseaseSource.sequence).soybean_field[diseaseRidge];
const beforeDiseaseHTML = plantEvidence({ farm: soy,
  ridge: frames[diseaseSource.sequence - 1].farms.soybean_field.ridges[diseaseRidge],
  observations: preDisease, step: diseaseSource.sequence - 1 });
const afterDiseaseHTML = plantEvidence({ farm: soy,
  ridge: frames[diseaseSource.sequence].farms.soybean_field.ridges[diseaseRidge],
  observations: postDisease, step: diseaseSource.sequence });
assert.equal(preDisease.disease, undefined, 'The second ground sample is not observed before its tool event');
assert.ok(!beforeDiseaseHTML.includes('Recorded ground detection'));
assert.ok(afterDiseaseHTML.includes('Recorded ground detection'));
assert.ok(afterDiseaseHTML.includes(`Confidence ${postDisease.disease.confidence.toFixed(3)}`),
  'Displayed confidence comes from the actual ground-inspection result');
const missingConfidence = plantEvidence({ farm: soy, ridge: initialPlant.ridge,
  observations: { disease: { value: false } }, step: 2 });
assert.ok(missingConfidence.includes('Confidence not recorded'));
assert.ok(!/Confidence\s+\d/.test(missingConfidence), 'A boolean detection does not invent a confidence value');

let surveyChecks = 0;
for (const event of events.filter(event => event.tool_name.endsWith('__fly_survey'))) {
  const farm = model.farmById[event.result.farm_id];
  const unchanged = JSON.stringify({ event, farm });
  const html = surveyEvidence({ event, farm });
  assert.equal(html, surveyEvidence({ event, farm }));
  assert.equal(JSON.stringify({ event, farm }), unchanged, 'Survey rendering is read-only');
  assert.ok(html.includes('data-evidence="survey"'));
  assert.ok(/not a captured image/i.test(html), 'The SVG map discloses that it is derived from numeric observations');
  assert.ok(html.includes('No disease diagnosis, plant count or confidence score has been inferred'));
  const body = html.match(/<tbody>([\s\S]*?)<\/tbody>/)?.[1] || '';
  const rows = [...body.matchAll(/<tr><th>(\d+)<\/th><td>([^<]*)<\/td><td>([^<]*)<\/td><\/tr>/g)]
    .map(([, ridgeId, ndvi, temperature]) => ({ ridgeId: Number(ridgeId), ndvi, temperature }));
  assert.equal(rows.length, event.result.observations.length);
  for (const row of rows) {
    surveyChecks++;
    const original = event.result.observations.find(value => value.ridge_id === row.ridgeId);
    assert.ok(event.result.surveyed_ridges.includes(row.ridgeId));
    if (original.ndvi === -1) assert.equal(row.ndvi, 'No reading (−1)');
    else assert.equal(Number(row.ndvi), original.ndvi, 'Exact returned NDVI stays exact');
    assert.equal(Number(row.temperature), original.canopy_temp_c, 'Exact returned temperature stays exact');
  }
  if (event.result.observations.every(row => row.ndvi === -1)) {
    assert.ok(html.includes('Canopy appearance is unknown'));
    assert.ok(html.includes('0 valid readings'));
  }
}
const noSurvey = surveyEvidence({ farm: soy });
assert.ok(noSurvey.includes('No survey values available'));
assert.ok(noSurvey.includes('Canopy appearance is unknown'));
assert.ok(!noSurvey.includes('<tbody>'), 'No numeric survey table exists before a survey');
const sparseSurvey = {
  sequence: 1, tool_name: 'Mavic3M__fly_survey', status: 'ok',
  arguments: { farm_id: soy.id, start_ridge: 20, end_ridge: 39 },
  result: { farm_id: soy.id, status: 'partial', surveyed_ridges: [20, 21], observations: [
    { ridge_id: 20, ndvi: .247839, canopy_temp_c: 23.71 },
    { ridge_id: 21, ndvi: -1, canopy_temp_c: 24.16 },
    { ridge_id: 39, ndvi: .999, canopy_temp_c: 99 },
  ] },
};
const sparseHTML = surveyEvidence({ event: sparseSurvey, farm: soy });
assert.ok(sparseHTML.includes('Partial survey'));
assert.ok(sparseHTML.includes('2 / 64'));
assert.ok(sparseHTML.includes('<tr><th>20</th><td>0.247839</td>'), 'The exact-value table preserves source precision');
assert.ok(!sparseHTML.includes('<tr><th>39</th>'), 'Unvisited requested tail cannot become evidence');
assert.ok(/data-ridge-id="39" data-status="unobserved"/.test(sparseHTML),
  'The unvisited requested tail remains unknown in the survey map');
const failedHTML = surveyEvidence({ event: { ...sparseSurvey, status: 'failed' }, farm: soy });
assert.ok(failedHTML.includes('Survey failed'), 'An event-level failure must be rejected even if a stale payload remains');
assert.ok(!failedHTML.includes('<tbody>'), 'Failed events do not supply evidence values');

console.log(JSON.stringify({ status: 'passed', events: events.length, pose_checks: poseChecks,
  random_access_queries: 700, unique_shared_devices: 4, latest_probe_checks: true,
  stage_geometries: silhouettes.size, exact_survey_values_checked: surveyChecks,
  no_browser: true, no_file_writes: true }, null, 2));
