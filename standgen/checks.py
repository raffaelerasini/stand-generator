"""Verifica di un supporto: collisioni a ogni angolo, pezzi interi, piatto, viti, tacche, stabilità."""
from dataclasses import dataclass, field

import numpy as np

from .cadlib import box, vol, bbox
from .model import BED

EPS = 0.01                 # mm³ di sovrapposizione tollerata
STAB_MIN = 15.0            # mm di margine minimo del baricentro davanti al bordo della base
BETA_RANGE = (20.0, 85.0)  # inclinazione accettabile dell'asta rispetto all'orizzontale
NOTCH_WALL = 3.0           # materiale minimo sotto una tacca


@dataclass
class Check:
    group: str
    label: str
    ok: bool
    detail: str = ""
    level: str = "error"          # "error" blocca, "warning" avvisa


@dataclass
class Report:
    checks: list = field(default_factory=list)
    info: dict = field(default_factory=dict)

    def add(self, *a, **k):
        self.checks.append(Check(*a, **k))

    @property
    def ok(self):
        return all(c.ok for c in self.checks if c.level == "error")

    def errors(self):
        return [c for c in self.checks if not c.ok and c.level == "error"]

    def warnings(self):
        return [c for c in self.checks if not c.ok and c.level == "warning"]

    def to_markdown(self):
        lines = [f"**Esito: {'OK' if self.ok else 'NON VALIDO'}**", ""]
        for c in self.checks:
            mark = "✅" if c.ok else ("❌" if c.level == "error" else "⚠️")
            lines.append(f"- {mark} **{c.group}** — {c.label}" + (f": {c.detail}" if c.detail else ""))
        return "\n".join(lines)


def _fmt(d):
    return ", ".join(f"{k} {v:.1f} mm³" for k, v in d.items())


