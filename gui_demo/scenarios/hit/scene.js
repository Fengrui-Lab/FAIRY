import * as THREE from '../../vendor/three.module.js';
import { getHitMotion, hitBounds, HIT_HOMES, HIT_MOTION_NOTE } from './motion.js';
import { hitSceneLayout, inRect, roiLocal, DRONE_FIELDS, DRONE_ROADS, DRONE_TREE_STRIPS, droneCropSamples } from './scene-layout.js';

// This renderer illustrates the recorded HIT workflow. Terrain, vegetation,
// equipment size and altitude are schematic; all overlays share image space.
const NS = 'http://www.w3.org/2000/svg';
const COLORS = { rice: '#8ea975', maize: '#b7a961', soybean: '#749684', other: '#abb393' };
const LABELS = { rice: 'Rice', maize: 'Maize', soybean: 'Soybean', other: 'Other vegetation' };
let sceneSerial = 0;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const assetUrl = value => value ? new URL(value, import.meta.url).href : null;
const validPoint = p => Array.isArray(p) && p.length >= 2 && p.slice(0, 2).every(Number.isFinite);
const outline = data => (data.farm?.boundary || []).filter(validPoint);
const roiOutline = data => (data.roi?.polygon || []).filter(validPoint);
const cropId = (data, row) => typeof row.cropId === 'string' ? row.cropId : data.crops?.find(crop => crop.classId === (row.classId ?? row.cropId))?.id || 'other';
const cropColor = (data, id) => data.crops?.find(crop => crop.id === id)?.naturalColor || COLORS[id] || COLORS.other;
const ratioOf = data => Math.max(.2, Math.min(2, (Number(data.farm?.height_m) || 147) / (Number(data.farm?.width_m) || 283)));
const builtSurfaceAt = (data, p) => [...(data.surfaceHints?.buildings || []), ...(data.surfaceHints?.roads || [])].some(box => Math.abs(p.x - box.x) <= box.width / 2 && Math.abs(p.y - box.y) <= box.height / 2);

function samplesOf(data) {
  if (Array.isArray(data.surfaceHints?.fieldSamples)) return data.surfaceHints.fieldSamples.filter(p => !builtSurfaceAt(data, p));
  if (Array.isArray(data.cropSamples)) return data.cropSamples.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y));
  const grid = data.cropGrid;
  if (!grid?.values || !grid.width || !grid.height) return [];
  const samples = [], stride = Math.max(2, Math.ceil(Math.sqrt(grid.width * grid.height / 1500)));
  for (let y = stride / 2 | 0; y < grid.height; y += stride) for (let x = stride / 2 | 0; x < grid.width; x += stride) {
    const classId = grid.values[y * grid.width + x];
    if (classId > 0) samples.push({ x: (x + .5) / grid.width, y: (y + .5) / grid.height, classId });
  }
  return samples;
}

export function createHitScene(container, options = {}, onPick = () => {}) {
  let state = { data: {}, dimension: '2d', step: 0, layer: 'natural', progress: 1, miniature: false, equipmentFocus: null, ...options };
  let view = null, disposed = false;
  const host = document.createElement('div');
  host.dataset.motionNote = HIT_MOTION_NOTE;
  Object.assign(host.style, { width: '100%', height: '100%', minHeight: state.miniature ? '150px' : '320px', position: 'relative', overflow: 'hidden', background: '#f1f3ed' });
  container.appendChild(host);

  function mount() {
    view?.destroy(); host.replaceChildren();
    view = state.dimension === '3d' ? create3D(host, state, onPick) : create2D(host, state, onPick);
  }
  mount();
  return {
    update(next = {}) {
      if (disposed) return;
      const previousData = state.data, previousDimension = state.dimension, previousMiniature = state.miniature;
      state = { ...state, ...next };
      if (previousData !== state.data || previousDimension !== state.dimension || previousMiniature !== state.miniature) mount();
      else view.update(state);
    },
    resetView() { if (!disposed) view.resetView(); },
    destroy() { if (!disposed) { disposed = true; view?.destroy(); host.remove(); } },
  };
}

