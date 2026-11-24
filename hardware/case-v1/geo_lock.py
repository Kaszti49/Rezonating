"""Rezon geophone lock: lets both SM-24s stand free on the room floor, or lifts and clamps them.

DRAFT, not built yet. Plain Python prints the sizing sums; FreeCAD also builds the parts into the
new document "Rezon_geo_lock" (the open case_v1 document is never touched). Units: mm, origin as in case_v1.py.

Idea: a collar with 3 round pins clamps on each geophone (like the cam pins of a zoom lens).
  lower layer = cam ring: its ramps scoop under the pins and lift them
  upper layer = fixed cage: 3 inverted V notches that the pins seat in (centres the geophone in travel)
DEPLOY: pins float in the cage slots, the geophone stands on the room floor and touches nothing.
"""
import math
import os

G = dict(
    # geophone: SM-24 datasheet (I/O Sensor 2006): 25.4 x 32 mm, 74 g, max tilt 10 deg. MEASURE the real one.
    D=25.4, H=32.0, MASS=74.0, CABLE_TOP=43.0,
    HOLE_D=32.0,                       # floor hole (removes the old 30 mm cup)
    LIFT=2.5, FREE=1.5, SIDE=1.8,        # travel lift; free air under the pins; free air beside them (deployed)
    # collar
    COL_T=2.2, COL_Z0=14.0, COL_Z1=25.0, COL_INT=0.6, COL_SLIT=3.0, ZIP_W=2.7, ZIP_D=0.8,
    PIN_D=5.0, PIN_Z=20.0, PIN_R=22.7, PIN_A=(90.0, 210.0, 330.0),
    # cage (upper layer), printed upside down
    CAGE_RI=17.0, CAGE_RO=19.4, PILLAR=11.0, CAGE_TOP=30.0, FOOT_Z=9.0,
    # cam ring (lower layer)
    RING_RI=19.75, RING_RO=23.0, RING_Z0=12.0, LOW_Z=16.0,
    LOW_HALF=12.0, STEEP=24.0, STEEP_TOP=19.7, WEDGE=5.0, WEDGE_TOP=20.5, END=4.0,   # degrees / mm
    CRANK_R=32.0, LEVER_R=46.0, A_DEPLOY=28.0, ROT_MAX=58.0,
    MU=0.35,                           # PLA on PLA (assumed)
)
for _k, _v in G.items():
    globals()['g' + _k] = _v
RM = (gRING_RI + gRING_RO) / 2
PIN_SEAT = gPIN_Z + gLIFT                       # pin centre when clamped
APEX = PIN_SEAT + gPIN_D / 2 * math.sqrt(2)     # tip of the 90 deg V
SLOT_W = gPIN_D + 2 * gSIDE


def arc(mm, r=RM):
    return math.degrees(mm / r)


RAMP1 = arc((gSTEEP_TOP - gLOW_Z) / math.tan(math.radians(gSTEEP)))
RAMP2 = arc((gWEDGE_TOP - gSTEEP_TOP) / math.tan(math.radians(gWEDGE)))


def cam_z(a):
    """Cam height at a degrees ahead of the deployed pin."""
    a -= gLOW_HALF
    if a <= 0: return gLOW_Z
    if a <= RAMP1: return gLOW_Z + (gSTEEP_TOP - gLOW_Z) * a / RAMP1
    return min(gWEDGE_TOP, gSTEEP_TOP + (gWEDGE_TOP - gSTEEP_TOP) * (a - RAMP1) / RAMP2)


def pin_bottom(rot):
    """Highest pin position the cam forces at this ring rotation (round pin, so check the whole width)."""
    best = 0
    for i in range(-50, 51):
        x = gPIN_D / 2 * i / 50
        best = max(best, cam_z(rot + arc(x)) + math.sqrt((gPIN_D / 2) ** 2 - x * x))
    return best - gPIN_D / 2


