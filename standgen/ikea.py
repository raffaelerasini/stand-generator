"""Istruzioni di montaggio illustrate (PDF A4, stile IKEA): pochi testi, disegni esplosi, frecce.

    from standgen.ikea import instructions_pdf
    instructions_pdf(stand, "istruzioni.pdf", title="Polyend Tracker+")

Pagine: copertina, pezzi stampati, ferramenta in scala 1:1, un passo per pagina, cambio angolo.
"""
import math

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, Circle, Polygon, Rectangle, FancyArrowPatch

from . import drawing as D
from . import hardware as hw
from .render import locked
from .cadlib import box

A4 = (8.27, 11.69)
MM = 1 / 25.4
INK = "#111111"


def _kind(length):
    for (k, l) in hw.SCREWS:
        if l == length:
            return k
    return "TCEI"


# ---------------------------------------------------------------- pagina e riquadri

def _page(pdf_pages, num=None, note=None):
    fig = plt.figure(figsize=A4)
    if num is not None:
        fig.text(0.07, 0.94, str(num), fontsize=54, fontweight="bold", color=INK, va="top")
    if note:
        fig.text(0.07, 0.035, note, fontsize=10, color="#444444", va="bottom", wrap=True)
    return fig


def _draw(fig, img, rect=(0.04, 0.08, 0.92, 0.66)):
    ax = fig.add_axes(rect)
    ax.imshow(img, cmap="gray", vmin=0, vmax=1, interpolation="lanczos")
    ax.set_axis_off()
    return ax


def _arrow(ax, view, p0, p1, shrink=4, lw=2.2):
    a, b = view.project(np.array([p0, p1], float))
    ax.add_patch(FancyArrowPatch(tuple(a), tuple(b), arrowstyle="-|>", mutation_scale=22, lw=lw,
                                 color=INK, shrinkA=shrink, shrinkB=shrink, zorder=5))


def _badge(fig, text, x=0.86, y=0.9):
    fig.text(x, y, text, fontsize=22, fontweight="bold", ha="center", va="center", color=INK,
             bbox=dict(boxstyle="circle,pad=0.45", fc="white", ec=INK, lw=2.5))


def _detail(fig, view, items, rect=(0.22, 0.085, 0.56, 0.27)):
    """riquadro di dettaglio ingrandito (lente): ritorna l'asse per le frecce"""
    fig.patches.append(FancyBboxPatch(rect[:2], rect[2], rect[3], boxstyle="round,pad=0.004,rounding_size=0.02",
                                      transform=fig.transFigure, fc="white", ec=INK, lw=1.6, figure=fig,
                                      zorder=-1))
    ax = fig.add_axes((rect[0] + 0.01, rect[1] + 0.01, rect[2] - 0.02, rect[3] - 0.02))
    ax.imshow(D.render(view, items), cmap="gray", vmin=0, vmax=1, interpolation="lanczos")
    ax.set_axis_off()
    return ax


_icon_cache = {}


def _icon(key, mesh):
    if key not in _icon_cache:
        v = D.View(az=240, el=30, width=360, height=240, ss=2)
        _icon_cache[key] = D.render(v, [(mesh, "new")])
    return _icon_cache[key]


def _hw_mesh(item):
    if item[0] == "screw":
        return D.screw(item[1], _kind(item[1])).rotate([0, 90, 0])
    if item[0] == "washer":
        return D.washer(item[1])
    return D.nut(nyloc=item[0] == "nyloc")


def _hw_label(item):
    if item[0] == "screw":
        return f"M5×{item[1]}"
    if item[0] == "washer":
        return f"rondella {item[1]:g}"
    return "dado M5" if item[0] == "nut" else "dado autobloccante"


def _callout(fig, entries, x0=0.30, y0=0.77, w=0.62, h=0.15):
    """riquadro con icone della ferramenta del passo: entries = [(item, quantità)]"""
    fig.patches.append(FancyBboxPatch((x0, y0), w, h, boxstyle="round,pad=0.006,rounding_size=0.015",
                                      transform=fig.transFigure, fc="white", ec=INK, lw=1.8, figure=fig, zorder=-1))
    n = len(entries)
    cw = w / max(n, 1)
    for i, (item, q) in enumerate(entries):
        cx = x0 + cw * i
        ax = fig.add_axes((cx + 0.01, y0 + 0.035, cw - 0.02, h - 0.045))
        ax.imshow(_icon(item, _hw_mesh(item)), cmap="gray", vmin=0, vmax=1)
        ax.set_axis_off()
        fig.text(cx + cw / 2, y0 + 0.012, f"{q}×  {_hw_label(item)}", ha="center", fontsize=10, color=INK)