def validate(s, quick=False):
    """s: Stand. quick=True salta i controlli che non dipendono dalle tacche (per il calcolo automatico)."""
    r = Report()
    base, deck, prop, bars = s.build_parts()
    heads = s.bolt_heads()
    allbars = bars[0] if len(bars) == 1 else bars[0] + bars[1]

    # --- viti dal catalogo ---
    if not quick:
        for e in s.screw_errors:
            r.add("Viti", "vite non disponibile nel catalogo standard", False, e)
        if not s.screw_errors:
            r.add("Viti", "tutte le viti sono nel catalogo standard", True,
                  f"cerniera M5×{s.hinge_len}, perno M5×{s.pivot_len}, traverse M5×{s.BOLT_CB}"
                  + (f", giunzione M5×{s.splice_len}" if s.SPLIT else ""))

    # --- tacche e asta ---
    xs = [n[0] for n in s.NOTCHES]
    gap_min = 2 * s.NOTCH_R + s.NOTCH_GAP
    gaps = np.diff(xs) if len(xs) > 1 else np.array([999.0])
    r.add("Tacche", f"distanza tra tacche ≥ {gap_min:.1f} mm", bool(gaps.min() >= gap_min - 1e-6),
          f"minima {gaps.min():.1f} mm")
    low = min(s.NOTCH_Z.values()) - s.NOTCH_R
    r.add("Tacche", f"materiale sotto le tacche ≥ {NOTCH_WALL:.0f} mm", low >= NOTCH_WALL - 1e-6,
          f"minimo {low:.1f} mm")
    bad = [f"{a}°: {abs(s.prop_angle(a)):.0f}°" for a in s.ANGLES
           if not BETA_RANGE[0] <= abs(s.prop_angle(a)) <= BETA_RANGE[1]]
    r.add("Tacche", f"asta inclinata tra {BETA_RANGE[0]:.0f}° e {BETA_RANGE[1]:.0f}°", not bad, ", ".join(bad))

    # --- collisioni a ogni angolo ---
    S_list = s.SPACING_RANGE
    for a in s.ANGLES:
        d, p, dv = s.place_deck(deck, a), s.place_prop(prop, a), s.dev_box(a)
        sub = dv ^ box(-500, 500, -s.W_OUT, s.W_OUT, -50, 500)
        res = {"ripiano/base": vol(d ^ base), "asta/base": vol(p ^ base), "asta/ripiano": vol(p ^ d),
               "strumento/base": vol(sub ^ (base + heads)), "strumento/asta": vol(sub ^ p),
               "ripiano/viti": vol(d ^ heads)}
        for cx in s.CB_X:
            b = allbars.translate([cx, 0, 0])
            res["strumento/traverse"] = res.get("strumento/traverse", 0) + vol(dv ^ b)
            for S in S_list:
                for sg in (-1, 1):                  # traversa vista da ciascun fianco
                    bl = b.translate([0, sg * S / 2, 0])
                    res["ripiano/traverse"] = res.get("ripiano/traverse", 0) + vol(d ^ bl)
                    res["asta/traverse"] = res.get("asta/traverse", 0) + vol(p ^ bl)
        bad = {k: v for k, v in res.items() if v > EPS}
        zmin = s.dev_box(a).bounding_box()[2]
        if zmin < 1:
            bad["strumento/tavolo"] = 0.0
        r.add("Collisioni", f"{a}°", not bad, _fmt(bad) if bad else "nessuna")

    if not quick:
        # --- traverse nelle basi ---
        bad = []
        for S in S_list:
            bases = base.translate([0, -S / 2, 0]) + base.translate([0, S / 2, 0])
            for cx in s.CB_X:
                v = vol(allbars.translate([cx, 0, 0]) ^ bases)
                if v > EPS:
                    bad.append(f"distanza {S:.0f}: {v:.1f} mm³")
        if len(bars) == 2 and vol(bars[0] ^ bars[1]) > EPS:
            bad.append("le due metà si sovrappongono")
        r.add("Collisioni", "traverse nei tunnel delle basi", not bad, "; ".join(bad))

        # --- pezzi interi e piatto ---
        for pn, m in s.print_parts().items():
            n = len(m.decompose())
            e = bbox(m)
            fits = max(e[0], e[1]) <= BED
            r.add("Pezzi", pn, n == 1 and fits,
                  f"{e[0]:.0f}×{e[1]:.0f}×{e[2]:.0f} mm"
                  + ("" if n == 1 else f", in {n} parti separate")
                  + ("" if fits else f", non entra nel piatto ({BED:.0f} mm)"))

    # --- ingombro ---
    depth = s.X_REAR - s.X_FRONT
    if s.MAX_DEPTH:
        r.add("Ingombro", f"profondità ≤ {s.MAX_DEPTH:.0f} mm", depth <= s.MAX_DEPTH + 1e-6, f"{depth:.0f} mm")

    # --- stabilità: baricentro dello strumento sopra la base ---
    margins = {a: float(s.dev_com(a)[0] - s.X_FRONT) for a in s.ANGLES}
    worst = min(margins, key=margins.get)
    m = margins[worst]
    r.add("Stabilità", "baricentro dentro l'appoggio", m > 0 and s.dev_com(worst)[0] < s.X_REAR,
          f"a {worst}° è {m:.0f} mm dietro il bordo anteriore")
    if m > 0:
        r.add("Stabilità", f"margine anti-ribaltamento ≥ {STAB_MIN:.0f} mm", m >= STAB_MIN,
              f"{m:.0f} mm a {worst}°", level="warning")

    if not quick:
        short = s.bom().shortages()
        r.add("Scorta", "ferramenta disponibile nella scorta", not short,
              ", ".join(f"{it.name}: servono {q}, scorta {it.stock}" for it, q in short), level="warning")
        r.info = summary(s)
    return r


def summary(s):
    parts = s.print_parts()
    cm3 = sum(2 * vol(m) / 1000 for m in parts.values())
    return {
        "profondita_mm": round(s.X_REAR - s.X_FRONT, 1),
        "piano_davanti_mm": round(s.Z_HINGE + s.DECK_H / 2, 1),
        "bordino_mm": s.LIP_H,
        "filamento_g": round(cm3 * 1.27 * 0.6),
        "tacche": [(round(x, 1), z) for x, z in s.NOTCHES],
        "asta_gradi": {a: round(abs(s.prop_angle(a)), 1) for a in s.ANGLES},
        "traversa_centrale_x": s.MID_CB_X,
        "pivot_d": s.PIVOT_D, "prop_l": s.PROP_L,
        "pezzi": {n: [round(v, 1) for v in bbox(m)] for n, m in parts.items()},
    }
