"""Test del motore: python -m pytest tests  (oppure: python tests/test_engine.py)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from standgen import PRESETS, Stand, validate, tune, generate  # noqa: E402

AUTO = ("NOTCH_Z", "PIVOT_D", "PROP_L")


def test_presets_valid():
    for name, p in PRESETS.items():
        r = validate(Stand(p))
        assert r.ok, (name, [(c.label, c.detail) for c in r.errors()])


def test_old_crossbar_position_is_caught():
    # la traversa centrale nella vecchia posizione tocca il ripiano all'angolo minimo
    r = validate(Stand({**PRESETS["tracker_plus"], "MID_CB_X": 45.0}))
    assert not r.ok and any("ripiano/traverse" in c.detail for c in r.errors())


def test_tune_presets_not_deeper_than_hand_tuned():
    for name, p in PRESETS.items():
        hand = Stand(p)
        t = tune({k: v for k, v in p.items() if k not in AUTO})
        assert t.ok, (name, t.message)
        s = Stand(t.params)
        assert validate(s).ok
        assert s.X_REAR - s.X_FRONT <= hand.X_REAR - hand.X_FRONT + 0.5, name


def test_new_device_end_to_end():
    params = dict(DEV_W=378.0, DEV_D=293.0, DEV_H=41.0, DEV_KG=3.2, ANGLES=[10, 20, 30])
    with tempfile.TemporaryDirectory() as d:
        r = generate(params, d, name="push", previews=False, glb=True)
        assert r.ok, r.message
        for f in ("stl/base_x2.stl", "ferramenta.csv", "verifica.md", "montaggio.md", "parametri.json",
                  "assemblato.glb", "zip"):
            assert os.path.exists(r.files[f]), f


def test_depth_limit_impossible():
    p = {k: v for k, v in PRESETS["virus_ti"].items() if k not in AUTO}
    t = tune({**p, "MAX_DEPTH": 110.0})
    assert not t.ok and "profondità" in t.message


def test_screw_not_in_catalog():
    s = Stand({**PRESETS["tracker_plus"], "BOLT_CB": 35.0})    # M5x35 non è nella scorta
    r = validate(s)
    assert not r.ok and any(c.group == "Viti" for c in r.errors())


def test_tipping_detected():
    # strumento molto profondo e alto, inclinato tanto: il baricentro esce davanti
    p = dict(DEV_W=300.0, DEV_D=120.0, DEV_H=300.0, DEV_KG=1.5, ANGLES=[50, 60], NOTCH_Z=None)
    t = tune(p)
    assert not t.ok and "ribalta" in t.message


def test_too_many_angles_message():
    t = tune(dict(DEV_W=250.0, DEV_D=150.0, DEV_H=40.0, DEV_KG=0.8, ANGLES=[5, 10, 15, 20, 25]))
    assert not t.ok and "meno angoli" in t.message


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
