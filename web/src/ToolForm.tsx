import { useEffect, useState, type FormEvent } from 'react';
import { Play, Code2 } from 'lucide-react';
import type { Data, Schema, Tool } from './types';

const names: Record<string, string> = {
  read_soil_sensors: '测量表层土壤', read_root_zone_sensors: '测量根区水分', read_canopy_sensors: '测量冠层',
  get_farm_overview: '读取农场概况', get_ridge_state: '读取单垄状态', get_ridge_range_state: '读取垄范围状态',
  get_inventory: '读取库存', get_status: '读取设备状态', get_current_weather: '读取当前天气',
  get_forecast: '读取天气预报', advance_time: '推进仿真时间', irrigate_range: '灌溉垄范围', irrigate: '灌溉',
  plant_seeds: '播种', harvest: '收割', unload_grain: '卸粮', store_grain: '入库', dry_grain: '干燥粮食',
  attach_implement: '挂载机具', detach_implement: '卸下机具', level: '整地', form_ridges: '起垄', load_seeds: '装载种子',
  apply_fertilizer: '施肥', refuel: '补充燃油', inspect_ridges: '巡检田垄', get_management_status: '管理状态',
};
const fields: Record<string, string> = {
  start: '起始垄', end: '结束垄', start_ridge: '起始垄', end_ridge: '结束垄', ridge_id: '垄编号',
  days: '天数', hours: '小时', minutes: '分钟', seconds: '秒', duration_hours: '持续小时',
  seed_type: '种子类型', count: '数量', depth_cm: '播种深度（cm）', seed_spacing_cm: '株距（cm）',
  ridge_width_m: '垄宽（m）', liters: '升', kg: '千克', implement: '机具', target_moisture_pct: '目标含水率（%）',
  farm_id: '农场', asset_id: '设备', sensor_id: '传感器',
};
export function toolLabel(name: string): string {
  const last = name.split('__').pop() || name;
  return names[last] || last.replaceAll('_', ' ');
}

function editableSchema(schema: Schema): Schema {
  const union = schema.anyOf || schema.oneOf;
  if (!Array.isArray(union)) return schema;
  const variants = (union as Schema[]).filter(s => s.type !== 'null');
  return variants.length === 1 ? { ...variants[0], ...schema, type: variants[0].type, enum: schema.enum || variants[0].enum } : schema;
}

function initialValue(name: string, schema: Schema, range: [number, number], farm: string, asset?: string): unknown {
  if (['start', 'start_ridge', 'ridge_id'].includes(name)) return range[0];
  if (['end', 'end_ridge'].includes(name)) return range[1];
  if (name === 'farm_id') return farm;
  if (name === 'asset_id' && asset) return asset;
  if (schema.default !== undefined) return schema.default;
  if (schema.enum?.length) return schema.enum[0];
  if (schema.type === 'boolean') return false;
  if (schema.type === 'integer' || schema.type === 'number') return schema.minimum ?? (name === 'days' ? 1 : 0);
  if (schema.type === 'array') return [];
  if (schema.type === 'object') return {};
  return '';
}

