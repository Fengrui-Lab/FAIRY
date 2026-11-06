import {FAIRY_LOGO} from '../../brand-logo.js';
import {escapeHTML as esc, dateLabel, number} from '../../data-model.js';
import {createHitScene} from './scene.js';
import {getHitMotion} from './motion.js';
import {mountHitWorkflow} from './workflow.js';
import {resultMarkup, mountResults} from './results.js';

const $ = (q, root = document) => root.querySelector(q);
const CATEGORY = {equipment: 'Equipment operations', processing: 'Image processing', presentation: 'Result presentation'};
const PROCESSING_ASSETS = {identify_crop_type:'processingClassify',post_process_results:'processingPostprocess',raw_images_to_visible_orthomosaic:'orthomosaic',identify_field_distribution:'processingFields'};
const paths = {
  farm:'M3 8h18M3 13h18M3 18h18M7 5v16M17 5v16', agent:'M5 5h5v5H5zM14 14h5v5h-5zM8 10v6h6M10 7h7v7',
  grid:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z', cube:'m12 3 9 5-9 5-9-5 9-5Zm-9 5v9l9 5 9-5V8M12 13v9',
  close:'m6 6 12 12M18 6 6 18', reset:'M3 10a9 9 0 1 1 2 9M3 4v6h6', leaf:'M12 21V10M12 15C4 15 3 9 3 4c7 0 10 3 9 11ZM12 11c0-6 5-8 9-8 0 5-3 9-9 9',
  timeline:'M3 12h18M6 8v8M12 5v14M18 8v8', camera:'M3 7h4l2-3h6l2 3h4v13H3V7Zm9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8',
  drone:'m7 7 10 10M7 17 10 7M3 5h8M13 5h8M3 19h8M13 19h8M8 9h8v6H8z', satellite:'m10 7 7 7-4 4-7-7 4-4ZM2 4l4-3 4 4-4 4-4-5ZM15 16l4-4 4 4-4 4-4-4ZM16 3a5 5 0 0 1 5 5M16 6a2 2 0 0 1 2 2',
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.farm}"/></svg>`;
const params = rows => `<div class="params">${rows.map(([key,value]) => `<div><small>${esc(key)}</small><b>${esc(String(value))}</b></div>`).join('')}</div>`;
const json = value => esc(JSON.stringify(value, null, 2));
const assetUrl = path => new URL(path, import.meta.url).href;
const state = {view:'farms', dimension:'2d', step:8, layer:'natural', pip:null, tool:null, pinned:null, progress:1};
let data, scene, graph, miniScene, pipResults, previewResults, previewEvent, previewAnchor;
let motionRaf=0, previewRaf=0, playTimer=0, playing=false;
const frame = (step=state.step) => data.frames[step];
const phaseLabel = phase => ({standby:'Standby', docked:'At base', departing:'Outbound', scanning:'Scanning', returning:'Returning'})[phase] || phase;
const datetime = () => frame().datetime;
const cropName = crop => ({rice:'Rice',maize:'Maize',soybean:'Soybean',other:'Other'})[crop.id] || crop.label;

