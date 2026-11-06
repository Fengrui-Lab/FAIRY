/**
 * A self-contained SVG of tool observations. Each ridge receives one flat
 * colour: this is a data visualization, never a photograph or pixel map.
 * No random values, interpolation along ridges, network requests or file I/O.
 */
export function buildSurveyMap(event, farm, { layer = 'ndvi', contrast = 'standard' } = {}) {
  event = event && typeof event === 'object' ? event : {};
  farm = farm && typeof farm === 'object' ? farm : {};
  const thermal = ['temperature', 'canopy_temp_c', 'thermal', 'temp'].includes(layer);
  layer = thermal ? 'temperature' : 'ndvi';
  contrast = !thermal && contrast === 'detail' ? 'detail' : 'standard';
  const detail = contrast === 'detail', min = thermal ? 0 : detail ? .75 : 0, max = thermal ? 45 : detail ? .90 : 1;
  const unit = thermal ? '°C' : 'index', field = thermal ? 'canopy_temp_c' : 'ndvi';
  const sourceResolution = 'Tool observations · One value per ridge';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const asciiLabel = (value, fallback) => {
    const text = String(value ?? '');
    return text && /^[\x20-\x7e]+$/.test(text) ? text.slice(0, 110) : fallback;
  };
  const farmId = String(farm.id || farm.farm_id || '');
  const plotLabel = asciiLabel(farm.label, farmId.includes('maize') ? 'farm plot B' : farmId.includes('soybean') ? 'farm plot A' : 'farm plot');
  const countValue = farm.num_ridges === undefined ? 64 : Number(farm.num_ridges);
  const count = Number.isFinite(countValue) && countValue > 0 ? Math.min(512, Math.floor(countValue)) : 0;
  const length = Number.isFinite(Number(farm.field_length_m)) && Number(farm.field_length_m) > 0 ? Number(farm.field_length_m) : 268;
  const spacing = Number.isFinite(Number(farm.ridge_width_m)) && Number(farm.ridge_width_m) > 0 ? Number(farm.ridge_width_m) : 1.1;
  const width = count * spacing;
  const result = event.result && typeof event.result === 'object' ? event.result : {};
  const args = event.arguments || event.tool_args || {};
  const tool = String(event.tool_name || event.toolName || '');
  const actor = asciiLabel(event.scope?.actor_app || tool.split('__')[0], 'Survey tool');
  const sequence = Number.isInteger(Number(event.sequence)) && Number(event.sequence) >= 0 ? Number(event.sequence) : null;
  const stepLabel = sequence === null ? 'Step unavailable' : `Step ${sequence}`;
  const title = `${thermal ? 'Canopy temperature' : 'NDVI'} · ${plotLabel}`;
  const date = typeof event.datetime_after === 'string' && /^\d{4}-\d{2}-\d{2}/.test(event.datetime_after) ? event.datetime_after.slice(0, 16).replace('T', ' ') : '';
  const failed = !!event.error || !!result.error || ['error', 'failed', 'cancelled'].includes(String(event.status).toLowerCase()) || ['error', 'failed', 'cancelled'].includes(String(result.status).toLowerCase());
  const declaredFarmIds = [args.farm_id, result.farm_id];
  if (event.scope?.farm_ids?.length === 1) declaredFarmIds.push(event.scope.farm_ids[0]);
  const wrongFarm = !farmId || declaredFarmIds.some(id => id !== undefined && id !== null && String(id) !== farmId);
  const wrongTool = !!tool && !tool.endsWith('__fly_survey');
  let reason = failed ? 'failed_event' : wrongFarm ? 'wrong_farm' : wrongTool ? 'wrong_tool' : null;
  const ridgeId = value => {
    if (typeof value !== 'number' && !(typeof value === 'string' && /^\d+$/.test(value))) return null;
    const id = Number(value);
    return Number.isInteger(id) && id >= 0 && id < count ? id : null;
  };

  const records = new Map(), duplicates = new Set(), declaredCoverage = new Set();
  const hasDeclaredCoverage = Array.isArray(result.surveyed_ridges);
  if (!reason) {
    for (const raw of hasDeclaredCoverage ? result.surveyed_ridges : []) {
      const id = ridgeId(raw); if (id !== null) declaredCoverage.add(id);
    }
    const observations = result.observations;
    const entries = Array.isArray(observations) ? observations.map(row => [undefined, row]) : observations && typeof observations === 'object' ? Object.entries(observations) : [];
    for (const [key, row] of entries) {
      if (!row || typeof row !== 'object') continue;
      const id = ridgeId(row.ridge_id ?? key);
      if (id === null || (hasDeclaredCoverage && !declaredCoverage.has(id))) continue;
      if (records.has(id)) duplicates.add(id);
      // Last entry wins, including an unavailable value. Never average records
      // or resurrect a preceding measurement after a later missing entry.
      records.set(id, row);
    }
  }
  const observedRidges = [...(hasDeclaredCoverage ? declaredCoverage : records.keys())].sort((a, b) => a - b);
  const observed = new Set(observedRidges), values = new Map();
  for (const [id, record] of records) {
    const value = record[field];
    if (typeof value !== 'number' || !Number.isFinite(value) || value === -1 || (!thermal && (value < 0 || value > 1))) continue;
    values.set(id, value);
  }
  const validRidges = [...values.keys()].sort((a, b) => a - b);
  const validCount = validRidges.length, coveredCount = observedRidges.length;
  const hasData = validCount > 0, missingCount = coveredCount - validCount;
  const dataMin = hasData ? Math.min(...values.values()) : null, dataMax = hasData ? Math.max(...values.values()) : null;
  const clippedCount = [...values.values()].filter(value => value < min || value > max).length;
  if (!reason && !hasData) reason = 'no_valid_data';
  const ranges = [];
  for (const id of observedRidges) {
    const last = ranges.at(-1);
    if (last && last[1] === id - 1) last[1] = id; else ranges.push([id, id]);
  }
  const coverage = { start: observedRidges[0] ?? null, end: observedRidges.at(-1) ?? null, ridgeIds: observedRidges, ranges };

  const ndviStops = [[0, '#b92f38'], [.25, '#db743e'], [.5, '#ead46d'], [.7, '#9bc558'], [.85, '#368d4e'], [1, '#105e3a']];
  const temperatureStops = [[0, '#3267b1'], [.25, '#64a9d0'], [.5, '#e4d986'], [.75, '#e58b4b'], [1, '#bd3a38']];
  const palette = thermal ? temperatureStops : ndviStops;
  function colour(value) {
    const t = Math.max(0, Math.min(1, (value - min) / (max - min)));
    let lower = palette[0], upper = palette.at(-1);
    for (let i = 1; i < palette.length; i++) if (t <= palette[i][0]) { lower = palette[i - 1]; upper = palette[i]; break; }
    const fraction = (t - lower[0]) / (upper[0] - lower[0] || 1);
    const rgb = hex => [1, 3, 5].map(position => parseInt(hex.slice(position, position + 2), 16));
    const a = rgb(lower[1]), b = rgb(upper[1]);
    return '#' + a.map((channel, i) => Math.round(channel + (b[i] - channel) * fraction).toString(16).padStart(2, '0')).join('');
  }
  let hash = 2166136261;
  for (const char of `${farmId}|${sequence}|${layer}|${contrast}`) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619) >>> 0;
  const uid = `survey-${hash.toString(16)}`;
  const fixed = value => Number(value.toFixed(2));
  // Oblique projection of a long rectangular plot. It retains the supplied
  // aspect ratio over normal farm dimensions; extreme inputs are bounded to
  // keep this labelled schematic within its standalone export frame.
  const acrossSize = Math.max(12, Math.min(190, width / length * 640));
  const along = [640, -100], across = [acrossSize * .55, acrossSize * .85];
  const origin = [472 - (along[0] + across[0]) / 2, 218 - (along[1] + across[1]) / 2];
  const point = (u, v, down = 0) => [fixed(origin[0] + along[0] * u + across[0] * v), fixed(origin[1] + along[1] * u + across[1] * v + down)];
  const points = rows => rows.map(p => p.join(',')).join(' ');
  const contour = points([point(0, 0), point(1, 0), point(1, 1), point(0, 1)]);
  const bands = Array.from({ length: count }, (_, id) => {
    const valid = values.has(id), status = valid ? 'valid' : observed.has(id) ? 'missing' : 'unobserved';
    const value = values.get(id), fill = valid ? colour(value) : status === 'missing' ? `url(#${uid}-missing)` : '#414c50';
    return `<polygon data-ridge-id="${id}" data-status="${status}"${valid ? ` data-value="${value}"` : ''} points="${points([point(0, id / count), point(1, id / count), point(1, (id + 1) / count), point(0, (id + 1) / count)])}" fill="${fill}" stroke="#192326" stroke-width="0.38"><title>Ridge ${id}: ${valid ? `${thermal ? 'Canopy temperature' : 'NDVI'} ${value}${thermal ? ' °C' : ''}` : status === 'missing' ? 'Observed; measurement unavailable' : 'Not observed'}</title></polygon>`;
  }).join('');
  const tickRows = count ? [...new Set([0, Math.floor((count - 1) / 4), Math.floor((count - 1) / 2), Math.floor((count - 1) * 3 / 4), count - 1])] : [];
  const rowTicks = tickRows.map(id => {
    const p = point(0, (id + .5) / count);
    return `<path d="M${p[0] - 9} ${p[1]}h6" stroke="#9ba7a9" stroke-width=".8"/><text x="${p[0] - 14}" y="${p[1] + 4}" text-anchor="end" fill="#b1bdbd" font-size="10" font-family="monospace">${String(id).padStart(2, '0')}</text>`;
  }).join('');
  const coverageText = coveredCount ? `${coveredCount} / ${count} ridges observed · ${validCount} valid` : `0 / ${count} ridges observed`;
  const rangeText = ranges.length ? ranges.slice(0, 5).map(([start, end]) => start === end ? `${start}` : `${start}–${end}`).join(', ') + (ranges.length > 5 ? ', …' : '') : 'None';
  const scaleText = detail ? 'Enhanced contrast · Fixed 0.75–0.90 scale' : thermal ? 'Fixed 0–45 °C scale' : 'Fixed 0–1 NDVI scale';
  const legendTicks = thermal ? [0, 15, 30, 45] : detail ? [.75, .80, .85, .90] : [0, .25, .50, .75, 1];
  const reasonText = ({ failed_event: 'Failed tool event · No observations displayed', wrong_farm: 'Event does not belong to this farm plot', wrong_tool: 'This event is not a drone survey', no_valid_data: 'Missing values are shown as unavailable' })[reason] || '';
  const emptyNotice = !hasData ? `<g><rect x="292" y="192" width="360" height="70" rx="6" fill="#152025" fill-opacity=".94" stroke="#66757a"/><text x="472" y="220" text-anchor="middle" fill="#f1f5f4" font-size="21" font-weight="600">${thermal ? 'No valid canopy temperature' : 'No valid NDVI'}</text><text x="472" y="244" text-anchor="middle" fill="#acb9bc" font-size="11">${reasonText}</text></g>` : '';
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 460" width="960" height="460" role="img" aria-labelledby="${uid}-title ${uid}-desc" data-layer="${layer}" data-contrast="${contrast}" data-valid-count="${validCount}">
<title id="${uid}-title">${escape(title)} · ${stepLabel}</title><desc id="${uid}-desc">${sourceResolution}. ${coverageText}. Uniform colour along each ridge. Unobserved ridges are grey. ${scaleText}. Derived visualization; not a captured image. Schematic orientation, not GPS.</desc>
<defs><linearGradient id="${uid}-scale" x1="0" y1="0" x2="1" y2="0">${palette.map(([stop, color]) => `<stop offset="${stop * 100}%" stop-color="${color}"/>`).join('')}</linearGradient><pattern id="${uid}-missing" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(32)"><rect width="6" height="6" fill="#414c50"/><path d="M0 0v6" stroke="#6b777a" stroke-width="1.7"/></pattern></defs>
<rect width="960" height="460" rx="8" fill="#202b30"/>
<g font-family="Arial,Helvetica,sans-serif"><text x="42" y="35" fill="#f0f4f2" font-size="21" font-weight="600">${escape(title)}</text><text x="42" y="59" fill="#aab8bc" font-size="11">${escape(actor)} · ${stepLabel}${date ? ` · ${escape(date)}` : ''}</text><text x="916" y="31" text-anchor="end" fill="${detail ? '#e8d28d' : '#b8c7ca'}" font-size="11" font-weight="600">${scaleText}</text><text x="916" y="51" text-anchor="end" fill="#9aabaf" font-size="10">${coverageText}</text>
<polygon points="${points([point(0, 1), point(1, 1), point(1, 1, 9), point(0, 1, 9)])}" fill="#111c20"/><polygon points="${points([point(1, 0), point(1, 1), point(1, 1, 9), point(1, 0, 9)])}" fill="#162227"/>
${bands}<path d="M${point(0, 0).join(' ')}L${point(1, 0).join(' ')}L${point(1, 1).join(' ')}L${point(0, 1).join(' ')}Z" fill="none" stroke="#b3c0be" stroke-width="1.2"/>
${rowTicks}${emptyNotice}
<text x="42" y="356" fill="#bdc9ca" font-size="10">Observed ridge IDs: ${escape(rangeText)}</text><text x="916" y="356" text-anchor="end" fill="#9fadaf" font-size="10">${fixed(length)} × ${fixed(width)} m · ${count} ridges</text>
<text x="42" y="380" fill="#e0e7e4" font-size="11" font-weight="600">${thermal ? 'Canopy temperature (°C)' : 'NDVI (dimensionless)'}</text><rect x="42" y="389" width="400" height="10" rx="2" fill="url(#${uid}-scale)"/>
${legendTicks.map(value => { const x = 42 + (value - min) / (max - min) * 400; return `<path d="M${fixed(x)} 401v4" stroke="#b1bebf"/><text x="${fixed(x)}" y="419" text-anchor="middle" fill="#bdc9ca" font-size="10">${thermal ? value : Number(value).toFixed(2)}</text>`; }).join('')}
<rect x="500" y="389" width="15" height="10" fill="#414c50" stroke="#839195" stroke-width=".6"/><text x="523" y="398" fill="#b7c3c5" font-size="10">Not observed</text><rect x="642" y="389" width="15" height="10" fill="url(#${uid}-missing)" stroke="#839195" stroke-width=".6"/><text x="665" y="398" fill="#b7c3c5" font-size="10">Unavailable value</text><text x="500" y="419" fill="#a1b2b5" font-size="10">${clippedCount ? `${clippedCount} value${clippedCount === 1 ? '' : 's'} outside scale` : ''}</text>
</g></svg>`;
  const safeFilename = value => String(value).replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 70) || 'survey';
  const filename = `${safeFilename(farmId || 'farm-plot')}-${safeFilename(actor)}-step-${sequence ?? 'unknown'}-${layer}${detail ? '-detail' : ''}.svg`;
  return { svg, layer, title, unit, min, max, validCount, coveredCount, hasData, coverage, filename, contrast,
    dataMin, dataMax, missingCount, unobservedCount: count - coveredCount, observedRidges, validRidges,
    duplicateRidges: [...duplicates].sort((a, b) => a - b), clippedCount, reason, sourceResolution, numRidges: count,
    scaleLabel: scaleText, isCapturedImage: false };
}
