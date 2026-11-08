"""Geometria del supporto inclinabile low profile.

Per lato: base a U con tacche a gradini + ripiano incernierato a pochi mm dal tavolo
+ asta che ruota in una forcella del ripiano e scende nelle tacche della base.
Due traverse passano in tunnel nelle pareti (centro e retro) e si fissano con una vite
nell'aletta interna della base. Davanti non c'è niente: la cerniera ruota libera.

Tutto è in una classe `Stand` costruita da un dizionario di parametri: niente variabili
globali, quindi più generazioni possono girare insieme.
Assi: X verso il retro, Y di lato, Z in alto; la cerniera è in x = 0.
"""
import math
import numpy as np
from manifold3d import CrossSection

from .cadlib import rect, circ, teardrop, xz_prism, xy_prism, box, vcyl, rot_y, M5, CB_R, NUT_F
from . import hardware as hw

# ---------------- parametri ----------------
# strumento leggero (< HEAVY_KG)
LIGHT = dict(
    W_IN=28.0, W_WALL=8.0, FLOOR=3.0, Z_HINGE=None, BOSS_R=6.5, WALL_FRONT=12.0, HINGE_NUT_D=5.2,
    NOTCH_R=4.3, NOTCH_GAP=6.0, MID_CB_X=None, FL_W=14.0, ROOF=3.0, FL_ROOF_MIN=3.0, BOLT_CB=None,
    DECK_W=27.0, DECK_H=14.0, DECK_LEN=190.0, LIP_T=5.0, LIP_H=10.0, LIP_X0=None, PIVOT_D=160.0,
    FORK_GAP=11.0,
    PROP_L=35.0, PROP_T=12.0, PROP_W=10.0, PIV_R=6.0, FOOT_R=4.0, FOOT_OFF=-2.0, EAR_W=40.0,
    CB_W=18.0, CB_H=10.0, CB_MID_H=None, LAP=50.0,
)
# strumento pesante: pezzi più robusti
HEAVY = dict(
    BOSS_R=8.0, WALL_FRONT=14.0, NOTCH_R=5.3, DECK_H=18.0, LIP_T=8.0, FORK_GAP=13.0,
    PROP_T=14.0, PROP_W=12.0, PIV_R=7.0, FOOT_R=5.0, EAR_W=41.0,
    CB_W=24.0, CB_H=12.0, CB_MID_H=20.0, FL_ROOF_MIN=7.0,
)
HEAVY_KG = 2.0
DEVICE = dict(DEV_W=282.0, DEV_D=207.0, DEV_H=33.0, DEV_KG=1.2,
              ANGLES=[5, 10, 15], NOTCH_Z=None, SPACING_RANGE=None, MAX_DEPTH=None)
BED = 254.0                     # lato utile del piatto (Bambu A1 256)

PRESETS = {
    "virus_ti": dict(
        LABEL="Access Virus TI/TI2 Desktop",
        DEV_W=470.0, DEV_D=188.0, DEV_H=81.0, DEV_KG=3.5, SPACING_RANGE=(330.0, 390.0),
        ANGLES=[15, 25, 35, 45], NOTCH_Z={15: 12.0, 25: 10.0, 35: 18.0, 45: 29.0},
        LIP_H=30.0, LIP_X0=-5.0, PIVOT_D=100.0, PROP_L=55.0),
    "tracker_plus": dict(
        LABEL="Polyend Tracker+",
        DEV_W=282.0, DEV_D=207.0, DEV_H=33.0, DEV_KG=1.2, SPACING_RANGE=(170.0, 200.0),
        ANGLES=[5, 10, 15], NOTCH_Z={5: 11.0, 10: 8.0, 15: 17.5}, LIP_H=10.0),
    "launchpad_pro": dict(
        LABEL="Novation Launchpad Pro MK3",
        DEV_W=268.0, DEV_D=268.0, DEV_H=18.0, DEV_KG=1.0, SPACING_RANGE=(160.0, 200.0),
        ANGLES=[5, 10, 15], NOTCH_Z={5: 11.0, 10: 8.0, 15: 17.5}, LIP_H=8.0),
}

KNOWN = set(LIGHT) | set(DEVICE) | {"LABEL"}


