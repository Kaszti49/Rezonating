"""Single source of truth for the Rezon wiring: holes, parts, nets, routes.
Writes data.json (for the 3D guide) and wiring_list.html (for the PDF)."""
import heapq, json, math, sys, os

OUT = sys.argv[1] if len(sys.argv) > 1 else '.'
P = 2.54
# ---------------------------------------------------------------- main board grid
COLS, ROWS = 35, 27
BX0, BZ0 = -55.18, -53.02          # hole A1 (component side, front edge = row AA)
YB = 7.6                           # board top
RN = [chr(65 + i) for i in range(26)] + ['AA']

def hname(c, r): return f"{RN[r-1]}{c}"
def parse(h):
    i = 0
    while h[i].isalpha(): i += 1
    return int(h[i:]), RN.index(h[:i]) + 1
def hxz(h):
    c, r = parse(h); return round(BX0 + (c - 1) * P, 3), round(BZ0 + (r - 1) * P, 3)

# ---------------------------------------------------------------- lid board grid (12 x 8, rows A-H)
LCOLS, LROWS = 12, 8
LX0, LZ0 = 6.03, -8.89
LY_BOT = 26.5
def lxz(h):
    c, r = parse(h); return round(LX0 + (c - 1) * P, 3), round(LZ0 + (r - 1) * P, 3)

# ---------------------------------------------------------------- pins
pins = {}   # hole -> (part, pin label)
def add_row(part, row, cols, labels):
    for c, lab in zip(cols, labels): pins[f"{row}{c}"] = (part, lab)
J1 = ['J1-1 3V3', 'J1-2 3V3', 'J1-3 EN', 'J1-4 GPIO4', 'J1-5 GPIO5', 'J1-6 GPIO6', 'J1-7 GPIO7', 'J1-8 GPIO15', 'J1-9 GPIO16', 'J1-10 GPIO17',
      'J1-11 GPIO18', 'J1-12 GPIO8', 'J1-13 GPIO3', 'J1-14 GPIO46', 'J1-15 GPIO9', 'J1-16 GPIO10', 'J1-17 GPIO11', 'J1-18 GPIO12', 'J1-19 GPIO13',
      'J1-20 GPIO14', 'J1-21 5V', 'J1-22 GND']
J3 = ['J3-1 GND', 'J3-2 TX', 'J3-3 RX', 'J3-4 GPIO1', 'J3-5 GPIO2', 'J3-6 GPIO42', 'J3-7 GPIO41', 'J3-8 GPIO40', 'J3-9 GPIO39', 'J3-10 GPIO38',
      'J3-11 GPIO37', 'J3-12 GPIO36', 'J3-13 GPIO35', 'J3-14 GPIO0', 'J3-15 GPIO45', 'J3-16 GPIO48', 'J3-17 GPIO47', 'J3-18 GPIO21', 'J3-19 GPIO20',
      'J3-20 GPIO19', 'J3-21 GND', 'J3-22 GND']
add_row('ESP32-S3', 'K', range(23, 1, -1), J1)
add_row('ESP32-S3', 'B', range(23, 1, -1), J3)
add_row('Click', 'N', range(9, 1, -1), ['CS2', 'INT (DRDY)', 'NC', 'NC', 'NC', 'NC', 'NC', 'GND'])
add_row('Click', 'W', range(9, 1, -1), ['NC', 'RST', 'CS1', 'SCK', 'SDO (MISO)', 'SDI (MOSI)', '3V3', 'GND'])
add_row('PCM5102A', 'N', range(20, 26), ['VIN', 'GND', 'LCK', 'DIN', 'BCK', 'SCK'])
add_row('H2', 'J', range(29, 34), ['3V3 → SIM868 pin 36', 'PWRKEY → SIM868 pin 19', 'SIM RXD → SIM868 pin 1', 'SIM TXD → SIM868 pin 2', 'GND → SIM868 pin 3'])
add_row('PAM8403', 'Q', [28, 29, 30, 31, 32], ['L in', '⏚ in', 'R in', '+5V', 'GND'])
add_row('PAM8403', 'Y', [28, 29, 31, 32], ['L+ out', 'L− out', 'R− out', 'R+ out'])
add_row('H1', 'Z', range(19, 25), ['5V', 'GND', 'LED', 'BTN', 'SPK+', 'SPK−'])

