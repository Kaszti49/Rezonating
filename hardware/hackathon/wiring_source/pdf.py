"""Builds the printable wiring list (HTML -> PDF via Edge) from out/data.json."""
import json, os, sys, html, re
here = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(here, 'out', 'data.json'), encoding='utf-8'))
OUT = sys.argv[1]
P, BX0, BZ0, COLS, ROWS, RN = D['P'], D['BX0'], D['BZ0'], D['COLS'], D['ROWS'], D['RN']
PINS, LPINS, COMPS, WIRES, NC = D['pins'], D['lidpins'], D['comps'], D['wires'], D['netcol']
NC = dict(NC, bare='#a9aeb2')
esc = html.escape

def parse(h):
    m = re.match(r'^([A-Z]+)(\d+)$', h); return int(m.group(2)), RN.index(m.group(1)) + 1

def what(h, lid=False):
    p = (LPINS if lid else PINS).get(h)
    if p: return f"<b>{esc(p[0])}</b> {esc(p[1])}"
    if not lid:
        for cid, c in COMPS.items():
            if h in c['legs']: return f"<b>{cid}</b> {esc(c['val'])} leg"
        c, r = parse(h); row = RN[r - 1]
        if row == 'AA': return '<b>GND rail</b>'
        if row == 'Y' and c <= 20: return '<b>5 V rail</b>'
        if c == 35 and 4 <= r <= 24: return '<b>VBAT rail</b>'
        if c == 2 and 2 <= r <= 23: return '<b>GND bus</b> col 2'
        if c == 33 and r >= 6: return '<b>GND bus</b> col 33'
    return 'free hole'

def hole_in(text):
    m = re.search(r'(?:^|\()([A-Z]{1,2}\d{1,2})(?=[ )])', text)
    if not m: return None, text
    h = m.group(1)
    try:
        c, r = parse(h)
        if c > COLS: return None, text
    except Exception: return None, text
    t = text.replace(f'({h})', '').strip()
    if t.startswith(h + ' '): t = t[len(h) + 1:]
    return h, t.replace('(', '').replace(')', '').strip()

# ------------------------------------------------------------------ SVG board map
S, M = 15.5, 34
FOOT = {  # module outlines in mm (x1, z1, x2, z2), label
    'esp': (-57.47, -52.05, 5.53, -26.05, 'ESP32-S3', '#6f8299'), 'click': (-56.5, -21.27, -13.6, 4.13, 'ADC 15 Click', '#8ea38a'),
    'pcm': (-10.57, -21.5, 9.43, 8.5, 'PCM5102A', '#8e86a3'), 'pam': (9.48, -13.22, 27.48, 8.78, 'PAM8403', '#9b9a72'),
    'h2': (14.2, -32.6, 27.8, -27.7, 'H2', '#a5776e')}
PARTCOL = {'ESP32-S3': '#6f8299', 'Click': '#7f977b', 'PCM5102A': '#857c9c', 'H2': '#a5776e', 'PAM8403': '#8f8e66', 'H1': '#4b4e51'}