def calc():
    out = []
    p = lambda s: out.append(s)
    ri = gD / 2
    gap_hole = (gHOLE_D - gD) / 2
    gap_cage = gCAGE_RI - ri - gCOL_T
    gap_v = (APEX - gPIN_Z) / math.sqrt(2) - gPIN_D / 2
    gap_low = gPIN_Z - gPIN_D / 2 - gLOW_Z
    p(f'Deployed free air: hole {gap_hole:.2f}, collar-cage {gap_cage:.2f}, pin sideways {(SLOT_W - gPIN_D) / 2:.2f}, '
      f'pin to V {gap_v:.2f}, pin to cam {gap_low:.2f}')
    # worst-case drift, height of the pins and of the floor hole
    print_, pos, centre, bump = 0.2, 0.2, 0.3, 0.5
    for name, z, gap in (('floor hole', 3.0, gap_hole), ('pins', gPIN_Z, min(gap_cage, (SLOT_W - gPIN_D) / 2))):
        tilt = z * math.tan(math.radians(1.0))
        lin = print_ + pos + centre + bump + tilt
        rss = math.sqrt(print_**2 + pos**2 + centre**2 + bump**2 + tilt**2)
        p(f'  {name}: worst-case sum {lin:.2f}, RSS {rss:.2f}, available {gap:.2f} -> {"OK" if gap > lin else ("OK by RSS only" if gap > rss else "TOO SMALL")}')
    W = gMASS / 1000 * 9.81
    E, w = 3000.0, gCOL_Z1 - gCOL_Z0
    I = w * gCOL_T ** 3 / 12
    dk = 1 / (ri - gCOL_INT / 2) - 1 / ri
    pr = E * I * dk / (2 * w * ri ** 2)
    N = pr * 2 * math.pi * ri * w
    p(f'Collar (C-ring, PLA E 3 GPa): strain {dk * gCOL_T / 2 * 100:.2f} %, grip {0.3 * N:.1f} N vs weight {W:.2f} N = {0.3 * N / W:.1f}x (before creep; add the zip tie)')
    rot = next((i / 10 for i in range(0, 900) if pin_bottom(i / 10) >= PIN_SEAT - gPIN_D / 2), None)
    p(f'Cam: first ramp {RAMP1:.1f} deg, wedge {RAMP2:.1f} deg; pins seat at {rot} deg, lever stop {gROT_MAX} deg')
    need = [pin_bottom(i / 10) for i in range(0, 900)]
    for d in (-0.3, 0.3):
        r2 = next((i / 10 for i, z in enumerate(need) if z >= PIN_SEAT - gPIN_D / 2 + d), None)
        p(f'  with {d:+.1f} mm print error: seats at {r2} deg')
    phi = math.degrees(math.atan(gMU))
    F = 1.1 * W * math.tan(math.radians(gSTEEP + phi))
    p(f'Lift: {F:.2f} N at the cam per geophone, {2 * F * RM / (gLEVER_R - 4):.2f} N at the lever for both; '
      f'wedge {gWEDGE} deg < friction angle {phi:.1f} deg -> {"self-locking" if gWEDGE < phi else "SLIPS"}')
    p(f'Stands by itself up to {math.degrees(math.atan(ri / (gH / 2))):.0f} deg (datasheet limit for its spec: 10 deg); '
      f'a pull of about {0.3 * W:.2f} N on the cable slides it (friction 0.3): leave a slack loop')
    p(f'Lifted in deploy: hangs on the cam, {gap_low:.2f} mm below the case; in travel {gLIFT:.1f} mm above the floor plane')
    p(f'Heights: cage top {gCAGE_TOP:.1f}, resistor top in travel {gCABLE_TOP + gLIFT:.1f}, lid underside 48.0 -> {48 - gCABLE_TOP - gLIFT:.1f} left; '
      f'V tip {APEX:.2f} leaves {gCAGE_TOP - APEX:.2f} mm of cage above it')
    y = 61.5 - 45.0
    a = 30 + arc(SLOT_W / 2, gCAGE_RO) + gPILLAR
    p(f'Board edge {y:.1f} from the geophone axis: cage reaches {gCAGE_RO * math.sin(math.radians(a)):.2f} towards it; '
      f'cam ring overhangs the board by {gRING_RO - y:.1f} at z {gRING_Z0} (board top 9.6)')
    return out


if __name__ == '__main__':
    print('\n'.join(calc()))
