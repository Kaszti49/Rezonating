import type {
  ApiErrorDetail,
  DataRoot,
  EnvelopeResponse,
  LabelState,
  LevelsResponse,
  LogEvent,
  Mark,
  MarkerInfo,
  PortInfo,
  ProtocolInfo,
  PsdResponse,
  RecordingEvent,
  RecordOptions,
  RecordResult,
  RunnerView,
  SessionForm,
  SpectrogramResponse,
  StateSnapshot,
} from './types';

export class ApiError extends Error {
  code: string;
  status: number;
  nodeCode: number | null;
  eventId: number | null;
  /** 422 form errors: `[{loc, msg}]` (the server never echoes the rejected value). */
  details: ApiErrorDetail[];
  constructor(
    status: number,
    code: string,
    message: string,
    nodeCode: number | null,
    eventId: number | null,
    details: ApiErrorDetail[] = [],
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.nodeCode = nodeCode;
    this.eventId = eventId;
    this.details = details;
  }
}

export async function request<T>(method: string, url: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const init: RequestInit = { method, signal };
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError(0, 'server_unreachable', 'The lab server did not answer. Is `rzlab serve` still running?', null, null);
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = (data as { error?: Record<string, unknown> } | null)?.error;
    throw new ApiError(
      res.status,
      typeof err?.code === 'string' ? err.code : `http_${res.status}`,
      typeof err?.message === 'string' ? err.message : `HTTP ${res.status}`,
      typeof err?.node_code === 'number' ? err.node_code : null,
      typeof err?.event_id === 'number' ? err.event_id : null,
      parseDetails(err?.details),
    );
  }
  return data as T;
}

function parseDetails(v: unknown): ApiErrorDetail[] {
  if (!Array.isArray(v)) return [];
  const out: ApiErrorDetail[] = [];
  for (const d of v) {
    if (d && typeof d === 'object' && Array.isArray((d as ApiErrorDetail).loc) && typeof (d as ApiErrorDetail).msg === 'string')
      out.push({ loc: (d as ApiErrorDetail).loc, msg: (d as ApiErrorDetail).msg });
  }
  return out;
}

function qs(params: Record<string, string | number | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined) p.set(k, String(v));
  return p.toString();
}

export interface ConnectRequest {
  kind: 'sim' | 'tcp' | 'serial';
  host?: string;
  port?: number;
  url?: string;
  key?: string;
}

export const api = {
  state: () => request<StateSnapshot>('GET', '/api/state'),
  ports: () => request<{ ports: PortInfo[] }>('GET', '/api/ports'),
  logs: () => request<{ logs: LogEvent[] }>('GET', '/api/logs?limit=500'),
  connect: (b: ConnectRequest) => request<{ state: string; node_id: string }>('POST', '/api/connect', b),
  disconnect: () => request<{ state: string }>('POST', '/api/disconnect', {}),
  acquisition: (action: 'start' | 'stop', streams?: (string | number)[]) =>
    request<Record<string, number>>('POST', '/api/acquisition', { action, streams: streams ?? [] }),
  set: (key: string, value: number) => request<{ set: string; value: number }>('POST', '/api/set', { key, value }),
  envelope: (p: { stream: number; window_s: number; columns: number; end?: number }, signal?: AbortSignal) =>
    request<EnvelopeResponse>('GET', `/api/view/envelope?${qs(p)}`, undefined, signal),
  levels: (p: { stream: number; window_s: number; end?: number }, signal?: AbortSignal) =>
    request<LevelsResponse>('GET', `/api/view/levels?${qs(p)}`, undefined, signal),
  psd: (p: { stream: number; window_s: number; nperseg: number; end?: number }, signal?: AbortSignal) =>
    request<PsdResponse>('GET', `/api/view/psd?${qs(p)}`, undefined, signal),
  spectrogram: (
    p: {
      stream: number;
      channel: number;
      window_s: number;
      nfft: number;
      hop?: number;
      since?: number;
      max_columns?: number;
      end?: number;
    },
    signal?: AbortSignal,
  ) => request<SpectrogramResponse>('GET', `/api/view/spectrogram?${qs(p)}`, undefined, signal),

  // Recorder and live labels (WEB_API.md section 9).
  recOptions: () => request<RecordOptions>('GET', '/api/record/options'),
  recState: () => request<RecordingEvent>('GET', '/api/record/state'),
  dataRoot: () => request<DataRoot>('GET', '/api/record/data-root'),
  setDataRoot: (path: string) => request<DataRoot>('PUT', '/api/record/data-root', { path }),
  recStart: (form: SessionForm) => request<RecordingEvent>('POST', '/api/record/start', form),
  recStop: () => request<RecordResult>('POST', '/api/record/stop'),
  getLabel: () => request<LabelState>('GET', '/api/record/current-label'),
  putLabel: (l: LabelState) => request<LabelState>('PUT', '/api/record/current-label', l),
  /** The browser sends only the edge; the server stamps the arrival on its own clock. */
  mark: (edge: 'toggle' | 'start' | 'end' = 'toggle') =>
    request<{ action: 'start' | 'end'; mark: Mark }>('POST', '/api/record/mark', { edge }),
  labels: () => request<{ labels: Mark[]; marking: boolean }>('GET', '/api/record/labels'),
  deleteLabel: (id: number) => request<{ deleted: number }>('DELETE', `/api/record/labels/${encodeURIComponent(String(id))}`),
  marker: () => request<MarkerInfo>('GET', '/api/record/marker'),

  // Protocol runner (WEB_API.md section 10). The server owns its state; every answer is the new runner view.
  protocol: (name: string) => request<ProtocolInfo>('GET', `/api/record/protocols/${encodeURIComponent(name)}`),
  runner: () => request<RunnerView>('GET', '/api/record/runner'),
  runnerStart: (protocol?: string) => request<RunnerView>('POST', '/api/record/runner/start', protocol ? { protocol } : {}),
  runnerStop: () => request<RunnerView>('POST', '/api/record/runner/stop'),
  runnerMove: (action: 'next' | 'back' | 'skip' | 'cancel') => request<RunnerView>('POST', `/api/record/runner/${action}`),
  runnerGoto: (index: number) => request<RunnerView>('POST', '/api/record/runner/goto', { index }),
};

export function isAbort(e: unknown): boolean {
  return e instanceof DOMException && e.name === 'AbortError';
}