# ---------------------------------------------------------------- geometria dei passi

def _deck_pt(s, p, a):
    """punto nel frame del ripiano -> mondo (come place_deck)"""
    t = math.radians(a)
    x, y, z = p
    return np.array([x * math.cos(t) - z * math.sin(t), y, x * math.sin(t) + z * math.cos(t) + s.Z_HINGE])


def _hinge_hw(s, y0=0.0, ex=0.0):
    half = s.W_OUT / 2
    z = s.Z_HINGE
    k = _kind(s.hinge_len)
    return [(D.along(D.screw(s.hinge_len, k), "-y", [0, y0 - half - 1 - ex, z]), "hw"),
            (D.along(D.washer(), "-y", [0, y0 - half - ex * 0.5, z]), "hw"),
            (D.along(D.nut(True), "+y", [0, y0 + half - s.HINGE_NUT_D + ex * 0.8, z]), "hw")]


def _pivot_hw(s, a, ex=0.0):
    """viteria del perno nel frame del ripiano, poi portata nel mondo"""
    hw_ = s.DECK_W / 2
    k = _kind(s.pivot_len)
    parts = [D.along(D.screw(s.pivot_len, k), "-y", [s.PIVOT_D, -hw_ - 1 - ex, 0]),
             D.along(D.washer(), "-y", [s.PIVOT_D, -hw_ - ex * 0.5, 0]),
             D.along(D.washer(), "+y", [s.PIVOT_D, hw_ + ex * 0.5, 0]),
             D.along(D.nut(True), "+y", [s.PIVOT_D, hw_ + 1 + ex * 0.8, 0])]
    return [(s.place_deck(m, a), "hw") for m in parts]


def _cb_hw(s, S, ex=0.0):
    """viti, rondelle e dadi delle traverse (alette interne, due basi a +-S/2)"""
    out = []
    k = _kind(s.BOLT_CB) if s.BOLT_CB else "TCEI"
    L = s.BOLT_CB or 16
    for cx in s.CB_X:
        for side in (-1, 1):
            y = side * (S / 2 - s.FL_Y)
            out += [(D.along(D.screw(L, k), "+z", [cx, y, s.FL_TOP + 1 + ex * 1.6]), "hw"),
                    (D.along(D.washer(), "+z", [cx, y, s.FL_TOP + ex * 0.8]), "hw"),
                    (D.along(D.nut(), "+z", [cx, y, 0.2 - ex * 0.9]), "hw")]
    return out


# ---------------------------------------------------------------- pagine

def _cover(pdf, s, title):
    base, deck, prop, bars = s.build_parts()
    a = s.ANGLES[-1]
    S = sum(s.SPACING_RANGE) / 2
    items = []
    for y in (-S / 2, S / 2):
        items += [(base.translate([0, y, 0]), "old"), (s.place_deck(deck, a).translate([0, y, 0]), "new"),
                  (s.place_prop(prop, a).translate([0, y, 0]), "new")]
    items += [(b.translate([cx, 0, 0]), "old") for cx in s.CB_X for b in bars]
    items.append((s.dev_box(a), "ghost"))
    fig = _page(pdf)
    fig.text(0.07, 0.93, "Supporto inclinabile", fontsize=30, fontweight="bold", color=INK, va="top")
    fig.text(0.07, 0.885, title, fontsize=16, color="#333333", va="top")
    fig.text(0.07, 0.855, "  ".join(f"{x:g}°" for x in s.ANGLES), fontsize=14, color="#333333", va="top")
    _draw(fig, D.render(D.View(width=1500, height=1100), items), (0.04, 0.25, 0.92, 0.58))
    # attrezzi
    fig.text(0.07, 0.19, "Ti servono", fontsize=13, fontweight="bold", color=INK)
    tools = ["chiave a brugola 4 mm", "chiave fissa o a tubo da 8 mm"]
    for i, t in enumerate(tools):
        fig.text(0.09, 0.16 - i * 0.028, "•  " + t, fontsize=12, color=INK)
    fig.text(0.07, 0.07, "Stampa i pezzi in PETG, 4 pareti, riempimento gyroid 30–40 %, senza supporti.\n"
                         "Le viti sono tutte M5 inox della scorta standard.", fontsize=10, color="#444444")
    pdf.savefig(fig)
    plt.close(fig)


