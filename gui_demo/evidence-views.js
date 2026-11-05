import {buildSurveyMap} from './survey-map.js';
/** Deterministic, code-native illustrations. No photographs or inferred diagnoses. */
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const finite = value => typeof value === 'number' && Number.isFinite(value);
const clamp = (value, low = 0, high = 1) => Math.max(low, Math.min(high, value));
const fmt = (value, digits = 3) => finite(value) ? value.toFixed(digits) : 'Not recorded';
const mean = values => values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
const hash = text => [...String(text)].reduce((value, char) => ((value * 31) + char.charCodeAt(0)) >>> 0, 7).toString(36);
const cropOf = farm => ['soybean', 'maize'].includes(farm?.crop_id) ? farm.crop_id : null;
const cropName = crop => crop === 'soybean' ? 'Soybean' : crop === 'maize' ? 'Maize' : 'Crop unknown';
const safeObject = value => {
  if (typeof value === 'string') { try { value = JSON.parse(value); } catch { return {}; } }
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
};

function timestamp(value) {
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}:\d{2})(?::[\d.]+)?(Z|[+-]\d{2}:?\d{2})?/);
  if (!match) return value ? String(value) : 'Timestamp not recorded';
  const month = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][Number(match[2]) - 1];
  return `${Number(match[3])} ${month} ${match[1]} · ${match[4]}${match[5] ? ` UTC${match[5] === 'Z' ? '' : match[5]}` : ''}`;
}

function growthState(ridge, crop) {
  const code = String(ridge?.growth_stage || '').toUpperCase();
  if (ridge?.harvested === true) return { key: 'harvested', label: 'Harvested', code };
  if (ridge?.planted === false || code === 'NOT_PLANTED') return { key: 'unplanted', label: 'Not planted', code };
  if (code === 'PLANTED_PRE_EMERGENCE' || (ridge?.planted === true && ['BARE', 'SOWN'].includes(code))) return { key: 'sown', label: 'Before emergence', code };
  if (!crop || !code) return { key: 'unknown', label: 'Growth state unknown', code };
  if (crop === 'maize' && /^VT(?:_|$)/.test(code)) return { key: 'vegetative', label: 'Tasseling', code, tasseling: true };
  if ((crop === 'soybean' && /^R[78]/.test(code)) || (crop === 'maize' && /^R6/.test(code))) return { key: 'maturity', label: 'Maturity', code };
  if (/^R[1-6]/.test(code)) return { key: 'reproductive', label: 'Reproductive', code };
  if (/^(VE|VC|V[12])(?:_|$)/.test(code)) return { key: 'seedling', label: 'Seedling', code };
  if (/^V\d+/.test(code)) return { key: 'vegetative', label: 'Vegetative', code };
  return { key: 'unknown', label: 'Growth state unknown', code };
}

const SPOTS = [[-5, -15, 2.2], [5, -26, 2.6], [-4, -35, 1.8], [9, -18, 1.8], [-10, -25, 2.1], [1, -43, 1.4], [1, -21, 1.6], [7, -34, 1.5], [-6, -23, 1.3], [3, -12, 1.3]];
function broadLeaf(x, y, angle, scale, fill, marks = 0, opacity = 1) {
  return `<g transform="translate(${x} ${y}) rotate(${angle}) scale(${scale})" opacity="${opacity}">
    <path d="M0 0C-15-5-25-29 0-51C25-29 15-5 0 0Z" fill="${fill}" stroke="#4f633f" stroke-opacity=".23" stroke-width=".8"/>
    <path d="M0-2V-45M0-15-10-24M0-26-10-33M0-19 10-28M0-32 7-39" fill="none" stroke="#e0e8bf" stroke-opacity=".4" stroke-width=".8"/>
    ${SPOTS.slice(0, marks).map(([sx, sy, radius]) => `<circle cx="${sx}" cy="${sy}" r="${radius + .8}" fill="#c5a768" opacity=".7"/><circle cx="${sx}" cy="${sy}" r="${radius}" fill="#80634b" opacity=".8"/>`).join('')}
  </g>`;
}

