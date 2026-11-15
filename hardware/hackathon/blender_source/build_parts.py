"""Rezon hardware parts as detailed, size-accurate Blender meshes (no textures).

Runs inside Blender (Text editor, `blender --python`, or the MCP `execute_code` tool).
Creates a collection "Rezon_Parts" next to the casing. Never touches any other object.
Scene convention of Rezon_Full_Mockup.blend: 1 Blender unit = 1 m, so every size below
is written in millimetres and scaled by 0.001 when the meshes are baked.
Re-running rebuilds the parts from scratch (only objects inside "Rezon_Parts" are replaced).
"""
import bpy
import bmesh
from math import radians, cos, sin, pi
from mathutils import Matrix

MM = 0.001
ROOT = "Rezon_Parts"
T = 1.6  # PCB thickness

# plate X -> world Y, plate Y -> world Z, extrusion -> world X
R_YZX = Matrix(((0, 0, 1, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
# plate X -> world X, plate Y -> world Z, extrusion -> world -Y
R_XZ = Matrix.Rotation(radians(90), 4, 'X')

# name: (base colour, metallic, roughness)   -- flat colours only, no textures
MATS = {
    'pcb_black': ((0.015, 0.017, 0.02), 0.0, 0.45),
    'pcb_blue': ((0.02, 0.07, 0.30), 0.0, 0.4),
    'pcb_red': ((0.55, 0.03, 0.04), 0.0, 0.4),
    'pcb_purple': ((0.22, 0.04, 0.33), 0.0, 0.4),
    'pcb_green': ((0.03, 0.22, 0.08), 0.0, 0.45),
    'tin': ((0.72, 0.73, 0.74), 1.0, 0.32),
    'steel': ((0.55, 0.56, 0.58), 1.0, 0.38),
    'zinc': ((0.62, 0.64, 0.66), 1.0, 0.45),
    'alu': ((0.80, 0.81, 0.82), 1.0, 0.28),
    'gold': ((0.95, 0.68, 0.22), 1.0, 0.3),
    'brass': ((0.80, 0.62, 0.25), 1.0, 0.35),
    'solder': ((0.78, 0.78, 0.76), 1.0, 0.25),
    'chip': ((0.03, 0.03, 0.035), 0.0, 0.5),
    'smd_res': ((0.04, 0.04, 0.045), 0.0, 0.55),
    'smd_cap': ((0.62, 0.50, 0.36), 0.0, 0.6),
    'led': ((0.95, 0.90, 0.60), 0.0, 0.35),
    'ferrite': ((0.09, 0.09, 0.10), 0.0, 0.7),
    'ferrite2': ((0.16, 0.16, 0.17), 0.0, 0.75),
    'plastic_black': ((0.025, 0.025, 0.028), 0.0, 0.5),
    'plastic_white': ((0.90, 0.89, 0.86), 0.0, 0.5),
    'plastic_blue': ((0.06, 0.22, 0.70), 0.0, 0.45),
    'plastic_teal': ((0.05, 0.42, 0.45), 0.0, 0.5),
    'plastic_grey': ((0.45, 0.46, 0.47), 0.0, 0.5),
    'usb_orange': ((0.90, 0.33, 0.10), 0.0, 0.5),
    'ink': ((0.02, 0.02, 0.02), 0.0, 0.6),
    'mark_white': ((0.85, 0.85, 0.85), 0.0, 0.6),
    'red': ((0.75, 0.06, 0.05), 0.0, 0.5),
    'paper': ((0.07, 0.07, 0.075), 0.0, 0.85),
    'paper_dark': ((0.035, 0.035, 0.04), 0.0, 0.7),
    'rubber': ((0.02, 0.02, 0.02), 0.0, 0.9),
    'cardboard': ((0.16, 0.14, 0.12), 0.0, 0.9),
    'phenolic': ((0.55, 0.36, 0.16), 0.0, 0.6),
}

SMD = {'0402': (1.0, 0.5, 0.35), '0603': (1.6, 0.8, 0.45), '0805': (2.0, 1.25, 0.5), '1206': (3.2, 1.6, 0.55)}


def rrect(sx, sy, r=0.0, seg=6, cx=0.0, cy=0.0):
    """Rounded rectangle outline, counter-clockwise."""
    if r <= 0:
        return [(cx - sx / 2, cy - sy / 2), (cx + sx / 2, cy - sy / 2), (cx + sx / 2, cy + sy / 2), (cx - sx / 2, cy + sy / 2)]
    pts = []
    for qx, qy, a0 in ((sx / 2 - r, sy / 2 - r, 0), (-sx / 2 + r, sy / 2 - r, 90), (-sx / 2 + r, -sy / 2 + r, 180), (sx / 2 - r, -sy / 2 + r, 270)):
        for i in range(seg + 1):
            a = radians(a0 + 90.0 * i / seg)
            pts.append((cx + qx + r * cos(a), cy + qy + r * sin(a)))
    return pts


def circ(cx, cy, r, seg=20):
    return [(cx + r * cos(2 * pi * i / seg), cy + r * sin(2 * pi * i / seg)) for i in range(seg)]


def segment(r, gap, a_half=None, seg=14, flip=False):
    """Circular segment: the part of a disc with x >= gap (mirrored if flip)."""
    a = a_half if a_half is not None else __import__('math').acos(max(-1.0, min(1.0, gap / r)))
    pts = [(r * cos(-a + 2 * a * i / seg), r * sin(-a + 2 * a * i / seg)) for i in range(seg + 1)]
    if flip:
        pts = [(-x, -y) for x, y in pts]
    return pts


def material(name):
    key = "RZ_" + name
    m = bpy.data.materials.get(key)
    if m is None:
        col, metal, rough = MATS[name]
        m = bpy.data.materials.new(key)
        try:
            m.use_nodes = True
        except Exception:
            pass
        m.diffuse_color = (*col, 1.0)
        m.metallic = min(metal, 0.5)  # viewport (solid mode) only; the shader node keeps the real value
        m.roughness = rough
        nt = getattr(m, 'node_tree', None)
        if nt:
            for n in nt.nodes:
                if n.type == 'BSDF_PRINCIPLED':
                    n.inputs['Base Color'].default_value = (*col, 1.0)
                    n.inputs['Metallic'].default_value = metal
                    n.inputs['Roughness'].default_value = rough
    return m


class Part:
    def __init__(self, name, **info):
        self.name = name
        self.info = info
        self.cats = {}
        self.stack = [Matrix.Identity(4)]

    # ---- local frames -------------------------------------------------
    def at(self, x=0.0, y=0.0, z=0.0, rot=0.0, flip=False):
        m = self.stack[-1] @ Matrix.Translation((x, y, z)) @ Matrix.Rotation(radians(rot), 4, 'Z')
        if flip:
            m = m @ Matrix.Rotation(pi, 4, 'X')
        self.stack.append(m)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.stack.pop()

    def _emit(self, cat, bm, M):
        bmesh.ops.transform(bm, matrix=self.stack[-1] @ M, verts=bm.verts[:])
        me = bpy.data.meshes.new("_rz_tmp")
        bm.to_mesh(me)
        bm.free()
        dst = self.cats.get(cat)
        if dst is None:
            dst = self.cats[cat] = bmesh.new()
        dst.from_mesh(me)
        bpy.data.meshes.remove(me)

    # ---- primitives (z = bottom of the primitive) ------------------------
    def box(self, cat, sx, sy, sz, x=0.0, y=0.0, z=0.0, bev=0.0, rot=0.0, seg=1):
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts[:])
        if bev > 0:
            b = min(bev, 0.45 * min(sx, sy, sz))
            bmesh.ops.bevel(bm, geom=bm.edges[:], offset=b, segments=seg, affect='EDGES', profile=0.5, clamp_overlap=True)
        self._emit(cat, bm, Matrix.Translation((x, y, z + sz / 2)) @ Matrix.Rotation(radians(rot), 4, 'Z'))

    @staticmethod
    def _axis(axis):
        if axis == 'x':
            return Matrix.Rotation(radians(90), 4, 'Y')
        if axis == 'y':
            return Matrix.Rotation(radians(-90), 4, 'X')
        return Matrix.Identity(4)

    def cyl(self, cat, r, h, x=0.0, y=0.0, z=0.0, seg=24, r2=None, axis='z'):
        """Cylinder / cone: base centre at (x, y, z), extends +h along the axis."""
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r, radius2=(r if r2 is None else r2), depth=h)
        self._emit(cat, bm, Matrix.Translation((x, y, z)) @ self._axis(axis) @ Matrix.Translation((0, 0, h / 2)))

    def lathe(self, cat, prof, x=0.0, y=0.0, z=0.0, seg=32, axis='z', closed=False, a0=0.0, a1=360.0):
        """Revolve a (radius, height) profile. closed joins the last point to the first. a0/a1 give a capped sector."""
        bm = bmesh.new()
        full = abs(a1 - a0) >= 359.999
        n = seg if full else seg + 1
        rings = []
        for r, zz in prof:
            if r < 1e-6:
                rings.append([bm.verts.new((0, 0, zz))])
            else:
                rings.append([bm.verts.new((r * cos(radians(a0 + (a1 - a0) * i / seg)), r * sin(radians(a0 + (a1 - a0) * i / seg)), zz)) for i in range(n)])
        pairs = list(zip(rings, rings[1:]))
        if closed:
            pairs.append((rings[-1], rings[0]))
        for a, b in pairs:
            for i in range(seg):
                j = (i + 1) % n
                try:
                    if len(a) == 1 and len(b) == 1:
                        continue
                    if len(a) == 1:
                        bm.faces.new((a[0], b[i], b[j]))
                    elif len(b) == 1:
                        bm.faces.new((a[i], a[j], b[0]))
                    else:
                        bm.faces.new((a[i], a[j], b[j], b[i]))
                except ValueError:
                    pass
        if not full:
            for idx in (0, seg):
                vs = []
                for ring in rings:
                    v = ring[0] if len(ring) == 1 else ring[idx]
                    if v not in vs:
                        vs.append(v)
                if len(vs) >= 3:
                    try:
                        bm.faces.new(vs)
                    except ValueError:
                        pass
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        self._emit(cat, bm, Matrix.Translation((x, y, z)) @ self._axis(axis))

    def plate(self, cat, outline, holes=(), h=T, x=0.0, y=0.0, z=0.0, rot=0.0, R=None):
        """Extruded 2D outline with holes (PCBs, shells, housings)."""
        bm = bmesh.new()
        loops, edges = [], []
        for pts in (outline, *holes):
            vs = [bm.verts.new((p[0], p[1], 0.0)) for p in pts]
            loops.append(vs)
            for i in range(len(vs)):
                edges.append(bm.edges.new((vs[i], vs[(i + 1) % len(vs)])))
        res = bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False, edges=edges, normal=(0, 0, 1))
        faces = [g for g in res['geom'] if isinstance(g, bmesh.types.BMFace)]
        top = {}
        for vs in loops:
            for v in vs:
                top[v] = bm.verts.new((v.co.x, v.co.y, h))
        for f in faces:
            bm.faces.new([top[v] for v in f.verts])
        for vs in loops:
            for i in range(len(vs)):
                a, b = vs[i], vs[(i + 1) % len(vs)]
                bm.faces.new((a, b, top[b], top[a]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bmesh.ops.dissolve_limit(bm, angle_limit=radians(0.5), verts=bm.verts[:], edges=bm.edges[:])
        M = Matrix.Translation((x, y, z)) @ Matrix.Rotation(radians(rot), 4, 'Z')
        if R is not None:
            M = M @ R
        self._emit(cat, bm, M)

    # ---- small electronic components (origin on the PCB top unless noted) ---
    def smd(self, kind, x, y, rot=0.0, size='0603', z=T):
        l, w, h = SMD[size]
        if kind == 'c':
            h = w * 0.9
        cat = {'r': 'smd_res', 'c': 'smd_cap', 'l': 'ferrite2', 'led': 'led', 'd': 'chip'}[kind]
        e = l * 0.22
        with self.at(x, y, z, rot):
            self.box(cat, l - 2 * e, w, h)
            for sg in (-1, 1):
                self.box('tin', e, w + 0.04, h + 0.02, sg * (l / 2 - e / 2))

    def passives(self, items, z=T):
        for it in items:
            kind, x, y = it[0], it[1], it[2]
            rot = it[3] if len(it) > 3 else 0
            size = it[4] if len(it) > 4 else '0603'
            self.smd(kind, x, y, rot, size, z)

    def _gull(self, xs, sg, bw, span, hz, lw, t=0.15, cat='tin'):
        ll = (span - bw) / 2
        for px in xs:
            self.box(cat, lw, ll * 0.45, t, px, sg * (span / 2 - ll * 0.225), 0)
            self.box(cat, lw, t, hz, px, sg * (span / 2 - ll * 0.45), 0)
            self.box(cat, lw, ll * 0.55 + 0.05, t, px, sg * (bw / 2 + ll * 0.275 - 0.025), hz - t)

    def soic(self, x, y, rot, bl, bw, bh, n, pitch, span, lw=0.3, z=T):
        """Gull-wing IC: bl along the pin rows, n pins per side, span = tip to tip."""
        with self.at(x, y, z, rot):
            self.box('chip', bl, bw, bh, 0, 0, 0.1, bev=0.12)
            self.cyl('mark_white', 0.28, 0.02, -bl / 2 + 0.65, -bw / 2 + 0.65, 0.1 + bh, seg=12)
            xs = [(i - (n - 1) / 2) * pitch for i in range(n)]
            for sg in (-1, 1):
                self._gull(xs, sg, bw, span, 0.1 + bh * 0.5, lw)

    def sot23(self, x, y, rot=0.0, five=False, z=T):
        with self.at(x, y, z, rot):
            self.box('chip', 2.9, 1.3, 1.0, 0, 0, 0.1, bev=0.1)
            self._gull([-0.95, 0, 0.95] if five else [-0.95, 0.95], -1, 1.3, 2.5, 0.6, 0.4)
            self._gull([-0.95, 0.95] if five else [0], 1, 1.3, 2.5, 0.6, 0.4)

    def sot223(self, x, y, rot=0.0, z=T):
        with self.at(x, y, z, rot):
            self.box('chip', 6.5, 3.5, 1.6, 0, 0, 0.1, bev=0.15)
            self._gull([-2.3, 0, 2.3], -1, 3.5, 7.0, 0.9, 0.7, t=0.25)
            self._gull([0], 1, 3.5, 7.0, 0.9, 3.0, t=0.25)

    def qfn(self, x, y, rot=0.0, size=4.0, n=6, pitch=0.5, h=0.85, z=T):
        with self.at(x, y, z, rot):
            self.box('chip', size, size, h, 0, 0, 0.02, bev=0.06)
            self.cyl('mark_white', 0.2, 0.02, -size / 2 + 0.5, -size / 2 + 0.5, 0.02 + h, seg=12)
            for i in range(n):
                p = (i - (n - 1) / 2) * pitch
                for sg in (-1, 1):
                    self.box('tin', 0.24, 0.4, 0.2, p, sg * (size / 2 - 0.12))
                    self.box('tin', 0.4, 0.24, 0.2, sg * (size / 2 - 0.12), p)

    def sma(self, x, y, rot=0.0, z=T):
        """SMA / DO-214AC diode."""
        with self.at(x, y, z, rot):
            self.box('chip', 4.3, 2.6, 2.2, 0, 0, 0.05, bev=0.2)
            self.box('mark_white', 0.55, 2.62, 2.22, -1.35, 0, 0.04, bev=0.2)
            for sg in (-1, 1):
                self.box('tin', 1.1, 1.5, 1.1, sg * 2.45, 0, 0)

    def solder(self, x, y, z=T, down=False):
        with self.at(x, y, z, flip=down):
            self.lathe('solder', [(0, 0), (0.9, 0), (0.42, 0.7), (0, 0.7)], seg=12)

    def header_male(self, n, x, y, rot=0.0, down=True, pitch=2.54, mate=6.1, col='plastic_black'):
        """Straight pin header. (x, y) = first pin, row runs along local +x. down: plastic and pins under the PCB."""
        with self.at(x, y, 0, rot):
            for i in range(n):
                px = i * pitch
                if down:
                    self.box(col, pitch - 0.06, 2.5, 2.54, px, 0, -2.54, bev=0.3)
                    self.box('gold', 0.64, 0.64, 2.54 + mate + T + 1.0, px, 0, -(2.54 + mate), bev=0.14)
                    self.solder(px, 0, T)
                else:
                    self.box(col, pitch - 0.06, 2.5, 2.54, px, 0, T, bev=0.3)
                    self.box('gold', 0.64, 0.64, 1.0 + T + 2.54 + mate, px, 0, -1.0, bev=0.14)
                    self.solder(px, 0, 0, down=True)

    def header_male_ra(self, n, x, y, rot=0.0, pitch=2.54, mate=6.1, col='plastic_black'):
        """Right-angle pin header on the PCB top. (x, y) = first solder hole, row along local +y, pins point local +x."""
        with self.at(x, y, 0, rot):
            for i in range(n):
                py = i * pitch
                zc = T + 1.52
                self.box(col, 2.5, pitch - 0.06, 2.54, 2.8, py, T + 0.25, bev=0.3)
                self.box('gold', 0.64, 0.64, 1.0 + zc + 0.32, 0, py, -1.0, bev=0.1)
                self.box('gold', 1.55 + 2.5 + mate, 0.64, 0.64, (1.55 + 2.5 + mate) / 2 - 0.32, py, zc - 0.32, bev=0.14)
                self.solder(0, py, 0, down=True)

    def header_female(self, n, x, y, rot=0.0, h=8.5, pitch=2.54, col='plastic_black'):
        """Female socket strip on the PCB top with real square pin holes. (x, y) = first pin, row along local +x."""
        L = n * pitch
        with self.at(x, y, 0, rot):
            cx = (n - 1) * pitch / 2
            holes = [rrect(1.0, 1.0, 0, 1, i * pitch, 0) for i in range(n)]
            self.plate(col, rrect(L, 2.5, 0, 1, cx, 0), holes, h - 0.8, z=T + 0.8)
            self.box(col, L, 2.5, 0.8, cx, 0, T)
            for i in range(n):
                self.box('gold', 0.9, 0.9, 0.5, i * pitch, 0, T + 0.8)
                self.box('gold', 0.5, 0.5, 2.6 + T, i * pitch, 0, -2.6)
                self.solder(i * pitch, 0, 0, down=True)

    def screw_term(self, n, x, y, rot=0.0, pitch=5.08, depth=7.6, h=10.0, col='plastic_blue', z=T):
        """PCB screw terminal block. Row along local x (centred), wire entry faces local -y."""
        W, hl, ft = n * pitch, h * 0.6, 2.0
        ud = depth * 0.72
        yu = (depth - ud) / 2
        with self.at(x, y, z, rot):
            holes = [rrect(pitch * 0.55, hl * 0.5, 0, 1, (i - (n - 1) / 2) * pitch, hl * 0.45) for i in range(n)]
            self.plate(col, rrect(W, hl, 0, 1, 0, hl / 2), holes, ft, y=-depth / 2 + ft, R=R_XZ)
            self.box(col, W, depth - ft, hl, 0, ft / 2, 0)
            wells = [circ((i - (n - 1) / 2) * pitch, 0, pitch * 0.33, 20) for i in range(n)]
            self.plate(col, rrect(W, ud, 0, 1), wells, h - hl, y=yu, z=hl)
            for i in range(n):
                px = (i - (n - 1) / 2) * pitch
                r = pitch * 0.3
                self.cyl('steel', r, h - hl - 1.4, px, yu, hl, seg=20)
                for fl in (False, True):
                    self.plate('steel', segment(r, 0.3, seg=8, flip=fl), [], 0.6, x=px, y=yu, z=h - 1.4)
                self.box('tin', pitch * 0.55 - 0.1, 0.3, hl * 0.5 - 0.1, px, -depth / 2 + 1.3, hl * 0.2 + 0.05)
                self.box('tin', 0.8, 0.5, T + 2.8, px, 0.5, -(T + 2.8))

    def ecap(self, x, y, d, h, rot=0.0, z=T):
        """SMD aluminium electrolytic capacitor."""
        b, c, r = d + 0.3, d * 0.22, d / 2
        with self.at(x, y, z, rot):
            self.plate('plastic_black', [(-b / 2, -b / 2), (b / 2 - c, -b / 2), (b / 2, -b / 2 + c), (b / 2, b / 2 - c), (b / 2 - c, b / 2), (-b / 2, b / 2)], [], 1.3)
            self.lathe('alu', [(0, 1.3), (r, 1.3), (r, 2.0), (r - 0.3, 2.25), (r, 2.5), (r, h - 0.35), (r - 0.35, h), (0, h)], seg=40)
            self.plate('ink', segment(r - 0.45, (r - 0.45) * 0.35, seg=16, flip=True), [], 0.03, z=h)
            for sg in (-1, 1):
                self.box('tin', 1.4, 0.9, 0.3, sg * (b / 2 + 0.35), 0, 0)

    def inductor(self, x, y, size=12.0, h=7.0, rot=0.0, z=T):
        """Shielded SMD power inductor."""
        a, c = size / 2, size * 0.2
        o = [(-a + c, -a), (a - c, -a), (a, -a + c), (a, a - c), (a - c, a), (-a + c, a), (-a, a - c), (-a, -a + c)]
        with self.at(x, y, z, rot):
            self.plate('ferrite', o, [], h - 1.2)
            self.plate('ferrite', o, [circ(0, 0, size * 0.37, 32)], 1.2, z=h - 1.2)
            self.cyl('ferrite2', size * 0.35, 0.9, 0, 0, h - 1.2, seg=32)
            for sg in (-1, 1):
                self.box('tin', 3.2, 0.35, 2.2, 0, sg * (a + 0.1), 0)

    def to263(self, x, y, rot=0.0, z=T):
        """TO-263-5 regulator: leads toward local +y, heatsink tab toward -y."""
        with self.at(x, y, z, rot):
            self.box('chip', 10.0, 8.6, 4.4, 0, 0, 0.05, bev=0.35)
            self.box('tin', 10.0, 10.1, 1.25, 0, -0.75, 0)
            self._gull([(i - 2) * 1.7 for i in range(5)], 1, 8.6, 8.6 + 2 * 4.6, 1.6, 0.8, t=0.45)

    def trimmer(self, x, y, rot=0.0, z=T):
        """3296W multi-turn trimmer, adjusting screw on top at local +x."""
        with self.at(x, y, z, rot):
            self.box('plastic_blue', 9.5, 4.8, 10.0, 0, 0, 0, bev=0.3)
            self.cyl('brass', 1.25, 0.9, 3.2, 0, 10.0, seg=20)
            for fl in (False, True):
                self.plate('brass', segment(1.25, 0.22, seg=8, flip=fl), [], 0.6, x=3.2, z=10.9)
            for px in (-2.54, 0, 2.54):
                self.box('tin', 0.5, 0.5, T + 3.0, px, 0, -(T + 3.0))

    def jack35(self, x, y, rot=0.0, bl=11.5, bw=6.0, bh=5.0, barrel=3.0, z=T):
        """3.5 mm audio jack. Mouth faces local +x, origin on the mouth plane of the body."""
        with self.at(x, y, z, rot):
            self.box('plastic_black', bl, bw, bh, -bl / 2, 0, 0, bev=0.25)
            self.lathe('plastic_black', [(1.8, 0), (2.5, 0), (2.5, barrel - 0.3), (2.25, barrel), (1.8, barrel)], 0, 0, bh / 2, seg=28, axis='x', closed=True)
            self.cyl('gold', 1.75, 0.15, 0.02, 0, bh / 2, seg=28, axis='x')
            for tx, sg in ((-1.6, 1), (-1.6, -1), (-bl + 2.0, 1), (-bl + 2.0, -1), (-bl / 2, -1)):
                self.box('gold', 1.6, 1.5, 0.4, tx, sg * (bw / 2 + 0.6), 0)

    def usb_c(self, x, y, rot=0.0, z=T):
        """USB-C receptacle. Mouth faces local +x, origin on the mouth plane."""
        with self.at(x, y, z, rot):
            self.plate('tin', rrect(8.94, 3.16, 1.5, 8, 0, 1.63), [rrect(8.34, 2.56, 1.2, 8, 0, 1.63)], 7.3, x=-7.3, R=R_YZX)
            self.box('tin', 0.4, 8.5, 2.9, -7.1, 0, 0.18)
            self.box('plastic_black', 5.8, 6.7, 0.7, -4.0, 0, 1.28)
            self.box('gold', 3.6, 5.8, 0.76, -2.9, 0, 1.25)
            for sy in (-1, 1):
                for sx in (-1.4, -5.6):
                    self.box('tin', 1.1, 0.5, 1.4, sx, sy * 4.6, -0.2)

    def usb_a(self, x, y, rot=0.0, z=T):
        """USB-A receptacle. Mouth faces local +x, origin on the mouth plane."""
        L = 14.0
        with self.at(x, y, z, rot):
            self.plate('tin', rrect(13.1, 5.7, 0.5, 4, 0, 2.95), [rrect(12.5, 5.1, 0.3, 4, 0, 2.95)], L, x=-L, R=R_YZX)
            self.box('tin', 0.4, 12.9, 5.4, -L + 0.2, 0, 0.25)
            self.box('usb_orange', 9.0, 11.2, 1.9, -L + 4.9, 0, 3.3)
            for py in (-3.5, -1.0, 1.0, 3.5):
                self.box('gold', 6.5, 1.0, 0.12, -L + 6.0, py, 3.2)
            for sy in (-1, 1):
                for sx in (-2.5, -11.0):
                    self.box('tin', 2.0, 0.4, 2.2, sx, sy * 6.75, -1.0)

    def dc_jack(self, x, y, rot=0.0, z=T):
        """5.5 x 2.1 mm DC barrel jack (DC-005). Mouth faces local +x."""
        with self.at(x, y, z, rot):
            self.plate('plastic_black', rrect(9.0, 11.0, 0.5, 3, 0, 5.5), [circ(0, 6.5, 3.2, 28)], 9.0, x=-9.0, R=R_YZX)
            self.box('plastic_black', 5.2, 9.0, 6.5, -11.6, 0, 0)
            self.cyl('plastic_black', 4.5, 5.2, -14.2, 0, 6.5, seg=32, axis='x')
            self.cyl('tin', 1.0, 8.2, -9.0, 0, 6.5, seg=16, axis='x')
            self.box('tin', 5.0, 2.6, 0.3, -4.5, 0, 3.4)
            self.box('tin', 0.4, 3.0, 4.0, -14.4, 0, 0.5)

    def tact_smd(self, x, y, rot=0.0, z=T):
        with self.at(x, y, z, rot):
            self.box('plastic_black', 4.0, 3.0, 1.2, 0, 0, 0)
            self.box('tin', 4.0, 3.0, 0.25, 0, 0, 1.2, bev=0.08)
            self.cyl('plastic_black', 0.85, 0.5, 0, 0, 1.45, seg=16)
            for sg in (-1, 1):
                self.box('tin', 0.7, 0.6, 0.4, sg * 2.3, 0, 0)

    def ufl(self, x, y, z=T):
        with self.at(x, y, z):
            self.box('gold', 2.6, 2.6, 0.35)
            self.lathe('gold', [(0.72, 0.35), (1.0, 0.35), (1.0, 1.15), (0.9, 1.25), (0.72, 1.25)], seg=24, closed=True)
            self.cyl('plastic_white', 0.72, 0.4, 0, 0, 0.35, seg=20)
            self.cyl('gold', 0.25, 0.5, 0, 0, 0.75, seg=12)

    def crystal(self, x, y, rot=0.0, z=T):
        """HC-49S crystal."""
        with self.at(x, y, z, rot):
            self.plate('tin', rrect(11.4, 4.9, 2.45, 8), [], 0.45)
            self.plate('tin', rrect(10.3, 3.8, 1.9, 8), [], 3.0, z=0.45)

    def pot(self, x, y, rot=0.0, z=T):
        """9 mm rotary volume pot with slotted shaft."""
        with self.at(x, y, z, rot):
            self.box('plastic_teal', 9.8, 11.0, 2.0, 0, 0, 0, bev=0.2)
            self.box('tin', 9.8, 11.0, 4.8, 0, 0, 2.0, bev=0.35)
            self.lathe('tin', [(0, 6.8), (3.4, 6.8), (3.4, 11.0), (3.1, 11.3), (0, 11.3)], seg=32)
            self.cyl('alu', 3.0, 1.0, 0, 0, 11.3, seg=32)
            for fl in (False, True):
                self.plate('alu', segment(3.0, 0.5, seg=14, flip=fl), [], 4.0, z=12.3)
            for sg in (-1, 1):
                self.box('tin', 0.4, 2.0, 5.5, sg * 5.1, 0, -0.5)
            for px in (-2.5, 0, 2.5):
                self.box('tin', 0.9, 0.3, 3.0, px, -6.2, 0)

    # ---- bake ----------------------------------------------------------
    def min_z(self):
        return min((v.co.z for bm in self.cats.values() for v in bm.verts), default=0.0)

    def bounds(self):
        xs = [v.co.x for bm in self.cats.values() for v in bm.verts]
        ys = [v.co.y for bm in self.cats.values() for v in bm.verts]
        zs = [v.co.z for bm in self.cats.values() for v in bm.verts]
        return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))

    def bake(self, parent_coll, loc_mm):
        coll = bpy.data.collections.new(self.name)
        parent_coll.children.link(coll)
        root = bpy.data.objects.new(self.name, None)
        root.empty_display_type = 'PLAIN_AXES'
        root.empty_display_size = 0.01
        root.location = (loc_mm[0] * MM, loc_mm[1] * MM, -self.min_z() * MM)
        bx = self.bounds()
        root["overall_mm"] = "%.1f x %.1f x %.1f" % bx
        for k, v in self.info.items():
            root[k] = v
        coll.objects.link(root)
        nverts = 0
        for cat, bm in self.cats.items():
            bmesh.ops.scale(bm, vec=(MM, MM, MM), verts=bm.verts[:])
            me = bpy.data.meshes.new("%s.%s" % (self.name, cat))
            bm.to_mesh(me)
            bm.free()
            me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
            try:
                me.set_sharp_from_angle(angle=radians(40))
            except Exception:
                pass
            me.materials.append(material(cat))
            ob = bpy.data.objects.new(me.name, me)
            ob.parent = root
            coll.objects.link(ob)
            nverts += len(me.vertices)
        self.cats = {}
        return root, bx, nverts