# components: id -> (label, legs{hole: leg label}, value)
comps = {
    'C3': ('470 µF', {'Y15': '+', 'AA15': '−'}, 'electrolytic, stripe = −'),
    'C1': ('1000 µF', {'M35': '+', 'M33': '−'}, 'electrolytic, stripe = −, burst reserve at the SIM868 power take-off'),
    'R1': ('10 kΩ', {'J17': 'a', 'J22': 'b'}, 'button pull-up'),
    'R4': ('100 kΩ', {'D34': 'a', 'D29': 'b'}, 'battery divider, top'),
    'R5': ('100 kΩ', {'F29': 'a', 'F34': 'b'}, 'battery divider, bottom'),
}
comp_step = {'C3': 3, 'C1': 7, 'R1': 8, 'R4': 8, 'R5': 8}

def describe(h):
    if h in pins: return f"{pins[h][0]} {pins[h][1]}"
    for cid, (val, legs, _) in comps.items():
        if h in legs: return f"{cid} {val} leg"
    return 'free hole'

# ---------------------------------------------------------------- rails / buses (bare 20 AWG on the solder side)
buses = [  # id, step, net, holes (start, end), label
    ('GND rail', 3, 'gnd', 'AA1', 'AA35', 'GND rail (bare wire along row AA)'),
    ('5V rail', 3, 'v5', 'Y1', 'Y20', '5 V rail (bare wire along row Y)'),
    ('GND bus col 2', 3, 'gnd', 'B2', 'W2', 'GND bus col 2: ESP32 GND ↔ Click GND (bare)'),
    ('GND bus col 33', 3, 'gnd', 'F33', 'AA33', 'GND bus col 33: H2 GND, C1−, SIM868 GND lead, PAM GND → rail (bare)'),
    ('VBAT rail', 3, 'vbat', 'D35', 'X35', 'VBAT rail (bare wire along col 35)'),
]
def line(a, b):
    ca, ra = parse(a); cb, rb = parse(b)
    if ra == rb: return [hname(c, ra) for c in range(min(ca, cb), max(ca, cb) + 1)]
    return [hname(ca, r) for r in range(min(ra, rb), max(ra, rb) + 1)]

bridges = [  # step, a, b, note
    (3, 'Z19', 'Y19', 'H1 5V → 5 V rail'), (3, 'Z20', 'AA20', 'H1 GND → GND rail'), (3, 'Q32', 'Q33', 'PAM8403 GND → GND bus'),
    (8, 'J17', 'K17', 'R1 leg → GPIO7'), (8, 'J22', 'K22', 'R1 leg → 3V3 (J1-2)'), (8, 'D34', 'D35', 'R4 leg → VBAT rail'), (8, 'F34', 'F33', 'R5 leg → GND bus col 33'),
]

# ---------------------------------------------------------------- board links (insulated, solder side) – routed automatically
NETCOL = {'gnd': '#3d4044', 'v5': '#c58c5c', 'vbat': '#b3665b', 'v33': '#c7ab5f', 'spi': '#6c8dae', 'i2s': '#8a7fae', 'uart': '#5d9a8b',
          'audio': '#a6799a', 'io': '#7c9a62', 'sense': '#9b8e76', 'geoP': '#b07a6a', 'geoN': '#a7a49d'}