function maizeLeaf(x, y, direction, length, droop, fill, marks = 0) {
  const endY = -length * .33 + droop * length * .66;
  const d = `M0 0C${length * .22} -29 ${length * .65} -46 ${length} ${endY}C${length * .62} ${-21 + droop * 26} ${length * .2} 10 0 0Z`;
  return `<g transform="translate(${x} ${y}) scale(${direction} 1)"><path d="${d}" fill="${fill}" stroke="#657143" stroke-opacity=".22" stroke-width=".8"/>
    <path d="M0 0C${length * .26} -13 ${length * .67} ${-30 + droop * 25} ${length} ${endY}" fill="none" stroke="#dce3ad" stroke-opacity=".5" stroke-width="1"/>
    ${Array.from({ length: marks }, (_, i) => `<ellipse cx="${length * (.22 + i * .055)}" cy="${-12 - i * 1.5 + droop * 5}" rx="2.2" ry=".85" fill="#92764d" opacity=".8"/>`).join('')}</g>`;
}

function soybeanPlant(growth, droop, marks, uid) {
  const small = growth.key === 'seedling', mature = growth.key === 'maturity';
  const height = small ? 58 : growth.key === 'vegetative' ? 124 : 181;
  const top = 278 - height, leafFill = mature ? `url(#${uid}-gold)` : `url(#${uid}-leaf)`;
  let svg = `<path d="M240 281C${238 + droop * 4} 227 244 ${top + 28} 240 ${top}" stroke="${mature ? '#93825b' : '#72864d'}" stroke-width="${small ? 3 : 4.6}" fill="none" stroke-linecap="round"/>`;
  if (small) {
    svg += broadLeaf(240, 250, -53 - droop * 22, .55, leafFill, marks);
    svg += broadLeaf(240, 246, 55 + droop * 22, .58, leafFill, marks);
    svg += broadLeaf(240, top + 8, 7, .34, leafFill, Math.min(marks, 2));
    return svg;
  }
  const levels = growth.key === 'vegetative' ? [0.27, .58, .87] : [.2, .42, .65, .88];
  for (const [i, level] of levels.entries()) {
    const y = 278 - height * level, side = i % 2 ? 1 : -1;
    const jointX = 240 + side * (29 + (1 - level) * 20), jointY = y - 15 + droop * 23;
    svg += `<path d="M240 ${y + 12}Q${240 + side * 21} ${y - 9} ${jointX} ${jointY}" stroke="${mature ? '#9c875a' : '#7a8e50'}" stroke-width="2" fill="none"/>`;
    const scale = .77 + (1 - level) * .18;
    svg += broadLeaf(jointX, jointY, side * (16 + droop * 22), scale, leafFill, marks);
    svg += broadLeaf(jointX, jointY, -60 - droop * 28, scale * .83, leafFill, Math.max(0, marks - 1));
    svg += broadLeaf(jointX, jointY, 63 + droop * 28, scale * .83, leafFill, Math.max(0, marks - 2));
    if (growth.key === 'reproductive' || mature) {
      if (/^R[12]/.test(growth.code)) {
        svg += `<g fill="#b8a2ba"><circle cx="${jointX - 3}" cy="${jointY + 8}" r="3"/><circle cx="${jointX + 2}" cy="${jointY + 9}" r="2.7"/><circle cx="${jointX}" cy="${jointY + 5}" r="2.6"/></g>`;
      } else {
        svg += `<g transform="translate(${240 + side * 9} ${y + 8}) rotate(${-side * 16})" fill="${mature ? '#b29b70' : '#8ca460'}" stroke="${mature ? '#947e58' : '#738c4c'}" stroke-width=".8"><path d="M0 0C-8 6-8 25-1 30C5 21 7 7 0 0Z"/><path d="M7 3C2 11 5 26 11 29C16 19 14 10 7 3Z"/></g>`;
      }
    }
  }
  return svg;
}

