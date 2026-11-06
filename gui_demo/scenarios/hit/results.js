/** Results shared by the HIT equipment panel and workflow previews. */
const TILE_SIZE = 256;
const MIN_ZOOM = 3;
const MAX_ZOOM = 20;
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const defaultAssetUrl = path => new URL(path, import.meta.url).href;

/** Results are revealed only after the corresponding presentation event. */
export function resultMarkup(data, equipment, step, { compact = false } = {}) {
  const satellite = equipment === 'Satellite';
  const threshold = satellite ? 4 : 8;
  const ready = Number(step) >= threshold;
  const kind = satellite ? 'satellite' : 'drone';
  const heading = satellite ? 'Remote sensing results' : 'Drone results';
  const open = `<section class="hit-results${compact ? ' hit-results-compact' : ''}" data-hit-results="${kind}"><h4>${heading}</h4>`;
  if (!ready) return `${open}<p class="hit-results-pending">Prepared result becomes available after step ${threshold}.</p></section>`;
  if (!satellite) {
    const path = data?.assets?.droneResult;
    if (!path) return `${open}<p class="hit-results-pending">Result image unavailable.</p></section>`;
    const url = escapeHtml(defaultAssetUrl(path));
    return `${open}<a class="hit-results-image-link" data-hit-asset-link="droneResult" href="${url}" target="_blank" rel="noopener noreferrer" aria-label="Open full-size drone result in a new tab"><div class="hit-results-lightboard"><img class="hit-results-drone-image hit-results-drone-source" data-hit-asset="droneResult" src="${url}" alt="Drone field, rice and lodging identification results" hidden><canvas class="hit-results-drone-image hit-results-drone-canvas" role="img" aria-label="Drone field, rice and lodging identification results on a light background" hidden></canvas><span class="hit-results-image-status" role="status">Loading result…</span></div></a><p class="hit-results-caption">Click the image to open the full-size result</p></section>`;
  }
  return `${open}
    <div class="hit-results-map-toolbar"><span>Map / Satellite / Classification</span><div><button type="button" data-hit-map-action="out" aria-label="Zoom map out">−</button><output class="hit-results-zoom" aria-label="Map zoom level"></output><button type="button" data-hit-map-action="in" aria-label="Zoom map in">+</button><button type="button" data-hit-map-action="reset">Reset</button></div></div>
    <div class="hit-results-map" tabindex="0" role="group" aria-label="Interactive satellite result map. Drag to pan; use plus and minus to zoom.">
      <div class="hit-results-tiles" aria-hidden="true"></div>
      <img class="hit-results-overlay" data-hit-asset="satelliteRgb" alt="Satellite RGB imagery" draggable="false">
      <img class="hit-results-overlay" data-hit-asset="satelliteMask" alt="Crop classification mask" draggable="false">
      <img class="hit-results-legend" data-hit-asset="legend" alt="Crop classification legend">
      <a class="hit-results-attribution" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a>
    </div>
    <div class="hit-results-opacity"><label><span>Satellite RGB</span><input type="range" min="0" max="100" value="90" data-hit-opacity="satelliteRgb" aria-label="Satellite image opacity"><output>90%</output></label><label><span>Crop classification</span><input type="range" min="0" max="100" value="55" data-hit-opacity="satelliteMask" aria-label="Classification mask opacity"><output>55%</output></label></div>
    <p class="hit-results-network-note" role="status" hidden>Basemap unavailable; local imagery is still shown</p>
  </section>`;
}

/** Make only edge-connected, neutral near-black padding transparent in memory.
 * The source JPEG has a thin white frame, so seed from a narrow perimeter band.
 * RGB values, enclosed dark detail, the colored footprint and legend are retained.
 */