async function init() {
  document.body.classList.add('hit-app');
  const response = await fetch(assetUrl('scenario.json'));
  if (!response.ok) throw new Error(`HIT recording: HTTP ${response.status}`);
  data = await response.json();
  if (data.events.length!==8 || data.frames.length!==9 || data.tools.length!==8) throw new Error('The HIT scenario requires eight tools, eight events and nine states.');
  const query = new URL(location.href).searchParams;
  state.step = query.has('step') ? Math.max(0, Math.min(8, Math.trunc(Number(query.get('step')))||0)) : 8;
  state.view = query.get('view')==='agent' ? 'agent' : 'farms';
  state.dimension = query.has('farm') ? '3d' : '2d';
  state.layer = ['natural','satellite','drone'].includes(query.get('layer')) ? query.get('layer') : 'natural';
  guardLayer(); render();
  document.body.dataset.ready = 'true';
  window.HIT_DEMO = {data,state,setStep,render,openDevice,openTool:name=>{state.tool=name;renderDrawer();},replay:()=>animate(true)};
}
function remember() {
  const url = new URL(location.href);
  url.searchParams.set('scenario','hit'); url.searchParams.set('step',state.step); url.searchParams.set('view',state.view); url.searchParams.set('layer',state.layer);
  if (state.dimension==='3d') url.searchParams.set('farm',data.farm.id); else url.searchParams.delete('farm');
  history.replaceState({},'',url);
}
function guardLayer() {
  if ((state.layer==='satellite' && state.step<3) || (state.layer==='drone' && state.step<7)) state.layer='natural';
}
function options(extra={}) { return {data,dimension:state.dimension,step:state.step,layer:state.layer,progress:state.progress,...extra}; }
function clearPreview() {
  cancelAnimationFrame(previewRaf); previewRaf=0; miniScene?.destroy(); miniScene=null;
  previewResults?.destroy(); previewResults=null; previewEvent=null;
  const host=$('#workflow-preview'); if(host) host.hidden=true;
}
function render() {
  scene?.destroy(); graph?.destroy(); scene=graph=null; pipResults?.destroy(); pipResults=null; clearPreview();
  $('#app').innerHTML = `<header class="topbar"><div class="brand"><span class="brand-symbol"><img class="brand-logo" src="${FAIRY_LOGO}" alt="FAIRY logo" width="42" height="42"></span><span class="brand-title">FAIRY<em>2.0</em></span><span class="brand-caption">Intelligent farm management</span></div><label class="scenario"><span>SCENARIO</span><select aria-label="Scenario"><option value="season">Soybean & maize · Disease and water</option><option value="hit" selected>HIT smart farm · Satellite & drone</option></select></label></header>
  <div class="workspace"><aside class="sidebar">${sidebar()}</aside><main class="main ${state.view==='farms'?'farm-view':''}"><div class="view-header"><div><div class="eyebrow">${state.view==='farms'?'FARM MANAGEMENT':'AGENT WORKFLOW'}</div><div class="title-row"><h1>${state.view==='agent'?'Agent workflow':state.dimension==='3d'?'HIT smart farm':'All farm plots'}</h1><span>${state.view==='agent'?'8 tool calls · Satellite then drone':state.dimension==='3d'?'Rice · Maize · Soybean · Other · 3D view':'1 farm plot · Satellite & drone'}</span></div></div><div class="world-time"><small>WORLD TIME · UTC+08</small><strong id="world-time">${dateLabel(datetime())}</strong></div></div>${state.view==='farms'?farmMarkup():agentMarkup()}</main></div><div id="drawer-host"></div>`;
  if (state.view==='farms') {
    scene = createHitScene($('#scene'),options(),picked => {
      if(picked.type==='farm'){state.dimension='3d';state.pip=null;render();}
      else if(picked.type==='device')openDevice(picked.id);
    });
    renderPip();
  } else {
    graph = mountHitWorkflow($('#workflow'),{events:data.events,step:state.step,
      onSelect:event=>{state.pinned=event.sequence;setStep(event.sequence);showPreview(event);},
      onHover:(event,placement)=>{if(!state.pinned)showPreview(event,placement);else positionPreview();}});
    if(state.pinned)showPreview(data.events[state.pinned-1]);
  }
  renderDrawer(); remember();
}
function sidebar() {
  return `<nav class="mode-switch" aria-label="Main view"><button data-view="farms" class="${state.view==='farms'?'active':''}">${icon('farm')}Farm plots</button><button data-view="agent" class="${state.view==='agent'?'active':''}">${icon('agent')}Agent tools</button></nav>${state.view==='farms'?`
    <div class="side-heading"><span>MANAGED FARM PLOTS</span><span>01</span></div><nav class="farm-tabs"><button class="farm-tab ${state.dimension==='2d'?'active':''}" data-dimension="2d"><span class="farm-letter">${icon('grid')}</span><span><strong>All farm plots</strong><small>2D overview</small></span></button><button class="farm-tab ${state.dimension==='3d'?'active':''}" data-dimension="3d"><span class="farm-letter">A</span><span><strong>HIT smart farm</strong><small>Rice · Maize · Soybean · Other</small></span><span class="chevron">›</span></button></nav><div class="side-foot"><strong>One plot. Two perspectives.</strong>8 actions · 9 world states</div>`:
    `<div class="side-heading"><span>SCENARIO TOOLS</span><span>08</span></div><input class="tool-search" id="tool-search" aria-label="Search tools" placeholder="Search tools…"><div class="tool-key"><span>8 tools</span><span>3 categories</span></div><div id="tool-list">${toolList()}</div><div class="side-foot"><strong>Satellite first. Drone next.</strong>Fixed reference workflow with prepared results.<a href="${assetUrl('scenario.json')}" download>Download scenario & schemas ↗</a></div>`}`;
}
function toolList(search='') {
  return Object.entries(CATEGORY).map(([key,label])=>{
    const tools=data.tools.filter(t=>t.category===key && `${t.name} ${t.title}`.toLowerCase().includes(search.toLowerCase()));
    return tools.length?`<section class="tool-group"><h3>${label}</h3>${tools.map(t=>`<button class="tool-button" data-tool="${esc(t.name)}"><b>${esc(t.title)}</b><span>${esc(t.equipment)}</span></button>`).join('')}</section>`:'';
  }).join('') || '<div class="empty-note">No matching tools.</div>';
}
function controls() {
  return `<div class="controls"><div class="field-context">${icon('leaf')}<span>Field conditions</span></div><label class="select-control">Color layer<select id="layer" aria-label="Color layer"><option value="natural" ${state.layer==='natural'?'selected':''}>Natural appearance</option><option value="satellite" ${state.layer==='satellite'?'selected':''} ${state.step<3?'disabled':''}>Satellite · Crop types${state.step<3?' · Step 3':''}</option><option value="drone" ${state.layer==='drone'?'selected':''} ${state.step<7?'disabled':''}>Drone · Rice & lodging${state.step<7?' · Step 7':''}</option></select></label></div>`;
}
function metrics() {
  const rice=data.crops.find(c=>c.id==='rice');
  const rows=[['Farm area',number(data.farm.area_m2/10000,2),'ha','Farm boundary area. 1 ha = 10,000 m².'],['Rice · satellite',state.step>=2?number(rice.area_m2/10000,2):'—','ha · whole farm','Area of pixels classified as rice across the clipped farm raster.'],['Drone survey area',state.step>=4?number(data.roi.area_m2/10000,2):'—','ha · survey footprint','Area of the survey rectangle; includes the image margins and other cover, not just identified rice.'],['Lodging · drone',state.step>=7?number(data.droneMetrics.lodging_percent,2):'—','% · surveyed rice','Lodging area divided by identified rice area within the drone placement.']];
  return rows.map(([label,value,unit,description])=>`<div class="metric" title="${esc(description)}"><small>${label}</small><b>${value}<span>${unit}</span></b></div>`).join('');
}
function farmMarkup() {
  return `${controls()}<div class="metrics" id="metrics">${metrics()}</div><div class="viewport ${state.dimension==='2d'?'overview-mode':''}"><div class="scene-stage" id="scene"></div><div class="viewport-tag">${icon(state.dimension==='3d'?'cube':'grid')}<b>${state.dimension==='3d'?'3D view':'2D overview'}</b></div><div class="view-actions">${state.dimension==='3d'?`<button class="icon-button" data-action="overview" aria-label="Back to overview" title="Back to overview">${icon('grid')}</button>`:''}<button class="icon-button" data-action="reset" aria-label="Reset view" title="Reset view">${icon('reset')}</button></div><div class="north-mark"><i></i>N</div><div id="equipment-tray" class="equipment-tray">${equipmentTray()}</div><div class="scene-note"><b>${state.dimension==='3d'?'Drag to rotate · Scroll to zoom · Click equipment to inspect':'Select the farm for 3D · Click satellite or drone to inspect'}</b></div><div id="legend">${legend()}</div><div id="pip-host"></div></div><div id="timeline-host">${timeline()}</div>`;
}
function equipmentTray() {
  const moving=getHitMotion(data,state.step,state.progress);
  return `<div class="equipment-heading">Equipment<small>Shared</small></div><div class="device-buttons">${moving.map(d=>`<button data-device="${d.id}" class="${d.active?'active':''}">${icon(d.id.toLowerCase())}<span>${d.id}<small data-device-status="${d.id}">${phaseLabel(d.phase)}</small></span></button>`).join('')}</div>${[1,5].includes(state.step)?`<div class="operation-replay"><button data-action="replay-operation">${icon('reset')}Replay operation</button><span id="operation-phase">${phaseLabel(moving.find(d=>d.missionStep===state.step).phase)}</span><progress id="operation-progress" value="${state.progress}" max="1" aria-label="Operation progress"></progress></div>`:''}`;
}
function legend() {
  if(state.layer==='natural')return '';
  const keys=state.layer==='satellite'?data.crops.map(c=>[cropName(c),c.color]):[['Field boundary','#27c5d0'],['Rice','#72a785'],['Lodging','#d96366']];
  return `<div class="legend"><div class="legend-head"><span>${state.layer==='satellite'?'Satellite crop classification':'Drone analysis'}</span></div><div class="hit-crop-key">${keys.map(([label,color])=>`<span><i style="background:${color}"></i>${label}</span>`).join('')}</div></div>`;
}
function timeline() {
  return `<section class="timeline hit-timeline" aria-label="Action timeline"><div class="timeline-top"><div class="timeline-title">${icon('timeline')}Action timeline<small>HIT smart farm · Shared equipment</small></div><div class="timeline-controls"><button data-action="previous" aria-label="Previous action" ${state.step===0?'disabled':''}>‹</button><button data-action="play" aria-label="${playing?'Pause':'Play'} timeline">${playing?'Pause':'Play'}</button><button data-action="next" aria-label="Next action" ${state.step===8?'disabled':''}>›</button><span class="jump-label">Jump to</span><select id="milestone" aria-label="Jump to milestone"><option value="">Choose checkpoint</option><option value="0">Start</option><option value="1">Satellite scan</option><option value="4">Satellite results</option><option value="5">Drone survey</option><option value="8">Drone results</option></select></div></div><div class="timeline-track"><button class="time-chip initial ${state.step===0?'active':''}" data-step="0"><small>Start</small><strong>Initial state</strong></button>${data.events.map(e=>`<button class="time-chip ${state.step===e.sequence?'active':''}" data-step="${e.sequence}" title="${esc(e.title)}" aria-label="Step ${e.sequence}: ${esc(e.title)}"><small>${String(e.sequence).padStart(3,'0')}</small><strong>${esc(e.title)}</strong></button>`).join('')}</div><div class="timeline-bottom"><input type="range" id="cursor" min="0" max="8" step="1" value="${state.step}" aria-label="Global world time step"><span>${state.step} / 8</span></div><div class="timeline-note"><span>${state.step?'Post-operation state · results':'Before the first tool call.'}</span><span class="current-action">${state.step?esc(data.events[state.step-1].title):'Start'}</span></div></section>`;
}
function setStep(value,{autoplay=false}={}) {
  if(!autoplay)stopPlay();
  state.step=Math.max(0,Math.min(8,Math.trunc(Number(value))||0));
  state.progress=1;guardLayer();cancelAnimationFrame(motionRaf);motionRaf=0;
  const time=$('#world-time');if(time)time.textContent=dateLabel(datetime());
  if(state.view==='farms') {
    $('#metrics').innerHTML=metrics();$('.controls').outerHTML=controls();$('#legend').innerHTML=legend();
    $('#timeline-host').innerHTML=timeline();$('#equipment-tray').innerHTML=equipmentTray();
    scene?.update(options());renderPip();
    $('.time-chip.active')?.scrollIntoView({block:'nearest',inline:'nearest'});
  } else { graph?.setStep(state.step); if(state.pinned)showPreview(data.events[state.step-1] || null); }
  if(state.tool)renderDrawer();remember();animate(false);
}
function animate(explicit=false) {
  cancelAnimationFrame(motionRaf);motionRaf=0;
  if(![1,5].includes(state.step) || (!explicit && matchMedia('(prefers-reduced-motion: reduce)').matches))return;
  const step=state.step,start=performance.now();state.progress=0;
  const tick=now=>{
    if(state.step!==step)return;
    state.progress=Math.min(1,(now-start)/12000);scene?.update({progress:state.progress});
    const moving=getHitMotion(data,state.step,state.progress);
    for(const d of moving){const label=$(`[data-device-status="${d.id}"]`);if(label)label.textContent=phaseLabel(d.phase);const live=$(`[data-live-phase="${d.id}"]`);if(live)live.textContent=phaseLabel(d.phase);}
    const meter=$('#operation-progress');if(meter)meter.value=state.progress;
    const phase=$('#operation-phase');if(phase)phase.textContent=phaseLabel(moving.find(d=>d.missionStep===state.step).phase);
    if(state.progress<1)motionRaf=requestAnimationFrame(tick);else motionRaf=0;
  };motionRaf=requestAnimationFrame(tick);
}
function stopPlay() { playing=false;clearTimeout(playTimer);playTimer=0;const button=$('[data-action="play"]');if(button){button.textContent='Play';button.setAttribute('aria-label','Play timeline');} }
function play() {
  if(playing){stopPlay();return;}
  if(state.step===8)setStep(0);
  playing=true;
  const next=()=>{
    if(!playing)return;
    if(state.step>=8){stopPlay();return;}
    setStep(state.step+1,{autoplay:true});
    playTimer=setTimeout(next,[1,5].includes(state.step)?12300:1600);
  };next();
}
function deviceParams(equipment,step=state.step) {
  const status=frame(step).equipment?.[equipment]?.status || 'ready';
  const rows=[['Equipment',equipment],['Ownership','Shared'],['Farm plot','HIT smart farm'],['Recorded status',status==='completed'?'Completed':'Ready']];
  if(equipment==='Satellite') {
    rows.push(['Coverage',number(data.farm.area_m2/10000,2)+' ha'],['Image date','14 Aug 2025']);
    if(step>=2)for(const crop of data.crops)rows.push([cropName(crop),number(crop.area_m2/10000,2)+' ha']);
  } else {
    rows.push(['Drone ID','DRONE_RICE_001'],['Survey region',step>=4?'Rice survey area':'Not selected yet']);
    if(step>=4)rows.push(['Survey footprint',number(data.roi.area_m2/10000,2)+' ha']);
    if(step>=7)rows.push(['Rice identified',number(data.droneMetrics.rice_area_m2/10000,3)+' ha'],['Lodged rice',number(data.droneMetrics.lodging_area_m2,1)+' m²'],['Lodging / surveyed rice',number(data.droneMetrics.lodging_percent,2)+'%']);
  }
  return params(rows);
}
function openDevice(equipment) { if(!['Satellite','Drone'].includes(equipment))return;state.pip=equipment;renderPip(); }
function renderPip() {
  pipResults?.destroy();pipResults=null;const host=$('#pip-host');if(!host)return;
  if(!state.pip){host.replaceChildren();return;}
  const equipment=state.pip;
  host.innerHTML=`<section class="pip pip-survey" aria-label="Object details"><div class="pip-head"><div><strong>${equipment}</strong><small>Shared · HIT smart farm · ${dateLabel(datetime())}</small></div><button class="close-button" data-action="close-pip" aria-label="Close object details">${icon('close')}</button></div><div class="pip-body"><div class="mini-heading">EQUIPMENT DETAILS</div>${deviceParams(equipment)}<div class="params"><div><small>Animation phase</small><b data-live-phase="${equipment}">${phaseLabel(getHitMotion(data,state.step,state.progress).find(d=>d.id===equipment).phase)}</b></div><div><small>Execution</small><b>Tool</b></div></div></div>${resultMarkup(data,equipment,state.step)}</section>`;
  pipResults=mountResults(host,data,{assetUrl});
}
function agentMarkup() {return `<div class="workflow-help">Lanes identify equipment operations, image processing and result presentation. Hover to preview; click to pin.</div><div class="workflow-area"><div class="workflow-host" id="workflow"></div></div><aside class="preview-pane workflow-popup" id="workflow-preview" role="dialog" aria-label="Action details" hidden></aside>`;}
function positionPreview() {
  const host=$('#workflow-preview');if(!host || host.hidden || !previewEvent)return;
  const node=$(`.wf-node[data-sequence="${previewEvent.sequence}"]`);const rect=node?.getBoundingClientRect();if(rect?.width)previewAnchor=rect;
  const anchor=previewAnchor || {right:innerWidth/2,left:innerWidth/2,top:120},width=host.offsetWidth,height=host.offsetHeight,pad=16;
  host.style.left=Math.max(pad,Math.min(anchor.right+12+width<=innerWidth-pad?anchor.right+12:anchor.left-width-12,innerWidth-width-pad))+'px';
  host.style.top=Math.max(84,Math.min(anchor.top,innerHeight-height-pad))+'px';
}
function processingMarkup(event) {
  const path=data.assets[PROCESSING_ASSETS[event.tool_name]];
  if(!path)return `<div class="hit-placeholder">${icon('camera')}<b>${esc(event.title)}</b><span>Processing result unavailable.</span></div>`;
  const isOrtho=event.tool_name==='raw_images_to_visible_orthomosaic';
  const caption=isOrtho?'Orthomosaic · Full image':'Reference run screenshot · Figures may differ from this placement';
  return `<figure class="hit-processing-result"><a href="${esc(assetUrl(path))}" target="_blank" rel="noopener" aria-label="Open full-size ${esc(event.title)} result"><img src="${esc(assetUrl(path))}" alt="${esc(event.title)} ${isOrtho?'orthomosaic':'reference processing output'}"></a><figcaption>${caption}</figcaption></figure>`;
}
function showPreview(event,placement) {
  if(placement?.anchor)previewAnchor=placement.anchor;
  if(event && previewEvent?.sequence===event.sequence && $('#workflow-preview')?.dataset.pinned===String(!!state.pinned)){positionPreview();return;}
  clearPreview();if(!event)return;previewEvent=event;
  const host=$('#workflow-preview');if(!host)return;host.hidden=false;host.dataset.pinned=String(!!state.pinned);
  let body='';
  if(event.category==='equipment')body=`<div class="hit-preview-scene" id="hit-mini-scene"></div><div class="pip-body"><div class="mini-heading">${event.equipment.toUpperCase()} OPERATION</div>${deviceParams(event.equipment,event.sequence)}</div>`;
  else if(event.category==='processing')body=`${processingMarkup(event)}<div class="pip-body">${params([['Equipment',event.equipment],['Result',event.tool_name==='raw_images_to_visible_orthomosaic'?'Orthomosaic':'Reference processing output']])}</div>`;
  else body=`<div class="pip-body"><div class="mini-heading">EQUIPMENT DETAILS</div>${deviceParams(event.equipment,event.sequence)}</div>${resultMarkup(data,event.equipment,event.sequence,{compact:true})}`;
  host.innerHTML=`<div class="pip-head"><div><strong>${esc(event.title)}</strong><small>Step ${event.sequence} · ${CATEGORY[event.category]}</small></div>${state.pinned?`<button class="close-button" data-action="unpin" aria-label="Unpin action preview">${icon('close')}</button>`:''}</div><div class="hit-preview-context">${state.pinned?'Selected action':'Action preview · Hover does not change the timeline'}</div>${body}<div class="pip-body hit-detail-json"><details><summary>Tool input & output</summary><pre>${json({arguments:event.arguments,result:event.result})}</pre></details></div>`;
  if(event.category==='equipment') {
    miniScene=createHitScene($('#hit-mini-scene'),options({dimension:'3d',step:event.sequence,layer:'natural',progress:.45,miniature:true,equipmentFocus:event.equipment}),()=>{});
    if(!matchMedia('(prefers-reduced-motion: reduce)').matches){const start=performance.now();const tick=now=>{miniScene?.update({progress:((now-start)/12000+.25)%1});previewRaf=requestAnimationFrame(tick);};previewRaf=requestAnimationFrame(tick);}
  } else if(event.category==='presentation')previewResults=mountResults(host,data,{assetUrl});
  host.querySelectorAll('.hit-processing-result img').forEach(img=>img.addEventListener('load',positionPreview,{once:true}));
  positionPreview();requestAnimationFrame(positionPreview);
}
function renderDrawer() {
  const host=$('#drawer-host');if(!host)return;
  const tool=data.tools.find(t=>t.name===state.tool);if(!tool){host.replaceChildren();return;}
  const schema=tool.schema.function || tool.schema,properties=schema.parameters.properties || {},required=schema.parameters.required || [];
  const executed=data.events.slice(0,state.step).find(e=>e.tool_name===tool.name);
  host.innerHTML=`<div class="drawer-scrim" data-action="close-tool"></div><section class="drawer" role="dialog" aria-modal="true" aria-label="Tool schema"><div class="drawer-head"><div><h2>${esc(tool.title)}</h2><p>${esc(tool.name)} · Tool</p></div><button class="close-button" data-action="close-tool" aria-label="Close tool schema">${icon('close')}</button></div><div class="drawer-body"><p>${esc(tool.description)}</p>${params([['Category',CATEGORY[tool.category]],['Equipment',tool.equipment],['Calls in this recording','1'],['Called by selected time',executed?'Yes':'No']])}<h3>Input parameters</h3>${Object.entries(properties).map(([key,p])=>`<div class="schema-field"><span class="field-type">${esc(p.type)} · ${required.includes(key)?'required':'optional'}</span><b>${esc(key)}</b>${p.description?`<p>${esc(p.description)}</p>`:''}</div>`).join('')}<details><summary>Complete input schema</summary><pre>${json(schema.parameters)}</pre></details><h3>Latest response by selected world time</h3>${executed?`<p>Step ${executed.sequence} · ${dateLabel(executed.datetime_after)}</p><pre>${json(executed.result)}</pre>`:'<div class="empty-note">This tool has not been called by the selected time.</div>'}<div class="drawer-links"><a href="${assetUrl('scenario.json')}" download>Download recording & schemas</a></div></div></section>`;
}
document.addEventListener('click',event=>{
  const el=event.target.closest('[data-view],[data-dimension],[data-device],[data-step],[data-action],[data-tool]');if(!el || !data)return;
  if(el.dataset.view){stopPlay();state.view=el.dataset.view;state.pip=null;render();}
  else if(el.dataset.dimension){state.dimension=el.dataset.dimension==='3d' && state.dimension==='3d'?'2d':el.dataset.dimension;state.pip=null;render();}
  else if(el.dataset.device)openDevice(el.dataset.device);
  else if(el.dataset.step!==undefined)setStep(el.dataset.step);
  else if(el.dataset.tool){state.tool=el.dataset.tool;renderDrawer();$('.drawer .close-button')?.focus();}
  else switch(el.dataset.action){
    case'overview':state.dimension='2d';state.pip=null;render();break;
    case'reset':scene?.resetView();break;
    case'close-pip':state.pip=null;renderPip();break;
    case'close-tool':state.tool=null;renderDrawer();break;
    case'unpin':state.pinned=null;clearPreview();break;
    case'previous':setStep(state.step-1);break;
    case'next':setStep(state.step+1);break;
    case'play':play();break;
    case'replay-operation':stopPlay();animate(true);break;
  }
});
document.addEventListener('change',event=>{
  if(event.target.id==='layer'){state.layer=event.target.value;guardLayer();scene?.update(options());$('#legend').innerHTML=legend();remember();}
  if(event.target.id==='milestone' && event.target.value!=='')setStep(event.target.value);
});
document.addEventListener('input',event=>{
  if(event.target.id==='cursor')setStep(event.target.value);
  if(event.target.id==='tool-search')$('#tool-list').innerHTML=toolList(event.target.value);
});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'){state.tool=null;state.pip=null;state.pinned=null;renderDrawer();renderPip();clearPreview();}
});
window.addEventListener('resize',positionPreview);
document.addEventListener('scroll',event=>{if(event.target.matches?.('.wf-scroll'))positionPreview();},true);
window.addEventListener('pagehide',()=>{stopPlay();cancelAnimationFrame(motionRaf);clearPreview();scene?.destroy();graph?.destroy();pipResults?.destroy();});
await init();