function maizePlant(growth, droop, marks, uid) {
  const small = growth.key === 'seedling', mature = growth.key === 'maturity';
  const height = small ? 57 : growth.key === 'vegetative' && !growth.tasseling ? 158 : 222, top = 280 - height;
  let svg = `<path d="M240 281Q243 166 240 ${top}" fill="none" stroke="${mature ? '#a28e53' : '#82965c'}" stroke-width="${small ? 3 : 7}" stroke-linecap="round"/>`;
  const levels = small ? [.24, .57, .9] : [.15, .28, .42, .56, .69, .81, .91];
  levels.forEach((level, index) => {
    const y = 279 - level * height, direction = index % 2 ? 1 : -1;
    const length = small ? 36 - index * 5 : 105 - level * 48;
    svg += maizeLeaf(240, y, direction, length, droop + (mature ? .15 : 0), mature ? `url(#${uid}-gold)` : `url(#${uid}-leaf)`, marks);
    if (!small) svg += `<path d="M236 ${y}h8" stroke="#b7c18a" stroke-width="2"/>`;
  });
  if (growth.tasseling || growth.key === 'reproductive' || mature) {
    svg += `<g class="ev-tassel" transform="translate(240 ${top + 6})" fill="none" stroke="${mature ? '#aa975e' : '#a5ab6b'}" stroke-width="1.5" stroke-linecap="round"><path d="M0 9V-24M0-12-15-23M0-7 15-22M0 0-20-10M0 4 18-9"/><path d="M-15-23-17-29M15-22 17-28M-20-10-23-14M18-9 22-13"/></g>`;
  }
  if (growth.key === 'reproductive' || mature) {
    svg += `<g class="ev-ear" transform="translate(243 ${top + 106}) rotate(-20)"><path d="M0 0Q-13 8-7 45Q1 46 7 5Z" fill="${mature ? '#c6ad66' : '#a3ae66'}"/><path d="M0 1Q0 24-7 45Q-18 20-9 12Z" fill="${mature ? '#b19b62' : '#7d9752'}"/><path d="M1 2Q6-8 3-16M3 3Q12-3 10-12" fill="none" stroke="#b89a74" stroke-width="1.1"/></g>`;
  }
  return svg;
}

