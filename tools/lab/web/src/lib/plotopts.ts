import type uPlot from 'uplot';

export interface Palette {
  axis: string;
  grid: string;
  err: string;
}

export function readPalette(): Palette {
  const cs = getComputedStyle(document.documentElement);
  const g = (n: string, d: string) => cs.getPropertyValue(n).trim() || d;
  return { axis: g('--axis', '#8593a3'), grid: g('--grid', 'rgba(133,147,163,.16)'), err: g('--err', '#f87171') };
}

export function cssVar(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** Compact axis number: plain for mid-range values, exponent for tiny or huge ones. */
export function fmtAxis(v: number): string {
  if (v === 0) return '0';
  const a = Math.abs(v);
  if (a < 1e-2 || a >= 1e6) return v.toExponential(1).replace('e+', 'e');
  if (a >= 100) return v.toFixed(0);
  return String(Number(v.toPrecision(3)));
}

/** Axis numbers with an SI prefix for V and g (all ticks share the prefix of the largest one). */
function fmtUnitSplits(splits: number[], unit: string): string[] {
  let m = 0;
  for (const v of splits) if (Number.isFinite(v)) m = Math.max(m, Math.abs(v));
  const [f, pre] = m >= 1 ? [1, ''] : m >= 1e-3 ? [1e3, 'm'] : m >= 1e-6 ? [1e6, 'µ'] : [1e9, 'n'];
  return splits.map((v) => (v === 0 ? '0' : `${String(Number((v * f).toPrecision(3)))} ${pre}${unit}`));
}

export function axisBase(p: Palette, label: string, unit?: string): uPlot.Axis {
  return {
    stroke: p.axis,
    grid: { stroke: p.grid, width: 1 },
    ticks: { stroke: p.grid, width: 1 },
    label,
    labelSize: 16,
    labelFont: '12px system-ui, sans-serif',
    font: '11px ui-monospace, Consolas, monospace',
    values: (_u, splits) => (unit ? fmtUnitSplits(splits, unit) : splits.map((v) => fmtAxis(v))),
  };
}

export function hexAlpha(hex: string, alpha: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  const a = Math.round(alpha * 255)
    .toString(16)
    .padStart(2, '0');
  return `#${m[1]}${a}`;
}
