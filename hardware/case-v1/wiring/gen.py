"""Wiring data for the Rezon OTIO node (case v1): ESP32-S3-DevKitC-1 + ADC 15 Click + two SM-24 geophones,
USB-C power, on the full 150 x 90 mm perfboard. Writes out/data.json for template.html (build.py).

Stripped from hardware/hackathon/wiring_source/gen.py: no SIM868, audio, power bank, step-down or lid board.

Frame (3D guide): X = along the board's long side (rows), Y = up, Z = across (columns, column 1 at +Z).
It matches the FreeCAD model (case_v1.py) as X = case x, Y = case z - 2, Z = -case y.
"""
import heapq
import json
import math
import os
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
P = 2.54
# ---------------------------------------------------------------- board grid (photo 2026-11-23: 33 columns x 54 rows)
COLS, ROWS = 33, 54
# The board prints A-Z, then A-Z again, then A, B. Second round = AA..AZ, third = BA, BB.
RN = [chr(65 + i) for i in range(26)] + ['A' + chr(65 + i) for i in range(26)] + ['BA', 'BB']
BX0 = -(ROWS - 1) * P / 2          # row A (USB end) at -X
BZ0 = (COLS - 1) * P / 2           # column 1 at +Z (= case -y)
YB = 7.6                           # board top in the guide frame


def hname(c, r): return f"{RN[r - 1]}{c}"


def parse(h):
    i = 0
    while h[i].isalpha():
        i += 1
    return int(h[i:]), RN.index(h[:i]) + 1


def hxz(h):
    c, r = parse(h)
    return round(BX0 + (r - 1) * P, 3), round(BZ0 - (c - 1) * P, 3)


# ---------------------------------------------------------------- pins
pins = {}


def add_col(part, col, rows, labels):
    for r, lab in zip(rows, labels):
        pins[hname(col, r)] = (part, lab)


J1 = ['J1-1 3V3', 'J1-2 3V3', 'J1-3 EN', 'J1-4 GPIO4', 'J1-5 GPIO5', 'J1-6 GPIO6', 'J1-7 GPIO7', 'J1-8 GPIO15', 'J1-9 GPIO16',
      'J1-10 GPIO17', 'J1-11 GPIO18', 'J1-12 GPIO8', 'J1-13 GPIO3', 'J1-14 GPIO46', 'J1-15 GPIO9', 'J1-16 GPIO10', 'J1-17 GPIO11',
      'J1-18 GPIO12', 'J1-19 GPIO13', 'J1-20 GPIO14', 'J1-21 5V', 'J1-22 GND']
J3 = ['J3-1 GND', 'J3-2 TX', 'J3-3 RX', 'J3-4 GPIO1', 'J3-5 GPIO2', 'J3-6 GPIO42', 'J3-7 GPIO41', 'J3-8 GPIO40', 'J3-9 GPIO39',
      'J3-10 GPIO38', 'J3-11 GPIO37', 'J3-12 GPIO36', 'J3-13 GPIO35', 'J3-14 GPIO0', 'J3-15 GPIO45', 'J3-16 GPIO48', 'J3-17 GPIO47',
      'J3-18 GPIO21', 'J3-19 GPIO20', 'J3-20 GPIO19', 'J3-21 GND', 'J3-22 GND']
# ESP32-S3: USB-C end at row A, pin 22 in row A, pin 1 in row V. J3 in column 7, J1 in column 16.
add_col('ESP32-S3', 16, range(22, 0, -1), J1)
add_col('ESP32-S3', 7, range(22, 0, -1), J3)
# ADC 15 Click: GND end at row A, pin 1 (AN / PWM) in row H. Right header (PWM side) col 19, left header (AN side) col 28.
add_col('Click', 19, range(8, 0, -1), ['PWM = CS2', 'INT (DRDY)', 'RX (NC)', 'TX (NC)', 'SCL (NC)', 'SDA (NC)', '5V (NC)', 'GND'])
add_col('Click', 28, range(8, 0, -1), ['AN (NC)', 'RST', 'CS1', 'SCK', 'SDO (MISO)', 'SDI (MOSI)', '3V3', 'GND'])
comps = {}

