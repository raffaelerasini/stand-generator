"""Sito per generare i supporti low profile.

    python app.py            -> http://localhost:7860

Variabili d'ambiente:
    DATA_DIR        cartella dei risultati (default ./data)
    CACHE_MAX       quante generazioni tenere (default 40)
    APP_PASSWORD    se impostata, il sito chiede utente/password (utente: APP_USER, default "admin")
    CONCURRENCY     generazioni in parallelo (default 2)
"""
import hashlib
import json
import os
import shutil
import threading
import time
from collections import OrderedDict

import gradio as gr

from standgen import PRESETS, Stand, generate, load_params
from standgen import render
from standgen.checks import summary
from standgen.pipeline import _jsonable

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.environ.get("DATA_DIR", os.path.join(HERE, "data")))
CACHE_DIR = os.path.join(DATA_DIR, "cache")
CACHE_MAX = int(os.environ.get("CACHE_MAX", 40))
CONCURRENCY = int(os.environ.get("CONCURRENCY", 2))
AUTO_KEYS = ("NOTCH_Z", "PIVOT_D", "PROP_L")
CUSTOM = "Strumento personalizzato"
PRESET_BY_LABEL = {p["LABEL"]: k for k, p in PRESETS.items()}
PART_NAMES = {"base": "Base (fianco)", "deck": "Ripiano", "prop": "Asta",
              "crossbar": "Traversa", "crossbar_A": "Traversa, metà A", "crossbar_B": "Traversa, metà B"}

os.makedirs(CACHE_DIR, exist_ok=True)
_locks = {}
_locks_guard = threading.Lock()
_stands = OrderedDict()          # piccola cache in memoria: chiave -> Stand


# ---------------------------------------------------------------- parametri

def parse_angles(text):
    try:
        angles = sorted({float(a) for a in str(text).replace(";", ",").replace(" ", ",").split(",") if a.strip()})
    except ValueError:
        raise gr.Error("Angoli: scrivi dei numeri separati da virgole, per esempio 10, 20, 30")
    angles = [int(a) if a == int(a) else a for a in angles]
    if not 1 <= len(angles) <= 6:
        raise gr.Error("Servono da 1 a 6 angoli")
    if any(not 1 <= a <= 60 for a in angles):
        raise gr.Error("Gli angoli devono stare tra 1° e 60°")
    return angles


def check_range(label, v, lo, hi):
    if v is None or not lo <= v <= hi:
        raise gr.Error(f"{label}: deve stare tra {lo} e {hi}")
    return float(v)


def build_params(preset, w, d, h, kg, angles_txt, max_depth, lip_h, sp_min, sp_max, keep_notches):
    angles = parse_angles(angles_txt)
    p = {}
    if preset != CUSTOM:
        p = {k: v for k, v in PRESETS[PRESET_BY_LABEL[preset]].items() if k != "LABEL"}
        same_angles = [float(a) for a in p["ANGLES"]] == [float(a) for a in angles]
        if not (keep_notches and same_angles):
            for k in AUTO_KEYS:
                p.pop(k, None)
    p.update(
        DEV_W=check_range("Larghezza", w, 80, 700),
        DEV_D=check_range("Profondità", d, 60, 500),
        DEV_H=check_range("Altezza", h, 5, 200),
        DEV_KG=check_range("Peso", kg, 0.1, 15),
        ANGLES=angles,
        LIP_H=check_range("Bordino", lip_h, 0, 60),
        MAX_DEPTH=float(max_depth) if max_depth else None,
    )
    if sp_min or sp_max:
        if not (sp_min and sp_max) or sp_max <= sp_min:
            raise gr.Error("Distanza tra i fianchi: indica minimo e massimo (massimo > minimo), "
                           "oppure lascia 0 e 0 per il calcolo automatico")
        p["SPACING_RANGE"] = (float(sp_min), float(sp_max))
    else:
        p["SPACING_RANGE"] = None
    return p