# =====================================================================
#  The parts
# =====================================================================
def build_esp32():
    """ESP32-S3-DevKitC-1 style board with ESP32-S3-WROOM-1-N16R8, two USB-C, 2 x 22 pins down."""
    P = Part("ESP32-S3_DevKit", pcb_mm="63.0 x 25.4 x 1.6", pins="2 x 22, 2.54 mm pitch, rows 22.86 mm apart",
             source="Espressif DevKitC-1 drawing + wiring guide")
    L, W = 63.0, 25.4
    P.plate('pcb_black', rrect(L, W, 0.8, 4), [], T)
    with P.at(-L / 2 + 12.75, 0, T):  # ESP32-S3-WROOM-1: 18 x 25.5 x 3.1
        P.box('pcb_black', 25.5, 18.0, 0.8)
        P.box('tin', 17.6, 15.8, 2.3, 3.45, 0, 0.8, bev=0.25)
        xs = [-12.0, -10.6, -9.2, -7.8]
        for i, xa in enumerate(xs):
            P.box('gold', 0.5, 13.0, 0.04, xa, 0, 0.8)
            if i < len(xs) - 1:
                P.box('gold', 1.9, 0.5, 0.04, xa + 0.7, 6.25 if i % 2 == 0 else -6.25, 0.8)
        for i in range(14):
            for sg in (-1, 1):
                P.box('gold', 0.75, 0.9, 0.84, 11.9 - i * 1.27, sg * 8.6, -0.02)
        for i in range(12):
            P.box('gold', 0.9, 0.75, 0.84, 12.35, (i - 5.5) * 1.27, -0.02)
    for sy in (-1, 1):
        P.usb_c(L / 2 + 1.0, sy * 5.7)
        P.tact_smd(20.5, sy * 7.8, 90)
        P.header_male(22, -26.67, sy * 11.43, down=True)
    with P.at(20.6, 0, T):  # addressable RGB LED
        P.box('plastic_white', 3.5, 3.5, 1.0, 0, 0, 0, bev=0.1)
        P.cyl('led', 1.3, 0.15, 0, 0, 1.0, seg=20)
    P.qfn(10.5, 4.6, 0, size=4.0, n=6)        # USB-UART bridge
    P.sot223(0.6, -5.2, 0)                    # 3.3 V LDO
    P.sot23(15.6, 3.2, 90)
    P.sot23(15.6, -3.2, 90)
    P.sot23(6.0, -1.0, 0, five=True)
    P.passives([
        ('c', -3.6, 6.5, 90, '0805'), ('c', -3.6, 2.5, 90, '0805'), ('c', 5.6, -6.6, 0, '0805'), ('c', 5.6, -4.4, 0, '0805'),
        ('r', 6.4, 8.3, 0, '0402'), ('r', 8.6, 8.3, 0, '0402'), ('c', 14.0, 8.4, 0, '0402'), ('c', 5.0, 2.2, 90, '0402'),
        ('r', 6.4, 2.2, 90, '0402'), ('c', 7.8, 2.2, 90, '0402'), ('r', 11.0, 0.6, 0, '0402'), ('c', 13.2, 0.6, 0, '0402'),
        ('r', 10.4, -2.6, 0, '0402'), ('r', 12.4, -2.6, 0, '0402'), ('c', 10.4, -4.2, 0, '0402'), ('c', 12.4, -4.2, 0, '0402'),
        ('led', 11.0, -7.4, 0, '0603'), ('r', 14.0, -7.4, 0, '0402'), ('d', 17.4, 6.4, 90, '0603'), ('d', 17.4, -6.4, 90, '0603'),
        ('c', -3.6, -1.6, 90, '0603'), ('r', 0.8, 1.4, 0, '0402'), ('r', 0.8, 3.0, 0, '0402'), ('c', 0.8, 5.0, 0, '0603'),
    ])
    return P


