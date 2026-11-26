"""Builds the geophone lock in FreeCAD (Macro > Execute). Sizes and sums: geo_lock.py; case: case_v1.py.

Makes its own document "Rezon_geo_lock" and saves geo_lock.FCStd; the case_v1 document and file are not touched.
Writes out/geo_lock_report.txt (self-checks), STLs to out/ and pictures to renders/. Units: mm, origin as in case_v1.py.
"""
import math
import os
import time
import traceback

import FreeCAD as App
import MeshPart
import Part
from FreeCAD import Vector as V

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:   # some runners don't set __file__
    HERE = os.path.join(os.path.expanduser('~'), 'Desktop', 'EP_RezonatingProject', 'Rezonating', 'hardware', 'case-v1')
OUT, REN = os.path.join(HERE, 'out'), os.path.join(HERE, 'renders')
DOC = 'Rezon_geo_lock'
Z, O = V(0, 0, 1), V(0, 0, 0)


def load(name, cut=''):
    """Run a script of this folder as a module, without its last line `cut`."""
    src = open(os.path.join(HERE, name), encoding='utf-8').read().rstrip()
    if cut:
        assert src.endswith('\n' + cut), f'{name} no longer ends with {cut}'
        src = src[:-len(cut)]
    ns = {'__file__': os.path.join(HERE, name), '__name__': 'loaded'}
    exec(compile(src, name, 'exec'), ns)
    return ns


C = load('case_v1.py', 'build()')      # its build() would close and rebuild the open case document
L = load('geo_lock.py')
G = L['G']
RM, APEX, SLOT_W, PIN_SEAT = L['RM'], L['APEX'], L['SLOT_W'], L['PIN_SEAT']
RAMP1, RAMP2, cam_z, pin_bottom = L['RAMP1'], L['RAMP2'], L['cam_z'], L['pin_bottom']
GY, FT = C['GEO_Y'], C['FLOOR_TOP']

FOOT_Z = 10.0                          # top of the cage's foot arcs
TWIST = 12.0                           # degrees of turn that lock the cage to the base
NUBS = (5.0, 58.0, 122.0, 175.0)       # twist-lock nubs on the base (degrees, board side is 270)
RN = 18.0                              # bottom radius of the notches for them
SA = math.degrees((SLOT_W / 2) / G['CAGE_RO'])
LA = 90 + G['A_DEPLOY']                # lever direction when deployed
PIN0 = G['PIN_Z'] - G['PIN_D'] / 2     # underside of the pins when deployed
SEAT = next(i / 10 for i in range(900) if pin_bottom(i / 10) >= PIN_SEAT - G['PIN_D'] / 2)


# ---------------------------------------------------------------- helpers
def prof(pts, a0, a1):
    w = Part.makePolygon([V(r, 0, z) for r, z in pts + pts[:1]])
    s = Part.Face(w).revolve(O, Z, min(a1 - a0, 360.0))
    if s.ShapeType != 'Solid':
        s = Part.Solid(s)
    s.rotate(O, Z, a0)
    return s


def sector(r0, r1, z0, z1, a0, a1):
    return prof([(r0, z0), (r1, z0), (r1, z1), (r0, z1)], a0, a1)


def tube(r0, r1, z0, z1):
    return Part.makeCylinder(r1, z1 - z0, V(0, 0, z0)).cut(Part.makeCylinder(r0, z1 - z0 + 2, V(0, 0, z0 - 1)))


def radial_prism(tz, r0, r1, ang):
    """Polygon in (tangential, z), extruded from r0 to r1 in the direction ang."""
    f = Part.Face(Part.makePolygon([V(r0, t, z) for t, z in tz + tz[:1]]))
    s = f.extrude(V(r1 - r0, 0, 0))
    s.rotate(O, Z, ang)
    return s


def radial_box(r0, r1, w, z0, z1, ang):
    return radial_prism([(-w / 2, z0), (w / 2, z0), (w / 2, z1), (-w / 2, z1)], r0, r1, ang)


