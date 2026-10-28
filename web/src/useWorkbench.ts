import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';
import type { AuditSnapshot, Catalog, CommandRecord, Data, HistoryEntry, Layout, LayoutObject, Observation, RunDescriptor, Snapshot, Tool, ViewMode } from './types';

export default function useWorkbench() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [runs, setRuns] = useState<RunDescriptor[]>([]);
  const [live, setLive] = useState<Snapshot | null>(null);
  const [historical, setHistorical] = useState<Snapshot | null>(null);
  const [historyPending, setHistoryPending] = useState(false);
  const [audit, setAudit] = useState<AuditSnapshot | null>(null);
  const [recordedObservations, setRecordedObservations] = useState<{ run_id: string; revision: number; observations: Observation[] } | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [layout, setLayout] = useState<Layout | null>(null);
  const [layoutDirty, setLayoutDirty] = useState(false);
  const [view, setView] = useState<ViewMode>('public');
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [connected, setConnected] = useState(false);
  const [reachable, setReachable] = useState(false);
  const [command, setCommand] = useState<CommandRecord | null>(null);
  const selected = useRef<string | null>(null);
  const current = useRef<string | null>(null);
  const historyRequest = useRef(0);
  const requestPending = useRef(false);
  const alive = useRef(true);
  const accept = useCallback((next: Snapshot) => {
    if (selected.current !== next.run_id) return;
    setLive(old => {
      if (selected.current !== next.run_id || old?.run_id === next.run_id && next.revision < old.revision) return old;
      return next;
    });
  }, []);
  const acceptHistory = useCallback((id: string, frames: HistoryEntry[]) => {
    if (selected.current !== id) return;
    setHistory(old => {
      if (selected.current !== id) return old;
      const incomingRevision = frames.at(-1)?.revision ?? -1;
      const savedRevision = old.at(-1)?.revision ?? -1;
      return incomingRevision >= savedRevision ? frames : old;
    });
  }, []);

  const selectRun = useCallback(async (id: string, initial?: Snapshot) => {
    selected.current = id;
    historyRequest.current++;
    setHistorical(null); setHistoryPending(false); setAudit(null); setRecordedObservations(null); setCommand(null); setTools([]); setHistory([]); setLayout(null); setLayoutDirty(false); setError('');
    if (initial) setLive(initial); else setLive(null);
    let next: Snapshot;
    try { next = initial || await api.snapshot(id); }
    catch (e) { if (selected.current === id) throw e; return; }
    if (selected.current !== id) return;
    accept(next);
    const results = await Promise.allSettled([api.tools(id), api.history(id), api.layout(id, next)]);
    if (selected.current !== id) return;
    if (results[0].status === 'fulfilled') setTools(results[0].value.tools);
    if (results[1].status === 'fulfilled') acceptHistory(id, results[1].value.frames);
    if (results[2].status === 'fulfilled') setLayout(results[2].value);
    const failure = results.find(r => r.status === 'rejected');
    if (failure?.status === 'rejected') setError(String(failure.reason));
  }, [accept, acceptHistory]);

  useEffect(() => {
    alive.current = true;
    let cancelled = false;
    void Promise.all([api.catalog(), api.runs(), api.current()]).then(async ([c, rs, active]) => {
      if (cancelled) return;
      setCatalog(c); setRuns(rs.runs); setReachable(true); current.current = active?.run_id || null; setCurrentRunId(current.current);
      if (active) await selectRun(active.run_id, active);
    }).catch(e => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; alive.current = false; };
  }, [selectRun]);

  useEffect(() => {
    if (!live?.run_id) return;
    const id = live.run_id;
    let disposed = false;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout>;
    let reconnect: ReturnType<typeof setTimeout>;
    const connect = () => {
      if (disposed || selected.current !== id) return;
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/runs/${encodeURIComponent(id)}/stream`);
      socket.onopen = () => { if (!disposed) { setConnected(true); setReachable(true); } };
      socket.onmessage = event => {
        try { const message = JSON.parse(event.data); if (message.type === 'snapshot' && message.snapshot) accept(message.snapshot); } catch { /* The next HTTP snapshot recovers a malformed transport frame. */ }
      };
      socket.onclose = () => { if (!disposed) { setConnected(false); reconnect = setTimeout(connect, 3000); } };
      socket.onerror = () => socket?.close();
    };
    const poll = async () => {
      try {
        const [next, frames, active, rs] = await Promise.all([api.snapshot(id), api.history(id), api.current(), api.runs()]);
        if (disposed || selected.current !== id) return;
        setReachable(true);
        const oldCurrent = current.current;
        current.current = active?.run_id || null;
        setCurrentRunId(current.current); setRuns(rs.runs);
        if (active && id === oldCurrent && active.run_id !== id) { await selectRun(active.run_id, active); return; }
        accept(next); acceptHistory(id, frames.frames);
      } catch { if (!disposed) { setConnected(false); setReachable(false); } }
      if (!disposed) timer = setTimeout(poll, 1800);
    };
    if (id === currentRunId && live.status === 'active') connect();
    timer = setTimeout(poll, 700);
    return () => { disposed = true; clearTimeout(timer); clearTimeout(reconnect); socket?.close(); setConnected(false); };
  }, [live?.run_id, live?.status, currentRunId, accept, acceptHistory, selectRun]);

  const snapshot = historical || live;
  useEffect(() => {
    if (!snapshot) return;
    const id = snapshot.run_id, revision = snapshot.revision;
    const abort = new AbortController();
    void api.observations(id, revision, abort.signal).then(result => {
      if (!abort.signal.aborted && selected.current === id) setRecordedObservations({ run_id: id, revision, observations: result.observations });
    }).catch(e => { if (!abort.signal.aborted && selected.current === id) setError(e.message); });
    return () => abort.abort();
  }, [snapshot?.run_id, snapshot?.revision]);
  useEffect(() => {
    setAudit(null);
    if (view !== 'audit' || !snapshot) return;
    const abort = new AbortController();
    const id = snapshot.run_id;
    void api.audit(id, snapshot.revision, abort.signal).then(result => {
      if (!abort.signal.aborted && selected.current === id) setAudit(result);
    }).catch(e => { if (!abort.signal.aborted) setError(e.message); });
    return () => abort.abort();
  }, [view, snapshot?.run_id, snapshot?.revision]);

  const perform = async (fn: () => Promise<void>) => {
    if (requestPending.current) return;
    requestPending.current = true; setBusy(true); setError(''); setNotice('');
    try { await fn(); } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : String(e)); }
    finally { requestPending.current = false; if (alive.current) setBusy(false); }
  };
  const create = (scenario: string) => perform(async () => {
    const next = await api.create(scenario); current.current = next.run_id; setCurrentRunId(next.run_id);
    await selectRun(next.run_id, next);
    const rs = await api.runs();
    if (selected.current === next.run_id) { setRuns(rs.runs); setNotice('新实验已创建。观测由你或 Agent 显式发起。'); }
  });
  const reset = () => perform(async () => {
    if (!live) return;
    const next = await api.reset(live.run_id); current.current = next.run_id; setCurrentRunId(next.run_id);
    await selectRun(next.run_id, next);
    const rs = await api.runs();
    if (selected.current === next.run_id) { setRuns(rs.runs); setNotice('已创建新的初始运行，旧运行保留在历史中。'); }
  });
  const submit = (tool: string, args: Data) => perform(async () => {
    if (!live || historical || historyPending || view !== 'public') return;
    const id = live.run_id;
    const commandId = crypto.randomUUID();
    let result: CommandRecord;
    try { result = await api.submit(id, commandId, tool, args); }
    catch (error) {
      // A lost POST response may follow a completed side effect. Query the same ID once; never resubmit it.
      try { result = await api.command(id, commandId); }
      catch { throw new Error(`命令结果未确认，未自动重试。命令 ID：${commandId}。${error instanceof Error ? error.message : ''}`); }
    }
    if (selected.current === id) setCommand(result);
    while (['queued', 'running'].includes(result.status) && selected.current === id && alive.current) {
      await new Promise(resolve => setTimeout(resolve, 500));
      result = await api.command(id, commandId);
      if (selected.current === id) setCommand(result);
    }
    if (selected.current !== id) return;
    const [next, frames] = await Promise.all([api.snapshot(id), api.history(id)]);
    if (selected.current !== id) return;
    accept(next); acceptHistory(id, frames.frames);
    setNotice(result.status === 'completed' ? '命令已返回，请查看业务回执。' : '命令未完整结束，请查看记录。');
  });
  const showHistory = async (revision: number) => {
    if (!live) return;
    const requestId = ++historyRequest.current;
    const id = live.run_id;
    setHistoryPending(true);
    try {
      const frame = await api.historical(id, revision);
      if (selected.current === id && requestId === historyRequest.current) setHistorical(frame);
    } catch (e) { if (requestId === historyRequest.current) setError(e instanceof Error ? e.message : String(e)); }
    finally { if (requestId === historyRequest.current) setHistoryPending(false); }
  };
  const returnLive = () => { historyRequest.current++; setHistorical(null); setHistoryPending(false); };
  const updateLayout = (id: string, patch: Partial<LayoutObject>) => { setLayout(old => old ? { ...old, objects: old.objects.map(o => o.id === id ? { ...o, ...patch } : o) } : old); setLayoutDirty(true); };
  const saveLayout = () => perform(async () => {
    if (!live || !layout) return;
    const id = live.run_id;
    const saved = await api.saveLayout(id, layout, live);
    if (selected.current === id) { setLayout(saved); setLayoutDirty(false); setNotice('视觉布局已保存，实验物理参数保持原配置。'); }
  });
  const startAgent = (task: string) => perform(async () => { if (!live) return; const id = live.run_id; const next = await api.startAgent(id, task); if (selected.current === id) accept(next.snapshot); });
  const stop = () => perform(async () => { if (!live) return; const id = live.run_id; const next = await api.stop(id); if (selected.current === id) { accept(next); setNotice('已请求在安全工具边界停止。'); } });
  const consistentAudit = view === 'audit' && audit && snapshot && audit.run_id === snapshot.run_id && audit.revision === snapshot.revision ? audit : null;
  const observationRecords = recordedObservations && snapshot && recordedObservations.run_id === snapshot.run_id && recordedObservations.revision === snapshot.revision ? recordedObservations.observations : snapshot?.observations || [];
  return { catalog, runs, snapshot, live, audit: consistentAudit, observationRecords, history, tools, layout, layoutDirty, view, setView, currentRunId, busy, error, setError, notice, connected, reachable, command,
    create, reset, selectRun: (id: string) => perform(() => selectRun(id)), submit, showHistory, returnLive, updateLayout, saveLayout, startAgent, stop,
    historical: !!historical || historyPending, readOnly: !!historical || historyPending || !!live && (live.run_id !== currentRunId || live.status !== 'active') };
}
