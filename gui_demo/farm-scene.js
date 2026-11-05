import * as THREE from './vendor/three.module.js';

/**
 * A read-only view of recorded simulation state. Field dimensions are supplied
 * by the caller; repeated plants and event-driven equipment poses are schematic.
 * This module neither advances the simulation nor invents observation coverage.
 */
export function createFarmScene(container, options = {}, onPick = () => {}) {
  let state = { farmId: 'soybean_field', colors: null, ...options };
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  } catch (_) {
    const fallback = document.createElement('div');
    fallback.setAttribute('role', 'status');
    fallback.textContent = '3D view unavailable. Use the 2D farm plot overview.';
    Object.assign(fallback.style, { display: 'grid', placeItems: 'center', minHeight: '160px', height: '100%', color: '#666', padding: '24px', textAlign: 'center', font: '13px system-ui' });
    container.appendChild(fallback);
    return { update() {}, setDevicePoses() {}, resetView() {}, destroy() { fallback.remove(); } };
  }

  let disposed = false, request = 0, modelKey = '', model = null, focusKey = '';
  let cameraBounds = null, cameraDeviceId = null;
  let azimuth = .67, elevation = .72, zoom = 1, pointer = null;
  const canvas = renderer.domElement;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, state.miniature ? 1.25 : 1.65));
  renderer.setClearColor(0xf5f5f4, 1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = .96;
  renderer.shadowMap.enabled = !state.miniature;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  Object.assign(canvas.style, { width: '100%', height: '100%', display: 'block', touchAction: 'none', cursor: 'grab', outlineOffset: '-3px' });
  canvas.tabIndex = 0;
  canvas.setAttribute('role', 'img');
  container.appendChild(canvas);

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-180, 180, 100, -100, .1, 1800);
  const target = new THREE.Vector3(0, 1, 0);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x827968, 1.55));
  const sun = new THREE.DirectionalLight(0xfffaf0, 2.0);
  sun.position.set(-110, 220, 110);
  sun.castShadow = !state.miniature;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -190, right: 190, top: 150, bottom: -150, near: 1, far: 600 });
  sun.shadow.normalBias = .18;
  sun.shadow.bias = -.0002;
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0xf0f3f5, .32);
  fill.position.set(80, 50, -120);
  scene.add(fill);

  const dummy = new THREE.Object3D(), scratchColor = new THREE.Color();
  const raycaster = new THREE.Raycaster(), mouse = new THREE.Vector2();

  function farmConfig() {
    const farm = state.farm || {};
    const maize = (farm.crop_id || farm.crop_type || state.farmId).toLowerCase().includes('maize');
    return {
      maize,
      count: Math.max(1, Math.min(512, Number(farm.num_ridges) || 64)),
      length: Math.max(1, Number(farm.field_length_m) || 268),
      spacing: Math.max(.1, Number(farm.ridge_width_m) || (maize ? .65 : 1.1)),
      lines: Math.max(1, Math.min(3, Number(farm.rows_per_ridge) || (maize ? 1 : 2))),
      label: farm.label || (maize ? 'farm plot B' : 'farm plot A'),
    };
  }

  function releaseModel() {
    if (!model) return;
    scene.remove(model.root);
    for (const object of model.instances) object.dispose();
    for (const geometry of model.geometries) geometry.dispose();
    for (const material of model.materials) material.dispose();
    model = null;
  }

  function buildModel(config) {
    releaseModel();
    const root = new THREE.Group();
    scene.add(root);
    const materials = new Set(), geometries = new Set(), instances = [], pickables = [], devices = [];
    const width = config.count * config.spacing, length = config.length;
    const material = (color, extra = {}) => {
      const result = new THREE.MeshStandardMaterial({ color, roughness: .88, ...extra });
      materials.add(result); return result;
    };
    const geometry = value => { geometries.add(value); return value; };
    const cube = geometry(new THREE.BoxGeometry(1, 1, 1));
    const sphere = geometry(new THREE.SphereGeometry(1, 8, 5));
    const cylinder = geometry(new THREE.CylinderGeometry(1, 1, 1, 12));
    const soil = material(0x826649), cutEarth = material(0x9b8569), dirtEdge = material(0xad997f);
    const road = material(0xbfbdb6), metal = material(0xaeb6b7, { metalness: .28, roughness: .5 });
    const black = material(0x292d2b), green = material(0x49703d), white = material(0xe7e6df);
    const glass = material(0x607679, { metalness: .2, roughness: .3 });
    const shadow = new THREE.ShadowMaterial({ opacity: .12 }); materials.add(shadow);

    function mesh(shape, surface, position, scale = [1, 1, 1], parent = root) {
      const result = new THREE.Mesh(shape, surface);
      result.position.set(...position); result.scale.set(...scale);
      result.castShadow = true; result.receiveShadow = true;
      parent.add(result); return result;
    }
    const box = (position, scale, surface, parent) => mesh(cube, surface, position, scale, parent);
    const tube = (position, scale, surface, parent, rotation) => {
      const result = mesh(cylinder, surface, position, scale, parent);
      if (rotation) result.rotation.set(...rotation);
      return result;
    };
    const register = (object, selection) => { object.userData.pick = selection; pickables.push(object); };
    function instanced(shape, surface, count, mapping) {
      const result = new THREE.InstancedMesh(shape, surface, count);
      result.castShadow = true; result.receiveShadow = true;
      result.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      root.add(result); instances.push(result);
      register(result, { type: 'ridge', mapping });
      return result;
    }

    box([0, -3.1, 0], [length + 24, 6, width + 28], cutEarth);
    box([0, -.3, 0], [length + 24, .6, width + 28], dirtEdge);
    box([0, .08, width / 2 + 8], [length + 22, .25, 10], road);
    box([-length / 2 - 7, .09, 0], [6, .26, width + 26], road);
    const field = box([0, .18, 0], [length, .35, width], soil);
    register(field, { type: 'ridge', surface: true });
    const ground = mesh(geometry(new THREE.PlaneGeometry(length * 4, length * 4)), shadow, [0, -6.15, 0]);
    ground.rotation.x = -Math.PI / 2; ground.castShadow = false;

    const rowShape = geometry(new THREE.BoxGeometry(length, .24, config.spacing * .84));
    const rows = instanced(rowShape, material(0xffffff), config.count, 'row');
    rows.castShadow = false;
    for (let rid = 0; rid < config.count; rid++) {
      dummy.position.set(0, .47, -width / 2 + (rid + .5) * config.spacing);
      dummy.rotation.set(0, 0, 0); dummy.scale.set(1, 1, 1); dummy.updateMatrix();
      rows.setMatrixAt(rid, dummy.matrix);
    }

    const plants = [], perLine = state.miniature ? 14 : 24;
    for (let rid = 0; rid < config.count; rid++) {
      for (let line = 0; line < config.lines; line++) {
        for (let index = 0; index < perLine; index++) {
          const jitter = .22 * Math.sin(rid * 2.39996 + line * 1.7) + .10 * Math.sin(index * 2.1 + rid * .83);
          plants.push({ rid, x: -length / 2 + (index + .5 + (line ? .12 : 0) + jitter) * length / perLine,
            z: -width / 2 + (rid + .5) * config.spacing + (line - (config.lines - 1) / 2) * config.spacing * .42,
            variation: Math.sin(rid * 12.17 + index * 7.31 + line * 3.1) });
        }
      }
    }
    const stalkShape = geometry(new THREE.CylinderGeometry(config.maize ? .07 : .045, config.maize ? .1 : .065, 1, 5));
    const stems = instanced(stalkShape, material(0xffffff), plants.length, 'stem');
    let leafShape;
    if (config.maize) {
      // Curved lanceolate leaves, visibly different from soybean leaflets.
      const verts = [], uv = [], indices = [], segments = 8;
      for (let i = 0; i <= segments; i++) {
        const t = i / segments, breadth = .38 * Math.sin(Math.PI * t) + .012;
        const y = .95 * Math.sin(t * Math.PI * .85) - .55 * t * t;
        verts.push(t * 2.6, y, -breadth, t * 2.6, y, breadth);
        uv.push(t, 0, t, 1);
        if (i < segments) { const n = i * 2; indices.push(n, n + 1, n + 2, n + 1, n + 3, n + 2); }
      }
      leafShape = new THREE.BufferGeometry();
      leafShape.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
      leafShape.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
      leafShape.setIndex(indices); leafShape.computeVertexNormals(); geometry(leafShape);
    } else {
      leafShape = geometry(new THREE.SphereGeometry(1, 6, 4));
    }
    const leafCount = config.maize ? 6 : 9;
    const leaves = instanced(leafShape, material(0xffffff, { side: THREE.DoubleSide, roughness: .94 }), plants.length * leafCount, 'leaf');
    const crowns = config.maize ? instanced(geometry(new THREE.ConeGeometry(.16, .85, 5)), material(0xc3b580), plants.length, 'stem') : null;

    // Corner stakes and two irrigation manifolds provide scale without fake labels.
    for (const x of [-length / 2, length / 2]) for (const z of [-width / 2, width / 2]) {
      tube([x, 1.1, z], [.13, 1.8, .13], metal);
      tube([x, 2.02, z], [.25, .12, .25], white);
    }
    const pipe = tube([0, .9, width / 2 + 1], [.18, length, .18], metal, root, [0, 0, Math.PI / 2]);
    register(pipe, { type: 'device', deviceId: config.maize ? 'Maize_Irrigation' : 'Soybean_Irrigation', label: 'Fixed irrigation system' });
    for (let r = 0; r < config.count; r += 8) {
      tube([-length / 2 + 1, .77, -width / 2 + (r + .5) * config.spacing], [.07, 1.1, .07], black);
    }

    function device(id, label, position, shared = true) {
      const group = new THREE.Group(); group.position.set(...position); root.add(group);
      register(group, { type: 'device', deviceId: id, label });
      devices.push({ id, group, shared, parkingPosition: group.position.clone() }); return group;
    }
    const edgeZ = width / 2 + 8;
    const tractor = device('Tractor', 'Shared tractor', [-length * .36, .35, edgeZ]);
    box([0, 1.9, 0], [6.8, 1.8, 3.8], green, tractor);
    box([-1, 3.7, 0], [3.2, 2.4, 3.15], glass, tractor);
    box([-1, 5, 0], [3.7, .3, 3.7], white, tractor);
    box([2.1, 2.7, 0], [2.5, 1.5, 3.1], green, tractor);
    box([3.5, 2.3, 0], [.15, 1.1, 2.4], black, tractor);
    tube([1.4, 4.1, -1.1], [.15, 2, .15], black, tractor);
    for (const x of [-2.1, 2.3]) for (const z of [-1.9, 1.9]) {
      const radius = x < 0 ? 1.5 : 1.1;
      tube([x, radius, z], [radius, .85, radius], black, tractor, [Math.PI / 2, 0, 0]);
      tube([x, radius, z * 1.07], [radius * .48, .9, radius * .48], metal, tractor, [Math.PI / 2, 0, 0]);
    }
    box([-5.5, 1.2, 0], [3.4, .5, 5.2], metal, tractor);
    for (let n = 0; n < 5; n++) box([-5.6, .65, -2.1 + n * 1.05], [2.6, .2, .15], black, tractor);

    function makeDrone(id, x, scale) {
      const drone = device(id, id === 'Mavic3M' ? 'Multispectral drone' : 'Thermal drone', [x, 2.1, edgeZ]);
      drone.scale.setScalar(scale);
      box([0, .1, 0], [1.8, .9, 2], white, drone);
      box([0, -.55, .7], [.85, .6, .8], black, drone);
      for (const direction of [-1, 1]) box([0, 0, 0], [6.4, .2, .2], black, drone).rotation.y = direction * .65;
      for (const x of [-2.55, 2.55]) for (const z of [-1.85, 1.85]) {
        tube([x, .05, z], [.27, .35, .27], metal, drone);
        const rotor = box([x, .28, z], [2.5, .06, .2], black, drone); rotor.rotation.y = .2 * x;
      }
      for (const z of [-.8, .8]) { box([0, -.9, z], [2.4, .14, .14], metal, drone); box([-.6, -.5, z], [.12, .8, .12], metal, drone); }
      return drone;
    }
    makeDrone('Mavic3M', -length * .06, 1.3);
    makeDrone('Matrice4T', length * .10, 1.6);
    const robot = device('Robot0', 'Ground inspection robot', [-length * .20, .5, edgeZ]);
    box([0, 1.6, 0], [3.8, 1.1, 2], white, robot);
    box([2, 1.75, 0], [.7, .8, 1.5], black, robot);
    for (const x of [-1.25, 1.25]) for (const z of [-1.1, 1.1]) {
      const leg = box([x, .75, z], [.35, 1.5, .3], metal, robot); leg.rotation.z = x * .15;
      box([x + .12, .1, z], [.65, .2, .4], black, robot);
    }
    const sensorId = config.maize ? 'Maize_Sensor' : 'Soybean_Sensor';
    const sensor = device(sensorId, 'Fixed soil and canopy sensors', [length * .28, .1, edgeZ], false);
    box([0, .3, 0], [3, .6, 2.5], road, sensor);
    tube([0, 3.7, 0], [.15, 7, .15], metal, sensor);
    box([0, 6.8, 0], [2.2, .9, 1.4], white, sensor);
    box([1.1, 4.7, 0], [1.8, 1.9, .2], glass, sensor).rotation.x = -.3;
    tube([0, 7.9, 0], [.08, 1.4, .08], metal, sensor);
    const irrigation = device(config.maize ? 'Maize_Irrigation' : 'Soybean_Irrigation', 'Fixed irrigation station', [length * .43, .1, edgeZ], false);
    box([0, .35, 0], [9, .7, 6], road, irrigation);
    tube([1.5, 2.7, 0], [2.2, 4.8, 2.2], metal, irrigation);
    tube([1.5, 5.2, 0], [2.3, .3, 2.3], white, irrigation);
    box([-2, 1.8, 0], [2, 2.8, 2.2], white, irrigation);
    box([-2, 2.2, 1.12], [1.3, .8, .06], glass, irrigation);

    const outlineMaterial = new THREE.MeshBasicMaterial({ color: 0x242925, transparent: true, opacity: .75, depthTest: false });
    materials.add(outlineMaterial);
    const selection = new THREE.Group(); root.add(selection); selection.visible = false;
    for (const side of [-1, 1]) box([0, .82, side * config.spacing * .46], [length, .07, .1], outlineMaterial, selection);
    for (const end of [-1, 1]) box([end * length / 2, .82, 0], [.18, .07, config.spacing], outlineMaterial, selection);
    selection.renderOrder = 8;
    const rangeOutline = new THREE.Group(); root.add(rangeOutline); rangeOutline.visible = false;
    const rangeEdges = [
      box([0, .9, 0], [length, .08, .13], outlineMaterial, rangeOutline),
      box([0, .9, 0], [length, .08, .13], outlineMaterial, rangeOutline),
      box([-length / 2, .9, 0], [.18, .08, 1], outlineMaterial, rangeOutline),
      box([length / 2, .9, 0], [.18, .08, 1], outlineMaterial, rangeOutline),
    ];
    rangeOutline.renderOrder = 7;
    const focus = instanced(geometry(new THREE.BoxGeometry(1.7, .16, config.spacing * .8)), material(0x343b35), config.count, 'row');
    focus.castShadow = false;
    const ringMaterial = new THREE.MeshBasicMaterial({ color: 0x3d4741, side: THREE.DoubleSide, transparent: true, opacity: .7, depthTest: false });
    materials.add(ringMaterial);
    const activeRing = mesh(geometry(new THREE.RingGeometry(4.3, 4.55, 40)), ringMaterial, [0, .62, edgeZ]);
    activeRing.rotation.x = -Math.PI / 2; activeRing.renderOrder = 10; activeRing.visible = false;
    for (const entry of devices.filter(item => item.shared)) {
      const trailGeometry = geometry(new THREE.BufferGeometry());
      trailGeometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(512 * 3), 3).setUsage(THREE.DynamicDrawUsage));
      trailGeometry.setDrawRange(0, 0);
      const trailMaterial = new THREE.LineBasicMaterial({ color: 0x617b89, transparent: true, opacity: .65 });
      materials.add(trailMaterial);
      entry.trail = new THREE.Line(trailGeometry, trailMaterial);
      entry.trail.frustumCulled = false; entry.trail.visible = false; root.add(entry.trail);
      const altitudeGeometry = geometry(new THREE.BufferGeometry());
      altitudeGeometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3).setUsage(THREE.DynamicDrawUsage));
      entry.altitudeLine = new THREE.Line(altitudeGeometry, trailMaterial);
      entry.altitudeLine.frustumCulled = false; entry.altitudeLine.visible = false; root.add(entry.altitudeLine);
    }

    model = { root, config, width, length, materials, geometries, instances, pickables, rows, plants, stems, leaves, crowns, leafCount, devices, selection, rangeOutline, rangeEdges, focus, activeRing, edgeZ };
  }

  function ridgeAppearance(ridge, maize) {
    if (!ridge?.planted && !ridge?.harvested) return { growth: 0, stubble: false, mature: false };
    if (ridge.harvested) return { growth: maize ? .065 : .08, stubble: true, mature: true };
    const stage = String(ridge.growth_stage || '').toUpperCase();
    if (/NOT_PLANTED|PRE_EMERGENCE|SOWN|^PLANTED$|GERMINAT/.test(stage)) return { growth: 0, stubble: false, mature: false };
    let growth = .45;
    if (/^VE$|EMERGEN/.test(stage)) growth = .14;
    else if (maize && /^VT(?:_|$)/.test(stage)) growth = 1;
    else if (/^V/.test(stage)) {
      const n = Number(stage.match(/\d+/)?.[0] || 3);
      growth = Math.min(.97, maize ? .16 + n * .065 : .22 + n * .13);
    } else if (/^R|MATURE|FLOWER|FILL/.test(stage)) growth = 1;
    return { growth, stubble: false, mature: maize ? /R[56]|MATURE|MATURITY/.test(stage) : /R[78]|MATURE/.test(stage) };
  }

  function update(next = {}) {
    if (disposed) return;
    state = { ...state, ...next };
    const config = farmConfig();
    const nextKey = JSON.stringify([state.farmId, config.maize, config.count, config.length, config.spacing, config.lines, !!state.miniature]);
    if (nextKey !== modelKey) { modelKey = nextKey; focusKey = ''; cameraBounds = null; target.set(0, 1, 0); buildModel(config); resize(); }
    canvas.setAttribute('aria-label', `${config.label}, ${config.maize ? 'maize' : 'soybean'}, recorded farm plot state. Schematic plants and equipment positions. Drag to rotate, scroll to zoom, click a ridge or device.`);
    const frameFarm = state.frame?.farms?.[state.farmId];
    const sourceRidges = frameFarm?.ridges || [];
    const lookup = Array.isArray(sourceRidges) ? new Map(sourceRidges.map((ridge, i) => [Number(ridge.ridge_id ?? i), ridge])) : new Map(Object.entries(sourceRidges).map(([id, ridge]) => [Number(id), ridge]));
    const appearances = Array.from({ length: config.count }, (_, rid) => ridgeAppearance(lookup.get(rid), config.maize));
    const mask = Array.isArray(state.colors) ? state.colors : null;
    const event = eventTarget();
    const requestedRidges = Array.isArray(state.focusRidges) ? state.focusRidges : event.ridges;
    const focusSet = new Set(requestedRidges.map(Number).filter(rid => Number.isInteger(rid) && rid >= 0 && rid < config.count));
    for (let rid = 0; rid < config.count; rid++) {
      const color = mask?.[rid];
      scratchColor.set(color || (rid % 2 ? '#907451' : '#856847'));
      model.rows.setColorAt(rid, scratchColor);
      dummy.position.set(-model.length / 2 - 2, .74, -model.width / 2 + (rid + .5) * config.spacing);
      dummy.rotation.set(0, 0, 0); dummy.scale.setScalar(focusSet.has(rid) ? 1 : 0); dummy.updateMatrix();
      model.focus.setMatrixAt(rid, dummy.matrix);
    }
    model.rows.instanceColor.needsUpdate = true;
    model.focus.instanceMatrix.needsUpdate = true; model.focus.computeBoundingSphere();
    const focused = [...focusSet].sort((a, b) => a - b);
    model.rangeOutline.visible = focused.length > 0;
    if (focused.length) {
      const minZ = -model.width / 2 + focused[0] * config.spacing;
      const maxZ = -model.width / 2 + (focused.at(-1) + 1) * config.spacing;
      model.rangeEdges[0].position.z = minZ;
      model.rangeEdges[1].position.z = maxZ;
      for (const edge of model.rangeEdges.slice(2)) { edge.position.z = (minZ + maxZ) / 2; edge.scale.z = maxZ - minZ; }
      // Disjoint targets keep individual headland markers; do not imply that
      // intervening unselected ridges belong to one continuous action range.
      model.rangeOutline.visible = focused.length === focused.at(-1) - focused[0] + 1;
    }
    for (let p = 0; p < model.plants.length; p++) {
      const plant = model.plants[p], appearance = appearances[plant.rid];
      const growth = appearance.growth, mature = appearance.mature;
      const h = (config.maize ? 6.7 : 2.6) * growth * (1 + plant.variation * .08);
      const base = .6, color = mask?.[plant.rid];
      dummy.position.set(plant.x, base + h / 2, plant.z); dummy.rotation.set(0, 0, 0);
      dummy.scale.set(growth ? 1 : 0, h, growth ? 1 : 0); dummy.updateMatrix();
      model.stems.setMatrixAt(p, dummy.matrix);
      scratchColor.set(color || (mature ? '#9c8652' : config.maize ? '#6d843f' : '#647943'));
      model.stems.setColorAt(p, scratchColor);
      for (let leaf = 0; leaf < model.leafCount; leaf++) {
        const angle = leaf * 2.39996 + p * .31;
        const scale = appearance.stubble ? 0 : growth;
        if (config.maize) {
          dummy.position.set(plant.x, base + h * (.30 + leaf * .105), plant.z);
          dummy.rotation.set(0, angle, -.05 + (leaf % 2) * .1);
          dummy.scale.set(.83 * scale, .8 * scale, .62 * scale);
        } else {
          const tier = Math.floor(leaf / 3), radius = (.31 - tier * .045) * scale;
          dummy.position.set(plant.x + Math.cos(angle) * radius, base + h * (.38 + tier * .22), plant.z + Math.sin(angle) * radius);
          dummy.rotation.set(.12 * Math.cos(angle), angle, .2 * Math.sin(angle));
          dummy.scale.set(.62 * scale, .13 * scale, .29 * scale);
        }
        dummy.updateMatrix(); model.leaves.setMatrixAt(p * model.leafCount + leaf, dummy.matrix);
        scratchColor.set(color || (mature ? (config.maize ? '#9c914d' : '#aa9954') : config.maize ? '#537c34' : '#4a7d3d'));
        if (!color) scratchColor.offsetHSL(0, 0, leaf % 2 ? .025 : -.018);
        model.leaves.setColorAt(p * model.leafCount + leaf, scratchColor);
      }
      if (model.crowns) {
        const tassel = growth >= .95 && !appearance.stubble;
        dummy.position.set(plant.x, base + h + .2, plant.z); dummy.rotation.set(0, 0, 0); dummy.scale.setScalar(tassel ? 1 : 0); dummy.updateMatrix();
        model.crowns.setMatrixAt(p, dummy.matrix); scratchColor.set(color || '#b4a776'); model.crowns.setColorAt(p, scratchColor);
      }
    }
    for (const object of [model.stems, model.leaves, model.crowns].filter(Boolean)) {
      object.instanceMatrix.needsUpdate = true;
      if (object.instanceColor) object.instanceColor.needsUpdate = true;
      object.computeBoundingSphere();
    }
    const selected = Number.isInteger(state.selectedRidge) && state.selectedRidge >= 0 && state.selectedRidge < config.count;
    model.selection.visible = selected;
    if (selected) model.selection.position.z = -model.width / 2 + (state.selectedRidge + .5) * config.spacing;
    updateDevices(event); focusCamera(event, focused); render();
  }

  function eventTarget() {
    const event = state.activeEvent || {};
    const args = event.arguments || event.tool_args || {};
    const actor = String(event.scope?.actor_app || event.actor || event.app || event.app_name || event.tool_name || event.tool || '');
    const scope = event.farmId || event.farm_id || event.scope?.farmId || event.scope?.farm_id || (event.scope?.farm_ids?.length === 1 ? event.scope.farm_ids[0] : null) || (typeof event.scope === 'string' ? event.scope : null) || args.farm_id;
    const otherFarm = scope && ['soybean_field', 'maize_field'].includes(scope) && scope !== state.farmId;
    let ridges = [];
    if (!otherFarm) {
      if (Array.isArray(args.ridge_ids)) ridges = args.ridge_ids;
      else if (Number.isInteger(args.ridge_id)) ridges = [args.ridge_id];
      else {
        const start = args.start_ridge ?? args.start;
        const end = args.end_ridge ?? args.end;
        if (Number.isInteger(start) && Number.isInteger(end) && end >= start && end - start < model.config.count) {
          ridges = Array.from({ length: end - start + 1 }, (_, i) => start + i);
        }
      }
    }
    return { actor, otherFarm, ridges, sequence: event.sequence ?? event.id ?? null };
  }

  function updateDevices(event) {
    const { actor, otherFarm } = event;
    model.activeRing.visible = false;
    const poses = Array.isArray(state.devicePoses) ? new Map(state.devicePoses.map(pose => [pose.id, pose])) : null;
    for (const entry of model.devices) {
      const pose = poses?.get(entry.id);
      if (entry.shared && poses) {
        const hubPreview = !!state.miniature && !!pose && pose.farmId === null && actor.includes(entry.id);
        entry.group.visible = !!pose && (pose.farmId === state.farmId || hubPreview);
        entry.trail.visible = false; entry.altitudeLine.visible = false;
        if (hubPreview) {
          // Dedicated resource previews use a declared schematic staging spot.
          // Main farm scenes still omit every device assigned to the shared hub.
          entry.group.position.copy(entry.parkingPosition); entry.group.rotation.y = 0;
        } else if (entry.group.visible) {
          // Base transit may leave the field bounds; clamping would pin an
          // outbound or returning vehicle to the final ridge/field edge.
          const x = ((Number(pose.x) || 0) - .5) * model.length;
          const z = ((Number(pose.z) || 0) - .5) * model.width;
          const altitude = Math.max(0, Number(pose.altitude) || 0);
          entry.group.position.set(x, .65 + altitude, z);
          entry.group.rotation.y = -(Number(pose.heading) || 0);
          const points = (pose.trail || []).slice(-512), attribute = entry.trail.geometry.attributes.position;
          points.forEach((point, index) => attribute.setXYZ(index, (point.x - .5) * model.length, .76 + Math.max(0, Number(point.altitude) || 0), (point.z - .5) * model.width));
          entry.trail.geometry.setDrawRange(0, points.length); attribute.needsUpdate = true;
          entry.trail.visible = points.length > 1 && !!pose.active;
          if (altitude > 0) {
            const heightLine = entry.altitudeLine.geometry.attributes.position;
            heightLine.setXYZ(0, x, .76, z); heightLine.setXYZ(1, x, altitude + .65, z); heightLine.needsUpdate = true;
            entry.altitudeLine.visible = true;
          }
        }
      } else {
        entry.group.visible = !(entry.shared && otherFarm);
        if (entry.trail) { entry.trail.visible = false; entry.altitudeLine.visible = false; }
      }
      const active = entry.shared && poses ? !!pose?.active : !!actor && actor.includes(entry.id) && !otherFarm;
      if (active && entry.group.visible) {
        model.activeRing.visible = true;
        model.activeRing.position.set(entry.group.position.x, .7, entry.group.position.z);
      }
    }
  }

  /** Move only equipment and its schematic trail; crop instances are untouched. */
  function setDevicePoses(poses) {
    if (disposed) return;
    state.devicePoses = Array.isArray(poses) ? poses : [];
    if (!model) return;
    updateDevices(eventTarget());
    if (cameraDeviceId) {
      const device = model.devices.find(item => item.id === cameraDeviceId && item.group.visible);
      if (device) { target.copy(device.group.position); target.y += 2.3; positionCamera(); }
    }
    render();
  }

  function focusCamera(event, ridges) {
    // A preview changes viewpoint; positions come from the shared replay poses.
    // Main views remain stable during playback unless focusEvent is requested.
    const enabled = state.focusEvent ?? !!state.miniature;
    const requestedDevice = state.focusDevice || (enabled && !ridges.length && !event.otherFarm ? event.actor : null);
    const device = requestedDevice && model.devices.find(item => item.group.visible && String(requestedDevice).includes(item.id));
    const newKey = JSON.stringify([modelKey, enabled, state.focusDevice, enabled ? event.sequence : null, enabled ? ridges : []]);
    if (newKey === focusKey) return;
    focusKey = newKey;
    cameraDeviceId = device?.id || null;
    if (device) {
      target.copy(device.group.position); target.y += 2.3;
      cameraBounds = { x: 25, y: 13, z: 22 };
    } else if (enabled && ridges.length) {
      target.set(0, 2, -model.width / 2 + ((ridges[0] + ridges.at(-1)) / 2 + .5) * model.config.spacing);
      cameraBounds = { x: model.length + 18, y: 17, z: Math.max(12, (ridges.at(-1) - ridges[0] + 1) * model.config.spacing + 8) };
    } else {
      target.set(0, 1, 0); cameraBounds = null;
    }
    zoom = 1; resize();
  }

  function positionCamera() {
    const distance = Math.max(430, (model?.length || 268) * 1.55);
    camera.position.set(Math.sin(azimuth) * Math.cos(elevation) * distance, Math.sin(elevation) * distance, Math.cos(azimuth) * Math.cos(elevation) * distance).add(target);
    camera.lookAt(target); camera.zoom = zoom; camera.updateProjectionMatrix();
  }
  function render() {
    if (disposed || request) return;
    request = requestAnimationFrame(() => { request = 0; if (!disposed) renderer.render(scene, camera); });
  }
  function resize() {
    if (disposed) return;
    const width = Math.max(1, container.clientWidth), height = Math.max(1, container.clientHeight), ratio = width / height;
    renderer.setSize(width, height, false);
    const length = model?.length || 268, depth = model?.width || 70.4;
    let halfHeight = Math.max(depth * .52 + 42, (length * .52 + depth * .25 + 15) / ratio);
    if (cameraBounds) {
      const horizontal = Math.abs(Math.cos(azimuth)) * cameraBounds.x / 2 + Math.abs(Math.sin(azimuth)) * cameraBounds.z / 2;
      const vertical = Math.abs(Math.sin(azimuth) * Math.sin(elevation)) * cameraBounds.x / 2 + Math.abs(Math.cos(azimuth) * Math.sin(elevation)) * cameraBounds.z / 2 + Math.cos(elevation) * cameraBounds.y / 2;
      halfHeight = Math.max(vertical, horizontal / ratio) * 1.15;
    }
    camera.left = -halfHeight * ratio; camera.right = halfHeight * ratio; camera.top = halfHeight; camera.bottom = -halfHeight;
    positionCamera(); render();
  }
  function down(event) {
    if (event.button !== 0) return;
    pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, lastX: event.clientX, lastY: event.clientY, moved: false };
    canvas.setPointerCapture(event.pointerId); canvas.style.cursor = 'grabbing';
  }
  function move(event) {
    if (!pointer || pointer.id !== event.pointerId) return;
    if (Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) > 4) pointer.moved = true;
    if (pointer.moved) {
      azimuth -= (event.clientX - pointer.lastX) * .005;
      elevation = THREE.MathUtils.clamp(elevation + (event.clientY - pointer.lastY) * .004, .25, 1.32);
      positionCamera(); render();
    }
    pointer.lastX = event.clientX; pointer.lastY = event.clientY;
  }
  function up(event) {
    if (!pointer || pointer.id !== event.pointerId) return;
    const clicked = !pointer.moved; pointer = null; canvas.style.cursor = 'grab';
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    if (!clicked || !model) return;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    mouse.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
    raycaster.setFromCamera(mouse, camera);
    const hits = raycaster.intersectObjects(model.pickables.filter(object => object.visible), true);
    for (const hit of hits) {
      let object = hit.object;
      while (object && !object.userData.pick) object = object.parent;
      if (!object?.userData.pick) continue;
      const pick = object.userData.pick;
      if (pick.type === 'device') { onPick({ type: 'device', farmId: state.farmId, deviceId: pick.deviceId, label: pick.label }); return; }
      let rid;
      if (pick.mapping === 'row') rid = hit.instanceId;
      else if (pick.mapping === 'stem') rid = model.plants[hit.instanceId]?.rid;
      else if (pick.mapping === 'leaf') rid = model.plants[Math.floor(hit.instanceId / model.leafCount)]?.rid;
      else rid = Math.floor((hit.point.z + model.width / 2) / model.config.spacing);
      if (!Number.isInteger(rid) || rid < 0 || rid >= model.config.count) continue;
      state.selectedRidge = rid; model.selection.visible = true;
      model.selection.position.z = -model.width / 2 + (rid + .5) * model.config.spacing;
      render(); onPick({ type: 'ridge', farmId: state.farmId, ridgeId: rid, label: `${model.config.label} · Ridge ${rid}` }); return;
    }
  }
  function cancel() { pointer = null; canvas.style.cursor = 'grab'; }
  function wheel(event) { event.preventDefault(); zoom = THREE.MathUtils.clamp(zoom * Math.exp(-event.deltaY * .001), .65, 5); positionCamera(); render(); }
  function resetView() { azimuth = .67; elevation = .72; zoom = 1; cameraBounds = null; cameraDeviceId = null; target.set(0, 1, 0); resize(); }
  function key(event) {
    if (event.key === 'Home' || event.key.toLowerCase() === 'r') { event.preventDefault(); resetView(); }
    else if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom = Math.min(5, zoom * 1.15); positionCamera(); render(); }
    else if (event.key === '-') { event.preventDefault(); zoom = Math.max(.65, zoom / 1.15); positionCamera(); render(); }
    else if (event.key.startsWith('Arrow')) {
      event.preventDefault();
      if (event.key === 'ArrowLeft') azimuth += .1;
      if (event.key === 'ArrowRight') azimuth -= .1;
      if (event.key === 'ArrowUp') elevation = Math.min(1.32, elevation + .08);
      if (event.key === 'ArrowDown') elevation = Math.max(.25, elevation - .08);
      positionCamera(); render();
    }
  }
  function lost(event) { event.preventDefault(); canvas.setAttribute('aria-label', '3D graphics context interrupted. Use the 2D farm plot overview.'); }
  function restored() { update(); resize(); }
  const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null;
  observer?.observe(container);
  window.addEventListener('resize', resize);
  canvas.addEventListener('pointerdown', down); canvas.addEventListener('pointermove', move);
  canvas.addEventListener('pointerup', up); canvas.addEventListener('pointercancel', cancel);
  canvas.addEventListener('wheel', wheel, { passive: false }); canvas.addEventListener('keydown', key);
  canvas.addEventListener('webglcontextlost', lost); canvas.addEventListener('webglcontextrestored', restored);
  update(); resize();

  return {
    update, setDevicePoses, resetView,
    destroy() {
      if (disposed) return;
      disposed = true; observer?.disconnect(); cancelAnimationFrame(request);
      window.removeEventListener('resize', resize);
      canvas.removeEventListener('pointerdown', down); canvas.removeEventListener('pointermove', move);
      canvas.removeEventListener('pointerup', up); canvas.removeEventListener('pointercancel', cancel);
      canvas.removeEventListener('wheel', wheel); canvas.removeEventListener('keydown', key);
      canvas.removeEventListener('webglcontextlost', lost); canvas.removeEventListener('webglcontextrestored', restored);
      releaseModel(); sun.shadow.dispose(); renderer.dispose(); renderer.forceContextLoss(); canvas.remove();
    },
  };
}
