#!/usr/bin/env node
/** Data and export checks for survey maps. Uses Node only and writes no files. */
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(process.argv[2] || resolve(dirname(fileURLToPath(import.meta.url)), '..'));
const readJSON = async name => JSON.parse(await readFile(resolve(root, 'data', name), 'utf8'));
const [events, manifest] = await Promise.all([readJSON('events.json'), readJSON('manifest.json')]);
const { buildSurveyMap } = await import(pathToFileURL(resolve(root, 'survey-map.js')).href);
const { surveyEvidence } = await import(pathToFileURL(resolve(root, 'evidence-views.js')).href);
assert.equal(typeof buildSurveyMap, 'function');
const original = JSON.stringify([events, manifest]);
const freeze = value => {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    Object.values(value).forEach(freeze);
  }
  return value;
};
freeze(events); freeze(manifest);
const farmById = Object.fromEntries(manifest.farms.map(farm => [farm.id, farm]));
const surveys = events.filter(event => event.tool_name.endsWith('__fly_survey'));
const soy = farmById.soybean_field, maize = farmById.maize_field;
const ids = values => [...values].map(value => typeof value === 'object' ? value.ridge_id : value).sort((a, b) => a - b);
let mapChecks = 0, ridgeChecks = 0, edgeCases = 0;

