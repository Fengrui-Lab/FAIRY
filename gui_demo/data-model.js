export const UNKNOWN = '#c9cece';
export const CATEGORY_NAMES = {observe:'Observation',diagnose:'Diagnosis',act:'Field operation',resource:'Resources',wait:'Time',report:'Report'};
export const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const humanize = value => String(value || '').replace(/__/g,' · ').replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase());
export function english(value) {
  if (typeof value==='string') return /[\u3400-\u9fff]/u.test(value) ? '[Original wording is available in the source JSON download]' : value;
  if (Array.isArray(value)) return value.map(english);
  if (value && typeof value==='object') return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,english(v)]));
  return value;
}
export function dateLabel(value, includeTime=true) {
  if(!value) return '—';
  return new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',day:'2-digit',month:'short',year:'numeric',...(includeTime?{hour:'2-digit',minute:'2-digit',hourCycle:'h23'}:{})}).format(new Date(typeof value==='number'?value*1000:value));
}
export const number = (n,d=2) => Number.isFinite(Number(n)) && n!==null && n!==undefined ? Number(n).toLocaleString('en-US',{maximumFractionDigits:d,minimumFractionDigits:d}) : '—';
function ramp(value, stops) {
  if(!Number.isFinite(value)) return UNKNOWN;
  const v=Math.max(stops[0][0],Math.min(stops.at(-1)[0],value));
  let a=stops[0],b=stops.at(-1);
  for(let i=1;i<stops.length;i++)if(v<=stops[i][0]){a=stops[i-1];b=stops[i];break;}
  const t=(v-a[0])/(b[0]-a[0]||1), rgb=hex=>[1,3,5].map(p=>parseInt(hex.slice(p,p+2),16));
  return '#'+rgb(a[1]).map((x,i)=>Math.round(x+(rgb(b[1])[i]-x)*t).toString(16).padStart(2,'0')).join('');
}
export function createDataModel(manifest,events,frames,catalog) {
  const farms=manifest.farms, farmById=Object.fromEntries(farms.map(f=>[f.id,f]));
  const tools=Array.isArray(catalog)?catalog:catalog.tools;
  const obsCache=new Map();
  function observations(step) {
    if(obsCache.has(step))return obsCache.get(step);
    const result=Object.fromEntries(farms.map(f=>[f.id,Array.from({length:f.num_ridges},()=>({}))]));
    for(const event of events.slice(0,step)) {
      const output=event.result;
      if(!output || typeof output!=='object' || event.error || event.status==='error')continue;
      const farmId=output.farm_id || (event.scope.farm_ids.length===1?event.scope.farm_ids[0]:null);
      if(!result[farmId])continue;
      const metadata={sequence:event.sequence,datetime:event.datetime_after,tool:event.tool_name};
      for(const sensor of output.soil_sensors || []) {
        for(let r=sensor.ridge_start;r<=sensor.ridge_end;r++) if(result[farmId][r])
          result[farmId][r].moisture={value:sensor.vwc,temperature:sensor.temp_c,sensorId:sensor.sensor_id,range:[sensor.ridge_start,sensor.ridge_end],...metadata};
      }
      for(const row of Object.values(output.observations || {})) {
        const r=Number(row.ridge_id);if(!result[farmId][r])continue;
        if(typeof row.disease_present==='boolean')result[farmId][r].disease={value:row.disease_present,confidence:row.disease_confidence,...metadata};
        if(Number.isFinite(row.ndvi))result[farmId][r].ndvi={value:row.ndvi,...metadata};
        if(Number.isFinite(row.ndvi_proxy))result[farmId][r].ndvi={value:row.ndvi_proxy,...metadata};
      }
    }
    if(obsCache.size>24)obsCache.delete(obsCache.keys().next().value);
    obsCache.set(step,result);return result;
  }
  function colors(farmId,step,layer,mode) {
    if(layer==='natural')return null;
    return frames[step].farms[farmId].ridges.map((r,index)=>{
      if(layer==='crop')return farmById[farmId].crop_id==='maize'?'#c0b668':'#7d966e';
      if(mode==='observation') {
        const obs=observations(step)[farmId][index]?.[layer];
        if(!obs)return UNKNOWN;
        if(layer==='disease')return obs.confidence<.6?UNKNOWN:obs.value?'#bd795b':'#98ad91';
        return ramp(obs.value,[[.1,'#c09b6a'],[.22,'#c0c79b'],[.4,'#739aa9']]);
      }
      return layer==='disease'?ramp(r.disease_pressure,[[0,'#9baa86'],[.25,'#d3bd7b'],[.6,'#b76c59']]):ramp(r.root_vwc,[[.1,'#c09b6a'],[.22,'#c0c79b'],[.4,'#739aa9']]);
    });
  }
  function summary(step,farmId) {
    const ids=farmId?[farmId]:farms.map(f=>f.id),rows=ids.flatMap(id=>frames[step].farms[id].ridges);
    const avg=key=>{const values=rows.map(r=>r[key]).filter(Number.isFinite);return values.length?values.reduce((a,b)=>a+b,0)/values.length:null;};
    return {ridged:rows.length,planted:rows.filter(r=>r.planted&&!r.harvested).length,harvested:rows.filter(r=>r.harvested).length,rootVwc:avg('root_vwc'),disease:avg('disease_pressure'),stages:[...new Set(rows.map(r=>r.growth_stage))]};
  }
  return {manifest,events,frames,farms,farmById,tools,observations,colors,summary};
}