def fuse(shapes):
    s = shapes[0]
    for x in shapes[1:]:
        s = s.fuse(x)
    return s.removeSplitter()


def put(s, m):
    """Module 1 sits at +y; module 2 is module 1 turned by 180 degrees."""
    s = s.copy()
    if m == 2:
        s.rotate(O, Z, 180)
    s.translate(V(0, GY if m == 1 else -GY, 0))
    return s


def turn(s, m, deg):
    s = s.copy()
    s.rotate(V(0, GY if m == 1 else -GY, 0), Z, deg)
    return s


def up(s, z):
    s = s.copy()
    s.translate(V(0, 0, z))
    return s


def vol(a, b):
    return a.common(b).Volume


# ---------------------------------------------------------------- parts (module at the origin, deployed)
def make_collar(ri):
    ro = ri + G['COL_T']
    zg = G['COL_Z0'] + 0.5
    s = tube(ri, ro, G['COL_Z0'], G['COL_Z1']).cut(tube(ro - G['ZIP_D'], ro + 5, zg, zg + G['ZIP_W']))
    for a in G['PIN_A']:
        c = Part.makeCylinder(G['PIN_D'] / 2, G['PIN_R'] - ri - 0.2, V(ri + 0.2, 0, G['PIN_Z']), V(1, 0, 0))
        c = c.cut(Part.makeCylinder(ri, 50))
        c.rotate(O, Z, a)
        s = s.fuse(c)
    return s.cut(radial_box(ri - 2, ro + 2, G['COL_SLIT'], G['COL_Z0'] - 1, G['COL_Z1'] + 1, 270.0)).removeSplitter()


def make_cage():
    ri, ro, h = G['CAGE_RI'], G['CAGE_RO'], SLOT_W / 2
    cg = [tube(ri, ro, APEX - h - 0.5, G['CAGE_TOP'])]
    for a in G['PIN_A']:
        for sg in (1, -1):
            a0, a1 = sorted((a + sg * (SA - 3), a + sg * (SA + G['PILLAR'])))
            board_side = (a, sg) in ((210.0, 1), (330.0, -1))     # these two end above the board
            cg.append(sector(ri, ro, 11.4 if board_side else FT + 0.1, APEX - h, a0, a1))
    cg.append(sector(ri, ro, FT + 0.1, FOOT_Z, SA - 30, 90 - SA))
    cg.append(sector(ri, ro, FT + 0.1, FOOT_Z, 90 + SA, 210 - SA))
    cage = fuse(cg)
    for a in G['PIN_A']:     # slots, closed by the 90 degree V the pin seats in
        cage = cage.cut(radial_prism([(-h, -1), (h, -1), (h, APEX - h), (0, APEX), (-h, APEX - h)], 14, 24, a))
    for n in NUBS:           # twist lock: entry, run (its lower lip is 0.15 under the nub's 45 degree underside), click bump
        cage = cage.cut(sector(RN, 21, 0, 8.2, n - TWIST - 4.5, n - TWIST + 4.5))
        cage = cage.cut(prof([(RN, 6.4), (21, 3.4), (21, 8.2), (RN, 8.2)], n - TWIST, n + 4.5))
        cage = cage.fuse(sector(RN - 0.3, 18.4, 6.9, 8.1, n - 5.6, n - 4.2))
    return cage.removeSplitter()


