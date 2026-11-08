"""Uscite per il sito: disegni "blueprint" (tratto chiaro su fondo trasparente) e mesh per il visore 3D.

I disegni nascono dal rasterizzatore di `drawing.py`: le linee diventano chiare, le facce grafite
semitrasparenti, lo strumento è solo un contorno grigio. Le mesh per il browser sono JSON compatti:
vertici e triangoli di ogni pezzo più gli spigoli vivi già calcolati (piega > 25°).
"""
import math

import numpy as np
from PIL import Image

from . import drawing as D

LINE = np.array([0.91, 0.925, 0.945])          # #E8ECF1
ACCENT = np.array([1.0, 0.416, 0.169])         # #FF6A2B
SURF = np.array([0.110, 0.129, 0.157])         # #1C2128
SURF_OLD = np.array([0.078, 0.090, 0.110])
GHOST = np.array([0.49, 0.53, 0.58])
LIGHT = (-0.3, -0.5, 0.8)


def _colorize(view, items, accent=()):
    """items: [(Manifold, stile)] con stile new/old/ghost -> immagine RGBA uint8"""
    solid = [it for it in items if it[1] != "ghost"]
    ghost = [it for it in items if it[1] == "ghost"]
    if view.scale is None:
        view.fit(np.concatenate([D._mesh(m)[0] for m, _ in items]))
    rgb = np.zeros((view.H, view.W, 3))
    a = np.zeros((view.H, view.W))
    if solid:
        s = D._render(view, solid, LIGHT)
        g, al = s[..., 0], s[..., 3]
        line = np.clip(1 - g / 0.7, 0, 1)
        old = (g > 0.8) & (g < 0.9)
        face = np.where(old[..., None], SURF_OLD, SURF)
        col = np.broadcast_to(LINE, rgb.shape)
        if accent:
            sa = D._render(view, [solid[i] for i in accent], LIGHT)
            col = np.where((sa[..., 3] > 0.5)[..., None], ACCENT, LINE)
        rgb = face * (1 - line[..., None]) + col * line[..., None]
        a = al * np.maximum(0.9, line)
    if ghost:
        gg = D._render(view, ghost, LIGHT)
        gl = np.clip((1 - gg[..., 0]) * gg[..., 3] / 0.4, 0, 1) * 0.8
        rgb = rgb * (1 - gl[..., None]) + GHOST * gl[..., None]
        a = np.maximum(a, gl)
    img = np.dstack([rgb, a])
    return Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8), "RGBA")


def _assembly_items(s, a, ghost=True):
    base, deck, prop, bars = s.build_parts()
    S = sum(s.SPACING_RANGE) / 2
    items = []
    for y in (-S / 2, S / 2):
        items += [(base.translate([0, y, 0]), "old"), (s.place_deck(deck, a).translate([0, y, 0]), "new"),
                  (s.place_prop(prop, a).translate([0, y, 0]), "new")]
    items += [(b.translate([cx, 0, 0]), "old") for cx in s.CB_X for b in bars]
    if ghost:
        items.append((s.dev_box(a), "ghost"))
    return items


def hero(s, path, angle=None):
    """assonometria dell'assemblato con lo strumento a contorno"""
    a = angle if angle is not None else s.ANGLES[-1]
    _colorize(D.View(az=225, el=26, width=1600, height=1100), _assembly_items(s, a)).save(path, optimize=True)
    return path


def side(s, path, angle):
    """profilo sinistro a un angolo; la scala è la stessa per tutti gli angoli (si possono sovrapporre)"""
    base, deck, prop, _ = s.build_parts()
    v = D.View(az=270, el=0, width=1500, height=560)
    pts = np.concatenate([D._mesh(m)[0] for a in s.ANGLES for m in
                          (base, s.place_deck(deck, a), s.place_prop(prop, a), s.dev_box(a))])
    v.fit(pts, margin=0.03)
    items = [(base, "old"), (s.place_deck(deck, angle), "new"), (s.place_prop(prop, angle), "new"),
             (s.dev_box(angle), "ghost")]
    _colorize(v, items).save(path, optimize=True)
    return path


def part(s, name, path):
    """un pezzo da stampare, orientato come sul piatto"""
    m = s.print_parts()[name]
    _colorize(D.View(az=235, el=32, width=900, height=620), [(m, "new")]).save(path, optimize=True)
    return path


# ---------------------------------------------------------------- mesh per il visore

def _feature_edges(V, F, crease=25.0):
    """spigoli dove le facce piegano più di `crease` gradi (o bordi aperti)"""
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    face = np.tile(np.arange(len(F)), 3)
    key = np.sort(e, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    key, face = key[order], face[order]
    same = np.all(key[1:] == key[:-1], axis=1)
    out = []
    i = 0
    cos_t = math.cos(math.radians(crease))
    while i < len(key):
        if i + 1 < len(key) and same[i]:
            if n[face[i]] @ n[face[i + 1]] < cos_t:
                out.append(key[i])
            i += 2
        else:
            out.append(key[i])
            i += 1
    return np.array(out, dtype=np.int64).reshape(-1, 2)


def _pack(m, kind):
    mesh = m.to_mesh()
    V = np.asarray(mesh.vert_properties)[:, :3].astype(float)
    F = np.asarray(mesh.tri_verts).astype(np.int64)
    # unisci vertici coincidenti (le proprietà possono duplicarli) per trovare gli spigoli
    q = np.round(V, 3)
    uniq, inv = np.unique(q, axis=0, return_inverse=True)
    F2 = inv.reshape(-1)[F]
    E = _feature_edges(uniq, F2)
    return {"kind": kind,
            "pos": np.round(uniq, 2).ravel().tolist(),
            "idx": F2.ravel().tolist(),
            "edges": E.ravel().tolist()}


def web_mesh(s, angle):
    """assemblato a un angolo per il visore del sito (Z in alto, mm)"""
    base, deck, prop, bars = s.build_parts()
    S = sum(s.SPACING_RANGE) / 2
    parts = []
    for y in (-S / 2, S / 2):
        parts += [_pack(base.translate([0, y, 0]), "base"),
                  _pack(s.place_deck(deck, angle).translate([0, y, 0]), "deck"),
                  _pack(s.place_prop(prop, angle).translate([0, y, 0]), "prop")]
    for cx in s.CB_X:
        parts += [_pack(b.translate([cx, 0, 0]), "bar") for b in bars]
    dev = _pack(s.dev_box(angle), "device")
    allv = np.concatenate([np.array(p["pos"]).reshape(-1, 3) for p in parts + [dev]])
    return {"angle": angle, "parts": parts, "device": {"pos": dev["pos"], "edges": dev["edges"]},
            "bounds": [allv.min(0).round(1).tolist(), allv.max(0).round(1).tolist()]}