function ridgePolygons(svg) {
  return [...svg.matchAll(/<polygon\b([^>]*)>/g)].map(([, raw]) => {
    const attributes = Object.fromEntries([...raw.matchAll(/([\w:-]+)="([^"]*)"/g)].map(([, key, value]) => [key, value]));
    return attributes;
  }).filter(attributes => 'data-ridge-id' in attributes);
}

function assertExport(map) {
  mapChecks++;
  assert.equal(typeof map.svg, 'string');
  assert.match(map.svg.trim(), /^(?:<\?xml[^>]*>\s*)?<svg\b/);
  assert.match(map.svg, /xmlns="http:\/\/www\.w3\.org\/2000\/svg"/,
    'The downloaded SVG is a standalone document');
  assert.ok(map.svg.trim().endsWith('</svg>'));
  assert.ok(!/<(?:script|foreignObject|iframe|image)\b/i.test(map.svg));
  const tags = [...map.svg.matchAll(/<[^>]+>/g)].map(match => match[0]);
  assert.ok(tags.every(tag => !/\son[a-z]+\s*=/i.test(tag)), 'No executable event-handler attributes');
  assert.ok(tags.every(tag => !/(?:href|src)\s*=\s*["'](?!#)/i.test(tag)), 'SVG has no external references');
  assert.ok(!/url\(\s*["']?(?!#)[^)]/i.test(map.svg), 'SVG has no external paint resources');
  assert.ok(!/@import|@font-face/i.test(map.svg));
  const defined = new Set([...map.svg.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));
  for (const match of map.svg.matchAll(/url\(#([^)]+)\)/g)) assert.ok(defined.has(match[1]), 'All SVG paint definitions are included');
  assert.equal(typeof map.filename, 'string');
  assert.match(map.filename, /^[a-zA-Z0-9._-]+\.svg$/, 'Portable filename without path components');
  assert.equal(typeof map.title, 'string');
  assert.equal(typeof map.unit, 'string');
  assert.ok([map.min, map.max].every(Number.isFinite));
  assert.ok(map.min < map.max);
  assert.match(map.sourceResolution, /one value per ridge/i);
  assert.equal(map.hasData, map.validCount > 0);
  assert.ok(Number.isInteger(map.validCount) && map.validCount >= 0);
  assert.ok(Number.isInteger(map.coveredCount) && map.coveredCount >= map.validCount);
  assert.ok(Number.isInteger(map.missingCount) && map.missingCount >= 0);
  const polygons = ridgePolygons(map.svg);
  assert.equal(new Set(polygons.map(polygon => polygon['data-ridge-id'])).size, polygons.length,
    'Exactly one uniform polygon represents each ridge; no fabricated along-ridge pixels');
  for (const polygon of polygons) {
    ridgeChecks++;
    assert.ok(['valid', 'missing', 'unobserved'].includes(polygon['data-status']));
    if (polygon['data-status'] === 'valid') {
      assert.match(polygon.fill, /^#[\da-f]{6}$/i, 'Each measured ridge has one solid data color');
      assert.ok(Number.isFinite(Number(polygon['data-value'])));
    } else {
      assert.match(polygon.fill, /^(?:#[\da-f]{6}|url\(#[\w-]+\))$/i, 'Unknown ridges use a local missing-data symbol');
      assert.ok(!('data-value' in polygon), 'Missing ridges have no fabricated numeric values');
      const patternId = polygon.fill.match(/^url\(#([\w-]+)\)$/)?.[1];
      const pattern = patternId ? map.svg.match(new RegExp(`<pattern\\b[^>]*id="${patternId}"[^>]*>([\\s\\S]*?)</pattern>`))?.[1] : '';
      const colors = patternId ? [...(pattern || '').matchAll(/(?:fill|stroke)="(#[\da-f]{6})"/gi)].map(match => match[1]) : [polygon.fill];
      assert.ok(colors.length > 0, 'The unavailable pattern has included, inspectable colors');
      for (const color of colors) {
        const channels = [1, 3, 5].map(start => parseInt(color.slice(start, start + 2), 16));
        assert.ok(Math.max(...channels) - Math.min(...channels) <= 40,
          'Unknown values use a neutral indicator rather than a green measurement color');
      }
    }
    assert.ok(!/NaN|Infinity/.test(polygon.points));
  }
  assert.equal(polygons.filter(polygon => polygon['data-status'] === 'valid').length, map.validCount);
  return polygons;
}

assert.deepEqual(surveys.map(event => event.sequence), [110, 115, 159, 188, 201]);
const actualMaps = new Map(), names = new Set();
for (const event of surveys) {
  const farm = farmById[event.result.farm_id];
  const rawValid = event.result.observations.filter(row => Number.isFinite(row.ndvi) && row.ndvi >= 0 && row.ndvi <= 1);
  for (const contrast of ['standard', 'detail']) {
    const map = buildSurveyMap(event, farm, { layer: 'ndvi', contrast });
    const polygons = assertExport(map);
    assert.deepEqual([map.min, map.max], contrast === 'detail' ? [.75, .9] : [0, 1],
      'NDVI scales stay fixed across farms and dates, not per-event min/max');
    assert.equal(map.layer, 'ndvi');
    assert.equal(map.validCount, rawValid.length);
    assert.equal(map.coveredCount, event.result.surveyed_ridges.length);
    assert.deepEqual(ids(map.coverage.ridgeIds), event.result.surveyed_ridges);
    assert.deepEqual(ids(map.observedRidges), event.result.surveyed_ridges);
    assert.deepEqual(ids(map.validRidges), rawValid.map(row => row.ridge_id));
    assert.equal(map.missingCount, map.coveredCount - rawValid.length);
    assert.equal(map.unobservedCount, farm.num_ridges - map.coveredCount);
    assert.equal(map.missingCount + map.unobservedCount, farm.num_ridges - rawValid.length);
    assert.equal(polygons.length, farm.num_ridges);
    assert.equal(map.coverage.start, event.result.surveyed_ridges[0]);
    assert.equal(map.coverage.end, event.result.surveyed_ridges.at(-1));
    for (const polygon of polygons) {
      const ridge = Number(polygon['data-ridge-id']);
      const row = rawValid.find(value => value.ridge_id === ridge);
      if (row) assert.equal(Number(polygon['data-value']), row.ndvi, 'Map values match this event exactly');
      else assert.notEqual(polygon['data-status'], 'valid', 'No coverage is extrapolated from a later or neighboring observation');
    }
    if (!rawValid.length) {
      assert.equal(map.hasData, false);
      assert.equal(map.reason, 'no_valid_data');
      assert.equal(new Set(polygons.map(polygon => polygon.fill)).size, 1,
        'All -1 readings use the same unknown color, never green crop data');
      assert.equal(map.dataMin, null); assert.equal(map.dataMax, null);
    } else {
      assert.equal(map.dataMin, Math.min(...rawValid.map(row => row.ndvi)));
      assert.equal(map.dataMax, Math.max(...rawValid.map(row => row.ndvi)));
      assert.equal(map.reason, null);
      assert.deepEqual(ids(map.validRidges), Array.from({ length: 20 }, (_, index) => 20 + index));
      assert.equal(polygons.filter(polygon => polygon['data-status'] === 'unobserved').length, 44);
    }
    assert.deepEqual(buildSurveyMap(event, farm, { layer: 'ndvi', contrast }), map, 'Repeated renders are deterministic');
    if (contrast === 'standard') { actualMaps.set(event.sequence, map); names.add(map.filename); }
  }
  const thermal = buildSurveyMap(event, farm, { layer: 'temperature' });
  const cells = assertExport(thermal);
  assert.deepEqual([thermal.min, thermal.max], [0, 45], 'Temperature uses one fixed scale across events');
  assert.equal(thermal.validCount, event.result.observations.length);
  for (const cell of cells.filter(cell => cell['data-status'] === 'valid')) {
    const row = event.result.observations.find(value => value.ridge_id === Number(cell['data-ridge-id']));
    assert.equal(Number(cell['data-value']), row.canopy_temp_c);
  }
}
assert.equal([...actualMaps.values()].filter(map => map.hasData).length, 3);
assert.equal(names.size, 5, 'Each recorded event has its own export filename');
const patterns = [...actualMaps.values()].filter(map => map.hasData)
  .map(map => ridgePolygons(map.svg).map(polygon => `${polygon['data-ridge-id']}:${polygon.fill}`).join('|'));
assert.equal(new Set(patterns).size, 3, 'The three surveys produce distinct value-driven maps, not one repeated illustration');

function eventFor(rows, declared = rows.map(row => row.ridge_id), overrides = {}) {
  return { sequence: 11, tool_name: 'Mavic3M__fly_survey', status: 'ok', datetime_after: '2026-07-20T08:42:43+08:00',
    arguments: { farm_id: soy.id, start_ridge: 20, end_ridge: 39 },
    result: { status: 'ok', farm_id: soy.id, surveyed_ridges: declared, observations: rows }, ...overrides };
}
const sample = [{ ridge_id: 20, ndvi: .801, canopy_temp_c: 27.5 }, { ridge_id: 21, ndvi: .827, canopy_temp_c: 28.25 }];
const validEvent = eventFor(sample);
const partial = eventFor([...sample, { ridge_id: 39, ndvi: .999, canopy_temp_c: 42 }], [20, 21]);
partial.result.status = 'partial';
const partialMap = buildSurveyMap(partial, soy);
const partialCells = assertExport(partialMap);
assert.equal(partialMap.coveredCount, 2); assert.equal(partialMap.validCount, 2);
assert.deepEqual(ids(partialMap.validRidges), [20, 21]);
assert.equal(partialCells.find(cell => cell['data-ridge-id'] === '39')['data-status'], 'unobserved');
edgeCases++;

for (const [badEvent, farm, reason] of [
  [{ ...validEvent, status: 'failed' }, soy, 'failed_event'],
  [{ ...validEvent, error: 'Rejected' }, soy, 'failed_event'],
  [{ ...validEvent, result: { ...validEvent.result, status: 'error' } }, soy, 'failed_event'],
  [validEvent, maize, 'wrong_farm'],
  [{ ...validEvent, tool_name: 'Robot0__inspect_crop_health' }, soy, 'wrong_tool'],
]) {
  const map = buildSurveyMap(badEvent, farm); assertExport(map);
  assert.equal(map.reason, reason); assert.equal(map.hasData, false);
  assert.equal(map.validCount, 0); assert.equal(map.coveredCount, 0);
  edgeCases++;
}

const repeated = eventFor([...sample, { ridge_id: 20, ndvi: -1, canopy_temp_c: 31 },
  { ridge_id: 21, ndvi: .744321, canopy_temp_c: 29.75 }], [20, 21, 21]);
const repeatedMap = buildSurveyMap(repeated, soy), repeatedCells = assertExport(repeatedMap);
assert.equal(repeatedMap.coveredCount, 2); assert.equal(repeatedMap.validCount, 1);
assert.equal(repeatedCells.find(cell => cell['data-ridge-id'] === '20')['data-status'], 'missing');
assert.equal(Number(repeatedCells.find(cell => cell['data-ridge-id'] === '21')['data-value']), .744321,
  'Duplicates use the last source record without averaging or rounding it');
assert.deepEqual(ids(repeatedMap.duplicateRidges), [20, 21]);
edgeCases++;

const invalidRows = [-1, Infinity, -Infinity, NaN, null, undefined, '0.8', -0.2, 1.2]
  .map((ndvi, index) => ({ ridge_id: index + 20, ndvi, canopy_temp_c: NaN }));
const invalidMap = buildSurveyMap(eventFor(invalidRows), soy); assertExport(invalidMap);
assert.equal(invalidMap.validCount, 0); assert.equal(invalidMap.hasData, false);
edgeCases++;
const validLimits = buildSurveyMap(eventFor([{ ridge_id: 20, ndvi: 0 }, { ridge_id: 21, ndvi: 1 }]), soy);
assertExport(validLimits); assert.equal(validLimits.validCount, 2);
edgeCases++;

const outOfRange = eventFor([{ ridge_id: 20, ndvi: .7, canopy_temp_c: 55 },
  { ridge_id: 21, ndvi: .8, canopy_temp_c: -5 }, { ridge_id: 22, ndvi: .9, canopy_temp_c: -1 }]);
const temperatureMap = buildSurveyMap(outOfRange, soy, { layer: 'temperature' });
const temperatureCells = assertExport(temperatureMap);
assert.equal(temperatureMap.validCount, 2); assert.equal(temperatureMap.clippedCount, 2);
assert.equal(Number(temperatureCells.find(cell => cell['data-ridge-id'] === '20')['data-value']), 55);
assert.equal(Number(temperatureCells.find(cell => cell['data-ridge-id'] === '21')['data-value']), -5);
assert.deepEqual([temperatureMap.min, temperatureMap.max], [0, 45]);
edgeCases++;

// The same numeric value must keep its color when other ridges or event dates change.
for (const contrast of ['standard', 'detail']) {
  const a = buildSurveyMap(eventFor([{ ridge_id: 20, ndvi: .8 }, { ridge_id: 21, ndvi: .79 }]), soy, { contrast });
  const b = buildSurveyMap(eventFor([{ ridge_id: 20, ndvi: .8 }, { ridge_id: 21, ndvi: .99 }], [20, 21], { sequence: 200 }), soy, { contrast });
  assert.equal(ridgePolygons(a.svg).find(cell => cell['data-ridge-id'] === '20').fill,
    ridgePolygons(b.svg).find(cell => cell['data-ridge-id'] === '20').fill,
    'Fixed scales must not stretch the same value differently across events');
  edgeCases++;
}

const hostile = '\"><script>alert(1)</script><image href="https://example.invalid/pixel" onload="alert(2)">';
const hostileMap = buildSurveyMap({ ...validEvent, sequence: hostile, datetime_after: hostile,
  tool_name: 'Mavic3M__fly_survey' }, { ...soy, label: hostile, crop_id: hostile });
assertExport(hostileMap);
assert.ok(!hostileMap.svg.includes(hostile), 'Metadata cannot break out of SVG text or attributes');
edgeCases++;

for (const [event, farm] of [[null, null], [{}, {}], [validEvent, { ...soy, num_ridges: 0 }],
  [validEvent, { ...soy, num_ridges: -12 }], [validEvent, { ...soy, num_ridges: NaN }],
  [validEvent, { ...soy, num_ridges: 1000000000 }]]) {
  const map = buildSurveyMap(event, farm);
  assert.equal(typeof map.svg, 'string');
  assert.ok(map.svg.length < 4000000, 'Invalid field dimensions must not allocate unbounded SVG output');
  assert.deepEqual(buildSurveyMap(event, farm), map);
  edgeCases++;
}

for (let i = 0; i < 50; i++) {
  const event = surveys[(i * 3) % surveys.length];
  buildSurveyMap(surveys[(i + 2) % surveys.length], farmById[surveys[(i + 2) % surveys.length].result.farm_id], { contrast: 'detail' });
  assert.deepEqual(buildSurveyMap(event, farmById[event.result.farm_id]), actualMaps.get(event.sequence),
    'Later calls cannot leak future survey values into an earlier event');
}

// Supplementary images are optional, exact-event references. They never alter
// the numeric evidence or replace the recorded map by default.
const assetCatalog = JSON.parse(await readFile(resolve(root, 'assets/catalog.json'), 'utf8'));
const exampleSlots = assetCatalog.assets.filter(asset => asset.role === 'ndvi_example');
assert.equal(assetCatalog.assets.length, 16);
assert.deepEqual(exampleSlots.map(asset => asset.survey_sequence).sort((a, b) => a - b), [159, 188, 201]);
const hasExampleImage = html => /<img\b[^>]*class="ev-example-image"/.test(html);
const hasExampleOption = html => /data-survey-source="example"/.test(html);
const metricMarkup = html => html.match(/<dl class="ev-metrics">[\s\S]*?<\/dl>/)?.[0];
const exactValues = html => html.match(/<tbody>[\s\S]*?<\/tbody>/)?.[0];
const coverageMarkup = html => html.match(/<div class="ev-coverage">[\s\S]*?<\/div>/)?.[0];
let sourceChecks = 0;
function assertImageRejected(input, message) {
  const html = surveyEvidence({ ...input, source: 'example' });
  assert.equal(hasExampleImage(html), false, message);
  assert.equal(hasExampleOption(html), false, message);
  assert.ok(html.includes('data-layer='), 'Rejected example requests fall back to the recorded map');
  sourceChecks++;
}
for (const slot of exampleSlots) {
  const event = events[slot.survey_sequence - 1], farm = farmById[slot.farm_id];
  assert.equal(event.result.farm_id, slot.farm_id);
  assert.equal(slot.from_step, slot.survey_sequence);
  assert.equal(slot.to_step, slot.survey_sequence);
  const example = { ...slot, url: `https://example.invalid/ndvi-${event.sequence}.png`,
    caption: `External illustration for event ${event.sequence}` };
  const unchanged = JSON.stringify(example);
  const baseline = surveyEvidence({ event, farm });
  assert.equal(hasExampleImage(baseline), false, 'No illustrative image appears without a supplied source');
  assert.equal(hasExampleOption(baseline), false);
  const defaultWithImage = surveyEvidence({ event, farm, example });
  assert.equal(hasExampleImage(defaultWithImage), false, 'Configured images do not replace the default recorded map');
  assert.equal(hasExampleOption(defaultWithImage), true);
  const shown = surveyEvidence({ event, farm, example, source: 'example' });
  assert.equal(hasExampleImage(shown), true, 'A valid NDVI example is available only for its exact event and farm');
  assert.ok(shown.includes('Illustrative NDVI map'));
  assert.ok(shown.includes('Example imagery is independent of the recorded ridge values'));
  assert.ok(metricMarkup(baseline) && exactValues(baseline) && coverageMarkup(baseline),
    'The reference panel contains the numeric summaries, exact rows and coverage being compared');
  assert.equal(metricMarkup(shown), metricMarkup(baseline), 'Example selection preserves measured summary values');
  assert.equal(exactValues(shown), exactValues(baseline), 'Example selection preserves every exact returned value');
  assert.equal(coverageMarkup(shown), coverageMarkup(baseline), 'Example selection preserves the actual coverage');
  assert.equal(JSON.stringify(example), unchanged, 'Rendering never changes the source slot');
  sourceChecks += 3;
  assertImageRejected({ event, farm, example, layer: 'temperature' }, 'NDVI illustrations cannot become thermal images');
  assertImageRejected({ event, farm, example: { ...example, survey_sequence: event.sequence + 1 } }, 'A later event image cannot be displayed early');
  assertImageRejected({ event, farm, example: { ...example, farm_id: farm.id === soy.id ? maize.id : soy.id } }, 'An image cannot cross farm boundaries');
  assertImageRejected({ event, farm: farm.id === soy.id ? maize : soy,
    example: { ...example, farm_id: farm.id === soy.id ? maize.id : soy.id } }, 'Conflicting event and farm metadata cannot display an image');
  assertImageRejected({ event: { ...event, status: 'failed' }, farm, example }, 'A failed survey cannot display a successful example');
  assertImageRejected({ event: { ...event, result: { ...event.result, status: 'error' } }, farm, example }, 'Result-level failure rejects an example');
  for (const altered of [
    { ...event, arguments: { ...event.arguments, farm_id: farm.id === soy.id ? maize.id : soy.id } },
    { ...event, status: 'cancelled' },
    { ...event, tool_name: 'Robot0__inspect_crop_health' },
  ]) assertImageRejected({ event: altered, farm, example }, 'Examples respect map rejection for conflicting scope, cancellation and wrong tool');
  assertImageRejected({ event, farm, example: { ...example, url: '' } }, 'Empty source slots do not create placeholder images');
  assertImageRejected({ event, farm, example: null }, 'No source means no example image');
  for (const url of ['javascript:alert(1)', 'file:///private/tmp/fake.png', 'ftp://example.invalid/fake.png',
    'data:text/html;base64,PHNjcmlwdD4=', 'data:image/svg+xml,<svg onload="alert(1)"/>']) {
    assertImageRejected({ event, farm, example: { ...example, url } }, 'Only supported web/image sources may be embedded');
  }
}
for (const event of surveys.filter(event => !actualMaps.get(event.sequence).hasData)) {
  assertImageRejected({ event, farm: farmById[event.result.farm_id], example: {
    farm_id: event.result.farm_id, survey_sequence: event.sequence,
    url: 'https://example.invalid/unobserved.png', caption: 'Never show this as acquired evidence',
  } }, 'No-reading surveys cannot be replaced by a green illustrative image');
}
assertImageRejected({ event: {}, farm: soy, example: {
  farm_id: soy.id, survey_sequence: undefined, url: 'https://example.invalid/no-event.png',
} }, 'No event means no acquired illustration');

// Saved assets must be byte-equivalent to current builder output and their
// index must retain the same event, time, coverage and fixed scale metadata.
const exportDirectory = resolve(root, 'assets/survey-maps');
const exportedIndex = JSON.parse(await readFile(resolve(exportDirectory, 'index.json'), 'utf8'));
const expectedKeys = surveys.flatMap(event => [
  `${event.sequence}:ndvi:standard`, `${event.sequence}:temperature:standard`,
  ...(actualMaps.get(event.sequence).hasData ? [`${event.sequence}:ndvi:detail`] : []),
]).sort();
assert.deepEqual(exportedIndex.maps.map(item => `${item.step}:${item.layer}:${item.contrast}`).sort(), expectedKeys,
  'All five surveys have standard maps; only the three valid NDVI surveys have detail exports');
assert.equal(new Set(exportedIndex.maps.map(item => item.file)).size, exportedIndex.maps.length);
assert.deepEqual((await readdir(exportDirectory)).filter(file => file.endsWith('.svg')).sort(),
  exportedIndex.maps.map(item => item.file).sort(), 'Every stored SVG appears exactly once in the export index');
for (const item of exportedIndex.maps) {
  const event = events[item.step - 1], farm = farmById[item.farm_id];
  assert.ok(surveys.includes(event));
  assert.equal(item.farm_id, event.result.farm_id);
  const map = buildSurveyMap(event, farm, { layer: item.layer, contrast: item.contrast });
  assert.equal(item.file, map.filename);
  assert.equal(item.acquired_at, event.datetime_after);
  assert.deepEqual(item.scale, [map.min, map.max]);
  assert.deepEqual(item.data_range, [map.dataMin, map.dataMax]);
  assert.equal(item.valid_ridges, map.validCount);
  assert.equal(item.covered_ridges, map.coveredCount);
  assert.equal(item.source, map.sourceResolution);
  assert.equal(item.is_captured_image, false);
  const saved = await readFile(resolve(exportDirectory, item.file), 'utf8');
  assert.equal(saved.trimEnd(), map.svg.trimEnd(), `Saved SVG must match its event and current builder: ${item.file}`);
}
assert.equal(JSON.stringify([events, manifest]), original, 'Recorded events and farm metadata are never changed');
console.log(JSON.stringify({ status: 'passed', recorded_surveys: surveys.length, valid_ndvi_maps: 3,
  unknown_ndvi_maps: 2, exported_maps_checked: mapChecks, ridge_checks: ridgeChecks,
  edge_cases: edgeCases, random_access_queries: 50, source_slot_checks: sourceChecks,
  material_slots: assetCatalog.assets.length, saved_svg_matches: exportedIndex.maps.length,
  no_browser: true, no_file_writes: true }, null, 2));
