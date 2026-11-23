"""Rezon OTIO case v1: round PLA case, bayonet twist-lock lid, no screws.

Run inside FreeCAD (Macro > Execute, or through the MCP Bridge). Rebuilds the document
"Rezon_case_v1" from the parameters below, runs the fit checks and exports STLs to out/.
Units: mm. Origin: centre of the case, z = 0 is the floor underside. The board's long axis is X.
Notes: 30 Hardware/Builds/OTIO case v1.md.
"""
import math
import os

import FreeCAD as App
import Part
from FreeCAD import Vector as V

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:   # some runners don't set __file__
    HERE = os.path.join(os.path.expanduser('~'), 'Desktop', 'EP_RezonatingProject', 'Rezonating', 'hardware', 'case-v1')
DOC = 'Rezon_case_v1'

# ---------------------------------------------------------------- parameters
# Values marked (E) are estimates: measure and change them.
P = dict(
    # perfboard (Kaszti, 2026-11-23: 150 x 90, corner holes)
    BOARD_L=150.0, BOARD_W=90.0, BOARD_T=1.6,
    HOLE_D=3.0,            # (E) corner hole diameter
    HOLE_IN=3.3,           # (E) corner hole centre from each edge (photo: about 3.0-3.3)
    PIN_CLEAR=0.5,         # corner pin is this much thinner than the hole (takes up hole-position error)
    GRID_ROWS=54, GRID_COLS=33,   # hole grid (photo 2026-11-23), centred on the board
    BOARD_LIFT=5.0,        # board underside above the floor top (room for solder-side wiring)
    # case
    FLOOR=3.0,             # floor thickness, flat bottom
    R_IN=88.3,             # inner wall radius (board corner sits at 87.5)
    R_OUT=93.2,            # outer radius of base and lid (flush)
    NECK_H=10.0,           # height of the neck the lid skirt covers
    R_NECK=91.0,           # outer radius of the neck
    INNER_H=45.0,          # free height above the floor top (geophone + resistor = 43)
    LID_T=3.0,             # lid plate (1.8 mm left under the 1.2 mm logo pocket)
    FIT=0.3,               # radial gap, lid skirt to neck
    CHAMFER=0.8,           # outer bottom edge of the base, top edge of the lid
    # bayonet (3 lugs, clockwise quarter-ish turn to close)
    LUGS=3, TURN=30.0,     # degrees of turn
    LUG_W=10.0, LUG_H=3.0, LUG_DEPTH=1.2,   # lug size (arc length, height, radial)
    GROOVE_D=1.5,          # groove depth into the neck (lug depth + 0.3)
    GROOVE_W_EXTRA=1.2,    # entry slot wider than the lug (arc mm)
    GROOVE_Z_GAP=0.2,      # vertical play lug-to-groove
    LUG_Z=1.6,             # lug underside above the skirt's bottom edge
    DETENT=0.8,            # click bump height above the groove bottom (lug face is 0.6 above it -> 0.2 interference)
    # geophones (two SM-24, Ø25.4 x 32, resistor on top -> 43 tall)
    GEO_D=25.4, GEO_H=32.0, GEO_TOP=43.0,
    CUP_WALL=2.0, CUP_H=12.0, CUP_CLEAR=0.3, RIB_INTERF=0.15,
    GEO_GAP=1.5,           # cup wall to board long edge
    # ESP32-S3-DevKitC-1 and ADC 15 Click positions follow wiring/gen.py: ESP J3 col 7, J1 col 16,
    # pin 22 in row A; Click headers cols 19 and 28, GND pins in row A
    HDR_H=8.5,             # (E) female header height: ESP PCB underside above board top
    ESP_L=62.74, ESP_W=25.4, ESP_T=1.6,
    ESP_END=4.8,           # (E) USB-end edge to the pin-22 centre
    USB_SPACING=10.0,      # (E) centre-to-centre of the two USB-C ports (UART port on the J1 side, +y)
    CLICK_L=42.9, CLICK_END=3.9,   # Click length; GND-end edge to the GND pin centre
    SLOT_W=27.0, SLOT_H=8.6, SLOT_R=2.0,   # tunnel: room for a plug in either port
    TUNNEL_WALL=2.5,
    # hold-down post on the lid axis (rotation-invariant, lands on the board centre)
    POST_OD=10.0, POST_ID=6.0, POST_GAP=0.4,
    # lid engraving
    FONT='C:/Windows/Fonts/segoeuib.ttf', TEXT='REZON', TEXT_H=26.0, TEXT_Y=14.0, TRACK=4.0,
    ENGRAVE=1.2,           # logo pocket depth in the lid = inlay thickness (boss: minimum 0.6)
    INLAY_GAP=0.1,         # inlay pieces are this much smaller per side than the pocket (press fit / drop of glue)
    WAVE_L=130.0, WAVE_A=11.0, WAVE_PERIODS=5.0, WAVE_W=3.0, WAVE_Y=-20.0,
)
for k, v in P.items():
    globals()[k] = v

