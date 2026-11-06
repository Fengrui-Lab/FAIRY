const CATEGORIES = {
  observe: { label: 'Observe', color: '#63849a', pale: '#edf3f6' },
  diagnose: { label: 'Diagnose', color: '#8b7c9c', pale: '#f2eef6' },
  act: { label: 'Act', color: '#718e7b', pale: '#edf3ef' },
  resource: { label: 'Resource', color: '#7e8991', pale: '#f0f2f4' },
  wait: { label: 'Wait', color: '#a18a64', pale: '#f6f2eb' },
  report: { label: 'Report', color: '#99817d', pale: '#f5f0ef' },
};
const STAGES = ['Establishment', 'Nutrition', 'Disease', 'Water', 'Harvest'];
const SVG = 'http://www.w3.org/2000/svg';
const NODE_W = 212, NODE_H = 116, X_STEP = 254, LANE_H = 158, HEIGHT = LANE_H * 3;
let instances = 0;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function dateLabel(event, full = false) {
  // Preserve the simulation's written timezone, rather than the browser timezone.
  const raw = String(event.datetime_after || '');
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}:\d{2})/);
  if (!match) return raw.slice(0, 16) || 'Time unavailable';
  const month = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][Number(match[2]) - 1];
  return `${month} ${Number(match[3])}${full ? `, ${match[1]}` : ''} · ${match[4]}`;
}

function stageMarker(event) {
  const id = String(event.step_id || '').toLowerCase();
  if (/^(wait_dent|late_fill_|wait_soybean_harvest|wait_maize_harvest|soybean_harvest_|maize_harvest_|harvest_|unload_|dry_|store_|final_)/.test(id)) return 4;
  if (/^(wait_grain_fill|grain_fill_|drought_)/.test(id)) return 3;
  if (/^(wait_silking|silking_|disease_)/.test(id)) return 2;
  if (/^(wait_vegetative|vegetative_|maize_topdress|maize_after_topdress)/.test(id)) return 1;
  return null;
}

/**
 * Recorded sequential execution, grouped into farm lanes for ownership only.
 * Callbacks receive the original event; hover never changes the selected step.
 * onHover also receives optional {x, y, anchor} positioning information.
 */