def build_click():
    """MikroE ADC 15 Click (MIKROE-4890, ADS131M02), M-size Click board, mikroBUS pins down."""
    P = Part("ADC15_Click", pcb_mm="42.9 x 25.4 x 1.6", pins="mikroBUS 2 x 8, rows 22.86 mm apart",
             source="MikroE Click M size + wiring guide positions")
    L, W = 42.9, 25.4
    a, b, c = L / 2, W / 2, 2.54
    out = rrect(L, W, 0.6, 3)
    # mikroBUS orientation chamfer on one corner
    out = [p for p in out if not (p[0] > a - c and p[1] < -b + c)] + []
    out = sorted(out, key=lambda p: __import__('math').atan2(p[1], p[0]))
    out.append((a, -b + c))
    out.append((a - c, -b))
    out = sorted(out, key=lambda p: __import__('math').atan2(p[1], p[0]))
    P.plate('pcb_black', out, [], T)
    for sy in (-1, 1):
        P.header_male(8, -20.13, sy * 11.43, down=True)
    P.screw_term(2, 17.05, 4.73, 90, pitch=4.0, depth=7.0, h=8.7, col='plastic_black')
    P.screw_term(2, 17.05, -6.27, 90, pitch=4.0, depth=7.0, h=8.7, col='plastic_black')
    P.soic(5.0, 0, 90, 6.5, 4.4, 1.0, 10, 0.65, 6.4, lw=0.25)      # ADS131M02, TSSOP-20
    P.soic(-4.6, 5.4, 0, 3.0, 3.0, 0.85, 4, 0.65, 4.9, lw=0.28)    # LTC6903 clock, MSOP-8
    P.sot23(-5.0, -5.4, 0, five=True)                               # LDO / reference
    P.sot23(-11.5, 0.4, 90)
    P.passives([
        ('c', 9.8, 3.4, 90), ('c', 9.8, 0.0, 90), ('c', 9.8, -3.4, 90), ('r', 11.6, 6.2, 0), ('r', 11.6, -6.6, 0),
        ('c', 0.4, 3.6, 90), ('c', 0.4, 0.0, 90), ('c', 0.4, -3.6, 90), ('r', -1.4, 8.6, 0), ('r', 1.6, 8.6, 0),
        ('c', -8.4, 5.4, 90), ('c', -0.6, 5.4, 90, '0402'), ('c', -8.6, -5.4, 90), ('c', -1.6, -5.4, 90),
        ('r', -11.4, 5.0, 0), ('r', -11.4, -4.6, 0), ('led', -16.2, -7.6, 0), ('r', -13.4, -7.6, 0),
        ('r', -16.0, 4.0, 90, '0805'), ('r', -16.0, -0.4, 90, '0805'), ('c', 5.0, 7.4, 0, '0805'), ('c', 5.0, -7.6, 0, '0805'),
    ])
    return P