# ---------------------------------------------------------------- bare buses (20 AWG, solder side)
buses = [  # id, step, net, start, end, label
    ('GND bus row A', 3, 'gnd', 'A7', 'A30', 'GND bus along row A: ESP32 J3-22, J1-22, Click GND ×2'),
    ('GND bus col 30', 3, 'gnd', 'A30', 'N30', 'GND bus up column 30 to N30 (taps for the CH1− / CH2− wires)'),
]


def line(a, b):
    ca, ra = parse(a)
    cb, rb = parse(b)
    if ra == rb:
        return [hname(c, ra) for c in range(min(ca, cb), max(ca, cb) + 1)]
    return [hname(ca, r) for r in range(min(ra, rb), max(ra, rb) + 1)]


bridges = []
NETCOL = {'gnd': '#3d4044', 'v33': '#c7ab5f', 'spi': '#6c8dae', 'geo1': '#b07a6a', 'geo2': '#7d9a6a', 'geoN': '#a7a49d'}
links = [  # step, from, to, net, note
    (3, 'V16', 'B28', 'v33', 'ESP32 3V3 (J1-1) → Click 3V3'),
    (4, 'E16', 'E28', 'spi', 'SCK (GPIO12)'), (4, 'D16', 'D28', 'spi', 'MISO (GPIO13) ← Click SDO'),
    (4, 'C16', 'C28', 'spi', 'MOSI (GPIO14) → Click SDI'), (4, 'F16', 'F28', 'spi', 'ADC chip select CS1 (GPIO11)'),
    (4, 'H16', 'H19', 'spi', 'clock-chip select CS2 (GPIO9)'), (4, 'G16', 'G19', 'spi', 'DRDY, active low (GPIO10)'),
    (4, 'K16', 'G28', 'spi', 'ADC reset RST (GPIO8)'),
]

# ---------------------------------------------------------------- router (unchanged from the hackathon guide)
R = {'cols': COLS, 'rows': ROWS, 'node': {}, 'edges': set()}


def nb(c, r, cols, rows):
    for dc, dr, d in ((1, 0, 'h'), (-1, 0, 'h'), (0, 1, 'v'), (0, -1, 'v')):
        cc, rr = c + dc, r + dr
        if 1 <= cc <= cols and 1 <= rr <= rows:
            yield cc, rr, (dc, dr), d


def ekey(a, b): return tuple(sorted((a, b)))


for h in pins:
    R['node'][h] = 'nc' if '(NC)' in pins[h][1] else 'pin'
for b in buses:
    hs = line(b[3], b[4])
    ori = 'h' if parse(b[3])[1] == parse(b[4])[1] else 'v'
    for a, c in zip(hs, hs[1:]):
        R['edges'].add(ekey(a, c))
    for h in hs:
        if h not in R['node']:
            R['node'][h] = 'rail' + ori
# keep the board centre free (the lid's hold-down post lands there): block a 6 mm radius
KEEP = []
for c in range(1, COLS + 1):
    for r in range(1, ROWS + 1):
        x, z = hxz(hname(c, r))
        if math.hypot(x, z) < 6.0:
            R['node'][hname(c, r)] = 'pin'
            KEEP.append(hname(c, r))