links = [  # step, from, to, net, note
    (3, 'W2', 'AA2', 'gnd', 'GND bus col 2 → GND rail'),
    (3, 'Y3', 'K3', 'v5', '5 V rail → ESP32 5V'),
    (3, 'Y20', 'N20', 'v5', '5 V rail → PCM VIN'),
    (3, 'N20', 'Q31', 'v5', 'PCM VIN → PAM8403 +5V'),
    (3, 'N21', 'AA26', 'gnd', 'PCM GND → GND rail'),
    (3, 'K23', 'W3', 'v33', 'ESP32 3V3 → Click 3V3'),
    (4, 'K6', 'W6', 'spi', 'SCK'), (4, 'K5', 'W5', 'spi', 'MISO'), (4, 'K4', 'W4', 'spi', 'MOSI'), (4, 'K7', 'W7', 'spi', 'ADC chip-select'),
    (4, 'K9', 'N9', 'spi', 'clock-chip select'), (4, 'K8', 'N8', 'spi', 'DRDY, active low'), (4, 'K12', 'W8', 'spi', 'ADC reset'),
    (6, 'K20', 'N24', 'i2s', 'bit clock'), (6, 'K19', 'N22', 'i2s', 'word clock'), (6, 'K18', 'N23', 'i2s', 'data'),
    (6, 'N25', 'AA25', 'gnd', 'SCK → GND rail (SCK must be grounded)'),
    (6, 'Y28', 'Z23', 'audio', 'speaker +'), (6, 'Y29', 'Z24', 'audio', 'speaker −, NOT ground'),
    (7, 'K23', 'J29', 'v33', 'ESP32 3V3 (J1-1) → H2 3V3 (feeds the SIM868 level shifter)'),
    (7, 'K15', 'J30', 'uart', 'GPIO16 → H2 PWRKEY (HIGH 1.5 s = power on/off)'),
    (7, 'K14', 'J31', 'uart', 'GPIO17 (ESP TX) → H2 SIM RXD'),
    (7, 'J32', 'K13', 'uart', 'H2 SIM TXD → GPIO18 (ESP RX)'),
    (8, 'D29', 'F29', 'sense', 'divider node R4–R5'),
    (8, 'F29', 'B20', 'sense', 'VBAT ÷ 2 → GPIO1'),
    (8, 'K17', 'Z22', 'io', 'button line'),
    (8, 'K16', 'Z21', 'io', 'LED data'),
]

# ---------------------------------------------------------------- router
def build_router(cols, rows):
    return {'cols': cols, 'rows': rows, 'node': {}, 'edges': set()}
R = build_router(COLS, ROWS)
def nb(c, r, cols, rows):
    for dc, dr, d in ((1, 0, 'h'), (-1, 0, 'h'), (0, 1, 'v'), (0, -1, 'v')):
        cc, rr = c + dc, r + dr
        if 1 <= cc <= cols and 1 <= rr <= rows: yield cc, rr, (dc, dr), d
def ekey(a, b): return tuple(sorted((a, b)))

def block(R, h, kind='pin'): R['node'][h] = kind
for h in pins: block(R, h, 'nc' if pins[h][1] == 'NC' else 'pin')
for cid, (_, legs, _) in comps.items():
    for h in legs: block(R, h, 'leg')
for b in buses:
    hs = line(b[3], b[4]); ori = 'h' if parse(b[3])[1] == parse(b[4])[1] else 'v'
    for a, c in zip(hs, hs[1:]): R['edges'].add(ekey(a, c))
    for h in hs:
        if h not in R['node']: R['node'][h] = 'rail' + ori
for st, a, b, _ in bridges: R['edges'].add(ekey(a, b))

