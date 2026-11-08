"""Anteprime PNG (matplotlib) e assemblato 3D colorato (GLB) di un supporto."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

COL = {"base": "#4a7bd0", "deck": "#e08a3c", "prop": "#3fa66b", "cross": "#8a8f99", "dev": "#cccccc"}


def tris(m):
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3]
    return v[np.asarray(mesh.tri_verts)]


def draw3d(ax, m, c, alpha=1.0):
    t = tris(m)
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    n /= (np.linalg.norm(n, axis=1, keepdims=True) + 1e-9)
    shade = 0.45 + 0.55 * np.clip(n @ np.array([-0.4, -0.5, 0.77]), 0, 1)
    rgb = np.array(matplotlib.colors.to_rgb(c))
    ax.add_collection3d(Poly3DCollection(t, facecolors=np.clip(rgb * shade[:, None], 0, 1),
                                         edgecolors="none", alpha=alpha))


def _extent(s):
    boxes = [s.dev_box(a).bounding_box() for a in s.ANGLES]
    x0 = min(min(b[0] for b in boxes), s.X_FRONT) - 15
    x1 = max(max(b[3] for b in boxes), s.X_REAR) + 15
    top = max(b[5] for b in boxes) + 10
    return x0, x1, top


def side_view(s, path, title=""):
    base, deck, prop, _ = s.build_parts()
    x0, x1, top = _extent(s)
    A = s.ANGLES
    fig, axs = plt.subplots(len(A), 1, figsize=(11, max(2.2, 11 * top / (x1 - x0)) * len(A)), squeeze=False)
    for ax, a in zip(axs[:, 0], A):
        for m, c in [(base, "base"), (s.place_deck(deck, a), "deck"), (s.place_prop(prop, a), "prop"),
                     (s.dev_box(a), "dev")]:
            for t in tris(m):
                ax.fill(t[:, 0], t[:, 2], color=COL[c], lw=0)
        ax.set_aspect("equal")
        ax.set_xlim(x0, x1)
        ax.set_ylim(0, top)
        ax.axhline(0, color="k", lw=1)
        ax.set_title(f"{title}  {a}°".strip())
        ax.grid(alpha=.3)
    plt.tight_layout()
    plt.savefig(path, dpi=85)
    plt.close(fig)


def assembly_view(s, path, angle=None, title=""):
    base, deck, prop, bars = s.build_parts()
    a = angle if angle is not None else s.ANGLES[-1]
    S = sum(s.SPACING_RANGE) / 2
    x0, x1, top = _extent(s)
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection="3d")
    for y in (-S / 2, S / 2):
        draw3d(ax, base.translate([0, y, 0]), COL["base"])
        draw3d(ax, s.place_deck(deck, a).translate([0, y, 0]), COL["deck"])
        draw3d(ax, s.place_prop(prop, a).translate([0, y, 0]), COL["prop"])
    for cx in s.CB_X:
        for b in bars:
            draw3d(ax, b.translate([cx, 0, 0]), COL["cross"])
    draw3d(ax, s.dev_box(a), COL["dev"], alpha=0.25)
    R = s.DEV_W / 2 + 20
    ax.set_xlim(x0, x1)
    ax.set_ylim(-R, R)
    ax.set_zlim(0, top)
    ax.set_box_aspect((x1 - x0, 2 * R, top))
    ax.view_init(24, -130)
    ax.set_axis_off()
    ax.set_title(f"{title} a {a}°".strip())
    plt.tight_layout()
    plt.savefig(path, dpi=85)
    plt.close(fig)


def assembly_glb(s, path, angle=None, with_device=True):
    """assemblato colorato in GLB (per il visore 3D del sito). Unità: mm, Y in alto come vuole glTF."""
    import trimesh
    base, deck, prop, bars = s.build_parts()
    a = angle if angle is not None else s.ANGLES[-1]
    S = sum(s.SPACING_RANGE) / 2
    items = []
    for y in (-S / 2, S / 2):
        items += [(base.translate([0, y, 0]), "base"), (s.place_deck(deck, a).translate([0, y, 0]), "deck"),
                  (s.place_prop(prop, a).translate([0, y, 0]), "prop")]
    for cx in s.CB_X:
        items += [(b.translate([cx, 0, 0]), "cross") for b in bars]
    if with_device:
        items.append((s.dev_box(a), "dev"))
    scene = trimesh.Scene()
    for i, (m, c) in enumerate(items):
        mesh = m.to_mesh()
        tm = trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=False)
        rgba = list(matplotlib.colors.to_rgb(COL[c])) + [0.35 if c == "dev" else 1.0]
        mat = trimesh.visual.material.PBRMaterial(baseColorFactor=rgba, metallicFactor=0.0, roughnessFactor=0.8,
                                                  alphaMode="BLEND" if c == "dev" else "OPAQUE")
        tm.visual = trimesh.visual.TextureVisuals(material=mat)
        scene.add_geometry(tm, node_name=f"{c}_{i}")
    # Z in alto -> Y in alto
    scene.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    scene.export(path)
