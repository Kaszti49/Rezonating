"""Printable divider walls around the placed Rezon parts.

Runs inside Blender on the open mockup. Reads where the parts in "Rezon_Parts" currently are, so it can be
re-run after moving a part. Creates one object, "Part_Walls", in the collection "Rezon_Walls".
Never modifies Base, Lid or the parts.

How the wall is made (all in mm, scene is 1 unit = 1 m):
  footprint  = convex outline of everything a part occupies, seen from above
  pocket     = footprint grown by CLEAR         (stays empty: nothing printed here)
  fence      = footprint grown by CLEAR + WALL
  wall       = all fences joined, cut back to the inside of the casing, minus every pocket,
               minus a slot in front of each plug / screw terminal so cables can still get in
Straight vertical sides, flat top, no overhangs: prints without supports.
"""
import bpy
import bmesh
from math import atan2, cos, sin, pi, hypot, radians, ceil
from mathutils import Vector

MM = 0.001
PARTS = "Rezon_Parts"
OUT_COLL = "Rezon_Walls"
OUT_NAME = "Part_Walls"

CLEAR = 1.0        # gap between a part and its wall
WALL = 1.6         # wall thickness = 4 lines of a 0.4 mm nozzle
HEIGHT_FRAC = 0.5  # wall top = this fraction of the base height
EMBED = 0.2        # wall starts this far inside the floor so it fuses with the base when printed together
MIN_PRINT = 0.8    # thinner than 2 lines is reported as a weak spot
MIN_STUB_AREA = 12.0  # mm2 seen from above: loose wall stubs smaller than this are removed
CONNECT = True     # join all wall pieces into one with short connector walls
RIB_CLEAR = 0.4    # a connector keeps at least this far from every pocket (so it stays >= 1.2 mm thick)
CORRIDOR = 6.0     # free space kept in front of a wire slot (wires bend up and over): connectors never cross it
PLUG = 40.0        # free space kept in front of a jack / USB slot (rigid plug): in practice all the way to the casing
DROP_UNREACHABLE = True  # a wall piece that could only be joined by blocking a plug is removed (and reported)

# Cable slots, in each part's own coordinates: (x, y) on the footprint edge, outward direction, slot width.
SLOTS = {  # (x, y, dir x, dir y, width, free corridor length)
    "ESP32-S3_DevKit": [(32.5, 0.0, 1, 0, 22.0, PLUG)],                                        # two USB-C ports
    "ADC15_Click": [(21.45, -0.8, 1, 0, 21.0, CORRIDOR)],                                      # geophone screw terminals
    "PCM5102A_DAC": [(-19.1, 3.4, -1, 0, 9.0, PLUG), (24.1, 1.27, 1, 0, 17.0, CORRIDOR)],      # line-out jack, 6-pin header
    "DCDC_StepUpDown": [(-31.25, 0.4, -1, 0, 13.0, CORRIDOR), (31.25, 0.4, 1, 0, 13.0, CORRIDOR)],  # IN and OUT terminals
    "ZK-502M_Amp": [(30.6, 1.5, 1, 0, 49.0, CORRIDOR), (-32.8, 17.2, -1, 0, 9.0, PLUG)],       # power + speaker side, AUX in
}


# ---------------- 2D helpers ----------------
def convex_hull(pts):
    pts = sorted(set((round(x, 4), round(y, 4)) for x, y in pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]   # counter-clockwise


def simplify(h, min_turn=radians(0.6), min_len=0.05):
    out = list(h)
    changed = True
    while changed and len(out) > 3:
        changed = False
        for i in range(len(out)):
            a, b, c = out[i - 1], out[i], out[(i + 1) % len(out)]
            l1, l2 = hypot(b[0] - a[0], b[1] - a[1]), hypot(c[0] - b[0], c[1] - b[1])
            if l1 < min_len:
                del out[i]
                changed = True
                break
            turn = abs(atan2((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]), (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])))
            if turn < min_turn and l1 < 2.0 and l2 < 2.0 and False:
                del out[i]
                changed = True
                break
    return out