def route(R, a, b, name):
    cols, rows = R['cols'], R['rows']
    ca, ra = parse(a); cb, rb = parse(b)
    start = (ca, ra, None)
    dist = {start: 0}; prev = {}
    pq = [(0, ca, ra, None)]
    goal = None
    while pq:
        d, c, r, dirv = heapq.heappop(pq)
        if dist.get((c, r, dirv), 1e9) < d: continue
        if (c, r) == (cb, rb): goal = (c, r, dirv); break
        here = hname(c, r)
        hk = R['node'].get(here)
        for cc, rr, dv, ori in nb(c, r, cols, rows):
            # if we are passing through a crossing node we must continue straight
            if (c, r) != (ca, ra) and hk in ('railh', 'railv', 'h', 'v', 'nc') and dirv is not None and dv != dirv: continue
            nh = hname(cc, rr)
            if ekey(here, nh) in R['edges']: continue
            k = R['node'].get(nh)
            if (cc, rr) != (cb, rb):
                if k in ('pin', 'leg', 'corner', 'end'): continue
                if k in ('railh', 'h') and ori == 'h': continue
                if k in ('railv', 'v') and ori == 'v': continue
            cost = 1
            if dirv is not None and dv != dirv: cost += 2.2
            if k in ('railh', 'railv', 'h', 'v'): cost += 1.4
            if k == 'nc': cost += 0.5
            nd = d + cost
            st = (cc, rr, dv)
            if nd < dist.get(st, 1e9):
                dist[st] = nd; prev[st] = (c, r, dirv); heapq.heappush(pq, (nd, cc, rr, dv))
    if goal is None: raise SystemExit(f'no route for {name}: {a} -> {b}')
    path = []; s = goal
    while s in prev or (s[0], s[1]) == (ca, ra):
        path.append(hname(s[0], s[1]))
        if (s[0], s[1]) == (ca, ra): break
        s = prev[s]
    path.reverse()
    # mark usage
    for x, y in zip(path, path[1:]): R['edges'].add(ekey(x, y))
    for i in range(1, len(path) - 1):
        p0, p1, p2 = parse(path[i - 1]), parse(path[i]), parse(path[i + 1])
        straight_h = p0[1] == p1[1] == p2[1]; straight_v = p0[0] == p1[0] == p2[0]
        k = R['node'].get(path[i])
        if k in ('railh', 'railv', 'h', 'v', 'nc'): R['node'][path[i]] = 'corner'  # crossing used twice → close it
        else: R['node'][path[i]] = 'h' if straight_h else ('v' if straight_v else 'corner')
    for e in (a, b):
        if R['node'].get(e) is None: R['node'][e] = 'end'
    return path

def corners(path):
    if len(path) <= 2: return path
    out = [path[0]]
    for i in range(1, len(path) - 1):
        p0, p1, p2 = parse(path[i - 1]), parse(path[i]), parse(path[i + 1])
        if not (p0[0] == p1[0] == p2[0] or p0[1] == p1[1] == p2[1]): out.append(path[i])
    out.append(path[-1]); return out

def r5(x): return int(math.ceil(x / 5.0) * 5)
wires = []
def addwire(**w): w['id'] = len(wires); wires.append(w); return w

for b in buses:
    hs = line(b[3], b[4]); L = (len(hs) - 1) * P
    taps = [h for h in hs if h in pins or any(h in c[1] for c in comps.values())]
    addwire(step=b[1], kind='bus', net=b[2], a=b[3], b=b[4], route=[b[3], b[4]], name=b[0], note=b[5],
            len=round(L, 1), cut=f"bare 20 AWG · cut {r5(L + 10)} mm", taps=taps, side='under')
for st, a, b, note in bridges:
    addwire(step=st, kind='bridge', net='gnd', a=a, b=b, route=[a, b], note=note, len=2.5, cut='solder bridge / bent leg', side='under')
PRIO = {('K6','W6'):0,('K5','W5'):0,('K4','W4'):0,('K7','W7'):0,('K9','N9'):0,('K8','N8'):0,('K12','W8'):1,('K16','Z21'):2,('K17','Z22'):2,('Y28','Z23'):3,('Y29','Z24'):3}
for st, a, b, net, note in sorted(links, key=lambda x: (PRIO.get((x[1], x[2]), 9), x[0])):
    path = route(R, a, b, note)
    L = (len(path) - 1) * P
    addwire(step=st, kind='link', net=net, a=a, b=b, route=corners(path), full=path, note=note, len=round(L, 1),
            cut=f"insulated core · cut {r5(L + 8)} mm, strip 3 mm both ends", side='under')