function create2D(host, initial, onPick) {
  let state = initial, staticKey = '';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 1100 600');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'HIT farm plot with satellite and drone workflow. Select the plot to explore in 3D.');
  Object.assign(svg.style, { display: 'block', width: '100%', height: '100%', minHeight: initial.miniature ? '150px' : '320px' });
  host.appendChild(svg);
  const uid = `hit-map-${++sceneSerial}`;
  const layout = hitSceneLayout(state.data), map = layout.farm, inset = layout.inset;
  const pixel = p => [map.x + p[0] * map.width, map.y + p[1] * map.height];
  const detailPixel = p => inRect(p, inset);
  const detailFromFarm = p => detailPixel(roiLocal(p, layout.roiBounds));
  const path = rows => rows.map((p, i) => `${i ? 'L' : 'M'}${pixel(p).join(' ')}`).join(' ');
  const points = rows => rows.map(p => pixel(p).join(',')).join(' ');
  const detailPoints = rows => rows.map(p => detailPixel(p).join(',')).join(' ');
  const detailPath = rows => rows.map((p, i) => `${i ? 'L' : 'M'}${detailFromFarm(p).join(' ')}`).join(' ');
  const classSamples = samplesOf(state.data);
  const image = (href, attrs = '') => href ? `<image href="${esc(assetUrl(href))}" x="${map.x}" y="${map.y}" width="${map.width}" height="${map.height}" preserveAspectRatio="none" ${attrs}/>` : '';

  function staticMarkup() {
    const data = state.data, boundary = outline(data), roi = roiOutline(data), assets = data.assets || {};
    const natural = state.layer === 'natural';
    const surfaces = data.surfaceHints || {};
    const roads = (surfaces.roads || []).map(road => {
      const [x, y] = pixel([road.x - road.width / 2, road.y - road.height / 2]);
      return `<rect x="${x}" y="${y}" width="${road.width * map.width}" height="${road.height * map.height}" fill="#aab0a6"/>`;
    }).join('');
    const buildings = (surfaces.buildings || []).map(building => {
      const [x, y] = pixel([building.x - building.width / 2, building.y - building.height / 2]);
      const w = Math.max(2, building.width * map.width), h = Math.max(2, building.height * map.height);
      return `<rect x="${x + 1}" y="${y + 1.8}" width="${w}" height="${h}" fill="#8c9793" opacity=".45"/><rect x="${x}" y="${y}" width="${w}" height="${h}" fill="#c8ceca" stroke="#8e9a96" stroke-width=".65"/>`;
    }).join('');
    const regionMarkup = (data.cropRegions || []).map(region => {
      const id = cropId(data, region), d = (region.rings || []).map(ring => `${path(ring)}Z`).join(' ');
      return `<path d="${d}" fill="${esc(cropColor(data, id))}" fill-rule="evenodd" opacity=".45"/>`;
    }).join('');
    const plants = classSamples.map(sample => {
      const [x, y] = pixel([sample.x, sample.y]), id = cropId(data, sample), color = cropColor(data, id);
      if (id === 'rice' || id === 'maize') return `<path d="M${x - 1.5} ${y + 2}l1.5-4 1.5 4m-1.5-3v4" stroke="${esc(color)}" stroke-width="1.1" fill="none"/>`;
      return `<circle cx="${x}" cy="${y}" r="1.7" fill="${esc(color)}" opacity=".9"/>`;
    }).join('');
    const [roiLeft, roiTop, roiRight, roiBottom] = data.roi?.bounds || hitBounds(roi);
    const orthoOrigin = pixel([roiLeft, roiTop]);
    const ortho = state.layer === 'drone' && state.step >= 6 && assets.orthomosaic ? `<image href="${esc(assetUrl(assets.orthomosaic))}" x="${orthoOrigin[0]}" y="${orthoOrigin[1]}" width="${(roiRight - roiLeft) * map.width}" height="${(roiBottom - roiTop) * map.height}" preserveAspectRatio="none" clip-path="url(#${uid}-roi)"/>` : '';
    const detailNatural = `<rect x="${inset.x}" y="${inset.y}" width="${inset.width}" height="${inset.height}" fill="#e7e9dc"/>${DRONE_FIELDS.map((polygon, index) => `<polygon points="${detailPoints(polygon)}" fill="${index ? '#aab991' : '#b4c29b'}" stroke="#93a684" stroke-width=".8"/>`).join('')}${droneCropSamples().map(p => { const [x, y] = detailPixel([p.x, p.y]); return `<path d="M${x - 1} ${y + 1.4}l1-2.7 1 2.7" fill="none" stroke="#80976b" stroke-width=".65"/>`; }).join('')}${DRONE_ROADS.map(road => `<polyline points="${detailPoints(road.points)}" fill="none" stroke="#b3b2a2" stroke-width="${road.width * inset.width}" stroke-linecap="round" stroke-linejoin="round"/>`).join('')}${DRONE_TREE_STRIPS.map(polygon => `<polygon points="${detailPoints(polygon)}" fill="#77956d"/>`).join('')}`;
    const detailImage = state.layer === 'drone' && state.step >= 6 ? `<image href="${esc(assetUrl(assets.orthomosaic))}" x="${inset.x}" y="${inset.y}" width="${inset.width}" height="${inset.height}" preserveAspectRatio="none"/>` : '';
    const detailMask = state.layer === 'drone' && state.step >= 7 ? `<image href="${esc(assetUrl(assets.droneMask))}" x="${inset.x - roiLeft / (roiRight - roiLeft) * inset.width}" y="${inset.y - roiTop / (roiBottom - roiTop) * inset.height}" width="${inset.width / (roiRight - roiLeft)}" height="${inset.height / (roiBottom - roiTop)}" preserveAspectRatio="none" opacity=".78"/>` : '';
    const roiTopPoint = pixel([roiLeft, roiTop]), roiBottomPoint = pixel([roiLeft, roiBottom]);
    const detailMarkup = state.step >= 4 ? `<g data-pick="farm" role="button" tabindex="0" aria-label="Explore the enlarged drone survey area in 3D" style="cursor:pointer"><rect x="${inset.x - 7}" y="${inset.y - 7}" width="${inset.width + 14}" height="${inset.height + 14}" rx="4" fill="#f8faf3" stroke="#b4c2b5"/><g clip-path="url(#${uid}-detail)">${detailNatural}${detailImage}${detailMask}</g><rect x="${inset.x}" y="${inset.y}" width="${inset.width}" height="${inset.height}" fill="none" stroke="#75978c" stroke-width="1.5"/></g><g pointer-events="none"><path d="M${inset.x + inset.width} ${inset.y}L${roiTopPoint.join(' ')}M${inset.x + inset.width} ${inset.y + inset.height}L${roiBottomPoint.join(' ')}" fill="none" stroke="#79a093" stroke-width="1.3" stroke-dasharray="6 6"/><text x="${inset.x}" y="${inset.y - 31}" fill="#526f63" font-size="17" font-family="Arial,sans-serif">Drone survey detail</text><text x="${inset.x}" y="${inset.y - 13}" fill="#8b9b91" font-size="10" font-family="Arial,sans-serif">Selected area · enlarged view of the same farm</text></g>` : '';
    const [labelX, labelY] = pixel([.015, -.08]);
    svg.innerHTML = `<desc>${esc(HIT_MOTION_NOTE)}</desc><defs><pattern id="${uid}-grid" width="30" height="30" patternUnits="userSpaceOnUse"><path d="M30 0H0V30" fill="none" stroke="#dfe6dc" stroke-width=".65"/></pattern><clipPath id="${uid}-farm"><polygon points="${points(boundary)}"/></clipPath><clipPath id="${uid}-roi"><polygon points="${points(roi)}"/></clipPath><clipPath id="${uid}-detail"><rect x="${inset.x}" y="${inset.y}" width="${inset.width}" height="${inset.height}"/></clipPath><filter id="${uid}-shadow" x="-50%" y="-50%" width="200%" height="200%"><feDropShadow dx="0" dy="2" stdDeviation="3" flood-opacity=".12"/></filter></defs>
      <rect width="1100" height="600" fill="#f1f3ed"/><rect width="1100" height="600" fill="url(#${uid}-grid)"/>
      <path d="M35 540H1070M930 48V550" stroke="#e2e6dc" stroke-width="18" fill="none"/>
      <g data-pick="farm" role="button" tabindex="0" aria-label="Explore HIT farm plot in 3D" style="cursor:pointer">
        <polygon points="${points(boundary)}" fill="#b6b99b" stroke="#718873" stroke-width="2"/>
        <g clip-path="url(#${uid}-farm)">${regionMarkup}${roads}${plants}${buildings}${!natural ? image(assets.satelliteRgb, 'opacity=".92"') : ''}${state.layer === 'satellite' && state.step >= 3 ? image(assets.satelliteMask, 'opacity=".58"') : ''}${ortho}${state.layer === 'drone' && state.step >= 7 ? image(assets.droneMask, 'opacity=".78"') : ''}</g>
        <polygon points="${points(boundary)}" fill="none" stroke="#668273" stroke-width="1.6"/>
        ${state.step >= 4 ? `<polygon points="${points(roi)}" fill="#d7e9df" fill-opacity=".07" stroke="#4e8d8e" stroke-width="1.7" stroke-dasharray="6 4"/>` : ''}
      </g>
      ${detailMarkup}
      <g pointer-events="none"><text x="${labelX}" y="${labelY}" fill="#526b63" font-size="21" font-family="Arial,sans-serif">${esc(data.farm?.label || 'HIT farm plot')}</text><text x="${labelX}" y="${labelY + 22}" fill="#8a9c91" font-size="11" font-family="Arial,sans-serif">Satellite context · Drone survey area</text></g>
      <g id="${uid}-routes" pointer-events="none"></g><g id="${uid}-scan" pointer-events="none"></g>
      <g data-pick="Satellite" role="button" tabindex="0" aria-label="Inspect satellite" style="cursor:pointer"><circle r="25" fill="white" stroke="#c2cdcc" filter="url(#${uid}-shadow)"/><g fill="#899fa7" stroke="#5f7985" stroke-width="1.3"><rect x="-23" y="-7" width="15" height="14" rx="1"/><rect x="8" y="-7" width="15" height="14" rx="1"/><rect x="-7" y="-9" width="14" height="18" rx="3" fill="#d8e2de"/><path d="M-18-7V7M-13-7V7M13-7V7M18-7V7M-23 0h15M8 0h15"/><path d="M0-9v-7m-4 0h8"/></g><text y="42" text-anchor="middle" font-size="12" fill="#71858b" font-family="Arial,sans-serif">Satellite</text></g>
      <g data-pick="Drone" role="button" tabindex="0" aria-label="Inspect drone" style="cursor:pointer"><circle r="25" fill="white" stroke="#c2cdcc" filter="url(#${uid}-shadow)"/><g stroke="#68808a" stroke-width="3" fill="none"><path d="M-13-10L13 10M13-10L-13 10"/><circle cx="-15" cy="-12" r="7" stroke-width="1.6"/><circle cx="15" cy="-12" r="7" stroke-width="1.6"/><circle cx="-15" cy="12" r="7" stroke-width="1.6"/><circle cx="15" cy="12" r="7" stroke-width="1.6"/></g><rect x="-7" y="-6" width="14" height="12" rx="3" fill="#8da4aa"/><text y="42" text-anchor="middle" font-size="12" fill="#71858b" font-family="Arial,sans-serif">Drone</text></g>`;
  }

  function update(next) {
    state = next;
    const key = `${state.layer}|${state.step >= 3}|${state.step >= 4}|${state.step >= 6}|${state.step >= 7}`;
    if (key !== staticKey) { staticKey = key; staticMarkup(); }
    const poses = getHitMotion(state.data, state.step, state.progress);
    svg.querySelector(`#${uid}-routes`).innerHTML = poses.filter(p => p.shown && Number(state.step) === p.missionStep).map(p => `<path d="${path(p.route)}" fill="none" stroke="${p.id === 'Satellite' ? '#899bb0' : '#438b89'}" stroke-width="${p.id === 'Satellite' ? 1.3 : 1}" stroke-dasharray="${p.id === 'Satellite' ? '6 6' : '4 3'}" opacity=".7"/>${p.id === 'Drone' && state.step === 5 ? `<path d="${detailPath(p.route)}" fill="none" stroke="#4a8b81" stroke-width="1.5" stroke-dasharray="5 4" opacity=".7"/>` : ''}${p.trail.length > 1 && p.id === 'Satellite' ? `<path d="${path(p.trail)}" fill="none" stroke="#778fa9" stroke-width="2.3"/>` : ''}`).join('');
    svg.querySelector(`#${uid}-scan`).innerHTML = poses.filter(p => p.active).map(p => {
      const satellite = p.id === 'Satellite', [x, y] = !satellite && p.phase === 'scanning' ? detailFromFarm(p.position) : pixel(p.position);
      return satellite ? `<rect x="${x - 25}" y="${map.y - 20}" width="50" height="${map.height + 40}" fill="#95b9ca" fill-opacity=".12" stroke="#8bafbf" stroke-opacity=".35"/>` : `<circle cx="${x}" cy="${y}" r="18" fill="#66aaa0" fill-opacity=".15" stroke="#67a69d" stroke-opacity=".4"/>`;
    }).join('');
    for (const pose of poses) {
      const el = svg.querySelector(`[data-pick="${pose.id}"]`), [x, y] = pose.id === 'Drone' && pose.active && pose.phase === 'scanning' ? detailFromFarm(pose.position) : pixel(pose.position);
      el.setAttribute('transform', `translate(${x},${y})`);
      el.querySelector('circle').setAttribute('stroke', state.equipmentFocus === pose.id || pose.active ? '#67978e' : '#c2cdcc');
      el.querySelector('circle').setAttribute('stroke-width', state.equipmentFocus === pose.id || pose.active ? '2.5' : '1');
    }
  }
  function pick(event) {
    if (event.type === 'keydown' && !['Enter', ' '].includes(event.key)) return;
    const target = event.target.closest('[data-pick]');
    if (!target) return;
    if (event.type === 'keydown') event.preventDefault();
    const id = target.dataset.pick;
    onPick(id === 'farm' ? { type: 'farm' } : { type: 'device', id });
  }
  svg.addEventListener('click', pick); svg.addEventListener('keydown', pick);
  update(state);
  return { update, resetView() {}, destroy() { svg.removeEventListener('click', pick); svg.removeEventListener('keydown', pick); svg.remove(); } };
}

