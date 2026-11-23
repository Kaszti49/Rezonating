// Locate page (WEB_API.md section 15): types and REST calls. Steps arrive as `locate_step` WebSocket events,
// the state as the cached `locate` event.
import { request } from './api';

export interface LocateCalibration {
  spacing_m: number;
  c_mps: number;
  tau0_s: number;
  gain_ratio: number;
  swap_sides: boolean;
  ref_amp: number | null;
  ref_m: number;
  decay_n: number;
  calibrated: string[];
}

export interface LocateState {
  type: 'locate';
  calibration: LocateCalibration;
  calibrating: { spot: 'left' | 'right'; got: number; want: number } | null;
  notes: string[];
  steps: number;
  skipped_gaps: number;
  noise_rms: number | null;
  fs_hz: number | null;
  recent?: LocateStep[];
}

export type Side = 'left' | 'right' | 'unsure';
export type Band = 'near' | 'mid' | 'far' | 'unknown';

export interface LocateStep {
  type: 'locate_step';
  id: number;
  index: number;
  epoch: number;
  calibration_step: boolean;
  tau_s: number;
  cc: number;
  amp: [number, number];
  side: Side;
  side_votes: { timing: string; amplitude: string };
  phi_deg: number | null;
  phi_sigma_deg: number;
  distance_m: number | null;
  distance_band: Band;
  confidence: number;
  lag_limited: boolean;
  t?: number;
}

export const locateApi = {
  view: () => request<LocateState>('GET', '/api/locate'),
  calibrate: (spot: 'left' | 'right', steps = 5) => request<LocateState>('POST', '/api/locate/calibrate', { spot, steps }),
  cancel: () => request<LocateState>('POST', '/api/locate/calibrate/cancel', {}),
  reset: () => request<LocateState>('POST', '/api/locate/calibrate/reset', {}),
  settings: (s: { c_mps?: number; decay_n?: number; spacing_m?: number }) =>
    request<LocateState>('POST', '/api/locate/settings', s),
  clear: () => request<LocateState>('POST', '/api/locate/clear', {}),
};

/** Radial extent (metres) drawn for a distance band; `unknown` spans the whole view, faintly. */
export function bandRange(s: LocateStep, maxM: number): [number, number] {
  if (s.distance_m !== null) {
    const r = s.distance_m;
    return [Math.max(0.15, r * 0.7), Math.min(maxM, r * 1.4)];
  }
  return [0.3, maxM];
}
