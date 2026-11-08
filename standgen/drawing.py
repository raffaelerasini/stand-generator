"""Disegni al tratto stile istruzioni di montaggio.

Un piccolo rasterizzatore ortografico in numpy (z-buffer) produce per ogni pixel: profondità,
pezzo e normale. Le linee nascono dalle discontinuità di queste tre immagini (contorni, spigoli,
confini tra pezzi), quindi le linee nascoste non compaiono. Sopra l'immagine matplotlib
disegna frecce ed etichette: `View.project` porta un punto 3D in coordinate pixel.
"""
import math

import numpy as np
from manifold3d import Manifold, CrossSection

from .cadlib import SEG

# riempimenti (grigio 0..1) per stile
FILL = {"new": 1.0, "old": 0.86, "hw": 0.72, "ghost": 1.0}
LINE = {"new": 0.0, "old": 0.25, "hw": 0.0, "ghost": 0.6}


class View:
    def __init__(self, az=225.0, el=28.0, width=1400, height=1000, ss=2):
        a, e = math.radians(az), math.radians(el)
        self.c = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
        f = -self.c
        self.r = np.cross(f, [0, 0, 1.0])
        self.r /= np.linalg.norm(self.r)
        self.u = np.cross(self.r, f)
        self.W, self.H, self.ss = width, height, ss
        self.scale = None

    def _xy(self, p):
        p = np.atleast_2d(p)
        return np.stack([p @ self.r, p @ self.u], axis=1)

    def fit(self, points, margin=0.08):
        xy = self._xy(points)
        lo, hi = xy.min(0), xy.max(0)
        span = np.maximum(hi - lo, 1e-6)
        self.scale = min(self.W * (1 - 2 * margin) / span[0], self.H * (1 - 2 * margin) / span[1])
        self.center = (lo + hi) / 2

    def project(self, p):
        """punti 3D -> pixel (x verso destra, y verso il basso) dell'immagine finale"""
        xy = (self._xy(p) - self.center) * self.scale
        return np.stack([self.W / 2 + xy[:, 0], self.H / 2 - xy[:, 1]], axis=1)


def _mesh(m):
    mesh = m.to_mesh()
    return np.asarray(mesh.vert_properties)[:, :3].astype(float), np.asarray(mesh.tri_verts)


def render(view, items, light=(-0.3, -0.5, 0.8)):
    """items: lista di (Manifold, stile). Ritorna un'immagine in grigi (H, W) su fondo bianco.
    Gli oggetti "ghost" (lo strumento) non coprono gli altri: se ne disegna solo il contorno, sopra."""
    solid = [it for it in items if it[1] != "ghost"]
    ghost = [it for it in items if it[1] == "ghost"]
    if view.scale is None:
        view.fit(np.concatenate([_mesh(m)[0] for m, _ in items]))
    img = np.ones((view.H, view.W))
    if solid:
        s = _render(view, solid, light)
        img = s[..., 0] * s[..., 3] + (1 - s[..., 3])
    if ghost:
        g = _render(view, ghost, light)
        gray = g[..., 0] * g[..., 3] + (1 - g[..., 3])      # 1 = niente, 0.6 = linea
        img = np.minimum(img, 1 - (1 - gray) * 0.9)
    return img


def _render(view, items, light):
    S = view.ss
    W, H = view.W * S, view.H * S
    verts, tris, owner = [], [], []
    off = 0
    for i, (m, _) in enumerate(items):
        v, f = _mesh(m)
        verts.append(v)
        tris.append(f + off)
        owner.append(np.full(len(f), i))
        off += len(v)
    V = np.concatenate(verts)
    F = np.concatenate(tris)
    own = np.concatenate(owner)
    if view.scale is None:
        view.fit(V)
    P = view.project(V) * S
    D = V @ view.c                                    # più grande = più vicino
    T = P[F]                                          # (n, 3, 2)
    Z = D[F]
    n3 = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    n3 /= np.linalg.norm(n3, axis=1, keepdims=True) + 1e-12
    # solo facce rivolte alla camera (mesh chiuse) e non degeneri
    front = n3 @ view.c > 1e-6
    e1, e2 = T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]
    area = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    keep = front & (np.abs(area) > 1e-9)
    depth, tbuf = _scanline(T[keep], Z[keep], np.nonzero(keep)[0], W, H)
    return _shade(view, items, tbuf.reshape(H, W), depth.reshape(H, W), own, n3, np.array(light))


