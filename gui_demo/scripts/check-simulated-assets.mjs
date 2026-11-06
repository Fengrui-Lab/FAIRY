#!/usr/bin/env node
/** Validate bundled illustrations and read-only evidence switching without a browser. */
import assert from 'node:assert/strict';
import { readFile, readdir, realpath } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { dirname, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(process.argv[2] || resolve(dirname(fileURLToPath(import.meta.url)), '..'));
const json = async name => JSON.parse(await readFile(resolve(root, name), 'utf8'));
const [manifest, events, frames, tools, catalog] = await Promise.all([
  json('data/manifest.json'), json('data/events.json'), json('data/frames.json'),
  json('data/tool-catalog.json'), json('assets/catalog.json'),
]);
const [{ plantEvidence, surveyEvidence, illustrativeNDVILegend }, { selectPlantIllustration }, { createDataModel }] = await Promise.all([
  import(pathToFileURL(resolve(root, 'evidence-views.js')).href),
  import(pathToFileURL(resolve(root, 'plant-illustrations.js')).href),
  import(pathToFileURL(resolve(root, 'data-model.js')).href),
]);
const model = createDataModel(manifest, events, frames, tools);
const imageDirectory = resolve(root, 'assets/media/simulated');
const expectedFiles = [
  ...['seedling', 'vegetative', 'flowering', 'disease', 'followup', 'mature'].map(state => `soybean-${state}.png`),
  ...['seedling', 'vegetative', 'reproductive', 'water-stress', 'followup', 'mature'].map(state => `maize-${state}.png`),
  'ndvi-soybean-159.png', 'ndvi-maize-188.png', 'ndvi-maize-201.png',
].sort();
assert.deepEqual((await readdir(imageDirectory)).filter(name => name.endsWith('.png')).sort(), expectedFiles);
const pngInfo = new Map();
for (const filename of expectedFiles) {
  const bytes = await readFile(resolve(imageDirectory, filename));
  assert.deepEqual(bytes.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), `PNG signature: ${filename}`);
  assert.equal(bytes.toString('ascii', 12, 16), 'IHDR');
  const width = bytes.readUInt32BE(16), height = bytes.readUInt32BE(20);
  assert.deepEqual([width, height], [1536, 1024], `Landscape native dimensions: ${filename}`);
  assert.ok(bytes.length > 10000, 'A generated image must not be an empty placeholder');
  assert.equal(bytes.toString('ascii', bytes.length - 8, bytes.length - 4), 'IEND', `Complete PNG: ${filename}`);
  pngInfo.set(filename, { width, height, sha256: createHash('sha256').update(bytes).digest('hex') });
}
const ndviFiles = expectedFiles.filter(name => name.startsWith('ndvi-'));
assert.equal(new Set(ndviFiles.map(name => pngInfo.get(name).sha256)).size, 3,
  'Three historical NDVI examples are three different raster files');

