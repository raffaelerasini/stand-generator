"""
Supporti inclinabili LOW PROFILE - generatore unico.

Profili:
  virus_ti       Access Virus TI/TI2 Desktop  470 x 188 x 81 mm, 3.5 kg   15/25/35/45 gradi
  tracker_plus   Polyend Tracker+             282 x 207 x 33 mm, 1.2 kg   5/10/15 gradi
  launchpad_pro  Novation Launchpad Pro MK3   268 x 268 x 18 mm, 1.0 kg   5/10/15 gradi

Per lato: base a U con tacche a gradini + ripiano incernierato a pochi mm dal tavolo
+ asta che ruota in una forcella del ripiano e scende nel canale della base.
Traverse che passano in due tunnel nelle pareti (centro e retro), fissate con una vite
nell'aletta interna della base. Davanti non c'è niente: la cerniera ruota libera.

python stand.py [profilo ...]   -> <profilo>/stl/*.stl
"""
import math, os, sys
import numpy as np
from manifold3d import CrossSection
from cadlib import (rect, circ, teardrop, xz_prism, xy_prism, box, vcyl, rot_y, vol, export_stl, bbox,
                   M5, CB_R, NUT_F)

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULTS = dict(
    ANGLES=[5, 10, 15], NOTCH_Z={5: 11.0, 10: 8.0, 15: 17.5},
    # base
    W_IN=28.0, W_WALL=8.0, FLOOR=3.0, Z_HINGE=11.0, BOSS_R=6.5, WALL_FRONT=12.0,
    NOTCH_R=4.3, MID_CB_X=45.0, FL_W=14.0, ROOF=3.0, FL_ROOF=4.0,
    # ripiano
    DECK_W=27.0, DECK_H=14.0, DECK_LEN=190.0, LIP_T=5.0, LIP_H=10.0, LIP_X0=None, PIVOT_D=160.0, FORK_GAP=11.0,
    # asta
    PROP_L=35.0, PROP_T=12.0, PROP_W=10.0, PIV_R=6.0, FOOT_R=4.0, FOOT_OFF=-2.0, EAR_W=40.0,
    # traverse
    CB_W=18.0, CB_H=10.0, CB_MID_H=10.0, LAP=50.0,
    # strumento
    DEV_W=282.0, DEV_D=207.0, DEV_H=33.0, SPACING_RANGE=(170.0, 200.0),
)

PROFILES = {
    "virus_ti": dict(
        DEV_W=470.0, DEV_D=188.0, DEV_H=81.0, SPACING_RANGE=(330.0, 390.0),
        ANGLES=[15, 25, 35, 45], NOTCH_Z={15: 12.0, 25: 10.0, 35: 18.0, 45: 29.0},
        Z_HINGE=13.0, BOSS_R=8.0, WALL_FRONT=14.0, NOTCH_R=5.3, MID_CB_X=40.0,
        DECK_H=18.0, LIP_T=8.0, LIP_H=16.0, LIP_X0=-5.0, PIVOT_D=100.0, FORK_GAP=13.0,
        PROP_L=55.0, PROP_T=14.0, PROP_W=12.0, PIV_R=7.0, FOOT_R=5.0, FOOT_OFF=-2.0, EAR_W=41.0,
        CB_W=24.0, CB_H=12.0, CB_MID_H=20.0),
    "tracker_plus": dict(DEV_W=282.0, DEV_D=207.0, DEV_H=33.0, LIP_H=10.0, SPACING_RANGE=(170.0, 200.0)),
    "launchpad_pro": dict(DEV_W=268.0, DEV_D=268.0, DEV_H=18.0, LIP_H=8.0, SPACING_RANGE=(160.0, 200.0)),
}

HARDWARE = {
    "virus_ti": ["2x M5x55 (cerniera)", "2x M5x40 (perno asta)", "4x dado autobloccante M5 + 8 rondelle",
                 "4x M5x25 + 4 dadi M5 + 4 rondelle (traverse, nell'aletta interna delle basi)", "6x M5x16 + 6 dadi M5 (giunzione traverse, 3 per traversa)"],
    "tracker_plus": ["2x M5x55 (cerniera)", "2x M5x35 (perno asta)", "4x dado autobloccante M5 + 8 rondelle",
                     "4x M5x20 + 4 dadi M5 + 4 rondelle (traverse, nell'aletta interna delle basi)"],
}
HARDWARE["launchpad_pro"] = HARDWARE["tracker_plus"]