def _scanline(T, Z, tri_idx, W, H):
    """rasterizzazione per righe di tutti i triangoli insieme (centri pixel in +0.5)"""
    depth = np.full(H * W, -np.inf)
    tbuf = np.full(H * W, -1)
    # piano della profondità: z = A x + B y + C
    x, y = T[:, :, 0], T[:, :, 1]
    e1x, e1y, e2x, e2y = x[:, 1] - x[:, 0], y[:, 1] - y[:, 0], x[:, 2] - x[:, 0], y[:, 2] - y[:, 0]
    dz1, dz2 = Z[:, 1] - Z[:, 0], Z[:, 2] - Z[:, 0]
    det = e1x * e2y - e1y * e2x
    A = (dz1 * e2y - dz2 * e1y) / det
    B = (dz2 * e1x - dz1 * e2x) / det
    C = Z[:, 0] - A * x[:, 0] - B * y[:, 0]
    r0 = np.clip(np.ceil(y.min(1) - 0.5).astype(int), 0, H)
    r1 = np.clip(np.floor(y.max(1) - 0.5).astype(int) + 1, 0, H)       # esclusivo
    nrows = np.maximum(r1 - r0, 0)
    tri = np.repeat(np.arange(len(T)), nrows)
    if not len(tri):
        return depth, tbuf
    row = np.arange(len(tri)) - np.repeat(np.cumsum(nrows) - nrows, nrows) + r0[tri]
    yc = row + 0.5
    xl = np.full(len(tri), np.inf)
    xr = np.full(len(tri), -np.inf)
    for i, j in ((0, 1), (1, 2), (2, 0)):
        xa, ya, xb, yb = x[tri, i], y[tri, i], x[tri, j], y[tri, j]
        lo, hi = np.minimum(ya, yb), np.maximum(ya, yb)
        ok = (yc >= lo) & (yc <= hi) & (hi > lo)
        xi = np.where(ok, xa + (yc - ya) * (xb - xa) / np.where(hi > lo, yb - ya, 1), 0)
        xl = np.where(ok, np.minimum(xl, xi), xl)
        xr = np.where(ok, np.maximum(xr, xi), xr)
    c0 = np.clip(np.ceil(np.nan_to_num(xl, posinf=W) - 0.5).astype(np.int64), 0, W)
    c1 = np.clip(np.floor(np.nan_to_num(xr, neginf=-1) - 0.5).astype(np.int64) + 1, 0, W)
    n = np.maximum(c1 - c0, 0)
    seg = np.repeat(np.arange(len(tri)), n)
    col = np.arange(len(seg)) - np.repeat(np.cumsum(n) - n, n) + c0[seg]
    t = tri[seg]
    r = row[seg]
    d = A[t] * (col + 0.5) + B[t] * (r + 0.5) + C[t]
    flat = r * W + col
    np.maximum.at(depth, flat, d)
    win = d >= depth[flat] - 1e-9
    tbuf[flat[win]] = tri_idx[t[win]]
    return depth, tbuf