def build_geophone():
    """SM-24 geophone element (SparkFun SEN-11744): 25.4 mm diameter, 32 mm tall."""
    P = Part("SM-24_Geophone", body_mm="dia 25.4 x 32.0 (terminals +4.0)", source="ION SM-24 brochure")
    r = 12.7
    P.lathe('steel', [(0, 0), (11.9, 0), (r, 0.8), (r, 3.0), (r - 0.25, 3.3), (r - 0.25, 3.9), (r, 4.2), (r, 26.6), (r - 0.25, 26.9),
                      (r - 0.25, 27.5), (r, 27.8), (r, 30.9), (r - 0.5, 31.6), (11.5, 31.6), (11.5, 30.4), (0, 30.4)], seg=64)
    P.lathe('plastic_black', [(0, 30.4), (11.5, 30.4), (11.5, 31.2), (10.9, 32.0), (0, 32.0)], seg=64)
    P.cyl('plastic_black', 2.2, 0.5, 0, 0, 32.0, seg=24)
    for sg in (-1, 1):
        P.cyl('plastic_black', 1.9, 0.8, sg * 5.0, 0, 32.0, seg=20)
        P.plate('tin', rrect(2.6, 4.0, 0.6, 3, 0, 2.0), [circ(0, 2.6, 0.6, 12)], 0.5, x=sg * 5.0, y=0.25, z=32.4, R=R_XZ)
    P.cyl('red', 0.8, 0.12, 5.0, 4.2, 32.0, seg=16)   # polarity dot next to the + terminal
    return P