def svg_board(step=None, solder=True, highlight=None, comp_view=False):
    W = (COLS - 1) * S + 2 * M; H = (ROWS - 1) * S + 2 * M
    def X(c): x = M + (c - 1) * S; return W - x if solder else x
    def Y(r): return M + (r - 1) * S
    def mmX(x): return X(1 + (x - BX0) / P)
    def mmY(z): return Y(1 + (z - BZ0) / P)
    o = [f'<svg viewBox="0 0 {W} {H + 16}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="IBM Plex Mono, Consolas, monospace">']
    boxes = []
    def tag(x, y, text, fill):
        w_, h_ = len(text) * 6.2 + 6, 10.5
        for dx, dy in ((6, -13), (6, 3), (-6 - w_, -13), (-6 - w_, 3), (6, -25), (6, 15), (-6 - w_, -25), (-6 - w_, 15)):
            r = (x + dx, y + dy, x + dx + w_, y + dy + h_)
            if not any(r[0] < b[2] and r[2] > b[0] and r[1] < b[3] and r[3] > b[1] for b in boxes): break
        boxes.append(r)
        return f'<g><rect x="{r[0]}" y="{r[1]}" width="{w_}" height="{h_}" rx="2" fill="{fill}"/><text x="{r[0] + 3}" y="{r[1] + 7.8}" font-size="8" fill="#fff" font-weight="600">{text}</text></g>'
    o.append(f'<rect x="{M - 12}" y="{M - 12}" width="{W - 2 * M + 24}" height="{H - 2 * M + 24}" rx="6" fill="#efe7cf" stroke="#c9bd98"/>')
    for c in range(1, COLS + 1):
        b = c % 5 == 0
        for yy in (M - 20, H - M + 26):
            o.append(f'<text x="{X(c)}" y="{yy}" font-size="{8.6 if b else 7.6}" font-weight="{700 if b else 400}" fill="{"#2a2c2e" if b else "#6b6f73"}" text-anchor="middle">{c}</text>')
    for r in range(1, ROWS + 1):
        for xx in (M - 24, W - M + 24):
            o.append(f'<text x="{xx}" y="{Y(r) + 3}" font-size="8.4" font-weight="600" fill="#2a2c2e" text-anchor="middle">{RN[r - 1]}</text>')
    # footprints
    for k, (x1, z1, x2, z2, lab, col) in FOOT.items():
        a, b = sorted((mmX(x1), mmX(x2))); t, bt = mmY(z1), mmY(z2)
        o.append(f'<rect x="{a}" y="{t}" width="{b - a}" height="{bt - t}" rx="4" fill="{col}" fill-opacity="{0.16 if comp_view else 0.07}" stroke="{col}" stroke-opacity=".7" stroke-dasharray="{"" if comp_view else "4 3"}"/>')
        o.append(f'<text x="{(a + b) / 2}" y="{(t + bt) / 2 + 4}" font-size="10" font-family="IBM Plex Sans, Arial" font-weight="700" fill="{col}" fill-opacity=".55" text-anchor="middle">{lab}{"" if comp_view else " (other side)"}</text>')
    for c in range(1, COLS + 1):
        for r in range(1, ROWS + 1):
            o.append(f'<circle cx="{X(c)}" cy="{Y(r)}" r="1.9" fill="#cdbf95"/>')
    def pt(h): c, r = parse(h); return X(c), Y(r)
    hl = set(highlight or [])
    cur = [w for w in WIRES if w['side'] == 'under' and (step is None or w['step'] <= step)]
    # rails/buses first
    for w in sorted(cur, key=lambda w: (w['step'] == step, w['kind'] != 'bus')):
        hs = w.get('full') or w['route']
        pts = ' '.join(f'{pt(h)[0]},{pt(h)[1]}' for h in hs)
        now = step is None or w['step'] == step
        if w['kind'] == 'bus':
            o.append(f'<polyline points="{pts}" fill="none" stroke="{"#9aa1a6" if now else "#d4d7d9"}" stroke-width="{4.2 if now else 3}" stroke-linecap="round"/>')
        elif w['kind'] == 'bridge':
            o.append(f'<polyline points="{pts}" fill="none" stroke="{"#6b7378" if now else "#c9cdd0"}" stroke-width="{5 if now else 3.5}" stroke-linecap="round"/>')
        else:
            col = NC[w['net']] if now else '#cfc9be'
            o.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="{2.8 if now else 1.5}" stroke-linejoin="round" stroke-linecap="round"/>')
    # pins / legs
    for h, (part, lab) in PINS.items():
        x, y = pt(h); col = PARTCOL.get(part, '#555')
        o.append(f'<circle cx="{x}" cy="{y}" r="3.4" fill="{col}" fill-opacity="{0.95 if lab != "NC" else 0.35}"/>')
    for cid, cc in COMPS.items():
        if step is not None and cc['step'] > step: continue
        hs = list(cc['legs']);
        (x1, y1), (x2, y2) = pt(hs[0]), pt(hs[1])
        if comp_view: o.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#bfae84" stroke-width="5" stroke-linecap="round"/>')
        for h in hs:
            x, y = pt(h); o.append(f'<rect x="{x - 3.2}" y="{y - 3.2}" width="6.4" height="6.4" rx="1.2" fill="#c4a96d" stroke="#8a7446" stroke-width=".8"/>')
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        o.append(f'<text x="{mx}" y="{my - 5}" font-size="7.4" fill="#6e5a2e" font-weight="600" text-anchor="middle">{cid}</text>')
    # labels for the current step's ends
    if step is not None or highlight:
        seen = set()
        for w in WIRES:
            if w['side'] != 'under' or (step is not None and w['step'] != step): continue
            for h in ([w['a'], w['b']] if w['kind'] != 'bus' else [w['a'], w['b']]):
                if h in seen: continue
                seen.add(h); x, y = pt(h)
                o.append(f'<circle cx="{x}" cy="{y}" r="5.6" fill="none" stroke="#2a2c2e" stroke-width="1.3"/>')
                o.append(tag(x, y, h, '#2a2c2e'))
        for h in hl:
            if h in seen: continue
            x, y = pt(h)
            o.append(f'<circle cx="{x}" cy="{y}" r="5.6" fill="none" stroke="#b3665b" stroke-width="1.6"/>')
            o.append(tag(x, y, h, '#b3665b'))
    side = 'SOLDER SIDE · board turned over like a page · row A at the top · column 1 on the RIGHT' if solder else 'COMPONENT SIDE · row A (back) at the top · column 1 on the left · solder-side wires shown through the board'
    o.append(f'<text x="{W / 2}" y="{H + 12}" font-size="8.6" font-weight="600" fill="#2a2c2e" text-anchor="middle" font-family="IBM Plex Sans, Arial">{side}</text>')
    o.append('</svg>'); return ''.join(o)