def _parts_page(pdf, s):
    parts = s.print_parts()
    names = {"base": "base", "deck": "ripiano", "prop": "asta", "crossbar": "traversa",
             "crossbar_A": "traversa A", "crossbar_B": "traversa B"}
    fig = _page(pdf)
    fig.text(0.07, 0.94, "Pezzi da stampare", fontsize=22, fontweight="bold", color=INK, va="top")
    n = len(parts)
    cols = 2
    rows = math.ceil(n / cols)
    for i, (pn, m) in enumerate(parts.items()):
        r, c = divmod(i, cols)
        x0, y0 = 0.06 + c * 0.46, 0.86 - (r + 1) * (0.78 / rows)
        h = 0.78 / rows
        img = D.render(D.View(az=235, el=32, width=800, height=560), [(m, "new")])
        ax = fig.add_axes((x0, y0 + 0.04, 0.42, h - 0.06))
        ax.imshow(img, cmap="gray", vmin=0, vmax=1)
        ax.set_axis_off()
        base_name, _, q = pn.rpartition("_x")
        bb = m.bounding_box()
        fig.text(x0 + 0.01, y0 + h - 0.03, f"{q}×", fontsize=22, fontweight="bold", color=INK, va="top")
        fig.text(x0 + 0.21, y0 + 0.02, f"{names.get(base_name, base_name)}  ·  {pn}.stl\n"
                 f"{bb[3] - bb[0]:.0f} × {bb[4] - bb[1]:.0f} × {bb[5] - bb[2]:.0f} mm",
                 fontsize=9.5, ha="center", color="#333333")
    pdf.savefig(fig)
    plt.close(fig)


def _screw_side(ax, x, y, L, kind):
    """vite vista di lato, in mm, testa a sinistra; (x, y) = sotto testa, asse orizzontale"""
    if kind == "TE":
        ax.add_patch(Rectangle((x - 3.5, y - 4.6), 3.5, 9.2, fc="white", ec=INK, lw=1))
        for dy in (-1.55, 1.55):
            ax.plot([x - 3.5, x], [y + dy, y + dy], color=INK, lw=0.6)
    else:
        ax.add_patch(Rectangle((x - 5, y - 4.25), 5, 8.5, fc="white", ec=INK, lw=1))
    ax.add_patch(Rectangle((x, y - 2.5), L, 5, fc="white", ec=INK, lw=1))
    for t in np.arange(x + 1.5, x + L - 0.3, 0.8):
        ax.plot([t, t + 0.5], [y - 2.5, y + 2.5], color=INK, lw=0.35)


def _hardware_page(pdf, s):
    """ferramenta in scala 1:1 (stampa al 100 %)"""
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 210)
    ax.set_ylim(0, 297)
    ax.set_axis_off()
    ax.text(15, 280, "Ferramenta", fontsize=22, fontweight="bold", color=INK, va="top")
    ax.text(15, 268, "Scala 1:1: stampa al 100 % e appoggia le viti sul disegno per riconoscerle.",
            fontsize=10, color="#444444", va="top")
    y = 250
    for item, q, uses in s.bom().totals():
        code = item.code
        label = f"{q}×"
        if code.startswith("M5x"):
            L = float(code[3:].replace("TE", ""))
            _screw_side(ax, 40, y, L, "TE" if code.endswith("TE") else "TCEI")
            ax.text(15, y, label, fontsize=18, fontweight="bold", va="center", color=INK)
            ax.text(40 + L + 6, y, f"{item.name}\n{', '.join(dict.fromkeys(uses))}", fontsize=9, va="center",
                    color="#333333")
            y -= 22
        else:
            if "RONDELLA" in code:
                d = 20 if "5x20" in code else 10
                ax.add_patch(Circle((45, y), d / 2, fc="white", ec=INK, lw=1))
                ax.add_patch(Circle((45, y), 2.65, fc="white", ec=INK, lw=1))
            else:
                r = 8 / math.sqrt(3)
                pts = [(45 + r * math.cos(math.radians(30 + 60 * k)), y + r * math.sin(math.radians(30 + 60 * k)))
                       for k in range(6)]
                ax.add_patch(Polygon(pts, fc="white", ec=INK, lw=1))
                ax.add_patch(Circle((45, y), 2.5, fc="white", ec=INK, lw=1))
                if "NYLOC" in code:
                    ax.add_patch(Circle((45, y), 3.4, fc="none", ec=INK, lw=0.6, ls=":"))
            ax.text(15, y, label, fontsize=18, fontweight="bold", va="center", color=INK)
            ax.text(62, y, f"{item.name}\n{', '.join(dict.fromkeys(uses))}", fontsize=9, va="center",
                    color="#333333")
            y -= 20
    # righello di controllo
    ax.plot([15, 115], [18, 18], color=INK, lw=1.2)
    for t in range(0, 101, 10):
        ax.plot([15 + t, 15 + t], [18, 21 if t % 50 else 23], color=INK, lw=1)
    ax.text(15, 25, "controllo scala: 100 mm", fontsize=8, color="#444444")
    pdf.savefig(fig)
    plt.close(fig)