# ---------------------------------------------------------------- lid board (12 x 8)
lidpins = {'C1': ('Lid header', '5V'), 'D1': ('Lid header', 'GND'), 'E1': ('Lid header', 'DIN'), 'F1': ('Lid header', 'BTN'),
           'C3': ('Button', 'leg 1'), 'C6': ('Button', 'leg 2 (same side)'), 'E3': ('Button', 'leg 3'), 'E6': ('Button', 'leg 4'),
           'A5': ('1N4001', 'anode'), 'A9': ('1N4001', 'cathode (stripe)'),
           'C10': ('WS2812B', '+5V stub'), 'E10': ('WS2812B', 'DIN stub'), 'G10': ('WS2812B', 'GND stub')}
LR = build_router(LCOLS, LROWS)
for h in lidpins: block(LR, h)
lidlinks = [(11, 'C1', 'A5', 'v5', 'header 5V → diode anode'), (11, 'A9', 'C10', 'v5', 'diode cathode → pixel +5V'),
            (11, 'E1', 'E10', 'io', 'header DIN → pixel DIN'), (11, 'D1', 'C3', 'gnd', 'header GND → button leg 1'),
            (11, 'C3', 'G10', 'gnd', 'button leg 1 → pixel GND'), (11, 'F1', 'E6', 'io', 'header BTN → button leg 4 (diagonal)')]
for st, a, b, net, note in lidlinks:
    path = route(LR, a, b, note); L = (len(path) - 1) * P
    addwire(step=st, kind='lid', net=net, a=a, b=b, route=corners(path), full=path, note=note, len=round(L, 1),
            cut=f"insulated core · cut {r5(L + 8)} mm, strip 3 mm both ends", side='lid')

# ---------------------------------------------------------------- off-board wires (explicit 3D)
def top(h, y=YB): x, z = hxz(h); return [x, y, z]
def plen(pts): return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
H1x = {n: hxz(f"Z{c}")[0] for n, c in zip(['5V', 'GND', 'LED', 'BTN', 'SPK+', 'SPK−'], range(19, 25))}
TERM = {'CH1−': [-14.5, 21, -15.3], 'CH1+': [-14.5, 21, -11.3], 'CH2+': [-14.5, 21, -4.3], 'CH2−': [-14.5, 21, -0.3]}
offb = []
def off(step, kind, net, a, b, pts, note='', **kw):
    L = plen(pts); offb.append(dict(step=step, kind=kind, net=net, a=a, b=b, pts=[[round(v, 2) for v in p] for p in pts], note=note, len=round(L, 1), **kw))
# geophone (step 5)
off(5, 'pair', 'geoP', 'SM-24 + tab', 'Click CH1+ screw terminal', [[59, 35.5, -30], [59, 34.2, -30], [45, 34.2, -14], [18, 26.5, -11.3], [-6, 26.5, -11.3], [-11, 21, -11.3], TERM['CH1+']], twin=0)
off(5, 'pair', 'geoN', 'SM-24 − tab', 'Click CH1− screw terminal', [[51, 35.5, -30], [51, 34.2, -30], [43, 34.2, -17], [18, 25.5, -15.3], [-6, 25.5, -15.3], [-11, 21, -15.3], TERM['CH1−']], twin=1)
x18, z18 = hxz('AA18'); x19, z19 = hxz('AA19')
off(5, 'top', 'gnd', 'AA18 (GND rail)', 'Click CH1− screw terminal', [[x18, YB, z18], [x18, 12, z18], [x18, 22, 6], [-11.5, 22, -15.3], TERM['CH1−']], note='2nd wire in CH1−: ties it to ground')
off(5, 'top', 'gnd', 'AA19 (GND rail)', 'Click CH2− screw terminal', [[x19, YB, z19], [x19, 12, z19], [x19, 23, 6], [-11.0, 23, -0.3], TERM['CH2−']], note='grounds the unused channel')
off(5, 'top', 'gnd', 'Click CH2+ screw terminal', 'Click CH2− screw terminal', [TERM['CH2+'], [-12, 21.6, -4.3], [-12, 21.6, -0.3], TERM['CH2−']], note='short loop: CH2 shorted')
# audio (step 6), top side
pl = [-2.5, 11.7, -3.5]; pa = [0, 11.7, -3.5]
qx28, qz28 = hxz('Q28'); qx29, qz29 = hxz('Q29')
off(6, 'top', 'audio', 'PCM5102A pad L (top)', 'PAM8403 pad L in (top, above Q28)', [pl, [-2.5, 13.4, -3.5], [qx28, 13.4, -3.5], [qx28, 11.6, qz28]])
off(6, 'top', 'gnd', 'PCM5102A pad AGND (top)', 'PAM8403 pad ⏚ in (top, above Q29)', [pa, [0, 12.6, -2.6], [qx29, 12.6, -2.6], [qx29, 11.6, qz29]])
# SIM868 (step 7): Waveshare Pico-SIM868 board standing on its long edge in a cradle at the back wall,
# component side facing the main board, antenna edge (header pins 1-20) up. Pico NOT fitted.
SIMZ, SIMY0, SIMY1 = -68.0, 9.0, 33.0           # front face of the SIM868 PCB, bottom / top edge
ROWT, ROWB = 29.9, 12.1                        # socket rows: pins 1-20 (top), pins 21-40 (bottom)
SOCK = SIMZ + 8.5                              # front face of its female sockets
def simpin(n):
    return ([34.4 - (n - 1) * 2.54, ROWT, SOCK] if n <= 20 else [34.4 - (40 - n) * 2.54, ROWB, SOCK])
