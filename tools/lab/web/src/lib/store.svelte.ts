// Application state, the WebSocket client and the commands. One instance (`app`) for the whole page.

import { api, ApiError, type ConnectRequest } from './api';
import { LiveRing } from './ring';
import type {
  ConfigEvent,
  ConnectionEvent,
  ErrorEvent,
  HelloEvent,
  LabelEvent,
  LogEvent,
  Mark,
  RecordingEvent,
  StatusEvent,
  StreamResetEvent,
  Toast,
  UnitName,
} from './types';

export type WsState = 'connecting' | 'open' | 'down';
export type Theme = 'dark' | 'light';

const MAX_LOGS = 1000;
const MAX_HEALTH = 600; // one point per second, 10 minutes
const BACKOFF_MS = [500, 1000, 2000, 4000, 5000];

function lsGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function lsSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private window or blocked storage: the page works without it */
  }
}

/** Per-second history for the Device page graphs. Plain arrays, trimmed to MAX_HEALTH. */
export class HealthHistory {
  t: number[] = [];
  rate = new Map<number, (number | null)[]>();
  lossDevice: (number | null)[] = [];
  lossLink: (number | null)[] = [];
  lossHost: (number | null)[] = [];
  queue: (number | null)[] = [];
  heap: (number | null)[] = [];
  temp: (number | null)[] = [];
  rssi: (number | null)[] = [];
  rtt: (number | null)[] = [];

  clear(): void {
    this.t = [];
    this.rate = new Map();
    this.lossDevice = [];
    this.lossLink = [];
    this.lossHost = [];
    this.queue = [];
    this.heap = [];
    this.temp = [];
    this.rssi = [];
    this.rtt = [];
  }

  private trim(a: unknown[]): void {
    if (a.length > MAX_HEALTH) a.splice(0, a.length - MAX_HEALTH);
  }

  push(s: StatusEvent): void {
    const n = this.t.length;
    this.t.push(s.t);
    for (const st of s.streams) {
      let arr = this.rate.get(st.id);
      if (!arr) {
        arr = new Array<number | null>(n).fill(null);
        this.rate.set(st.id, arr);
      }
      arr.push(st.running ? (st.rate_hz_fit ?? st.rate_hz_status) : null);
    }
    for (const [id, arr] of this.rate) if (!s.streams.some((x) => x.id === id)) arr.push(null);
    let d = 0;
    let l = 0;
    let h = 0;
    let any = false;
    for (const st of s.streams) {
      if (st.loss) {
        any = true;
        d += st.loss.device;
        l += st.loss.link;
        h += st.loss.host;
      }
    }
    this.lossDevice.push(any ? d : null);
    this.lossLink.push(any ? l : null);
    this.lossHost.push(any ? h : null);
    this.queue.push(s.health?.queue_fill ?? null);
    this.heap.push(s.health?.heap_free != null ? s.health.heap_free / 1024 : null);
    this.temp.push(s.health?.temp_c ?? null);
    this.rssi.push(s.health?.rssi_dbm ?? null);
    this.rtt.push(s.link?.rtt_ms ?? null);
    if (this.t.length > MAX_HEALTH) {
      this.trim(this.t);
      for (const arr of this.rate.values()) this.trim(arr);
      for (const a of [this.lossDevice, this.lossLink, this.lossHost, this.queue, this.heap, this.temp, this.rssi, this.rtt])
        this.trim(a);
    }
  }
}

class AppState {
  ws = $state<WsState>('connecting');
  wsAttempt = $state(0);
  connection = $state.raw<ConnectionEvent | null>(null);
  hello = $state.raw<HelloEvent | null>(null);
  config = $state.raw<ConfigEvent | null>(null);
  status = $state.raw<StatusEvent | null>(null);
  logs = $state.raw<LogEvent[]>([]);
  toasts = $state.raw<Toast[]>([]);
  /** Bumped when the health history changes (once per status event). */
  healthVersion = $state(0);
  /** Name of the running command ("connect", "start", ...) or null. */
  busy = $state<string | null>(null);

