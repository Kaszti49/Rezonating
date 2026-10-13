// Live sample ring (index-aligned, NaN = gap) and the scope-series builders.
// Nothing here allocates per frame: the output arrays are reused and only their length changes.

import type { EnvelopeResponse } from './types';

/** Last ~65 s of one stream, indexed by absolute sample index (WEB_API.md 4.2). */
export class LiveRing {
  readonly nCh: number;
  readonly cap: number;
  readonly data: Float32Array[];
  epoch = -1;
  /** One past the newest stored index. */
  head = 0;
  /** First index received since the last reset. */
  base = 0;
  hasData = false;
  /** Bumped on every reset: scopes refetch history when it changes. */
  generation = 0;
  /** Bumped on every push or reset: scopes redraw only when it changes. */
  version = 0;

  constructor(nCh: number, nominalHz: number) {
    this.nCh = nCh;
    this.cap = Math.ceil(nominalHz * 1.05 * 65) + 8192;
    this.data = [];
    for (let c = 0; c < nCh; c++) this.data.push(new Float32Array(this.cap).fill(Number.NaN));
  }

  /** First index that is still held. */
  get lo(): number {
    return Math.max(this.base, this.head - this.cap);
  }

  reset(epoch: number): void {
    for (const d of this.data) d.fill(Number.NaN);
    this.epoch = epoch;
    this.head = 0;
    this.base = 0;
    this.hasData = false;
    this.generation++;
    this.version++;
  }

  /** Append one frame message. Holes are filled with NaN (never joined). */
  push(first: number, n: number, codes: Int32Array): void {
    const { nCh, cap } = this;
    let off = 0;
    if (!this.hasData) {
      this.base = first;
      this.head = first;
      this.hasData = true;
    }
    if (first < this.head) {
      const skip = this.head - first;
      if (skip >= n) return;
      off = skip;
      first = this.head;
      n -= skip;
    } else if (first > this.head) {
      const from = Math.max(this.head, first - cap);
      for (let i = from; i < first; i++) {
        const j = i % cap;
        for (let c = 0; c < nCh; c++) this.data[c][j] = Number.NaN;
      }
    }
    let j = first % cap;
    for (let i = 0; i < n; i++) {
      const src = (off + i) * nCh;
      for (let c = 0; c < nCh; c++) this.data[c][j] = codes[src + c];
      if (++j === cap) j = 0;
    }
    this.head = first + n;
    this.version++;
  }
}

/** Columns for uPlot: x, then (max, min) per channel. Gap columns hold null. */
export class ScopeData {
  readonly nCh: number;
  readonly x: number[] = [];
  readonly plot: (number | null)[][] = [];
  /** Per column: 0 ok, 1 no valid sample (gap), 2 some samples missing. */
  readonly flag: number[] = [];
  n = 0;
  /** Right edge of the window in seconds since index 0 (x values are relative to it). */
  tRight = 0;

  constructor(nCh: number) {
    this.nCh = nCh;
    this.plot.push(this.x);
    for (let c = 0; c < nCh * 2; c++) this.plot.push([]);
  }

  clear(): void {
    this.n = 0;
  }

  add(x: number, hi: (number | null)[], lo: (number | null)[], flag: number): void {
    const i = this.n++;
    this.x[i] = x;
    this.flag[i] = flag;
    for (let c = 0; c < this.nCh; c++) {
      this.plot[1 + 2 * c][i] = hi[c];
      this.plot[2 + 2 * c][i] = lo[c];
    }
  }

  finish(): void {
    const n = this.n;
    this.x.length = n;
    this.flag.length = n;
    for (let k = 1; k < this.plot.length; k++) this.plot[k].length = n;
  }
}

/** Server envelope response kept as history for the left part of a live window. */
export interface HistEnvelope {
  fs: number;
  lo: number;
  hi: number;
  columns: number;
  min: (number | null)[][];
  max: (number | null)[][];
}

