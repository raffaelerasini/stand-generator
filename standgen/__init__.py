"""standgen: generatore di supporti inclinabili low profile.

    from standgen import PRESETS, generate
    r = generate(PRESETS["tracker_plus"], "out/tracker")       # tacche già tarate
    r = generate(dict(DEV_W=300, DEV_D=180, DEV_H=40, DEV_KG=1.5, ANGLES=[10, 20, 30]), "out/mio")  # tacche calcolate
"""
from .model import Stand, PRESETS, resolve_params
from .checks import validate
from .tune import tune
from .pipeline import generate, load_params

__all__ = ["Stand", "PRESETS", "resolve_params", "validate", "tune", "generate", "load_params"]