def build_speaker():
    """Small 1 W 8 ohm speaker, 40 mm frame (size taken from the wiring guide: measure the real one)."""
    P = Part("Speaker_1W_8ohm", body_mm="dia 40.0 x 16.0", source="wiring guide placeholder size, not measured")
    P.lathe('zinc', [(0, 0), (9.5, 0), (10.0, 0.4), (10.0, 1.8), (0, 1.8)], seg=48)
    P.lathe('ferrite', [(0, 1.8), (10.7, 1.8), (11.0, 2.1), (11.0, 6.0), (10.7, 6.3), (0, 6.3)], seg=48)
    P.lathe('zinc', [(0, 6.3), (10.5, 6.3), (10.5, 7.8), (0, 7.8)], seg=48)
    P.lathe('zinc', [(5.0, 7.8), (12.0, 7.8), (12.6, 8.3), (5.0, 8.3)], seg=48, closed=True)
    for k in range(4):
        P.lathe('zinc', [(12.0, 7.9), (12.6, 7.9), (18.6, 13.5), (18.0, 13.5)], seg=6, closed=True, a0=45 + 90 * k - 19, a1=45 + 90 * k + 19)
    P.lathe('zinc', [(18.0, 13.3), (18.7, 13.3), (18.7, 14.9), (20.0, 14.9), (20.0, 15.5), (18.0, 15.5)], seg=64, closed=True)
    P.lathe('cardboard', [(18.4, 15.5), (20.0, 15.5), (20.0, 16.0), (18.4, 16.0)], seg=64, closed=True)
    top = [(17.0 - 1.4 * cos(pi * k / 8), 15.0 + 0.9 * sin(pi * k / 8)) for k in range(9)]
    P.lathe('rubber', top + [(rr, zz - 0.25) for rr, zz in reversed(top)], seg=64, closed=True)
    P.lathe('paper', [(5.5, 9.3), (10.2, 12.5), (15.6, 15.0), (15.6, 14.7), (10.2, 12.2), (5.5, 9.0)], seg=64, closed=True)
    P.lathe('paper_dark', [(0, 11.5)] + [(5.8 * sin(pi / 2 * k / 6), 9.3 + 2.2 * cos(pi / 2 * k / 6)) for k in range(1, 7)] + [(0, 9.3)], seg=48)
    P.box('phenolic', 1.0, 10.0, 5.0, 16.4, 0, 8.4)
    for sg in (-1, 1):
        P.plate('tin', rrect(2.4, 6.0, 0.5, 3, 0, 3.0), [circ(0, 1.4, 0.6, 12)], 0.4, x=17.3, y=sg * 2.7, z=5.6,
                R=Matrix(((0, 0, 1, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 1))))
        P.cyl('brass', 0.8, 0.5, 16.9, sg * 2.7, 10.4, seg=12, axis='x')
    return P