def make_ring(lever, crank):
    s = tube(G['RING_RI'], G['RING_RO'], G['RING_Z0'], G['LOW_Z'])
    a0 = G['LOW_HALF']
    a1 = a0 + RAMP1 + RAMP2 + G['END']
    am = (a0 + a1) / 2
    ann = tube(G['RING_RI'], G['RING_RO'], G['LOW_Z'] - 2, 25)
    for a in G['PIN_A']:
        pts = [(RM * math.sin(math.radians(a0 - am)), G['LOW_Z'] - 1)]
        for i in range(41):
            x = a0 + (a1 - a0) * i / 40
            pts.append((RM * math.sin(math.radians(x - am)), cam_z(x) + (0.001 if i == 0 else 0)))
        pts.append((RM * math.sin(math.radians(a1 - am)), G['LOW_Z'] - 1))
        s = s.fuse(radial_prism(pts, 15, 26, a + am).common(ann))
    s = s.fuse(radial_box(22, 35, 8, G['RING_Z0'], 15, crank))
    pin = Part.makeCylinder(2.0, 4.4, V(G['CRANK_R'], 0, 14.9))
    # snap lip: the rod (hole 4.4 mm) presses over it, so it stays on when the case is upside down
    lip = Part.makeCone(2.0, 2.4, 0.4, V(G['CRANK_R'], 0, 18.4)).fuse(Part.makeCone(2.4, 1.8, 0.9, V(G['CRANK_R'], 0, 18.8)))
    pin = pin.fuse(lip)
    pin.rotate(O, Z, crank)
    s = s.fuse(pin)
    if lever:
        # 2026-11-26: the plug-in lever (peg in a socket) was too loose even glued, so the arm is now part of the ring.
        # No knob: a flat bar slides out through the wall slot when the ring goes in (see the fitting check).
        # It starts at the ring's underside so it prints flat on the plate; the slot is 11.7 to 16.3.
        s = s.fuse(radial_box(20.5, 26.6, 9, G['RING_Z0'], G['LOW_Z'], LA))
        s = s.fuse(radial_box(26.0, G['LEVER_R'], 8, G['RING_Z0'], 15.7, LA))
    return s.removeSplitter()


def crank_xy(rot):
    b = math.radians(G['A_DEPLOY'] - rot)
    return G['CRANK_R'] * math.cos(b), G['CRANK_R'] * math.sin(b)


def make_rod():
    px, py = crank_xy(0)
    rod = Part.makeBox(8, 2 * GY, 3, V(px - 4, py - GY, 15.2))
    for s in (1, -1):
        rod = rod.fuse(Part.makeCylinder(4, 3, V(px, py + s * GY, 15.2)))
    for s in (1, -1):
        rod = rod.cut(Part.makeCylinder(2.2, 5, V(px, py + s * GY, 14)))
    return rod.removeSplitter()


def make_base():
    """v1 base: cups out, holes, ring towers, twist-lock nubs, lever slot."""
    base = C['make_base']()
    for m in (1, 2):
        base = base.cut(put(Part.makeCylinder(G['HOLE_D'] / 2, 25, V(0, 0, -1)), m))
        base = base.cut(put(Part.makeCone(G['HOLE_D'] / 2 + 1.0, G['HOLE_D'] / 2, 1.0, V(0, 0, -0.2)), m))
        tw = [sector(G['RING_RI'], G['RING_RO'], FT - 0.5, G['RING_Z0'], a - 10, a + 10) for a in (90.0, 207.0, 333.0)]
        for n in NUBS:
            tw.append(sector(G['RING_RI'], 22.5, FT - 0.5, 9.5, n - 5, n + 5))
            tw.append(prof([(20.05, 4.55), (18.2, 6.4), (18.2, 8.0), (20.05, 8.0)], n - 3.5, n + 3.5))
        for t in tw:
            base = base.fuse(put(t, m))
    return base.cut(put(sector(25, 50, 11.7, 16.3, LA - G['ROT_MAX'] - 10, LA + 10), 1)).removeSplitter()