function plantSVG({ crop, growth, rootVwc, pressure, surfaceVwc, step, ridgeId, farmId, stand }) {
  const uid = `ev-${hash(`${crop}|${farmId}|${ridgeId}|${step}|${growth.key}`)}`;
  // Pure visual mappings, deliberately not agronomic thresholds or symptom claims.
  const droop = finite(rootVwc) ? clamp((.35 - rootVwc) / .25) : 0;
  const marks = finite(pressure) ? Math.round(clamp(pressure) * 16) : 0;
  const empty = finite(stand) && stand <= 0 && !['unplanted', 'sown', 'harvested'].includes(growth.key);
  let plant = '';
  if (growth.key === 'harvested') {
    plant = `<g stroke="#a08b63" stroke-width="5" stroke-linecap="round"><path d="M240 282V255M238 270 223 258M242 273 257 262"/></g><path d="M218 288l-19-7m57 9 21-6m-38 8 10 3" stroke="#c7b68f" stroke-width="3" stroke-linecap="round"/>`;
  } else if (growth.key === 'sown') {
    plant = `<path d="M209 282q31-13 62 0" fill="none" stroke="#bba786" stroke-width="4"/><ellipse cx="240" cy="288" rx="5.5" ry="3" fill="#d4bd89"/><path d="M218 275h44" stroke="#c1b495" stroke-width="1.4" stroke-dasharray="2 4"/>`;
  } else if (growth.key === 'unknown' || !crop || empty) {
    plant = `<path d="M240 275v-95m0 51q-36-3-46-32 40-1 46 32m0-23q34-8 40-36-36 3-40 36" fill="none" stroke="#c7cfd2" stroke-width="2" stroke-dasharray="4 5"/><circle cx="240" cy="158" r="15" fill="#f5f7f7"/><text x="240" y="163" text-anchor="middle" font-family="sans-serif" font-size="14" fill="#89969d">?</text>`;
  } else if (growth.key !== 'unplanted') {
    plant = crop === 'soybean' ? soybeanPlant(growth, droop, marks, uid) : maizePlant(growth, droop, marks, uid);
  }
  const soil = finite(surfaceVwc) && surfaceVwc >= .28 ? '#b4a58b' : '#c8b797';
  return `<svg class="ev-plant-svg" viewBox="0 0 480 328" role="img" aria-label="${escape(`${cropName(crop)} ${growth.label.toLowerCase()} schematic; not a photograph or observed leaf symptoms`)}">
    <defs><linearGradient id="${uid}-leaf" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#a5b976"/><stop offset=".5" stop-color="#799455"/><stop offset="1" stop-color="#5e7b42"/></linearGradient><linearGradient id="${uid}-gold"><stop stop-color="#c7ba76"/><stop offset="1" stop-color="#9f955b"/></linearGradient><radialGradient id="${uid}-back"><stop stop-color="#f5f7f7"/><stop offset="1" stop-color="#fcfcfc"/></radialGradient></defs>
    <rect width="480" height="328" fill="#fcfcfc"/><ellipse cx="240" cy="165" rx="184" ry="149" fill="url(#${uid}-back)"/>
    <path d="M58 283H422" stroke="#e3e7e7"/><ellipse cx="240" cy="284" rx="90" ry="15" fill="#e8e5d9"/><ellipse cx="240" cy="284" rx="63" ry="9" fill="${soil}" opacity=".7"/>
    ${plant}<text x="240" y="313" text-anchor="middle" fill="#89969d" font-family="inherit" font-size="10" letter-spacing="1.4">${escape(empty ? 'NO SURVIVING STAND RECORDED' : growth.key === 'unplanted' ? 'BEFORE PLANTING' : growth.key === 'sown' ? 'SEED SOWN · NOT YET EMERGED' : growth.key === 'unknown' || !crop ? 'PHYSICAL APPEARANCE NOT KNOWN' : 'ILLUSTRATED PLANT · NOT TO SCALE')}</text>
  </svg>`;
}

function observationFor(observations, farm, ridge) {
  let value = observations || {};
  if (value?.[farm?.id]) value = value[farm.id];
  if (value?.[ridge?.ridge_id]) value = value[ridge.ridge_id];
  return safeObject(value);
}