BATX, BATY = 16.0, 24.0                        # PH2.0 battery socket on the SIM868 board (under the missing Pico)
xL35, zL35 = hxz('L35'); xL33, zL33 = hxz('L33')
off(7, 'w05', 'vbat', 'L35 (VBAT rail, next to C1+)', 'SIM868 battery socket + (PH2.0 plug, red lead)',
    [[xL35, YB, zL35], [xL35, 12.5, zL35], [xL35, 12.5, -57.5], [BATX + 1, BATY, -57.5], [BATX + 1, BATY, SIMZ + 5]], note='SIM868 power: straight from the switched 18650, never 5 V')
off(7, 'w05', 'gnd', 'L33 (GND bus col 33, next to C1−)', 'SIM868 battery socket − (PH2.0 plug, black lead)',
    [[xL33, YB, zL33], [xL33, 11.5, zL33], [xL33, 11.5, -56.5], [BATX - 1, BATY - 0.5, -56.5], [BATX - 1, BATY - 0.5, SIMZ + 5]])
for hole, pin, net, what in (('J29', 36, 'v33', '3V3(OUT)'), ('J30', 19, 'uart', 'GP14 / PWR_EN'), ('J31', 1, 'uart', 'GP0 / RXD'), ('J32', 2, 'uart', 'GP1 / TXD'), ('J33', 3, 'gnd', 'GND')):
    hx_, hz_ = hxz(hole); px, py, pz = simpin(pin); ye = 34.0 - (int(hole[1:]) - 29) * 0.5
    off(7, 'mf', net, f'{hole} (H2 {pins[hole][1].split(" →")[0]})', f'SIM868 header pin {pin} ({what})',
        [[hx_, 30, hz_], [hx_, ye, hz_], [hx_, ye, -40 - (int(hole[1:]) - 29)], [px, ye, -40 - (int(hole[1:]) - 29)], [px, py, -44], [px, py, pz + 14]],
        note='female end on H2, male end straight into the SIM868 socket (Pico removed)', plug='z')

