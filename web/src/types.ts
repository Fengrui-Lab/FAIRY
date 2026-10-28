export type Value = string | number | boolean | null | Value[] | { [key: string]: Value };
export type Data = Record<string, unknown>;
export type Vec3 = [number, number, number];
export type ViewMode = 'public' | 'audit';
export type Controller = 'human' | 'agent' | 'external' | 'oracle';

export interface Schema extends Data {
  type?: string;
  title?: string;
  description?: string;
  enum?: unknown[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
  properties?: Record<string, Schema>;
  required?: string[];
}
export interface Tool { name: string; description: string; parameters: Schema; category?: string }
export interface Scenario { scenario_id: string; name: string; description?: string; crop?: string; location?: string; backend?: string; available?: boolean; reason?: string }
export interface Catalog { scenarios: Scenario[]; tools: Tool[]; agent_ready?: boolean; agent_reason?: string }
export interface RunDescriptor extends Data {
  run_id: string;
  scenario_id: string;
  status?: string;
  created_at?: string;
  timezone?: string;
  backend?: string;
  seed?: number;
  audit_assisted?: boolean;
}
export interface Ridge extends Data { ridge_id: number; planted?: boolean; harvested?: boolean; growth_stage?: string }
export interface Farm extends Data {
  farm_id: string;
  name?: string;
  geometry: { num_ridges: number; length_m: number; ridge_width_m: number; rows_per_ridge?: number; boundary_width_m?: number | null };
  ridges: Ridge[];
}
export interface Device extends Data { asset_id: string; kind: string; farm_id?: string; label?: string; state?: Data }
export interface Observation extends Data { tool: string; observed_at?: number | string; available_at?: number | string; data?: unknown; farm_id?: string }
export interface Snapshot extends Data {
  run_id: string;
  revision: number;
  sim_time: number;
  sim_datetime?: string;
  descriptor?: RunDescriptor;
  farms: Farm[];
  devices: Device[];
  observations: Observation[];
  controller: { owner: string; status: string; summary?: string; error?: string | { code: string; message: string } | null };
  current_command?: CommandRecord | null;
  audit_assisted?: boolean;
  events?: Data[];
  inventory?: Data;
}
export interface AuditRidge extends Data { ridge_id: number; values: Data; model_state_day?: string | null }
export interface AuditSnapshot extends Data {
  run_id: string;
  revision: number;
  sim_time: number;
  farms: { farm_id: string; ridges: AuditRidge[] }[];
  units?: Record<string, string>;
}
export interface CommandRecord extends Data {
  command_id: string;
  tool?: string;
  arguments?: Data;
  status: string;
  time_before?: number;
  time_after?: number;
  result?: unknown;
  error?: unknown;
}
export interface HistoryEntry extends Data { revision: number; sim_time: number; tool?: string; command_id?: string; status?: string }
export interface LayoutObject {
  id: string;
  kind: string;
  label: string;
  farm_id?: string;
  asset_id?: string;
  position: Vec3;
  rotation: Vec3;
  asset_url?: string | null;
  binding_kind?: 'farm' | 'device' | 'sensor';
}
export interface Layout { schema_version: number; objects: LayoutObject[] }
