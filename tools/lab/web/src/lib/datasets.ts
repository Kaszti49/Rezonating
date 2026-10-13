// Datasets page (WEB_API.md section 13): the session index, filters, the data/manifest.json builder.
import { request } from './api';

export interface LossTotals {
  device: number;
  link: number;
  host: number;
}

/** One manifest entry (rezonating_ml.manifest format v1) as the index keeps it: `sha256` is null until hashed. */
export interface DatasetStream {
  session: string;
  stream: 'adc_raw' | 'adc_dec' | 'accel' | null;
  wav: string;
  sidecar: string;
  wav_present: boolean;
  sha256: string | null;
  size_bytes: number | null;
  frames: number | null;
  channels: number | null;
  fs_header_hz: number | null;
  fs_measured_hz: number | null;
  duration_s: number | null;
  start_utc: string | null;
  protocol: string | null;
  floor: string | null;
  surface: string[];
  people: string[];
  label_count: number;
  loss: LossTotals | null;
  simulated: boolean;
  incomplete: boolean;
  valid: boolean;
  errors: string[];
}

export interface DatasetRow {
  session: string;
  date: string;
  site: string;
  room: string;
  take: string;
  floor: string | null;
  protocol: string | null;
  people: string[];
  surface: string[];
  duration_s: number | null;
  label_count: number;
  streams_n: number;
  valid: boolean;
  errors: string[];
  warnings: string[];
  wav_present: boolean;
  wav_missing: number;
  simulated: boolean;
  incomplete: boolean;
  loss: LossTotals | null;
  in_repo: boolean;
  /** Where the sidecars were read: the repository's data/, or next to the WAVs on the data root (not in repo). */
  sidecar_source: 'repo' | 'data_root' | null;
  on_data_root: boolean;
  unmatched_wavs: string[];
  size_bytes: number;
  streams: DatasetStream[];
}

export interface Totals {
  sessions: number;
  hours: number;
  labels: number;
  invalid: number;
  wav_missing: number;
  simulated: number;
  per_person: { person: string; sessions: number; hours: number }[];
}

export interface RefreshStats {
  sidecars: number;
  sessions_rebuilt: number;
  sidecars_reused: number;
  /** Sidecars read from the data root (sessions with none in the repository). */
  sidecars_data_root: number;
  sidecars_removed: number;
  cache_dropped: boolean;
  seconds: number;
  at: number;
}

export interface IndexInfo {
  db: string;
  refresh: RefreshStats | null;
  data_root: { ok: boolean; path: string | null; error: { code: string; message: string } | null };
  manifest: { path: string; exists: boolean };
}

export interface DatasetList {
  index: IndexInfo;
  facets: { protocols: string[]; floors: string[]; people: string[] };
  all: number;
  totals: Totals;
  sessions: DatasetRow[];
}

export interface DatasetFilters {
  protocol?: string;
  floor?: string;
  person?: string;
  valid?: boolean;
  wav?: 'present' | 'missing';
  simulated?: boolean;
  date_from?: string;
  date_to?: string;
}

export interface ManifestRequest {
  sessions?: string[];
  filters?: DatasetFilters;
  include_simulated: boolean;
  include_invalid: boolean;
}

export interface Excluded {
  session: string;
  reason: string;
  wav?: string;
}

export interface ManifestPlan {
  sessions: string[];
  entries: number;
  hours: number;
  bytes_to_hash: number;
  wav_missing: number;
  excluded: Excluded[];
  include_simulated: boolean;
  include_invalid: boolean;
  out: string;
  exists: boolean;
}

export interface ManifestResult {
  written: string;
  created: string;
  sessions: string[];
  entries: number;
  hours: number;
  bytes_hashed: number;
  wav_missing: number;
  unmatched_wavs: string[];
  excluded: Excluded[];
  seconds: number;
}

function query(f: DatasetFilters): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v !== undefined && v !== '') q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : '';
}

export const datasetsApi = {
  list: (f: DatasetFilters = {}, signal?: AbortSignal) =>
    request<DatasetList>('GET', `/api/datasets/sessions${query(f)}`, undefined, signal),
  session: (name: string) => request<DatasetRow>('GET', `/api/datasets/sessions/${encodeURIComponent(name)}`),
  hash: (name: string) =>
    request<{ session: string; wavs: { wav: string; sha256: string | null }[] }>(
      'POST',
      `/api/datasets/sessions/${encodeURIComponent(name)}/hash`,
    ),
  rebuild: () => request<{ refresh: RefreshStats; index: IndexInfo }>('POST', '/api/datasets/rebuild'),
  preview: (body: ManifestRequest) => request<ManifestPlan>('POST', '/api/datasets/manifest/preview', body),
  build: (body: ManifestRequest) => request<ManifestResult>('POST', '/api/datasets/manifest', body),
};
