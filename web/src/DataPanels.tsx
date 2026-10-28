import { useMemo, useState } from 'react';
import { ArrowLeftRight, Check, Info } from 'lucide-react';
import { api, localDate, pretty } from './api';
import { toolLabel } from './ToolForm';
import type { AuditSnapshot, CommandRecord, Data, Observation, RunDescriptor, Snapshot } from './types';

export function DataRows({ data }: { data: Data }) {
  return <dl className="data-rows">{Object.entries(data).map(([key, value]) => <div key={key}>
    <dt>{key}</dt><dd>{value && typeof value === 'object' ? <details><summary>展开数据</summary><pre>{pretty(value)}</pre></details> : pretty(value)}</dd>
  </div>)}</dl>;
}

export function Receipt({ command }: { command: CommandRecord }) {
  const result = command.result as { ok?: boolean; data?: unknown; error?: unknown } | undefined;
  const success = command.status === 'completed' && result?.ok === true;
  return <div className={`receipt ${success ? 'success' : result?.ok === false ? 'rejected' : ''}`} data-testid="command-receipt" data-command-id={command.command_id}>
    <div className="section-heading"><strong>{success ? '业务操作完成' : result?.ok === false ? '业务操作未成功' : command.status === 'running' || command.status === 'queued' ? '命令处理中' : command.status}</strong><span>{command.tool?.split('__').pop()}</span></div>
    {command.time_before != null && command.time_after != null && <p>经过 {pretty(command.time_after - command.time_before)} 仿真秒</p>}
    <details open={result?.ok === false}><summary>查看完整回执</summary><pre>{pretty(result || command)}</pre></details>
  </div>;
}

export function Observations({ observations, timezone }: { observations: Observation[]; timezone?: string }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? [...observations].reverse() : observations.slice(-4).reverse();
  return <div className="observations">
    {!observations.length && <div className="empty-card"><Info size={17} /><p>尚未测量</p><span>选择观测工具获取数据。刷新页面不会触发测量。</span></div>}
    {shown.map((o, index) => <details key={String(o.observation_id || index)} className="observation-card" open={index === 0}>
      <summary><span>{toolLabel(o.tool)}</span><time>{localDate(o.observed_at, timezone)}</time></summary>
      <p className="microcopy">测量时刻 {String(o.observed_datetime || localDate(o.observed_at, timezone))} · 可用时刻 {localDate(o.available_at, timezone)}</p>
      {o.coverage != null && <p className="coverage">覆盖：{pretty(o.coverage)}</p>}
      <ObservationReadings data={o.data} />
    </details>)}
    {observations.length > 4 && <button className="text-button" onClick={() => setExpanded(v => !v)}>{expanded ? '收起' : `查看全部 ${observations.length} 条观测`}</button>}
  </div>;
}

function ObservationReadings({ data }: { data: unknown }) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return <pre>{pretty(data)}</pre>;
  const body = data as Data;
  const rows = body.soil_sensors || body.root_zone_sensors || body.canopy_sensors;
  if (!Array.isArray(rows)) return <DataRows data={body} />;
  const columns = ['vwc', 'temp_c', 'root_vwc', 'ndvi_proxy'].filter(key => rows.some(row => key in row));
  const titles: Record<string, string> = { vwc: '表层水分 m³/m³', temp_c: '温度 °C', root_vwc: '根区水分 m³/m³', ndvi_proxy: '冠层指数' };
  return <><table className="sensor-table"><thead><tr><th>探头 / 覆盖垄</th>{columns.map(key => <th key={key}>{titles[key]}</th>)}</tr></thead><tbody>{rows.map((row: Data, i) => <tr key={String(row.sensor_id || i)}><td>{String(row.sensor_id || '—')}<small>{row.ridge_start != null ? `${row.ridge_start}–${row.ridge_end}` : row.ridge_id != null ? String(row.ridge_id) : '见来源覆盖'}</small></td>{columns.map(key => <td key={key}>{key === 'ndvi_proxy' && row[key] === -1 ? '未获得有效读数' : pretty(row[key])}</td>)}</tr>)}</tbody></table><details className="raw-observation"><summary>完整观测与来源字段</summary><pre>{pretty(data)}</pre></details></>;
}