def apply_profile(name):
    g = globals()
    g.update(DEFAULTS)
    g.update(PROFILES[name])
    g["W_OUT"] = W_IN + 2 * W_WALL
    if LIP_X0 is None:
        g["LIP_X0"] = -DECK_H / 2
    g["SLOT_W"], g["SLOT_H"] = CB_W + 0.6, CB_H + 0.4
    xs = [float(foot_pos(a)[0]) for a in ANGLES]
    g["NOTCHES"] = sorted((float(foot_pos(a)[0]), NOTCH_Z[a]) for a in ANGLES)
    rear_cx = max(xs) + NOTCH_R + 3 + SLOT_W / 2
    g["X_FRONT"] = -BOSS_R
    g["X_REAR"] = rear_cx + SLOT_W / 2 + 4
    g["CB_X"] = (MID_CB_X, rear_cx)
    g["FL_Y"] = W_OUT / 2 + FL_W / 2                  # vite traversa nell'aletta
    g["CB_END"] = SPACING_RANGE[1] / 2 + W_OUT / 2 + 2
    g["SPLIT"] = 2 * CB_END > 250


# ---------------- cinematica ----------------
def pivot_pos(theta):
    t = math.radians(theta)
    return np.array([PIVOT_D * math.cos(t), Z_HINGE + PIVOT_D * math.sin(t)])

def prop_angle(theta):
    P, zt = pivot_pos(theta), NOTCH_Z[theta]
    def fz(b):
        b = math.radians(b)
        return P[1] + PROP_L * math.sin(b) + FOOT_OFF * math.cos(b)
    lo, hi = -100.0, 0.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if fz(mid) > zt: hi = mid
        else: lo = mid
    return (lo + hi) / 2

def foot_pos(theta):
    P = pivot_pos(theta)
    b = math.radians(prop_angle(theta))
    return P + np.array([PROP_L * math.cos(b) - FOOT_OFF * math.sin(b),
                         PROP_L * math.sin(b) + FOOT_OFF * math.cos(b)])


# ---------------- parti ----------------
def make_base():
    tun_h = SLOT_H + ROOF
    prof = CrossSection.batch_hull([circ(0, Z_HINGE, BOSS_R), rect(-BOSS_R, 14, 0, WALL_FRONT - 4)])
    prof = prof + rect(-BOSS_R, X_REAR, 0, min(NOTCH_Z.values()))
    xs = [n[0] for n in NOTCHES]
    for i, (nx, nz) in enumerate(NOTCHES):
        x0 = (xs[i - 1] + nx) / 2 if i > 0 else nx - 12
        x1 = (xs[i + 1] + nx) / 2 if i < len(xs) - 1 else nx + 8
        prof = prof + rect(x0, x1, 0, nz)          # gradino piatto attorno alla tacca
    for cx in CB_X:                                 # pareti piene sopra i tunnel delle traverse
        prof = prof + rect(cx - SLOT_W / 2 - 4, cx + SLOT_W / 2 + 4, 0, tun_h)
    prof = prof + rect(CB_X[1] - SLOT_W / 2 - 4, X_REAR, 0, tun_h)
    for nx, nz in NOTCHES:
        prof = prof - circ(nx, nz, NOTCH_R)
    prof = prof - teardrop(0, Z_HINGE, M5)
    half = W_OUT / 2
    body = xz_prism(prof, -half, -W_IN / 2) + xz_prism(prof, W_IN / 2, half)
    body = body + box(-BOSS_R, X_REAR, -half, half, 0, FLOOR)
    # fondo aperto sotto le tacche (passaggio asta)
    body = body - box(min(xs) - 10, max(xs) + 6, -W_IN / 2, W_IN / 2, -1, FLOOR + 0.01)
    yo = half + FL_W
    for cx in CB_X:
        x0, x1 = cx - SLOT_W / 2 - 4, cx + SLOT_W / 2 + 4
        # alette laterali (vite della traversa) + tunnel passante
        body = body + box(x0, x1, -yo, -half + 0.01, 0, SLOT_H + FL_ROOF) \
                    + box(x0, x1, half - 0.01, yo, 0, SLOT_H + FL_ROOF)
        body = body - box(cx - SLOT_W / 2, cx + SLOT_W / 2, -yo - 1, yo + 1, -1, SLOT_H)
        for sy in (-FL_Y, FL_Y):
            body = body - vcyl(cx, sy, -1, 40, M5)
    return body