def params_key(p):
    blob = json.dumps(_jsonable(p), sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def safe_name(text):
    s = "".join(c if c.isalnum() or c in "-_" else "_" for c in (text or "").strip().lower())
    return s.strip("_")[:40] or "supporto"


# ---------------------------------------------------------------- cache

def _lock(key):
    with _locks_guard:
        return _locks.setdefault(key, threading.RLock())


def _prune_cache():
    dirs = sorted((os.path.join(CACHE_DIR, d) for d in os.listdir(CACHE_DIR)), key=os.path.getmtime)
    for d in dirs[:-CACHE_MAX]:
        shutil.rmtree(d, ignore_errors=True)


def get_stand(key):
    if key in _stands:
        _stands.move_to_end(key)
        return _stands[key]
    s = Stand(load_params(os.path.join(CACHE_DIR, key, "parametri.json")))
    _stands[key] = s
    while len(_stands) > 6:
        _stands.popitem(last=False)
    return s


def glb_path(key, angle):
    f = os.path.join(CACHE_DIR, key, f"assemblato_{angle}.glb")
    if not os.path.exists(f):
        with _lock(key):
            if not os.path.exists(f):
                render.assembly_glb(get_stand(key), f, angle)
    return f


def run(params, name, progress):
    """genera (o riprende dalla cache) e ritorna il dizionario risultato."""
    key = params_key({**params, "_name": name})
    out = os.path.join(CACHE_DIR, key)
    res_file = os.path.join(out, "risultato.json")
    with _lock(key):
        if os.path.exists(res_file):
            os.utime(out)
            with open(res_file, encoding="utf-8") as fh:
                return json.load(fh)
        steps = {"calcolo tacche": 0.1, "geometria": 0.35, "verifica": 0.45, "anteprime": 0.6}
        r = generate(params, out, name=name, previews=True, glb=False,
                     progress=lambda st: progress(steps.get(st, 0.5), desc=st.capitalize()))
        res = {"key": key, "name": name, "ok": r.ok, "message": r.message,
               "tune": r.tune.message if r.tune else None,
               "tune_errors": r.tune.last_errors if r.tune else []}
        if r.stand is not None:
            s = r.stand
            _stands[key] = s
            sm = summary(s)
            res.update(
                angles=list(s.ANGLES),
                summary={k: sm[k] for k in ("profondita_mm", "piano_davanti_mm", "bordino_mm", "filamento_g",
                                            "pivot_d", "prop_l")},
                spacing=list(s.SPACING_RANGE),
                parts=[[n, v] for n, v in sm["pezzi"].items()],
                bom=[[q, it.name, ", ".join(dict.fromkeys(uses)), it.stock] for it, q, uses in s.bom().totals()],
                errors=[f"{c.group} — {c.label}: {c.detail}" for c in r.report.errors()],
                warnings=[f"{c.group} — {c.label}: {c.detail}" for c in r.report.warnings()],
                files={k: os.path.relpath(v, out) for k, v in r.files.items()},
            )
            progress(0.85, desc="Modello 3D")
            glb_path(key, s.ANGLES[-1])
        os.makedirs(out, exist_ok=True)
        with open(res_file, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
    _prune_cache()
    return res


# ---------------------------------------------------------------- interfaccia

def status_md(res):
    if "summary" not in res:
        md = f"### ❌ Nessun supporto possibile\n\n{res['message']}"
        if res.get("tune_errors"):
            md += "\n\nUltimo controllo fallito: " + res["tune_errors"][0]
        return md
    sm = res["summary"]
    head = "### ✅ Supporto valido" if res["ok"] else "### ❌ Supporto NON valido"
    md = (f"{head}\n\n**Profondità base {sm['profondita_mm']:.0f} mm** · piano d'appoggio davanti "
          f"{sm['piano_davanti_mm']:.0f} mm (bordino +{sm['bordino_mm']:.0f}) · circa **{sm['filamento_g']} g** "
          f"di filamento · fianchi a {res['spacing'][0]:.0f}–{res['spacing'][1]:.0f} mm")
    if res.get("tune"):
        md += f"\n\nTacche calcolate automaticamente: {res['tune']}"
    if res["errors"]:
        md += "\n\n**Problemi:**\n" + "\n".join(f"- {e}" for e in res["errors"])
    if res["warnings"]:
        md += "\n\n**Avvisi:**\n" + "\n".join(f"- ⚠️ {w}" for w in res["warnings"])
    return md


def parts_rows(res):
    rows = []
    for name, dims in res.get("parts", []):
        base, _, q = name.rpartition("_x")
        rows.append([PART_NAMES.get(base, base), int(q) if q.isdigit() else 1,
                     " × ".join(f"{v:.0f}" for v in dims), f"{name}.stl"])
    return rows


def bom_rows(res):
    return [[q, n, u, s, "" if q <= s else "⚠️ oltre la scorta"] for q, n, u, s in res.get("bom", [])]


def on_generate(preset, name, w, d, h, kg, angles_txt, max_depth, lip_h, sp_min, sp_max, keep_notches,
                progress=gr.Progress()):
    t0 = time.time()
    params = build_params(preset, w, d, h, kg, angles_txt, max_depth, lip_h, sp_min, sp_max, keep_notches)
    res = run(params, safe_name(name), progress)
    out = os.path.join(CACHE_DIR, res["key"])
    if "summary" not in res:
        empty = gr.update(value=None)
        return (res["key"], status_md(res), empty, gr.update(choices=[], value=None, visible=False), empty, empty,
                [], [], "", "", empty, empty)
    f = {k: os.path.join(out, v) for k, v in res["files"].items()}
    stls = [v for k, v in sorted(f.items()) if k.startswith("stl/")]
    a = res["angles"][-1]
    montaggio = open(f["montaggio.md"], encoding="utf-8").read()
    verifica = open(f["verifica.md"], encoding="utf-8").read()
    status = status_md(res) + f"\n\n<sub>generato in {time.time() - t0:.1f} s</sub>"
    return (res["key"], status, glb_path(res["key"], a),
            gr.update(choices=[(f"{x}°", x) for x in res["angles"]], value=a, visible=True),
            f.get("preview/vista_laterale.png"), f.get("preview/assemblaggio.png"),
            parts_rows(res), bom_rows(res), montaggio, verifica, f["zip"], stls)


def on_angle(key, angle):
    if not key or angle is None:
        return gr.update()
    return glb_path(key, angle)


def on_preset(preset):
    if preset == CUSTOM:
        return [gr.update()] * 9 + [gr.update(visible=False)]
    p = PRESETS[PRESET_BY_LABEL[preset]]
    sp = p.get("SPACING_RANGE") or (0, 0)
    return [PRESET_BY_LABEL[preset], p["DEV_W"], p["DEV_D"], p["DEV_H"], p["DEV_KG"],
            ", ".join(str(a) for a in p["ANGLES"]), p.get("LIP_H", 10), sp[0], sp[1], gr.update(visible=True)]


INTRO = """# Supporti inclinabili low profile
Inserisci le misure dello strumento e gli angoli: il generatore calcola tacche, asta e viti,
controlla collisioni e stabilità e ti dà gli STL pronti da stampare, la lista della ferramenta
(solo viti M5 della scorta standard) e le istruzioni di montaggio."""


def build_ui():
    first = PRESETS["tracker_plus"]
    with gr.Blocks(title="Supporti low profile") as demo:
        key = gr.State(None)
        gr.Markdown(INTRO)
        with gr.Row():
            with gr.Column(scale=1, min_width=320):
                preset = gr.Dropdown([CUSTOM] + list(PRESET_BY_LABEL), value=first["LABEL"], label="Strumento")
                name = gr.Textbox("tracker_plus", label="Nome del progetto (per i file)")
                with gr.Row():
                    w = gr.Number(first["DEV_W"], label="Larghezza mm", minimum=80, maximum=700)
                    d = gr.Number(first["DEV_D"], label="Profondità mm", minimum=60, maximum=500)
                with gr.Row():
                    h = gr.Number(first["DEV_H"], label="Altezza mm", minimum=5, maximum=200)
                    kg = gr.Number(first["DEV_KG"], label="Peso kg", minimum=0.1, maximum=15, step=0.1)
                angles = gr.Textbox("5, 10, 15", label="Angoli (gradi, separati da virgole, max 6)")
                with gr.Accordion("Opzioni", open=False):
                    max_depth = gr.Number(0, label="Profondità massima della base, mm (0 = nessun limite)",
                                          minimum=0)
                    lip_h = gr.Number(first["LIP_H"], label="Altezza del bordino anteriore, mm", minimum=0,
                                      maximum=60)
                    with gr.Row():
                        sp_min = gr.Number(first["SPACING_RANGE"][0], label="Distanza fianchi min, mm", minimum=0)
                        sp_max = gr.Number(first["SPACING_RANGE"][1], label="max (0 e 0 = automatica)", minimum=0)
                    keep = gr.Checkbox(True, label="Usa le tacche tarate a mano del modello "
                                                   "(se togli la spunta le ricalcolo per la base più corta)")
                btn = gr.Button("Genera", variant="primary", size="lg")
                status = gr.Markdown()
            with gr.Column(scale=2):
                with gr.Tab("3D"):
                    viewer = gr.Model3D(label="Assemblato (strumento trasparente)", height=480,
                                        clear_color=(0.96, 0.96, 0.96, 1.0))
                    angle = gr.Radio([], label="Angolo", visible=False)
                with gr.Tab("Anteprime"):
                    side = gr.Image(label="Vista laterale, tutti gli angoli", type="filepath")
                    iso = gr.Image(label="Assemblato", type="filepath")
                with gr.Tab("Pezzi"):
                    parts = gr.Dataframe(headers=["Pezzo", "Quantità", "Ingombro mm", "File"],
                                         interactive=False, wrap=True)
                    bom = gr.Dataframe(headers=["Q.tà", "Articolo", "Uso", "Scorta", ""],
                                       interactive=False, wrap=True, label="Ferramenta")
                with gr.Tab("Montaggio"):
                    montaggio = gr.Markdown()
                with gr.Tab("Verifica"):
                    verifica = gr.Markdown()
                with gr.Tab("Scarica"):
                    zipf = gr.File(label="Tutto (zip: STL, anteprime, ferramenta, istruzioni, parametri)")
                    stls = gr.File(label="Singoli STL", file_count="multiple")
        inputs = [preset, name, w, d, h, kg, angles, max_depth, lip_h, sp_min, sp_max, keep]
        preset.change(on_preset, preset, [name, w, d, h, kg, angles, lip_h, sp_min, sp_max, keep])
        btn.click(on_generate, inputs,
                  [key, status, viewer, angle, side, iso, parts, bom, montaggio, verifica, zipf, stls],
                  concurrency_limit=CONCURRENCY, concurrency_id="gen")
        angle.change(on_angle, [key, angle], viewer, concurrency_limit=CONCURRENCY, concurrency_id="gen")
    return demo


if __name__ == "__main__":
    pw = os.environ.get("APP_PASSWORD")
    build_ui().queue(max_size=20).launch(
        server_name=os.environ.get("HOST", "0.0.0.0"), server_port=int(os.environ.get("PORT", 7860)),
        allowed_paths=[DATA_DIR], auth=(os.environ.get("APP_USER", "admin"), pw) if pw else None,
        theme=gr.themes.Soft(), show_error=True)