function clearEdgeBackground(pixels, width, height) {
  const count = width * height;
  const visited = new Uint8Array(count), queue = new Uint32Array(count);
  let head = 0, tail = 0;
  const seed = index => {
    if (visited[index]) return;
    visited[index] = 1;
    const offset = index * 4;
    const high = Math.max(pixels[offset], pixels[offset + 1], pixels[offset + 2]);
    const low = Math.min(pixels[offset], pixels[offset + 1], pixels[offset + 2]);
    if (pixels[offset + 3] && high <= 32 && high - low <= 12) queue[tail++] = index;
  };
  const band = Math.min(width, height, Math.max(4, Math.min(Math.ceil(Math.min(width, height) * .015), 16)));
  for (let y = 0; y < height; y++) {
    if (y < band || y >= height - band) {
      for (let x = 0; x < width; x++) seed(y * width + x);
    } else {
      for (let x = 0; x < band; x++) { seed(y * width + x); seed(y * width + width - 1 - x); }
    }
  }
  while (head < tail) {
    const index = queue[head++], x = index % width;
    pixels[index * 4 + 3] = 0;
    if (x) seed(index - 1);
    if (x < width - 1) seed(index + 1);
    if (index >= width) seed(index - width);
    if (index < count - width) seed(index + width);
  }
  return tail;
}

function mercator(lon, lat) {
  const latitude = Math.max(-85.05112878, Math.min(85.05112878, lat)) * Math.PI / 180;
  return { x: (lon + 180) / 360, y: (1 - Math.log(Math.tan(Math.PI / 4 + latitude / 2)) / Math.PI) / 2 };
}

