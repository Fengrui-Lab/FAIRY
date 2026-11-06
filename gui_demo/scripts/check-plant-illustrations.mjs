import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {dirname, resolve} from 'node:path';
import {selectPlantIllustration as select} from '../plant-illustrations.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = name => readFile(resolve(root, 'data', name), 'utf8').then(JSON.parse);
const [frames, events, manifest] = await Promise.all(['frames.json', 'events.json', 'manifest.json'].map(read));
const farms = Object.fromEntries(manifest.farms.map(farm => [farm.crop_id, farm]));
const input = (crop, step, id = 28) => ({farm: farms[crop], ridge: frames[step].farms[farms[crop].id].ridges[id], step, events});
const idAt = (crop, step, id = 28) => select(input(crop, step, id))?.id ?? null;

for (const crop of ['soybean', 'maize']) {
  assert.equal(idAt(crop, 0), null);
  assert.equal(idAt(crop, 115), null, 'Pre-emergence must not show a grown plant');
  assert.equal(idAt(crop, 119), `${crop}-seedling`);
  assert.equal(idAt(crop, 124), `${crop}-vegetative`);
  assert.equal(idAt(crop, 374), null, 'Harvested ridges must use the stubble schematic');
}
assert.equal(idAt('soybean', 142), 'soybean-flowering', 'No future disease survey may select symptoms');
assert.equal(idAt('soybean', 158), 'soybean-flowering');
assert.equal(idAt('soybean', 159), 'soybean-disease');
assert.equal(idAt('soybean', 162, 0), 'soybean-flowering', 'No symptom image on an untargeted ridge');
assert.equal(idAt('soybean', 167), 'soybean-disease', 'Treatment does not imply immediate recovery');
assert.equal(idAt('soybean', 173), null, 'Waiting seven days is not a ground recheck');
assert.equal(idAt('soybean', 174), 'soybean-followup');
assert.equal(idAt('soybean', 174, 33), null, 'Ridge 33 has not been rechecked yet');
assert.equal(idAt('soybean', 175, 33), 'soybean-followup');
assert.equal(idAt('soybean', 175, 31), null, 'Low-confidence observation is not recovery evidence');
assert.equal(idAt('soybean', 175, 20), null, 'No ground follow-up exists for unsampled ridge 20');
assert.equal(idAt('soybean', 175, 0), null);
assert.equal(idAt('soybean', 188), null, 'R5 cannot use an R1 flower or R3 early-pod image');
assert.equal(idAt('soybean', 207), 'soybean-mature');
assert.equal(idAt('soybean', 254), 'soybean-mature');
assert.equal(idAt('soybean', 255), null);
assert.equal(idAt('maize', 187), 'maize-reproductive');
assert.equal(idAt('maize', 188), 'maize-water-stress');
assert.equal(idAt('maize', 188, 0), 'maize-reproductive');
assert.equal(idAt('maize', 189), 'maize-water-stress');
assert.equal(idAt('maize', 192), 'maize-water-stress', 'Soil alone does not complete the crop recheck');
assert.equal(idAt('maize', 193), 'maize-followup');
assert.equal(idAt('maize', 196), 'maize-water-stress', 'Previous follow-up must not persist into a later drought round');
assert.equal(idAt('maize', 201), 'maize-water-stress');
assert.equal(idAt('maize', 202), 'maize-water-stress');
assert.equal(idAt('maize', 205), 'maize-water-stress');
assert.equal(idAt('maize', 206), 'maize-followup');
assert.equal(idAt('maize', 207), null, 'R5 dent does not use R6 mature or early reproductive artwork');
assert.equal(idAt('maize', 292), 'maize-mature');
assert.equal(idAt('maize', 331), null);

const without = (...steps) => events.filter(event => !steps.includes(event.sequence));
assert.equal(select({...input('soybean', 175), events: without(166)})?.id ?? null, null);
assert.equal(select({...input('soybean', 175), events: without(174)})?.id ?? null, null);
for (const missing of [189, 192, 193])
  assert.equal(select({...input('maize', 193), events: without(missing)})?.id, 'maize-water-stress');
for (const missing of [202, 205, 206])
  assert.equal(select({...input('maize', 206), events: without(missing)})?.id, 'maize-water-stress');
const failed = structuredClone(events);
failed[188].status = 'error';
assert.equal(select({...input('maize', 193), events: failed})?.id, 'maize-water-stress');
const partial = structuredClone(events);
partial[158].result.status = 'partial';
partial[158].result.surveyed_ridges = [20, 21];
assert.equal(select({...input('soybean', 162), events: partial})?.id, 'soybean-flowering');
assert.equal(select({...input('soybean', 162, 20), events: partial})?.id, 'soybean-disease');
const noImprovement = structuredClone(events);
const before = noImprovement[180].result.soil_sensors.find(row => row.ridge_start <= 28 && row.ridge_end >= 28);
noImprovement[191].result.soil_sensors.find(row => row.ridge_start <= 28 && row.ridge_end >= 28).vwc = before.vwc;
assert.equal(select({...input('maize', 193), events: noImprovement})?.id, 'maize-water-stress');

for (const change of [{root_vwc: null}, {disease_pressure: NaN}, {stand_fraction: 0},
  {planted: false}, {harvested: true}, {growth_stage: 'UNKNOWN'}, {growth_stage: 'VT_TASSELING'}])
  assert.equal(select({...input('maize', 188), ridge: {...input('maize', 188).ridge, ...change}}), null);
assert.equal(select(), null);
assert.equal(select({...input('soybean', 162), step: NaN}), null);
assert.equal(select({...input('soybean', 162), events: null}), null);

let queries = 0;
const immutableBefore = JSON.stringify([events, frames[175], frames[206], manifest.farms]);
for (let step = 0; step < frames.length; step++) {
  for (const crop of ['soybean', 'maize']) {
    for (const ridgeId of [0, 20, 28, 31, 33, 39, 63]) {
      const args = input(crop, step, ridgeId);
      const full = select(args), pastOnly = select({...args, events: events.slice(0, step)});
      assert.deepEqual(full, pastOnly, 'Future events cannot affect a past illustration');
      if (full) {
        assert.match(full.url, /^assets\/media\/simulated\/(soybean|maize)-[a-z-]+\.png$/);
        assert.equal(full.kind, 'simulation illustration');
        assert.match(full.caption, /not a captured image/);
      }
      queries++;
    }
  }
}
assert.equal(JSON.stringify([events, frames[175], frames[206], manifest.farms]), immutableBefore);
console.log(JSON.stringify({status: 'passed', real_state_queries: queries,
  checks: ['actual stages', 'per-ridge harvest', 'no future events', 'wrong-ridge exclusions',
    'treatment and recheck negative controls', 'failed and partial events', 'missing-state fallback',
    'per-round water improvement evidence', 'input immutability']}, null, 2));