const auditLabels: Record<string, string> = { dvs: '发育阶段 DVS', lai: '叶面积指数 LAI', root_vwc: '根区体积含水量', available_n_kg_ha: '可用氮', aboveground_biomass_kg_ha: '地上干物质', storage_organ_dry_kg_ha: '贮藏器官干物质' };

export function Diagnostic({ audit, farm, ridge }: { audit: AuditSnapshot | null; farm: string; ridge: number }) {
  const row = audit?.farms.find(f => f.farm_id === farm)?.ridges.find(r => r.ridge_id === ridge);
  return <div className="diagnostic">
    <div className="audit-banner"><Info size={17} /><span>模型诊断为内部模拟状态。查看行为已记录，之后的人工干预将标记为审计辅助。</span></div>
    {!audit ? <p className="muted">正在获取同一版本的模型诊断…</p> : !row ? <p className="muted">所选垄没有已记录的诊断数据。</p> : <>
      <p className="microcopy">第 {ridge} 垄 · 原生状态日 {row.model_state_day || '未结算'}</p>
      <div className="diagnostic-grid">{Object.entries(row.values).map(([key, value]) => <div key={key} data-quantity={key}>
        <span>{auditLabels[key] || key}</span><strong>{pretty(value)}</strong><small>{audit?.units?.[key] || ''}</small>
      </div>)}</div>
      <p className="microcopy">缺失值表示尚不可用。模型结算日可能早于当前仿真时间。</p>
    </>}
    {Array.isArray(audit?.notes) && audit.notes.length > 0 && <details><summary>模型语义与限制</summary><ul>{audit.notes.map((n, i) => <li key={i}>{String(n)}</li>)}</ul></details>}
  </div>;
}

export function ObservationChart({ observations, timezone }: { observations: Observation[]; timezone?: string }) {
  const [seriesKey, setSeriesKey] = useState('');
  const collection = useMemo(() => {
    const groups = new Map<string, { title: string; unit: string; points: { time: number; value: number }[] }>();
    const metrics: Record<string, { title: string; unit: string }> = { vwc: { title: '表层水分', unit: 'm³/m³' }, root_vwc: { title: '根区水分', unit: 'm³/m³' }, temp_c: { title: '土壤温度', unit: '°C' }, ndvi_proxy: { title: '冠层指数', unit: '' } };
    for (const o of observations) {
      const data = o.data as Data | undefined;
      const coverage = o.coverage as { farm_id?: string; ridge_ids?: number[] } | undefined;
      const readings = data?.root_zone_sensors || data?.soil_sensors || data?.canopy_sensors;
      if (!Array.isArray(readings) || typeof o.observed_at !== 'number') continue;
      for (const row of readings as Data[]) {
        const ridges = row.ridge_start != null ? `${row.ridge_start}–${row.ridge_end}` : row.ridge_id != null ? String(row.ridge_id) : JSON.stringify(coverage?.ridge_ids || []);
        for (const [key, metric] of Object.entries(metrics)) {
          const value = row[key];
          if (typeof value !== 'number' || !Number.isFinite(value) || key === 'ndvi_proxy' && value < 0) continue;
          const sensor = String(row.sensor_id || '未命名探头');
          const id = JSON.stringify([coverage?.farm_id || o.farm_id || '', o.tool, sensor, ridges, key]);
          const group: { title: string; unit: string; points: { time: number; value: number }[] } = groups.get(id) || { title: `${metric.title} · ${sensor} · 垄 ${ridges}`, unit: metric.unit, points: [] };
          group.points.push({ time: o.observed_at, value }); groups.set(id, group);
        }
      }
    }
    return [...groups.entries()].map(([key, group]) => ({ key, ...group, points: group.points.sort((a, b) => a.time - b.time) }));
  }, [observations]);
  const selected = collection.find(s => s.key === seriesKey) || collection[0];
  if (!selected) return null;
  const series = selected.points;
  const minT = series[0].time, maxT = series[series.length - 1].time;
  const low = Math.min(0, ...series.map(p => p.value)), high = Math.max(.01, ...series.map(p => p.value)) * 1.1;
  const points = series.map(p => ({ ...p, x: maxT === minT ? 200 : 32 + (p.time - minT) / (maxT - minT) * 344, y: 104 - (p.value - low) / (high - low) * 80 }));
  return <div className="observation-chart"><div className="section-heading"><strong>已记录观测</strong><span>{selected.unit}</span></div>
    <select aria-label="观测序列" value={selected.key} onChange={e => setSeriesKey(e.target.value)}>{collection.map(s => <option key={s.key} value={s.key}>{s.title}</option>)}</select>
    <svg viewBox="0 0 400 130" role="img" aria-label={`${selected.title} 的实际观测点；横轴为测量时间，纵轴单位 ${selected.unit || '无量纲'}。`}>
      {[24, 64, 104].map(y => <line key={y} x1="24" y1={y} x2="376" y2={y} stroke="#dfe5d8" />)}
      <text x="0" y="28">{high.toFixed(2)}</text><text x="0" y="108">{low.toFixed(1)}</text>
      {points.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r="4" fill="#417758"><title>{localDate(p.time, timezone)} · {p.value}</title></circle>)}
      <text x="24" y="126">{localDate(minT, timezone)}</text><text x="376" y="126" textAnchor="end">{localDate(maxT, timezone)}</text>
    </svg><p className="microcopy">仅显示已记录测量点；点间不补造每日数值。</p>
  </div>;
}