def offset(h, d, step=radians(9)):
    """Grow a counter-clockwise convex polygon by d with round corners (still convex)."""
    n = len(h)
    out = []
    for i in range(n):
        p0, p1, p2 = h[i - 1], h[i], h[(i + 1) % n]
        a0 = atan2(-(p1[0] - p0[0]), (p1[1] - p0[1]))  # angle of outward normal of edge p0->p1: (dy, -dx)
        a0 = atan2(-(p1[0] - p0[0]), p1[1] - p0[1])
        n0 = (p1[1] - p0[1], -(p1[0] - p0[0]))
        n1 = (p2[1] - p1[1], -(p2[0] - p1[0]))
        a0, a1 = atan2(n0[1], n0[0]), atan2(n1[1], n1[0])
        while a1 < a0:
            a1 += 2 * pi
        k = max(1, int(ceil((a1 - a0) / step)))
        for j in range(k + 1):
            a = a0 + (a1 - a0) * j / k
            out.append((p1[0] + d * cos(a), p1[1] + d * sin(a)))
    return simplify(out, min_len=0.02)


def poly_gap(A, B):
    """Distance between two convex polygons (0 if they overlap)."""
    def sep(P, Q):
        best = -1e9
        for i in range(len(P)):
            a, b = P[i], P[(i + 1) % len(P)]
            nx, ny = b[1] - a[1], -(b[0] - a[0])
            l = hypot(nx, ny) or 1.0
            best = max(best, min(((q[0] - a[0]) * nx + (q[1] - a[1]) * ny) / l for q in Q))
        return best
    if max(sep(A, B), sep(B, A)) <= 0:
        return 0.0

    def pt_seg(p, a, b):
        vx, vy = b[0] - a[0], b[1] - a[1]
        t = max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / ((vx * vx + vy * vy) or 1.0)))
        return hypot(p[0] - a[0] - t * vx, p[1] - a[1] - t * vy)
    d = 1e9
    for P, Q in ((A, B), (B, A)):
        for p in P:
            for i in range(len(Q)):
                d = min(d, pt_seg(p, Q[i], Q[(i + 1) % len(Q)]))
    return d


def inside(q, P):
    """Point strictly inside a counter-clockwise convex polygon."""
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        if (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0]) <= 0:
            return False
    return True


def crossings(A, B):
    """Points where the outlines of A and B cross, with the unit edge directions there."""
    out = []
    for i in range(len(A)):
        a0, a1 = A[i], A[(i + 1) % len(A)]
        rx, ry = a1[0] - a0[0], a1[1] - a0[1]
        for j in range(len(B)):
            b0, b1 = B[j], B[(j + 1) % len(B)]
            sx, sy = b1[0] - b0[0], b1[1] - b0[1]
            den = rx * sy - ry * sx
            if abs(den) < 1e-12:
                continue
            u = ((b0[0] - a0[0]) * sy - (b0[1] - a0[1]) * sx) / den
            v = ((b0[0] - a0[0]) * ry - (b0[1] - a0[1]) * rx) / den
            if 0 <= u < 1 and 0 <= v < 1:
                lr, ls = hypot(rx, ry), hypot(sx, sy)
                out.append((a0[0] + u * rx, a0[1] + u * ry, (rx / lr, ry / lr), (sx / ls, sy / ls)))
    return out


def pt_seg(p, a, b):
    """Distance from point p to segment a-b, and the closest point."""
    vx, vy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / ((vx * vx + vy * vy) or 1.0)))
    q = (a[0] + t * vx, a[1] + t * vy)
    return hypot(p[0] - q[0], p[1] - q[1]), q


def seg_hit(p, q, a, b):
    def o(u, v, w):
        return (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])
    return (o(p, q, a) > 0) != (o(p, q, b) > 0) and (o(a, b, p) > 0) != (o(a, b, q) > 0)