LCOLS, LROWS = D['LCOLS'], D['LROWS']
def svg_lid(solder=True):
    s, m = 26, 36
    W = (LCOLS - 1) * s + 2 * m; H = (LROWS - 1) * s + 2 * m
    def X(c): x = m + (c - 1) * s; return W - x if solder else x
    def Y(r): return m + (r - 1) * s
    def pt(h): c, r = parse(h); return X(c), Y(r)
    o = [f'<svg viewBox="0 0 {W} {H + 14}" width="62%" xmlns="http://www.w3.org/2000/svg" font-family="IBM Plex Mono, Consolas, monospace">']
    o.append(f'<rect x="{m - 14}" y="{m - 14}" width="{W - 2 * m + 28}" height="{H - 2 * m + 28}" rx="6" fill="#efe7cf" stroke="#c9bd98"/>')
    for c in range(1, LCOLS + 1): o.append(f'<text x="{X(c)}" y="{m - 20}" font-size="10" text-anchor="middle" fill="#2a2c2e">{c}</text>')
    for r in range(1, LROWS + 1):
        for xx in (m - 26, W - m + 26): o.append(f'<text x="{xx}" y="{Y(r) + 3.5}" font-size="10" font-weight="600" text-anchor="middle" fill="#2a2c2e">{RN[r - 1]}</text>')
    for c in range(1, LCOLS + 1):
        for r in range(1, LROWS + 1): o.append(f'<circle cx="{X(c)}" cy="{Y(r)}" r="2.6" fill="#cdbf95"/>')
    for w in WIRES:
        if w['side'] != 'lid': continue
        pts = ' '.join(f'{pt(h)[0]},{pt(h)[1]}' for h in w['full'])
        o.append(f'<polyline points="{pts}" fill="none" stroke="{NC[w["net"]]}" stroke-width="3.6" stroke-linejoin="round" stroke-linecap="round"/>')
    for h, (part, lab) in LPINS.items():
        x, y = pt(h); o.append(f'<circle cx="{x}" cy="{y}" r="5" fill="#4b4e51"/>')
        o.append(f'<g><rect x="{x + 7}" y="{y - 16}" width="{len(h) * 7 + 6}" height="12" rx="2" fill="#2a2c2e"/><text x="{x + 10}" y="{y - 7}" font-size="9" fill="#fff" font-weight="600">{h}</text></g>')
    o.append(f'<text x="{W / 2}" y="{H + 8}" font-size="10" font-weight="600" text-anchor="middle" font-family="IBM Plex Sans, Arial" fill="#2a2c2e">LID BOARD · LINK SIDE (turned over like a page: column 1 on the RIGHT)</text></svg>')
    return ''.join(o)