FLOOR_TOP = FLOOR
BOARD_Z0 = FLOOR_TOP + BOARD_LIFT
BOARD_TOP = BOARD_Z0 + BOARD_T
H_BASE = FLOOR_TOP + INNER_H            # neck top = lid plate underside
NECK_Z0 = H_BASE - NECK_H
TOP = H_BASE + LID_T
ESP_Z0 = BOARD_TOP + HDR_H
USB_Z = ESP_Z0 + ESP_T + 1.63           # USB-C receptacle centre (3.26 tall, on the PCB top)
GX0 = -(GRID_ROWS - 1) * 2.54 / 2           # row A (x)
GY0 = -(GRID_COLS - 1) * 2.54 / 2           # column 1 (y)
def col_y(c): return GY0 + (c - 1) * 2.54
ESP_Y = (col_y(7) + col_y(16)) / 2
ESP_X0 = GX0 - ESP_END                      # USB-end edge of the ESP32-S3
CLICK_X0 = GX0 - CLICK_END
CLICK_Y = (col_y(19) + col_y(28)) / 2
USB_Y = ESP_Y
R_SKIRT_IN = R_NECK + FIT
RG = R_NECK - GROOVE_D                  # groove bottom radius
LUG_RIN = R_SKIRT_IN - LUG_DEPTH        # lug inner face radius (0.3 from groove bottom)
LZ0 = NECK_Z0 + 0.2 + LUG_Z             # lug underside (skirt ends 0.2 above the step)
LZ1 = LZ0 + LUG_H
BR_Z0 = LZ0 - GROOVE_Z_GAP
BR_Z1 = LZ1 + GROOVE_Z_GAP
GEO_Y = BOARD_W / 2 + GEO_GAP + GEO_D / 2 + CUP_CLEAR + CUP_WALL
HX, HY = BOARD_L / 2 - HOLE_IN, BOARD_W / 2 - HOLE_IN
Z = V(0, 0, 1)
O = V(0, 0, 0)


def revolve(pts, deg=360.0, start=0.0):
    """Revolve an (r, z) polygon about Z by deg, starting at angle start (degrees)."""
    w = Part.makePolygon([V(r, 0, z) for r, z in pts] + [V(pts[0][0], 0, pts[0][1])])
    s = Part.Face(w).revolve(O, Z, deg)
    if start:
        s.rotate(O, Z, start)
    return s


def cyl(r, h, x=0, y=0, z=0):
    return Part.makeCylinder(r, h, V(x, y, z))