# power (step 9): the power bank is the only source. It sits OUTSIDE the case; a cut USB-A cable enters through the
# grommet in the left wall. Red = 5 V → rocker (main switch) → 5 V rail at Y1. Black = GND → GND rail at AA1.
X35 = top('X35'); AA35 = top('AA35'); Y1 = top('Y1'); AA1 = top('AA1')
BK_IN_H, BK_GND_H = 'Y13', 'AA14'                       # rail holes the step-down takes its input from
BKIN = top(BK_IN_H); BKGND = top(BK_GND_H)
off(9, 'usb', 'v5', 'USB cable red (from the power bank, through the grommet)', 'Rocker pin 1',
    [[-73.0, 6.5, 39.6], [-62, 5, 52], [-40, 8, 70], [30, 8, 70], [45, 8, 40], [45, 8, 20.5], [45, 11.7, 10], [58, 11.7, 4.5], [65, 11.7, 4.5]], note='power bank 5 V into the main switch')
off(9, 'w05', 'v5', 'Rocker pin 2', 'Y1 (5 V rail start)',
    [[65, 18.7, 8.5], [50, 18.7, 8.5], [47, 4, 20], [47, 2, 52], [-55.9, 2, 52], [-55.9, 2, 17], [-55.9, 9.4, 15.5], [Y1[0], 9.4, Y1[2]], Y1], note='switched 5 V → 5 V rail')
off(9, 'usb', 'gnd', 'USB cable black (from the power bank, through the grommet)', 'AA1 (GND rail start)',
    [[-74.0, 5.5, 41.4], [-63.5, 5.5, 41.4], [-57.6, 5.5, 30], [-57.6, 5.5, 17], [-57.6, 9.8, 15.5], [AA1[0], 9.8, AA1[2]], AA1], note='power bank GND → GND rail')
# step-down for the SIM868 (step 10): STP28UD-3A (stock row 291) lying where the 18650 holder used to be, set to 4.0 V.
# 5 V rail → IN, OUT → VBAT rail (col 35) → C1 → SIM868 PH2.0 lead (unchanged).
BK = {'IN+': [-30, 4.6, 32], 'IN−': [-30, 4.6, 39], 'OUT+': [17, 4.6, 32], 'OUT−': [17, 4.6, 39]}
off(10, 'w05', 'v5', f'{BK_IN_H} (5 V rail)', 'Step-down IN+',
    [BKIN, [BKIN[0], 11.5, BKIN[2]], [BKIN[0], 11.5, 20], [-30, 10, 30], BK['IN+']], note='5 V into the step-down')
off(10, 'w05', 'gnd', f'{BK_GND_H} (GND rail)', 'Step-down IN−',
    [BKGND, [BKGND[0], 10.5, BKGND[2]], [BKGND[0], 10.5, 22], [-33, 9, 39], BK['IN−']], note='ground into the step-down')
off(10, 'w05', 'vbat', 'Step-down OUT+ (4.0 V)', 'X35 (VBAT rail end)',
    [BK['OUT+'], [17, 11, 30], [33.5, 11, 16], [33.5, 11, X35[2]], [X35[0], 11, X35[2]], X35], note='4.0 V → VBAT rail → SIM868')
off(10, 'w05', 'gnd', 'Step-down OUT−', 'AA35 (GND rail end)',
    [BK['OUT−'], [17, 10, 41], [AA35[0], 10, 22], [AA35[0], 10, AA35[2]], AA35], note='step-down output ground')
# harness (step 12)
LIDZ = {'5V': -3.81, 'GND': -1.27, 'DIN': 1.27, 'BTN': 3.81}
for n, lz, net, lidn in (('5V', LIDZ['5V'], 'v5', '5V'), ('GND', LIDZ['GND'], 'gnd', 'GND'), ('LED', LIDZ['DIN'], 'io', 'DIN'), ('BTN', LIDZ['BTN'], 'io', 'BTN')):
    x = H1x[n]
    off(12, 'ff', net, f'H1 {n} (Z{list(H1x).index(n) + 19})', f'Lid header {lidn}', [[x, 30, 10.48], [x, 32.6, 10.48], [x, 32.6, lz], [-19, 32.6, lz], [-15, 27.3, lz]], harness=True)
