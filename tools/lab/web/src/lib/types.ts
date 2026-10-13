// Types of the JSON in WEB_API.md. Only the fields the UI reads are typed.

export type LinkState = 'disconnected' | 'connecting' | 'connected' | 'disconnecting';
export type LinkKind = 'tcp' | 'serial' | 'sim' | null;
export type UnitName = 'counts' | 'V' | 'g';

export interface ConnectionEvent {
  type: 'connection';
  state: LinkState;
  link: LinkKind;
  target: string | null;
  embedded_sim: boolean;
  error: string | null;
  t: number;
}

export interface HelloStream {
  id: number;
  name: string;
  n_ch: number;
  nominal_hz: number;
  bits: number;
  full_scale: number;
  clock: string;
  fir_taps: number;
  fir_delay: number;
}

export interface HelloEvent {
  type: 'hello';
  proto: number;
  fw_version: string;
  node_id: string;
  t_dev_us: number;
  streams: HelloStream[];
  heads: { port: number; descriptor: unknown }[];
  t: number;
}

export interface ConfigChannel {
  gain: number;
  scale: number;
  units: UnitName;
}
export interface ConfigStream {
  id: number;
  name: string;
  channels: ConfigChannel[];
}
export interface ConfigEvent {
  type: 'config';
  streams: ConfigStream[];
  accel_range_g: number;
  status_period_ms: number;
  t: number;
}

export interface Loss {
  device: number;
  link: number;
  host: number;
  host_exact: boolean;
  host_max: number;
  pending: number;
  received: number;
  missing: number;
  final: boolean;
  incomplete: boolean;
  protocol_bug: boolean;
}

export interface Levels {
  mean: number | null;
  rms: number | null;
  std: number | null;
  peak: number | null;
  clipped: number;
  n: number;
  units: UnitName;
}

export interface StatusStream {
  id: number;
  name: string;
  n_ch: number;
  nominal_hz: number;
  running: boolean;
  rate_hz_status: number | null;
  rate_hz_fit: number | null;
  offset_pct_status: number | null;
  offset_pct_fit: number | null;
  produced: number;
  node_device_dropped: number;
  node_clipped: number;
  loss: Loss | null;
  levels: (Levels | null)[] | null;
  epoch: number;
  head: number;
}

export interface StatusLink {
  type: string;
  target: string;
  rtt_ms?: number | null;
  bad_frames?: number;
  lost_frames?: number;
  rx_bytes_per_s?: number | null;
  stale?: boolean;
}

export interface Health {
  queue_fill: number | null;
  heap_free: number | null;
  temp_c: number | null;
  rssi_dbm: number | null;
  sd_state: number | null;
  sd_free_mb: number | null;
}

export interface StatusEvent {
  type: 'status';
  state: LinkState;
  node: { node_id: string; fw_version: string; proto: number } | null;
  link: StatusLink | null;
  health: Health | null;
  streams: StatusStream[];
  acquiring: boolean;
  recording: boolean;
  t: number;
}

export interface LogEvent {
  type: 'log';
  source: 'node' | 'host';
  level: number;
  level_name: string;
  t_dev_us: number | null;
  tag: string;
  msg: string;
  t: number;
}

export interface ErrorEvent {
  type: 'error';
  id: number;
  command: string;
  code: string;
  node_code?: number | null;
  event_id?: number | null;
  message: string;
  t: number;
}

export interface StreamResetEvent {
  type: 'stream_reset';
  stream: number;
  name: string;
  epoch: number;
  t: number;
}

export interface StateSnapshot {
  type: 'state';
  clients: number;
  connection?: ConnectionEvent;
  hello?: HelloEvent;
  config?: ConfigEvent;
  status?: StatusEvent;
}

export interface PortInfo {
  device: string;
  description: string;
  hwid: string;
  manufacturer: string | null;
  serial_number: string | null;
  vid_pid: string | null;
  is_node: boolean;
}

export interface ViewCommon {
  stream: number;
  name: string;
  n_ch: number;
  epoch: number;
  fs_hz: number;
  fs_source: string;
  nominal_hz: number;
  scale: number[];
  units: UnitName[];
  lo: number;
  hi: number;
  head: number;
  oldest: number | null;
}
export interface EnvelopeResponse extends ViewCommon {
  columns: number;
  samples_per_column: number;
  min: (number | null)[][];
  max: (number | null)[][];
  gap: number[];
  valid_samples: number;
}
export interface LevelsResponse extends ViewCommon {
  channels: Levels[];
}
export interface PsdResponse extends ViewCommon {
  nperseg: number;
  n_segments: number;
  freq_hz: number[];
  psd: ((number | null)[] | null)[];
  psd_units: string[];
}
export interface SpectrogramResponse extends ViewCommon {
  channel: number;
  nfft: number;
  hop: number;
  freq_hz: number[];
  center_index: number[];
  db: ((number | null)[] | null)[];
  db_units: string;
}

