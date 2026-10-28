import { useEffect, useState } from 'react';
import { Sprout, Plus, RotateCcw, Eye, ScanLine, Map, Move, Rotate3D, Save, Check, Radio, History, ArrowRight, Layers, Bot, Square, SlidersHorizontal, ChevronRight, Tractor, X, Leaf, ExternalLink } from 'lucide-react';
import FieldViewport from './FieldViewport';
import ToolForm from './ToolForm';
import { ComparePanel, DataRows, Diagnostic, ObservationChart, Observations, Receipt, StateSummary } from './DataPanels';
import { localDate } from './api';
import useWorkbench from './useWorkbench';
import type { LayoutObject, Vec3 } from './types';

function LayoutEditor({ object, dirty, busy, objects, onSelect, onChange, onSave }: {
  object?: LayoutObject; dirty: boolean; busy: boolean; objects: LayoutObject[];
  onSelect: (id: string) => void; onChange: (id: string, patch: Partial<LayoutObject>) => void; onSave: () => void;
}) {
  const position = (index: number, value: number) => {
    if (!object || !Number.isFinite(value)) return;
    const next = [...object.position] as Vec3; next[index] = value; onChange(object.id, { position: next });
  };
  return <div className="layout-editor">
    <div className="section-heading"><h2>视觉布局</h2><span>{dirty ? '尚未保存' : '已保存'}</span></div>
    <p className="microcopy">修改展示位置与外观。田块面积、设备资源和传感器覆盖保持实验配置。</p>
    <label>对象<select data-testid="layout-object-select" value={object?.id || ''} onChange={e => onSelect(e.target.value)} disabled={busy}><option value="">选择对象</option>{objects.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}</select></label>
    {object && <>
      <label>显示名称<input data-testid="layout-label" value={object.label} maxLength={100} disabled={busy} onChange={e => onChange(object.id, { label: e.target.value })} /></label>
      <div className="three-fields">{['X', 'Y', 'Z'].map((axis, i) => <label key={axis}>{axis}（米）<input type="number" step="0.1" data-testid={`layout-${axis.toLowerCase()}`} disabled={busy} value={object.position[i]} onChange={e => position(i, e.target.valueAsNumber)} /></label>)}</div>
      <label>朝向 Y（度）<input data-testid="layout-rotation-y" type="number" step="1" disabled={busy} value={Math.round(object.rotation[1] * 180 / Math.PI * 100) / 100} onChange={e => { const v = e.target.valueAsNumber; if (Number.isFinite(v)) onChange(object.id, { rotation: [object.rotation[0], v * Math.PI / 180, object.rotation[2]] }); }} /></label>
      {object.kind !== 'field' && <label>GLB 模型<input data-testid="layout-model-url" placeholder="/models/tractor.glb" value={object.asset_url || ''} disabled={busy} onChange={e => onChange(object.id, { asset_url: e.target.value || null })} /><small>模型不可用时使用程序几何体。</small></label>}
      {object.kind === 'field' && <div className="microcopy" data-testid="field-model-note">农田保留按垄选择的程序几何体。GLB 外观仅用于设备与传感器。{object.asset_url && <><p>此农田记录中的模型引用不会用于渲染。</p><button type="button" className="text-button" disabled={busy} onClick={() => onChange(object.id, { asset_url: null })}>清除未使用的模型引用</button></>}</div>}
      <p className="binding-label">绑定 {object.farm_id || ''}{object.asset_id ? ` / ${object.asset_id}` : ''}</p>
    </>}
    <button className="primary full" data-testid="layout-save" disabled={!dirty || busy} onClick={onSave}><Save size={15} />保存视觉布局</button>
  </div>;
}