# ---------------------------------------------------------------- build and check
def run(rep):
    rep.append('# parts')
    col, cage, ring_a, ring_b = make_collar(G['D'] / 2), make_cage(), make_ring(True, G['A_DEPLOY']), make_ring(False, G['A_DEPLOY'] - 180)
    rod, base = make_rod(), make_base()
    geo = Part.makeCylinder(G['D'] / 2, G['H']).fuse(Part.makeBox(12, 6, G['CABLE_TOP'] - G['H'], V(-6, -3, G['H'])))
    parts = {'Base': base, 'Cage_1': put(cage, 1), 'Cage_2': put(cage, 2), 'Ring_1': put(ring_a, 1), 'Ring_2': put(ring_b, 2),
             'Collar_1': put(col, 1), 'Collar_2': put(col, 2), 'Rod': rod}
    geos = {1: put(geo, 1), 2: put(geo, 2)}
    dm = {n: s for n, s in C['make_dummies']().items() if not n.startswith('SM-24')}
    for n, s in parts.items():
        rep.append(f'{"OK  " if s.isValid() and len(s.Solids) == 1 else "HIT "} {n}: valid {s.isValid()}, solids {len(s.Solids)}, {s.Volume / 1000:.2f} cm3')

    if DOC in App.listDocuments():
        App.closeDocument(DOC)
    doc = App.newDocument(DOC)
    ob = {}
    for n, s in list(parts.items()) + [(f'SM24_{m}', g) for m, g in geos.items()] + \
            [(n.replace(' ', '_').replace('-', '_'), s) for n, s in dm.items()]:
        ob[n] = doc.addObject('Part::Feature', n)
        ob[n].Shape = s
    doc.recompute()

    rep.append('# checks')

    def line(ok, txt):
        rep.append(('OK   ' if ok else 'HIT  ') + txt)

    for m in (1, 2):
        a = Part.makeCompound([geos[m], parts[f'Collar_{m}']])
        for n in ('Base', f'Cage_{m}', f'Ring_{m}', 'Rod'):
            d = a.distToShape(parts[n])[0]
            line(d >= 1.45, f'deployed, geophone {m} to {n}: {d:.2f} mm')
    for n in ('Cage_1', 'Cage_2', 'Ring_1', 'Ring_2', 'Rod'):
        for o, s in list(dm.items()) + [('Base', base)]:
            if vol(parts[n], s) > 0.01:
                line(False, f'{n} vs {o}: {vol(parts[n], s):.2f} mm3')
    worst = 0
    for i in range(8):
        t = math.radians(45 * i)
        v = 0
        for s in (geo, col):
            b = s.copy()
            b.rotate(O, V(-math.sin(t), math.cos(t), 0), 1.0)
            b.translate(V(0.9 * math.cos(t), 0.9 * math.sin(t), 0))
            b = put(b, 1)
            v += vol(b, parts['Cage_1']) + vol(b, parts['Ring_1']) + vol(b, base)
        worst = max(worst, v)
    line(worst < 0.01, f'deployed, 1 deg tilted and 0.9 mm off centre, 8 directions: worst overlap {worst:.3f} mm3')
    for rot in (0, 8, 15, 22, 30, 36, 40, SEAT):
        z = max(0.0, pin_bottom(rot) - PIN0)
        c = up(parts['Collar_1'], z)
        v1, v2 = vol(c, turn(parts['Ring_1'], 1, -rot)), vol(c, parts['Cage_1'])
        line(v1 < 2 and v2 < 2, f'lever {rot:.1f} deg, geophone up {z:.2f}: pins vs cam {v1:.2f}, vs cage {v2:.2f} mm3')
    c = up(parts['Collar_1'], G['LIFT'])
    d = c.distToShape(parts['Cage_1'])[0]
    line(d < 0.1, f'travel: pins to V notches {d:.3f} mm (0 = seated)')
    line(up(geos[1], G['LIFT']).BoundBox.ZMin > 0, f"travel: geophone bottom {up(geos[1], G['LIFT']).BoundBox.ZMin:.2f} mm above the case underside")
    hang = up(parts['Collar_1'], -G['FREE'])
    d = hang.distToShape(parts['Ring_1'])[0]
    line(d < 0.1 and vol(hang, parts['Ring_1']) < 0.5, f'lifted while deployed: pins to cam {d:.3f} mm (0 = caught)')
    for rot in (0, 15, 30, SEAT, G['ROT_MAX']):
        x0, y0 = crank_xy(0)
        x1, y1 = crank_xy(rot)
        r = rod.copy()
        r.translate(V(x1 - x0, y1 - y0, 0))
        mv = {'Ring_1': turn(parts['Ring_1'], 1, -rot), 'Ring_2': turn(parts['Ring_2'], 2, -rot), 'Rod': r}
        z = max(0.0, min(G['LIFT'], pin_bottom(rot) - PIN0))
        fixed = list(dm.items()) + [(n, parts[n]) for n in ('Base', 'Cage_1', 'Cage_2')]
        pairs = [(n, s, o, t) for n, s in mv.items() for o, t in fixed]
        pairs += [(x, mv[x], y, mv[y]) for x, y in (('Rod', 'Ring_1'), ('Rod', 'Ring_2'))]
        pairs += [('Rod', r, f'Collar_{m}', up(parts[f'Collar_{m}'], z)) for m in (1, 2)]
        bad = [f'{n}/{o} {vol(s, t):.2f}' for n, s, o, t in pairs if vol(s, t) > 0.01]
        line(not bad, f'moving parts, lever {rot:.1f} deg: ' + (', '.join(bad) or 'free'))
    for m in (1, 2):
        v = vol(up(rod, 0.9), parts[f'Ring_{m}'])
        line(v > 0.3, f'rod lifted 0.9 mm: {v:.2f} mm3 into the snap lip of ring {m} (must be held)')
    # fit the one-piece ring with the board in and before the cage: lower it with the arm inside the wall,
    # 0.3 above its towers, then slide it out along the arm until the bar sticks out through the slot
    u = V(math.cos(math.radians(LA)), math.sin(math.radians(LA)), 0)
    bad, back = [], 21.0
    for d, z in [(back, z) for z in (25, 15, 8, 4, 1, 0.3)] + [(d, 0.3) for d in (18, 15, 12, 9, 6, 3, 0)] + [(0, 0)]:
        r = up(parts['Ring_1'], z)
        r.translate(u * -d)
        hits = [f'{o} {vol(r, s):.2f}' for o, s in [('Base', base)] + list(dm.items()) if vol(r, s) > 0.01]
        if hits:
            bad.append(f'back {d:.0f} up {z}: ' + ', '.join(hits))
    line(not bad, f'ring with lever fitting path (lower {back:.0f} mm in, slide out through the slot): ' + ('; '.join(bad) or 'free'))
    for m in (1, 2):      # fit the cage with the board already in: drop in turned by TWIST, then turn to lock
        bad, total, ends = [], 0.0, 0.0
        for z, t in ((15, 1), (8, 1), (4, 1), (2, 1), (0, 1), (0, .75), (0, .5), (0, .1), (0, 0)):
            c = up(turn(parts[f'Cage_{m}'], m, TWIST * t), z)
            v = vol(c, base) + sum(vol(c, s) for s in dm.values())
            if v > 0.01:
                bad.append(f'z{z} turn{TWIST * t:.0f}: {v:.2f}')
            total, ends = total + v, v
            if z and v > 0.01:
                total += 100
        line(total < 2 and ends < 0.01, f'cage {m} fitting path: ' + (', '.join(bad) or 'free') + ' (under 2 in all is the click bumps; 0 when locked)')
        v = vol(up(parts[f'Cage_{m}'], 0.6), base)
        line(v > 0.5, f'cage {m} pulled up 0.6 mm while locked: {v:.2f} mm3 in the nubs (must be held)')
    try:
        lid = C['make_lid']()
        bad = [f'{n} {vol(lid, s):.2f}' for n, s in parts.items() if vol(lid, s) > 0.01]
        bad += [f'geophone {m}' for m in (1, 2) if vol(up(geos[m], G['LIFT']), lid) > 0.01]
        line(not bad, 'lid closed over it: ' + (', '.join(bad) or 'free'))
    except Exception as ex:
        rep.append(f'SKIP lid check: {ex}')

    flat = cage.copy()
    flat.rotate(O, V(1, 0, 0), 180)        # the cage prints upside down
    coupon = base.common(Part.makeCylinder(27, 14, V(0, -GY, -1)))
    for n, s in (('geo_lock_base', base), ('geo_lock_cage_x2', flat), ('geo_lock_ring_lever', ring_a), ('geo_lock_ring_plain', ring_b),
                 ('geo_lock_collar_x2', make_collar((G['D'] - G['COL_INT']) / 2)), ('geo_lock_rod', rod),
                 ('fit_test_geo_lock_base', coupon)):
        s = up(s, -s.BoundBox.ZMin)
        MeshPart.meshFromShape(Shape=s, LinearDeflection=0.02, AngularDeflection=0.08, Relative=False).write(os.path.join(OUT, n + '.stl'))
    doc.saveAs(os.path.join(HERE, 'geo_lock.FCStd'))
    try:
        pictures(ob)
    except Exception as ex:
        rep.append(f'SKIP pictures: {ex}')