  /** Latest `recording` event (WEB_API.md 9.4); null until the server sent one. */
  recording = $state.raw<RecordingEvent | null>(null);
  /** Marks of the running recording, in order of start (from GET /api/record/labels and `label` events). */
  marks = $state.raw<Mark[]>([]);
  /** True while this page asked for the stop: the result is then shown from the stop answer, not as a surprise. */
  stopRequested = false;

  theme = $state<Theme>('dark');
  units = $state<UnitName>('counts');
  windowS = $state(10);
  /** Resolved channel colours (from CSS), refreshed when the theme changes. */
  colors = $state<string[]>(['#4cc9f0', '#ff9f1c', '#b8e063']);

  readonly health = new HealthHistory();
  readonly rings = new Map<number, LiveRing>();
  /** Measured rate per stream id for the x axis (fit, else status, else nominal). */
  readonly fs = new Map<number, number>();

  private toastKey = 0;
  private seenEvents = new Set<number>();
  private sock: WebSocket | null = null;
  private timer: number | undefined;
  private hadOpen = false;

  // ----------------------------------------------------------------------------------- start-up

  init(): void {
    const th = lsGet('rzlab.theme');
    this.setTheme(th === 'light' ? 'light' : 'dark', false);
    const u = lsGet('rzlab.units');
    if (u === 'V' || u === 'g' || u === 'counts') this.units = u;
    const w = Number(lsGet('rzlab.window'));
    if ([1, 2, 5, 10, 20, 30, 60].includes(w)) this.windowS = w;
    this.openSocket();
  }

  setTheme(t: Theme, persist = true): void {
    this.theme = t;
    document.documentElement.setAttribute('data-theme', t);
    if (persist) lsSet('rzlab.theme', t);
    const cs = getComputedStyle(document.documentElement);
    const c = [0, 1, 2].map((i) => cs.getPropertyValue(`--ch${i}`).trim() || this.colors[i]);
    this.colors = c;
  }

  setUnits(u: UnitName): void {
    this.units = u;
    lsSet('rzlab.units', u);
  }

  setWindow(s: number): void {
    this.windowS = s;
    lsSet('rzlab.window', String(s));
  }

  // ----------------------------------------------------------------------------------- toasts

  toast(text: string, kind: Toast['kind'] = 'error', eventId?: number | null): void {
    if (eventId != null) {
      if (this.seenEvents.has(eventId)) return;
      this.seenEvents.add(eventId);
      if (this.seenEvents.size > 200) this.seenEvents.delete(this.seenEvents.values().next().value as number);
    }
    const key = ++this.toastKey;
    this.toasts = [...this.toasts.slice(-4), { key, kind, text }];
    window.setTimeout(() => this.dismiss(key), kind === 'error' ? 9000 : 4000);
  }

  dismiss(key: number): void {
    this.toasts = this.toasts.filter((t) => t.key !== key);
  }

  // ----------------------------------------------------------------------------------- websocket

  private openSocket(): void {
    window.clearTimeout(this.timer);
    this.ws = this.hadOpen ? 'down' : 'connecting';
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    let sock: WebSocket;
    try {
      sock = new WebSocket(`${scheme}://${location.host}/ws`);
    } catch {
      this.scheduleReconnect();
      return;
    }
    sock.binaryType = 'arraybuffer';
    this.sock = sock;
    sock.onopen = () => {
      this.ws = 'open';
      this.wsAttempt = 0;
      if (this.hadOpen) {
        // Samples may have been missed: drop the live rings; history comes back through the view requests.
        for (const r of this.rings.values()) r.reset(r.epoch);
      }
      this.hadOpen = true;
      void this.loadLogs();
      if (this.recording && this.recording.state !== 'idle') void this.loadMarks();
    };
    sock.onmessage = (ev: MessageEvent) => {
      if (typeof ev.data === 'string') this.onText(ev.data);
      else if (ev.data instanceof ArrayBuffer) this.onBinary(ev.data);
    };
    sock.onclose = () => {
      if (this.sock === sock) this.sock = null;
      this.ws = 'down';
      this.scheduleReconnect();
    };
    sock.onerror = () => {
      /* onclose follows */
    };
  }