off(12, 'ffcut', 'audio', 'H1 SPK+ (Z23)', 'Speaker + tab', [[H1x['SPK+'], 30, 10.48], [H1x['SPK+'], 33.2, 10.48], [H1x['SPK+'], 33.2, 31], [-24.5, 32, 31]], harness=True)
off(12, 'ffcut', 'audio', 'H1 SPK− (Z24)', 'Speaker − tab', [[H1x['SPK−'], 30, 10.48], [H1x['SPK−'], 33.8, 10.48], [H1x['SPK−'], 33.8, 39], [-24.5, 32, 39]], harness=True)

SLACK = {'pair': 25, 'top': 10, 'lead': 10, 'w05': 15, 'usb': 15, 'ff': 25, 'ffcut': 25, 'mf': 20}
for w in offb:
    L = w['len'] + SLACK[w['kind']]
    k = w['kind']
    if k == 'pair': cut = f"6×0.22 cable core · cut {r5(L)} mm, twist the two cores ~1 turn/cm"
    elif k == 'top': cut = f"insulated core · cut {r5(L)} mm, strip 5 mm (screw end) / 3 mm"
    elif k == 'lead': cut = f"holder lead · trim to {r5(L)} mm, strip 4 mm"
    elif k == 'w05': cut = f"0.5 mm² {'red' if w['net'] in ('vbat', 'v5') else 'black'} · cut {r5(L)} mm, strip 4 mm, tin"
    elif k == 'usb': cut = f"USB-A cable, {'red' if w['net'] == 'v5' else 'black'} core · {r5(L)} mm past the grommet, strip 4 mm, tin (white + green cut short, taped)"
    elif k == 'mf':
        assert L <= 100, f'M-F jumper too short for {w["a"]}: {L} mm'
        cut = 'M-F jumper 10 cm (stock row 39), used as is: female end on H2, male end into the SIM868 socket'
    elif k == 'ff': cut = f"F-F jumper → {r5(L)} mm: cut {100 - r5(L)} mm out of the middle, splice + heat-shrink"
    else: cut = f"F-F jumper → {r5(L)} mm: keep one female end, cut {100 - r5(L)} mm off, solder to the speaker tab"
    w['cut'] = cut; w['L'] = r5(L); w['side'] = 'off'
    addwire(**w)

# ---------------------------------------------------------------- checks
used = {}
for w in wires:
    if w['kind'] in ('link', 'lid'):
        assert w['a'] != w['b']
problems = []
for h in (BK_IN_H, BK_GND_H):   # rail holes that take an off-board wire must be free of pins, legs and links
    if h in pins or any(h in c[1] for c in comps.values()): problems.append(f'{h} is a pin/leg')
    for w in wires:
        if w['kind'] in ('link', 'bridge') and h in (w.get('full') or w['route']): problems.append(f'{h} used by {w["kind"]} {w["a"]}->{w["b"]}')
for st, a, b, _ in bridges:
    ca, ra = parse(a); cb, rb = parse(b)
    if abs(ca - cb) + abs(ra - rb) != 1: problems.append(f'bridge not adjacent {a}-{b}')
if problems: raise SystemExit('\n'.join(problems))

data = {'P': P, 'BX0': BX0, 'BZ0': BZ0, 'COLS': COLS, 'ROWS': ROWS, 'RN': RN, 'LX0': LX0, 'LZ0': LZ0, 'LCOLS': LCOLS, 'LROWS': LROWS,
        'pins': {h: list(v) for h, v in pins.items()}, 'lidpins': {h: list(v) for h, v in lidpins.items()},
        'comps': {k: {'val': v[0], 'legs': v[1], 'note': v[2], 'step': comp_step[k]} for k, v in comps.items()},
        'wires': wires, 'netcol': NETCOL}
os.makedirs(OUT, exist_ok=True)
json.dump(data, open(os.path.join(OUT, 'data.json'), 'w', encoding='utf-8'), ensure_ascii=False)
print('wires', len(wires), 'links', sum(1 for w in wires if w['kind'] == 'link'))
for w in wires:
    if w['kind'] in ('link', 'lid'): print(w['step'], w['a'], '->', w['b'], ' via ', ' '.join(w['route'][1:-1]), f"{w['len']}mm")