export default function ToolForm({ tools, disabled, onSubmit, range, farm, asset }: {
  tools: Tool[]; disabled: boolean; onSubmit: (tool: string, args: Data) => void; range: [number, number]; farm: string; asset?: string;
}) {
  const [toolName, setToolName] = useState('');
  const [values, setValues] = useState<Data>({});
  const [raw, setRaw] = useState('{}');
  const [advanced, setAdvanced] = useState(false);
  const [error, setError] = useState('');
  const [complex, setComplex] = useState<Record<string, string>>({});
  const tool = tools.find(t => t.name === toolName) || tools[0];
  useEffect(() => {
    if (!tool) return;
    const next: Data = {};
    Object.entries(tool.parameters.properties || {}).forEach(([key, rawSchema]) => {
      const schema = editableSchema(rawSchema);
      if (tool.parameters.required?.includes(key) || schema.default !== undefined || ['days', 'start', 'end', 'start_ridge', 'end_ridge', 'ridge_id', 'farm_id'].includes(key)) next[key] = initialValue(key, schema, range, farm, asset);
    });
    setValues(next); setRaw(JSON.stringify(next, null, 2)); setComplex({}); setError('');
  }, [tool?.name, range[0], range[1], farm, asset]);
  const change = (key: string, value: unknown) => { const next = { ...values, [key]: value }; if (value === '') delete next[key]; setValues(next); setRaw(JSON.stringify(next, null, 2)); };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!tool || disabled) return;
    try {
      const args = advanced ? JSON.parse(raw) : { ...values, ...Object.fromEntries(Object.entries(complex).map(([key, value]) => [key, JSON.parse(value)])) };
      if (!args || Array.isArray(args) || typeof args !== 'object') throw new Error('参数必须是 JSON 对象');
      setError(''); onSubmit(tool.name, args);
    } catch (e) { setError(e instanceof Error ? e.message : '参数格式有误'); }
  };
  return <form className="tool-form" onSubmit={submit}>
    <label className="field-label" htmlFor="tool">农事与观测工具</label>
    <select id="tool" data-testid="tool-select" value={tool?.name || ''} onChange={e => setToolName(e.target.value)} disabled={disabled || !tools.length}>
      {tools.map(t => <option key={t.name} value={t.name}>{toolLabel(t.name)} · {t.name.split('__')[0]}</option>)}
    </select>
    {tool && <>
      <p className="tool-description">{tool.description.split('\n\n')[0]}</p>
      <button type="button" className="text-button" onClick={() => setAdvanced(v => !v)}><Code2 size={13} />{advanced ? '使用参数表单' : '编辑 JSON 参数'}</button>
      {advanced ? <textarea data-testid="tool-args" className="code-input" aria-label="工具 JSON 参数" rows={7} value={raw} onChange={e => setRaw(e.target.value)} disabled={disabled} />
        : <div className="parameter-grid">{Object.entries(tool.parameters.properties || {}).map(([key, rawSchema]) => {
          const schema = editableSchema(rawSchema);
          const required = tool.parameters.required?.includes(key);
          const type = schema.type;
          return <label key={key} className={type === 'object' || type === 'array' ? 'wide' : ''} title={schema.description}>
            <span>{fields[key] || key}{required && <i> *</i>}</span>
            {schema.enum ? <select data-testid={`arg-${key}`} value={String(values[key] ?? '')} disabled={disabled} onChange={e => change(key, schema.enum?.find(v => String(v) === e.target.value))}>
              {!required && <option value="">默认</option>}{schema.enum.map(v => <option key={String(v)} value={String(v)}>{String(v)}</option>)}
            </select> : type === 'boolean' ? <input data-testid={`arg-${key}`} type="checkbox" checked={Boolean(values[key])} disabled={disabled} onChange={e => change(key, e.target.checked)} />
              : type === 'object' || type === 'array' ? <textarea data-testid={`arg-${key}`} rows={2} disabled={disabled} value={complex[key] ?? JSON.stringify(values[key] ?? (type === 'array' ? [] : {}))} onChange={e => { setComplex(old => ({ ...old, [key]: e.target.value })); try { change(key, JSON.parse(e.target.value)); } catch { /* Keep unfinished JSON editable until submission. */ } }} />
                : <input data-testid={`arg-${key}`} type={type === 'integer' || type === 'number' ? 'number' : 'text'} value={values[key] == null ? '' : String(values[key])} min={schema.minimum} max={schema.maximum} step={type === 'integer' ? 1 : 'any'} required={required} placeholder={required ? '' : '默认'} disabled={disabled} onChange={e => change(key, e.target.value === '' ? '' : type === 'integer' || type === 'number' ? Number(e.target.value) : e.target.value)} />}
          </label>;
        })}</div>}
      {error && <p className="inline-error">{error}</p>}
      <button type="submit" data-testid="execute-command" className="primary full" disabled={disabled}><Play size={14} />执行{toolLabel(tool.name)}</button>
      <p className="microcopy">测量会产生新观测。农事的耗时和效果由模型结算。</p>
    </>}
  </form>;
}
