"""Solo anteprime: python render.py [profilo ...] -> <profilo>/preview/*.png"""
import os
import sys

from standgen import PRESETS, Stand
from standgen import render

for name in (sys.argv[1:] or list(PRESETS)):
    s = Stand(PRESETS[name])
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), name, "preview")
    os.makedirs(out, exist_ok=True)
    render.side_view(s, os.path.join(out, "vista_laterale.png"), name)
    render.assembly_view(s, os.path.join(out, "assemblaggio.png"), title=name)
    print("ok", name)
