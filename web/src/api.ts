import type { AuditSnapshot, Catalog, CommandRecord, Data, HistoryEntry, Layout, LayoutObject, Observation, RunDescriptor, Snapshot, Tool } from './types';

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, { ...init, headers: { ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers } });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail ?? body?.error ?? body;
    throw new Error(typeof detail === 'string' ? detail : detail?.message || `请求未完成（HTTP ${response.status}）`);
  }
  return body as T;
}
const post = <T>(path: string, body: unknown = {}) => request<T>(path, { method: 'POST', body: JSON.stringify(body) });
const runPath = (id: string) => `/runs/${encodeURIComponent(id)}`;

export const api = {
  async catalog(): Promise<Catalog> {
    const raw = await request<{ scenarios: Data[]; agent: { configured: boolean; reason?: string } }>('/catalog');
    return { scenarios: raw.scenarios.map(s => ({ scenario_id: String(s.id), name: String(s.title), backend: String(s.backend || ''), crop: String(s.crop || ''), location: String(s.location || ''), available: s.available !== false, reason: s.reason == null ? undefined : String(s.reason) })), tools: [], agent_ready: raw.agent.configured, agent_reason: raw.agent.reason };
  },
  runs: () => request<{ runs: RunDescriptor[] }>('/runs'),
  current: () => request<Snapshot | null>('/runs/current'),
  create: (scenario_id: string) => post<Snapshot>('/runs', { scenario_id, seed: 0 }),
  snapshot: (id: string) => request<Snapshot>(`${runPath(id)}/snapshot`),
  tools: (id: string) => request<{ tools: Tool[] }>(`${runPath(id)}/tools`),
  audit: (id: string, revision: number, signal?: AbortSignal) => request<AuditSnapshot>(`${runPath(id)}/audit?revision=${revision}`, { signal }),
  history: (id: string) => request<{ frames: HistoryEntry[] }>(`${runPath(id)}/history`),
  observations: (id: string, revision: number, signal?: AbortSignal) => request<{ observations: Observation[] }>(`${runPath(id)}/observations?revision=${revision}`, { signal }),
  historical: (id: string, revision: number) => request<Snapshot>(`${runPath(id)}/history/${revision}`),
  submit: (id: string, command_id: string, tool: string, args: Data) => post<CommandRecord>(`${runPath(id)}/commands`, { command_id, tool, args }),
  command: (id: string, command_id: string) => request<CommandRecord>(`${runPath(id)}/commands/${encodeURIComponent(command_id)}`),
  startAgent: (id: string, task: string) => post<{ snapshot: Snapshot }>(`${runPath(id)}/controller`, { mode: 'llm', task }),
  stop: (id: string) => post<Snapshot>(`${runPath(id)}/stop`),
  reset: (id: string) => post<Snapshot>(`${runPath(id)}/reset`),
  async layout(id: string, snapshot: Snapshot): Promise<Layout> {
    const raw = await request<{ schema_version: number; objects: (Data & { binding: Data })[] }>(`${runPath(id)}/layout`);
    return decodeLayout(raw, snapshot);
  },
  async saveLayout(id: string, layout: Layout, snapshot: Snapshot): Promise<Layout> {
    const raw = await request<{ schema_version: number; objects: (Data & { binding: Data })[] }>(`${runPath(id)}/layout`, { method: 'PUT', body: JSON.stringify({
      schema_version: 1,
      objects: layout.objects.map(o => ({ visual_id: o.id, binding: { kind: o.binding_kind || (o.kind === 'field' ? 'farm' : 'device'), ...(o.farm_id ? { farm_id: o.farm_id } : {}), ...(o.asset_id ? { asset_id: o.asset_id } : {}) }, label: o.label, position: o.position, rotation: o.rotation, model_url: o.asset_url || null })),
    }) });
    return decodeLayout(raw, snapshot);
  },
  compare: (left: string, right: string) => request<{ left: Snapshot; right: Snapshot; compatible: boolean; differences: { field: string; left: unknown; right: unknown }[]; metrics: { left: Data; right: Data } }>(`/compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`),
};

function decodeLayout(raw: { schema_version: number; objects: (Data & { binding: Data })[] }, snapshot: Snapshot): Layout {
  return { schema_version: raw.schema_version, objects: raw.objects.map(o => ({
    id: String(o.visual_id), binding_kind: o.binding.kind as LayoutObject['binding_kind'],
    kind: o.binding.kind === 'farm' ? 'field' : snapshot.devices.find(d => d.asset_id === o.binding.asset_id)?.kind || String(o.binding.kind),
    label: String(o.label), farm_id: typeof o.binding.farm_id === 'string' ? o.binding.farm_id : undefined,
    asset_id: typeof o.binding.asset_id === 'string' ? o.binding.asset_id : undefined,
    position: o.position as LayoutObject['position'], rotation: o.rotation as LayoutObject['rotation'],
    asset_url: typeof o.model_url === 'string' ? o.model_url : null,
  })) };
}

export function localDate(value: number | string | undefined, timezone?: string): string {
  if (value == null) return '—';
  const date = new Date(typeof value === 'number' ? value * 1000 : value);
  if (!Number.isFinite(date.getTime())) return String(value);
  try { return new Intl.DateTimeFormat('zh-CN', { timeZone: timezone || 'UTC', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date); }
  catch { return date.toISOString().slice(0, 16).replace('T', ' '); }
}
export function pretty(value: unknown): string {
  if (value == null) return '未提供';
  if (typeof value === 'number') return Number.isInteger(value) ? value.toLocaleString('zh-CN') : value.toLocaleString('zh-CN', { maximumFractionDigits: 4 });
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}