/** Attach controls only within host; call destroy before replacing its markup. */
export function mountResults(host, data, { assetUrl = defaultAssetUrl } = {}) {
  const cleanups = [];
  const roots = [...(host.matches?.('.hit-results') ? [host] : []), ...host.querySelectorAll('.hit-results')];
  let destroyed = false;
  const listen = (node, type, handler, options) => {
    node.addEventListener(type, handler, options);
    cleanups.push(() => node.removeEventListener(type, handler, options));
  };
  for (const root of roots) {
    root.querySelectorAll('[data-hit-asset]').forEach(image => {
      const path = data?.assets?.[image.dataset.hitAsset];
      if (path) image.src = assetUrl(path);
    });
    root.querySelectorAll('[data-hit-asset-link]').forEach(link => {
      const path = data?.assets?.[link.dataset.hitAssetLink];
      if (path) link.href = assetUrl(path);
    });
    const source = root.querySelector('.hit-results-drone-source');
    if (source) {
      const canvas = root.querySelector('.hit-results-drone-canvas');
      const link = root.querySelector('.hit-results-image-link');
      const status = root.querySelector('.hit-results-image-status');
      let resultUrl = null, renderVersion = 0;
      const renderResult = () => {
        if (destroyed || !source.naturalWidth || !source.naturalHeight) return;
        const version = ++renderVersion;
        canvas.width = source.naturalWidth; canvas.height = source.naturalHeight;
        try {
          const context = canvas.getContext('2d', { willReadFrequently: true });
          if (!context) throw new Error('Canvas unavailable');
          context.drawImage(source, 0, 0);
          const image = context.getImageData(0, 0, canvas.width, canvas.height);
          canvas.dataset.backgroundPixels = String(clearEdgeBackground(image.data, canvas.width, canvas.height));
          context.putImageData(image, 0, 0);
          source.hidden = true; canvas.hidden = false; status.hidden = true;
          // Full-size viewing uses the same lightboard, without changing any asset.
          const board = document.createElement('canvas');
          board.width = canvas.width; board.height = canvas.height;
          const boardContext = board.getContext('2d');
          if (!boardContext) return;
          boardContext.fillStyle = '#f5f5f2'; boardContext.fillRect(0, 0, board.width, board.height);
          boardContext.drawImage(canvas, 0, 0);
          board.toBlob(blob => {
            if (destroyed || version !== renderVersion || !blob) return;
            if (resultUrl) URL.revokeObjectURL(resultUrl);
            resultUrl = URL.createObjectURL(blob); link.href = resultUrl;
          }, 'image/png');
        } catch {
          // Preserve the complete source if canvas access is unavailable.
          source.hidden = false; canvas.hidden = true; status.hidden = true;
        }
      };
      const failResult = () => {
        if (destroyed) return;
        renderVersion++;
        source.hidden = true; canvas.hidden = true;
        status.textContent = 'Result image unavailable.'; status.hidden = false;
        link.removeAttribute('href');
      };
      listen(source, 'load', renderResult); listen(source, 'error', failResult);
      if (source.complete) { if (source.naturalWidth) renderResult(); else failResult(); }
      cleanups.push(() => { renderVersion++; if (resultUrl) URL.revokeObjectURL(resultUrl); });
    }
    const viewport = root.querySelector('.hit-results-map');
    if (!viewport) continue;
    const bounds = data?.farm?.bounds;
    if (!Array.isArray(bounds) || bounds.length !== 4 || !bounds.every(Number.isFinite) || bounds[0] >= bounds[2] || bounds[1] >= bounds[3]) {
      viewport.textContent = 'Map bounds unavailable.';
      continue;
    }
    const northwest = mercator(bounds[0], bounds[3]);
    const southeast = mercator(bounds[2], bounds[1]);
    const fieldCenter = { x: (northwest.x + southeast.x) / 2, y: (northwest.y + southeast.y) / 2 };
    const tileHost = viewport.querySelector('.hit-results-tiles');
    const overlays = [...viewport.querySelectorAll('.hit-results-overlay')];
    const note = root.querySelector('.hit-results-network-note');
    const zoomLabel = root.querySelector('.hit-results-zoom');
    const tiles = new Map();
    let zoom = 15, center = { ...fieldCenter }, width = 320, height = 240, pan = null, autoFit = true;
    let pendingFrame = 0;

    function scheduleRender() {
      if (!pendingFrame && !destroyed) pendingFrame = requestAnimationFrame(() => { pendingFrame = 0; if (!destroyed) render(); });
    }

    function render() {
      const world = TILE_SIZE * 2 ** zoom;
      const left = center.x * world - width / 2;
      const top = center.y * world - height / 2;
      const extent = 2 ** zoom;
      const visible = new Set();
      for (let y = Math.floor(top / TILE_SIZE); y <= Math.floor((top + height) / TILE_SIZE); y++) {
        if (y < 0 || y >= extent) continue;
        for (let x = Math.floor(left / TILE_SIZE); x <= Math.floor((left + width) / TILE_SIZE); x++) {
          const key = `${zoom}/${x}/${y}`;
          visible.add(key);
          let tile = tiles.get(key);
          if (!tile) {
            tile = document.createElement('img');
            tile.alt = ''; tile.draggable = false; tile.className = 'hit-results-tile';
            tile.width = TILE_SIZE; tile.height = TILE_SIZE;
            tile.onerror = () => { if (!destroyed && tiles.has(key)) note.hidden = false; };
            tile.src = `https://tile.openstreetmap.org/${zoom}/${((x % extent) + extent) % extent}/${y}.png`;
            tiles.set(key, tile); tileHost.append(tile);
          }
          tile.style.left = `${x * TILE_SIZE - left}px`;
          tile.style.top = `${y * TILE_SIZE - top}px`;
        }
      }
      for (const [key, tile] of tiles) if (!visible.has(key)) { tile.onerror = null; tile.remove(); tiles.delete(key); }
      // Project both identically georeferenced rasters into the basemap bounds.
      for (const overlay of overlays) {
        overlay.style.left = `${northwest.x * world - left}px`;
        overlay.style.top = `${northwest.y * world - top}px`;
        overlay.style.width = `${(southeast.x - northwest.x) * world}px`;
        overlay.style.height = `${(southeast.y - northwest.y) * world}px`;
      }
      zoomLabel.textContent = String(zoom);
      root.querySelector('[data-hit-map-action="out"]').disabled = zoom <= MIN_ZOOM;
      root.querySelector('[data-hit-map-action="in"]').disabled = zoom >= MAX_ZOOM;
    }

    function fit() {
      center = { ...fieldCenter };
      const scale = Math.min(width * .9 / ((southeast.x - northwest.x) * TILE_SIZE), height * .9 / ((southeast.y - northwest.y) * TILE_SIZE));
      zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.floor(Math.log2(scale))));
      scheduleRender();
    }

    function resize() {
      width = viewport.clientWidth || 320; height = viewport.clientHeight || 240;
      if (autoFit) fit(); else scheduleRender();
    }

    function zoomAt(next, x = width / 2, y = height / 2) {
      next = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, next));
      if (next === zoom) return;
      autoFit = false;
      const before = TILE_SIZE * 2 ** zoom, after = TILE_SIZE * 2 ** next;
      center.x += (x - width / 2) * (1 / before - 1 / after);
      center.y = Math.max(0, Math.min(1, center.y + (y - height / 2) * (1 / before - 1 / after)));
      zoom = next; scheduleRender();
    }

    for (const slider of root.querySelectorAll('[data-hit-opacity]')) {
      const image = overlays.find(item => item.dataset.hitAsset === slider.dataset.hitOpacity);
      const update = () => { if (image) image.style.opacity = String(Number(slider.value) / 100); slider.parentElement.querySelector('output').textContent = `${slider.value}%`; };
      listen(slider, 'input', update); update();
    }
    listen(root, 'click', event => {
      const button = event.target.closest('[data-hit-map-action]');
      if (!button || !root.contains(button)) return;
      event.stopPropagation();
      if (button.dataset.hitMapAction === 'reset') { autoFit = true; fit(); }
      else zoomAt(zoom + (button.dataset.hitMapAction === 'in' ? 1 : -1));
    });
    listen(viewport, 'wheel', event => {
      event.preventDefault(); event.stopPropagation();
      const rect = viewport.getBoundingClientRect();
      zoomAt(zoom + (event.deltaY < 0 ? 1 : -1), event.clientX - rect.left, event.clientY - rect.top);
    }, { passive: false });
    listen(viewport, 'pointerdown', event => {
      if (event.button !== 0 || event.target.closest('a')) return;
      autoFit = false; pan = { id: event.pointerId, x: event.clientX, y: event.clientY, center: { ...center } };
      viewport.setPointerCapture(event.pointerId); viewport.classList.add('hit-results-panning'); event.preventDefault(); event.stopPropagation();
    });
    listen(viewport, 'pointermove', event => {
      if (pan?.id !== event.pointerId) return;
      const world = TILE_SIZE * 2 ** zoom;
      center.x = pan.center.x - (event.clientX - pan.x) / world;
      center.y = Math.max(0, Math.min(1, pan.center.y - (event.clientY - pan.y) / world));
      scheduleRender();
    });
    const endPan = event => {
      if (pan?.id !== event.pointerId) return;
      pan = null; viewport.classList.remove('hit-results-panning');
      if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
    };
    listen(viewport, 'pointerup', endPan); listen(viewport, 'pointercancel', endPan); listen(viewport, 'lostpointercapture', endPan);
    listen(viewport, 'keydown', event => {
      if (event.key === '+' || event.key === '=') zoomAt(zoom + 1);
      else if (event.key === '-') zoomAt(zoom - 1);
      else if (event.key === '0') { autoFit = true; fit(); }
      else if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
        autoFit = false; const move = 40 / (TILE_SIZE * 2 ** zoom);
        center.x += event.key === 'ArrowLeft' ? -move : event.key === 'ArrowRight' ? move : 0;
        center.y = Math.max(0, Math.min(1, center.y + (event.key === 'ArrowUp' ? -move : event.key === 'ArrowDown' ? move : 0)));
        scheduleRender();
      } else return;
      event.preventDefault(); event.stopPropagation();
    });
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(resize) : null;
    observer?.observe(viewport);
    if (!observer) listen(window, 'resize', resize);
    cleanups.push(() => {
      observer?.disconnect(); cancelAnimationFrame(pendingFrame);
      for (const tile of tiles.values()) tile.onerror = null;
      tiles.clear();
      if (pan && viewport.hasPointerCapture(pan.id)) viewport.releasePointerCapture(pan.id);
      pan = null; viewport.classList.remove('hit-results-panning');
    });
    resize();
  }
  return { destroy() { if (destroyed) return; destroyed = true; cleanups.forEach(cleanup => cleanup()); } };
}