export function ComparePanel({ runs, currentRun }: { runs: RunDescriptor[]; currentRun?: string }) {
  const [left, setLeft] = useState(currentRun || runs[0]?.run_id || '');
  const [right, setRight] = useState(runs.find(r => r.run_id !== currentRun)?.run_id || '');
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.compare>> | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const compare = async () => {
    setBusy(true); setError(''); setResult(null);
    try { setResult(await api.compare(left, right)); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const option = (r: RunDescriptor) => <option key={r.run_id} value={r.run_id}>{String(r.title || r.scenario_id)} · {r.run_id.slice(0, 8)}</option>;
  return <div className="compare-panel">
    <p className="microcopy">对照本工具保存的运行。条件不同可以并列查看，不能直接归因策略优劣。</p>
    <div className="compare-selectors"><select aria-label="左侧运行" data-testid="compare-left" value={left} onChange={e => setLeft(e.target.value)}><option value="">选择运行 A</option>{runs.map(option)}</select><ArrowLeftRight size={18} /><select aria-label="右侧运行" data-testid="compare-right" value={right} onChange={e => setRight(e.target.value)}><option value="">选择运行 B</option>{runs.map(option)}</select></div>
    <button className="primary" data-testid="compare-run" disabled={!left || !right || left === right || busy} onClick={compare}>对照记录</button>
    {error && <p className="inline-error">{error}</p>}
    {result && <>
      <div className={`comparison-verdict ${result.compatible ? 'compatible' : ''}`}><Check size={16} />{result.compatible ? '记录的实验配置相容' : '实验条件存在差异'}</div>
      {!!result.differences.length && <table><thead><tr><th>条件</th><th>A</th><th>B</th></tr></thead><tbody>{result.differences.map(d => <tr key={d.field}><td>{d.field}</td><td>{pretty(d.left)}</td><td>{pretty(d.right)}</td></tr>)}</tbody></table>}
      <table><thead><tr><th>公开指标</th><th>运行 A</th><th>运行 B</th></tr></thead><tbody>{[...new Set([...Object.keys(result.metrics.left), ...Object.keys(result.metrics.right)])].map(k => <tr key={k}><td>{k}</td><td>{pretty(result.metrics.left[k])}</td><td>{pretty(result.metrics.right[k])}</td></tr>)}</tbody></table>
      <p className="microcopy">模型诊断需分别打开对应运行查看；此对照接口只返回公开指标。</p>
    </>}
  </div>;
}

export function StateSummary({ snapshot, observationCount }: { snapshot: Snapshot; observationCount?: number }) {
  const ridges = snapshot.farms.flatMap(f => f.ridges);
  const planted = ridges.filter(r => r.planted).length;
  const harvested = ridges.filter(r => r.harvested).length;
  return <div className="stat-strip">
    <div><span>田垄</span><strong>{ridges.length}<small>垄</small></strong></div>
    <div><span>已播种</span><strong>{planted}<small>垄</small></strong></div>
    <div><span>已收割</span><strong>{harvested}<small>垄</small></strong></div>
    <div><span>实际观测</span><strong>{observationCount ?? snapshot.observations.length}<small>条</small></strong></div>
  </div>;
}