# ------------------------------------------------------------------ steps (same numbering as the 3D guide)
TOOLS = {'solder': 'Soldering station', 'cut': 'Cutting bench', 'screw': 'Small flat screwdriver', 'meter': 'Multimeter', 'hands': 'Hands only', 'laptop': 'Laptop + USB-C'}
STEPS = {
    2: ('Cut the perfboard', ['cut'], 'Cut the 9 × 15 cm perfboard (stock row 101) into the main board (35 columns × 27 rows of holes, ≈ 90 × 70 mm) and the lid board (12 × 8 holes, ≈ 30 × 20 mm). Score both sides along a hole row, snap, sand flat, knock 1 mm off each corner. With a pen, write “A” at the back edge and “1” at the left edge on BOTH sides of the main board.', []),
    3: ('Sockets, headers & module pins', ['solder', 'cut'], 'Component side up. Solder every socket and header before any wire. Plug the module in while soldering so the rows stay parallel; tack one pin at each end first, check, then solder the rest.', [
        ('B2 … B23', 'ESP32-S3 J3 socket, 22 contacts. B23 = J3-1 (GND, antenna end), B2 = J3-22 (GND, USB end)'),
        ('K2 … K23', 'ESP32-S3 J1 socket, 22 contacts. K23 = J1-1 (3V3), K3 = J1-21 (5V), K2 = J1-22 (GND)'),
        ('N2 … N9', 'Click back header socket, 8 contacts. N9 = CS2, N8 = INT, N7–N3 = NC, N2 = GND'),
        ('W2 … W9', 'Click front header socket, 8 contacts. W9 = NC, W8 = RST, W7 = CS1, W6 = SCK, W5 = SDO, W4 = SDI, W3 = 3V3, W2 = GND'),
        ('J29 … J33', 'H2 SIM868 header, 5 male pins pointing up: J29 3V3, J30 PWRKEY, J31 SIM RXD, J32 SIM TXD, J33 GND (the SIM868 board itself is off the perfboard, at the back wall)'),
        ('N20 … N25', 'PCM5102A: its own male header soldered straight into the board. N20 VIN, N21 GND, N22 LCK, N23 DIN, N24 BCK, N25 SCK'),
        ('Q28 … Q32', 'PAM8403 input/power pins (male header pins, module 2 mm above the board): Q28 L in, Q29 ⏚ in, Q30 R in, Q31 +5V, Q32 GND'),
        ('Y28 Y29 Y31 Y32', 'PAM8403 output pins: Y28 L+, Y29 L−, Y31 R−, Y32 R+'),
        ('Z19 … Z24', 'H1 lid header, 6 male pins pointing up: Z19 5V, Z20 GND, Z21 LED, Z22 BTN, Z23 SPK+, Z24 SPK−')]),
    4: ('Rails, buses & power distribution', ['solder', 'cut'], 'Board turned over (solder side). Lay the bare rails first, then fit C3, then the bridges and links. Bare wire: straighten 20 AWG, lay it across the pads, solder at every hole that has a pin or leg and at every 4th hole in between.', []),
    5: ('ADC 15 Click ↔ ESP32-S3 (SPI)', ['solder'], 'Seven links on the solder side. Six run straight in one column and pass the Click’s unused NC pins (N3–N7, W9): keep the insulation intact there.', []),
    6: ('Geophone → Click CH1', ['solder', 'screw'], 'Solder the 1 kΩ resistor across the two SM-24 solder tabs. Twist two cores of the 6×0.22 cable (about 1 turn per cm), solder to the tabs (mark the + core). Screw-terminal ends: strip 5 mm, twist, tin lightly. Each terminal takes at most two conductors.', []),
    7: ('Audio: I²S, DAC → amp → H1', ['solder'], 'Before wiring, set the PCM5102A back-side jumpers: 1 FLT = L, 2 DEMP = L, 3 XSMT = H, 4 FMT = L. The two DAC → amp wires run on the component side, pad to pad on top of the modules.', []),
    8: ('SIM868: power leads, UART, jumpers', ['solder', 'cut'], 'The Waveshare Pico-SIM868 board is used as a modem only: pull the Pico H off it, it is not used. Fit C1, then the four links on the solder side to H2. Then the two 0.5 mm² power leads from L35/L33 (top side) to a PH2.0 plug for the board’s battery socket, and five M-F jumpers from H2 into the board’s Pico sockets. Before power-on: GSM antenna on the “GSM” u.FL socket, nano SIM (PIN off) in the slot, the board’s power slide switch on the battery side.', [
        ('pin 1 (GP0)', 'SIM868 RXD, through the board’s own 3.3 V ↔ 2.8 V level shifter. From H2 J31 ← GPIO17 (ESP TX). No divider needed.'),
        ('pin 2 (GP1)', 'SIM868 TXD. To H2 J32 → GPIO18 (ESP RX).'),
        ('pin 3', 'GND. From H2 J33 (GND bus col 33).'),
        ('pin 19 (GP14)', 'PWR_EN: drives an NPN on the SIM868 PWRKEY. HIGH for 1.5 s switches the module on (or off). From H2 J30 ← GPIO16.'),
        ('pin 36 (3V3 OUT)', 'Powers the board’s level shifter, microphone and RTC backup. From H2 J29 ← ESP32 3V3. Without it the UART stays dead.'),
        ('pin 39, pin 40', 'VSYS, VBUS: leave EMPTY. Never 5 V into this board.'),
        ('BAT (PH2.0)', 'Battery socket → SIM868 VBAT (3.4–4.4 V, 2 A bursts). Red lead from L35 (VBAT rail), black from L33 (GND bus). Check polarity against the plug of the Li-po in the box.'),
        ('GSM (u.FL)', 'GSM antenna, stuck flat to the inner wall at the back left. GNSS and BT sockets stay empty.')]),
    9: ('Battery sense, button & LED lines', ['solder'], 'R4, R5 (free area at the back right, rows D and F) and R1 (under the ESP32-S3) go in from the component side; bridges and links on the solder side.', []),
    10: ('Power bank → rocker → 5 V rail', ['cut', 'solder', 'meter'], 'The power bank is the only power source and stays OUTSIDE the case. Cut the far plug off a USB-A cable, feed it through the grommet in the left wall, strip ~60 mm of jacket: red = 5 V, black = GND, white and green cut short and taped. Check with the meter first (power bank on: red to black ≈ 5.0 V). Push the rocker into the base cutout from outside, then solder: USB red → rocker pin 1, rocker pin 2 → Y1, USB black → AA1 (lamp pin unused). Rail-end holes: push the tinned wire through from the component side and solder it to the rail underneath. Cable tie on the jacket inside the grommet. Auto-off test before building: run the ESP32 alone from the power bank for 2–3 minutes; if it switches off, find its always-on / low-current mode. A 5 W power bank gives about 1 A in total: the firmware must not play the voice line while the SIM868 call is connecting.', []),
    11: ('Step-down 4.0 V for the SIM868', ['meter', 'solder'], 'The SIM868 must never see 5 V. The STP28UD-3A module (stock row 291) lies flat in the pocket where the 18650 holder was. Set it first: 5 V on IN only, nothing on OUT, turn the trimmer until OUT reads 4.00 V (±0.05 V). Then wire it: IN+ from Y13, IN− from AA14, OUT+ to X35 (VBAT rail), OUT− to AA35. The VBAT rail feeds C1 and the SIM868 PH2.0 lead as before; R4/R5 now read the fixed 4.0 V, not a battery.', []),
    12: ('Lid board: button, LED, diode', ['solder', 'cut'], 'Lid board, component side up: fit the parts into the listed holes, then turn it over and make the links. The header pins are bent 90° outward over the edge after soldering.', []),
    13: ('Lid harness & speaker leads', ['cut', 'solder'], 'Four F-F jumpers are shortened (cut the stated length out of the middle, strip 4 mm, twist, solder, heat-shrink) and two are cut for the speaker (keep one female plug, solder the cut end to the speaker tab, heat-shrink).', []),
}
LIDPARTS = [('C1 D1 E1 F1', 'Lid header, 4 straight pins (C1 5V, D1 GND, E1 DIN, F1 BTN), bent 90° outward over the edge'),
            ('C3 C6 E3 E6', 'Tact switch legs (C3 + C6 are joined inside, E3 + E6 are joined inside)'),
            ('A5 → A9', '1N4001: anode A5, cathode (stripe) A9'),
            ('C10 E10 G10', 'WS2812B single pixel: stubs (resistor-leg offcuts) from its +5V, DIN, GND pads into C10, E10, G10')]
