"""Helper geometrici comuni (manifold3d) per i supporti."""
import math
import numpy as np
from manifold3d import Manifold, CrossSection

SEG = 64
M5 = 2.75                        # raggio foro passante M5 (5.5 mm)
CB_R = 4.9                       # raggio lamatura testa M5 (9.8 mm)
NUT_F = 8.4                      # chiave dado M5 (8.0) + gioco


# ---------------- helper ----------------
def rect(x0, x1, y0, y1):
    return CrossSection.square([x1 - x0, y1 - y0]).translate([x0, y0])

def circ(x, y, r):
    return CrossSection.circle(r, SEG).translate([x, y])

def teardrop(x, y, r):
    tip = CrossSection.square([0.01, 0.01], center=True).translate([0, r * math.sqrt(2)])
    return CrossSection.batch_hull([CrossSection.circle(r, SEG), tip]).translate([x, y])

def xz_prism(cs, y0, y1):
    """profilo nel piano XZ estruso lungo Y in [y0, y1]"""
    return cs.extrude(y1 - y0).rotate([90, 0, 0]).translate([0, y1, 0])

def xy_prism(cs, z0, z1):
    return cs.extrude(z1 - z0).translate([0, 0, z0])

def box(x0, x1, y0, y1, z0, z1):
    return Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])

def vcyl(x, y, z0, z1, r):
    return Manifold.cylinder(z1 - z0, r, r, SEG).translate([x, y, z0])

def rot_y(m, deg):
    """ruota nel piano XZ: +deg porta +X verso +Z"""
    return m.rotate([0, -deg, 0])



def vol(m):
    return m.volume() if hasattr(m, "volume") else m.get_properties().volume


def export_stl(m, path):
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3]
    f = np.asarray(mesh.tri_verts)
    import trimesh
    trimesh.Trimesh(v, f, process=False).export(path)


def bbox(m):
    b = m.bounding_box()
    return np.array(b[3:]) - np.array(b[:3])