  private scheduleReconnect(): void {
    const delay = BACKOFF_MS[Math.min(this.wsAttempt, BACKOFF_MS.length - 1)];
    this.wsAttempt++;
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => this.openSocket(), delay);
  }

  private onBinary(buf: ArrayBuffer): void {
    if (buf.byteLength < 20) return;
    const dv = new DataView(buf);
    if (dv.getUint8(0) !== 1 || dv.getUint8(3) !== 0) return;
    const stream = dv.getUint8(1);
    const nCh = dv.getUint8(2);
    const epoch = dv.getUint16(4, true);
    const first = Number(dv.getBigUint64(8, true));
    const n = dv.getUint32(16, true);
    if (nCh === 0 || buf.byteLength !== 20 + 4 * n * nCh) return;
    let ring = this.rings.get(stream);
    if (!ring || ring.nCh !== nCh) {
      const nominal = this.hello?.streams.find((s) => s.id === stream)?.nominal_hz ?? 2000;
      ring = new LiveRing(nCh, nominal);
      this.rings.set(stream, ring);
    }
    if (ring.epoch !== epoch) ring.reset(epoch);
    ring.push(first, n, new Int32Array(buf, 20, n * nCh));
  }

  private onText(text: string): void {
    let m: { type?: string };
    try {
      m = JSON.parse(text) as { type?: string };
    } catch {
      return;
    }
    switch (m.type) {
      case 'connection': {
        const c = m as ConnectionEvent;
        this.connection = c;
        break;
      }
      case 'hello': {
        const h = m as HelloEvent;
        this.hello = h;
        this.health.clear();
        this.healthVersion++;
        break;
      }
      case 'config':
        this.config = m as ConfigEvent;
        break;
      case 'status': {
        const s = m as StatusEvent;
        this.status = s;
        for (const st of s.streams) {
          const f = st.rate_hz_fit ?? st.rate_hz_status ?? st.nominal_hz;
          if (f > 0) this.fs.set(st.id, f);
        }
        this.health.push(s);
        this.healthVersion++;
        break;
      }
      case 'log': {
        const l = m as LogEvent;
        const next = this.logs.length >= MAX_LOGS ? this.logs.slice(this.logs.length - MAX_LOGS + 1) : this.logs.slice();
        next.push(l);
        this.logs = next;
        break;
      }
      case 'error': {
        const e = m as ErrorEvent;
        this.toast(e.message, 'error', e.id);
        break;
      }
      case 'recording':
        this.applyRecording(m as RecordingEvent);
        break;
      case 'label':
        this.applyLabel(m as LabelEvent);
        break;
      case 'stream_reset': {
        const r = m as StreamResetEvent;
        this.rings.get(r.stream)?.reset(r.epoch & 0xffff);
        break;
      }
      default:
        break;
    }
  }

  /** True while a recording is starting, running or being finished. */
  get recActive(): boolean {
    const s = this.recording?.state;
    return s === 'starting' || s === 'recording' || s === 'stopping' || s === 'finalizing';
  }

  applyRecording(r: RecordingEvent): void {
    const prev = this.recording;
    this.recording = r;
    if (r.state === 'recording' && prev?.session !== r.session) {
      this.marks = [];
      void this.loadMarks();
    }
    const wasActive = prev != null && prev.state !== 'idle';
    if (wasActive && r.state === 'idle' && r.last && !this.stopRequested) {
      // Nobody on this page pressed Stop (link lost, or another tab): say so; the Record page shows the result.
      const why =
        r.last.ended_by === 'link_lost'
          ? 'ended on its own: the link to the node was lost'
          : r.last.ended_by === 'stop'
            ? 'was stopped from another tab'
            : `ended (${r.last.ended_by})`;
      this.toast(`Recording ${r.last.session} ${why}. The result is on the Record page.`, r.last.ok ? 'info' : 'error');
    }
    if (r.state === 'idle') this.stopRequested = false;
  }

  applyLabel(e: Pick<LabelEvent, 'action' | 'mark'>): void {
    if (e.action === 'delete') {
      this.marks = this.marks.filter((x) => x.id !== e.mark.id);
      return;
    }
    const mk = e.mark as Mark;
    const i = this.marks.findIndex((x) => x.id === mk.id);
    if (i >= 0) {
      const next = this.marks.slice();
      next[i] = mk;
      this.marks = next;
    } else {
      this.marks = [...this.marks, mk].sort((a, b) => a.start_s - b.start_s);
    }
  }

  async loadMarks(): Promise<void> {
    try {
      const r = await api.labels();
      this.marks = r.labels;
    } catch {
      /* the list fills from `label` events anyway */
    }
  }

  private async loadLogs(): Promise<void> {
    try {
      const r = await api.logs();
      this.logs = r.logs.slice(-MAX_LOGS);
    } catch {
      /* the log list fills from events anyway */
    }
  }

  // ----------------------------------------------------------------------------------- commands

  /** Run a command; errors become a toast (one per event id) unless `quiet`. Returns the error or null. */
  async run(name: string, fn: () => Promise<unknown>, quiet = false): Promise<ApiError | null> {
    this.busy = name;
    try {
      await fn();
      return null;
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, 'client_error', String(e), null, null);
      if (err.eventId != null) {
        // The same failure may already have arrived as a WebSocket event; show it once.
        if (quiet) this.seenEvents.add(err.eventId);
        else this.toast(err.message, 'error', err.eventId);
      } else if (!quiet) {
        this.toast(err.message, 'error');
      }
      return err;
    } finally {
      this.busy = null;
    }
  }

  connect(req: ConnectRequest): Promise<ApiError | null> {
    return this.run('connect', () => api.connect(req));
  }
  disconnect(): Promise<ApiError | null> {
    return this.run('disconnect', () => api.disconnect());
  }
  startAcq(): Promise<ApiError | null> {
    return this.run('start', () => api.acquisition('start'));
  }
  stopAcq(): Promise<ApiError | null> {
    return this.run('stop', () => api.acquisition('stop'));
  }
  setValue(key: string, value: number): Promise<ApiError | null> {
    return this.run(`set ${key}`, () => api.set(key, value), true);
  }
}