def seg_poly_dist(p, q, P):
    """Distance from segment p-q to a counter-clockwise convex polygon (0 if they touch or cross)."""
    if inside(p, P) or inside(q, P):
        return 0.0
    d = 1e9
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        if seg_hit(p, q, a, b):
            return 0.0
        d = min(d, pt_seg(p, a, b)[0], pt_seg(q, a, b)[0], pt_seg(a, p, q)[0], pt_seg(b, p, q)[0])
    return d


def top_outline(comp, z_top):
    """Outline of one wall piece seen from above, as 2D segments in mm."""
    segs, done = [], set()
    for v in comp:
        for e in v.link_edges:
            if e.index in done:
                continue
            done.add(e.index)
            a, b = e.verts
            if abs(a.co.z / MM - z_top) > 0.01 or abs(b.co.z / MM - z_top) > 0.01:
                continue
            if any(abs(f.normal.z) < 0.5 for f in e.link_faces):
                segs.append(((a.co.x / MM, a.co.y / MM), (b.co.x / MM, b.co.y / MM)))
    return segs


def route_connectors(outlines, pockets, corridors, info):
    """Shortest connector paths that join every wall piece into one.

    Works on a 0.5 mm grid of the casing floor. A connector may not come closer to a pocket than its own half
    width + RIB_CLEAR, and may not cross the free corridor in front of a cable slot. Returns a list of polylines.
    """
    import heapq
    import numpy as np
    step = 0.5
    R, cx, cy = info["r_in"], info["cx"], info["cy"]
    n = int(ceil(2 * R / step)) + 4
    x0, y0 = cx - n * step / 2, cy - n * step / 2
    c = (np.arange(n) + 0.5) * step
    X, Y = np.meshgrid(x0 + c, y0 + c)

    def mask(poly):
        m = np.ones((n, n), dtype=bool)
        for i in range(len(poly)):
            ax, ay = poly[i]
            bx, by = poly[(i + 1) % len(poly)]
            m &= ((bx - ax) * (Y - ay) - (by - ay) * (X - ax)) >= 0
        return m

    blocked = (X - cx) ** 2 + (Y - cy) ** 2 > (R - WALL / 2) ** 2
    for P in pockets:
        blocked |= mask(offset(P, WALL / 2 + RIB_CLEAR + 0.2))
    for P in corridors:
        blocked |= mask(offset(P, WALL / 2))
    blocked = blocked.tolist()

    def cell(pt):
        return (int((pt[1] - y0) / step), int((pt[0] - x0) / step))

    # places on each piece's outline where a connector may attach
    attach = [dict() for _ in outlines]
    for k, segs in enumerate(outlines):
        for a, b in segs:
            l = hypot(b[0] - a[0], b[1] - a[1])
            m = max(1, int(l / 0.25))
            for i in range(m + 1):
                pt = (a[0] + (b[0] - a[0]) * i / m, a[1] + (b[1] - a[1]) * i / m)
                iy, ix = cell(pt)
                if 0 <= iy < n and 0 <= ix < n and not blocked[iy][ix]:
                    attach[k].setdefault((iy, ix), pt)

    blockers = list(pockets) + list(corridors)

    def clear(a, b):
        return all(seg_poly_dist(a, b, P) >= WALL / 2 for P in blockers)

    order = sorted(range(len(outlines)), key=lambda k: -len(outlines[k]))
    joined = {order[0]}
    sources = dict(attach[order[0]])
    paths, failed = [], []
    nb = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142))
    while len(joined) < len(outlines):
        targets = {}
        for k in range(len(outlines)):
            if k not in joined:
                for cl, pt in attach[k].items():
                    targets.setdefault(cl, (k, pt))
        dist, prev, heap = {}, {}, []
        for cl in sources:
            dist[cl] = 0.0
            heap.append((0.0, cl))
        heapq.heapify(heap)
        hit = None
        while heap:
            d, cl = heapq.heappop(heap)
            if d > dist.get(cl, 1e18):
                continue
            if cl in targets:
                hit = cl
                break
            for dy, dx, w in nb:
                iy, ix = cl[0] + dy, cl[1] + dx
                if not (0 <= iy < n and 0 <= ix < n) or blocked[iy][ix]:
                    continue
                nd = d + w
                if nd < dist.get((iy, ix), 1e18):
                    dist[(iy, ix)] = nd
                    prev[(iy, ix)] = cl
                    heapq.heappush(heap, (nd, (iy, ix)))
        if hit is None:
            failed = [k for k in range(len(outlines)) if k not in joined]
            break
        k, end_pt = targets[hit]
        cells = [hit]
        while cells[-1] in prev:
            cells.append(prev[cells[-1]])
        cells.reverse()
        pts = [(x0 + (ix + 0.5) * step, y0 + (iy + 0.5) * step) for iy, ix in cells]
        pts[0] = sources[cells[0]]
        if len(pts) == 1:
            pts.append(end_pt)
            cells.append(cells[0])
        pts[-1] = end_pt
        # straighten: keep only the corners that are needed
        line, i = [pts[0]], 0
        while i < len(pts) - 1:
            j = len(pts) - 1
            while j > i + 1 and not clear(pts[i], pts[j]):
                j -= 1
            line.append(pts[j])
            i = j
        if len(line) >= 2 and hypot(line[-1][0] - line[0][0], line[-1][1] - line[0][1]) > 1e-4:
            paths.append(line)
        joined.add(k)
        sources.update(attach[k])
        for cl, pt in zip(cells, pts):
            sources.setdefault(cl, pt)
    return paths, failed


