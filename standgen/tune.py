"""Calcolo automatico di tacche, perno e lunghezza dell'asta.

Per ogni coppia (distanza del perno PIVOT_D, lunghezza dell'asta PROP_L):
  1. per ogni angolo si calcolano le quote di tacca possibili (asta né troppo piatta né verticale);
  2. le tacche si dispongono il più vicino possibile alla cerniera, distanziate del minimo
     (si provano tutti gli ordini degli angoli);
  3. i candidati si ordinano per profondità della base e si verificano in 3D, dal migliore,
     finché uno passa tutti i controlli.
"""
import itertools
import math
import time
from dataclasses import dataclass, field

import numpy as np

from .model import Stand, resolve_params, foot_xz, prop_beta
from .checks import validate, BETA_RANGE, NOTCH_WALL


@dataclass
class TuneResult:
    params: dict = None              # parametri completi da passare a Stand (None se fallito)
    ok: bool = False
    evaluated: int = 0
    candidates: int = 0
    seconds: float = 0.0
    message: str = ""
    last_errors: list = field(default_factory=list)


def _notch_options(theta, p, z_hinge, pivot_d, prop_l, zgrid):
    out = []
    for nz in zgrid:
        b = abs(prop_beta(theta, nz, pivot_d, z_hinge, prop_l, p["FOOT_OFF"]))
        if BETA_RANGE[0] + 1 <= b <= BETA_RANGE[1] - 1:
            out.append((float(nz), float(foot_xz(theta, nz, pivot_d, z_hinge, prop_l, p["FOOT_OFF"])[0])))
    return out


def _place(angles, opts, gap):
    """sceglie una tacca per angolo: x crescenti distanziate >= gap, max x minimo."""
    best = None
    for perm in itertools.permutations(angles):
        prev, pick = -1e9, {}
        for a in perm:
            o = next(((nz, x) for nz, x in opts[a] if x >= prev + gap), None)
            if o is None:
                break
            pick[a] = o
            prev = o[1]
        else:
            key = (max(x for _, x in pick.values()), sum(nz for nz, _ in pick.values()))
            if best is None or key < best[0]:
                best = (key, pick)
    return best[1] if best else None


def tune(params, time_limit=40.0, max_evals=600, progress=None):
    t0 = time.time()
    p = resolve_params({**params, "NOTCH_Z": None})
    z_hinge = p["Z_HINGE"] if p["Z_HINGE"] is not None else p["FLOOR"] + p["DECK_H"] / 2 + 1
    R = p["NOTCH_R"]
    slot_w = p["CB_W"] + 0.6
    zgrid = np.arange(R + NOTCH_WALL, 45.01, 0.5)
    angles = p["ANGLES"]
    if len(angles) > 6:
        return TuneResult(message="al massimo 6 angoli")
    # traversa centrale: stessa posizione per tutti i candidati (dipende solo da angolo minimo e ripiano)
    probe = Stand({**params, "NOTCH_Z": {a: 20.0 for a in angles}, "PIVOT_D": 100.0, "PROP_L": 40.0})
    mid_end = probe.MID_CB_X + slot_w / 2 + 4
    for a in angles:                       # il baricentro non dipende dalle tacche
        m = probe.dev_com(a)[0] - probe.X_FRONT
        if m <= 0:
            return TuneResult(seconds=time.time() - t0,
                              message=f"a {a}° lo strumento si ribalta in avanti: il baricentro cade "
                                      f"{-m:.0f} mm davanti alla base. Riduci l'angolo massimo.")
    if probe.screw_errors:
        return TuneResult(message="viti: " + "; ".join(probe.screw_errors), seconds=time.time() - t0)

    cands = []
    for pivot_d in range(60, int(p["DECK_LEN"]) - 19, 10):
        for prop_l in range(25, 91, 5):
            opts = {a: _notch_options(a, p, z_hinge, pivot_d, prop_l, zgrid) for a in angles}
            if any(not o for o in opts.values()):
                continue
            for gf in (1.0, 1.25, 1.6):
                pick = _place(angles, opts, (2 * R + p["NOTCH_GAP"]) * gf)
                if not pick:
                    continue
                xs = [x for _, x in pick.values()]
                if min(xs) - 12 < mid_end:          # le tacche devono stare dietro la traversa centrale
                    continue
                depth = max(xs) + R + 3 + slot_w + 4 + p["BOSS_R"]
                cands.append((round(depth, 1), max(nz for nz, _ in pick.values()), prop_l, pivot_d,
                              {a: nz for a, (nz, _) in pick.items()}))
    if not cands:
        return TuneResult(seconds=time.time() - t0,
                          message=f"non riesco a sistemare {len(angles)} tacche abbastanza distanziate "
                                  f"(almeno {2 * R + p['NOTCH_GAP']:.0f} mm l'una dall'altra): "
                                  "prova con meno angoli o con angoli più distanti tra loro")
    cands.sort(key=lambda c: c[:4])
    if p["MAX_DEPTH"]:
        n_all = len(cands)
        cands = [c for c in cands if c[0] <= p["MAX_DEPTH"]]
        if not cands:
            return TuneResult(candidates=n_all, seconds=time.time() - t0,
                              message=f"nessuna combinazione sta in {p['MAX_DEPTH']:.0f} mm di profondità: "
                                      "aumenta la profondità massima o togli l'angolo più basso/più alto")
    res = TuneResult(candidates=len(cands))
    seen = set()
    for depth, _, prop_l, pivot_d, nzs in cands:
        key = (prop_l, pivot_d, tuple(sorted(nzs.items())))
        if key in seen:
            continue
        seen.add(key)
        if res.evaluated >= max_evals or time.time() - t0 > time_limit:
            break
        trial = {**params, "NOTCH_Z": nzs, "PIVOT_D": float(pivot_d), "PROP_L": float(prop_l)}
        res.evaluated += 1
        if progress:
            progress(res.evaluated, len(cands), depth)
        rep = validate(Stand(trial), quick=True)
        if rep.ok:
            res.params, res.ok = trial, True
            res.message = (f"trovata dopo {res.evaluated} prove: profondità {depth:.0f} mm, "
                           f"perno a {pivot_d} mm, asta {prop_l} mm")
            break
        res.last_errors = [f"{c.group} {c.label}: {c.detail}" for c in rep.errors()]
    res.seconds = time.time() - t0
    if not res.ok and not res.message:
        res.message = (f"nessuna soluzione valida dopo {res.evaluated} prove su {len(cands)} candidati"
                       + (f" (ultimo errore: {res.last_errors[0]})" if res.last_errors else ""))
    return res