export interface Toast {
  key: number;
  kind: 'error' | 'info';
  text: string;
}

// ------------------------------------------------------------------ recorder (WEB_API.md section 9)

export interface ApiErrorDetail {
  loc: (string | number)[];
  msg: string;
}

export interface DataRoot {
  configured: boolean;
  ok: boolean;
  path: string | null;
  source: 'env' | 'config' | null;
  config_file: string | null;
  free_gb: number | null;
  error: { code: string; message: string } | null;
}

export interface ChannelDefaults {
  head?: string | null;
  serial?: string | null;
  port?: number | null;
  mount?: string | null;
}

export interface OptionChannel {
  ch: number;
  units: UnitName;
  gain: number;
  scale: number;
  defaults?: ChannelDefaults | null;
}

export interface OptionStream {
  name: string;
  n_ch: number;
  nominal_hz: number;
  clock: string;
  recordable: boolean;
  channels: OptionChannel[];
}

export type Pace = 'slow' | 'normal' | 'fast';

export interface LabelState {
  label: string;
  person: string | null;
  pace: Pace | null;
  shoes: boolean | null;
}

export interface Blocker {
  code: string;
  message: string;
}

export interface RecordOptions {
  state: RecordState;
  data_root: DataRoot;
  protocols: string[];
  default_protocol: string;
  person_pattern: string;
  node: {
    node_id: string;
    fw_version: string;
    link: string | null;
    simulated: boolean;
    streams: OptionStream[];
  } | null;
  label_state: LabelState;
  marker: { bind: string; port: number; hosts: string[] };
  can_start: boolean;
  blockers: Blocker[];
}

export interface SensorEntry {
  stream: 'adc_raw' | 'accel';
  ch?: number;
  position_m: number[];
  port?: number;
  head?: string;
  serial?: string;
  mount?: string;
}

export interface SessionForm {
  site: string;
  room: string;
  floor?: string;
  surface?: string;
  persons: string[];
  protocol: string;
  streams: ('adc_raw' | 'accel')[];
  sensors: SensorEntry[];
  notes?: string;
  marker: boolean;
  marker_host?: string;
}

export type RecordState = 'idle' | 'starting' | 'recording' | 'stopping' | 'finalizing';

export interface RecLoss {
  device: number;
  link: number;
  host: number;
  host_exact?: boolean;
  host_max?: number;
  final?: boolean;
  incomplete?: boolean;
  protocol_bug?: boolean;
}

export interface RecStreamProgress {
  stream: string;
  file: string;
  frames_written: number;
  frames_received: number;
  queue_depth: number;
  overflow_packets: number;
  rejected_packets: number;
  error: string | null;
  loss: RecLoss | null;
}

export interface ResultStream {
  stream: string;
  wav: string;
  sidecar: string;
  frames: number;
  duration_s: number;
  sample_rate: number;
  sample_rate_measured: number | null;
  rate_source: string;
  first_sample: number;
  loss: RecLoss;
  incomplete: boolean;
  labels: number;
  problems: string[];
}

export interface RecordResult {
  ok: boolean;
  session: string;
  ended_by: string;
  stored: 'data_root' | 'staging' | string;
  path: string;
  streams: ResultStream[];
  n_labels: number;
  sidecars_copied: string[] | null;
  sidecars_copy_skipped: string | null;
  validation: { ok: boolean; problems: string[] } | null;
  problems: string[];
}

export interface RecordingEvent {
  type?: 'recording';
  state: RecordState;
  session: string | null;
  protocol: string | null;
  elapsed_s: number | null;
  streams: RecStreamProgress[];
  n_labels: number;
  marking: boolean;
  label_state: LabelState | null;
  marker: { active: boolean; port: number } | null;
  marker_error: string | null;
  last: RecordResult | null;
  t?: number;
}

export interface Mark {
  id: number;
  state: 'open' | 'closed';
  label: string;
  person: string | null;
  pace: Pace | null;
  shoes: boolean | null;
  src: string;
  start_s: number;
  end_s: number | null;
  rtt_ms: number | null;
}

export interface LabelEvent {
  type: 'label';
  action: 'start' | 'end' | 'delete';
  mark: Mark | { id: number };
  n_labels: number;
  t: number;
}

export type MarkerInfo =
  | { active: true; host: string; port: number; url: string; hosts: string[]; qr_svg: string }
  | { active: false; reason: string };
