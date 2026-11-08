"""Dalla lista di parametri al pacchetto completo: STL, anteprime, ferramenta, verifica, zip."""
import json
import os
import zipfile
from dataclasses import dataclass, field

from .cadlib import export_stl
from .checks import validate
from .model import Stand, resolve_params
from .tune import tune
from . import render


@dataclass
class Result:
    ok: bool
    stand: Stand = None
    report: object = None
    tune: object = None
    out_dir: str = ""
    files: dict = field(default_factory=dict)
    message: str = ""


def needs_tuning(params):
    nz = params.get("NOTCH_Z")
    return not nz or any(a not in nz for a in params.get("ANGLES", []))


def assembly_text(s):
    """istruzioni di montaggio in testo, con le viti scelte per questo supporto"""
    b = s.bom()
    steps = []
    if s.SPLIT:
        steps.append(f"**Traverse.** Unisci le metà A e B nella zona a mezzo legno con 3 viti M5×{s.splice_len} "
                     "per traversa: i dadi nelle sedi esagonali sotto A, le teste nelle lamature sopra B.")
    steps.append(f"**Basi.** Infila le due traverse nei tunnel delle basi (centro e retro). "
                 f"Nelle alette interne: dado nel canale sotto la traversa, vite M5×{s.BOLT_CB} con rondella "
                 f"dall'alto. Le asole regolano la distanza tra i fianchi: "
                 f"{s.SPACING_RANGE[0]:.0f}–{s.SPACING_RANGE[1]:.0f} mm.")
    steps.append(f"**Ripiano.** Infilalo davanti tra le pareti della base e fissalo con la vite M5×{s.hinge_len} "
                 "(rondella sotto la testa) e il dado autobloccante, incassato nella sede esagonale "
                 "sul lato esterno della parete.")
    steps.append(f"**Asta.** Inseriscila nella forcella sul retro del ripiano e fissala con la vite M5×{s.pivot_len}, "
                 "due rondelle e il dado autobloccante. Le orecchie del piede si appoggiano nelle tacche.")
    order = sorted(s.ANGLES, key=lambda a: s.foot_pos(a)[0])
    steps.append("**Cambio angolo.** Solleva il retro dello strumento, sposta il piede nella tacca voluta e "
                 "riabbassa. Tacche dalla più avanti alla più indietro: "
                 + ", ".join(f"{a}°" for a in order) + ".")
    lines = ["# Montaggio", "", "## Ferramenta (per un supporto completo)", ""]
    lines += [f"- {l}" for l in b.as_lines()]
    lines += ["", "## Passi", ""] + [f"{i}. {t}" for i, t in enumerate(steps, 1)]
    return "\n".join(lines) + "\n"


def generate(params, out_dir, name="supporto", previews=True, glb=False, make_zip=True, progress=None):
    """genera tutto in out_dir. Se mancano le tacche le calcola. Ritorna un Result."""
    params = dict(params)
    tr = None
    if needs_tuning(params):
        if progress:
            progress("calcolo tacche")
        tr = tune(params)
        if not tr.ok:
            return Result(False, tune=tr, message=tr.message)
        params = tr.params
    if progress:
        progress("geometria")
    s = Stand(params)
    if progress:
        progress("verifica")
    rep = validate(s)
    os.makedirs(out_dir, exist_ok=True)
    stl_dir = os.path.join(out_dir, "stl")
    os.makedirs(stl_dir, exist_ok=True)
    for f in os.listdir(stl_dir):               # via i pezzi di una generazione precedente
        os.remove(os.path.join(stl_dir, f))
    files = {}
    for pn, m in s.print_parts().items():
        f = os.path.join(stl_dir, f"{pn}.stl")
        export_stl(m, f)
        files[f"stl/{pn}.stl"] = f
    if previews:
        if progress:
            progress("anteprime")
        pv = os.path.join(out_dir, "preview")
        os.makedirs(pv, exist_ok=True)
        render.side_view(s, os.path.join(pv, "vista_laterale.png"), name)
        render.assembly_view(s, os.path.join(pv, "assemblaggio.png"), title=name)
        files["preview/vista_laterale.png"] = os.path.join(pv, "vista_laterale.png")
        files["preview/assemblaggio.png"] = os.path.join(pv, "assemblaggio.png")
    if glb:
        f = os.path.join(out_dir, "assemblato.glb")
        render.assembly_glb(s, f)
        files["assemblato.glb"] = f
    texts = {
        "ferramenta.csv": s.bom().to_csv(),
        "verifica.md": f"# Verifica: {name}\n\n" + rep.to_markdown() + "\n",
        "montaggio.md": assembly_text(s),
        "parametri.json": json.dumps(_jsonable(s.params), indent=2, ensure_ascii=False) + "\n",
    }
    for fn, txt in texts.items():
        f = os.path.join(out_dir, fn)
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(txt)
        files[fn] = f
    if make_zip:
        z = os.path.join(out_dir, f"{name}.zip")
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for arc, f in files.items():
                if not f.endswith(".glb"):
                    zf.write(f, f"{name}/{arc}")
        files["zip"] = z
    msg = "valido" if rep.ok else "NON valido: " + "; ".join(f"{c.group} {c.label}" for c in rep.errors())
    return Result(rep.ok, s, rep, tr, out_dir, files, msg)


def _jsonable(p):
    out = {}
    for k, v in p.items():
        if isinstance(v, dict):
            v = {str(a): b for a, b in v.items()}
        elif isinstance(v, tuple):
            v = list(v)
        out[k] = v
    return out


def load_params(path):
    """legge un parametri.json (anche quello scritto da generate)"""
    with open(path, encoding="utf-8") as fh:
        p = json.load(fh)
    if p.get("NOTCH_Z"):
        p["NOTCH_Z"] = {float(a) if "." in a else int(a): z for a, z in p["NOTCH_Z"].items()}
    resolve_params(p)          # controlla i nomi
    return p