ORDER = {'bus': 0, 'bridge': 2, 'link': 3, 'lid': 3, 'top': 4, 'pair': 1, 'lead': 1, 'w05': 4, 'usb': 4, 'ff': 1, 'ffcut': 2, 'mf': 5}
KINDNAME = {'bus': 'Bare wire', 'bridge': 'Bridge', 'link': 'Link', 'lid': 'Link', 'top': 'Top wire', 'pair': 'Pair', 'lead': 'Lead', 'w05': '0.5 mm²', 'usb': 'USB cable', 'ff': 'Jumper', 'ffcut': 'Jumper', 'mf': 'Jumper'}

def end_cell(w, which):
    h = w[which]
    if w['side'] in ('under', 'lid'):
        return f'<span class="h">{h}</span> {what(h, w["side"] == "lid")}'
    hh, txt = hole_in(h)
    if hh: return f'<span class="h">{hh}</span> {esc(txt)}'
    return f'<span class="h off">↗</span> {esc(h)}'

def ops_table(step):
    rows = []; n = 0
    comps = [(k, c) for k, c in COMPS.items() if c['step'] == step - 1]
    for k, c in comps:
        n += 1
        legs = ' '.join(f'<span class="h">{h}</span>{"" if l in "ab" else " " + esc(l)}' for h, l in c['legs'].items())
        rows.append(f'<tr><td class="n">{step}.{n}</td><td class="k">Part</td><td colspan="2"><b>{k}</b> {esc(c["val"])} · {esc(c["note"])}<br>legs into {legs} (component side)</td><td></td><td>bend legs flat after soldering</td></tr>')
    ws = sorted([w for w in WIRES if w['step'] == step - 1], key=lambda w: (ORDER[w['kind']], w['id']))
    for w in ws:
        n += 1
        col = '#a9aeb2' if w['kind'] in ('bus', 'bridge') else NC[w['net']]
        if w['kind'] == 'bus':
            route = f"along {w['a']} → {w['b']}<br>solder at: {', '.join(w['taps'] + [w['a'], w['b']])}"
        elif w['side'] in ('under', 'lid') and w['kind'] != 'bridge':
            route = ('via ' + ' → '.join(w['route'][1:-1])) if len(w['route']) > 2 else 'straight'
        else: route = ''
        note = f'<div class="note">{esc(w.get("note") or "")}</div>' if w.get('note') else ''
        rows.append(f'<tr><td class="n">{step}.{n}</td><td class="k"><span class="sw" style="background:{col}"></span>{KINDNAME[w["kind"]]}</td>'
                    f'<td>{end_cell(w, "a")}</td><td>{end_cell(w, "b")}{note}</td><td class="route">{route}</td><td class="cut">{esc(w["cut"])}</td></tr>')
    if not rows: return ''
    return ('<table class="ops"><thead><tr><th>#</th><th>Type</th><th>From</th><th>To</th><th>Route (solder side)</th><th>Wire / cut</th></tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table>')

def holes_table(items):
    return '<table class="holes">' + ''.join(f'<tr><td><span class="h">{a}</span></td><td>{esc(b)}</td></tr>' for a, b in items) + '</table>'