# ---------------- scene reading ----------------
def base_info():
    base = bpy.data.objects["Base"]
    ws = [base.matrix_world @ v.co for v in base.data.vertices]
    zs = sorted(set(round(w.z / MM, 2) for w in ws))
    top = zs[-1]
    floor = zs[1] if len(zs) > 2 else zs[0]
    r_in = min(hypot(w.x, w.y) / MM for w in ws if abs(w.z / MM - top) < 0.01)
    cx = sum(w.x for w in ws) / len(ws) / MM
    cy = sum(w.y for w in ws) / len(ws) / MM
    return {"z0": zs[0], "floor": floor, "top": top, "r_in": r_in, "cx": cx, "cy": cy}


def read_parts():
    parts = []
    for coll in bpy.data.collections[PARTS].children:
        empties = [o for o in coll.objects if o.type == 'EMPTY']
        pts = []
        for o in coll.objects:
            if o.type != 'MESH':
                continue
            mw = o.matrix_world
            for v in o.data.vertices:
                w = mw @ v.co
                pts.append((w.x / MM, w.y / MM))
        if not pts:
            continue
        parts.append({"name": coll.name, "hull": simplify(convex_hull(pts)), "empty": empties[0] if empties else None})
    return parts


# ---------------- 3D helpers ----------------
def prism_mesh(name, poly, z0, z1):
    bm = bmesh.new()
    lo = [bm.verts.new((x * MM, y * MM, z0 * MM)) for x, y in poly]
    hi = [bm.verts.new((x * MM, y * MM, z1 * MM)) for x, y in poly]
    bm.faces.new(list(reversed(lo)))
    bm.faces.new(hi)
    n = len(poly)
    for i in range(n):
        bm.faces.new((lo[i], lo[(i + 1) % n], hi[(i + 1) % n], hi[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def circle(cx, cy, r, n=180):
    return [(cx + r * cos(2 * pi * i / n), cy + r * sin(2 * pi * i / n)) for i in range(n)]


def build():
    scene = bpy.context.scene
    info = base_info()
    parts = read_parts()
    z_bot = info["floor"] - EMBED
    z_top = info["z0"] + (info["top"] - info["z0"]) * HEIGHT_FRAC
    log = []
    log.append("Base: floor top z=%.1f, rim z=%.1f, inner radius %.2f  ->  wall z %.1f..%.1f (%.1f mm above the floor), %.1f thick, %.1f clearance"
               % (info["floor"], info["top"], info["r_in"], z_bot, z_top, z_top - info["floor"], WALL, CLEAR))

    for p in parts:
        p["pocket"] = offset(p["hull"], CLEAR)
        p["fence"] = offset(p["hull"], CLEAR + WALL)
        far = max(hypot(x - info["cx"], y - info["cy"]) for x, y in p["hull"])
        if far > info["r_in"] - 0.05:
            log.append("  ! %s reaches %.2f mm from the centre: it touches / enters the casing wall (inner radius %.2f)" % (p["name"], far, info["r_in"]))
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            g = poly_gap(parts[i]["hull"], parts[j]["hull"])
            if g < 2 * CLEAR + WALL + 4:
                if g <= 0:
                    note = "OVERLAP seen from above: no wall can go between them"
                elif g < 2 * CLEAR:
                    note = "closer than 2 x clearance: no wall between them at the closest point"
                elif g < 2 * CLEAR + MIN_PRINT:
                    note = "wall thinner than %.1f mm at the closest point" % MIN_PRINT
                else:
                    note = "wall %.1f mm at the closest point" % min(g - 2 * CLEAR, 2 * WALL)
                log.append("  %-18s - %-18s gap %5.2f mm: %s" % (parts[i]["name"], parts[j]["name"], g, note))

    # cable slots -> world rectangles
    slots = []
    corridors = []
    for p in parts:
        e = p["empty"]
        for (lx, ly, dx, dy, w, free) in SLOTS.get(p["name"], []):
            if e is None:
                continue
            m = e.matrix_world @ Vector((lx * MM, ly * MM, 0))
            d = (e.matrix_world.to_3x3() @ Vector((dx, dy, 0)))
            d = Vector((d.x, d.y)).normalized()
            t = Vector((-d.y, d.x))
            c = Vector((m.x / MM, m.y / MM))
            reach = [(Vector(h) - c).dot(d) for h in p["hull"] if abs((Vector(h) - c).dot(t)) <= w / 2 + CLEAR + WALL]
            a, b = -1.5, max(reach + [0.0]) + CLEAR + WALL + 1.0
            slots.append([tuple(c + d * a - t * w / 2), tuple(c + d * b - t * w / 2), tuple(c + d * b + t * w / 2), tuple(c + d * a + t * w / 2)])
            b2 = b + free
            corridors.append([tuple(c + d * a - t * w / 2), tuple(c + d * b2 - t * w / 2), tuple(c + d * b2 + t * w / 2), tuple(c + d * a + t * w / 2)])

    # where two pockets cross, the wall between them tapers to a knife edge: cut the tip back to MIN_PRINT width
    blunts = []
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            A, B = parts[i]["pocket"], parts[j]["pocket"]
            if poly_gap(A, B) > 0:
                continue
            for x, y, ti, tj in crossings(A, B):
                best = None
                for bx, by in ((ti[0] + tj[0], ti[1] + tj[1]), (-ti[0] - tj[0], -ti[1] - tj[1]), (ti[0] - tj[0], ti[1] - tj[1]), (tj[0] - ti[0], tj[1] - ti[1])):
                    l = hypot(bx, by)
                    if l < 1e-9:
                        continue
                    q = (x + 0.05 * bx / l, y + 0.05 * by / l)
                    if not inside(q, A) and not inside(q, B):
                        best = (bx / l, by / l)
                        break
                if best is None:
                    continue
                half = abs(atan2(best[0] * ti[1] - best[1] * ti[0], best[0] * ti[0] + best[1] * ti[1]))
                half = min(half, pi - half)
                rho = min(10.0, MIN_PRINT / (2 * max(sin(half), 0.04)))
                blunts.append((x, y, rho))
                log.append("  tip between %s and %s at (%.1f, %.1f) trimmed back %.1f mm" % (parts[i]["name"], parts[j]["name"], x, y, rho))

    # ---- boolean build on temporary objects ----
    tmp = bpy.data.collections.new("_rz_wall_tmp")
    scene.collection.children.link(tmp)
    add_c = bpy.data.collections.new("_rz_wall_add")
    cut_c = bpy.data.collections.new("_rz_wall_cut")
    tmp.children.link(add_c)
    tmp.children.link(cut_c)
    made = []

    def obj(name, me, coll):
        o = bpy.data.objects.new(name, me)
        coll.objects.link(o)
        made.append(o)
        return o

    seed = obj("_rz_seed", prism_mesh("_rz_seed", parts[0]["fence"], z_bot, z_top), tmp)
    for p in parts[1:]:
        obj("_rz_f_" + p["name"], prism_mesh("_rz_f", p["fence"], z_bot, z_top), add_c)
    for p in parts:
        obj("_rz_p_" + p["name"], prism_mesh("_rz_p", p["pocket"], z_bot - 2, z_top + 2), cut_c)
    for k, s in enumerate(slots):
        obj("_rz_s_%d" % k, prism_mesh("_rz_s", s, z_bot - 2, z_top + 2), cut_c)
    for k, (x, y, rho) in enumerate(blunts):
        obj("_rz_b_%d" % k, prism_mesh("_rz_b", circle(x, y, rho, 48), z_bot - 2, z_top + 2), cut_c)
    clip = obj("_rz_clip", prism_mesh("_rz_clip", circle(info["cx"], info["cy"], info["r_in"] + 0.3), z_bot - 3, z_top + 3), tmp)

    m1 = seed.modifiers.new("u", 'BOOLEAN'); m1.operation = 'UNION'; m1.operand_type = 'COLLECTION'; m1.collection = add_c; m1.solver = 'EXACT'
    m2 = seed.modifiers.new("i", 'BOOLEAN'); m2.operation = 'INTERSECT'; m2.operand_type = 'OBJECT'; m2.object = clip; m2.solver = 'EXACT'
    m3 = seed.modifiers.new("d", 'BOOLEAN'); m3.operation = 'DIFFERENCE'; m3.operand_type = 'COLLECTION'; m3.collection = cut_c; m3.solver = 'EXACT'
    def evaluate():
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(seed.evaluated_get(dg), depsgraph=dg)
        bm = bmesh.new()
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-6)
        bmesh.ops.dissolve_limit(bm, angle_limit=radians(0.2), verts=bm.verts[:], edges=bm.edges[:])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        # split into connected pieces and drop stubs too small to print well
        bm.verts.index_update()
        seen, pieces = set(), []
        for v in bm.verts:
            if v.index in seen:
                continue
            comp, stack = [], [v]
            while stack:
                u = stack.pop()
                if u.index in seen:
                    continue
                seen.add(u.index)
                comp.append(u)
                stack.extend(e.other_vert(u) for e in u.link_edges)
            pieces.append(comp)
        keep, dropped = [], 0
        for comp in pieces:
            faces = set(f for u in comp for f in u.link_faces)
            vol = abs(sum(f.calc_center_median().dot(f.normal) * f.calc_area() for f in faces) / 3.0) / MM ** 3
            if vol / (z_top - z_bot) < MIN_STUB_AREA:
                bmesh.ops.delete(bm, geom=comp, context='VERTS')
                dropped += 1
            else:
                keep.append((vol, comp))
        return bm, keep, dropped

    bm, keep, dropped = evaluate()
    first_count = len(keep)

    # ---- connector walls: shortest routes that join every piece, never through a pocket or a cable corridor ----
    n_ribs = 0
    if CONNECT and len(keep) > 1:
        bm.edges.index_update()
        outlines = [top_outline(comp, z_top) for vol, comp in keep]
        paths, failed = route_connectors(outlines, [q["pocket"] for q in parts], corridors, info)
        for line in paths:
            total = 0.0
            for k in range(len(line) - 1):
                a, b = line[k], line[k + 1]
                d = hypot(b[0] - a[0], b[1] - a[1])
                if d < 1e-6:
                    continue
                total += d
                ux, uy = (b[0] - a[0]) / d, (b[1] - a[1]) / d
                ea = 0.6 if k == 0 else 0.0
                eb = 0.6 if k == len(line) - 2 else 0.0
                a2 = (a[0] - ux * ea, a[1] - uy * ea)
                b2 = (b[0] + ux * eb, b[1] + uy * eb)
                nx, ny = -uy * WALL / 2, ux * WALL / 2
                rib = [(a2[0] - nx, a2[1] - ny), (b2[0] - nx, b2[1] - ny), (b2[0] + nx, b2[1] + ny), (a2[0] + nx, a2[1] + ny)]
                obj("_rz_r_%d_%d" % (n_ribs, k), prism_mesh("_rz_r", rib, z_bot, z_top), add_c)
                if k > 0:
                    obj("_rz_j_%d_%d" % (n_ribs, k), prism_mesh("_rz_j", circle(a[0], a[1], WALL / 2, 24), z_bot, z_top), add_c)
            n_ribs += 1
            log.append("  connector wall %d: %.1f mm long, %d straight run(s), from (%.1f, %.1f) to (%.1f, %.1f)"
                       % (n_ribs, total, len(line) - 1, line[0][0], line[0][1], line[-1][0], line[-1][1]))
        if failed:
            log.append("  ! %d piece(s) could not be reached without crossing a pocket or a cable corridor" % len(failed))
        if n_ribs:
            bm.free()
            bm, keep, dropped = evaluate()

    for o in made:
        me = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if me.users == 0:
            bpy.data.meshes.remove(me)
    for c in (add_c, cut_c, tmp):
        bpy.data.collections.remove(c)

    removed = 0
    if CONNECT and DROP_UNREACHABLE and len(keep) > 1:
        keep.sort(key=lambda k: -k[0])
        for vol, comp in keep[1:]:
            xs = [v.co.x / MM for v in comp]
            ys = [v.co.y / MM for v in comp]
            log.append("  removed a loose wall piece, about %.0f x %.0f mm, centred at (%.1f, %.1f): joining it would block a plug"
                       % (max(xs) - min(xs), max(ys) - min(ys), (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2))
            bmesh.ops.delete(bm, geom=comp, context='VERTS')
            removed += 1
        keep = keep[:1]
    islands = len(keep)
    non_manifold = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    volume = bm.calc_volume() / MM ** 3
    result = bpy.data.meshes.new(OUT_NAME)
    bm.to_mesh(result)
    nv, nf = len(bm.verts), len(bm.faces)
    bm.free()
    result.name = OUT_NAME

    # ---- replace the previous wall object ----
    coll = bpy.data.collections.get(OUT_COLL)
    if coll is None:
        coll = bpy.data.collections.new(OUT_COLL)
        scene.collection.children.link(coll)
    for o in list(coll.objects):
        me = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if me and me.users == 0:
            bpy.data.meshes.remove(me)
    ob = bpy.data.objects.new(OUT_NAME, result)
    coll.objects.link(ob)
    mat = bpy.data.materials.get("RZ_wall_print")
    if mat is None:
        mat = bpy.data.materials.new("RZ_wall_print")
        mat.diffuse_color = (0.18, 0.56, 0.54, 1.0)
        mat.roughness = 0.6
    result.materials.clear()
    result.materials.append(mat)
    ob["wall_mm"] = "thickness %.1f, clearance %.1f, z %.1f..%.1f" % (WALL, CLEAR, z_bot, z_top)

    log.append("Part_Walls: %d verts, %d faces, %d separate piece(s) (was %d before %d connector walls; %d tiny stubs removed), volume %.1f cm3, open/non-manifold edges: %d"
               % (nv, nf, islands, first_count, n_ribs, dropped, volume / 1000.0, non_manifold))
    log.append("Cable slots cut: %d" % len(slots))
    print("\n".join(log))
    return ob


if __name__ == "__main__":
    build()