def route(R, a, b, name):
    cols, rows = R['cols'], R['rows']
    ca, ra = parse(a)
    cb, rb = parse(b)
    start = (ca, ra, None)
    dist = {start: 0}
    prev = {}
    pq = [(0, ca, ra, None)]
    goal = None
    while pq:
        d, c, r, dirv = heapq.heappop(pq)
        if dist.get((c, r, dirv), 1e9) < d:
            continue
        if (c, r) == (cb, rb):
            goal = (c, r, dirv)
            break
        here = hname(c, r)
        hk = R['node'].get(here)
        for cc, rr, dv, ori in nb(c, r, cols, rows):
            if (c, r) != (ca, ra) and hk in ('railh', 'railv', 'h', 'v', 'nc') and dirv is not None and dv != dirv:
                continue
            nh = hname(cc, rr)
            if ekey(here, nh) in R['edges']:
                continue
            k = R['node'].get(nh)
            if (cc, rr) != (cb, rb):
                if k in ('pin', 'leg', 'corner', 'end'):
                    continue
                if k in ('railh', 'h') and ori == 'h':
                    continue
                if k in ('railv', 'v') and ori == 'v':
                    continue
            cost = 1
            if dirv is not None and dv != dirv:
                cost += 2.2
            if k in ('railh', 'railv', 'h', 'v'):
                cost += 1.4
            if k == 'nc':
                cost += 0.5
            nd = d + cost
            st = (cc, rr, dv)
            if nd < dist.get(st, 1e9):
                dist[st] = nd
                prev[st] = (c, r, dirv)
                heapq.heappush(pq, (nd, cc, rr, dv))
    if goal is None:
        raise SystemExit(f'no route for {name}: {a} -> {b}')
    path = []
    s = goal
    while s in prev or (s[0], s[1]) == (ca, ra):
        path.append(hname(s[0], s[1]))
        if (s[0], s[1]) == (ca, ra):
            break
        s = prev[s]
    path.reverse()
    for x, y in zip(path, path[1:]):
        R['edges'].add(ekey(x, y))
    for i in range(1, len(path) - 1):
        p0, p1, p2 = parse(path[i - 1]), parse(path[i]), parse(path[i + 1])
        straight_h = p0[1] == p1[1] == p2[1]
        straight_v = p0[0] == p1[0] == p2[0]
        k = R['node'].get(path[i])
        if k in ('railh', 'railv', 'h', 'v', 'nc'):
            R['node'][path[i]] = 'corner'
        else:
            R['node'][path[i]] = 'h' if straight_h else ('v' if straight_v else 'corner')
    for e in (a, b):
        if R['node'].get(e) is None:
            R['node'][e] = 'end'
    return path


def corners(path):
    if len(path) <= 2:
        return path
    out = [path[0]]
    for i in range(1, len(path) - 1):
        p0, p1, p2 = parse(path[i - 1]), parse(path[i]), parse(path[i + 1])
        if not (p0[0] == p1[0] == p2[0] or p0[1] == p1[1] == p2[1]):
            out.append(path[i])
    out.append(path[-1])
    return out


def r5(x): return int(math.ceil(x / 5.0) * 5)


wires = []


def addwire(**w):
    w['id'] = len(wires)
    wires.append(w)
    return w


for b in buses:
    hs = line(b[3], b[4])
    L = (len(hs) - 1) * P
    taps = [h for h in hs if h in pins]
    addwire(step=b[1], kind='bus', net=b[2], a=b[3], b=b[4], route=[b[3], b[4]], name=b[0], note=b[5],
            len=round(L, 1), cut=f"bare 20 AWG · cut {r5(L + 10)} mm", taps=taps, side='under')
# straight same-row SPI links first so they get their rows, then the rest
PRIO = {('E16', 'E28'): 0, ('D16', 'D28'): 0, ('C16', 'C28'): 0, ('F16', 'F28'): 0, ('H16', 'H19'): 0, ('G16', 'G19'): 0}
for st, a, b, net, note in sorted(links, key=lambda x: (PRIO.get((x[1], x[2]), 9), x[0])):
    path = route(R, a, b, note)
    L = (len(path) - 1) * P
    addwire(step=st, kind='link', net=net, a=a, b=b, route=corners(path), full=path, note=note, len=round(L, 1),
            cut=f"insulated core · cut {r5(L + 8)} mm, strip 3 mm both ends", side='under')

# ---------------------------------------------------------------- off-board wires (explicit 3D, guide frame)
def top(h, y=YB):
    x, z = hxz(h)
    return [x, y, z]


def plen(pts): return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


# Click screw terminals (wire entry side faces +X, the board centre). Order across the Click from the
# column-19 side to the column-28 side: CH1+, CH1−, CH2−, CH2+ (vault part note; check the Click's silkscreen).
TX_ = -28.8
TERM = {'CH1+': [TX_, 21, -9.8], 'CH1−': [TX_, 21, -13.8], 'CH2−': [TX_, 21, -20.8], 'CH2+': [TX_, 21, -24.8]}
GEO = {1: (0.0, 61.5), 2: (0.0, -61.5)}      # geophone 1 in the column-1-side cup (+Z), geophone 2 in the other
offb = []