# ------------------------------------------------------------------ document
css = """
@page { size: A4; margin: 12mm 11mm 13mm 11mm; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "IBM Plex Sans", "Segoe UI", Arial, sans-serif; color: #2a2c2e; font-size: 8.6pt; line-height: 1.35; background: #fff; }
h1 { font-size: 19pt; margin: 0 0 2px; letter-spacing: -.2px; } h1 b { color: #5f8f8b; letter-spacing: 1.2px; }
h2 { font-size: 13pt; margin: 0 0 4px; display: flex; align-items: baseline; gap: 8px; }
h2 .num { font: 600 10pt "IBM Plex Mono", monospace; color: #fff; background: #2a2c2e; border-radius: 4px; padding: 1px 7px; }
h3 { font: 600 8pt "IBM Plex Mono", monospace; letter-spacing: 1px; text-transform: uppercase; color: #7b7f83; margin: 10px 0 4px; }
.sub { color: #7b7f83; font-size: 9pt; }
.page { page-break-before: always; }
.tools span { display: inline-block; border: 1px solid #d1cbc0; border-radius: 99px; padding: 0 8px; margin-right: 4px; font-size: 8pt; font-weight: 600; }
.tools span.solder { color: #a9655b; border-color: #e6c9c3; background: #f5e6e3; }
.tools span.meter { color: #a7783e; border-color: #ead7b8; background: #f6eddf; }
p.intro { margin: 5px 0 6px; }
.h { display: inline-block; min-width: 26px; font: 600 8pt "IBM Plex Mono", monospace; background: #2a2c2e; color: #fff; border-radius: 3px; padding: 0 4px; text-align: center; }
.h.off { background: #8c8f93; }
table { border-collapse: collapse; width: 100%; }
table.ops th { text-align: left; font: 600 7pt "IBM Plex Mono", monospace; letter-spacing: .5px; text-transform: uppercase; color: #7b7f83; border-bottom: 1.2px solid #2a2c2e; padding: 3px 4px; }
table.ops td { border-bottom: 1px solid #e0dbd2; padding: 3.5px 4px; vertical-align: top; }
table.ops tr { page-break-inside: avoid; }
td.n { font: 600 8pt "IBM Plex Mono", monospace; color: #7b7f83; width: 30px; white-space: nowrap; }
td.k { width: 64px; white-space: nowrap; font-weight: 600; }
td.route { font: 7.6pt "IBM Plex Mono", monospace; color: #4b5a66; width: 120px; }
td.cut { font: 7.4pt "IBM Plex Mono", monospace; color: #5d5f62; width: 150px; }
.note { color: #7b7f83; font-size: 7.6pt; margin-top: 1px; }
.sw { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; box-shadow: inset 0 0 0 1px rgba(0,0,0,.2); }
table.holes td { padding: 2.5px 4px; border-bottom: 1px solid #e0dbd2; vertical-align: top; }
table.holes td:first-child { width: 120px; }
.map { margin-top: 6px; page-break-inside: avoid; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.box { border: 1px solid #e0dbd2; border-radius: 6px; padding: 7px 9px; }
.box h3 { margin-top: 0; }
.warn { border: 1px solid #e6c9c3; background: #f5e6e3; color: #7e4a42; border-radius: 6px; padding: 6px 9px; margin-top: 6px; }
ul { margin: 2px 0; padding-left: 15px; } li { margin: 1.5px 0; }
.leg { display: inline-flex; align-items: center; gap: 5px; margin-right: 10px; } .leg i { width: 16px; height: 4px; border-radius: 2px; display: inline-block; }
.chk td:first-child { width: 14px; } .chk .cb { display: inline-block; width: 9px; height: 9px; border: 1.2px solid #8c959f; border-radius: 2px; }
table.chk td { border-bottom: 1px solid #e0dbd2; padding: 2.5px 4px; }
"""
o = [f'<!doctype html><html><head><meta charset="utf-8"><title>Rezon Wiring List</title><link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;600;700&display=swap" rel="stylesheet"><style>{css}</style></head><body>']
# ---- page 1
n_link = sum(1 for w in WIRES if w['kind'] in ('link', 'lid'))
o.append('<h1><b>REZON</b> fall detector · wiring list</h1><div class="sub">SM-24 geophone · ADC 15 Click · ESP32-S3 · PCM5102A + PAM8403 · SIM868 (Waveshare) · power bank 5 V + 4.0 V step-down for the SIM868 · hackathon build · 2026-11-13 · same numbering as the 3D guide (Rezon_Wiring_Guide.html)</div>')
o.append('<div class="grid2" style="margin-top:10px"><div class="box"><h3>How to read a hole</h3><ul>'
         '<li>Main board: <b>rows A … Z, AA</b> (27) from the back edge to the front edge; <b>columns 1 … 35</b> from left to right, <b>seen from the component side</b> with the rails and H1 at the front.</li>'
         '<li><span class="h">K6</span> = row K, column 6. Lid board: rows A–H, columns 1–12, same rule.</li>'
         '<li>On the <b>solder side</b> (board turned over like a page) row A stays at the top and <b>column 1 is on the right</b>. All maps of solder-side work are drawn that way.</li>'
         '<li>Write “A” and “1” on both sides of the board before you start.</li></ul></div>'
         '<div class="box"><h3>How every connection is made</h3><ul>'
         '<li><b>Bare wire</b> (rails/buses): 20 AWG solid, laid across the pads on the solder side, soldered at each listed hole.</li>'
         '<li><b>Bridge</b>: bend the component leg flat onto the neighbouring pin and solder both (one joint).</li>'
         f'<li><b>Link</b> ({n_link}×): one insulated core from the 6×0.22 cable on the solder side. Cut to the listed length, strip 3 mm both ends, solder each end onto the named pin leg. “via” lists the corner holes the wire passes over.</li>'
         '<li><b>Top wire</b>: on the component side (screw terminals, module pads).</li>'
         '<li>Two wires may cross (insulated); a link never runs along a bare rail.</li></ul></div></div>')