def build_sim868():
    """Waveshare Pico-SIM868-GSM/GPRS/GNSS board, Pico removed (used as a modem only)."""
    P = Part("SIM868_Board", pcb_mm="76.15 x 24.0 x 1.6", pins="2 x 20 female sockets, rows 17.78 mm apart",
             source="Waveshare outline 76.15 x 24.00 + photo uploads/NewSIM.jpg")
    L, W = 76.15, 24.0
    P.plate('pcb_blue', rrect(L, W, 1.0, 4), [], T)
    for sy in (-1, 1):
        P.header_female(20, -12.16, sy * 8.89)
    with P.at(-26.0, -1.6, T):  # SIM868 module: 15.7 x 17.6 x 2.3
        P.box('pcb_green', 15.7, 17.6, 0.7)
        P.box('tin', 14.6, 16.5, 1.6, 0, 0, 0.7, bev=0.2)
        P.box('red', 4.4, 13.5, 0.03, -4.6, 0, 2.3)
        for i in range(15):
            for sg in (-1, 1):
                P.box('gold', 0.6, 0.7, 0.74, sg * 7.55, (i - 7) * 1.1, -0.02)
        for i in range(13):
            for sg in (-1, 1):
                P.box('gold', 0.7, 0.6, 0.74, (i - 6) * 1.1, sg * 8.5, -0.02)
    P.ufl(-30.6, 9.6)     # GSM
    P.ufl(-24.6, 9.6)     # BT
    P.ufl(-36.0, -9.8)    # GNSS
    with P.at(-18.9, 9.6, T):   # microphone
        P.cyl('tin', 2.0, 1.3, seg=24)
        P.cyl('ink', 0.5, 0.02, 0, 0, 1.3, seg=12)
    P.tact_smd(-13.2, 10.0, 0)                      # PWR key
    with P.at(-14.6, -10.4, T):                     # power slide switch
        P.box('tin', 6.7, 2.7, 1.4, 0, 0, 0, bev=0.1)
        P.box('plastic_black', 1.3, 1.6, 1.0, -1.0, -2.0, 0.2)
    with P.at(17.7, 3.0, T):                        # PH2.0 battery socket
        P.plate('plastic_white', rrect(5.9, 4.5, 0.3, 2), [rrect(4.6, 3.0, 0, 1, 0, -0.1)], 5.2, z=0.8)
        P.box('plastic_white', 5.9, 4.5, 0.8)
        for sg in (-1, 1):
            P.box('tin', 0.5, 0.5, 4.0, sg * 1.0, -0.1, 0.8)
    P.soic(6.0, 1.5, 0, 5.0, 4.4, 1.0, 7, 0.65, 6.4, lw=0.25)      # TXB0104 level shifter
    P.soic(27.5, -1.0, 90, 4.9, 3.9, 1.4, 4, 1.27, 6.0, lw=0.4)    # charger, SOP-8
    P.sot23(-3.5, -3.5, 0, five=True)
    P.sot23(11.5, -3.6, 0)
    P.sot23(22.0, 4.6, 90)
    with P.at(-5.2, 3.2, T):                        # small power inductor
        P.box('ferrite', 4.0, 4.0, 2.0, 0, 0, 0, bev=0.3)
    P.sma(33.0, 2.0, 90)
    P.passives([
        ('led', -36.6, -1.0, 90), ('led', -36.6, 4.6, 90), ('led', -9.0, -10.6, 0), ('r', -36.6, 1.8, 90, '0402'),
        ('c', -15.6, 4.6, 90, '0805'), ('c', -15.6, 1.0, 90, '0805'), ('c', -15.6, -3.0, 90, '0805'), ('c', -15.6, -6.4, 90),
        ('r', 0.0, -3.6, 0, '0402'), ('r', 0.0, -2.2, 0, '0402'), ('c', 0.6, 4.6, 0), ('c', 11.4, 2.6, 0), ('c', 11.4, 4.4, 0),
        ('r', 15.4, -3.6, 0), ('r', 15.4, -1.6, 0), ('c', 22.4, -3.6, 0, '0805'), ('c', 22.4, -1.0, 0, '0805'),
        ('r', 26.0, 4.8, 0), ('r', 29.4, 4.8, 0), ('c', 32.8, -3.4, 0), ('r', 6.0, -3.8, 0), ('c', 6.0, 5.4, 0),
        ('r', -9.2, 10.6, 0, '0402'), ('c', -21.6, -10.6, 0, '0402'), ('c', -27.6, 10.9, 0, '0402'),
    ])
    with P.at(-25.5, 0.5, 0, flip=True):            # nano SIM holder on the back
        P.plate('tin', rrect(12.3, 11.6, 0.4, 2), [rrect(8.6, 7.4, 0.3, 2, -0.6, 0)], 0.2, z=1.15)
        for sg in (-1, 1):
            P.box('tin', 12.3, 0.25, 1.15, 0, sg * 5.68, 0)
        P.box('tin', 0.25, 11.6, 1.15, 6.03, 0, 0)
        P.box('plastic_black', 11.6, 10.8, 0.45, -0.1, 0, 0)
        for i in range(6):
            P.box('gold', 1.4, 0.7, 0.3, -2.0 + (i // 3) * 3.6, (i % 3 - 1) * 2.54, 0.45)
    with P.at(-8.0, 0, 0, flip=True):               # speaker socket, 1.25 mm 2-pin
        P.plate('plastic_white', rrect(4.2, 3.4, 0.2, 2), [rrect(3.0, 1.8, 0, 1)], 3.2, z=0.6)
        P.box('plastic_white', 4.2, 3.4, 0.6)
    with P.at(0, 0, 0, flip=True):
        P.passives([('c', 8.0, 4.0, 0), ('c', 8.0, 1.6, 0), ('r', 8.0, -1.0, 0), ('c', 14.0, 3.0, 90, '0805'), ('r', 14.0, -2.4, 90),
                    ('c', -14.0, 6.0, 0), ('c', -14.0, -6.0, 0), ('r', 20.0, 0.0, 90), ('c', 26.0, 3.0, 0), ('c', 26.0, -3.0, 0)], z=0)
    return P


def build_pcm5102():
    """PCM5102A I2S DAC module (purple GY-PCM5102), photo uploads/Device1.jpg."""
    P = Part("PCM5102A_DAC", pcb_mm="31.8 x 17.2 x 1.6", pins="6-pin right-angle header + 9 empty holes",
             source="GY-PCM5102 outline on a 2.54 mm grid + photo")
    L, W = 31.8, 17.2
    row = [(-10.16 + 2.54 * i, -7.62) for i in range(9)]
    P.plate('pcb_purple', rrect(L, W, 0.5, 3), [circ(x, y, 0.5, 12) for x, y in row], T)
    for x, y in row:
        for zz in (T, -0.04):
            P.lathe('gold', [(0.5, 0), (0.95, 0), (0.95, 0.04), (0.5, 0.04)], x, y, zz, seg=16, closed=True)
    P.header_male_ra(6, 14.3, -5.08, 0)
    P.jack35(-L / 2, 3.4, 180, bl=10.5, bw=6.4, bh=5.0, barrel=3.2)
    P.soic(3.4, 2.0, 90, 6.5, 4.4, 1.0, 10, 0.65, 6.4, lw=0.25)    # PCM5102A, TSSOP-20
    P.sot23(3.2, 6.9, 0, five=True)
    P.sot23(3.8, -3.2, 0, five=True)
    P.passives([
        ('r', -3.6, 6.8, 0), ('c', -1.0, 6.8, 0, '0402'), ('c', -3.4, 4.2, 0), ('c', -3.2, 2.2, 0), ('c', -2.6, 0.0, 0),
        ('c', -2.0, -2.2, 0, '0805'), ('c', -0.6, -4.6, 0), ('c', 8.6, 6.4, 0), ('c', 8.8, 4.0, 0), ('r', 9.6, 1.6, 90, '0805'),
        ('c', 7.6, -1.4, 0), ('c', 8.2, -3.4, 0), ('r', -6.4, -3.6, 90, '0402'), ('r', -8.0, -3.6, 90, '0402'), ('c', 0.0, 4.4, 90, '0402'),
    ])
    with P.at(0, 0, 0, flip=True):                  # solder-jumper pads on the back (H1L..H4L)
        for i in range(4):
            for dx in (-0.9, 0, 0.9):
                P.box('gold', 0.7, 1.4, 0.04, -6.0 + i * 4.0 + dx, 1.5, 0)
    return P


def build_zk502m():
    """ZK-502M Bluetooth / AUX amplifier board (WUZHI), photo uploads/Device2.jpg."""
    P = Part("ZK-502M_Amp", pcb_mm="60.0 x 58.0 x 1.6 (from the photo: check with calipers)", source="seller size 60 x 60 x 18 + photo")
    L, W = 60.0, 58.0
    holes = [circ(sx * 26.6, sy * 25.6, 1.5, 20) for sx in (-1, 1) for sy in (-1, 1)]
    grid = [(-7.6 + 2.54 * c, 27.2 - 1.27 * r) for c in range(2) for r in range(6)]
    holes += [circ(x, y, 0.3, 8) for x, y in grid]
    P.plate('pcb_black', rrect(L, W, 1.2, 4), holes, T)
    for x, y in grid:
        P.lathe('gold', [(0.3, 0), (0.55, 0), (0.55, 0.04), (0.3, 0.04)], x, y, T, seg=12, closed=True)
    P.ecap(3.5, 23.2, 10.0, 10.5, 90)
    P.ecap(3.5, 12.6, 10.0, 10.5, 90)
    P.dc_jack(L / 2 + 0.6, 20.4, 0)
    P.jack35(-L / 2 - 0.2, 17.2, 180, bl=12.0, bw=6.2, bh=5.0, barrel=2.6)   # AUX in
    P.jack35(L / 2 + 0.2, 6.0, 0, bl=12.0, bw=6.2, bh=5.0, barrel=2.6)
    P.usb_a(-L / 2 - 0.5, -15.5, 180)
    P.screw_term(4, 26.2, -11.2, 90, pitch=5.08, depth=7.6, h=11.0, col='plastic_black')
    P.pot(0.0, 2.0, 0)
    with P.at(-14.8, W / 2 + 0.3, T, 90):           # self-locking push switch, plunger over the top edge
        P.box('plastic_grey', 7.4, 5.8, 5.8, -3.7, 0, 0, bev=0.2)
        P.box('plastic_white', 3.2, 3.2, 3.2, 1.0, 0, 1.3)
        P.box('plastic_white', 2.2, 5.2, 5.0, 3.5, 0, 0.4, bev=0.3)
    P.soic(-15.9, 1.0, 90, 8.65, 3.9, 1.5, 12, 0.635, 6.0, lw=0.25)   # Bluetooth SoC, SSOP-24
    P.soic(2.1, -15.4, 90, 9.7, 4.4, 1.0, 14, 0.65, 6.4, lw=0.25)     # amplifier, HTSSOP-28
    P.crystal(-16.8, -5.6, 0)
    P.sot223(-10.6, 18.0, 90)
    P.sma(-21.4, 24.6, 0)
    P.sma(11.8, 21.0, 90)
    P.sot23(-13.1, -10.9, 0)
    col_a = [('c', -5.8, -10.3 - 1.63 * i, 0) for i in range(7)]
    col_b = [('c', 8.0, y, 90, '0805') for y in (-10.3, -13.6, -17.3, -21.0)]
    col_c = [('l', 12.6, -7.6 - 2.15 * i, 0, '1206') for i in range(8)]
    col_d = [('c', 16.4, y, 90, '0805') for y in (-8.4, -12.6, -17.3, -21.5)]
    top = [('r', -26.8 + 2.3 * i, 10.4, 90) for i in range(7)]
    P.passives(col_a + col_b + col_c + col_d + top + [
        ('c', -0.4, -7.9, 0), ('c', -0.4, -9.5, 0), ('c', 2.6, -22.4, 0), ('c', 2.6, -24.0, 0), ('c', -22.7, 2.2, 0), ('c', -22.7, 0.4, 0),
        ('c', -21.6, -2.4, 0), ('r', -13.4, -8.6, 0), ('r', -15.6, -15.7, 90), ('r', -13.7, -15.7, 90), ('d', -22.4, -24.6, 0, '0805'),
        ('led', -27.6, 23.4, 90, '0805'), ('c', -12.6, 13.2, 0), ('r', -8.6, 11.6, 0), ('led', -8.4, 13.4, 0, '0805'),
        ('c', 12.5, 9.7, 0), ('c', 12.5, 5.8, 0), ('r', 20.7, 12.8, 0), ('r', 23.2, 1.2, 0), ('c', -7.4, 0.6, 0), ('c', -6.4, -1.2, 0),
        ('r', -27.0, 6.6, 0), ('r', -23.4, 6.6, 0), ('c', -3.6, 16.6, 90, '1206'),
    ])
    return P


def build_dcdc():
    """LM2596S + XL6009 step-up/step-down converter (Hestore STP28UD-3A), photo uploads/Device3.jpg."""
    P = Part("DCDC_StepUpDown", pcb_mm="60.5 x 37.2 x 1.6, 15.8 tall overall", source="Hestore prod_10038689 + photo")
    L, W = 60.5, 37.2
    holes = [circ(sx * 26.4, sy * 14.8, 1.55, 20) for sx in (-1, 1) for sy in (-1, 1)]
    P.plate('pcb_red', rrect(L, W, 3.6, 8), holes, T)
    P.inductor(-15.6, 8.6, 12.0, 7.0)
    P.inductor(17.4, 9.2, 12.0, 7.0)
    P.ecap(1.2, 5.6, 10.0, 10.5, 90)
    P.ecap(-19.2, -5.2, 6.3, 7.7, 90)
    P.ecap(19.6, -5.0, 6.3, 7.7, 90)
    P.to263(-9.1, -13.0, 0)     # LM2596S
    P.to263(10.6, -13.0, 0)     # XL6009
    P.screw_term(2, -L / 2 + 2.8, 0.4, -90, pitch=5.08, depth=7.6, h=10.0)
    P.screw_term(2, L / 2 - 2.8, 0.4, 90, pitch=5.08, depth=7.6, h=10.0)
    P.trimmer(0.6, W / 2 - 1.6, 0)
    P.sma(14.6, 16.2, 0)
    P.sma(-11.8, 16.2, 0)
    P.passives([
        ('r', 0.4, -9.2, 90, '0805'), ('r', 0.4, -15.6, 90, '0805'), ('c', -2.0, -9.6, 90, '0805'), ('r', 21.0, -13.4, 0, '0805'),
        ('r', 17.4, -15.8, 90, '0805'), ('led', 20.6, -16.2, 0, '0805'), ('c', -6.6, 14.6, 0, '1206'), ('c', 8.2, 10.6, 90, '1206'),
        ('c', -7.6, 9.0, 90, '1206'),
    ])
    return P


BUILDERS = [  # (builder, layout position in mm, beside the 190 mm casing)
    (build_esp32, (150, 60)),
    (build_click, (222, 60)),
    (build_pcm5102, (274, 60)),
    (build_sim868, (157, 15)),
    (build_dcdc, (246, 15)),
    (build_zk502m, (150, -52)),
    (build_speaker, (216, -52)),
    (build_geophone, (262, -52)),
]


def clear_previous():
    root = bpy.data.collections.get(ROOT)
    if root is None:
        return
    colls = [root] + list(root.children_recursive)
    for c in colls:
        for ob in list(c.objects):
            me = ob.data if ob.type == 'MESH' else None
            bpy.data.objects.remove(ob, do_unlink=True)
            if me is not None and me.users == 0:
                bpy.data.meshes.remove(me)
    for c in reversed(colls):
        bpy.data.collections.remove(c)


def build_all(scene=None):
    scene = scene or bpy.context.scene
    clear_previous()
    root = bpy.data.collections.new(ROOT)
    scene.collection.children.link(root)
    report = []
    for fn, loc in BUILDERS:
        part = fn()
        ob, bx, nverts = part.bake(root, loc)
        report.append("%-20s overall %6.1f x %5.1f x %5.1f mm   %6d verts" % (ob.name, bx[0], bx[1], bx[2], nverts))
    print("\n".join(report))
    return report


if __name__ == "__main__":
    build_all()
