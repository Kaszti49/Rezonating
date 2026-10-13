// The Record page's session form (WEB_API.md 9.3). Module state, so the form survives switching pages; the
// fields are also remembered in localStorage after a successful start (a convenience: the page works without it).

import type { ApiErrorDetail, RecordOptions, SensorEntry, SessionForm } from './types';

export interface ChanForm {
  x: number | null;
  y: number | null;
  z: number | null;
  head: string;
  serial: string;
  port: number | null;
  mount: string;
}

type RecStream = 'adc_raw' | 'accel';
const KEY = 'rzlab.recform';
export const MAX_PERSONS = 12;
const FIELDS = ['site', 'room', 'floor', 'surface', 'persons', 'protocol', 'streams', 'sensors', 'notes', 'marker_host'];

function emptyChan(): ChanForm {
  return { x: null, y: null, z: null, head: '', serial: '', port: null, mount: '' };
}

/** Key of one channel row: `adc_raw:0`, or `accel:*` for one position shared by all channels of the stream. */
export function chanKey(stream: string, ch: number | '*'): string {
  return `${stream}:${ch}`;
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

class RecForm {
  site = $state('');
  room = $state('');
  floor = $state('');
  surface = $state('');
  notes = $state('');
  persons = $state<string[]>([]);
  protocol = $state('');
  /** Stream name -> recorded. */
  streams = $state<Record<string, boolean>>({});
  /** Stream name -> one position for all channels (default for the 3-axis accelerometer). */
  shared = $state<Record<string, boolean>>({});
  chans = $state<Record<string, ChanForm>>({});
  marker = $state(true);
  markerHost = $state('');
  /** Field errors: `site`, `persons`, `sensor:<key>`, `form` (anything else). Texts come from the server or this
   * page and never contain the rejected value. */
  errors = $state<Record<string, string>>({});

  private loaded = false;

  /** Fill gaps from the options (never overwrites what the user typed). */
  sync(o: RecordOptions): void {
    if (!this.loaded) {
      this.loaded = true;
      this.restore();
    }
    if (!this.protocol || !o.protocols.includes(this.protocol)) this.protocol = o.default_protocol || o.protocols[0] || '';
    const hosts = o.marker.hosts;
    if (!hosts.includes(this.markerHost)) this.markerHost = hosts.includes(o.marker.bind) ? o.marker.bind : (hosts[0] ?? '');
    for (const s of o.node?.streams ?? []) {
      if (!s.recordable) continue;
      if (this.streams[s.name] === undefined) this.streams[s.name] = true;
      if (this.shared[s.name] === undefined) this.shared[s.name] = s.n_ch === 3;
      if (!this.chans[chanKey(s.name, '*')]) this.chans[chanKey(s.name, '*')] = emptyChan();
      for (const c of s.channels) if (!this.chans[chanKey(s.name, c.ch)]) this.chans[chanKey(s.name, c.ch)] = emptyChan();
    }
  }

  /** Build the start body. `keys[i]` is the row key of `sensors[i]`, to put 422 errors next to the right row. */
  build(o: RecordOptions): { form: SessionForm; keys: string[] } {
    const sensors: SensorEntry[] = [];
    const keys: string[] = [];
    const streams: RecStream[] = [];
    for (const s of o.node?.streams ?? []) {
      if (!s.recordable || !this.streams[s.name]) continue;
      if (s.name !== 'adc_raw' && s.name !== 'accel') continue;
      streams.push(s.name);
      const rows: (number | '*')[] = this.shared[s.name] ? ['*'] : s.channels.map((c) => c.ch);
      for (const ch of rows) {
        const k = chanKey(s.name, ch);
        const c = this.chans[k] ?? emptyChan();
        const pos: number[] = [];
        for (const v of [c.x, c.y]) {
          const n = num(v);
          if (n !== null) pos.push(n);
        }
        const z = num(c.z);
        if (z !== null) pos.push(z);
        const e: SensorEntry = { stream: s.name, position_m: pos };
        if (ch !== '*') e.ch = ch;
        if (c.head.trim()) e.head = c.head.trim();
        if (c.serial.trim()) e.serial = c.serial.trim();
        if (c.mount.trim()) e.mount = c.mount.trim();
        const port = num(c.port);
        if (port !== null) e.port = port;
        sensors.push(e);
        keys.push(k);
      }
    }
    const form: SessionForm = {
      site: this.site.trim(),
      room: this.room.trim(),
      persons: this.persons.slice(),
      protocol: this.protocol,
      streams,
      sensors,
      marker: this.marker,
    };
    if (this.floor.trim()) form.floor = this.floor.trim();
    if (this.surface.trim()) form.surface = this.surface.trim();
    if (this.notes.trim()) form.notes = this.notes.trim();
    if (this.marker && this.markerHost && o.marker.hosts.includes(this.markerHost)) form.marker_host = this.markerHost;
    return { form, keys };
  }

  /** Checks the server repeats; they only save a round trip. */
  precheck(form: SessionForm, keys: string[], cx: { x: boolean; y: boolean }[]): boolean {
    const e: Record<string, string> = {};
    if (!form.site) e.site = 'Required.';
    if (!form.room) e.room = 'Required.';
    if (form.streams.length === 0) e.streams = 'Record at least one stream.';
    form.sensors.forEach((_s, i) => {
      if (!cx[i]?.x || !cx[i]?.y) e[`sensor:${keys[i]}`] = 'Position x and y (metres) are required.';
    });
    this.errors = e;
    return Object.keys(e).length === 0;
  }

  /** Which rows have x and y filled in (for `precheck`). */
  filled(keys: string[]): { x: boolean; y: boolean }[] {
    return keys.map((k) => ({ x: num(this.chans[k]?.x) !== null, y: num(this.chans[k]?.y) !== null }));
  }

  /** Put a 422's `details` next to the fields. The server never echoes the rejected value, and neither does this. */
  applyDetails(details: ApiErrorDetail[], keys: string[], fallback: string): void {
    const e: Record<string, string> = {};
    for (const d of details) {
      const loc = d.loc[0] === 'body' ? d.loc.slice(1) : d.loc;
      const msg = d.msg.replace(/^Value error, /, '');
      let field = typeof loc[0] === 'string' ? loc[0] : 'form';
      if (field === 'sensors' && typeof loc[1] === 'number' && keys[loc[1]]) field = `sensor:${keys[loc[1]]}`;
      else if (!FIELDS.includes(field)) field = 'form';
      e[field] = e[field] ? `${e[field]} ${msg}` : msg;
    }
    if (Object.keys(e).length === 0) e.form = fallback;
    this.errors = e;
  }

  save(): void {
    const data = {
      site: this.site,
      room: this.room,
      floor: this.floor,
      surface: this.surface,
      persons: this.persons,
      protocol: this.protocol,
      streams: this.streams,
      shared: this.shared,
      chans: this.chans,
      marker: this.marker,
      markerHost: this.markerHost,
    };
    try {
      localStorage.setItem(KEY, JSON.stringify(data));
    } catch {
      /* blocked storage: nothing to remember */
    }
  }

  private restore(): void {
    let raw: string | null = null;
    try {
      raw = localStorage.getItem(KEY);
    } catch {
      return;
    }
    if (!raw) return;
    try {
      const d = JSON.parse(raw) as Record<string, unknown>;
      const str = (v: unknown): string => (typeof v === 'string' ? v : '');
      const bools = (v: unknown): Record<string, boolean> => {
        const out: Record<string, boolean> = {};
        if (v && typeof v === 'object') for (const [k, b] of Object.entries(v)) if (typeof b === 'boolean') out[k] = b;
        return out;
      };
      this.site = str(d.site);
      this.room = str(d.room);
      this.floor = str(d.floor);
      this.surface = str(d.surface);
      this.protocol = str(d.protocol);
      this.markerHost = str(d.markerHost);
      if (typeof d.marker === 'boolean') this.marker = d.marker;
      if (Array.isArray(d.persons))
        this.persons = d.persons.filter((p): p is string => typeof p === 'string' && /^P\d+$/.test(p)).slice(0, MAX_PERSONS);
      this.streams = bools(d.streams);
      this.shared = bools(d.shared);
      if (d.chans && typeof d.chans === 'object') {
        const out: Record<string, ChanForm> = {};
        for (const [k, v] of Object.entries(d.chans as Record<string, unknown>)) {
          if (!v || typeof v !== 'object') continue;
          const r = v as Record<string, unknown>;
          out[k] = { x: num(r.x), y: num(r.y), z: num(r.z), head: str(r.head), serial: str(r.serial), port: num(r.port), mount: str(r.mount) };
        }
        this.chans = out;
      }
    } catch {
      /* a broken entry is ignored */
    }
  }
}

export const recForm = new RecForm();