def _step_splice(pdf, s, num):
    bars = s.build_parts()[3]
    clip = box(-60, 60, -s.LAP - 25, s.LAP + 25, -60, 120)
    A, B = bars[0] ^ clip, bars[1] ^ clip
    ex = 45
    items = [(A, "new"), (B.translate([0, 0, ex]), "new")]
    for yb in (-s.LAP / 3, 0, s.LAP / 3):
        items.append((D.along(D.screw(s.splice_len, "TCEI"), "+z", [0, yb, s.splice_cb + ex * 2]), "hw"))
        items.append((D.along(D.nut(), "+z", [0, yb, -ex * 0.7]), "hw"))
    v = D.View(az=215, el=32)
    img = D.render(v, items)
    fig = _page(pdf, num, "Unisci le due metà di ogni traversa nella zona a mezzo legno: "
                          "dadi nelle sedi esagonali sotto, teste delle viti nelle lamature sopra.")
    ax = _draw(fig, img)
    _arrow(ax, v, [0, s.LAP / 2 + 20, s.CB_MID_H + ex], [0, s.LAP / 2 + 20, s.CB_MID_H + 4])
    for yb in (-s.LAP / 3, s.LAP / 3):
        _arrow(ax, v, [0, yb, s.splice_cb + ex * 2 - 6], [0, yb, s.CB_MID_H + ex + 4], lw=1.6)
        _arrow(ax, v, [0, yb, -ex * 0.7 - 3], [0, yb, -4], lw=1.6)
    for lab, m_ in (("A", A), ("B", B.translate([0, 0, ex]))):
        bb = m_.bounding_box()
        q = v.project(np.array([[bb[3] + 8, (bb[1] + bb[4]) / 2 + 45, (bb[2] + bb[5]) / 2]]))[0]
        ax.text(q[0], q[1], lab, fontsize=26, fontweight="bold", color=INK, ha="center", va="center")
    _callout(fig, [(("screw", s.splice_len), 3), (("nut",), 3)])
    _badge(fig, "2×", y=0.70)
    pdf.savefig(fig)
    plt.close(fig)


MAIN2 = (0.04, 0.37, 0.92, 0.39)       # disegno principale quando sotto c'è il dettaglio


def _step_bases(pdf, s, num):
    base, _, _, bars = s.build_parts()
    S = sum(s.SPACING_RANGE) / 2
    ex = 80
    items = [(b.translate([cx, 0, 0]), "old" if s.SPLIT else "new") for cx in s.CB_X for b in bars]
    items += [(base.translate([0, -S / 2 - ex, 0]), "new"), (base.translate([0, S / 2 + ex, 0]), "new")]
    v = D.View(az=205, el=35)
    img = D.render(v, items)
    fig = _page(pdf, num, "Infila le traverse nei tunnel delle due basi, una davanti e una dietro (sono uguali). "
                          "Le alette con il foro restano verso l'interno.")
    ax = _draw(fig, img)
    for sgn in (-1, 1):
        y_out = sgn * (S / 2 + ex - s.W_OUT / 2 - 8)
        for cx in s.CB_X:
            _arrow(ax, v, [cx, y_out, s.FL_TOP + 30], [cx, y_out - sgn * (ex - 15), s.FL_TOP + 30], lw=2.6)
    pdf.savefig(fig)
    plt.close(fig)