export const app = new AppState();

// ------------------------------------------------------------------------------------- helpers

/** Unit to show for a stream's channel under the user's choice; null = the choice does not apply. */
export function effUnit(native: UnitName | undefined, mode: UnitName): UnitName | null {
  if (mode === 'counts') return 'counts';
  return native === mode ? mode : null;
}

/** Multiplier from code to displayed value for one channel (1 for counts or when the unit does not apply). */
export function unitFactor(streamId: number, ch: number, mode: UnitName): number {
  const c = app.config?.streams.find((s) => s.id === streamId)?.channels[ch];
  if (!c) return 1;
  return effUnit(c.units, mode) === c.units ? c.scale : 1;
}

export function nativeUnit(streamId: number, ch: number): UnitName | undefined {
  return app.config?.streams.find((s) => s.id === streamId)?.channels[ch]?.units;
}

/** Convert a value reported in the channel's native unit (levels, PSD) into the chosen unit. */
export function toDisplay(streamId: number, ch: number, v: number | null | undefined, mode: UnitName): number | null {
  if (v === null || v === undefined) return null;
  const c = app.config?.streams.find((s) => s.id === streamId)?.channels[ch];
  if (!c) return v;
  if (mode === 'counts') return c.scale > 0 ? v / c.scale : null;
  return mode === c.units ? v : null;
}

export function chName(streamName: string, ch: number): string {
  return streamName === 'accel' ? ['x', 'y', 'z'][ch] ?? `ch${ch}` : `ch${ch}`;
}

export function streamFs(streamId: number): number {
  return app.fs.get(streamId) ?? app.hello?.streams.find((s) => s.id === streamId)?.nominal_hz ?? 1000;
}