export function mountWorkflow(container, { events = [], step = 0, farms = [], onSelect = () => {}, onHover = () => {} } = {}) {
  const id = `wf-${++instances}`;
  const source = [...events].filter(e => Number.isFinite(Number(e.sequence))).sort((a, b) => Number(a.sequence) - Number(b.sequence));
  let currentStage = 0;
  const entries = source.map((event, index) => {
    const marker = stageMarker(event);
    if (marker != null) currentStage = Math.max(currentStage, marker);
    return { event, index, sequence: Number(event.sequence), stage: STAGES[currentStage] };
  });
  const entryBySequence = new Map(entries.map(entry => [entry.sequence, entry]));
  const farmA = farms.find(f => /farm plot a/i.test(f.label || '') || /soybean/i.test(f.id || '')) || farms[0];
  const farmB = farms.find(f => /farm plot b/i.test(f.label || '')) || farms.find(f => f !== farmA);
  const farmIds = [farmA?.id || 'soybean_field', farmB?.id || 'maize_field'];
  const cropName = farm => String(farm?.crop_id || farm?.crop || (String(farm?.id).includes('soybean') ? 'Soybean' : 'Maize')).replace(/^./, c => c.toUpperCase());
  const lanes = [
    { label: 'farm plot A', mark: 'A', subtitle: cropName(farmA) },
    { label: 'Shared / global', mark: '↔', subtitle: 'Assets and clock' },
    { label: 'farm plot B', mark: 'B', subtitle: cropName(farmB) },
  ];
  const laneFor = entry => {
    const ids = entry.event.scope?.farm_ids || [];
    return ids.length === 1 && ids[0] === farmIds[0] ? 0 : ids.length === 1 && ids[0] === farmIds[1] ? 2 : 1;
  };
  const scopeLabel = entry => laneFor(entry) === 1 ? (entry.event.scope?.kind === 'global' ? 'Global' : 'Shared') : lanes[laneFor(entry)].label;
  const titleFor = entry => entry.event.title || String(entry.event.tool_name || 'Operation').split('__').pop().replaceAll('_', ' ');
  const normalize = value => Number(value) === 0 ? 0 : entryBySequence.has(Number(value)) ? Number(value) : 0;
  let selected = normalize(step), stage = 'all', query = '', page = 0, pageSize = 18, zoom = 1, fitToHeight = true;
  let filtered = entries, visible = [], width = 400, destroyed = false, frame = 0;
  let buttons = new Map(), positions = new Map(), pan = null;
  const cleanups = [];
  const listen = (node, type, handler, options) => {
    node.addEventListener(type, handler, options);
    cleanups.push(() => node.removeEventListener(type, handler, options));
  };
  const root = element('section', 'wf-root');
  root.setAttribute('aria-label', 'Recorded workflow for farm plot A and farm plot B');
  root.innerHTML = `
    <div class="wf-toolbar">
      <label class="wf-control"><span>Stage</span><select class="wf-stage" aria-label="Filter workflow by stage"></select></label>
      <label class="wf-search"><span class="wf-sr-only">Search tool, action or step number</span><input type="search" placeholder="Find an action or tool…" aria-label="Search tool, action or step number"></label>
      <button type="button" class="wf-control-button" data-action="locate">Locate current</button>
      <div class="wf-zoom" aria-label="Workflow zoom"><button type="button" data-action="out" aria-label="Zoom out">−</button><output aria-label="Current zoom">100%</output><button type="button" data-action="in" aria-label="Zoom in">+</button></div>
      <button type="button" class="wf-control-button" data-action="fit">Fit height</button>
    </div>
    <div class="wf-subbar"><div class="wf-legend" aria-label="Category colors"></div><span class="wf-chain-label">Execution order</span></div>
    <div class="wf-body"><aside class="wf-rail" aria-label="Farm ownership lanes"></aside><div class="wf-scroll" tabindex="0" aria-label="Workflow canvas. Scroll or drag the background to pan."><div class="wf-size"><div class="wf-world"></div></div><div class="wf-empty" hidden>No matching actions.<button type="button" data-action="reset">Clear filters</button></div></div></div>
    <div class="wf-footer"><div class="wf-page-tools"><button type="button" data-action="previous" aria-label="Previous workflow page">←</button><span class="wf-page-label" aria-live="polite"></span><button type="button" data-action="next" aria-label="Next workflow page">→</button><label class="wf-page-size"><span class="wf-sr-only">Actions per page</span><select aria-label="Actions per page"><option value="18">18 / page</option><option value="30">30 / page</option><option value="48">48 / page</option></select></label></div><span class="wf-range-label"></span><span class="wf-selected-label"></span></div>
    <div class="wf-help">Arrows follow execution order across lanes. Dashed arrows skip filtered actions. Hover to preview; click to select.</div>`;
  container.append(root);
  const viewport = root.querySelector('.wf-scroll'), world = root.querySelector('.wf-world'), size = root.querySelector('.wf-size');
  const rail = root.querySelector('.wf-rail'), stageSelect = root.querySelector('.wf-stage'), search = root.querySelector('input');
  const pageSizeSelect = root.querySelector('.wf-page-size select');
  const option = (value, label) => { const node = element('option', '', label); node.value = value; return node; };
  stageSelect.append(option('all', `All stages (${entries.length})`));
  for (const label of STAGES) {
    const count = entries.filter(entry => entry.stage === label).length;
    const node = option(label, `${label} (${count})`); node.disabled = count === 0; stageSelect.append(node);
  }
  for (const category of Object.values(CATEGORIES)) {
    const item = element('span', 'wf-legend-item'), swatch = element('i');
    swatch.style.backgroundColor = category.color; item.append(swatch, document.createTextNode(category.label));
    root.querySelector('.wf-legend').append(item);
  }
  lanes.forEach((lane, index) => {
    const label = element('div', 'wf-lane-label'); label.dataset.lane = index;
    label.append(element('span', 'wf-farm-mark', lane.mark), element('strong', '', lane.label), element('small', '', lane.subtitle));
    rail.append(label);
  });

  function applyFilters() {
    const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    filtered = entries.filter(entry => {
      const haystack = `${entry.sequence} ${entry.event.step_id} ${entry.event.tool_name} ${titleFor(entry)} ${scopeLabel(entry)} ${entry.stage}`.toLowerCase();
      return (stage === 'all' || entry.stage === stage) && terms.every(term => haystack.includes(term));
    });
    page = Math.min(page, Math.max(0, Math.ceil(filtered.length / pageSize) - 1));
  }

  function render() {
    onHover(null); applyFilters(); buttons = new Map(); positions = new Map(); world.replaceChildren();
    visible = filtered.slice(page * pageSize, (page + 1) * pageSize);
    width = Math.max(400, visible.length * X_STEP + 28);
    world.style.width = `${width}px`; world.style.height = `${HEIGHT}px`;
    for (let lane = 0; lane < 3; lane++) {
      const band = element('div', 'wf-lane-band'); band.style.top = `${lane * LANE_H}px`; band.style.height = `${LANE_H}px`; world.append(band);
    }
    const svg = document.createElementNS(SVG, 'svg'); svg.classList.add('wf-edges');
    svg.setAttribute('viewBox', `0 0 ${width} ${HEIGHT}`); svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = `<defs><marker id="${id}-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0 L10 5 L0 10Z" fill="#9b9b9b"/></marker></defs>`;
    world.append(svg);
    visible.forEach((entry, index) => {
      const point = { x: 24 + index * X_STEP, y: laneFor(entry) * LANE_H + 30 };
      positions.set(entry.sequence, point);
      if (index > 0) {
        const previous = visible[index - 1], from = positions.get(previous.sequence), gap = entry.index - previous.index - 1;
        const x1 = from.x + NODE_W, y1 = from.y + NODE_H / 2, x2 = point.x - 4, y2 = point.y + NODE_H / 2, mid = (x1 + x2) / 2;
        const path = document.createElementNS(SVG, 'path');
        path.setAttribute('d', `M${x1} ${y1} C${mid} ${y1},${mid} ${y2},${x2} ${y2}`);
        path.setAttribute('marker-end', `url(#${id}-arrow)`); if (gap) path.classList.add('wf-gap-edge');
        const description = document.createElementNS(SVG, 'title'); description.textContent = gap ? `${gap} filtered actions between these steps` : 'Next recorded action';
        path.append(description); svg.append(path);
        if (gap) {
          const badge = element('span', 'wf-gap-count', `+${gap}`); badge.style.left = `${mid - 12}px`; badge.style.top = `${Math.min(y1, y2) - 26}px`;
          badge.title = `${gap} filtered actions`; world.append(badge);
        }
      }
      const category = CATEGORIES[entry.event.category] || CATEGORIES.observe;
      const button = element('button', 'wf-node'); button.type = 'button'; button.dataset.sequence = entry.sequence;
      button.style.left = `${point.x}px`; button.style.top = `${point.y}px`;
      button.style.setProperty('--wf-category-color', category.color); button.style.setProperty('--wf-category-pale', category.pale);
      button.setAttribute('aria-label', `Step ${entry.sequence}. ${scopeLabel(entry)}. ${titleFor(entry)}. ${entry.event.tool_name}. ${dateLabel(entry.event, true)}`);
      const top = element('div', 'wf-node-top'); top.append(element('span', 'wf-node-index', String(entry.sequence).padStart(3, '0')), element('span', 'wf-node-category', category.label), element('span', 'wf-node-current', 'Current'));
      const title = element('strong', 'wf-node-title', titleFor(entry)); title.title = titleFor(entry);
      const tool = element('span', 'wf-node-tool', String(entry.event.tool_name || '').replace('__', '.')); tool.title = entry.event.tool_name || '';
      const bottom = element('div', 'wf-node-bottom'), scope = element('span', 'wf-scope-group');
      scope.append(element('span', 'wf-scope-badge', scopeLabel(entry)));
      const actor = entry.event.scope?.actor_app || String(entry.event.tool_name || '').split('__')[0];
      if (laneFor(entry) !== 1 && (entry.event.scope?.actor_scope === 'shared' || ['Tractor', 'Warehouse', 'Mavic3M', 'Matrice4T', 'Robot0'].includes(actor))) {
        const shared = element('span', 'wf-shared-mark', '↔'); shared.title = `Shared asset: ${actor}`;
        shared.setAttribute('aria-label', `Shared asset: ${actor}`); scope.append(shared);
      }
      bottom.append(scope, element('time', 'wf-node-date', dateLabel(entry.event)));
      button.append(top, title, tool, bottom); world.append(button); buttons.set(entry.sequence, button);
    });
    root.querySelector('.wf-empty').hidden = visible.length > 0;
    root.querySelector('.wf-page-label').textContent = `${filtered.length ? page + 1 : 0} / ${Math.max(1, Math.ceil(filtered.length / pageSize))}`;
    root.querySelector('[data-action="previous"]').disabled = page === 0;
    root.querySelector('[data-action="next"]').disabled = (page + 1) * pageSize >= filtered.length;
    const first = visible[0], last = visible.at(-1);
    root.querySelector('.wf-range-label').textContent = first ? `Steps ${first.sequence}–${last.sequence} · ${filtered.length} of ${entries.length} actions` : `0 of ${entries.length} actions`;
    setZoom(zoom, false); renderSelection(); viewport.scrollTo({ left: 0, top: 0 });
  }

  function renderSelection() {
    for (const [sequence, button] of buttons) {
      button.classList.toggle('wf-selected', sequence === selected);
      button.classList.toggle('wf-before-cursor', sequence < selected);
      button.setAttribute('aria-pressed', String(sequence === selected));
    }
    const entry = entryBySequence.get(selected);
    root.querySelector('.wf-selected-label').textContent = entry ? `Current: ${selected} / ${entries.length}${buttons.has(selected) ? '' : ' · outside this page'}` : 'Initial state · step 0';
  }

  function setZoom(value, preserve = true) {
    const centerX = (viewport.scrollLeft + viewport.clientWidth / 2) / zoom;
    const centerY = (viewport.scrollTop + viewport.clientHeight / 2) / zoom;
    zoom = Math.max(.55, Math.min(1.5, value));
    world.style.transform = `scale(${zoom})`; size.style.width = `${width * zoom}px`; size.style.height = `${HEIGHT * zoom}px`;
    root.querySelector('output').textContent = `${Math.round(zoom * 100)}%`;
    rail.style.setProperty('--wf-lane-height', `${LANE_H * zoom}px`);
    rail.querySelectorAll('.wf-lane-label').forEach(label => { label.style.top = `${(Number(label.dataset.lane) + .5) * LANE_H * zoom}px`; });
    root.querySelector('[data-action="out"]').disabled = zoom <= .55;
    root.querySelector('[data-action="in"]').disabled = zoom >= 1.5;
    if (preserve) { viewport.scrollLeft = centerX * zoom - viewport.clientWidth / 2; viewport.scrollTop = centerY * zoom - viewport.clientHeight / 2; }
    onHover(null); syncRail();
  }

  function syncRail() { rail.style.setProperty('--wf-scroll-y', `${-viewport.scrollTop}px`); }
  function scrollToEntry(sequence, center = true) {
    const point = positions.get(sequence); if (!point) return;
    const left = point.x * zoom, right = (point.x + NODE_W) * zoom;
    const top = point.y * zoom, bottom = (point.y + NODE_H) * zoom;
    if (center || left < viewport.scrollLeft || right > viewport.scrollLeft + viewport.clientWidth) viewport.scrollLeft = (left + right - viewport.clientWidth) / 2;
    if (center || top < viewport.scrollTop || bottom > viewport.scrollTop + viewport.clientHeight) viewport.scrollTop = (top + bottom - viewport.clientHeight) / 2;
  }
  function locate() {
    if (destroyed) return;
    if (selected === 0) { stage = 'all'; query = ''; page = 0; stageSelect.value = stage; search.value = ''; render(); return; }
    let index = filtered.findIndex(entry => entry.sequence === selected);
    if (index < 0) { stage = 'all'; query = ''; stageSelect.value = stage; search.value = ''; applyFilters(); index = filtered.findIndex(entry => entry.sequence === selected); }
    const nextPage = Math.floor(Math.max(0, index) / pageSize);
    if (nextPage !== page || !buttons.has(selected)) { page = nextPage; render(); }
    scrollToEntry(selected);
  }
  function hover(button, event) {
    const entry = entryBySequence.get(Number(button.dataset.sequence)); if (!entry) return;
    const anchor = button.getBoundingClientRect();
    onHover(entry.event, { x: event?.clientX ?? anchor.right, y: event?.clientY ?? anchor.top, anchor });
  }

  listen(root, 'click', event => {
    const button = event.target.closest('button'); if (!button || !root.contains(button)) return;
    // The host also has previous/next actions. Workflow paging must not advance
    // the global world cursor; node selection uses the explicit callback below.
    event.stopPropagation();
    if (button.dataset.sequence) { selected = Number(button.dataset.sequence); renderSelection(); onSelect(entryBySequence.get(selected).event); return; }
    const action = button.dataset.action;
    if (action === 'out' || action === 'in') { fitToHeight = false; setZoom(zoom + (action === 'in' ? .1 : -.1)); }
    if (action === 'fit') { fitToHeight = true; setZoom(Math.min(1, (viewport.clientHeight - 12) / HEIGHT), false); viewport.scrollTop = 0; }
    if (action === 'locate') locate();
    if (action === 'previous' || action === 'next') { page += action === 'next' ? 1 : -1; render(); }
    if (action === 'reset') { stage = 'all'; query = ''; page = 0; stageSelect.value = stage; search.value = ''; render(); }
  });
  listen(stageSelect, 'change', () => { stage = stageSelect.value; page = 0; render(); });
  listen(search, 'input', () => { query = search.value; page = 0; render(); });
  listen(pageSizeSelect, 'change', () => { const first = page * pageSize; pageSize = Number(pageSizeSelect.value); page = Math.floor(first / pageSize); render(); });
  listen(world, 'pointerover', event => { const button = event.target.closest('.wf-node'); if (button && !button.contains(event.relatedTarget)) hover(button, event); });
  listen(world, 'pointerout', event => { const button = event.target.closest('.wf-node'); if (button && !button.contains(event.relatedTarget)) onHover(null); });
  listen(world, 'focusin', event => { const button = event.target.closest('.wf-node'); if (button) hover(button); });
  listen(world, 'focusout', event => { if (event.target.closest('.wf-node')) onHover(null); });
  listen(viewport, 'scroll', () => {
    syncRail();
    const focused = document.activeElement;
    if (focused?.classList.contains('wf-node') && world.contains(focused) && focused.matches(':focus-visible')) hover(focused);
    else onHover(null);
  }, { passive: true });
  listen(world, 'keydown', event => {
    const button = event.target.closest('.wf-node'); if (!button) return;
    let index = filtered.findIndex(entry => entry.sequence === Number(button.dataset.sequence));
    if (event.key === 'ArrowRight') index++;
    else if (event.key === 'ArrowLeft') index--;
    else if (event.key === 'Home') index = 0;
    else if (event.key === 'End') index = filtered.length - 1;
    else return;
    event.preventDefault(); index = Math.max(0, Math.min(filtered.length - 1, index));
    const entry = filtered[index], nextPage = Math.floor(index / pageSize);
    if (nextPage !== page) { page = nextPage; render(); }
    buttons.get(entry.sequence)?.focus({ preventScroll: true }); scrollToEntry(entry.sequence, false);
  });
  listen(viewport, 'pointerdown', event => {
    if (event.pointerType !== 'mouse' || event.button !== 0 || event.target.closest('button')) return;
    pan = { id: event.pointerId, x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop };
    viewport.setPointerCapture(event.pointerId); viewport.classList.add('wf-panning'); event.preventDefault();
  });
  listen(viewport, 'pointermove', event => { if (pan?.id === event.pointerId) { viewport.scrollLeft = pan.left - event.clientX + pan.x; viewport.scrollTop = pan.top - event.clientY + pan.y; } });
  const endPan = event => { if (pan?.id === event.pointerId) { pan = null; viewport.classList.remove('wf-panning'); if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId); } };
  listen(viewport, 'pointerup', endPan); listen(viewport, 'pointercancel', endPan); listen(viewport, 'lostpointercapture', () => { pan = null; viewport.classList.remove('wf-panning'); });
  const resize = typeof ResizeObserver === 'function' ? new ResizeObserver(() => {
    if (destroyed) return;
    if (fitToHeight && viewport.clientHeight > 0) { setZoom(Math.min(1, (viewport.clientHeight - 12) / HEIGHT), false); scrollToEntry(selected, false); }
    else syncRail();
  }) : null;
  resize?.observe(viewport);
  render();
  frame = requestAnimationFrame(() => {
    if (!destroyed) {
      if (viewport.clientHeight > 0) setZoom(Math.min(1, (viewport.clientHeight - 12) / HEIGHT), false);
      if (selected) locate();
    }
  });
  return {
    update({ step: next } = {}) {
      if (destroyed || next == null) return;
      selected = normalize(next); renderSelection();
      if (!selected) return;
      if (!buttons.has(selected)) locate(); else scrollToEntry(selected, false);
    },
    locate,
    destroy() {
      if (destroyed) return;
      destroyed = true; cancelAnimationFrame(frame); resize?.disconnect(); cleanups.forEach(cleanup => cleanup());
      pan = null; onHover(null); root.remove();
    },
  };
}