def bolt_heads():
    """ingombro delle teste delle viti delle traverse (solo per il controllo collisioni)"""
    m = None
    for cx in CB_X:
        for sy in (-FL_Y, FL_Y):
            c = vcyl(cx, sy, SLOT_H + FL_ROOF, SLOT_H + FL_ROOF + 6, 5.0)
            m = c if m is None else m + c
    return m

def make_deck():
    h = DECK_H / 2
    front = circ(0, 0, h) + CrossSection.batch_hull([rect(LIP_X0, LIP_X0 + LIP_T, 0, h + LIP_H), rect(0, LIP_X0 + LIP_T, -h, 0)])
    prof = front + rect(0, DECK_LEN - 4, -h, h) + CrossSection.batch_hull(
        [circ(DECK_LEN - 4, h - 4, 4), circ(DECK_LEN - 4, -h + 4, 4)])
    prof = prof - teardrop(0, 0, M5) - teardrop(PIVOT_D, 0, M5)
    deck = xz_prism(prof, -DECK_W / 2, DECK_W / 2)
    return deck - box(PIVOT_D - PIV_R - 18, DECK_LEN + 1, -FORK_GAP / 2, FORK_GAP / 2, -h - 1, h + 1)

def make_prop():
    t = PROP_T / 2
    bar = xz_prism(CrossSection.batch_hull([circ(0, 0, PIV_R), circ(PROP_L, FOOT_OFF, FOOT_R + 2)]),
                   -PROP_W / 2, PROP_W / 2)
    bar = bar ^ box(-30, PROP_L + 30, -50, 50, -t, t)
    ears = xz_prism(circ(PROP_L, FOOT_OFF, FOOT_R), -EAR_W / 2, EAR_W / 2)
    return (bar + ears) - xz_prism(teardrop(0, 0, M5), -30, 30)

def make_crossbars():
    """ritorna la lista delle parti traversa nel frame di montaggio (lunghezza lungo Y)"""
    s0, s1 = SPACING_RANGE[0] / 2, SPACING_RANGE[1] / 2
    end, hw = CB_END, CB_W / 2
    mid = s0 - W_OUT / 2 - FL_W - 3                     # parte alta tra le basi
    def slots(bar, ys_list):
        for ys in ys_list:
            sl = CrossSection.batch_hull([circ(0, ys[0], M5), circ(0, ys[1], M5)])
            bar = bar - xy_prism(sl, -1, CB_MID_H + 1)
            bar = bar - box(-NUT_F / 2, NUT_F / 2, ys[0] - 5, ys[1] + 5, -1, 4.2)
        return bar
    full = box(-hw, hw, -end, end, 0, CB_H) + box(-hw, hw, -mid, mid, 0, CB_MID_H)
    # la vite va nell'aletta interna: y = S/2 - FL_Y
    left, right = (-(s1 - FL_Y), -(s0 - FL_Y)), (s0 - FL_Y, s1 - FL_Y)
    if not SPLIT:
        return [slots(full, [left, right])]
    hl, H = LAP / 2, CB_MID_H
    A = (full ^ box(-50, 50, -end - 1, -hl, -1, 99)) + (full ^ box(-50, 50, -hl, hl, -1, H / 2))
    B = (full ^ box(-50, 50, hl, end + 1, -1, 99)) + (full ^ box(-50, 50, -hl, hl, H / 2, 99))
    A, B = slots(A, [left]), slots(B, [right])
    for yb in (-LAP / 3, 0, LAP / 3):
        A = A - vcyl(0, yb, -1, H + 1, M5) - xy_prism(CrossSection.circle(NUT_F / math.sqrt(3), 6).translate([0, yb]), -1, 4.2)
        B = B - vcyl(0, yb, -1, H + 1, M5) - vcyl(0, yb, H - 4, H + 1, CB_R)
    return [A, B]


# ---------------- assemblaggio ----------------
def place_deck(deck, a):
    return rot_y(deck, a).translate([0, 0, Z_HINGE])

def place_prop(prop, a):
    P = pivot_pos(a)
    return rot_y(prop, prop_angle(a)).translate([P[0], 0, P[1]])