const assetRoot = await realpath(resolve(root, 'assets'));
async function assertBundledURL(url) {
  assert.match(url, /^assets\//, 'Runtime assets use repository-relative URLs');
  assert.ok(!url.includes('\\') && !url.includes('\0'));
  assert.ok(!decodeURIComponent(url).split('/').includes('..'), 'Asset URLs cannot traverse outside assets');
  const target = await realpath(resolve(root, url));
  assert.ok(target.startsWith(assetRoot + sep), 'Resolved image remains inside assets, including symlinks');
  return target;
}
const filled = catalog.assets.filter(asset => asset.url), empty = catalog.assets.filter(asset => !asset.url);
assert.equal(catalog.assets.length, 16); assert.equal(filled.length, 12); assert.equal(empty.length, 4);
assert.equal(filled.filter(asset => asset.role === 'ndvi_example').length, 3);
assert.equal(filled.filter(asset => asset.role === 'crop_reference').length, 2);
assert.equal(filled.filter(asset => !['ndvi_example', 'crop_reference'].includes(asset.role)).length, 7);
for (const asset of filled) {
  assert.equal(asset.kind, 'image');
  const target = await assertBundledURL(asset.url);
  assert.match(asset.source_type, /illustration/i);
  assert.match(asset.actual_or_illustrative, /illustrat/i);
  assert.match(asset.status, /simulation_example/);
  assert.ok(asset.caption && asset.context && asset.source_or_creator);
  assert.equal(asset.acquired_at, null, 'Generated examples do not invent an observation acquisition time');
  assert.deepEqual(asset.missing_fields, []);
  const bytes = await readFile(target);
  assert.deepEqual(asset.original_image_dimensions, [bytes.readUInt32BE(16), bytes.readUInt32BE(20)]);
}
for (const asset of empty) {
  assert.equal(asset.priority, 'optional');
  assert.equal(asset.acquired_at, null);
  assert.ok(asset.missing_fields.length > 0, 'Unfilled optional material is still explicitly missing');
}
for (const name of (await readdir(root)).filter(name => /\.(?:js|html|css)$/.test(name))) {
  const text = await readFile(resolve(root, name), 'utf8');
  assert.ok(!/file:\/\/|\/Users\/|\/private\/(?:tmp|var)|[A-Z]:\\\\Users\\/i.test(text),
    `No machine-specific runtime paths in ${name}`);
}

const metrics = html => [...html.matchAll(/<dl class="ev-metrics">[\s\S]*?<\/dl>/g)].map(match => match[0]);
const acquired = html => html.match(/<details class="ev-observations">[\s\S]*?<\/details>/)?.[0] || null;
const rasterShown = html => /<img\b[^>]*class="ev-plant-image"/.test(html);
const scenarios = [
  ['soybean_field', 119, 0, 'soybean-seedling'], ['soybean_field', 124, 0, 'soybean-vegetative'],
  ['soybean_field', 142, 0, 'soybean-flowering'], ['soybean_field', 162, 28, 'soybean-disease'],
  ['soybean_field', 175, 28, 'soybean-followup'], ['soybean_field', 216, 0, 'soybean-mature'],
  ['maize_field', 119, 0, 'maize-seedling'], ['maize_field', 124, 0, 'maize-vegetative'],
  ['maize_field', 142, 0, 'maize-reproductive'], ['maize_field', 188, 28, 'maize-water-stress'],
  ['maize_field', 193, 28, 'maize-followup'], ['maize_field', 292, 0, 'maize-mature'],
];
let switches = 0, blockedRasters = 0;
for (const [farmId, step, ridgeId, expectedId] of scenarios) {
  const farm = model.farmById[farmId], ridge = frames[step].farms[farmId].ridges[ridgeId];
  const illustration = selectPlantIllustration({ farm, ridge, step, events });
  assert.equal(illustration?.id, expectedId);
  await assertBundledURL(illustration.url);
  const input = { farm, ridge, step, observations: model.observations(step)[farmId][ridgeId], illustration };
  const before = JSON.stringify(input);
  const rendered = plantEvidence({ ...input, source: 'example' });
  const schematic = plantEvidence({ ...input, source: 'schematic' });
  assert.equal(rasterShown(rendered), true);
  assert.equal(rasterShown(schematic), false);
  assert.ok(schematic.includes('class="ev-plant-svg"'));
  assert.ok(rendered.includes('Plant image'));
  assert.ok(rendered.includes('State view'));
  assert.ok(rendered.includes(`data-plant-example="${expectedId}"`));
  assert.ok(metrics(rendered).length > 0, 'Compared cards actually contain recorded metrics');
  assert.deepEqual(metrics(rendered), metrics(schematic), 'Raster/schematic switching preserves every displayed metric');
  assert.equal(acquired(rendered), acquired(schematic), 'Switching imagery leaves acquired probe and ground observations unchanged');
  assert.ok(rendered.includes(ridge.root_vwc.toFixed(3)));
  assert.ok(rendered.includes(ridge.disease_pressure.toFixed(3)));
  assert.equal(plantEvidence({ ...input, source: 'example' }), rendered, 'Switching back is deterministic');
  assert.equal(JSON.stringify(input), before, 'Rendering does not change simulation or observation records');
  const noImage = plantEvidence({ ...input, illustration: null, source: 'example' });
  assert.equal(rasterShown(noImage), false, 'Absent raster falls back to the state schematic');
  switches++;
}

const reference = { id: 'maize-water-stress', title: 'Simulation illustration',
  url: 'assets/media/simulated/maize-water-stress.png', caption: 'Synthetic example; not measured evidence.' };
for (const farm of manifest.farms) {
  const base = frames[142].farms[farm.id].ridges[0];
  for (const ridge of [
    frames[0].farms[farm.id].ridges[0],
    { ...base, planted: false, harvested: true, growth_stage: 'BARE' },
    { ...base, growth_stage: 'UNKNOWN' }, { ...base, growth_stage: '' },
    { ...base, growth_stage: 'PLANTED_PRE_EMERGENCE' }, { ...base, stand_fraction: 0 },
  ]) {
    const html = plantEvidence({ farm, ridge, step: 142, illustration: reference, source: 'example' });
    assert.equal(rasterShown(html), false, 'Unplanted, pre-emergence, harvested, unknown or absent stand cannot show a live plant raster');
    assert.ok(!html.includes('data-plant-source="example"'));
    blockedRasters++;
  }
}
for (const url of ['javascript:alert(1)', 'file:///private/tmp/plant.png', '/Users/someone/plant.png',
  '/private/tmp/plant.png', 'assets/media/simulated/plant.png" onerror="alert(1)']) {
  const html = plantEvidence({ farm: model.farmById.maize_field,
    ridge: frames[142].farms.maize_field.ridges[0], illustration: { ...reference, url }, source: 'example' });
  assert.equal(rasterShown(html), false, 'Unsupported or unsafe raster URLs fall back to the schematic');
  blockedRasters++;
}

const legend = illustrativeNDVILegend();
assert.match(legend, /<strong>NDVI<\/strong>/);
for (const tick of ['0.00', '0.25', '0.50', '0.75', '1.00']) assert.ok(legend.includes(`>${tick}</span>`));
for (const slot of filled.filter(asset => asset.role === 'ndvi_example')) {
  const event = events[slot.survey_sequence - 1], farm = model.farmById[slot.farm_id];
  const example = { ...slot, url: new URL(slot.url, 'http://demo.invalid/gui_demo/').href };
  const shown = surveyEvidence({ event, farm, example, source: 'example' });
  const recorded = surveyEvidence({ event, farm, example, source: 'recorded' });
  assert.ok(shown.includes(legend), 'Every NDVI image carries its color legend');
  assert.ok(!recorded.includes(legend), 'Recorded ridge maps keep their separate measurement scale');
  assert.deepEqual(metrics(shown), metrics(recorded));
}
console.log(JSON.stringify({ status: 'passed', png_files: expectedFiles.length,
  png_dimensions: '1536x1024', distinct_ndvi_files: 3, material_slots: catalog.assets.length,
  filled_material_slots: filled.length, optional_empty_slots: empty.length,
  plant_source_switches: switches, blocked_plant_rasters: blockedRasters,
  illustrative_legends: 3, no_browser: true, no_file_writes: true }, null, 2));
