// Rig checks (WEB_API.md section 11): types and REST calls. Live progress arrives as the `rigcheck` WebSocket event.
import { request } from './api';

export type RigCheckId = 'adc' | 'rate' | 'noise' | 'tap' | 'accel';
export type RigCheckState = 'idle' | 'running' | 'waiting' | 'pass' | 'fail' | 'error' | 'cancelled';

export interface RigCheck {
  id: RigCheckId;
  title: string;
  guide: string[];
  state: RigCheckState;
  prompt: string | null;
  detail: string | null;
  limit: string | null;
  numbers: Record<string, unknown>;
  started: number | null;
  finished: number | null;
}

export interface RigCheckView {
  type: 'rigcheck';
  running: boolean;
  current: RigCheckId | null;
  awaiting_confirm: boolean;
  sim: boolean;
  node: { node_id?: string | null; fw_version?: string | null; link?: string | null; target?: string | null };
  session_started: string | null;
  report_path: string | null;
  report_error: string | null;
  checks: RigCheck[];
  thresholds: Record<string, number>;
}

export const REPORT_URL = '/api/rigcheck/report';

export const rigApi = {
  view: () => request<RigCheckView>('GET', '/api/rigcheck'),
  run: (checks?: RigCheckId[]) => request<RigCheckView>('POST', '/api/rigcheck/run', checks ? { checks } : {}),
  confirm: () => request<RigCheckView>('POST', '/api/rigcheck/confirm', {}),
  cancel: () => request<RigCheckView>('POST', '/api/rigcheck/cancel', {}),
  async report(): Promise<string> {
    const res = await fetch(REPORT_URL);
    if (!res.ok) throw new Error(res.status === 404 ? 'No rig check has run yet.' : `HTTP ${res.status}`);
    return res.text();
  },
};
