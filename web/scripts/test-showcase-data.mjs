import assert from 'node:assert/strict';
import { test } from 'node:test';
import { SCENES, FRAMES, makeSteps, regions, mediaFor, area, formatTime, regionColor } from '../src/showcase/data.ts';

test('Pinned scenario dimensions, crops and device ownership', () => {
  assert.deepEqual(SCENES.two.fields.map(f => [f.id, f.cultivar, f.width, f.rows]), [['soybean_field', 'SOYBEAN_901', 70.4, 2], ['maize_field', 'MAIZE_201', 48, 1]]);
  assert.deepEqual(SCENES.two.equipment, ['Tractor', 'Drone', 'Robot']);
  assert.equal(area(SCENES.two.fields[0]).toFixed(5), '1.88672');
  assert.equal(area(SCENES.two.fields[1]).toFixed(5), '1.28640');
  assert.deepEqual(SCENES.three.fields.map(f => f.id), ['farm_a', 'farm_b', 'farm_c']);
  assert.ok(SCENES.three.fields.every(f => f.crop === 'Soybean' && f.cultivar === 'HEINONG84' && f.length === 268));
  assert.equal(new Set(SCENES.three.fields.map(f => f.sensor)).size, 3);
  assert.equal(new Set(SCENES.three.fields.map(f => f.irrigation)).size, 3);
  assert.deepEqual(SCENES.three.equipment, ['Tractor', 'Mavic3M', 'Matrice4T', 'Robot0']);
});
test('240 deterministic chronological steps per scenario, with valid frame / field / region / media references', () => {
  for (const scene of Object.values(SCENES)) {
    const steps = makeSteps(scene), cells = regions(scene);
    assert.equal(steps.length, 240); assert.equal(new Set(steps.map(s => s.id)).size, 240);
    assert.deepEqual(steps, makeSteps(scene));
    assert.deepEqual(FRAMES.map(f => steps.filter(s => s.frameId === f.id).length), [40, 40, 40, 40, 40, 40]);
    steps.forEach((s, i) => {
      const field = scene.fields.find(f => f.id === s.fieldId);
      assert.ok(field); assert.ok(cells.some(c => c.id === s.regionId && c.fieldId === field.id));
      assert.ok(FRAMES.some(f => f.id === s.frameId));
      if (i) assert.ok(s.time >= steps[i - 1].time);
      if (s.mediaId) { const m = mediaFor(scene, field); assert.equal(s.mediaId, m.id); assert.equal(s.regionId, m.regionId); }
    });
  }
});
test('Spatial cells exactly cover each field; soil water units and severity semantics stay valid', () => {
  for (const scene of Object.values(SCENES)) for (const frame of FRAMES) {
    const cells = regions(scene, frame);
    assert.equal(new Set(cells.map(c => c.id)).size, scene.fields.length * 16);
    for (const f of scene.fields) {
      const local = cells.filter(c => c.fieldId === f.id);
      assert.ok(Math.abs(local.reduce((a, c) => a + c.width * c.length, 0) - f.width * f.length) < 1e-8);
      assert.ok(local.every(c => c.x - c.width / 2 >= f.x - f.width / 2 - 1e-9 && c.x + c.width / 2 <= f.x + f.width / 2 + 1e-9));
      assert.ok(local.every(c => c.moisture >= .12 && c.moisture <= .38));
      if (f.crop === 'Maize') assert.ok(local.every(c => c.severity === 'N/A'));
      else assert.equal(local.filter(c => c.severity === 'High').length, frame.pestVisible ? 1 : 0);
    }
  }
  const r = regions(SCENES.two)[0], f = SCENES.two.fields[0];
  assert.notEqual(regionColor({ ...r, moisture: .221 }, f, 'moisture'), regionColor({ ...r, moisture: .229 }, f, 'moisture'));
});
test('Scenario calendars are formatted explicitly rather than in browser local time', () => {
  assert.equal(formatTime(SCENES.two.start, SCENES.two, true), '07:00');
  assert.equal(formatTime(SCENES.three.start, SCENES.three, true), '07:00');
  assert.equal(SCENES.two.timezone, 'Europe/Paris'); assert.equal(SCENES.three.timezone, 'Asia/Shanghai');
});
