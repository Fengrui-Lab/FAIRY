// Configuration is sourced; all measurements, poses, steps and frames are authored UI fixtures.
export const SOURCE_COMMIT = '4afdd742d1bef147a41680ab722ebda2bc53f22a';
export type Layer = 'crop' | 'moisture' | 'pest';
export type View = 'world' | 'map' | 'crops';
export type SceneId = 'two' | 'three';
export type Phase = 'Preparation' | 'Sowing' | 'Monitoring' | 'Management' | 'Harvest' | 'Storage';
export const PHASES: Phase[] = ['Preparation', 'Sowing', 'Monitoring', 'Management', 'Harvest', 'Storage'];
export const PHASE_COLORS = ['#aab49b', '#d3b55d', '#4e927e', '#6192ae', '#b58c5a', '#8e82ac'];
export interface Field {
  id: string; name: string; crop: 'Soybean' | 'Maize'; cultivar: string;
  width: number; length: number; ridgeWidth: number; rows: number; x: number;
  sensor: string; irrigation: string; color: string;
}
export interface Scene {
  id: SceneId; title: string; subtitle: string; location: string; timezone: string;
  start: string; fields: Field[]; equipment: string[]; source: string; durationDays: number;
}
export interface Region {
  id: string; fieldId: string; column: number; row: number; x: number; z: number;
  width: number; length: number; ridges: [number, number]; moisture: number; severity: 'Low' | 'Moderate' | 'High' | 'N/A';
}
export interface Frame { id: string; phase: Phase; growth: number; moistureOffset: number; pestVisible: boolean }
export interface Step {
  id: string; number: number; phase: Phase; fieldId: string; regionId: string;
  tool: string; title: string; summary: string; time: string; frameId: string; mediaId?: string;
  coverage: string;
}
export interface Media { id: string; sceneId: SceneId; fieldId: string; regionId: string; aerial: string; closeup: string; provenance: string }
const soy = { crop: 'Soybean' as const, width: 70.4, length: 268, ridgeWidth: 1.1, rows: 2, color: '#81a66c' };
export const SCENES: Record<SceneId, Scene> = {
  two: { id: 'two', title: 'Maize × Soybean', subtitle: 'Native WOFOST · two farms', location: 'Thionville, France', timezone: 'Europe/Paris', start: '2019-05-01T07:00:00+02:00', durationDays: 190,
    source: 'two_farm/scenario_two_farm_wofost_soybean_maize_full_season.py', equipment: ['Tractor', 'Drone', 'Robot'],
    fields: [
      { ...soy, id: 'soybean_field', name: 'Soybean field', cultivar: 'SOYBEAN_901', x: -39, sensor: 'Soybean_Sensor', irrigation: 'Soybean_Irrigation' },
      { id: 'maize_field', name: 'Maize field', crop: 'Maize', cultivar: 'MAIZE_201', x: 34.2, width: 48, length: 268, ridgeWidth: .75, rows: 1, color: '#d7b85b', sensor: 'Maize_Sensor', irrigation: 'Maize_Irrigation' },
    ] },
  three: { id: 'three', title: 'Three soybean farms', subtitle: 'Shared resources · three farms', location: 'Harbin, China', timezone: 'Asia/Shanghai', start: '2026-05-05T07:00:00+08:00', durationDays: 165,
    source: 'three_farm/scenario_three_farm_full_season_hn84_normal.py', equipment: ['Tractor', 'Mavic3M', 'Matrice4T', 'Robot0'],
    fields: ['a', 'b', 'c'].map((letter, i) => ({ ...soy, id: `farm_${letter}`, name: `Farm ${letter.toUpperCase()}`, cultivar: 'HEINONG84', x: (i - 1) * 85, sensor: `Farm${letter.toUpperCase()}_Sensor`, irrigation: `Farm${letter.toUpperCase()}_Irrigation` })) },
};
export const FRAMES: Frame[] = PHASES.map((phase, i) => ({ id: `frame-${i}`, phase, growth: [0, .18, 1, 1, .35, 0][i], moistureOffset: [.03, .02, 0, .04, -.02, -.01][i], pestVisible: i === 2 || i === 3 }));
export const area = (f: Field) => f.width * f.length / 10000;
export const stage = (f: Field, frame: Frame) => ({ Preparation: 'Seedbed ready', Sowing: 'Emergence', Monitoring: f.crop === 'Maize' ? 'VT · Tasseling' : 'R2 · Full bloom', Management: f.crop === 'Maize' ? 'R1 · Silking' : 'R3 · Pod set', Harvest: 'Harvest ready', Storage: 'Stored' })[frame.phase];
export const managementSummary = (f: Field, frame: Frame) => ({ Preparation: 'Seedbed preparation · 64 ridges', Sowing: 'Crop-specific planter · 4-ridge passes', Monitoring: f.crop === 'Maize' ? 'Water & canopy observation' : 'Survey → ground confirmation', Management: f.crop === 'Maize' ? 'Water & nitrogen management' : 'Water plan · local inspection', Harvest: 'Separate batches before farm transfer', Storage: 'Traceable field-origin grain batches' })[frame.phase];
export const regionId = (f: Field, col = 1, row = 2) => `${f.id}:r${row}c${col}`;
export function regions(scene: Scene, frame = FRAMES[2]): Region[] {
  return scene.fields.flatMap((f, fi) => Array.from({ length: 16 }, (_, n) => {
    const column = n % 4, row = Math.floor(n / 4);
    return { id: regionId(f, column, row), fieldId: f.id, column, row, x: f.x - f.width / 2 + (column + .5) * f.width / 4,
      z: -134 + (row + .5) * 67, width: f.width / 4, length: 67, ridges: [column * 16, column * 16 + 15] as [number, number],
      moisture: Math.max(.12, Math.min(.38, .16 + ((n * 7 + fi * 3) % 11) * .017 + frame.moistureOffset)),
      severity: f.crop === 'Maize' ? 'N/A' : !frame.pestVisible ? 'Low' : column === 1 && row === 2 ? 'High' : (n === 5 || n === 10) ? 'Moderate' : 'Low' };
  }));
}
export const MOISTURE_COLORS = ['#d8c5a1', '#b7cdbd', '#82b7bf', '#518caa', '#346585'];
export function regionColor(r: Region, field: Field, layer: Layer) {
  if (layer === 'crop') return field.color;
  if (layer === 'moisture') {
    const value = Math.max(0, Math.min(4, (r.moisture - .12) / .26 * 4));
    const index = Math.min(3, Math.floor(value)), t = value - index;
    const a = MOISTURE_COLORS[index], b = MOISTURE_COLORS[index + 1];
    return '#' + [1, 3, 5].map(i => Math.round(parseInt(a.slice(i, i + 2), 16) * (1 - t) + parseInt(b.slice(i, i + 2), 16) * t).toString(16).padStart(2, '0')).join('');
  }
  return { Low: '#a2bf90', Moderate: '#e5b75e', High: '#d96550', 'N/A': '#c9cec5' }[r.severity];
}
export function mediaFor(scene: Scene, field: Field): Media {
  return { id: `${scene.id}:${field.id}:survey`, sceneId: scene.id, fieldId: field.id, regionId: regionId(field), aerial: `/showcase-media/${scene.id}-${field.id}.png`, closeup: field.crop === 'Soybean' ? '/showcase-media/soybean-leaf.svg' : `/showcase-media/${scene.id}-${field.id}.png`, provenance: 'Procedural farm render / authored illustration' };
}
const actionNames = [
  ['Inspect seedbed', 'Level field', 'Form ridges', 'Check implements'],
  ['Load cultivar', 'Sow ridge group', 'Check emergence', 'Return supplies'],
  ['Read soil profile', 'Survey canopy', 'Inspect crop health', 'Review observations'],
  ['Read water budget', 'Irrigate ridge group', 'Review canopy', 'Check shared resources'],
  ['Check grain moisture', 'Harvest ridge group', 'Unload grain', 'Inspect batch'],
  ['Check grain batch', 'Dry crop batch', 'Store batch', 'Reconcile inventory'],
];
export function makeSteps(scene: Scene): Step[] {
  const phaseDays = [0, 7, 72, 92, 145, scene.durationDays - 6];
  return Array.from({ length: 240 }, (_, i) => {
    const pi = Math.floor(i / 40), within = i % 40;
    const field = scene.fields[Math.floor(within / 4) % scene.fields.length];
    const action = within % 4, isDrone = pi === 2 && action === 1;
    const prefix = pi === 2 ? [field.sensor, scene.id === 'two' ? 'Drone' : 'Mavic3M', scene.id === 'two' ? 'Robot' : 'Robot0', 'Agent'][action] : pi === 3 ? [field.sensor, field.irrigation, field.sensor, 'Warehouse'][action] : pi === 5 ? 'Warehouse' : 'Tractor';
    const methods = [['get_status', 'level', 'form_ridges', 'get_status'], ['load_seeds', 'sow', 'get_status', 'return_supplies'], ['read_soil', 'fly_survey', 'inspect_crop_health', 'review'], ['read_soil', 'irrigate', 'read_canopy', 'get_stock'], ['get_status', 'harvest', 'unload_grain', 'get_status'], ['get_stock', 'dry_grain', 'store_grain', 'get_stock']];
    const start = (Math.floor(within / 4) % 16) * 4;
    return { id: `${scene.id}:step-${String(i + 1).padStart(3, '0')}`, number: i + 1, phase: PHASES[pi], fieldId: field.id, regionId: regionId(field),
      tool: `${prefix}.${methods[pi][action]}`, title: actionNames[pi][action],
      summary: isDrone ? 'Canopy mosaic available. Inspect the marked region; aerial appearance alone is not a diagnosis.' : `${actionNames[pi][action]} recorded for ${field.name.toLowerCase()}. Authored result for the UI demonstration.`,
      time: new Date(new Date(scene.start).getTime() + (phaseDays[pi] + Math.floor(within / 8)) * 86400000 + (within % 8) * 42 * 60000).toISOString(),
      frameId: `frame-${pi}`, mediaId: isDrone ? mediaFor(scene, field).id : undefined,
      coverage: isDrone ? 'Ridges 0–63 · full field' : `Ridges ${start}–${start + 3} · sample`,
    };
  });
}
export const formatTime = (iso: string, scene: Scene, short = false) => new Intl.DateTimeFormat('en-GB', { timeZone: scene.timezone, ...(short ? {} : { day: '2-digit', month: 'short', year: 'numeric' }), hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(iso));
export const PRESETS = {
  overview: { title: 'Platform overview', view: 'world', layer: 'crop', step: 98, pip: false },
  trajectory: { title: 'Agent trajectory', view: 'world', layer: 'crop', step: 98, pip: true },
  moisture: { title: '3D soil moisture', view: 'world', layer: 'moisture', step: 97, pip: false },
  investigation: { title: '2D pest investigation', view: 'map', layer: 'pest', step: 98, pip: true },
  management: { title: 'L4 crop management', view: 'crops', layer: 'crop', step: 98, pip: false },
} as const;
export type PresetId = keyof typeof PRESETS;