def pictures(ob):
    import FreeCADGui as Gui
    colors = {'Base': (.93, .93, .91), 'Cage': (.20, .45, .75), 'Ring': (.95, .55, .15), 'Coll': (.85, .2, .2),
              'Rod': (.95, .55, .15), 'SM24': (.75, .6, .2), 'Perf': (.1, .45, .25), 'ESP3': (.15, .15, .18), 'ADC_': (.6, .1, .1)}
    for n, o in ob.items():
        o.ViewObject.ShapeColor = colors.get(n[:4], (.4, .4, .4))
    ob['Cage_1'].ViewObject.Transparency = 60
    view = Gui.getDocument(DOC).activeView()

    home = {n: o.Placement for n, o in ob.items()}        # shapes carry their own placement: pose on top of it
    iso = App.Rotation(0.424708, 0.17592, 0.339851, 0.820473)
    looks = {'iso': App.Rotation(Z, 150).multiply(iso), 'top': App.Rotation(), 'side': App.Rotation(V(1, 0, 0), 90),
             'module': App.Rotation(Z, 60).multiply(iso)}

    def pose(n, pl):
        ob[n].Placement = pl.multiply(home[n])

    def settle():      # the camera moves are animated
        t = time.time()
        while time.time() - t < 1.2:
            Gui.updateGui()
            time.sleep(0.02)

    def save(look, name):
        view.setCameraOrientation(looks[look])
        settle()
        view.fitAll()
        settle()
        view.saveImage(os.path.join(REN, name), 1400, 1000, 'White')

    x0, y0 = crank_xy(0)
    for tag, rot, z in (('travel', SEAT, G['LIFT']), ('deployed', 0, 0)):     # ends in the deployed pose
        for m in (1, 2):
            pose(f'Ring_{m}', App.Placement(O, App.Rotation(Z, -rot), V(0, GY if m == 1 else -GY, 0)))
            for n in (f'Collar_{m}', f'SM24_{m}'):
                pose(n, App.Placement(V(0, 0, z), App.Rotation()))
        x1, y1 = crank_xy(rot)
        pose('Rod', App.Placement(V(x1 - x0, y1 - y0, 0), App.Rotation()))
        save('iso', f'geo_lock_{tag}_iso.png')
        save('top', f'geo_lock_{tag}_top.png')
        hid = [o for n, o in ob.items() if n not in ('Cage_1', 'Ring_1', 'Collar_1', 'SM24_1')]
        ob['Cage_1'].ViewObject.Transparency = 70
        for o in hid:
            o.ViewObject.Visibility = False
        save('module', f'geo_lock_{tag}_module.png')
        save('side', f'geo_lock_{tag}_side.png')
        for o in hid:
            o.ViewObject.Visibility = True
    view.setCameraOrientation(looks['iso'])
    view.fitAll()


os.makedirs(OUT, exist_ok=True)
os.makedirs(REN, exist_ok=True)
REP = ['# sums'] + L['calc']()
try:
    run(REP)
    REP.append('DONE')
except Exception:
    REP.append('FAILED\n' + traceback.format_exc())
with open(os.path.join(OUT, 'geo_lock_report.txt'), 'w', encoding='utf-8') as fh:
    fh.write('\n'.join(REP) + '\n')
print('\n'.join(REP))
