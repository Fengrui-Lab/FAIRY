#!/usr/bin/env node
/** Check the exported replay and observation model without a browser or writes. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { createGunzip } from 'node:zlib';

const root = resolve(process.argv[2] || resolve(dirname(fileURLToPath(import.meta.url)), '..'));
const json = async name => JSON.parse(await readFile(resolve(root, name), 'utf8'));
const [manifest, events, frames, catalog, assets, hashes, modelSource] = await Promise.all([
  json('data/manifest.json'), json('data/events.json'), json('data/frames.json'),
  json('data/tool-catalog.json'), json('assets/catalog.json'), json('data/file-manifest.json'),
  readFile(resolve(root, 'data-model.js'), 'utf8'),
]);
// The web demo intentionally has no package.json; load its dependency-free ES module explicitly.
const { createDataModel, UNKNOWN } = await import(`data:text/javascript;base64,${Buffer.from(modelSource).toString('base64')}`);
const model = createDataModel(manifest, events, frames, catalog);
const farmIds = ['soybean_field', 'maize_field'];
const ids64 = Array.from({ length: 64 }, (_, i) => i);
const sorted = values => [...values].sort();
const sameIds = (actual, expected, message) => assert.deepEqual(sorted(actual), sorted(expected), message);
const eventByName = new Map(events.map(event => [event.step_id, event]));
const toolByName = new Map(catalog.tools.map(tool => [tool.name, tool]));
const titles = new Set(['observe', 'diagnose', 'act', 'resource', 'wait', 'report']);
let observationChecks = 0;

assert.equal(manifest.scenario_id, 'scenario_two_farm_soybean_maize_disease_water');
assert.equal(events.length, 374);
assert.equal(frames.length, 375);
assert.equal(manifest.event_count, events.length);
assert.equal(manifest.frame_count, frames.length);
assert.equal(manifest.validation.success, true);
assert.ok(Object.values(manifest.checks).every(value => value === true));
sameIds(manifest.farms.map(farm => farm.id), farmIds, 'Exactly the two configured farm plots are present');
assert.equal(manifest.farms.find(farm => farm.id === farmIds[0]).label, 'farm plot A');
assert.equal(manifest.farms.find(farm => farm.id === farmIds[1]).label, 'farm plot B');
assert.equal(new Set(events.map(event => event.step_id)).size, events.length);

const useCounts = new Map();
const fixedTargets = {
  SoybeanFarm: 'soybean_field', Soybean_Sensor: 'soybean_field', Soybean_Irrigation: 'soybean_field',
  MaizeFarm: 'maize_field', Maize_Sensor: 'maize_field', Maize_Irrigation: 'maize_field',
};
const sharedApps = new Set(['Tractor', 'Mavic3M', 'Matrice4T', 'Robot0', 'Warehouse']);
for (const [index, frame] of frames.entries()) {
  assert.equal(frame.index, index);
  assert.equal(Date.parse(frame.datetime) / 1000, frame.timestamp);
  sameIds(Object.keys(frame.farms), farmIds);
  for (const farmId of farmIds) {
    const ridges = frame.farms[farmId].ridges;
    assert.deepEqual(ridges.map(ridge => ridge.ridge_id), ids64, `Frame ${index}: local ridge IDs are 0-63`);
    for (const ridge of ridges) {
      for (const key of ['soil_vwc', 'root_vwc', 'disease_pressure', 'pest_pressure', 'nutrient_index', 'grain_moisture_pct', 'stand_fraction']) {
        assert.ok(Number.isFinite(ridge[key]), `Frame ${index}, ${farmId}, ridge ${ridge.ridge_id}: finite ${key}`);
      }
      assert.ok(ridge.soil_vwc >= 0 && ridge.soil_vwc <= 1);
      assert.ok(ridge.root_vwc >= 0 && ridge.root_vwc <= 1);
    }
  }
  if (index === 0) continue;
  const event = events[index - 1];
  assert.equal(event.sequence, index);
  assert.equal(event.snapshot_before, index - 1);
  assert.equal(event.snapshot_after, index);
  assert.equal(frame.timestamp, event.time_after);
  assert.equal(event.time_before, frames[index - 1].timestamp, `Event ${index}: global clock is continuous`);
  assert.ok(event.time_after >= event.time_before);
  assert.equal(Date.parse(event.datetime_before) / 1000, event.time_before);
  assert.equal(Date.parse(event.datetime_after) / 1000, event.time_after);
  assert.equal(event.status, 'ok');
  assert.ok(!event.error);
  assert.ok(titles.has(event.category));
  assert.ok(event.title && !/[\u3400-\u9fff]/u.test(event.title));
  assert.ok(toolByName.has(event.tool_name), `Event ${index}: tool exists in runtime catalog`);
  useCounts.set(event.tool_name, (useCounts.get(event.tool_name) || 0) + 1);
  const app = event.tool_name.split('__')[0];
  assert.equal(event.scope.actor_app, app);
  sameIds(event.scope.world_farm_ids, farmIds);
  assert.ok(event.scope.farm_ids.every(id => farmIds.includes(id)));
  if (fixedTargets[app]) {
    assert.equal(event.scope.actor_scope, 'fixed');
    assert.equal(event.scope.kind, 'farm_plot');
    assert.deepEqual(event.scope.farm_ids, [fixedTargets[app]]);
  }
  if (event.arguments.farm_id) {
    assert.equal(event.scope.kind, 'farm_plot');
    assert.deepEqual(event.scope.farm_ids, [event.arguments.farm_id]);
    if (event.result?.farm_id) assert.equal(event.result.farm_id, event.arguments.farm_id);
  }
  if (sharedApps.has(app)) assert.equal(event.scope.actor_scope, 'shared');
  if (['SystemApp', 'WeatherApp', 'AgentUserInterface'].includes(app)) {
    assert.equal(event.scope.actor_scope, 'global');
    assert.equal(event.scope.kind, 'global');
    sameIds(event.scope.farm_ids, farmIds);
  }
  if (event.result?.batch?.origin_farm_id) {
    assert.deepEqual(event.scope.farm_ids, [event.result.batch.origin_farm_id]);
  }
}

assert.equal(catalog.tools.length, 73);
assert.equal(catalog.tools.filter(tool => tool.exposed).length, 72);
assert.equal(useCounts.size, 42);
assert.equal(catalog.runtime_count, catalog.tools.length);
assert.equal(catalog.agent_exposed_count, 72);
assert.equal(catalog.used_count, useCounts.size);
assert.equal(manifest.runtime_tool_count, 73);
assert.equal(manifest.agent_exposed_tool_count, 72);
assert.equal(manifest.executed_tool_count, 42);
assert.equal(toolByName.size, catalog.tools.length);
assert.deepEqual(catalog.runtime_only_names, ['AgentUserInterface__send_message_to_agent']);
for (const tool of catalog.tools) {
  assert.equal(tool.schema.type, 'function');
  assert.equal(tool.schema.function.name, tool.name);
  assert.equal(tool.app, tool.name.split('__')[0]);
  assert.equal(tool.exposed, tool.name !== 'AgentUserInterface__send_message_to_agent');
  assert.equal(tool.use_count, useCounts.get(tool.name) || 0);
  assert.equal(tool.output_schema, null, 'Do not invent a formal output schema');
  const firstUse = events.find(event => event.tool_name === tool.name);
  assert.deepEqual(tool.output_example, firstUse?.result ?? null);
}

// Check observation provenance independently of the visual frame's simulation truth.
// An observed value must belong to an executed source event and its actual coverage.
for (let step = 0; step <= events.length; step++) {
  const observed = model.observations(step);
  for (const farmId of farmIds) for (const [ridgeId, fields] of observed[farmId].entries()) {
    for (const [kind, observation] of Object.entries(fields)) {
      observationChecks++;
      assert.ok(observation.sequence > 0 && observation.sequence <= step, `Step ${step}: no future observation`);
      const source = events[observation.sequence - 1];
      assert.equal(observation.tool, source.tool_name);
      assert.equal(observation.datetime, source.datetime_after);
      assert.ok(source.time_after <= frames[step].timestamp);
      const sourceFarm = source.result.farm_id || (source.scope.farm_ids.length === 1 ? source.scope.farm_ids[0] : null);
      assert.equal(sourceFarm, farmId, 'Observation cannot cross farm ownership');
      if (kind === 'moisture') {
        const sensor = source.result.soil_sensors.find(value => value.sensor_id === observation.sensorId);
        assert.ok(sensor, 'Observed moisture came from an actual probe');
        assert.ok(ridgeId >= sensor.ridge_start && ridgeId <= sensor.ridge_end, 'Probe values stay within actual coverage');
        assert.equal(observation.value, sensor.vwc);
        assert.equal(observation.temperature, sensor.temp_c);
        assert.deepEqual(observation.range, [sensor.ridge_start, sensor.ridge_end]);
      } else {
        const row = Object.values(source.result.observations).find(value => value.ridge_id === ridgeId);
        assert.ok(row, 'Observed disease or NDVI came from an actual sampled ridge');
        const coverage = source.result.covered_ridges || source.result.surveyed_ridges;
        if (coverage) assert.ok(coverage.includes(ridgeId), 'No extrapolation outside actual mission coverage');
        if (kind === 'disease') {
          assert.equal(observation.value, row.disease_present);
          assert.equal(observation.confidence, row.disease_confidence);
        } else if (kind === 'ndvi') {
          assert.equal(observation.value, row.ndvi ?? row.ndvi_proxy);
        } else assert.fail(`Unexpected observation kind ${kind}`);
      }
    }
  }
}
for (const farmId of farmIds) {
  assert.ok(model.observations(0)[farmId].every(row => Object.keys(row).length === 0));
  assert.ok(model.colors(farmId, 0, 'moisture', 'observation').every(color => color === UNKNOWN));
  assert.ok(model.colors(farmId, 0, 'disease', 'observation').every(color => color === UNKNOWN));
}

// Deliberately sparse observations prove that the model does not fill unsampled ridges
// with simulation truth, borrow another farm's sample, or reveal the next event.
const synthetic = [
  { sequence: 1, datetime_after: events[0].datetime_after, tool_name: 'Soybean_Sensor__read_soil_sensors', status: 'ok',
    scope: { farm_ids: ['soybean_field'] }, result: { farm_id: 'soybean_field',
      soil_sensors: [{ sensor_id: 'TEST', ridge_start: 20, ridge_end: 22, vwc: .217, temp_c: 19 }] } },
  { sequence: 2, datetime_after: events[1].datetime_after, tool_name: 'Robot0__inspect_crop_health', status: 'ok',
    scope: { farm_ids: ['maize_field'] }, result: { farm_id: 'maize_field', covered_ridges: [28],
      observations: { 28: { ridge_id: 28, disease_present: true, disease_confidence: .8 } } } },
];
const sparse = createDataModel(manifest, synthetic, frames, catalog);
assert.deepEqual(sparse.observations(1).soybean_field.flatMap((row, i) => row.moisture ? [i] : []), [20, 21, 22]);
assert.ok(sparse.observations(1).maize_field.every(row => Object.keys(row).length === 0));
assert.deepEqual(sparse.observations(2).maize_field.flatMap((row, i) => row.disease ? [i] : []), [28]);
assert.ok(sparse.observations(2).soybean_field.every(row => !row.disease));

const initial = frames[0];
assert.ok(farmIds.every(id => initial.farms[id].ridges.every(r => !r.planted && !r.harvested)));
assert.equal(initial.farms.soybean_field.ridges[28].soil_vwc, .303);
assert.equal(initial.farms.soybean_field.ridges[28].root_vwc, .303);
assert.equal(initial.farms.soybean_field.ridges[28].disease_pressure, .20);
assert.equal(initial.farms.maize_field.ridges[28].disease_pressure, .02);
const final = frames.at(-1);
for (const farmId of farmIds) {
  assert.equal(model.summary(374, farmId).harvested, 64);
  const batches = Object.values(final.warehouse.grain_batches).filter(batch => batch.origin_farm_id === farmId);
  assert.deepEqual(batches.flatMap(batch => batch.ridge_ids).sort((a, b) => a - b), ids64);
  assert.ok(batches.every(batch => batch.status === 'stored' && batch.quantity_kg > 0));
}
assert.equal(final.farms.maize_field.management.irrigation_used_mm_total, 12.5);
assert.equal(final.farms.soybean_field.management.irrigation_used_mm_total, 0);
assert.equal(initial.warehouse.stock.pesticide_liters - final.warehouse.stock.pesticide_liters, 76);

const milestoneSources = {
  disease_before: 'disease_confirm_32', disease_after: 'disease_treat_30', disease_followup: 'disease_followup_32',
  water_before: 'drought_thermal', water_after: 'drought_irrigate', water_followup: 'drought_crop_recheck',
};
for (const [key, name] of Object.entries(milestoneSources)) assert.equal(manifest.milestones[key], eventByName.get(name).sequence);
assert.equal(manifest.milestones.final, 374);
for (const asset of assets.assets) {
  assert.ok(Number.isInteger(asset.from_step) && Number.isInteger(asset.to_step));
  assert.ok(asset.from_step >= 0 && asset.to_step >= asset.from_step && asset.to_step <= 374);
  assert.ok(asset.farm_id === null || farmIds.includes(asset.farm_id));
  if (asset.role === 'disease_before') {
    assert.ok(asset.from_step >= eventByName.get('disease_multispectral').sequence);
    assert.ok(asset.to_step < eventByName.get('disease_treat_20').sequence);
  }
  if (asset.role === 'disease_followup') assert.ok(asset.from_step >= eventByName.get('disease_followup_28').sequence);
  if (asset.role === 'water_before') assert.equal(asset.from_step, eventByName.get('drought_thermal').sequence);
  if (asset.role === 'water_followup') assert.ok(asset.from_step >= eventByName.get('grain_fill_maize_recheck').sequence);
  if (asset.role === 'water_second_before') assert.equal(asset.from_step, eventByName.get('drought_second_thermal').sequence);
  if (asset.role === 'water_second_followup') assert.ok(asset.from_step >= eventByName.get('drought_second_recheck').sequence);
  if (asset.url) assert.ok(asset.source_type && asset.caption, 'Supplied media needs source type and caption');
}

for (const [name, record] of Object.entries(hashes)) {
  const bytes = await readFile(resolve(root, 'data', name));
  assert.equal(bytes.length, record.bytes, `${name}: byte count`);
  assert.equal(createHash('sha256').update(bytes).digest('hex'), record.sha256, `${name}: SHA-256 integrity`);
}
let auditCount = 0;
const auditLines = createInterface({ input: createReadStream(resolve(root, 'data/audit-snapshots.jsonl.gz')).pipe(createGunzip()), crlfDelay: Infinity });
for await (const line of auditLines) {
  const audit = JSON.parse(line);
  assert.equal(audit.index, auditCount);
  assert.equal(audit.timestamp, frames[auditCount].timestamp);
  if (auditCount > 0) assert.equal(audit.after_step_id, events[auditCount - 1].step_id);
  auditCount++;
}
assert.equal(auditCount, 375);
console.log(JSON.stringify({ status: 'passed', events: events.length, frames: frames.length,
  runtime_tools: catalog.tools.length, agent_exposed_tools: 72, executed_tools: useCounts.size,
  observation_provenance_checks: observationChecks, audit_frames: auditCount,
  asset_slots: assets.assets.length, no_browser: true, no_file_writes: true }, null, 2));
