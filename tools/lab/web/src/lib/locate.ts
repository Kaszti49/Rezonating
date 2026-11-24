// Locate (WEB_API.md section 15): types and REST calls. Steps arrive as `locate_step` WebSocket events,
// the state as the cached `locate` event.
import { request } from './api';

/** `same`: the step came from the front, the back, or too far away to tell. */
export type Side = 'left' | 'right' | 'same';

/** Rig health from the signal itself. */
export interface RigHealth {
  rest: [number, number] | null;
  quiet: number | null;
  /** Share of the last steps where the two geophones move alike; null before five steps. */
  agree: number | null;
  agree_n: number;
  baseline: { rest: [number, number]; quiet: number; saved?: string } | null;
  warnings: string[];
}

export interface LocateState {
  type: 'locate';
  swap_sides: boolean;
  steps: number;
  sides: Record<Side, number>;
  health: RigHealth;
  skipped_gaps: number;
  skipped_clipped: number;
  noise_rms: number | null;
  fs_hz: number | null;
  recent?: LocateStep[];
}

export interface LocateStep {
  type: 'locate_step';
  id: number;
  index: number;
  epoch: number;
  side: Side;
  reason: 'louder' | 'first' | 'same';
  /** Majority of the walk's last three steps. */
  walk_side: Side;
  walk_steps: number;
  tau_s: number;
  cc: number;
  amp: [number, number];
  ratio: number;
  /** The two geophones move alike (rig health; the rule does not use it). */
  agree: boolean;
  t?: number;
}

export const SIDE_WORD: Record<Side, string> = { left: 'LEFT', right: 'RIGHT', same: 'FRONT, BACK or FAR' };
export const REASON_TEXT: Record<LocateStep['reason'], string> = {
  louder: 'louder on that side',
  first: 'heard first on that side',
  same: 'about the same on both',
};

export const locateApi = {
  view: () => request<LocateState>('GET', '/api/locate'),
  swap: (swap_sides: boolean) => request<LocateState>('POST', '/api/locate/settings', { swap_sides }),
  saveBaseline: () => request<LocateState>('POST', '/api/locate/baseline', {}),
  clear: () => request<LocateState>('POST', '/api/locate/clear', {}),
};
