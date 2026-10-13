// Review page (WEB_API.md section 12): sessions in the data root, display views, label edits, save, SD import.
import { request } from './api';
import type { Pace } from './types';

export type ReviewStream = 'adc_raw' | 'accel';

export interface ReviewLabel {
  t0: number;
  t1: number;
  i0: number;
  i1: number;
  src?: 'key' | 'phone' | 'review' | 'auto';
  unc_ms?: number;
  label: string;
  person?: string;
  pace?: Pace;
  shoes?: boolean;
}

export interface SessionSummary {
  name: string;
  repo_copy: boolean;
  streams: { stream: ReviewStream; wav: boolean; labels?: number; sample_rate?: number; duration_s?: number | null; error?: string }[];
}

export interface StreamInfo {
  stream: ReviewStream;
  sidecar: string;
  wav: string | null;
  frames: number | null;
  sample_rate: number;
  n_ch: number;
  channels: { ch: number; units: string; scale: number; head: string }[];
  labels: ReviewLabel[];
  version: string;
  backup: boolean;
  /** Positions of the labels whose text is not in labels_allowed (older sessions); a save needs them retagged. */
  labels_off_list?: number[];
}

export interface SessionInfo {
  name: string;
  streams: Partial<Record<ReviewStream, StreamInfo>>;
  persons: string[];
  protocol: string | null;
  /** The protocol's fixed label list; only the shared ones (noise, other, bad) for a protocol without a YAML;
   *  null when the sidecar names no protocol (then no label can be set). */
  labels_allowed: string[] | null;
  labels_note: string | null;
  repo_copy: boolean;
}

export interface ReviewEnvelope {
  frames: number;
  sample_rate: number;
  i0: number;
  i1: number;
  edges: number[];
  units: string[];
  min: (number | null)[][];
  max: (number | null)[][];
}

export interface ReviewSpectrogram {
  frames: number;
  sample_rate: number;
  i0: number;
  i1: number;
  ch: number;
  units: string;
  nfft: number;
  hop: number;
  freq_hz: number[];
  center_index: number[];
  power_db: (number | null)[][];
}

export type EditOp =
  | { kind: 'move'; n: number; edge: 'start' | 'end'; i: number }
  | { kind: 'split'; n: number; i: number }
  | { kind: 'merge'; n: number }
  | { kind: 'retag'; n: number; set: Partial<Record<'label' | 'person' | 'pace' | 'shoes', string | boolean | null>> }
  | { kind: 'delete'; n: number }
  | { kind: 'add'; i0: number; i1: number; label: string; person?: string; pace?: Pace; shoes?: boolean };

export interface SaveResult {
  saved: boolean;
  stream: ReviewStream;
  sidecar: string;
  problems: string[];
  note?: string;
  backup?: string;
  version?: string;
  labels?: ReviewLabel[];
  validation: { ok: boolean; problems: string[]; warnings: string[] } | null;
  repo_copy: { updated: boolean; path?: string; paths?: string[]; reason?: string };
  /** The other stream's sidecar, written in step (same labels through the device clock). */
  peer?: { stream: ReviewStream; sidecar: string; backup: string; version: string; labels: ReviewLabel[]; labels_dropped?: number };
  /** e.g. labels that lie entirely outside the other stream's file and were not copied to it (labels_dropped). */
  warnings?: string[];
}

export interface ImportResult {
  session: string;
  source: string;
  status: 'imported' | 'skipped' | 'invalid' | 'failed';
  problems: string[];
  path: string | null;
  sidecars_copied: string[];
  note: string | null;
  /** e.g. labels outside the protocol's list (retag them on the Review page). */
  warnings?: string[];
}

function q(p: Record<string, string | number | undefined>): string {
  return Object.entries(p)
    .filter(([, v]) => v !== undefined)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&');
}

const base = (name: string) => `/api/review/sessions/${encodeURIComponent(name)}`;

export const reviewApi = {
  sessions: () => request<{ root: string; sessions: SessionSummary[] }>('GET', '/api/review/sessions'),
  open: (name: string) => request<SessionInfo>('GET', base(name)),
  envelope: (name: string, p: { stream: ReviewStream; i0: number; i1: number; columns: number }, signal?: AbortSignal) =>
    request<ReviewEnvelope>('GET', `${base(name)}/envelope?${q(p)}`, undefined, signal),
  spectrogram: (
    name: string,
    p: { stream: ReviewStream; ch: number; i0: number; i1: number; columns: number; nfft: number },
    signal?: AbortSignal,
  ) => request<ReviewSpectrogram>('GET', `${base(name)}/spectrogram?${q(p)}`, undefined, signal),
  edit: (name: string, stream: ReviewStream, labels: ReviewLabel[], op: EditOp) =>
    request<{ labels: ReviewLabel[] }>('POST', `${base(name)}/edit`, { stream, labels, op }),
  save: (name: string, stream: ReviewStream, labels: ReviewLabel[], version: string, peerVersion: string | null) =>
    request<SaveResult>('PUT', `${base(name)}/labels`, { stream, labels, version, peer_version: peerVersion }),
  importSd: (path: string) =>
    request<{ results: ImportResult[]; summary: Record<string, number> }>('POST', '/api/review/import-sd', { path }),
};

/** A small colour ramp (dark blue -> teal -> yellow) for the spectrogram, t in [0, 1]. */
export function ramp(t: number): [number, number, number] {
  const stops: [number, number, number][] = [
    [13, 8, 60],
    [38, 70, 140],
    [32, 145, 140],
    [94, 201, 98],
    [253, 231, 37],
  ];
  const x = Math.min(1, Math.max(0, t)) * (stops.length - 1);
  const k = Math.min(stops.length - 2, Math.floor(x));
  const f = x - k;
  const a = stops[k];
  const b = stops[k + 1];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}