def dev_box(a):
    x0 = LIP_X0 + LIP_T
    s = box(x0, x0 + DEV_D, -DEV_W / 2, DEV_W / 2, DECK_H / 2 + 0.01, DECK_H / 2 + DEV_H)
    return rot_y(s, a).translate([0, 0, Z_HINGE])

def build_parts(name):
    apply_profile(name)
    return make_base(), make_deck(), make_prop(), make_crossbars()


def build(name):
    base, deck, prop, bars = build_parts(name)
    out = os.path.join(HERE, name)
    os.makedirs(os.path.join(out, "stl"), exist_ok=True)
    for f in os.listdir(os.path.join(out, "stl")):
        os.remove(os.path.join(out, "stl", f))
    print(f"\n=== {name} ({DEV_W:.0f} x {DEV_D:.0f} x {DEV_H:.0f} mm) ===")
    ok = True
    for a in ANGLES:
        d, p, s = place_deck(deck, a), place_prop(prop, a), dev_box(a)
        sub = s ^ box(-500, 500, -W_OUT, W_OUT, -50, 500)
        res = {"deck/base": vol(d ^ base), "prop/base": vol(p ^ base), "prop/deck": vol(p ^ d),
               "dev/base": vol(sub ^ (base + bolt_heads())), "dev/prop": vol(sub ^ p),
               "deck/viti": vol(d ^ bolt_heads())}
        ok &= all(v < 0.01 for v in res.values())
        fx, fz = foot_pos(a)
        print(f"  {a:2d} deg: asta {abs(prop_angle(a)):.0f} deg, piede ({fx:.1f}, {fz:.1f}), collisioni",
              {k: round(v, 2) for k, v in res.items() if v > 0.01} or "nessuna")
    for S in SPACING_RANGE:
        bases = base.translate([0, -S / 2, 0]) + base.translate([0, S / 2, 0])
        allbars = bars[0] if len(bars) == 1 else bars[0] + bars[1]
        for cx in CB_X:
            ok &= vol(allbars.translate([cx, 0, 0]) ^ bases) < 0.01
        if len(bars) == 2:
            ok &= vol(bars[0] ^ bars[1]) < 0.01
    for a in ANGLES:
        allbars = bars[0] if len(bars) == 1 else bars[0] + bars[1]
        for cx in CB_X:
            ok &= vol(allbars.translate([cx, 0, 0]) ^ dev_box(a)) < 0.01
    for pn, m in (("base", base), ("deck", deck), ("prop", prop)) + tuple(("traversa", b) for b in bars):
        n = len(m.decompose())
        if n != 1:
            ok = False
            print(f"  !!! {pn} e' in {n} pezzi separati")
    xs = [n[0] for n in NOTCHES]
    print(f"  ingombro base: da {X_FRONT:.0f} a {X_REAR:.0f} mm = profondita' {X_REAR - X_FRONT:.0f} mm")
    print(f"  tacche x: {[round(x, 1) for x in xs]}  spaziatura min {min(np.diff(xs)):.1f} mm")
    print(f"  piano d'appoggio davanti a {Z_HINGE + DECK_H / 2:.0f} mm dal tavolo, bordino +{LIP_H:.0f} mm")
    print("  OK nessuna collisione" if ok else "  !!! COLLISIONI")
    parts = {"base_x2": base, "deck_x2": deck.translate([0, 0, DECK_H / 2]),
             "prop_x2": prop.translate([0, 0, PROP_T / 2])}
    if len(bars) == 1:
        parts["crossbar_x2"] = bars[0]
    else:
        parts["crossbar_A_x2"] = bars[0]
        parts["crossbar_B_x2"] = bars[1].rotate([180, 0, 0])   # stampata capovolta
    total = 0
    for pn, m in parts.items():
        b = m.bounding_box()
        m = m.translate([-b[0], -b[1], -b[2]])
        export_stl(m, os.path.join(out, "stl", f"{pn}.stl"))
        v = vol(m) / 1000
        total += 2 * v
        e = bbox(m)
        fits = "ok" if max(e[0], e[1]) <= 254 else "NON ENTRA"
        print(f"  {pn:14s} {np.round(e, 1)} mm  {v:5.1f} cm3  piatto: {fits}")
    print(f"  totale {total:.0f} cm3 (~{total * 1.27 * 0.6:.0f} g PETG)")
    return ok


if __name__ == "__main__":
    for n in (sys.argv[1:] or list(PROFILES)):
        build(n)
