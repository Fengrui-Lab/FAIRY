/** Local-only screenshot harness. Requires Playwright in the caller's tooling environment. */
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright');
const base = process.env.SHOWCASE_URL || 'http://127.0.0.1:5173';
const output = resolve(root, '../docs/figures/showcase');
const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) });
const errors = [], apiCalls = [], failures = [];
const report = { status: 'running', viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2, base, screenshots: [], checks: [], errors, apiCalls, failures };
const check = (name, value) => { assert.ok(value, name); report.checks.push(name); };
function track(page) {
  page.on('pageerror', e => errors.push({ message: e.message, stack: e.stack, url: page.url() }));
  page.on('request', r => { if (r.url().includes('/api/') || r.url().includes('ws:')) apiCalls.push({ url: r.url(), method: r.method() }); });
  page.on('response', r => { if (r.status() >= 400) failures.push(`${r.status()} ${r.url()}`); });
}
async function ready(page) {
  await page.waitForLoadState('networkidle');
  await page.evaluate(async () => { await document.fonts.ready; await Promise.all([...document.images].map(i => i.decode().catch(() => {}))); });
  await page.waitForTimeout(900);
}
async function verify(page) {
  const app = page.getByTestId('showcase');
  await page.goto(`${base}/showcase?preset=investigation`); await ready(page);
  await page.getByRole('button', { name: 'Close evidence', exact: true }).click();
  await page.getByTestId('region-soybean_field:r2c1').click();
  check('Hotspot opens the matching aerial PiP', await page.getByTestId('media-pip').isVisible());
  const pipMedia = await page.locator('.sc-pip-image > img').getAttribute('data-media-id');
  check('Trajectory thumbnail and hotspot share a media ID', pipMedia === await page.locator('.sc-media-thumb > img').getAttribute('data-media-id'));
  await page.getByRole('button', { name: 'Close evidence', exact: true }).click();
  const before = await app.evaluate(e => ({ field: e.dataset.field, region: e.dataset.region, layer: e.dataset.layer }));
  await page.getByRole('tab', { name: '3D World', exact: true }).click(); await ready(page);
  check('3D renders a WebGL canvas', await page.locator('canvas[data-rendered=true]').count() === 1);
  check('2D → 3D retains field / region / layer', JSON.stringify(before) === JSON.stringify(await app.evaluate(e => ({ field: e.dataset.field, region: e.dataset.region, layer: e.dataset.layer }))));
  await page.getByRole('tab', { name: '2D Map', exact: true }).click();
  check('3D → 2D retains the selected region', await app.getAttribute('data-region') === before.region);
  await page.getByLabel('Map layer', { exact: true }).selectOption('moisture');
  check('Moisture legend has explicit physical units', (await page.getByTestId('layer-legend').innerText()).includes('m³/m³'));
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
  check('SVG map zoom responds', (await page.locator('.sc-map-controls').innerText()).includes('120%'));
  await page.getByRole('button', { name: 'Reset map', exact: true }).click();
  const svg = page.locator('.sc-map > svg'), bounds = await svg.boundingBox();
  await page.mouse.move(bounds.x + 100, bounds.y + 110); await page.mouse.down(); await page.mouse.move(bounds.x + 150, bounds.y + 140, { steps: 5 }); await page.mouse.up();
  check('SVG map pans with pointer drag', (await page.locator('.sc-map > svg > g').getAttribute('transform')).startsWith('translate(0 0)') === false);
  await page.getByRole('tab', { name: '3D World', exact: true }).click(); await ready(page);
  await page.locator('.sc-world-label').filter({ hasText: 'Maize field' }).click();
  check('3D field label selects the correct farm', await app.getAttribute('data-field') === 'maize_field');
  const canvas = await page.locator('canvas').boundingBox();
  for (const [x, y] of [[.5, .5], [.47, .4], [.6, .55], [.45, .6]]) {
    await page.mouse.click(canvas.x + canvas.width * x, canvas.y + canvas.height * y);
    if (await app.getAttribute('data-region')) break;
  }
  check('3D raycasting selects an actual region', !!(await app.getAttribute('data-region')));
  await page.getByLabel('Scenario', { exact: true }).selectOption('three'); await ready(page);
  check('Three-farm mode uses its source calendar and location', (await page.locator('.sc-clock').innerText()).includes('Asia/Shanghai') && (await page.locator('.sc-scenario-meta').innerText()).includes('Harbin'));
  check('Three farms show only HEINONG84 soybean', await page.locator('.sc-world-label').count() === 3 && (await page.locator('.sc-world-label').allTextContents()).every(t => t.includes('HEINONG84')));
  check('Shared equipment switches with scenario', (await page.locator('.sc-resource-bar').innerText()).includes('Matrice4T') && (await page.locator('.sc-resource-bar').innerText()).includes('Robot0'));
  await page.getByRole('tab', { name: 'Crop Management', exact: true }).click();
  await page.getByTestId('field-farm_b').press('Enter');
  await page.locator('.sc-bindings summary').click();
  check('Field-specific devices track farm selection', (await page.locator('.sc-bindings').innerText()).includes('FarmB_Sensor') && (await page.locator('.sc-bindings').innerText()).includes('FarmB_Irrigation'));
  check('Three-farm crop legend does not invent maize', !(await page.getByTestId('layer-legend').innerText()).includes('Maize'));
  await page.getByRole('button', { name: 'Locate step 240', exact: true }).click();
  check('Long trajectory can locate the final step and its frame', await app.getAttribute('data-frame') === 'frame-5' && (await page.getByTestId('step-detail').innerText()).includes('#240'));
  await page.getByLabel('Figure preset', { exact: true }).selectOption('trajectory');
  await page.getByTestId('step-98').hover();
  check('Hover reveals a tool / time / image preview', await page.getByRole('tooltip').isVisible() && await page.locator('.sc-hover img').count() === 1);
  await page.mouse.move(1900, 1050);
  const savedState = await app.evaluate(e => JSON.stringify(e.dataset));
  await page.reload(); await ready(page);
  check('Shared URL restores selected frame, field, region and layer', savedState === await app.evaluate(e => JSON.stringify(e.dataset)));
  check('All displayed local media decode', await page.evaluate(() => [...document.images].every(i => i.complete && i.naturalWidth > 0)));
  const workbench = await browser.newPage({ viewport: report.viewport });
  const farmWrites = [];
  workbench.on('request', r => { if (r.url().includes('/api/') && r.method() !== 'GET') farmWrites.push(r.url()); });
  await workbench.goto(base); await ready(workbench);
  check('Original workbench still renders its scenario selector', await workbench.locator('.app-shell .scenario-picker select').count() === 1);
  check('Original workbench loads without issuing farm commands', farmWrites.length === 0);
  const health = await workbench.request.get(`${base}/api/health`);
  check('Existing API health responds successfully', health.ok());
  const catalog = await workbench.request.get(`${base}/api/catalog`);
  check('Existing scenario catalog remains available', catalog.ok());
  await workbench.close();
}
try {
  if (process.argv.includes('--media')) {
    const page = await browser.newPage({ viewport: { width: 1000, height: 460 }, deviceScaleFactor: 1 });
    track(page);
    const mediaDir = resolve(root, 'public/showcase-media');
    await mkdir(mediaDir, { recursive: true });
    for (const [scene, fields] of Object.entries({ two: ['soybean_field', 'maize_field'], three: ['farm_a', 'farm_b', 'farm_c'] })) {
      for (const field of fields) {
        await page.goto(`${base}/showcase?scene=${scene}&capture=${field}`);
        await page.locator('canvas[data-rendered=true]').waitFor(); await ready(page);
        await page.locator('canvas').screenshot({ path: resolve(mediaDir, `${scene}-${field}.png`) });
        console.log(`Media: ${scene}/${field}`);
      }
    }
    await page.close();
  }
  if (!process.argv.includes('--media-only')) {
    const page = await browser.newPage({ viewport: report.viewport, deviceScaleFactor: 2 });
    track(page);
    await mkdir(output, { recursive: true });
    for (const [index, preset] of ['overview', 'trajectory', 'moisture', 'investigation', 'management'].entries()) {
      await page.goto(`${base}/showcase?preset=${preset}`); await ready(page);
      await page.mouse.move(1900, 1050);
      const file = `${String(index + 1).padStart(2, '0')}-${preset}.png`;
      await page.screenshot({ path: resolve(output, file) });
      const state = await page.locator('[data-testid=showcase]').evaluate(el => ({ ...el.dataset }));
      check(`${preset}: all images load`, await page.evaluate(() => [...document.images].every(i => i.complete && i.naturalWidth > 0)));
      const layout = await page.evaluate(() => {
        const pip = document.querySelector('.sc-pip')?.getBoundingClientRect(), viewport = document.querySelector('.sc-viewport').getBoundingClientRect();
        return { noOverflow: document.documentElement.scrollWidth === innerWidth && document.documentElement.scrollHeight === innerHeight, pipInside: !pip || (pip.left >= viewport.left && pip.right <= viewport.right && pip.top >= viewport.top && pip.bottom <= viewport.bottom) };
      });
      check(`${preset}: viewport and PiP fit without clipping`, layout.noOverflow && layout.pipInside);
      await page.reload(); await ready(page);
      check(`${preset}: direct URL restores fixed state`, JSON.stringify(state) === await page.locator('[data-testid=showcase]').evaluate(el => JSON.stringify(el.dataset)));
      report.screenshots.push({ preset, file, state, pixels: [3840, 2160] });
      console.log(`Screenshot: ${file}`);
    }
    if (process.argv.includes('--verify')) await verify(page);
    await page.close();
  }
  report.status = errors.length || apiCalls.length || failures.length ? 'failed' : 'passed';
} catch (error) {
  report.status = 'failed'; errors.push({ harness: error.message }); process.exitCode = 1;
} finally {
  await browser.close();
  await mkdir(output, { recursive: true });
  await writeFile(resolve(output, 'capture-report.json'), JSON.stringify(report, null, 2) + '\n');
}
if (errors.length || apiCalls.length || failures.length) { console.error(JSON.stringify(report, null, 2)); process.exitCode = 1; }
