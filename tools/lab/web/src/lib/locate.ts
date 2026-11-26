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
  /** first: one geophone heard it clearly first; louder: no clear timing, but 1.5 times louder on one side. */
  reason: 'first' | 'louder' | 'same';
  /** Majority of the walk's last three steps. */
  walk_side: Side;
  walk_steps: number;
  tau_s: number;
  /** How much earlier the side's geophone heard it (0 unless `reason` is first). */
  lead_s: number;
  cc: number;
  amp: [number, number];
  ratio: number;
  /** The two geophones move alike (rig health; the rule does not use it). */
  agree: boolean;
  t?: number;
}

export const SIDE_WORD: Record<Side, string> = { left: 'LEFT', right: 'RIGHT', same: 'FRONT, BACK or FAR' };
export const REASON_TEXT: Record<LocateStep['reason'], string> = {
  first: 'heard first on that side',
  louder: 'much louder on that side',
  same: 'no clear difference',
};

/** A step the radar draws solid: heard first by at least this much (smaller leads are drawn hollow). */
export const CLEAR_LEAD_S = 0.3e-3;

/** The steps of the current walk (the newest `walk_steps` of the trail), oldest first. */
export function walkSteps(steps: LocateStep[]): LocateStep[] {
  const last = steps.length ? steps[steps.length - 1] : null;
  return last ? steps.slice(Math.max(0, steps.length - last.walk_steps)) : [];
}

/** How many of the walk's last three steps agree with its side, as "2 of 3"; '' before two steps. */
export function walkAgreement(steps: LocateStep[]): string {
  const walk = walkSteps(steps);
  const last = walk[walk.length - 1];
  if (!last || walk.length < 2 || last.walk_side === 'same') return '';
  const tail = walk.slice(-3);
  return `${tail.filter((s) => s.side === last.walk_side).length} of ${tail.length} steps`;
}

export const locateApi = {
  view: () => request<LocateState>('GET', '/api/locate'),
  swap: (swap_sides: boolean) => request<LocateState>('POST', '/api/locate/settings', { swap_sides }),
  saveBaseline: () => request<LocateState>('POST', '/api/locate/baseline', {}),
  clear: () => request<LocateState>('POST', '/api/locate/clear', {}),
};