def off(step, kind, net, a, b, pts, note='', **kw):
    L = plen(pts)
    offb.append(dict(step=step, kind=kind, net=net, a=a, b=b, pts=[[round(v, 2) for v in p] for p in pts], note=note,
                     len=round(L, 1), **kw))


gx, gz = GEO[1]
off(5, 'pair', 'geo1', 'Geophone 1 + tab', 'Click CH1+ screw terminal',
    [[gx + 4, 35.5, gz], [gx + 4, 37, gz], [8, 36, 30], [8, 34, -6], [-20, 30, -9.8], TERM['CH1+']], twin=0)
off(5, 'pair', 'geoN', 'Geophone 1 − tab', 'Click CH1− screw terminal',
    [[gx - 4, 35.5, gz], [gx - 4, 37, gz], [6, 36, 30], [6, 34, -8], [-20, 30, -13.8], TERM['CH1−']], twin=1)
gx, gz = GEO[2]
off(5, 'pair', 'geo2', 'Geophone 2 + tab', 'Click CH2+ screw terminal',
    [[gx + 4, 35.5, gz], [gx + 4, 37, gz], [-6, 34, -40], [-20, 30, -24.8], TERM['CH2+']], twin=0)
off(5, 'pair', 'geoN', 'Geophone 2 − tab', 'Click CH2− screw terminal',
    [[gx - 4, 35.5, gz], [gx - 4, 37, gz], [-8, 34, -38], [-20, 30, -20.8], TERM['CH2−']], twin=1)
for hole, t in (('M30', 'CH1−'), ('N30', 'CH2−')):
    x, z = hxz(hole)
    off(5, 'top', 'gnd', f'{hole} (GND bus col 30)', f'Click {t} screw terminal',
        [[x, YB, z], [x, 12, z], [-24, 24, z + 2], [-24, 22, TERM[t][2]], TERM[t]],
        note=f'2nd wire in {t}: ties the geophone − side to ground')

SLACK = {'pair': 30, 'top': 10}
for w in offb:
    L = w['len'] + SLACK[w['kind']]
    if w['kind'] == 'pair':
        cut = f"6×0.22 cable core · cut {r5(L)} mm, twist the two cores ~1 turn/cm"
    else:
        cut = f"insulated core · cut {r5(L)} mm, strip 5 mm (screw end) / 3 mm"
    w['cut'] = cut
    w['L'] = r5(L)
    w['side'] = 'off'
    addwire(**w)

# ---------------------------------------------------------------- checks
problems = []
for w in wires:
    if w['kind'] == 'link':
        for h in w['full']:
            if h in KEEP:
                problems.append(f'{w["note"]} crosses the centre keep-out at {h}')
for hole in ('M30', 'N30'):
    for w in wires:
        if w['kind'] == 'link' and hole in w['full']:
            problems.append(f'{hole} used by link {w["a"]}->{w["b"]}')
if problems:
    raise SystemExit('\n'.join(problems))

data = {'P': P, 'BX0': BX0, 'BZ0': BZ0, 'COLS': COLS, 'ROWS': ROWS, 'RN': RN, 'KEEP': KEEP,
        'pins': {h: list(v) for h, v in pins.items()}, 'comps': comps, 'wires': wires, 'netcol': NETCOL}
os.makedirs(OUT, exist_ok=True)
json.dump(data, open(os.path.join(OUT, 'data.json'), 'w', encoding='utf-8'), ensure_ascii=False)
print('wires', len(wires), 'links', sum(1 for w in wires if w['kind'] == 'link'))
for w in wires:
    if w['kind'] == 'link':
        print(w['step'], w['a'], '->', w['b'], ' via ', ' '.join(w['route'][1:-1]), f"{w['len']}mm")
    elif w['kind'] in ('pair', 'top'):
        print(w['step'], w['kind'], w['a'], '->', w['b'], w['cut'])