/** Snapshot fields drive shape. Optional acquired observations are listed separately. */
export function plantEvidence({ farm = {}, ridge = {}, observations = {}, step = null, illustration = null, source = 'example' } = {}) {
  farm = safeObject(farm); ridge = safeObject(ridge);
  const crop = cropOf(farm), growth = growthState(ridge, crop), obs = observationFor(observations, farm, ridge);
  const detected = typeof obs.disease?.value === 'boolean' ? obs.disease.value : typeof obs.disease_present === 'boolean' ? obs.disease_present : null;
  const confidence = obs.disease?.confidence ?? obs.disease_confidence;
  const soilObservation = obs.moisture?.value;
  const hasObservation = detected !== null || finite(soilObservation);
  const water = finite(ridge.root_vwc) ? `${fmt(ridge.root_vwc)} m³/m³` : 'Unknown';
  const pressure = finite(ridge.disease_pressure) ? fmt(ridge.disease_pressure) : 'Unknown';
  const record = Number.isInteger(step) ? `Step ${step}` : 'Step not supplied';
  const illustrationUrl = typeof illustration?.url === 'string' && /^(?:https?:\/\/|assets\/media\/simulated\/)[^\s<>"']+$/i.test(illustration.url) ? illustration.url : null;
  const canIllustrate = illustrationUrl && !['unplanted','sown','harvested','unknown'].includes(growth.key) && !(finite(ridge.stand_fraction) && ridge.stand_fraction <= 0);
  const showIllustration = canIllustrate && source === 'example';
  return `<section class="ev-card ev-plant" data-evidence="plant" data-growth="${growth.key}" aria-label="Plant illustration">
    <header class="ev-head"><div><h3>Plant illustration</h3><p>${showIllustration?'AI-generated simulation example':'Schematic · Recorded ridge state'}</p></div><span class="ev-record">${record}</span></header>
    <div class="ev-identity"><strong>${escape(cropName(crop))}</strong><span>${escape(farm.label || farm.id || 'Farm plot not supplied')} · ${Number.isInteger(ridge.ridge_id) ? `Ridge ${ridge.ridge_id}` : 'Ridge unknown'}</span></div>
    ${canIllustrate?`<div class="ev-map-sources"><button data-plant-source="example" class="${showIllustration?'selected':''}">Simulated image</button><button data-plant-source="schematic" class="${!showIllustration?'selected':''}">State schematic</button></div>`:''}
    <div class="ev-art"><span class="ev-stage">${escape(growth.label)}${growth.code && !['BARE', 'PLANTED_PRE_EMERGENCE'].includes(growth.code) ? ` · ${escape(growth.code)}` : ''}</span>${showIllustration?`<a class="ev-plant-open" href="${escape(illustrationUrl)}" target="_blank" rel="noopener noreferrer" aria-label="Open full-size simulated plant image"><img class="ev-plant-image" data-plant-example="${escape(illustration.id)}" src="${escape(illustrationUrl)}" alt="${escape(illustration.title)}"><span>Open full-size image ↗</span></a>`:plantSVG({ crop, growth, rootVwc: ridge.root_vwc, pressure: ridge.disease_pressure, surfaceVwc: ridge.soil_vwc, step, ridgeId: ridge.ridge_id, farmId: farm.id, stand: ridge.stand_fraction })}</div>
    <dl class="ev-metrics"><div><dt>Root-zone VWC</dt><dd>${water}</dd></div><div><dt>Disease pressure</dt><dd>${pressure}<small>${finite(ridge.disease_pressure) ? 'model index' : 'not recorded'}</small></dd></div></dl>
    <p class="ev-caption">${showIllustration?escape(illustration.caption)+' Numeric metrics remain recorded values.':'Leaf marks encode disease pressure; leaf angle encodes root-zone moisture. These are display cues, not observed symptoms or a measured wilt score.'}</p>
    ${!finite(ridge.root_vwc) || !finite(ridge.disease_pressure) ? '<p class="ev-missing">Missing stress values are not rendered as confirmed healthy conditions.</p>' : ''}
    ${hasObservation ? `<details class="ev-observations"><summary>Acquired evidence · separate from illustration</summary><dl class="ev-metrics">${finite(soilObservation) ? `<div><dt>Surface-probe VWC</dt><dd>${fmt(soilObservation)}<small>${escape(timestamp(obs.moisture.datetime))}</small></dd></div>` : ''}${detected !== null ? `<div><dt>Recorded ground detection</dt><dd>${detected ? 'Present' : 'Not detected'}<small>${finite(confidence) ? `Confidence ${fmt(confidence)}` : 'Confidence not recorded'}</small></dd></div>` : ''}</dl></details>` : ''}
  </section>`;
}

/** A legend for a generated example, never a claim of radiometric calibration. */
export function illustrativeNDVILegend(){return `<div class="ev-example-legend"><div><strong>NDVI · illustrative palette</strong><span>Simulated example</span></div><i></i><div class="ev-example-ticks"><span>0.00</span><span>0.25</span><span>0.50</span><span>0.75</span><span>1.00</span></div><p>Synthetic spatial pattern · Pixels are not measured NDVI values</p></div>`;}

function ranges(ids) {
  if (!ids.length) return 'None recorded';
  const groups = []; let start = ids[0], end = start;
  for (const value of ids.slice(1)) { if (value === end + 1) end = value; else { groups.push(start === end ? `${start}` : `${start}–${end}`); start = end = value; } }
  groups.push(start === end ? `${start}` : `${start}–${end}`); return groups.join(', ');
}

/** Uses only returned survey rows. NDVI -1 is the source model's no-reading sentinel. */
export function surveyEvidence({ event = {}, farm = {}, layer = 'ndvi', contrast = 'standard', example = null, source = 'recorded' } = {}) {
  event = safeObject(event); farm = safeObject(farm);
  const result = safeObject(event.result), sourceFarm = result.farm_id || event.arguments?.farm_id || null;
  const mismatch = Boolean(sourceFarm && farm.id && sourceFarm !== farm.id);
  const crop = mismatch ? null : cropOf(farm), actor = String(event.tool_name || '').split('__')[0];
  const rejected = Boolean(event.error || result.error || ['failed', 'error'].includes(event.status) || ['failed', 'error'].includes(result.status));
  const rawRows = Array.isArray(result.observations) ? result.observations : Object.values(safeObject(result.observations));
  const validId=id=>Number.isInteger(id)&&id>=0&&(!Number.isInteger(farm.num_ridges)||id<farm.num_ridges);
  const declared = Array.isArray(result.surveyed_ridges) ? new Set(result.surveyed_ridges.filter(validId)) : null;
  const byRidge = new Map((rejected||mismatch ? [] : rawRows).filter(row => row && validId(row.ridge_id) && (!declared || declared.has(row.ridge_id))).map(row=>[row.ridge_id,row]));
  const rows = [...byRidge.values()].sort((a,b)=>a.ridge_id-b.ridge_id);
  const covered = rejected||mismatch ? [] : declared ? [...declared].sort((a,b)=>a-b) : [...byRidge.keys()];
  const ndviValid = value => finite(value) && value >= 0 && value <= 1;
  const ndvis = rows.map(row => row.ndvi).filter(ndviValid), temperatures = rows.map(row => row.canopy_temp_c).filter(finite);
  const thermal = layer === 'temperature';
  const map = buildSurveyMap(event, farm, {layer,contrast});
  const exampleUrl = typeof example?.url === 'string' && /^(?:https?:\/\/|data:image\/(?:png|jpeg|webp);base64,)/i.test(example.url) ? example.url : null;
  const canShowExample = !thermal && map.hasData && !rejected && !mismatch && ndvis.length > 0 && exampleUrl && example.survey_sequence === event.sequence && example.farm_id === farm.id;
  const showExample = source === 'example' && canShowExample;
  const fieldCount = !mismatch && Number.isInteger(farm.num_ridges) && farm.num_ridges > 0 ? farm.num_ridges : null;
  const formatNDVI = value => value === -1 ? 'No reading (−1)' : ndviValid(value) ? String(value) : 'Not recorded';
  const label = mismatch ? sourceFarm : farm.label || sourceFarm || 'Farm plot not recorded';
  return `<section class="ev-card ev-survey" data-evidence="survey" aria-label="Survey result">
    <header class="ev-head"><div><h3>Survey result</h3><p>NDVI and canopy-temperature observations</p></div><span class="ev-record">${Number.isInteger(event.sequence) ? `Step ${event.sequence}` : 'No event'}</span></header>
    <div class="ev-identity"><strong>${escape(actor || 'Survey device')}</strong><span>${escape(label)}</span></div>
    <div class="ev-map-controls"><label>Map layer<select id="survey-layer" aria-label="Survey map layer"><option value="ndvi" ${!thermal?'selected':''}>NDVI</option><option value="temperature" ${thermal?'selected':''}>Canopy temperature</option></select></label>${!thermal?`<label>Color scale<select id="survey-contrast" aria-label="NDVI color scale" ${showExample?'disabled':''}><option value="standard" ${contrast!=='detail'?'selected':''}>Standard · 0–1</option><option value="detail" ${contrast==='detail'?'selected':''}>Detail · 0.75–0.90</option></select></label>`:''}</div>
    ${canShowExample?`<div class="ev-map-sources"><button data-survey-source="recorded" class="${!showExample?'selected':''}">Recorded ridge map</button><button data-survey-source="example" class="${showExample?'selected':''}">Illustrative image</button></div>`:''}
    <button class="ev-map-open" data-action="expand-survey-map" aria-label="Enlarge survey map" title="Open a larger view">${showExample?`<img class="ev-example-image" data-example-id="${escape(example.id)}" src="${escape(exampleUrl)}" alt="${escape(example.caption||'Illustrative NDVI map')}" referrerpolicy="no-referrer"><span class="ev-example-label">Illustrative NDVI map</span>`:map.svg}<span class="ev-map-expand">Enlarge ↗</span></button>
    ${showExample?illustrativeNDVILegend():''}
    <p class="ev-caption ev-map-caption">${showExample?`Illustrative NDVI map · ${escape(example.caption||example.title||'External example')}<br>Example imagery is independent of the recorded ridge values below.`:map.hasData?'One returned value per ridge; gray areas have no valid reading. Along-ridge patches and GPS positions are not supplied.':thermal?'No valid canopy-temperature readings are available for this survey.':'No valid NDVI · Canopy appearance is unknown. Missing readings are not interpreted as low NDVI.'}${!showExample&&!thermal&&contrast==='detail'?'<br>Enhanced contrast uses the same 0.75–0.90 scale for every survey. Red means lower within this range, not confirmed disease.':''}</p>
    ${!showExample?`<div class="ev-map-download"><a href="data:image/svg+xml;charset=utf-8,${encodeURIComponent(map.svg)}" download="${escape(map.filename)}">Download map SVG</a><span>${map.validCount} valid ridges · ${map.min}–${map.max}${thermal?' °C':''}</span></div>`:''}
    ${mismatch ? '<p class="ev-missing">Plot metadata does not match the returned survey. Crop appearance is left unknown.</p>' : ''}
    <div class="ev-acquired">${escape(timestamp(event.datetime_after))}<span>${rejected ? 'Survey failed' : result.status === 'partial' ? 'Partial survey' : rows.length ? 'Recorded tool response' : 'No survey values available'}</span></div>
    <dl class="ev-metrics"><div><dt>Mean valid NDVI</dt><dd>${ndvis.length ? fmt(mean(ndvis)) : 'Unknown'}<small>${ndvis.length} valid readings</small></dd></div><div><dt>Mean canopy temperature</dt><dd>${temperatures.length ? `${fmt(mean(temperatures), 1)} °C` : 'Unknown'}<small>${temperatures.length} recorded readings</small></dd></div></dl>
    <div class="ev-coverage"><strong>${declared ? 'Surveyed ridges' : 'Returned ridge values'}</strong><span>${covered.length}${fieldCount ? ` / ${fieldCount}` : ''} · ${escape(ranges(covered))}</span></div>
    ${rows.length ? `<details class="ev-values"><summary>Exact returned values · ${rows.length} ridges</summary><div class="ev-table-scroll"><table><thead><tr><th>Ridge</th><th>NDVI</th><th>Canopy °C</th></tr></thead><tbody>${rows.map(row => `<tr><th>${row.ridge_id}</th><td>${formatNDVI(row.ndvi)}</td><td>${finite(row.canopy_temp_c) ? escape(row.canopy_temp_c) : 'Not recorded'}</td></tr>`).join('')}</tbody></table></div></details>` : ''}
    <p class="ev-caption ev-bottom-note">Values and coverage come from this tool response. No disease diagnosis, plant count or confidence score has been inferred from the illustration.</p>
  </section>`;
}