def resolve_params(params):
    """unisce default leggero/pesante, strumento e parametri dati (None = automatico)."""
    params = dict(params)
    bad = set(params) - KNOWN
    if bad:
        raise ValueError(f"parametri sconosciuti: {sorted(bad)}")
    kg = params.get("DEV_KG", DEVICE["DEV_KG"])
    p = dict(LIGHT)
    if kg >= HEAVY_KG:
        p.update(HEAVY)
    p.update(DEVICE)
    p.update({k: v for k, v in params.items() if v is not None or k in ("NOTCH_Z",)})
    p["ANGLES"] = sorted(float(a) if a % 1 else int(a) for a in p["ANGLES"])
    if p["NOTCH_Z"] is not None:
        p["NOTCH_Z"] = {(int(a) if float(a) % 1 == 0 else float(a)): float(z) for a, z in p["NOTCH_Z"].items()}
    if p["SPACING_RANGE"] is None:
        p["SPACING_RANGE"] = default_spacing(p["DEV_W"])
    p["SPACING_RANGE"] = tuple(float(s) for s in p["SPACING_RANGE"])
    return p


def default_spacing(dev_w):
    """distanza tra i fianchi: circa 60-75 % della larghezza dello strumento."""
    s0 = round(dev_w * 0.62 / 5) * 5
    return (float(s0), float(s0 + 30))


# ---------------- cinematica (anche senza Stand, per il calcolo automatico) ----------------
def pivot_xz(theta, pivot_d, z_hinge):
    t = math.radians(theta)
    return np.array([pivot_d * math.cos(t), z_hinge + pivot_d * math.sin(t)])


def prop_beta(theta, nz, pivot_d, z_hinge, prop_l, foot_off):
    """angolo dell'asta (gradi, negativo = verso il basso) con il piede alla quota nz."""
    P = pivot_xz(theta, pivot_d, z_hinge)

    def fz(b):
        b = math.radians(b)
        return P[1] + prop_l * math.sin(b) + foot_off * math.cos(b)
    lo, hi = -100.0, 0.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if fz(mid) > nz:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def foot_xz(theta, nz, pivot_d, z_hinge, prop_l, foot_off):
    P = pivot_xz(theta, pivot_d, z_hinge)
    b = math.radians(prop_beta(theta, nz, pivot_d, z_hinge, prop_l, foot_off))
    return P + np.array([prop_l * math.cos(b) - foot_off * math.sin(b),
                         prop_l * math.sin(b) + foot_off * math.cos(b)])


