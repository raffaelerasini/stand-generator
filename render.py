"""Anteprime: python render.py [profilo ...] -> <profilo>/preview/*.png"""
import os, sys, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import stand as L

COL = {"base": "#4a7bd0", "deck": "#e08a3c", "prop": "#3fa66b", "cross": "#8a8f99", "dev": "#cccccc"}

def tris(m):
    mesh = m.to_mesh(); v = np.asarray(mesh.vert_properties)[:, :3]; f = np.asarray(mesh.tri_verts)
    return v[f]

def draw3d(ax, m, c, alpha=1.0):
    t = tris(m)
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]); n /= (np.linalg.norm(n, axis=1, keepdims=True) + 1e-9)
    shade = 0.45 + 0.55 * np.clip(n @ np.array([-0.4, -0.5, 0.77]), 0, 1)
    rgb = np.array(matplotlib.colors.to_rgb(c))
    ax.add_collection3d(Poly3DCollection(t, facecolors=np.clip(rgb * shade[:, None], 0, 1), edgecolors="none", alpha=alpha))

for name in (sys.argv[1:] or list(L.PROFILES)):
    base, deck, prop, bars = L.build_parts(name)
    out = os.path.join(name, "preview"); os.makedirs(out, exist_ok=True)
    A = L.ANGLES
    top = 230 if name == "virus_ti" else 110
    fig, axs = plt.subplots(len(A), 1, figsize=(11, 3.4 * len(A) * top / 130))
    for ax, a in zip(axs, A):
        for m, c in [(base, "base"), (L.place_deck(deck, a), "deck"), (L.place_prop(prop, a), "prop"), (L.dev_box(a), "dev")]:
            for t in tris(m): ax.fill(t[:, 0], t[:, 2], color=COL[c], lw=0)
        ax.set_aspect("equal"); ax.set_xlim(-80, 290); ax.set_ylim(0, top); ax.axhline(0, color="k", lw=1)
        ax.set_title(f"{name}  {a}°"); ax.grid(alpha=.3)
    plt.tight_layout(); plt.savefig(os.path.join(out, "vista_laterale.png"), dpi=85); plt.close()
    S = sum(L.SPACING_RANGE) / 2; a = A[-1]
    fig = plt.figure(figsize=(10, 8)); ax = fig.add_subplot(111, projection="3d")
    for y in (-S / 2, S / 2):
        draw3d(ax, base.translate([0, y, 0]), COL["base"]); draw3d(ax, L.place_deck(deck, a).translate([0, y, 0]), COL["deck"])
        draw3d(ax, L.place_prop(prop, a).translate([0, y, 0]), COL["prop"])
    for cx in L.CB_X:
        for b in bars: draw3d(ax, b.translate([cx, 0, 0]), COL["cross"])
    draw3d(ax, L.dev_box(a), COL["dev"], alpha=0.25)
    R = L.DEV_W / 2 + 20
    ax.set_xlim(-80, 290); ax.set_ylim(-R, R); ax.set_zlim(0, top); ax.set_box_aspect((370, 2 * R, top))
    ax.view_init(24, -130); ax.set_axis_off(); ax.set_title(f"{name} a {a}°")
    plt.tight_layout(); plt.savefig(os.path.join(out, "assemblaggio.png"), dpi=85); plt.close()
    print("ok", name)