export function histFrom(r: EnvelopeResponse): HistEnvelope {
  return { fs: r.fs_hz, lo: r.lo, hi: r.hi, columns: r.columns, min: r.min, max: r.max };
}

const tmpHi: (number | null)[] = [];
const tmpLo: (number | null)[] = [];

/** Fill `out` with the envelope of an envelope response; x is relative to the window's right edge. */
export function fillFromEnvelope(
  out: ScopeData,
  r: HistEnvelope,
  k: number[],
  tRight: number,
  tLeft: number,
  beforeIndex: number,
): void {
  const span = r.hi - r.lo;
  for (let c = 0; c < r.columns; c++) {
    const idx = r.lo + (c * span) / r.columns;
    if (idx >= beforeIndex) break;
    const x = idx / r.fs - tRight;
    if (x < tLeft) continue;
    let valid = false;
    for (let ch = 0; ch < out.nCh; ch++) {
      const mx = r.max[ch]?.[c];
      const mn = r.min[ch]?.[c];
      if (mx === null || mx === undefined || mn === null || mn === undefined) {
        tmpHi[ch] = null;
        tmpLo[ch] = null;
      } else {
        tmpHi[ch] = mx * k[ch];
        tmpLo[ch] = mn * k[ch];
        valid = true;
      }
    }
    out.add(x, tmpHi, tmpLo, valid ? 0 : 1);
  }
}

/**
 * Envelope of the newest `windowS` seconds of a live ring. Columns lie on a fixed grid of `spc` samples
 * (absolute index multiples), so the picture does not flicker while it scrolls.
 */
export function buildLive(
  out: ScopeData,
  ring: LiveRing,
  windowS: number,
  fs: number,
  cols: number,
  k: number[],
  hist: HistEnvelope | null,
): void {
  out.clear();
  const wn = Math.max(1, Math.round(windowS * fs));
  const spc = Math.max(1, Math.round(wn / Math.max(50, cols)));
  const kEnd = Math.floor(ring.head / spc);
  const kStart = Math.max(0, Math.floor((ring.head - wn) / spc));
  const tRight = (kEnd * spc) / fs;
  out.tRight = tRight;
  const tLeft = -windowS;
  const lo = ring.lo;
  if (hist && ring.hasData) fillFromEnvelope(out, hist, k, tRight, tLeft, Math.max(lo, ring.base));
  const { nCh, cap, data } = ring;
  for (let col = kStart; col < kEnd; col++) {
    const a = col * spc;
    if (a < lo) continue;
    let flag = 0;
    let anyValid = false;
    for (let ch = 0; ch < nCh; ch++) {
      const arr = data[ch];
      let mn = Infinity;
      let mx = -Infinity;
      let valid = 0;
      let j = a % cap;
      for (let i = 0; i < spc; i++) {
        const v = arr[j];
        if (++j === cap) j = 0;
        if (v === v) {
          valid++;
          if (v < mn) mn = v;
          if (v > mx) mx = v;
        }
      }
      if (valid === 0) {
        tmpHi[ch] = null;
        tmpLo[ch] = null;
        flag = Math.max(flag, 1);
      } else {
        tmpHi[ch] = mx * k[ch];
        tmpLo[ch] = mn * k[ch];
        anyValid = true;
        if (valid < spc) flag = Math.max(flag, 2);
      }
    }
    out.add(a / fs - tRight, tmpHi, tmpLo, anyValid ? (flag === 1 ? 2 : flag) : 1);
  }
  out.finish();
}

/** Fill `out` from a server envelope answer (paused / scroll-back). */
export function buildFromServer(out: ScopeData, r: EnvelopeResponse, k: number[]): void {
  out.clear();
  const tRight = r.hi / r.fs_hz;
  out.tRight = tRight;
  fillFromEnvelope(out, histFrom(r), k, tRight, -Infinity, Infinity);
  out.finish();
}