o.append('<div class="box" style="margin-top:8px"><h3>Colours used in this list</h3>' + ''.join(f'<span class="leg"><i style="background:{c}"></i>{n}</span>' for n, c in [('GND', NC['gnd']), ('5 V', NC['v5']), ('VBAT', NC['vbat']), ('3V3', NC['v33']), ('SPI', NC['spi']), ('I²S', NC['i2s']), ('UART', NC['uart']), ('Speaker', NC['audio']), ('LED/button', NC['io']), ('VBAT sense', NC['sense']), ('Bare wire', '#a9aeb2')]) + '<div class="sub" style="margin-top:3px">Colours are for reading the list. The insulated cores can be any colour; label both ends with tape if they are all the same.</div></div>')
o.append('<h3>Board layout · component side</h3><div class="map">' + svg_board(None, solder=False, comp_view=True) + '</div>')
o.append('<div class="warn"><b>Check your modules first.</b> The ESP32-S3 rows must be 9 holes apart (B and K), the Click rows 9 apart (N and W). If one of yours differs, shift that module’s second row and every hole that refers to it. Firmware pin map: SCK 12, MISO 13, MOSI 14, ADC-CS 11, clock-CS 9, DRDY 10, ADC-RST 8, I²S BCK 4 / LCK 5 / DIN 6, SIM868 TXD→GPIO18, GPIO17→SIM868 RXD, SIM868 PWRKEY 16 (HIGH 1.5 s), button 7, LED 15, VBAT/2 on GPIO1.</div>')

# ---- pinout reference page
o.append('<div class="page"></div><h2><span class="num">REF</span>Every pin hole on the main board</h2><p class="intro">Use this to check a hole before soldering. Pins are listed per module, left to right on the component side.</p>')
by = {}
for h, (part, lab) in PINS.items(): by.setdefault(part, []).append((parse(h)[1], parse(h)[0], h, lab))
cells = []
for part in ['ESP32-S3', 'Click', 'PCM5102A', 'H2', 'PAM8403', 'H1']:
    lst = sorted(by[part])
    cells.append(f'<div class="box"><h3>{part}</h3><table class="holes">' + ''.join(f'<tr><td style="width:44px"><span class="h">{h}</span></td><td>{esc(l)}</td></tr>' for _, _, h, l in lst) + '</table></div>')
cells.append('<div class="box"><h3>Parts on the main board</h3><table class="holes">' + ''.join(f'<tr><td style="width:44px"><b>{k}</b></td><td>{esc(c["val"])} · ' + ', '.join(f'<span class="h">{h}</span>{"" if l in "ab" else " " + esc(l)}' for h, l in c['legs'].items()) + f' · step {c["step"] + 1}</td></tr>' for k, c in COMPS.items()) + '</table></div>')
cells.append('<div class="box"><h3>Bare rails and buses</h3><table class="holes"><tr><td><span class="h">AA1–AA35</span></td><td>GND rail</td></tr><tr><td><span class="h">Y1–Y20</span></td><td>5 V rail</td></tr><tr><td><span class="h">D35–X35</span></td><td>VBAT rail (4.0 V from the step-down, SIM868 only)</td></tr><tr><td><span class="h">B2–W2</span></td><td>GND bus col 2</td></tr><tr><td><span class="h">F33–AA33</span></td><td>GND bus col 33</td></tr></table>'
             '<h3 style="margin-top:8px">Off-board wires land in</h3><table class="holes"><tr><td><span class="h">X35</span></td><td>4.0 V from the step-down OUT+</td></tr><tr><td><span class="h">AA35</span></td><td>GND from the step-down OUT−</td></tr><tr><td><span class="h">Y1</span></td><td>switched 5 V from rocker pin 2 (USB red → rocker pin 1)</td></tr><tr><td><span class="h">AA1</span></td><td>GND from the power bank (USB black)</td></tr><tr><td><span class="h">Y13</span></td><td>5 V to the step-down IN+</td></tr><tr><td><span class="h">AA14</span></td><td>GND to the step-down IN−</td></tr><tr><td><span class="h">AA18 AA19</span></td><td>GND wires up to the Click screw terminals</td></tr><tr><td><span class="h">L35</span></td><td>VBAT to the SIM868 battery plug (red)</td></tr><tr><td><span class="h">L33</span></td><td>GND to the SIM868 battery plug (black)</td></tr></table></div>')
o.append('<div class="grid2">' + ''.join(cells) + '</div>')

# ---- steps
for st in range(2, 14):
    title, tools, intro, holes = STEPS[st]
    o.append(f'<div class="page"></div><h2><span class="num">STEP {st}</span>{esc(title)}</h2>')
    o.append('<div class="tools">' + ''.join(f'<span class="{t}">{TOOLS[t]}</span>' for t in tools) + '</div>')
    o.append(f'<p class="intro">{esc(intro)}</p>')
    if holes: o.append(('<h3>SIM868 board: what goes where</h3>' if st == 8 else '<h3>Holes</h3>') + holes_table(holes))
    if st == 12: o.append('<h3>Parts into holes (component side)</h3>' + holes_table(LIDPARTS))
    t = ops_table(st)
    if t: o.append('<h3>Do these in order</h3>' + t)
    if st == 3: o.append('<div class="map">' + svg_board(None, solder=False, comp_view=True) + '</div>')
    elif st in (4, 5, 7, 9):
        o.append('<div class="map">' + svg_board(st - 1, solder=True) + '</div>')
    elif st == 8:
        o.append('<div class="map">' + svg_board(st - 1, solder=True) + '</div>')
        o.append('<div class="map">' + svg_board(st - 1, solder=False, comp_view=True, highlight=['L35', 'L33', 'J29', 'J30', 'J31', 'J32', 'J33']) + '</div>')
    elif st == 6: o.append('<div class="map">' + svg_board(st - 1, solder=False, comp_view=True, highlight=['AA18', 'AA19']) + '</div>')
    elif st in (10, 11): o.append('<div class="map">' + svg_board(st - 1, solder=False, comp_view=True, highlight=['X35', 'W35', 'AA35', 'AA34', 'Y1', 'AA1'] if st == 11 else ['X35', 'AA35']) + '</div>')
    elif st == 12: o.append('<div class="map" style="text-align:center">' + svg_lid(True) + '</div>')
    elif st == 13: o.append('<div class="map">' + svg_board(None, solder=False, comp_view=True, highlight=['Z19', 'Z20', 'Z21', 'Z22', 'Z23', 'Z24']) + '</div>')