function create3D(host, initial, onPick) {
  let state = initial, disposed = false, pointer = null;
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false }); }
  catch (_) {
    const fallback = create2D(host, { ...initial, dimension: '2d' }, onPick);
    return fallback;
  }
  const geometries = new Set(), materials = new Set(), textures = new Set(), instances = new Set();
  const geometry = value => { geometries.add(value); return value; };
  const material = (color, extra = {}) => { const value = new THREE.MeshStandardMaterial({ color, roughness: .86, metalness: .02, ...extra }); materials.add(value); return value; };
  const lineMaterial = (color, extra = {}) => { const value = new THREE.LineBasicMaterial({ color, ...extra }); materials.add(value); return value; };
  const data = state.data, layout = hitSceneLayout(data), displayScale = .34;
  const width = layout.farm.width * displayScale, height = layout.farm.height * displayScale, unit = 1100 * displayScale;
  const projected = (p, rect, altitude = .3) => { const [x, y] = inRect(p, rect); return new THREE.Vector3((x - 550) * displayScale, altitude, (y - 300) * displayScale); };
  const world = (p, altitude = .3) => projected(p, layout.farm, altitude);
  const detailWorld = (p, altitude = .3) => projected(p, layout.inset, altitude);
  const detailFromFarm = (p, altitude = .3) => detailWorld(roiLocal(p, layout.roiBounds), altitude);
  const scene = new THREE.Scene(); scene.background = new THREE.Color('#f1f3ed');
  const camera = new THREE.OrthographicCamera(-unit, unit, unit * .6, -unit * .6, .1, 2200);
  let azimuth = .12, elevation = .91, zoom = 1.22;
  const target = new THREE.Vector3(0, 5, 0);
  const canvas = renderer.domElement;
  canvas.tabIndex = 0; canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', `HIT farm plot in 3D. Drag to orbit, scroll to zoom, and select the satellite or drone. ${HIT_MOTION_NOTE}`);
  Object.assign(canvas.style, { display: 'block', width: '100%', height: '100%', touchAction: 'none', outlineOffset: '-3px' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, state.miniature ? 1.3 : 1.7));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.1;
  host.appendChild(canvas);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x9caa8b, 2.1));
  const sun = new THREE.DirectionalLight(0xfff5df, 2.2); sun.position.set(-120, 210, 100); scene.add(sun);
  const ground = new THREE.Mesh(geometry(new THREE.PlaneGeometry(unit * 5, unit * 5)), material('#e9ede3'));
  ground.rotation.x = -Math.PI / 2; ground.position.y = -4.6; scene.add(ground);
  const grid = new THREE.GridHelper(unit * 5, 125, '#cfd8ca', '#dce3d5'); grid.position.y = -4.5; scene.add(grid);
  geometries.add(grid.geometry); (Array.isArray(grid.material) ? grid.material : [grid.material]).forEach(m => materials.add(m));
  const pickable = [];

  function shapeGeometry(rows, rect = layout.farm) {
    const shape = new THREE.Shape();
    rows.forEach((p, i) => { const value = projected(p, rect, 0), x = value.x, y = -value.z; if (i) shape.lineTo(x, y); else shape.moveTo(x, y); });
    shape.closePath();
    const geo = geometry(new THREE.ShapeGeometry(shape));
    const positions = geo.attributes.position, uvs = geo.attributes.uv;
    for (let i = 0; i < positions.count; i++) uvs.setXY(i, (positions.getX(i) / displayScale + 550 - rect.x) / rect.width, 1 - (-positions.getY(i) / displayScale + 300 - rect.y) / rect.height);
    return geo;
  }
  function line(rows, color, altitude = .8, closed = false, opacity = 1) {
    const values = rows.map(p => world(p, altitude));
    if (closed && values.length) values.push(values[0]);
    const geo = geometry(new THREE.BufferGeometry().setFromPoints(values));
    const object = new THREE.Line(geo, lineMaterial(color, { transparent: opacity < 1, opacity })); scene.add(object); return object;
  }
  const boundary = outline(data), roi = roiOutline(data);
  const farmShape = shapeGeometry(boundary);
  const farm = new THREE.Mesh(farmShape, material('#a7b18b', { side: THREE.DoubleSide }));
  farm.rotation.x = -Math.PI / 2; farm.position.y = 0; farm.userData.pick = { type: 'farm' }; pickable.push(farm); scene.add(farm);
  function skirt(rows, projector, parent = scene) {
    const values = [];
    for (let i = 0; i < rows.length; i++) {
      const a = projector(rows[i], .05), b = projector(rows[(i + 1) % rows.length], .05);
      values.push(a.x, a.y, a.z, b.x, b.y, b.z, a.x, -3.7, a.z, b.x, b.y, b.z, b.x, -3.7, b.z, a.x, -3.7, a.z);
    }
    const geo = geometry(new THREE.BufferGeometry()); geo.setAttribute('position', new THREE.Float32BufferAttribute(values, 3)); geo.computeVertexNormals();
    parent.add(new THREE.Mesh(geo, material('#b9b19b', { side: THREE.DoubleSide })));
  }
  skirt(boundary, world);
  line(boundary, '#647e67', .65, true); const roiLine = line(roi, '#3f8784', 1.1, true);
  const vegetation = new THREE.Group(); scene.add(vegetation);
  const dummy = new THREE.Object3D(), color = new THREE.Color();
  const otherVegetation = (data.surfaceHints?.surfaceSamples || []).filter(p => p.kind === 'vegetation' && (!p.classId || p.classId === 4) && !builtSurfaceAt(data, p)).map(p => ({ ...p, cropId: 'other' }));
  const samples = [...samplesOf(data), ...otherVegetation].slice(0, 3600);
  for (const id of ['rice', 'maize', 'soybean', 'other']) {
    const rows = samples.filter(p => cropId(data, p) === id);
    if (!rows.length) continue;
    const green = cropColor(data, id);
    const mat = material(green);
    const cropHeight = id === 'maize' ? 2.4 : id === 'rice' ? 1.7 : id === 'soybean' ? 1.4 : .9;
    const shape = id === 'soybean' || id === 'other' ? geometry(new THREE.IcosahedronGeometry(id === 'soybean' ? 1.1 : .9, 0)) : geometry(new THREE.ConeGeometry(id === 'rice' ? .85 : .72, cropHeight, id === 'rice' ? 5 : 4));
    const plants = new THREE.InstancedMesh(shape, mat, rows.length); vegetation.add(plants); instances.add(plants);
    const stems = id === 'rice' || id === 'maize' ? new THREE.InstancedMesh(geometry(new THREE.CylinderGeometry(.1, .14, cropHeight, 4)), material(id === 'maize' ? '#8e8a54' : '#82976a'), rows.length) : null;
    if (stems) { vegetation.add(stems); instances.add(stems); }
    rows.forEach((sample, index) => {
      const variation = .84 + ((index * 37) % 19) / 65;
      const p = world([sample.x, sample.y], cropHeight * .48);
      dummy.position.copy(p); dummy.rotation.set(0, index * 2.39996, id === 'rice' ? .1 : 0); dummy.scale.setScalar(variation); dummy.updateMatrix(); plants.setMatrixAt(index, dummy.matrix);
      color.set(green).multiplyScalar(.85 + (index % 7) * .035); plants.setColorAt(index, color);
      if (stems) { dummy.scale.set(.75, variation, .75); dummy.updateMatrix(); stems.setMatrixAt(index, dummy.matrix); }
    });
    plants.instanceMatrix.needsUpdate = true;
    if (plants.instanceColor) plants.instanceColor.needsUpdate = true;
  }

  const loader = new THREE.TextureLoader();
  function textureMesh(asset, geo = farmShape, altitude = .5, opacity = 1, parent = scene) {
    if (!asset) return null;
    const mat = material('#ffffff', { transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -1 });
    const mesh = new THREE.Mesh(geo, mat); mesh.rotation.x = -Math.PI / 2; mesh.position.y = altitude; parent.add(mesh);
    const texture = loader.load(assetUrl(asset), () => { if (!disposed) render(); });
    texture.colorSpace = THREE.SRGBColorSpace; texture.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy()); textures.add(texture); mat.map = texture;
    return mesh;
  }
  const assets = data.assets || {};
  const rgb = textureMesh(assets.satelliteRgb, farmShape, .35);
  const classification = textureMesh(assets.satelliteMask, farmShape, .6, .6);
  const droneMask = textureMesh(assets.droneMask, farmShape, 1.05, .82);
  const roiGeo = shapeGeometry(roi);
  const [roiLeft, roiTop, roiRight, roiBottom] = data.roi?.bounds || hitBounds(roi);
  const roiUv = roiGeo.attributes.uv;
  for (let i = 0; i < roiUv.count; i++) roiUv.setXY(i, (roiUv.getX(i) - roiLeft) / (roiRight - roiLeft), (roiUv.getY(i) - (1 - roiBottom)) / (roiBottom - roiTop));
  const ortho = textureMesh(assets.orthomosaic, roiGeo, .8);

  function box(group, dimensions, position, mat) {
    const item = new THREE.Mesh(geometry(new THREE.BoxGeometry(...dimensions)), mat); item.position.set(...position); group.add(item); return item;
  }
  const structures = new THREE.Group(); scene.add(structures);
  const roadMaterial = material('#a9ada6'), buildingMaterial = material('#a6b3af'), roofMaterial = material('#7b8c8a');
  function instanceBoxes(parent, rows, mat) {
    if (!rows.length) return;
    const mesh = new THREE.InstancedMesh(geometry(new THREE.BoxGeometry(1, 1, 1)), mat, rows.length); instances.add(mesh); parent.add(mesh);
    rows.forEach((row, index) => { dummy.position.set(...row.position); dummy.rotation.set(0, 0, 0); dummy.scale.set(...row.size); dummy.updateMatrix(); mesh.setMatrixAt(index, dummy.matrix); });
    mesh.instanceMatrix.needsUpdate = true;
  }
  const roadBoxes = [], buildingBoxes = [], roofBoxes = [];
  for (const road of data.surfaceHints?.roads || []) {
    const p = world([road.x, road.y], .13);
    roadBoxes.push({ size: [Math.max(.25, road.width * width), .24, Math.max(.25, road.height * height)], position: [p.x, p.y, p.z] });
  }
  for (const building of data.surfaceHints?.buildings || []) {
    const h = Math.max(1.5, Math.min(4.3, (building.height_m || 6) * .38));
    const p = world([building.x, building.y], h / 2 + .2);
    const w = Math.max(.6, building.width * width), d = Math.max(.6, building.height * height);
    buildingBoxes.push({ size: [w, h, d], position: [p.x, p.y, p.z] });
    roofBoxes.push({ size: [w + .12, .18, d + .12], position: [p.x, h + .3, p.z] });
  }
  instanceBoxes(structures, roadBoxes, roadMaterial); instanceBoxes(structures, buildingBoxes, buildingMaterial); instanceBoxes(structures, roofBoxes, roofMaterial);

  const detail = new THREE.Group(), detailNatural = new THREE.Group(); detail.add(detailNatural); scene.add(detail);
  const detailBoundary = [[0, 0], [1, 0], [1, 1], [0, 1]], detailShape = shapeGeometry(detailBoundary, layout.inset);
  const detailPlate = new THREE.Mesh(detailShape, material('#d6dcc9', { side: THREE.DoubleSide })); detailPlate.rotation.x = -Math.PI / 2; detailPlate.position.y = .1; detailPlate.userData.pick = { type: 'farm' }; detail.add(detailPlate); pickable.push(detailPlate);
  skirt(detailBoundary, detailWorld, detail);
  for (const [index, polygon] of DRONE_FIELDS.entries()) {
    const surface = new THREE.Mesh(shapeGeometry(polygon, layout.inset), material(index ? '#a2b589' : '#afbe95', { side: THREE.DoubleSide })); surface.rotation.x = -Math.PI / 2; surface.position.y = .3; detailNatural.add(surface);
  }
  const detailSamples = droneCropSamples();
  const detailPlants = new THREE.InstancedMesh(geometry(new THREE.ConeGeometry(.37, 1.35, 5)), material('#7d9863'), detailSamples.length); detailNatural.add(detailPlants); instances.add(detailPlants);
  detailSamples.forEach((sample, index) => { dummy.position.copy(detailWorld([sample.x, sample.y], 1.0)); dummy.rotation.set(.04, index * 1.8, .06); dummy.scale.setScalar(.88 + (index % 7) * .035); dummy.updateMatrix(); detailPlants.setMatrixAt(index, dummy.matrix); });
  detailPlants.instanceMatrix.needsUpdate = true;
  for (const road of DRONE_ROADS) for (let i = 1; i < road.points.length; i++) {
    const a = detailWorld(road.points[i - 1], .5), b = detailWorld(road.points[i], .5), dx = b.x - a.x, dz = b.z - a.z;
    const strip = box(detailNatural, [Math.hypot(dx, dz), .3, road.width * layout.inset.width * displayScale], [(a.x + b.x) / 2, .5, (a.z + b.z) / 2], material('#a8a998'));
    strip.rotation.y = -Math.atan2(dz, dx);
  }
  for (const strip of DRONE_TREE_STRIPS) {
    const surface = new THREE.Mesh(shapeGeometry(strip, layout.inset), material('#78936c', { side: THREE.DoubleSide })); surface.rotation.x = -Math.PI / 2; surface.position.y = .5; detailNatural.add(surface);
    for (let i = 0; i < strip.length - 1; i++) for (let n = 0; n < 4; n++) {
      const t = n / 4, p = [strip[i][0] + (strip[i + 1][0] - strip[i][0]) * t, strip[i][1] + (strip[i + 1][1] - strip[i][1]) * t];
      const tree = new THREE.Mesh(geometry(new THREE.IcosahedronGeometry(1.2 + (n % 2) * .3, 0)), material(n % 2 ? '#6e8b5f' : '#839c6f')); tree.position.copy(detailWorld(p, 1.35)); detailNatural.add(tree);
    }
  }
  const detailOrtho = textureMesh(assets.orthomosaic, detailShape, .75, 1, detail);
  const detailMaskShape = shapeGeometry(detailBoundary, layout.inset), detailMaskUv = detailMaskShape.attributes.uv;
  for (let i = 0; i < detailMaskUv.count; i++) detailMaskUv.setXY(i, roiLeft + detailMaskUv.getX(i) * (roiRight - roiLeft), 1 - roiBottom + detailMaskUv.getY(i) * (roiBottom - roiTop));
  const detailMask = textureMesh(assets.droneMask, detailMaskShape, 1.02, .8, detail);
  const connectorMaterial = new THREE.LineDashedMaterial({ color: '#6b9b88', dashSize: 2.2, gapSize: 1.7, transparent: true, opacity: .8 }); materials.add(connectorMaterial);
  for (const [source, destination] of [[[1, 0], [roiLeft, roiTop]], [[1, 1], [roiLeft, roiBottom]]]) {
    const connector = new THREE.Line(geometry(new THREE.BufferGeometry().setFromPoints([detailWorld(source, .9), world(destination, 1.1)])), connectorMaterial); connector.computeLineDistances(); detail.add(connector);
  }
  function label(text, location, parent = scene, size = 70) {
    const labelCanvas = document.createElement('canvas'); labelCanvas.width = 1024; labelCanvas.height = 140;
    const context = labelCanvas.getContext('2d'); context.font = '500 52px Arial,sans-serif'; context.textAlign = 'center'; context.fillStyle = '#647b6b'; context.fillText(text, 512, 90);
    const texture = new THREE.CanvasTexture(labelCanvas); texture.colorSpace = THREE.SRGBColorSpace; textures.add(texture);
    const mat = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }); materials.add(mat);
    const sprite = new THREE.Sprite(mat); sprite.position.copy(location); sprite.scale.set(size, size * 140 / 1024, 1); parent.add(sprite);
  }
  label('Drone detail · same farm, enlarged', detailWorld([.5, -.13], 4), detail, 99);
  label('Whole farm · satellite context', world([.5, -.13], 4), scene, 110);
  function makeDevice(id) {
    const group = new THREE.Group(), body = material('#a4bab6'), dark = material('#3e5b67'), panel = material('#466c8d');
    if (id === 'Satellite') {
      box(group, [5.5, 4, 4.5], [0, 0, 0], body);
      box(group, [9.5, .35, 7], [-9, 0, 0], panel); box(group, [9.5, .35, 7], [9, 0, 0], panel);
      box(group, [5, .6, .6], [-4, 0, 0], dark); box(group, [5, .6, .6], [4, 0, 0], dark);
      for (const x of [-12, -9, -6, 6, 9, 12]) box(group, [.12, .5, 7], [x, .1, 0], body);
      const lens = new THREE.Mesh(geometry(new THREE.CylinderGeometry(1.1, 1.5, 2.7, 10)), dark); lens.position.y = -2.2; group.add(lens);
    } else {
      box(group, [4.5, 1.8, 3], [0, 0, 0], body);
      for (const [x, z] of [[-4, -3.5], [4, -3.5], [-4, 3.5], [4, 3.5]]) {
        const arm = box(group, [Math.hypot(x, z), .45, .55], [x / 2, 0, z / 2], dark); arm.rotation.y = -Math.atan2(z, x);
        const prop = new THREE.Mesh(geometry(new THREE.CylinderGeometry(2.1, 2.1, .16, 16)), material('#4c6d73', { transparent: true, opacity: .92 })); prop.position.set(x, .6, z); group.add(prop);
      }
      box(group, [1.8, 1.2, 1.4], [0, -1.2, .5], dark);
    }
    const ring = new THREE.Mesh(geometry(new THREE.RingGeometry(id === 'Satellite' ? 15 : 10, id === 'Satellite' ? 15.9 : 10.9, 48)), material('#4c7870', { side: THREE.DoubleSide, transparent: true, opacity: .8 }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = -3.2; group.add(ring);
    group.traverse(object => { if (object.isMesh) { object.userData.pick = { type: 'device', id }; pickable.push(object); } }); scene.add(group);
    const home = world(HIT_HOMES[id], .7);
    const pad = new THREE.Mesh(geometry(new THREE.CircleGeometry(id === 'Satellite' ? 17 : 12, 40)), material('#f9fbf5', { side: THREE.DoubleSide })); pad.rotation.x = -Math.PI / 2; pad.position.copy(home); scene.add(pad);
    const padBorder = new THREE.Mesh(geometry(new THREE.RingGeometry(id === 'Satellite' ? 16.2 : 11.2, id === 'Satellite' ? 17.1 : 12.1, 48)), material('#78988e', { side: THREE.DoubleSide })); padBorder.rotation.x = -Math.PI / 2; padBorder.position.copy(home); padBorder.position.y += .05; scene.add(padBorder);
    const guide = line([HIT_HOMES[id], HIT_HOMES[id]], '#afbfbc', .9);
    const beamGeo = geometry(new THREE.BufferGeometry()); beamGeo.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(18), 3));
    const beam = new THREE.Mesh(beamGeo, material(id === 'Satellite' ? '#a0c0d3' : '#78b4ab', { transparent: true, opacity: .11, side: THREE.DoubleSide, depthWrite: false })); scene.add(beam);
    const route = line([], id === 'Satellite' ? '#8b9fb5' : '#4e938c', id === 'Satellite' ? .9 : 1.2, false, .55);
    const trail = line([], id === 'Satellite' ? '#8096ad' : '#4c918c', 1, false, .9);
    const detailRoute = id === 'Drone' ? line([], '#4e938c', 1.2, false, .6) : null;
    if (detailRoute) detail.add(detailRoute);
    for (const path of [route, detailRoute].filter(Boolean)) {
      const previousMaterial = path.material;
      materials.delete(previousMaterial); previousMaterial.dispose();
      path.material = new THREE.LineDashedMaterial({ color: id === 'Satellite' ? '#4d7187' : '#367e70', dashSize: 2.2, gapSize: 1.35, transparent: true, opacity: .94, depthTest: false, depthWrite: false });
      materials.add(path.material); path.renderOrder = 30;
    }
    return { group, ring, route, detailRoute, trail, guide, beam };
  }
  const devices = { Satellite: makeDevice('Satellite'), Drone: makeDevice('Drone') };

  function replaceLine(object, points) {
    const previous = object.geometry;
    object.geometry = geometry(new THREE.BufferGeometry().setFromPoints(points));
    geometries.delete(previous); previous.dispose();
    if (object.material.isLineDashedMaterial) object.computeLineDistances();
  }
  function positionCamera() {
    const distance = unit * 2.1;
    camera.position.set(target.x + Math.sin(azimuth) * Math.cos(elevation) * distance, target.y + Math.sin(elevation) * distance, target.z + Math.cos(azimuth) * Math.cos(elevation) * distance);
    camera.lookAt(target); camera.zoom = zoom; camera.updateProjectionMatrix();
  }
  function render() { if (!disposed) renderer.render(scene, camera); }
  function resize() {
    if (disposed) return;
    const rect = host.getBoundingClientRect(), w = Math.max(1, rect.width), h = Math.max(150, rect.height), aspect = w / h;
    renderer.setSize(w, h, false);
    const vertical = Math.max(112, 205 / aspect);
    camera.left = -vertical * aspect; camera.right = vertical * aspect; camera.top = vertical; camera.bottom = -vertical;
    positionCamera(); render();
  }
  function update(next) {
    const previousFocus = state.equipmentFocus;
    state = next;
    vegetation.visible = state.layer === 'natural';
    if (rgb) rgb.visible = state.layer !== 'natural';
    if (classification) classification.visible = state.layer === 'satellite' && state.step >= 3;
    if (ortho) ortho.visible = state.layer === 'drone' && state.step >= 6;
    if (droneMask) droneMask.visible = state.layer === 'drone' && state.step >= 7;
    roiLine.visible = state.step >= 4;
    detail.visible = state.step >= 4;
    detailNatural.visible = state.layer !== 'drone' || state.step < 6;
    if (detailOrtho) detailOrtho.visible = state.layer === 'drone' && state.step >= 6;
    if (detailMask) detailMask.visible = state.layer === 'drone' && state.step >= 7;
    const poses = getHitMotion(data, state.step, state.progress);
    for (const pose of poses) {
      const entry = devices[pose.id], altitude = pose.altitude + (pose.id === 'Drone' ? 2.2 : 0);
      const inDetail = pose.id === 'Drone' && pose.active && pose.phase === 'scanning' && state.step >= 4;
      const projector = inDetail ? detailFromFarm : world;
      entry.group.position.copy(projector(pose.position, altitude)); entry.group.rotation.y = -pose.heading;
      entry.ring.material.opacity = state.equipmentFocus === pose.id || pose.active ? .98 : .72;
      entry.route.visible = pose.shown && Number(state.step) === pose.missionStep;
      replaceLine(entry.route, pose.route.map(p => world(p, 3.6)));
      if (entry.detailRoute) {
        entry.detailRoute.visible = state.step === 5;
        replaceLine(entry.detailRoute, pose.route.map(p => detailFromFarm(p, 3.2)));
      }
      entry.trail.visible = pose.active && pose.trail.length > 1;
      const trail = inDetail ? pose.trail.filter(p => { const local = roiLocal(p, layout.roiBounds); return local[0] >= -.15 && local[0] <= 1.15 && local[1] >= -.15 && local[1] <= 1.15; }) : pose.trail;
      replaceLine(entry.trail, trail.map(p => projector(p, altitude)));
      entry.guide.visible = pose.active;
      replaceLine(entry.guide, [projector(pose.position, .9), projector(pose.position, altitude - 2)]);
      entry.beam.visible = pose.active;
      if (pose.active) {
        const center = projector(pose.position, altitude - 2);
        const reachX = pose.id === 'Satellite' ? 15 : 7, reachZ = pose.id === 'Satellite' ? height * .56 : 7;
        const ground = projector(pose.position, 1.2), values = entry.beam.geometry.attributes.position;
        [[center.x, center.y, center.z], [ground.x - reachX, ground.y, ground.z - reachZ], [ground.x + reachX, ground.y, ground.z + reachZ], [center.x, center.y, center.z], [ground.x + reachX, ground.y, ground.z - reachZ], [ground.x - reachX, ground.y, ground.z + reachZ]].forEach((p, i) => values.setXYZ(i, ...p));
        values.needsUpdate = true; entry.beam.geometry.computeBoundingSphere();
      }
    }
    if (state.equipmentFocus && (state.miniature || state.equipmentFocus !== previousFocus)) {
      target.copy(devices[state.equipmentFocus]?.group.position || new THREE.Vector3()); zoom = state.miniature ? 2.6 : 1.45; positionCamera();
    }
    render();
  }
  function resetView() { azimuth = .12; elevation = .91; zoom = 1.22; target.set(0, 5, 0); positionCamera(); render(); }
  const raycaster = new THREE.Raycaster(), mouse = new THREE.Vector2();
  function down(event) {
    if (event.button !== 0) return;
    pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, moved: false };
    canvas.setPointerCapture(event.pointerId);
  }
  function move(event) {
    if (!pointer || event.pointerId !== pointer.id) return;
    const dx = event.clientX - pointer.x, dy = event.clientY - pointer.y;
    if (Math.abs(dx) + Math.abs(dy) > 2) pointer.moved = true;
    azimuth -= dx * .006; elevation = Math.max(.22, Math.min(1.5, elevation + dy * .005));
    pointer.x = event.clientX; pointer.y = event.clientY; positionCamera(); render();
  }
  function up(event) {
    if (!pointer || event.pointerId !== pointer.id) return;
    const click = !pointer.moved;
    pointer = null;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    if (!click) return;
    const rect = canvas.getBoundingClientRect();
    mouse.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
    raycaster.setFromCamera(mouse, camera);
    const hit = raycaster.intersectObjects(pickable, false).find(item => item.object.visible && item.object.parent?.visible);
    if (hit?.object.userData.pick) onPick(hit.object.userData.pick);
  }
  function cancel() { pointer = null; }
  function wheel(event) { event.preventDefault(); zoom = Math.max(.6, Math.min(5, zoom * Math.exp(-event.deltaY * .001))); positionCamera(); render(); }
  function key(event) {
    if (event.key === 'Home' || event.key.toLowerCase() === 'r') { event.preventDefault(); resetView(); }
    else if (['+', '=', '-'].includes(event.key)) { event.preventDefault(); zoom = Math.max(.6, Math.min(5, zoom * (event.key === '-' ? .85 : 1.15))); positionCamera(); render(); }
    else if (event.key.startsWith('Arrow')) { event.preventDefault(); if (event.key === 'ArrowLeft') azimuth += .1; if (event.key === 'ArrowRight') azimuth -= .1; if (event.key === 'ArrowUp') elevation = Math.min(1.5, elevation + .1); if (event.key === 'ArrowDown') elevation = Math.max(.22, elevation - .1); positionCamera(); render(); }
  }
  function lost(event) { event.preventDefault(); canvas.setAttribute('aria-label', '3D graphics interrupted. Switch to the 2D overview.'); }
  function restored() { update(state); resize(); }
  canvas.addEventListener('pointerdown', down); canvas.addEventListener('pointermove', move); canvas.addEventListener('pointerup', up); canvas.addEventListener('pointercancel', cancel);
  canvas.addEventListener('wheel', wheel, { passive: false }); canvas.addEventListener('keydown', key); canvas.addEventListener('webglcontextlost', lost); canvas.addEventListener('webglcontextrestored', restored);
  const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null; observer?.observe(host); window.addEventListener('resize', resize);
  resize(); update(state);
  return {
    update, resetView,
    destroy() {
      if (disposed) return; disposed = true; observer?.disconnect(); window.removeEventListener('resize', resize);
      canvas.removeEventListener('pointerdown', down); canvas.removeEventListener('pointermove', move); canvas.removeEventListener('pointerup', up); canvas.removeEventListener('pointercancel', cancel);
      canvas.removeEventListener('wheel', wheel); canvas.removeEventListener('keydown', key); canvas.removeEventListener('webglcontextlost', lost); canvas.removeEventListener('webglcontextrestored', restored);
      instances.forEach(value => value.dispose()); textures.forEach(value => value.dispose()); materials.forEach(value => value.dispose()); geometries.forEach(value => value.dispose());
      renderer.dispose(); renderer.forceContextLoss(); canvas.remove();
    },
  };
}