export default function App() {
  const lab = useWorkbench();
  const [scenario, setScenario] = useState('');
  const [selectedFarm, setSelectedFarm] = useState('');
  const [range, setRange] = useState<[number, number]>([0, 0]);
  const [selectedObject, setSelectedObject] = useState<string | null>(null);
  const [camera, setCamera] = useState<'perspective' | 'top'>('perspective');
  const [editing, setEditing] = useState(false);
  const [transform, setTransform] = useState<'translate' | 'rotate'>('translate');
  const [overlay, setOverlay] = useState<'stage' | 'root_vwc' | 'lai'>('stage');
  const [labels, setLabels] = useState(true);
  const [bottomTab, setBottomTab] = useState<'observations' | 'history' | 'compare' | 'resources'>('observations');
  const [agentTask, setAgentTask] = useState('');
  const snapshot = lab.snapshot;
  const farm = snapshot?.farms.find(f => f.farm_id === selectedFarm) || snapshot?.farms[0];
  const object = lab.layout?.objects.find(o => o.id === selectedObject);
  const selectedDevice = snapshot?.devices.find(d => d.asset_id === object?.asset_id);
  const controller = lab.live?.controller;
  const canOperate = !!snapshot && !lab.readOnly && lab.view === 'public' && !editing && controller?.owner === 'human' && controller.status === 'idle' && !lab.busy;
  const canEdit = !!snapshot && !lab.readOnly && lab.view === 'public' && !lab.busy;
  const timezone = snapshot?.descriptor?.timezone;
  const historyIndex = snapshot ? Math.max(0, lab.history.findIndex(h => h.revision === snapshot.revision)) : 0;
  useEffect(() => { if (lab.catalog && !scenario) setScenario(lab.catalog.scenarios[0]?.scenario_id || ''); }, [lab.catalog, scenario]);
  useEffect(() => {
    setSelectedFarm(lab.live?.farms[0]?.farm_id || ''); setRange([0, 0]); setSelectedObject(null); setEditing(false);
  }, [lab.live?.run_id]);
  useEffect(() => { if (lab.readOnly || lab.view !== 'public') setEditing(false); }, [lab.readOnly, lab.view]);
  const selectRidge = (farmId: string, ridge: number, extend: boolean) => {
    setSelectedObject(null); setSelectedFarm(farmId);
    setRange(old => extend && farmId === selectedFarm ? [Math.min(old[0], ridge), Math.max(old[1], ridge)] : [ridge, ridge]);
  };
  const changeRange = (index: 0 | 1, value: number) => {
    if (!farm || !Number.isInteger(value)) return;
    const n = Math.max(0, Math.min(farm.geometry.num_ridges - 1, value));
    setRange(old => index === 0 ? [n, Math.max(n, old[1])] : [Math.min(old[0], n), n]);
  };
  const switchView = (mode: 'public' | 'audit') => { lab.setView(mode); setEditing(false); if (mode === 'public') setOverlay('stage'); };
  return <div className="app-shell" data-testid="app" data-run-id={snapshot?.run_id || ''} data-revision={snapshot?.revision ?? ''} data-view={lab.view} data-history={lab.historical ? 'true' : 'false'}>
    <header className="app-header">
      <div className="brand"><span className="brand-symbol"><Sprout size={25} strokeWidth={1.6} /></span><div><strong>FAIRY</strong><span>农场实验台</span></div><span className="brand-divider" /><p>观察生长，理解决策。</p></div>
      <div className="header-meta"><span className={`connection ${lab.connected ? 'online' : ''}`}><i />{lab.connected ? '实时连接' : !lab.reachable ? '连接中断' : snapshot ? '快照同步' : '等待实验'}</span><a href="https://github.com/Fengrui-Lab/FAIRY" target="_blank" rel="noreferrer">FAIRY 项目<ExternalLink size={12} /></a></div>
    </header>

    <div className="run-toolbar">
      <div className="scenario-picker"><label htmlFor="scenario">实验场景</label><select id="scenario" value={scenario} onChange={e => setScenario(e.target.value)} disabled={lab.busy}>{lab.catalog?.scenarios.map(s => <option value={s.scenario_id} key={s.scenario_id} disabled={!s.available}>{s.name}{!s.available ? ' · 暂不可用' : ''}</option>)}</select></div>
      <button className="primary" data-testid="create-run" disabled={!scenario || lab.busy || lab.catalog?.scenarios.find(s => s.scenario_id === scenario)?.available === false || controller?.status === 'running'} onClick={() => lab.create(scenario)}><Plus size={16} />新建实验</button>
      <button className="secondary" data-testid="reset-run" disabled={!snapshot || lab.readOnly || lab.busy || controller?.status !== 'idle'} onClick={lab.reset}><RotateCcw size={14} />重置</button>
      <div className="run-clock"><span>当地仿真时间</span><strong>{snapshot?.sim_datetime?.replace('T', ' ').slice(0, 19) || '—'}</strong><small>{timezone || '场景时区'}</small></div>
      {snapshot && <div className={`control-chip ${snapshot.audit_assisted ? 'assisted' : ''}`}>{snapshot.audit_assisted ? '审计辅助实验' : controller?.owner === 'human' ? '人工控制' : controller?.owner === 'agent' ? 'Agent 控制' : controller?.owner === 'external' ? '外部控制' : '已保存运行'}</div>}
    </div>

    {(lab.error || lab.notice) && <div className={`notice-bar ${lab.error ? 'error' : ''}`} role={lab.error ? 'alert' : 'status'}>{lab.error ? <InfoMark /> : <Check size={16} />}<span>{lab.error || lab.notice}</span>{lab.error && <button aria-label="关闭提示" onClick={() => lab.setError('')}><X size={14} /></button>}</div>}

    {!snapshot ? <main className="welcome">
      <div className="welcome-art"><div /><div /><div /><Sprout size={64} strokeWidth={1} /></div>
      <span className="eyebrow">FARM EXPERIMENT WORKBENCH</span><h1>从一块真实计算的农田开始</h1><p>在三维场景中观察田垄、执行农事，<br />沿着同一条时间轴对照公开观测与模型状态。</p>
      <button className="primary" onClick={() => lab.create(scenario)} disabled={!scenario || lab.busy || lab.catalog?.scenarios.find(s => s.scenario_id === scenario)?.available === false}><Plus size={16} />创建第一个实验</button>
      {lab.catalog?.scenarios.find(s => s.scenario_id === scenario)?.reason && <p className="inline-error">{lab.catalog.scenarios.find(s => s.scenario_id === scenario)?.reason}</p>}
      {!!lab.runs.length && <div className="saved-start"><span>已保存的运行</span>{lab.runs.slice(0, 5).map(r => <button key={r.run_id} onClick={() => lab.selectRun(r.run_id)}>{String(r.title || r.scenario_id)}<small>{r.run_id.slice(0, 8)}</small><ChevronRight size={14} /></button>)}</div>}
    </main> : <>
      <div className="workspace">
        <aside className="object-sidebar">
          <div className="section-heading"><h2>场景对象</h2><Layers size={15} /></div>
          {snapshot.farms.map(f => <div className="farm-directory" key={f.farm_id}>
            <button className={`farm-row ${selectedFarm === f.farm_id ? 'selected' : ''}`} onClick={() => setSelectedFarm(f.farm_id)}><Leaf size={17} /><span>{f.name || f.farm_id}<small>{f.geometry.num_ridges} 垄 · {f.geometry.length_m} m</small></span><ChevronRight size={13} /></button>
            {f.farm_id === farm?.farm_id && <><p className="microcopy">点击选垄 · Shift 选择范围</p><div className="ridge-grid">{f.ridges.map(r => <button key={r.ridge_id} data-testid={`ridge-${r.ridge_id}`} title={`第 ${r.ridge_id} 垄 · ${r.growth_stage || '未提供'}`} className={`${range[0] <= r.ridge_id && range[1] >= r.ridge_id ? 'selected' : ''} ${r.harvested ? 'harvested' : r.planted ? 'planted' : ''}`} onClick={e => selectRidge(f.farm_id, r.ridge_id, e.shiftKey)}>{r.ridge_id}</button>)}</div></>}
          </div>)}
          <div className="sidebar-section"><h3>设备与观测设施</h3>{snapshot.devices.map(d => <button className="device-row" key={d.asset_id} onClick={() => { const visual = lab.layout?.objects.find(o => o.asset_id === d.asset_id); if (visual) setSelectedObject(visual.id); }}><Tractor size={15} /><span>{String(d.name || d.label || d.asset_id)}<small>{d.kind}</small></span></button>)}{!snapshot.devices.length && <p className="microcopy">此场景未公开设备目录。</p>}</div>
          <div className="sidebar-section saved-runs"><h3>运行记录</h3><select aria-label="选择已保存运行" data-testid="run-select" value={snapshot.run_id} onChange={e => lab.selectRun(e.target.value)} disabled={lab.busy}>{lab.runs.map(r => <option key={r.run_id} value={r.run_id}>{r.run_id.slice(0, 8)} · {r.status || '已保存'}</option>)}</select><p className="run-id">{snapshot.run_id}</p><p className="microcopy">{String(snapshot.descriptor?.location || '')}<br />{String(snapshot.descriptor?.cultivar || snapshot.descriptor?.crop || '')}<br />{String(snapshot.descriptor?.backend || 'WOFOST')}</p></div>
        </aside>

        <main className="scene-column">
          <div className="scene-toolbar"><div className="segmented"><button data-testid="view-public" className={lab.view === 'public' ? 'active' : ''} onClick={() => switchView('public')}><Eye size={14} />公开观测</button><button data-testid="view-audit" className={lab.view === 'audit' ? 'active audit' : ''} onClick={() => switchView('audit')}><ScanLine size={14} />模型诊断</button></div>
            <div className="scene-actions"><button className={camera === 'top' ? 'active' : ''} title="切换俯视" aria-label="切换俯视" data-testid="camera-top" onClick={() => setCamera(v => v === 'top' ? 'perspective' : 'top')}><Map size={17} /></button><button title="视觉布局编辑" aria-label="视觉布局编辑" data-testid="edit-layout" disabled={!canEdit} className={editing ? 'active' : ''} onClick={() => { setEditing(v => !v); if (!selectedObject) setSelectedObject(lab.layout?.objects[0]?.id || null); }}><SlidersHorizontal size={17} /></button></div>
          </div>
          {(lab.historical || lab.readOnly) && <div className="history-banner"><History size={15} /><span>{lab.historical ? `历史快照 · 版本 ${snapshot.revision}` : '已保存运行 · 只读'}</span>{lab.historical && <button data-testid="return-live" onClick={lab.returnLive}>返回实时<ArrowRight size={13} /></button>}</div>}
          {lab.view === 'audit' && <div className="overlay-toolbar"><label>模型图层<select aria-label="模型图层" value={overlay} onChange={e => setOverlay(e.target.value as typeof overlay)}><option value="stage">公开生育阶段</option><option value="root_vwc">根区水分</option><option value="lai">叶面积指数</option></select></label><span>灰色表示没有模型值</span></div>}
          {editing && <div className="overlay-toolbar"><span>视觉布局编辑</span><div className="segmented compact"><button className={transform === 'translate' ? 'active' : ''} onClick={() => setTransform('translate')}><Move size={13} />移动</button><button className={transform === 'rotate' ? 'active' : ''} onClick={() => setTransform('rotate')}><Rotate3D size={13} />旋转</button></div></div>}
          <div className="canvas-wrap" data-selected-ridge={range[0]} data-selected-end={range[1]}>
            <FieldViewport farms={snapshot.farms} layout={lab.layout} audit={lab.view === 'audit' ? lab.audit : null} selectedFarm={farm?.farm_id || ''} range={range} selectedObject={selectedObject} onRidge={selectRidge} onObject={setSelectedObject} onTransform={lab.updateLayout} camera={camera} editing={editing && !lab.busy} transform={transform} overlay={lab.view === 'public' ? 'stage' : overlay} labels={labels} />
            <label className="labels-toggle"><input type="checkbox" checked={labels} onChange={e => setLabels(e.target.checked)} />对象标签</label>
          </div>
          <div className="field-legend"><span><i className="bare" />未播种</span><span><i className="growing" />生长中</span><span><i className="harvested" />已收割</span><span><i className="selected" />所选范围</span><span className="legend-note">按真实垄编号绑定</span></div>
          <StateSummary snapshot={snapshot} observationCount={lab.observationRecords.length} />
        </main>

        <aside className="inspector">
          {editing ? <LayoutEditor object={object} objects={lab.layout?.objects || []} dirty={lab.layoutDirty} busy={lab.busy} onSelect={setSelectedObject} onChange={lab.updateLayout} onSave={lab.saveLayout} /> : <>
            <div className="section-heading"><h2>{lab.view === 'audit' ? '模型状态' : '田垄与操作'}</h2><span data-testid="selected-ridge">{range[0] === range[1] ? `第 ${range[0]} 垄` : `${range[0]}–${range[1]} 垄`}</span></div>
            <div className="range-inputs"><label>起始垄<input aria-label="起始垄" type="number" min={0} max={(farm?.geometry.num_ridges || 1) - 1} value={range[0]} onChange={e => changeRange(0, e.target.valueAsNumber)} /></label><span>—</span><label>结束垄<input aria-label="结束垄" type="number" min={0} max={(farm?.geometry.num_ridges || 1) - 1} value={range[1]} onChange={e => changeRange(1, e.target.valueAsNumber)} /></label></div>
            {lab.view === 'audit' ? <Diagnostic audit={lab.audit} farm={farm?.farm_id || ''} ridge={range[0]} /> : <>
              {selectedDevice && <details className="selected-device" open><summary>{String(selectedDevice.name || selectedDevice.asset_id)} · {selectedDevice.kind}</summary><DataRows data={selectedDevice.state || {}} /></details>}
              <div className="selected-state"><span>生育阶段</span><strong>{String(farm?.ridges.find(r => r.ridge_id === range[0])?.growth_stage || '未提供')}</strong><small>{range[1] - range[0] + 1} 垄已选择</small></div>
              {lab.readOnly && <p className="read-only-note">历史状态只读。返回活动运行后继续操作。</p>}
              {controller?.owner !== 'human' && !lab.readOnly && <p className="read-only-note">控制者：{controller?.owner}。停止并移交后可人工操作。</p>}
              <ToolForm tools={lab.tools} disabled={!canOperate} onSubmit={lab.submit} range={range} farm={farm?.farm_id || ''} asset={selectedDevice?.asset_id} />
              {lab.command && <Receipt command={lab.command} />}
              <details className="agent-panel"><summary><Bot size={16} />Agent 接管<span>{controller?.status || 'idle'}</span></summary><p className="microcopy">复用当前实验与已完成操作。Agent 只获得公开观测。</p><textarea aria-label="Agent 任务" placeholder="描述本次管理目标，例如检查根区水分并在需要时灌溉。" value={agentTask} maxLength={4000} rows={3} onChange={e => setAgentTask(e.target.value)} disabled={!canOperate} />
                {!lab.catalog?.agent_ready && <p className="microcopy">{lab.catalog?.agent_reason || '尚未配置模型服务'}</p>}
                <div className="button-row"><button className="primary" disabled={!canOperate || !agentTask.trim() || !lab.catalog?.agent_ready} onClick={() => lab.startAgent(agentTask)}><Bot size={14} />启动 Agent</button><button className="secondary" disabled={lab.readOnly || controller?.owner === 'human' || lab.busy} onClick={lab.stop}><Square size={12} />请求停止</button></div>
                {controller?.summary && <p className="agent-summary">{controller.summary}</p>}{controller?.error && <p className="inline-error">{typeof controller.error === 'string' ? controller.error : controller.error.message}</p>}
              </details>
            </>}
          </>}
        </aside>
      </div>

      <section className="timeline">
        <div className="timeline-label"><History size={15} /><strong>运行时间轴</strong><span>{lab.history.length} 个已记录节点</span></div>
        <input aria-label="历史快照时间轴" data-testid="history-slider" type="range" min={0} max={Math.max(0, lab.history.length - 1)} value={lab.historical ? historyIndex : Math.max(0, lab.history.length - 1)} disabled={lab.history.length < 1 || lab.busy} onChange={e => { const frame = lab.history[Number(e.target.value)]; if (frame) void lab.showHistory(frame.revision); }} />
        <span className="timeline-time">{localDate(snapshot.sim_time, timezone)}</span><button className={!lab.historical ? 'live active' : 'live'} onClick={lab.returnLive}><Radio size={13} />实时</button>
      </section>
      <section className="bottom-panel">
        <nav className="bottom-tabs"><button className={bottomTab === 'observations' ? 'active' : ''} onClick={() => setBottomTab('observations')}>观测记录<span>{lab.observationRecords.length}</span></button><button className={bottomTab === 'history' ? 'active' : ''} onClick={() => setBottomTab('history')}>操作时间线</button><button className={bottomTab === 'resources' ? 'active' : ''} onClick={() => setBottomTab('resources')}>资源与设备</button><button className={bottomTab === 'compare' ? 'active' : ''} onClick={() => setBottomTab('compare')}>运行对照</button></nav>
        <div className="bottom-content">
          {bottomTab === 'observations' && <div className="observation-layout"><Observations observations={lab.observationRecords} timezone={timezone} /><ObservationChart observations={lab.observationRecords} timezone={timezone} /></div>}
          {bottomTab === 'history' && <div className="event-list">{lab.history.map((h, i) => <button key={h.revision} className={h.revision === snapshot.revision ? 'selected' : ''} onClick={() => lab.showHistory(h.revision)}><span className="event-index">{String(i + 1).padStart(2, '0')}</span><span><strong>快照 {h.revision}</strong><small>{h.command_id ? String(h.command_id) : '初始状态'}</small></span><time>{localDate(h.sim_time, timezone)}</time><ChevronRight size={14} /></button>)}<p className="microcopy">仅回看实际保存的节点；未记录时段不生成精确中间状态。</p></div>}
          {bottomTab === 'resources' && <div className="resource-columns"><div><h3>农场库存</h3><DataRows data={(farm?.inventory || {}) as Record<string, unknown>} /></div>{snapshot.devices.map(d => <div key={d.asset_id}><h3>{String(d.name || d.asset_id)}</h3><DataRows data={d.state || {}} /></div>)}</div>}
          {bottomTab === 'compare' && <ComparePanel runs={lab.runs} currentRun={snapshot.run_id} />}
        </div>
      </section>
    </>}
    <footer className="app-footer"><span>FAIRY / WOFOST · 交互实验与模型诊断</span><span>{snapshot ? `运行 ${snapshot.run_id.slice(0, 8)} · 版本 ${snapshot.revision}` : '公开观测与模型状态分开记录'}</span></footer>
  </div>;
}

function InfoMark() { return <span className="info-mark">!</span>; }
