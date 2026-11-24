// Home page: results API (WEB_API.md section 16), smooth SVG paths, a small FFT and the device checks.
import { request } from './api';
import type { LocateState } from './locate';
import type { StatusEvent } from './types';

// ------------------------------------------------------------------------------------- results

export interface ScoreRow {
  set: string;
  right: number;
  same: number;
  wrong: number;
}

export interface ExperimentResult {
  id: string;
  title: string;
  date: string;
  status: string;
  pack: string;
  people: number | null;
  metric: string;
  value: number | null;
  result: string;
  /** The note says the limits were chosen on these same steps. */
  in_sample: boolean;
  score: ScoreRow[];
}

export const homeApi = {
  results: () => request<{ experiments: ExperimentResult[] }>('GET', '/api/home/results'),
};

// ------------------------------------------------------------------------------------- paths

export type Pt = readonly [number, number];

/** Smooth SVG path through points (Catmull-Rom as cubic Beziers; y is kept inside the two points it joins). */
export function smoothPath(p: Pt[]): string {
  if (p.length === 0) return '';
  let d = `M${p[0][0].toFixed(1)} ${p[0][1].toFixed(1)}`;
  for (let i = 0; i < p.length - 1; i++) {
    const a = p[Math.max(0, i - 1)];
    const b = p[i];
    const c = p[i + 1];
    const e = p[Math.min(p.length - 1, i + 2)];
    const lo = Math.min(b[1], c[1]);
    const hi = Math.max(b[1], c[1]);
    const clamp = (v: number): number => Math.min(hi, Math.max(lo, v));
    const x1 = b[0] + (c[0] - a[0]) / 6;
    const y1 = clamp(b[1] + (c[1] - a[1]) / 6);
    const x2 = c[0] - (e[0] - b[0]) / 6;
    const y2 = clamp(c[1] - (e[1] - b[1]) / 6);
    d += `C${x1.toFixed(1)} ${y1.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)} ${c[0].toFixed(1)} ${c[1].toFixed(1)}`;
  }
  return d;
}

/** Closed smooth ring around (0, 0) with the given radius per point. */
export function ringPath(radius: Float32Array | number[]): string {
  const n = radius.length;
  const at = (i: number): Pt => {
    const k = ((i % n) + n) % n;
    const a = (k / n) * Math.PI * 2 - Math.PI / 2;
    return [Math.cos(a) * radius[k], Math.sin(a) * radius[k]];
  };
  let d = '';
  for (let i = 0; i < n; i++) {
    const a = at(i - 1);
    const b = at(i);
    const c = at(i + 1);
    const e = at(i + 2);
    if (i === 0) d = `M${b[0].toFixed(2)} ${b[1].toFixed(2)}`;
    d +=
      `C${(b[0] + (c[0] - a[0]) / 6).toFixed(2)} ${(b[1] + (c[1] - a[1]) / 6).toFixed(2)} ` +
      `${(c[0] - (e[0] - b[0]) / 6).toFixed(2)} ${(c[1] - (e[1] - b[1]) / 6).toFixed(2)} ${c[0].toFixed(2)} ${c[1].toFixed(2)}`;
  }
  return d + 'Z';
}

// ------------------------------------------------------------------------------------- FFT

/** In-place radix-2 FFT; `re` and `im` have a power-of-two length. */
export function fft(re: Float32Array, im: Float32Array): void {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [re[i], re[j]] = [re[j], re[i]];
      [im[i], im[j]] = [im[j], im[i]];
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len;
    const wr = Math.cos(ang);
    const wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1;
      let ci = 0;
      for (let k = 0; k < len / 2; k++) {
        const a = i + k;
        const b = a + len / 2;
        const xr = re[b] * cr - im[b] * ci;
        const xi = re[b] * ci + im[b] * cr;
        re[b] = re[a] - xr;
        im[b] = im[a] - xi;
        re[a] += xr;
        im[a] += xi;
        const t = cr * wr - ci * wi;
        ci = cr * wi + ci * wr;
        cr = t;
      }
    }
  }
}

// ------------------------------------------------------------------------------------- device checks

export interface Check {
  id: string;
  label: string;
  /** `wait`: not known yet (it is not counted as passed). */
  state: 'ok' | 'warn' | 'wait';
  detail: string;
}

const RATE_LIMIT_PCT = 1.65; // LTC6903 over temperature (CLAUDE.md, hardware facts)
const AGREE_MIN = 0.7;

/** What "healthy" means, one line per check. Every check reads a number the node or the server reports. */
export function deviceChecks(status: StatusEvent | null, locate: LocateState | null): Check[] {
  const raw = status?.streams.find((s) => s.name === 'adc_raw') ?? null;
  const out: Check[] = [];
  const link = status?.link ?? null;
  const bad = link?.bad_frames ?? 0;
  out.push(
    link === null
      ? { id: 'link', label: 'Link', state: 'wait', detail: 'waiting' }
      : link.stale || bad > 0
        ? { id: 'link', label: 'Link', state: 'warn', detail: link.stale ? 'no data' : `${bad} bad frames` }
        : { id: 'link', label: 'Link', state: 'ok', detail: 'clean' },
  );
  const rate = raw?.rate_hz_fit ?? raw?.rate_hz_status ?? null;
  if (raw === null || rate === null) out.push({ id: 'rate', label: 'Sample rate', state: 'wait', detail: 'measuring' });
  else {
    const off = (100 * (rate - raw.nominal_hz)) / raw.nominal_hz;
    out.push({
      id: 'rate',
      label: 'Sample rate',
      state: Math.abs(off) <= RATE_LIMIT_PCT ? 'ok' : 'warn',
      detail: `${off >= 0 ? '+' : '−'}${Math.abs(off).toFixed(2)} %`,
    });
  }
  const loss = raw?.loss ?? null;
  const lost = loss === null ? null : loss.device + loss.link + loss.host;
  out.push(
    lost === null
      ? { id: 'loss', label: 'Lost samples', state: 'wait', detail: 'counting' }
      : { id: 'loss', label: 'Lost samples', state: lost === 0 ? 'ok' : 'warn', detail: lost.toLocaleString('en') },
  );
  const h = locate?.health ?? null;
  out.push(
    h === null || h.agree === null
      ? { id: 'pair', label: 'Geophone pair', state: 'wait', detail: 'needs 5 steps' }
      : {
          id: 'pair',
          label: 'Geophone pair',
          state: h.agree >= AGREE_MIN ? 'ok' : 'warn',
          detail: `${Math.round(100 * h.agree)} % alike`,
        },
  );
  const moved = h?.warnings.some((w) => w.startsWith('The rest level')) ?? false;
  out.push(
    h === null || h.rest === null
      ? { id: 'rest', label: 'Case position', state: 'wait', detail: 'waiting' }
      : h.baseline === null
        ? { id: 'rest', label: 'Case position', state: 'wait', detail: 'no reference saved' }
        : { id: 'rest', label: 'Case position', state: moved ? 'warn' : 'ok', detail: moved ? 'moved' : 'unchanged' },
  );
  return out;
}

export function reducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}