def _step_fix_bars(pdf, s, num):
    base, _, _, bars = s.build_parts()
    S = sum(s.SPACING_RANGE) / 2
    ex = 22
    items = [(b.translate([cx, 0, 0]), "old") for cx in s.CB_X for b in bars]
    items += [(base.translate([0, -S / 2, 0]), "old"), (base.translate([0, S / 2, 0]), "old")]
    items += _cb_hw(s, S, ex)
    v = D.View(az=205, el=40)
    img = D.render(v, items)
    lo, hi = s.SPACING_RANGE
    fig = _page(pdf, num, f"Dado nel canale sotto la traversa, vite con rondella dall'alto nell'aletta interna. "
                          f"Prima di stringere regola la distanza tra le basi: {lo:.0f}–{hi:.0f} mm "
                          f"(da centro a centro).")
    ax = _draw(fig, img, MAIN2)
    a, b = v.project(np.array([[-30, -S / 2, 0], [-30, S / 2, 0]]))
    ax.add_patch(FancyArrowPatch(tuple(a), tuple(b), arrowstyle="<|-|>", mutation_scale=16, lw=1.4, color=INK))
    m = (a + b) / 2
    ax.text(m[0], m[1] + 45, f"{lo:.0f}–{hi:.0f} mm", fontsize=13, fontweight="bold", ha="center", color=INK)
    # dettaglio: un'aletta
    cx, yt = s.CB_X[1], S / 2 - s.FL_Y
    clip = box(cx - s.SLOT_W / 2 - 16, cx + s.SLOT_W / 2 + 16, yt - 32, yt + 26, -40, 90)
    L = s.BOLT_CB or 16
    k = _kind(L)
    dz = 22
    det = [(base.translate([0, S / 2, 0]) ^ clip, "old")] + [(b.translate([cx, 0, 0]) ^ clip, "old") for b in bars]
    det += [(D.along(D.screw(L, k), "+z", [cx, yt, s.FL_TOP + 1 + dz * 1.5]), "hw"),
            (D.along(D.washer(), "+z", [cx, yt, s.FL_TOP + dz * 0.7]), "hw"),
            (D.along(D.nut(), "+z", [cx, yt, 0.2 - dz]), "hw")]
    dv = D.View(az=215, el=28, width=1100, height=740)
    dax = _detail(fig, dv, [(m_, st) for m_, st in det if not m_.is_empty()])
    _arrow(dax, dv, [cx, yt, s.FL_TOP + dz * 1.5 - 4], [cx, yt, s.FL_TOP + 3], lw=1.8)
    _arrow(dax, dv, [cx, yt, -dz + 2], [cx, yt, -2], lw=1.8)
    _callout(fig, [(("screw", L), 4), (("washer", 10), 4), (("nut",), 4)])
    pdf.savefig(fig)
    plt.close(fig)


def _step_deck(pdf, s, num):
    base, deck, _, _ = s.build_parts()
    a = s.ANGLES[0]
    ex = 45
    items = [(base, "old"), (s.place_deck(deck, a).translate([0, 0, ex]), "new")]
    v = D.View(az=230, el=28)
    img = D.render(v, items)
    fig = _page(pdf, num, "Appoggia il ripiano tra le pareti, davanti. Vite con rondella dal lato esterno, "
                          "dado autobloccante nella sede esagonale dall'altro lato. Stringi senza bloccare: "
                          "il ripiano deve ruotare.")
    ax = _draw(fig, img, MAIN2)
    z = s.Z_HINGE
    _arrow(ax, v, [0, 0, z + ex + 10], [0, 0, z + 8], lw=2.6)
    # dettaglio: cerniera
    half = s.W_OUT / 2
    clip = box(-25, 30, -half - 80, half + 80, -1, z + 22)
    det = [(base ^ clip, "old"), (s.place_deck(deck, a) ^ clip, "new")] + _hinge_hw(s, 0, 32)
    dv = D.View(az=235, el=22, width=1100, height=740)
    dax = _detail(fig, dv, det)
    _arrow(dax, dv, [0, -half - 34 - s.hinge_len * 0.0 - 6, z + 9], [0, -half - 4, z + 9], lw=1.8)
    _arrow(dax, dv, [0, half + 34, z + 9], [0, half + 3, z + 9], lw=1.8)
    _callout(fig, [(("screw", s.hinge_len), 1), (("washer", 10), 1), (("nyloc",), 1)])
    _badge(fig, "2×", y=0.70)
    pdf.savefig(fig)
    plt.close(fig)