def _shade(view, items, tb, depth, own, normals, light):
    S = view.ss
    H, W = tb.shape
    hit = tb >= 0
    part = np.where(hit, own[np.maximum(tb, 0)], -1)
    nrm = np.where(hit[..., None], normals[np.maximum(tb, 0)], 0)
    styles = [st for _, st in items]
    fill = np.ones((H, W))
    lw = np.zeros((H, W))                 # colore della linea per pixel
    light = light / np.linalg.norm(light)
    lam = np.clip(nrm @ light, 0, 1)
    for i, st in enumerate(styles):
        m = part == i
        base = FILL[st]
        fill[m] = base * (0.9 + 0.1 * lam[m]) if st != "ghost" else 1.0
        lw[m] = LINE[st]
    # bordi: pezzo diverso, salto di profondità, piega
    edge = np.zeros((H, W), bool)
    ink = np.ones((H, W))
    dz_tol = 1.0 + 12 / (view.scale * S)             # mm: tollera le superfici molto inclinate
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        a = (slice(0, H - dy), slice(max(0, -dx), W - max(0, dx)))
        b = (slice(dy, H), slice(max(0, dx), W - max(0, -dx) if dx < 0 else W))
        pa, pb = part[a], part[b]
        e = pa != pb
        both = (pa >= 0) & (pb >= 0) & ~e
        with np.errstate(invalid="ignore"):
            e |= both & (np.abs(depth[a] - depth[b]) > dz_tol)
        e |= both & ((nrm[a] * nrm[b]).sum(-1) < math.cos(math.radians(28)))
        # colore: quello del pezzo più vicino tra i due lati
        cand = np.where(pa < 0, lw[b], np.where(pb < 0, lw[a], np.where(depth[a] >= depth[b], lw[a], lw[b])))
        edge[a] |= e
        ink[a] = np.where(e, np.minimum(ink[a], cand), ink[a])
    # linee più spesse: dilatazione 3x3
    e0, k0 = edge.copy(), ink.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            es = np.roll(np.roll(e0, dy, 0), dx, 1)
            ks = np.roll(np.roll(k0, dy, 0), dx, 1)
            ink = np.where(es, np.minimum(ink, ks), ink)
            edge |= es
    img = np.where(edge, ink, fill)
    alpha = np.where(hit | edge, 1.0, 0.0)
    # ghost: solo contorno sottile, interno trasparente
    if "ghost" in styles:
        gi = [i for i, st in enumerate(styles) if st == "ghost"]
        g = np.isin(part, gi)
        alpha = np.where(g & ~edge, 0.0, alpha)
    rgba = np.dstack([img, img, img, alpha])
    # sottocampionamento S x S (antialias)
    rgba = rgba.reshape(H // S, S, W // S, S, 4).mean((1, 3))
    return rgba


# ---------------------------------------------------------------- ferramenta 3D

def _hex(across_flats, h):
    r = across_flats / math.sqrt(3)
    return CrossSection.circle(r, 6).extrude(h)


def screw(length, kind="TCEI"):
    """vite M5 lungo +Z: sotto testa in z = 0, gambo verso -Z"""
    shaft = Manifold.cylinder(length, 2.5, 2.5, 24).translate([0, 0, -length])
    if kind == "TE":
        head = _hex(8.0, 3.5)
    else:
        head = Manifold.cylinder(5.0, 4.25, 4.25, SEG) - _hex(4.0, 3.0).translate([0, 0, 2.5])
    return shaft + head


def washer(d_out=10.0, t=1.0):
    return Manifold.cylinder(t, d_out / 2, d_out / 2, SEG) - Manifold.cylinder(3 * t, 2.65, 2.65, 24).translate(
        [0, 0, -t])


def nut(nyloc=False):
    h = 4.0
    n = _hex(8.0, h) - Manifold.cylinder(20, 2.5, 2.5, 24).translate([0, 0, -1])
    if nyloc:
        n = n + (Manifold.cylinder(1.5, 4.0, 3.4, SEG) - Manifold.cylinder(5, 2.5, 2.5, 24).translate(
            [0, 0, -1])).translate([0, 0, h])
    return n


def along(m, axis, at):
    """orienta un pezzo costruito lungo +Z verso l'asse dato ('+y','-y','+z','-z') e lo sposta in `at`"""
    rot = {"+z": [0, 0, 0], "-z": [180, 0, 0], "+y": [-90, 0, 0], "-y": [90, 0, 0],
           "+x": [0, 90, 0], "-x": [0, -90, 0]}[axis]
    return m.rotate(rot).translate(list(at))