def box(x0, x1, y0, y1, z0, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def deg(arc_mm, r):
    return math.degrees(arc_mm / r)


# ---------------------------------------------------------------- base
def make_base():
    c = CHAMFER
    prof = [(0, 0), (R_OUT - c, 0), (R_OUT, c), (R_OUT, NECK_Z0), (R_NECK, NECK_Z0 + 0.0),
            (R_NECK, H_BASE - 0.4), (R_NECK - 0.4, H_BASE), (R_IN, H_BASE), (R_IN, FLOOR_TOP), (0, FLOOR_TOP)]
    base = revolve(prof)

    # USB tunnel block (fills the gap between the wall and the board's short edge)
    x_in = -(BOARD_L / 2 + 1.0)
    blk = box(-R_OUT - 1, x_in, USB_Y - SLOT_W / 2 - TUNNEL_WALL, USB_Y + SLOT_W / 2 + TUNNEL_WALL,
              FLOOR_TOP - 0.01, USB_Z + SLOT_H / 2 + TUNNEL_WALL)
    blk = blk.common(cyl(R_OUT - 0.01, 200, z=-50))
    base = base.fuse(blk)

    # geophone cups with crush ribs
    for sy in (1, -1):
        y = sy * GEO_Y
        ri = GEO_D / 2 + CUP_CLEAR
        cup = cyl(ri + CUP_WALL, CUP_H, 0, y, FLOOR_TOP - 0.01).cut(cyl(ri, CUP_H + 1, 0, y, FLOOR_TOP))
        for k in range(6):
            a = math.radians(30 + 60 * k)
            rr = 0.6
            rc = GEO_D / 2 - RIB_INTERF + rr
            cup = cup.fuse(cyl(rr, CUP_H - 1.0, rc * math.cos(a), y + rc * math.sin(a), FLOOR_TOP - 0.01))
        base = base.fuse(cup)

    # corner pegs: standoff + locating pin through the board's corner holes
    for sx in (1, -1):
        for sy in (1, -1):
            x, y = sx * HX, sy * HY
            base = base.fuse(cyl(3.2, BOARD_LIFT + 0.01, x, y, FLOOR_TOP - 0.01))
            pin_d = HOLE_D - PIN_CLEAR
            base = base.fuse(cyl(pin_d / 2, BOARD_T + 1.0, x, y, BOARD_Z0))
            base = base.fuse(Part.makeCone(pin_d / 2, pin_d / 2 - 0.5, 0.8, V(x, y, BOARD_Z0 + BOARD_T + 1.0)))

    # USB slot: rounded rectangle along X, through block and wall
    r, hw, hh = SLOT_R, SLOT_W / 2, SLOT_H / 2
    xa, xb = -R_OUT - 2, x_in + 1
    slot = box(xa, xb, USB_Y - hw, USB_Y + hw, USB_Z - hh + r, USB_Z + hh - r)
    slot = slot.fuse(box(xa, xb, USB_Y - hw + r, USB_Y + hw - r, USB_Z - hh, USB_Z + hh))
    for sy in (-1, 1):
        for sz in (-1, 1):
            slot = slot.fuse(Part.makeCylinder(r, xb - xa, V(xa, USB_Y + sy * (hw - r), USB_Z + sz * (hh - r)), V(1, 0, 0)))
    base = base.cut(slot)

    # bayonet grooves: entry slot + branch, roof chamfered 45 deg for printing
    aL, aE = deg(LUG_W, R_NECK), deg(LUG_W + GROOVE_W_EXTRA, R_NECK)
    ro = R_NECK + 1.0
    for k in range(LUGS):
        a0 = k * 360.0 / LUGS
        entry = revolve([(RG, BR_Z0), (ro, BR_Z0), (ro, H_BASE + 1), (RG, H_BASE + 1)], aE, a0 - aE / 2)
        branch = revolve([(RG, BR_Z0), (ro, BR_Z0), (ro, BR_Z1 + (ro - RG)), (RG, BR_Z1)],
                         TURN + aE, a0 - TURN - aE / 2)
        base = base.cut(entry).cut(branch)
        # click bump on the groove bottom, just behind the lug's trailing edge when locked
        ab = math.radians(a0 - TURN + aL / 2 + deg(1.5 + 0.3, RG))
        rb = RG + DETENT - 1.5
        base = base.fuse(cyl(1.5, BR_Z1 - BR_Z0 - 0.6, rb * math.cos(ab), rb * math.sin(ab), BR_Z0 + 0.3)
                         .common(cyl(RG + DETENT, 50, z=0)))
    return base.removeSplitter()


# ---------------------------------------------------------------- lid (modelled in the locked position)
def text_faces():
    import Part as _P
    chars = _P.makeWireString(TEXT, FONT, TEXT_H, TRACK)
    faces = []
    for ch in chars:
        if ch:
            faces.append(Part.makeFace(ch, 'Part::FaceMakerBullseye'))
    comp = Part.makeCompound(faces)
    bb = comp.BoundBox
    comp.translate(V(-(bb.XMin + bb.XMax) / 2, TEXT_Y - (bb.YMin + bb.YMax) / 2, 0))
    return comp


def wave_face(h=None):
    """Wave stroke: a Gaussian-enveloped sine (a footstep burst), outline built point by point."""
    n, s = 600, WAVE_L / 2
    def f(x):
        return WAVE_A * math.exp(-(x / (0.42 * s)) ** 2) * math.sin(2 * math.pi * WAVE_PERIODS * x / WAVE_L)
    xs = [-s + WAVE_L * i / n for i in range(n + 1)]
    c = [(x, f(x)) for x in xs]
    h = WAVE_W / 2 if h is None else h
    left, right, tang = [], [], []
    for i, (x, y) in enumerate(c):
        a, b = c[max(i - 1, 0)], c[min(i + 1, n)]
        tx, ty = b[0] - a[0], b[1] - a[1]
        L = math.hypot(tx, ty); tx, ty = tx / L, ty / L; nx, ny = -ty, tx
        tang.append((tx, ty, nx, ny))
        left.append(V(x + nx * h, WAVE_Y + y + ny * h, 0))
        right.append(V(x - nx * h, WAVE_Y + y - ny * h, 0))

    def cap(i, sgn):   # semicircle round end, one closed outline (no fuse, so it stays one piece)
        (x, y), (tx, ty, nx, ny) = c[i], tang[i]
        out = []
        for k in range(1, 16):
            ph = math.pi * k / 16
            u, w = math.cos(ph), math.sin(ph)
            out.append(V(x + h * sgn * (u * nx + w * tx), WAVE_Y + y + h * sgn * (u * ny + w * ty), 0))
        return out
    pts = left + cap(n, 1) + right[::-1] + cap(0, -1) + [left[0]]
    return Part.Face(Part.makePolygon(pts))


def make_lid():
    c = CHAMFER + 0.2
    z_sk = NECK_Z0 + 0.2
    prof = [(0, H_BASE), (R_SKIRT_IN, H_BASE), (R_SKIRT_IN, z_sk), (R_OUT, z_sk),
            (R_OUT, TOP - c), (R_OUT - c, TOP), (0, TOP)]
    lid = revolve(prof)
    aL = deg(LUG_W, R_NECK)
    for k in range(LUGS):
        a0 = k * 360.0 / LUGS - TURN
        lug = revolve([(LUG_RIN, LZ0), (R_SKIRT_IN + 0.01, LZ0), (R_SKIRT_IN + 0.01, LZ1 + (R_SKIRT_IN - LUG_RIN)),
                       (LUG_RIN, LZ1)], aL, a0 - aL / 2)
        lid = lid.fuse(lug)
    # hold-down post on the axis
    post_z0 = BOARD_TOP + POST_GAP
    lid = lid.fuse(cyl(POST_OD / 2, H_BASE - post_z0 + 0.01, z=post_z0).cut(cyl(POST_ID / 2, H_BASE, z=post_z0 - 1)))
    # logo pocket for the white inlay
    for m in logo_faces():
        m = m.copy()
        m.translate(V(0, 0, TOP - ENGRAVE))
        lid = lid.cut(m.extrude(V(0, 0, ENGRAVE + 1)))
    return lid.removeSplitter()


def logo_faces():
    """REZON letters and the wave as flat faces at z = 0 (one face per letter, holes included)."""
    faces = list(text_faces().Faces)
    faces.append(wave_face())
    return faces


def make_inlays():
    """White inlay pieces in place in the lid: the pocket shapes shrunk by INLAY_GAP, flush with the top."""
    flat = []
    for f in text_faces().Faces:
        # offset outline and holes separately (offsetting the whole face crashes on the R)
        outer = f.OuterWire.makeOffset2D(-INLAY_GAP, 0)
        holes = [w.makeOffset2D(INLAY_GAP, 0) for w in f.Wires if not w.isSame(f.OuterWire)]
        flat.append(Part.makeFace([outer] + holes, 'Part::FaceMakerBullseye'))
    flat.append(wave_face(WAVE_W / 2 - INLAY_GAP))
    pieces = []
    for g in flat:
        pc = g.extrude(V(0, 0, ENGRAVE))
        pc.translate(V(0, 0, TOP - ENGRAVE))
        pieces.append(pc)
    return Part.makeCompound(pieces)


# ---------------------------------------------------------------- dummies (fit check only, not printed)
def make_dummies():
    d = {}
    board = box(-BOARD_L / 2, BOARD_L / 2, -BOARD_W / 2, BOARD_W / 2, BOARD_Z0, BOARD_TOP)
    for sx in (1, -1):
        for sy in (1, -1):
            board = board.cut(cyl(HOLE_D / 2, 5, sx * HX, sy * HY, BOARD_Z0 - 1))
    d['Perfboard'] = board
    x0 = ESP_X0
    esp = box(x0, x0 + ESP_L, ESP_Y - ESP_W / 2, ESP_Y + ESP_W / 2, ESP_Z0, ESP_Z0 + ESP_T)
    esp = esp.fuse(box(x0 + ESP_L - 25.5, x0 + ESP_L, ESP_Y - 9, ESP_Y + 9, ESP_Z0 + ESP_T, ESP_Z0 + ESP_T + 3.1))
    for sy in (1, -1):   # USB-C receptacles
        esp = esp.fuse(box(x0, x0 + 7.35, ESP_Y + sy * USB_SPACING / 2 - 4.47, ESP_Y + sy * USB_SPACING / 2 + 4.47,
                           ESP_Z0 + ESP_T, ESP_Z0 + ESP_T + 3.26))
    for c in (7, 16):    # female headers, rows A..V
        esp = esp.fuse(box(GX0 - 1.27, GX0 + 21 * 2.54 + 1.27, col_y(c) - 1.27, col_y(c) + 1.27, BOARD_TOP, ESP_Z0))
    d['ESP32-S3 DevKitC-1'] = esp
    cx0, cx1 = CLICK_X0, CLICK_X0 + CLICK_L
    click = box(cx0, cx1, CLICK_Y - 12.7, CLICK_Y + 12.7, ESP_Z0, ESP_Z0 + 1.6)
    for yc in (CLICK_Y - 4.7, CLICK_Y + 6.3):   # two 2-pole screw terminals at the far end
        click = click.fuse(box(cx1 - 7.5, cx1 - 0.5, yc - 4.5, yc + 4.5, ESP_Z0 + 1.6, ESP_Z0 + 1.6 + 10))
    for c in (19, 28):   # female headers, rows A..H
        click = click.fuse(box(GX0 - 1.27, GX0 + 7 * 2.54 + 1.27, col_y(c) - 1.27, col_y(c) + 1.27, BOARD_TOP, ESP_Z0))
    d['ADC 15 Click'] = click
    for i, sy in enumerate((1, -1), 1):
        g = cyl(GEO_D / 2, GEO_H, 0, sy * GEO_Y, FLOOR_TOP)
        g = g.fuse(box(-6, 6, sy * GEO_Y - 3, sy * GEO_Y + 3, FLOOR_TOP + GEO_H, FLOOR_TOP + GEO_TOP))
        d[f'SM-24 geophone {i}'] = g
    # USB-C plug in one port: metal 8.3 x 2.5 x 6.6 into the receptacle, overmold 12.4 x 6.6 x 22
    py = ESP_Y + USB_SPACING / 2
    plug = box(x0 - 0.5, x0 + 6.1, py - 4.15, py + 4.15, USB_Z - 1.25, USB_Z + 1.25)
    plug = plug.fuse(box(x0 - 22.5, x0 - 0.5, py - 6.2, py + 6.2, USB_Z - 3.3, USB_Z + 3.3))
    d['USB-C plug'] = plug
    return d


# ---------------------------------------------------------------- build
def build():
    if DOC in App.listDocuments():
        App.closeDocument(DOC)
    doc = App.newDocument(DOC)
    base, lid, dummies = make_base(), make_lid(), make_dummies()
    inlay = make_inlays()
    ob = doc.addObject('Part::Feature', 'Base'); ob.Shape = base
    ol = doc.addObject('Part::Feature', 'Lid'); ol.Shape = lid
    oi = doc.addObject('Part::Feature', 'Lid_inlay'); oi.Shape = inlay
    grp = doc.addObject('App::DocumentObjectGroup', 'Fit_dummies')
    dobs = {}
    for name, s in dummies.items():
        o = doc.addObject('Part::Feature', name.replace(' ', '_').replace('-', '_'))
        o.Label = name; o.Shape = s; grp.addObject(o); dobs[name] = o
    doc.recompute()

    # ---- fit checks
    rep = []
    def vol(a, b):
        try:
            return a.common(b).Volume
        except Exception:
            return -1
    for name, s in dummies.items():
        for pn, ps in (('Base', base), ('Lid', lid)):
            v = vol(ps, s)
            if name == 'USB-C plug' and pn == 'Base':
                rep.append(f'{"OK  " if v < 0.5 else "HIT "} {name} vs {pn}: {v:.2f} mm3 (plug must pass the tunnel)')
            elif name.startswith('SM-24') and pn == 'Base' and v < 8:
                rep.append(f'OK   {name} vs {pn}: {v:.2f} mm3 (crush ribs, press fit on purpose)')
            elif v > 0.01:
                rep.append(f'HIT  {name} vs {pn}: {v:.2f} mm3')
    names = list(dummies)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            v = vol(dummies[names[i]], dummies[names[j]])
            if v > 0.01 and 'plug' not in names[i] + names[j]:
                rep.append(f'HIT  {names[i]} vs {names[j]}: {v:.2f} mm3')
    rep.append(f'Lid vs Base (locked): {vol(lid, base):.3f} mm3 overlap (0 expected)')
    rep.append(f'Board corner radius {math.hypot(BOARD_L / 2, BOARD_W / 2):.2f} vs inner wall {R_IN} '
               f'-> {R_IN - math.hypot(BOARD_L / 2, BOARD_W / 2):.2f} mm clearance')
    rep.append(f'Geophone cups at y = +-{GEO_Y:.2f}, outer edge r = {GEO_Y + GEO_D / 2 + CUP_CLEAR + CUP_WALL:.2f}')
    rep.append(f'Geophone top z = {FLOOR_TOP + GEO_TOP:.1f}, lid underside z = {H_BASE:.1f}')
    rep.append(f'USB-C centre z = {USB_Z:.2f} (floor underside = 0)')
    rep.append(f'Outside: diameter {2 * R_OUT:.1f}, height {TOP:.1f}')
    rep.append(f'Base {base.Volume / 1000:.1f} cm3, valid {base.isValid()}, solids {len(base.Solids)}; '
               f'Lid {lid.Volume / 1000:.1f} cm3, valid {lid.isValid()}, solids {len(lid.Solids)}')
    rep.append(f'PLA mass about {(base.Volume + lid.Volume) / 1000 * 1.24 * 0.55:.0f} g (55 % solid guess)')

    # ---- looks
    try:
        import FreeCADGui as Gui
        ob.ViewObject.ShapeColor = (0.93, 0.93, 0.91)
        ol.ViewObject.ShapeColor = (0.12, 0.12, 0.13)
        ol.ViewObject.Transparency = 0
        oi.ViewObject.ShapeColor = (0.97, 0.97, 0.96)
        colors = {'Perfboard': (0.1, 0.45, 0.25), 'ESP32-S3 DevKitC-1': (0.15, 0.15, 0.18),
                  'ADC 15 Click': (0.6, 0.1, 0.1), 'USB-C plug': (0.3, 0.3, 0.3)}
        for n, o in dobs.items():
            o.ViewObject.ShapeColor = colors.get(n, (0.75, 0.6, 0.2))
        Gui.activeDocument().activeView().viewIsometric()
        Gui.SendMsgToActiveView('ViewFit')
    except Exception:
        pass

    # ---- export
    out = os.path.join(HERE, 'out')
    os.makedirs(out, exist_ok=True)
    import MeshPart
    # inlay checks: no overlap with the lid, flush with the top
    rep.append(f'Inlay: {len(inlay.Solids)} pieces, {inlay.Volume / 1000:.2f} cm3, overlap with lid {lid.common(inlay).Volume:.3f} mm3 (0 expected), '
               f'top z {inlay.BoundBox.ZMax:.2f} vs lid top {TOP:.2f}, pocket {ENGRAVE} mm deep, gap {INLAY_GAP} mm per side')
    # print orientation: visible face down on the plate (rotate 180 deg about X, sit on z = 0)
    inlay_print = inlay.copy(); inlay_print.rotate(V(0, 0, 0), V(1, 0, 0), 180)
    inlay_print.translate(V(0, 0, -inlay_print.BoundBox.ZMin))
    # logo fit-test coupon: only the lid plate around the logo, face down; print black + the inlay in white
    coupon = lid.common(box(-72, 72, WAVE_Y - WAVE_A - 6, TEXT_Y + TEXT_H / 2 + 6, H_BASE, TOP + 1))
    coupon.rotate(V(0, 0, 0), V(1, 0, 0), 180); coupon.translate(V(0, 0, -coupon.BoundBox.ZMin))
    rep.append(f'fit_test_logo_coupon: {coupon.Volume / 1000:.1f} cm3, solids {len(coupon.Solids)}')
    for name, s in (('rezon_case_v1_base', base), ('rezon_case_v1_lid', lid), ('rezon_case_v1_lid_inlay_white', inlay_print),
                    ('fit_test_logo_coupon', coupon)):
        m = MeshPart.meshFromShape(Shape=s, LinearDeflection=0.02, AngularDeflection=0.08, Relative=False)
        m.write(os.path.join(out, name + '.stl'))
    # fit-test rings: only the bayonet (neck + a thin lid ring), about an hour of printing
    ring = cyl(R_OUT + 1, 100, z=-10).cut(cyl(R_IN - 6, 120, z=-20))
    t_base = base.common(ring.common(box(-200, 200, -200, 200, NECK_Z0 - 3, H_BASE + 1)))
    t_base = t_base.fuse(cyl(R_OUT, 1.2, z=NECK_Z0 - 3).cut(cyl(R_IN - 0.01, 3, z=NECK_Z0 - 4)))   # flat ring to print on
    t_lid = lid.common(ring.common(box(-200, 200, -200, 200, NECK_Z0 - 1, H_BASE + 1.2)))   # plate thinned to 1.2 mm
    for name, s in (('fit_test_neck', t_base), ('fit_test_lid_ring', t_lid)):
        m = MeshPart.meshFromShape(Shape=s.removeSplitter(), LinearDeflection=0.02, AngularDeflection=0.08, Relative=False)
        m.write(os.path.join(out, name + '.stl'))
        rep.append(f'{name}: {s.Volume / 1000:.1f} cm3, solids {len(s.Solids)}')
    doc.saveAs(os.path.join(HERE, 'case_v1.FCStd'))
    print('\n'.join(rep))


build()