class Stand:
    def __init__(self, params):
        p = resolve_params(params)
        if p["NOTCH_Z"] is None:
            raise ValueError("NOTCH_Z mancante: usa standgen.tune per calcolarlo")
        missing = [a for a in p["ANGLES"] if a not in p["NOTCH_Z"]]
        if missing:
            raise ValueError(f"manca la quota della tacca per gli angoli {missing}")
        self.params = p
        self.__dict__.update(p)
        self.W_OUT = self.W_IN + 2 * self.W_WALL
        if self.Z_HINGE is None:            # il ripiano a 0° resta 1 mm sopra il fondo
            self.Z_HINGE = self.FLOOR + self.DECK_H / 2 + 1
        if self.LIP_X0 is None:
            self.LIP_X0 = -self.DECK_H / 2
        self.SLOT_W, self.SLOT_H = self.CB_W + 0.6, self.CB_H + 0.4
        xs = [float(self.foot_pos(a)[0]) for a in self.ANGLES]
        self.NOTCHES = sorted((float(self.foot_pos(a)[0]), self.NOTCH_Z[a]) for a in self.ANGLES)
        rear_cx = max(xs) + self.NOTCH_R + 3 + self.SLOT_W / 2
        if self.MID_CB_X is None:
            self.MID_CB_X = self.auto_mid_cb_x()
        self.X_FRONT = -self.BOSS_R
        self.X_REAR = rear_cx + self.SLOT_W / 2 + 4
        self.CB_X = (self.MID_CB_X, rear_cx)
        # --- viti scelte dal catalogo (le eccezioni NoScrew finiscono nel resoconto) ---
        self.screw_errors = []
        self.hinge_len = self._pick(lambda: hw.shortest_at_least(self.W_OUT + hw.WASHER_T + 0.8, max_extra=8),
                                    "cerniera")
        self.pivot_len = self._pick(lambda: hw.shortest_at_least(
            self.DECK_W + 2 * hw.WASHER_T + hw.NYLOC_H + 1, max_extra=8), "perno asta")
        if self.BOLT_CB is None:            # aletta: tunnel + tetto minimo, punta a filo sotto
            self.BOLT_CB = self._pick(lambda: hw.shortest_at_least(
                self.SLOT_H + self.FL_ROOF_MIN + 0.5), "traverse") or 16
        else:
            self._pick(lambda: (self.BOLT_CB, hw.screw_by_length(self.BOLT_CB)), "traverse")
        self.FL_TOP = self.BOLT_CB - 0.5
        self.FL_Y = self.W_OUT / 2 + self.FL_W / 2
        self.CB_END = self.SPACING_RANGE[1] / 2 + self.W_OUT / 2 + 2
        self.SPLIT = 2 * self.CB_END > 250
        if self.CB_MID_H is None:           # in due pezzi serve altezza per la giunzione (M5x16 + lamatura)
            self.CB_MID_H = 20.0 if self.SPLIT else self.CB_H
        self.splice_len = None
        if self.SPLIT:                      # giunzione a mezzo legno: lamatura >= 3 mm
            self.splice_len = self._pick(lambda: hw.longest_at_most(self.CB_MID_H - 3), "giunzione traverse")
        self.splice_cb = self.splice_len or 16          # quota della sede testa (punta a filo sotto)

    def _pick(self, fn, use):
        try:
            return fn()[0]
        except hw.NoScrew as e:
            self.screw_errors.append(f"{use}: {e}")
            return None

    def auto_mid_cb_x(self):
        """traversa centrale il più avanti possibile, ma col ripiano (all'angolo minimo)
        almeno 1 mm sopra la traversa per tutta la larghezza del tunnel."""
        a = math.radians(min(self.ANGLES))
        h = self.DECK_H / 2
        x0 = (self.CB_H + 1 - self.Z_HINGE + h * math.cos(a)) / math.tan(a) + h * math.sin(a)
        return max(math.ceil(x0 + self.SLOT_W / 2), self.BOSS_R + self.SLOT_W / 2 + 6)

    # ---------------- cinematica ----------------
    def pivot_pos(self, theta):
        return pivot_xz(theta, self.PIVOT_D, self.Z_HINGE)

    def prop_angle(self, theta):
        return prop_beta(theta, self.NOTCH_Z[theta], self.PIVOT_D, self.Z_HINGE, self.PROP_L, self.FOOT_OFF)

    def foot_pos(self, theta):
        return foot_xz(theta, self.NOTCH_Z[theta], self.PIVOT_D, self.Z_HINGE, self.PROP_L, self.FOOT_OFF)

    # ---------------- parti ----------------
    def make_base(self):
        s = self
        tun_h = s.SLOT_H + s.ROOF
        prof = CrossSection.batch_hull([circ(0, s.Z_HINGE, s.BOSS_R), rect(-s.BOSS_R, 14, 0, s.WALL_FRONT - 4)])
        prof = prof + rect(-s.BOSS_R, s.X_REAR, 0, min(s.NOTCH_Z.values()))
        xs = [n[0] for n in s.NOTCHES]
        for i, (nx, nz) in enumerate(s.NOTCHES):
            x0 = (xs[i - 1] + nx) / 2 if i > 0 else nx - 12
            x1 = (xs[i + 1] + nx) / 2 if i < len(xs) - 1 else nx + 8
            prof = prof + rect(x0, x1, 0, nz)          # gradino piatto attorno alla tacca
        for cx in s.CB_X:                               # pareti piene sopra i tunnel delle traverse
            prof = prof + rect(cx - s.SLOT_W / 2 - 4, cx + s.SLOT_W / 2 + 4, 0, tun_h)
        prof = prof + rect(s.CB_X[1] - s.SLOT_W / 2 - 4, s.X_REAR, 0, tun_h)
        for nx, nz in s.NOTCHES:
            prof = prof - circ(nx, nz, s.NOTCH_R)
        prof = prof - teardrop(0, s.Z_HINGE, M5)
        half = s.W_OUT / 2
        body = xz_prism(prof, -half, -s.W_IN / 2) + xz_prism(prof, s.W_IN / 2, half)
        body = body + box(-s.BOSS_R, s.X_REAR, -half, half, 0, s.FLOOR)
        # sede esagonale per l'autobloccante della cerniera (lato +Y)
        nut = CrossSection.circle(NUT_F / math.sqrt(3), 6).translate([0, s.Z_HINGE])
        body = body - xz_prism(nut, half - s.HINGE_NUT_D, half + 1)
        # fondo aperto sotto le tacche (passaggio asta)
        body = body - box(min(xs) - 10, max(xs) + 6, -s.W_IN / 2, s.W_IN / 2, -1, s.FLOOR + 0.01)
        yo = half + s.FL_W
        for cx in s.CB_X:
            x0, x1 = cx - s.SLOT_W / 2 - 4, cx + s.SLOT_W / 2 + 4
            # alette laterali (vite della traversa) + tunnel passante
            body = body + box(x0, x1, -yo, -half + 0.01, 0, s.FL_TOP) \
                        + box(x0, x1, half - 0.01, yo, 0, s.FL_TOP)
            body = body - box(cx - s.SLOT_W / 2, cx + s.SLOT_W / 2, -yo - 1, yo + 1, -1, s.SLOT_H)
            for sy in (-s.FL_Y, s.FL_Y):
                body = body - vcyl(cx, sy, -1, 40, M5)
        return body

    def bolt_heads(self):
        """ingombro delle teste delle viti delle traverse (solo per il controllo collisioni)"""
        m = None
        for cx in self.CB_X:
            for sy in (-self.FL_Y, self.FL_Y):
                c = vcyl(cx, sy, self.FL_TOP, self.FL_TOP + 6, 5.0)
                m = c if m is None else m + c
        return m

    def make_deck(self):
        s = self
        h = s.DECK_H / 2
        front = circ(0, 0, h) + CrossSection.batch_hull(
            [rect(s.LIP_X0, s.LIP_X0 + s.LIP_T, 0, h + s.LIP_H), rect(0, s.LIP_X0 + s.LIP_T, -h, 0)])
        prof = front + rect(0, s.DECK_LEN - 4, -h, h) + CrossSection.batch_hull(
            [circ(s.DECK_LEN - 4, h - 4, 4), circ(s.DECK_LEN - 4, -h + 4, 4)])
        prof = prof - teardrop(0, 0, M5) - teardrop(s.PIVOT_D, 0, M5)
        deck = xz_prism(prof, -s.DECK_W / 2, s.DECK_W / 2)
        return deck - box(s.PIVOT_D - s.PIV_R - 18, s.DECK_LEN + 1, -s.FORK_GAP / 2, s.FORK_GAP / 2, -h - 1, h + 1)

    def make_prop(self):
        s = self
        t = s.PROP_T / 2
        bar = xz_prism(CrossSection.batch_hull([circ(0, 0, s.PIV_R), circ(s.PROP_L, s.FOOT_OFF, s.FOOT_R + 2)]),
                       -s.PROP_W / 2, s.PROP_W / 2)
        bar = bar ^ box(-30, s.PROP_L + 30, -50, 50, -t, t)
        ears = xz_prism(circ(s.PROP_L, s.FOOT_OFF, s.FOOT_R), -s.EAR_W / 2, s.EAR_W / 2)
        return (bar + ears) - xz_prism(teardrop(0, 0, M5), -30, 30)

    def make_crossbars(self):
        """lista delle parti traversa nel frame di montaggio (lunghezza lungo Y)"""
        s = self
        s0, s1 = s.SPACING_RANGE[0] / 2, s.SPACING_RANGE[1] / 2
        end, hw_ = s.CB_END, s.CB_W / 2
        mid = s0 - s.W_OUT / 2 - s.FL_W - 3                     # parte alta tra le basi

        def slots(bar, ys_list):
            for ys in ys_list:
                sl = CrossSection.batch_hull([circ(0, ys[0], M5), circ(0, ys[1], M5)])
                bar = bar - xy_prism(sl, -1, s.CB_MID_H + 1)
                bar = bar - box(-NUT_F / 2, NUT_F / 2, ys[0] - 5, ys[1] + 5, -1, 4.2)
            return bar
        full = box(-hw_, hw_, -end, end, 0, s.CB_H) + box(-hw_, hw_, -mid, mid, 0, s.CB_MID_H)
        # la vite va nell'aletta interna: y = S/2 - FL_Y
        left, right = (-(s1 - s.FL_Y), -(s0 - s.FL_Y)), (s0 - s.FL_Y, s1 - s.FL_Y)
        if not s.SPLIT:
            return [slots(full, [left, right])]
        hl, H = s.LAP / 2, s.CB_MID_H
        A = (full ^ box(-50, 50, -end - 1, -hl, -1, 99)) + (full ^ box(-50, 50, -hl, hl, -1, H / 2))
        B = (full ^ box(-50, 50, hl, end + 1, -1, 99)) + (full ^ box(-50, 50, -hl, hl, H / 2, 99))
        A, B = slots(A, [left]), slots(B, [right])
        for yb in (-s.LAP / 3, 0, s.LAP / 3):
            A = A - vcyl(0, yb, -1, H + 1, M5) - xy_prism(
                CrossSection.circle(NUT_F / math.sqrt(3), 6).translate([0, yb]), -1, 4.2)
            B = B - vcyl(0, yb, -1, H + 1, M5) - vcyl(0, yb, s.splice_cb, H + 1, CB_R)
        return [A, B]

    def build_parts(self):
        if not hasattr(self, "_parts"):
            self._parts = (self.make_base(), self.make_deck(), self.make_prop(), self.make_crossbars())
        return self._parts

    # ---------------- assemblaggio ----------------
    def place_deck(self, deck, a):
        return rot_y(deck, a).translate([0, 0, self.Z_HINGE])

    def place_prop(self, prop, a):
        P = self.pivot_pos(a)
        return rot_y(prop, self.prop_angle(a)).translate([P[0], 0, P[1]])

    def dev_box(self, a):
        x0 = self.LIP_X0 + self.LIP_T
        s = box(x0, x0 + self.DEV_D, -self.DEV_W / 2, self.DEV_W / 2,
                self.DECK_H / 2 + 0.01, self.DECK_H / 2 + self.DEV_H)
        return rot_y(s, a).translate([0, 0, self.Z_HINGE])

    def dev_com(self, a):
        """baricentro dello strumento (scatola uniforme) nel piano XZ"""
        x0 = self.LIP_X0 + self.LIP_T
        u, w = x0 + self.DEV_D / 2, self.DECK_H / 2 + self.DEV_H / 2
        t = math.radians(a)
        return np.array([u * math.cos(t) - w * math.sin(t), self.Z_HINGE + u * math.sin(t) + w * math.cos(t)])

    def print_parts(self):
        """pezzi orientati per la stampa (nome -> Manifold), appoggiati in z = 0"""
        base, deck, prop, bars = self.build_parts()
        parts = {"base_x2": base, "deck_x2": deck.translate([0, 0, self.DECK_H / 2]),
                 "prop_x2": prop.translate([0, 0, self.PROP_T / 2])}
        if len(bars) == 1:
            parts["crossbar_x2"] = bars[0]
        else:
            parts["crossbar_A_x2"] = bars[0]
            parts["crossbar_B_x2"] = bars[1].rotate([180, 0, 0])   # stampata capovolta
        out = {}
        for n, m in parts.items():
            b = m.bounding_box()
            out[n] = m.translate([-b[0], -b[1], -b[2]])
        return out

    def bom(self):
        """ferramenta per un supporto completo (due fianchi)"""
        b = hw.Bom()
        if self.hinge_len:
            b.add(hw.screw_by_length(self.hinge_len), 2, "cerniera")
        b.add(hw.NYLOC, 2, "cerniera")
        if self.pivot_len:
            b.add(hw.screw_by_length(self.pivot_len), 2, "perno asta")
        b.add(hw.NYLOC, 2, "perno asta")
        b.add(hw.WASHER, 2, "cerniera")
        b.add(hw.WASHER, 4, "perno asta")
        if self.BOLT_CB:
            b.add(hw.screw_or_missing(self.BOLT_CB), 4, "traverse")
        b.add(hw.NUT, 4, "traverse")
        b.add(hw.WASHER, 4, "traverse")
        if self.SPLIT and self.splice_len:
            b.add(hw.screw_by_length(self.splice_len), 6, "giunzione traverse")
            b.add(hw.NUT, 6, "giunzione traverse")
        return b
