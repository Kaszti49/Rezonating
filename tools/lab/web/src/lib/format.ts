import type { UnitName } from './types';

const DASH = '—';

/** Number with SI prefix for V and g, plain for counts. `unit === null` means "does not apply". */
export function fmtVal(v: number | null | undefined, unit: UnitName | null): string {
  if (v === null || v === undefined || !Number.isFinite(v) || unit === null) return DASH;
  if (unit === 'counts') return Math.abs(v) >= 1e6 ? v.toExponential(2) : v.toFixed(0);
  const a = Math.abs(v);
  if (a === 0) return `0 ${unit}`;
  if (a >= 1) return `${v.toPrecision(3)} ${unit}`;
  if (a >= 1e-3) return `${(v * 1e3).toPrecision(3)} m${unit}`;
  if (a >= 1e-6) return `${(v * 1e6).toPrecision(3)} µ${unit}`;
  return `${(v * 1e9).toPrecision(3)} n${unit}`;
}

export function fmtFixed(v: number | null | undefined, digits: number, suffix = ''): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  return v.toFixed(digits) + suffix;
}

export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)} %`;
}

export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  return Math.round(v).toLocaleString('en-US').replace(/,/g, ' ');
}

export function fmtBytes(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  if (v >= 1048576) return `${(v / 1048576).toFixed(2)} MB`;
  if (v >= 1024) return `${(v / 1024).toFixed(1)} kB`;
  return `${v.toFixed(0)} B`;
}

export function fmtClock(tUnix: number): string {
  const d = new Date(tUnix * 1000);
  const p = (n: number, w = 2) => String(n).padStart(w, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}

/** Loss text: "N+" when the live host value is only a lower bound. */
export function fmtHostLoss(host: number, exact: boolean): string {
  return exact ? fmtInt(host) : `${fmtInt(host)}+`;
}

/** Elapsed time as m:ss (h:mm:ss from one hour). */
export function fmtElapsed(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s) || s < 0) return DASH;
  const t = Math.floor(s);
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = String(t % 60).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
}