# ---- check sheet
o.append('<div class="page"></div><h2><span class="num">STEP 14</span>Check sheet</h2><p class="intro">Power bank unplugged, all modules unplugged. Beep each pair with the meter. Tick when done.</p>')
o.append('<h3>Must NOT beep (shorts)</h3><table class="chk">' + ''.join(f'<tr><td><span class="cb"></span></td><td><span class="h">{a}</span> ↔ <span class="h">{b}</span></td><td>{esc(t)}</td></tr>' for a, b, t in [('AA1', 'Y1', 'GND ↔ 5 V'), ('AA1', 'X35', 'GND ↔ VBAT'), ('AA1', 'K23', 'GND ↔ 3V3'), ('Y1', 'X35', '5 V ↔ VBAT'), ('Y1', 'L35', '5 V ↔ SIM868 VBAT lead (would destroy the SIM868)'), ('Y1', 'J29', '5 V ↔ H2 3V3'), ('L35', 'J29', 'VBAT ↔ H2 3V3'), ('Y28', 'AA1', 'PAM L+ ↔ GND'), ('Y29', 'AA1', 'PAM L− ↔ GND')]) + '</table>')
o.append('<h3>Must beep (every link, end to end)</h3><table class="chk">')
for w in WIRES:
    if w['kind'] in ('link', 'lid', 'bridge'):
        o.append(f'<tr><td><span class="cb"></span></td><td style="width:120px"><span class="h">{w["a"]}</span> ↔ <span class="h">{w["b"]}</span>{" (lid)" if w["side"] == "lid" else ""}</td><td>{esc(w.get("note") or "")}</td><td class="sub">step {w["step"] + 1}</td></tr>')
o.append('</table>')
o.append('<h3>Then, modules plugged in, power bank on, rocker ON</h3><table class="chk">' + ''.join(f'<tr><td><span class="cb"></span></td><td>{t}</td></tr>' for t in ['5.0 V between Z19 and Z20 (H1 5V–GND)', '3.3 V between W3 and W2 (Click 3V3–GND)', '3.3 V between J29 and J33 (H2 3V3–GND)', '4.0 V between L35 and L33 (SIM868 battery lead) and the same on the PH2.0 plug, red = +', 'SIM868: PWRKEY pulse → NET LED blinks fast, then about every 3 s (registered); AT → AT+CPIN? → AT+CREG? (0,1) → test call', 'Rocker OFF before plugging USB-C into the ESP32-S3 to flash']) + '</table>')

# ---- cut list
o.append('<div class="page"></div><h2><span class="num">CUT</span>Cut list (every wire cut to length)</h2><table class="ops"><thead><tr><th>Step</th><th>Type</th><th>From</th><th>To</th><th>Length</th><th>Instruction</th></tr></thead><tbody>')
for w in sorted(WIRES, key=lambda w: (w['step'], ORDER[w['kind']], w['id'])):
    m = re.search(r'(\d+) mm', w['cut'])
    if not m or w['kind'] == 'bridge': continue
    col = '#a9aeb2' if w['kind'] == 'bus' else NC[w['net']]
    o.append(f'<tr><td class="n">{w["step"] + 1}</td><td class="k"><span class="sw" style="background:{col}"></span>{KINDNAME[w["kind"]]}</td><td>{end_cell(w, "a")}</td><td>{end_cell(w, "b")}</td><td><b>{m.group(1)} mm</b></td><td class="cut">{esc(w["cut"])}</td></tr>')
o.append('</tbody></table>')
tot_link = sum(int(re.search(r'(\d+) mm', w['cut']).group(1)) for w in WIRES if w['kind'] in ('link', 'lid'))
tot_bare = sum(int(re.search(r'(\d+) mm', w['cut']).group(1)) for w in WIRES if w['kind'] == 'bus')
o.append(f'<p class="sub">Totals: insulated cores ≈ {tot_link} mm (≈ {round(tot_link / 6 / 10) * 10 + 50} mm of the 6-core cable), bare 20 AWG ≈ {tot_bare} mm. Module outlines on the maps are approximate; hole positions are exact.</p>')
o.append('</body></html>')
open(OUT, 'w', encoding='utf-8').write(''.join(o))
print('pdf html written')