def _step_prop(pdf, s, num):
    _, deck, prop, _ = s.build_parts()
    a = s.ANGLES[0]
    ex = 35
    P = s.pivot_pos(a)
    items = [(s.place_deck(deck, a), "old"), (s.place_prop(prop, a).translate([0, 0, -ex]), "new")]
    items += _pivot_hw(s, a, 40)
    v = D.View(az=315, el=24)
    img = D.render(v, items)
    fig = _page(pdf, num, "Metti l'asta nella forcella sul retro del ripiano e fissala con vite, "
                          "due rondelle e dado autobloccante. Anche qui l'asta deve ruotare libera.")
    ax = _draw(fig, img)
    hw_ = s.DECK_W / 2
    _arrow(ax, v, _deck_pt(s, [s.PIVOT_D, -hw_ - 40 - 12, 0], a), _deck_pt(s, [s.PIVOT_D, -hw_ - 5, 0], a))
    _arrow(ax, v, _deck_pt(s, [s.PIVOT_D, hw_ + 52, 0], a), _deck_pt(s, [s.PIVOT_D, hw_ + 5, 0], a))
    _arrow(ax, v, [P[0], 0, P[1] - ex - s.PIV_R - 3], [P[0], 0, P[1] - s.PIV_R - 4], lw=2.4)
    _callout(fig, [(("screw", s.pivot_len), 1), (("washer", 10), 2), (("nyloc",), 1)])
    _badge(fig, "2×", y=0.70)
    pdf.savefig(fig)
    plt.close(fig)


def _step_angles(pdf, s, num):
    base, deck, prop, _ = s.build_parts()
    fig = _page(pdf, num, "Per cambiare angolo solleva il retro dello strumento, sposta il piede dell'asta "
                          "nella tacca voluta (su entrambi i lati) e riabbassa.")
    n = len(s.ANGLES)
    v = D.View(az=270, el=0, width=1500, height=520)
    allpts = np.concatenate([D._mesh(m)[0] for a in s.ANGLES for m in
                             (base, s.place_deck(deck, a), s.place_prop(prop, a), s.dev_box(a))])
    v.fit(allpts, margin=0.03)
    h = 0.78 / n
    for i, a in enumerate(s.ANGLES):
        img = D.render(v, [(base, "old"), (s.place_deck(deck, a), "new"), (s.place_prop(prop, a), "new"),
                           (s.dev_box(a), "ghost")])
        y0 = 0.86 - (i + 1) * h
        ax = fig.add_axes((0.2, y0, 0.76, h * 0.95))
        ax.imshow(img, cmap="gray", vmin=0, vmax=1)
        ax.set_axis_off()
        fig.text(0.07, y0 + h / 2, f"{a:g}°", fontsize=30, fontweight="bold", va="center", color=INK)
    pdf.savefig(fig)
    plt.close(fig)


class _Out:
    """PdfPages che può anche salvare ogni pagina in PNG (anteprime / controllo)"""

    def __init__(self, pdf, png_prefix=None, dpi=70):
        self.pdf, self.prefix, self.dpi, self.n = pdf, png_prefix, dpi, 0
        self.pngs = []

    def savefig(self, fig):
        self.pdf.savefig(fig)
        self.n += 1
        if self.prefix:
            f = f"{self.prefix}{self.n:02d}.png"
            fig.savefig(f, dpi=self.dpi)
            self.pngs.append(f)

    def infodict(self):
        return self.pdf.infodict()


@locked
def instructions_pdf(s, path, title="", png_prefix=None):
    """scrive il PDF delle istruzioni per lo Stand s (png_prefix: salva anche le pagine in PNG)"""
    with PdfPages(path) as raw:
        pdf = _Out(raw, png_prefix)
        _cover(pdf, s, title)
        _parts_page(pdf, s)
        _hardware_page(pdf, s)
        num = 1
        if s.SPLIT and s.splice_len:
            _step_splice(pdf, s, num)
            num += 1
        for step in (_step_bases, _step_fix_bars, _step_deck, _step_prop, _step_angles):
            step(pdf, s, num)
            num += 1
        d = pdf.infodict()
        d["Title"] = f"Istruzioni di montaggio – {title}".strip(" –")
    return path
