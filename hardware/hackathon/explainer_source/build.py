"""Builds the 'how it works' explainer: template.html + a plot of a real recording -> out/how_it_works.html.
Then print to PDF with Chrome:
  python build.py
  chrome --headless=new --no-pdf-header-footer --virtual-time-budget=8000 --print-to-pdf=..\\Rezon_How_It_Works.pdf out\\how_it_works.html
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REC = os.path.join(HERE, '..', 'uploads', 'geophone_2026-11-12T10-50-07.csv')
T0, T1 = 13.0, 33.0            # seconds from the start of the recording
BIN = 0.02                     # s per plotted column (min/max)

t, b = [], []
for i, line in enumerate(open(REC, encoding='utf-8-sig')):
    r = line.strip().split(',')
    if i == 0 or len(r) < 6: continue
    t.append(int(r[0])); b.append(float(r[5]))
t0 = t[0]
bins = {}
for ti, bi in zip(t, b):
    s = (ti - t0) / 1000
    if T0 <= s < T1:
        k = int((s - T0) / BIN)
        lo, hi = bins.get(k, (bi, bi)); bins[k] = (min(lo, bi), max(hi, bi))
keys = sorted(bins)
pk_k = max(keys, key=lambda k: max(abs(bins[k][0]), abs(bins[k][1])))
pk = max(abs(bins[pk_k][0]), abs(bins[pk_k][1])); pk_s = T0 + pk_k * BIN

X0, X1 = 52, 708
def X(s): return X0 + (s - T0) / (T1 - T0) * (X1 - X0)

def panel(ytop, h, rng, ticks, thr, thr_label, clip_note='', lab_bottom=False):
    mid = ytop + h / 2
    Y = lambda v: mid - max(-rng, min(rng, v)) / rng * (h / 2)
    o = [f'<rect x="{X0}" y="{ytop}" width="{X1 - X0}" height="{h}" fill="#fbfaf7" stroke="#ddd8cf"/>']
    for v in ticks:
        o.append(f'<path d="M{X0} {Y(v):.1f} H{X1}" stroke="#e6e1d8" stroke-width=".7"/><text class="s" x="{X0 - 5}" y="{Y(v) + 3:.1f}" text-anchor="end">{v:g}</text>')
    for v in (thr, -thr):
        o.append(f'<path d="M{X0} {Y(v):.1f} H{X1}" stroke="#b3493a" stroke-width=".9" stroke-dasharray="5 3"/>')
    lx, ly, anc = (X0 + 5, ytop + h - 5, 'start') if lab_bottom else (X0 + 5, Y(thr) - 3, 'start')
    o.append(f'<text x="{lx}" y="{ly:.1f}" text-anchor="{anc}" style="fill:#b3493a;font-size:9px">{thr_label}</text>')
    up = ' '.join(f'{X(T0 + k * BIN):.1f},{Y(bins[k][1]):.1f}' for k in keys)
    dn = ' '.join(f'{X(T0 + k * BIN):.1f},{Y(bins[k][0]):.1f}' for k in reversed(keys))
    o.append(f'<polygon points="{up} {dn}" fill="#2f8f8b" stroke="#2f8f8b" stroke-width=".6"/>')
    if clip_note: o.append(f'<text class="s" x="{X(pk_s) + 14:.1f}" y="{ytop + 11}">{clip_note}</text>')
    return ''.join(o)

p1 = panel(14, 120, 0.8, (-0.8, -0.4, 0, 0.4, 0.8), 0.3, 'impact threshold 0.3 mm/s')
p2 = panel(150, 96, 0.15, (-0.1, 0, 0.1), 0.02, 'dashed: step threshold (minimum) 0.02 mm/s', 'impact, clipped by this zoom', lab_bottom=True)
ax = ''.join(f'<text class="s" x="{X(s):.1f}" y="260" text-anchor="middle">{s - T0:g} s</text><path d="M{X(s):.1f} 246 v4" stroke="#8c959f"/>' for s in range(int(T0), int(T1) + 1, 2))
svg = (f'<figure><svg viewBox="0 0 720 266">{p1}{p2}{ax}'
       f'<text class="s" x="12" y="74" text-anchor="middle" transform="rotate(-90 12 74)">mm/s</text><text class="s" x="12" y="198" text-anchor="middle" transform="rotate(-90 12 198)">mm/s, zoomed</text>'
       f'<text class="t" x="{X(pk_s) + 14:.1f}" y="29" style="fill:#b3493a">impact: {pk:.2f} mm/s</text>'
       f'<text class="s" x="{X(pk_s) + 14:.1f}" y="41">afterwards: only small, irregular movement</text>'
       f'<text x="{X(18.5):.1f}" y="30" text-anchor="middle" class="l">small regular bursts, about 0.1 mm/s</text>'
       f'<path d="M{X(18.5):.1f} 34 V60" stroke="#2f6f6c" stroke-width=".8" marker-end="url(#ah)"/>'
       '</svg><figcaption>Figure 7. Twenty seconds of our own data (recording of 12 Nov, 10:50, band-pass filtered, min/max per 20 ms). '
       'Top: full scale. Bottom: the same trace zoomed in 5×, where the small bursts and the background become visible. '
       'The recording carries no labels; reading the small bursts as footsteps and the spike as a test fall is my interpretation of it. <span class="tag tm">MEASURED</span></figcaption></figure>'
       '<p>This picture is the whole idea in one view: the impact is roughly seven times larger than anything before it, so a single threshold finds it; and what follows it (no regular rhythm of walking, only small irregular movement) is what turns “impact” into “fall”.</p>')

tpl = open(os.path.join(HERE, 'template.html'), encoding='utf-8').read()
assert '<!--PLOT-->' in tpl
os.makedirs(os.path.join(HERE, 'out'), exist_ok=True)
open(os.path.join(HERE, 'out', 'how_it_works.html'), 'w', encoding='utf-8').write(tpl.replace('<!--PLOT-->', svg))
print(f'written; window {T0}-{T1} s, {len(keys)} columns, peak {pk:.3f} mm/s at {pk_s:.2f} s')
