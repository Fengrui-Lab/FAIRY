#!/usr/bin/env node
// Optional build utility. Runtime maps use the same renderer; Node is not
// required to run the demo. No captured or synthetic pixel imagery is made.
import {readFile, mkdir, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve, dirname} from 'node:path';
import {buildSurveyMap} from '../survey-map.js';

const root=resolve(dirname(fileURLToPath(import.meta.url)), '..');
const events=JSON.parse(await readFile(resolve(root,'data/events.json'),'utf8'));
const manifest=JSON.parse(await readFile(resolve(root,'data/manifest.json'),'utf8'));
const output=resolve(root,'assets/survey-maps');
await mkdir(output,{recursive:true});
const maps=[];
for(const event of events.filter(e=>e.tool_name.endsWith('__fly_survey'))){
  const farm=manifest.farms.find(f=>f.id===event.result?.farm_id);
  const ndvi=buildSurveyMap(event,farm);
  const variants=[ndvi,buildSurveyMap(event,farm,{layer:'temperature'})];
  if(ndvi.hasData)variants.push(buildSurveyMap(event,farm,{contrast:'detail'}));
  for(const map of variants){
    await writeFile(resolve(output,map.filename),map.svg+'\n');
    maps.push({file:map.filename,step:event.sequence,farm_id:farm.id,
      acquired_at:event.datetime_after,layer:map.layer,contrast:map.contrast,
      scale:[map.min,map.max],data_range:[map.dataMin,map.dataMax],
      valid_ridges:map.validCount,covered_ridges:map.coveredCount,
      source:map.sourceResolution,is_captured_image:false});
  }
}
await writeFile(resolve(output,'index.json'),JSON.stringify({
  description:'Maps of recorded per-ridge tool values, not captured aerial imagery. Gray indicates unavailable or unobserved values.',
  maps
},null,2)+'\n');
console.log(`Exported ${maps.length} standalone SVG maps to assets/survey-maps/`);
