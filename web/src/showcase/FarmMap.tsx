import { useRef, useState } from 'react';
import { Minus, Plus, RotateCcw } from 'lucide-react';
import { type Field, type Frame, type Layer, type Region, type Scene, area, regionColor, stage } from './data';

export default function FarmMap({ scene, frame, layer, cells, selectedField, selectedRegion, onSelect, management }: {
  scene: Scene; frame: Frame; layer: Layer; cells: Region[]; selectedField: string; selectedRegion: string;
  onSelect: (field: string, region?: string) => void; management: boolean;
}) {
  const [zoom, setZoom] = useState(1), [pan, setPan] = useState({ x: 0, y: 0 });
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ x: number; y: number; px: number; py: number; moved: boolean } | null>(null);
  const fieldLabel = (f: Field) => `${f.id} · ${f.crop} · ${area(f).toFixed(5)} ha`;
  return <div className="sc-map" data-testid={management ? 'crop-view' : 'map-view'}>
    <svg ref={svg} viewBox={`-182 ${scene.id === 'two' ? -136 : -164} 364 ${scene.id === 'two' ? 272 : 328}`} role="group" aria-label="Interactive farm map" onPointerDown={e => { if (e.button !== 0) return; drag.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y, moved: false }; }}
      onPointerMove={e => { const d = drag.current; if (!d || !svg.current) return; const unit = 364 / svg.current.getBoundingClientRect().width; if (Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 5) { d.moved = true; svg.current.setPointerCapture(e.pointerId); setPan({ x: d.px + (e.clientX - d.x) * unit, y: d.py + (e.clientY - d.y) * unit }); } }}
      onPointerUp={e => { if (svg.current?.hasPointerCapture(e.pointerId)) svg.current.releasePointerCapture(e.pointerId); setTimeout(() => { drag.current = null; }, 0); }} onPointerCancel={() => { drag.current = null; }}
      onWheel={e => setZoom(v => Math.max(.7, Math.min(3, v * (e.deltaY < 0 ? 1.08 : .92))))}>
      <defs><pattern id="sc-grid" width="10" height="10" patternUnits="userSpaceOnUse"><path d="M10 0H0V10" fill="none" stroke="#bac7b8" strokeWidth=".15" /></pattern><pattern id="sc-rows" width="3" height="3" patternUnits="userSpaceOnUse"><path d="M0 0H3" stroke="#ffffff" strokeOpacity=".2" strokeWidth=".45" /></pattern><pattern id="sc-na" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><path d="M0 0V4" stroke="#9ca69d" strokeWidth=".6" /></pattern></defs>
      <rect x="-500" y="-500" width="1000" height="1000" fill="url(#sc-grid)" />
      <g transform={`translate(${pan.x} ${pan.y}) scale(${zoom})`}>
        <path d="M-148 -145V145M150 -145V145M-148 140H150" stroke="#d9d1bd" strokeWidth="8" fill="none" />
        <path d="M-148 -145V145M150 -145V145" stroke="#f2ecdd" strokeWidth=".8" strokeDasharray="4 4" fill="none" />
        {scene.fields.map(f => <g key={f.id} role="button" tabIndex={0} aria-label={`Select ${f.name}`} data-testid={`field-${f.id}`} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(f.id); } }} onClick={() => { if (!drag.current?.moved) onSelect(f.id); }}>
          <title>{fieldLabel(f)}</title>
          <rect x={-136} y={f.x - f.width / 2 - 2} width={272} height={f.width + 4} rx="1.5" fill="#c1c5a7" />
          {cells.filter(c => c.fieldId === f.id).map(c => <g key={c.id} role="button" tabIndex={0} aria-label={`${f.name}, region ${c.row + 1}-${c.column + 1}, ${layer === 'moisture' ? c.moisture.toFixed(3) + ' cubic metres per cubic metre' : c.severity + ' severity'}`} data-testid={`region-${c.id}`} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); onSelect(f.id, c.id); } }} onClick={e => { e.stopPropagation(); if (!drag.current?.moved) onSelect(f.id, c.id); }}>
            <rect x={c.z - c.length / 2} y={c.x - c.width / 2} width={c.length} height={c.width} fill={regionColor(c, f, management ? 'crop' : layer)} stroke="#fff" strokeWidth=".18" />
            {layer === 'pest' && c.severity === 'N/A' && !management && <rect x={c.z - c.length / 2} y={c.x - c.width / 2} width={c.length} height={c.width} fill="url(#sc-na)" />}
            {c.id === selectedRegion && <rect x={c.z - c.length / 2 + .7} y={c.x - c.width / 2 + .7} width={c.length - 1.4} height={c.width - 1.4} fill="none" stroke="#fff4ce" strokeWidth="1.2" />}
            {layer === 'pest' && c.severity === 'High' && !management && <g pointerEvents="none"><circle cx={c.z} cy={c.x} r="3.2" fill="#fff8ed" /><text x={c.z} y={c.x + 1.4} textAnchor="middle" fill="#b14336" fontSize="4.6" fontWeight="700">!</text></g>}
          </g>)}
          <rect pointerEvents="none" x={-134} y={f.x - f.width / 2} width={268} height={f.width} fill="url(#sc-rows)" />
          <rect pointerEvents="none" x={-135} y={f.x - f.width / 2 - 1} width={270} height={f.width + 2} fill="none" stroke={selectedField === f.id ? '#254e40' : '#789072'} strokeWidth={selectedField === f.id ? 1.15 : .45} />
          <g pointerEvents="none" transform={`translate(-122 ${f.x - f.width / 2 + 5})`}><rect width="100" height={management ? 24 : 16} fill="#fffef4" fillOpacity=".94" rx="1.6" /><circle cx="6" cy="6" r="1.5" fill={f.color} /><text x="11" y="7" className="sc-svg-name">{f.name}</text><text x="5" y="12.5" className="sc-svg-sub">{f.cultivar} · {area(f).toFixed(2)} ha</text>{management && <text x="5" y="20" className="sc-svg-sub">{stage(f, frame)} · 64 ridges</text>}</g>
          <g transform={`translate(25 ${f.x - f.width / 2 - 5})`}><circle r="3" fill="#fff" stroke="#3e7c85" strokeWidth=".7" /><circle r="1" fill="#3e7c85" /><text x="5" y="1.3" className="sc-svg-sensor">{f.sensor}</text></g>
          <path d={`M-132 ${f.x + f.width / 2 + 3}H132`} stroke="#79a5b2" strokeWidth=".65" strokeDasharray="2 1" />
        </g>)}
        <g transform="translate(150 -100)"><rect x="-8" y="-8" width="16" height="26" rx="1" fill="#e9e2ce" stroke="#9ca68f" strokeWidth=".5" /><path d="M-8 -8L0 -14L8 -8" fill="#688173" /><text x="0" y="25" textAnchor="middle" className="sc-svg-sub">Warehouse</text></g>
        <g transform="translate(150 -50)"><rect x="-4" y="-5" width="8" height="10" rx="1.5" fill="#c59c46" /><text x="0" y="12" textAnchor="middle" className="sc-svg-sub">Tractor</text></g>
        <g transform={`translate(20 ${scene.fields[0].x})`} pointerEvents="none"><circle r="7" fill="#ffffff" fillOpacity=".9" /><path d="M-4 -4L4 4M4 -4L-4 4" stroke="#326655" strokeWidth="1.2" /><circle r="2" fill="#326655" /><text x="10" y="1.5" className="sc-svg-sensor">{scene.id === 'two' ? 'Drone' : 'Mavic3M'}</text></g>
        {scene.id === 'three' && <g transform={`translate(-50 ${scene.fields[1].x})`}><circle r="4" fill="#fff" stroke="#326655" strokeWidth=".6" /><text x="6" y="1.5" className="sc-svg-sensor">Matrice4T</text></g>}
        <g transform="translate(150 10)"><rect x="-3" y="-3" width="6" height="6" rx="1.2" fill="#718881" /><text x="0" y="10" textAnchor="middle" className="sc-svg-sub">{scene.id === 'two' ? 'Robot' : 'Robot0'}</text></g>
        <g transform={`translate(-126 ${scene.id === 'two' ? 105 : 144})`}><path d="M0 -2V0H50V-2M25 0V-2" stroke="#53695d" fill="none" strokeWidth=".6" /><text x="0" y="5" className="sc-svg-sub">0</text><text x="43" y="5" className="sc-svg-sub">50 m</text></g>
      </g>
    </svg>
    <div className="sc-map-controls"><button aria-label="Zoom in" onClick={() => setZoom(v => Math.min(3, v * 1.2))}><Plus size={15} /></button><span>{Math.round(zoom * 100)}%</span><button aria-label="Zoom out" onClick={() => setZoom(v => Math.max(.7, v / 1.2))}><Minus size={15} /></button><button aria-label="Reset map" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}><RotateCcw size={14} /></button></div>
    <span className="sc-north">← N</span>
  </div>;
}
