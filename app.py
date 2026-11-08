"""STAND, il sito: interfaccia HTML/CSS/JS in static/ sopra un'API FastAPI che usa standgen.

    python app.py            -> http://localhost:7860

Variabili d'ambiente:
    DATA_DIR        cartella dei risultati (default ./data)
    CACHE_MAX       quante generazioni tenere (default 40)
    APP_PASSWORD    se impostata, il sito chiede utente/password (utente: APP_USER, default "admin")
    CONCURRENCY     generazioni in parallelo (default 2)
"""
import base64
import hashlib
import json
import os
import secrets
import shutil
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from standgen import PRESETS, Stand, generate, load_params
from standgen.model import PRESET_GROUPS
from standgen import blueprint
from standgen.checks import summary
from standgen.pipeline import _jsonable, add_instructions

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
DATA_DIR = os.path.abspath(os.environ.get("DATA_DIR", os.path.join(HERE, "data")))
CACHE_DIR = os.path.join(DATA_DIR, "cache")
CACHE_MAX = int(os.environ.get("CACHE_MAX", 40))
CONCURRENCY = int(os.environ.get("CONCURRENCY", 2))
RESULT_VERSION = 3                      # cambia la chiave della cache quando cambia il formato del risultato
AUTO_KEYS = ("NOTCH_Z", "PIVOT_D", "PROP_L")
PRESET_GROUP = {k: g for g, ks in PRESET_GROUPS.items() for k in ks}
PART_NAMES = {"base": "Base", "deck": "Ripiano", "prop": "Asta",
              "crossbar": "Traversa", "crossbar_A": "Traversa A", "crossbar_B": "Traversa B"}

os.makedirs(CACHE_DIR, exist_ok=True)
_locks = {}
_locks_guard = threading.Lock()
_stands = OrderedDict()                 # piccola cache in memoria: chiave -> Stand
_jobs = {}                              # id -> stato del lavoro
_pool = ThreadPoolExecutor(max_workers=CONCURRENCY)


class BadInput(ValueError):
    pass


def _np_default(o):
    return o.item() if hasattr(o, "item") else str(o)


def fmt_angle(a):
    a = float(a)
    return str(int(a)) if a == int(a) else f"{a:g}"


# ---------------------------------------------------------------- parametri

def parse_angles(values):
    if isinstance(values, str):
        values = values.replace(";", ",").replace(" ", ",").split(",")
    try:
        angles = sorted({float(a) for a in values if str(a).strip()})
    except (TypeError, ValueError):
        raise BadInput("Angoli: servono dei numeri, per esempio 10, 20, 30")
    if not 1 <= len(angles) <= 6:
        raise BadInput("Servono da 1 a 6 angoli")
    if any(not 1 <= a <= 60 for a in angles):
        raise BadInput("Gli angoli devono stare tra 1° e 60°")
    return [int(a) if a == int(a) else a for a in angles]


def num(body, key, label, lo, hi, default=None, optional=False):
    v = body.get(key, default)
    if v in (None, "") and optional:
        return None
    try:
        v = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        raise BadInput(f"{label}: scrivi un numero")
    if not lo <= v <= hi:
        raise BadInput(f"{label}: deve stare tra {lo:g} e {hi:g}")
    return v


def build_params(body):
    """dal JSON del modulo ai parametri del motore (solleva BadInput con un messaggio leggibile)"""
    preset = body.get("preset") or None
    if preset and preset not in PRESETS:
        raise BadInput("Profilo sconosciuto")
    angles = parse_angles(body.get("angles", []))
    p = {}
    if preset:
        p = {k: v for k, v in PRESETS[preset].items() if k != "LABEL"}
        same_angles = [float(a) for a in p["ANGLES"]] == [float(a) for a in angles]
        if not (body.get("keep_notches", True) and same_angles):
            for k in AUTO_KEYS:
                p.pop(k, None)
    p.update(
        DEV_W=num(body, "w", "Larghezza", 80, 700),
        DEV_D=num(body, "d", "Profondità", 60, 500),
        DEV_H=num(body, "h", "Altezza", 5, 200),
        DEV_KG=num(body, "kg", "Peso", 0.1, 15),
        ANGLES=angles,
        LIP_H=num(body, "lip", "Bordino", 0, 60, default=p.get("LIP_H", 10)),
        MAX_DEPTH=num(body, "max_depth", "Profondità massima", 60, 600, optional=True),
    )
    sp_min = num(body, "sp_min", "Distanza minima tra i fianchi", 40, 800, optional=True)
    sp_max = num(body, "sp_max", "Distanza massima tra i fianchi", 40, 800, optional=True)
    if sp_min or sp_max:
        if not (sp_min and sp_max) or sp_max <= sp_min:
            raise BadInput("Distanza tra i fianchi: indica minimo e massimo (massimo > minimo), "
                           "oppure lascia vuoto per il calcolo automatico")
        p["SPACING_RANGE"] = (sp_min, sp_max)
    else:
        p["SPACING_RANGE"] = None
    return p


def params_key(p):
    blob = json.dumps(_jsonable({**p, "_v": RESULT_VERSION}), sort_keys=True, default=str)
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


def out_dir(key):
    if not key.isalnum() or len(key) != 16:
        raise HTTPException(404, "Risultato inesistente")
    d = os.path.join(CACHE_DIR, key)
    if not os.path.isfile(os.path.join(d, "risultato.json")):
        raise HTTPException(404, "Risultato inesistente o scaduto: rigeneralo")
    return d


def read_result(key):
    with open(os.path.join(out_dir(key), "risultato.json"), encoding="utf-8") as fh:
        return json.load(fh)


def get_stand(key):
    if key in _stands:
        _stands.move_to_end(key)
        return _stands[key]
    s = Stand(load_params(os.path.join(out_dir(key), "parametri.json")))
    _stands[key] = s
    while len(_stands) > 6:
        _stands.popitem(last=False)
    return s


# ---------------------------------------------------------------- generazione

def guide(s):
    """pagine del PDF con titolo, testo e ferramenta del passo (stesso ordine di ikea.instructions_pdf)"""
    sp = s.SPACING_RANGE
    pages = [
        {"kind": "Copertina", "title": "Supporto inclinabile",
         "text": "Il supporto montato, gli angoli disponibili e gli attrezzi: brugola da 4 mm e chiave da 8 mm."},
        {"kind": "Elenco", "title": "Pezzi da stampare",
         "text": "I pezzi da stampare, già orientati sul piatto. PETG, 4 pareti, gyroid 30–40 %, senza supporti."},
        {"kind": "Elenco", "title": "Ferramenta in scala 1:1",
         "text": "Appoggia le viti sul foglio per riconoscerle. Il righello da 100 mm conferma che hai stampato "
                 "al 100 %."},
    ]
    steps = []
    if s.SPLIT:
        steps.append({"title": "Unisci le traverse", "twice": True,
                      "text": "Sovrapponi le metà A e B nella zona a mezzo legno: i dadi nelle sedi esagonali "
                              "sotto A, le teste delle viti nelle lamature sopra B.",
                      "need": [[f"Vite M5×{s.splice_len}", 3], ["Dado M5", 3]]})
    steps.append({"title": "Traverse nelle basi",
                  "text": "Infila le due traverse nei tunnel delle basi, quello al centro e quello dietro. "
                          "Le alette forate guardano verso l'interno.", "need": []})
    steps.append({"title": "Fissa le traverse",
                  "text": f"Dado nel canale sotto la traversa, vite con rondella dall'alto. Prima regola le "
                          f"asole: fianchi tra {sp[0]:.0f} e {sp[1]:.0f} mm.",
                  "need": [[f"Vite M5×{s.BOLT_CB}", 4], ["Dado M5", 4], ["Rondella M5", 4]]})
    steps.append({"title": "Monta il ripiano", "twice": True,
                  "text": "Infila il ripiano tra le pareti della base, davanti. Vite della cerniera con la "
                          "rondella sotto la testa; il dado autobloccante va incassato nella sede esagonale "
                          "esterna.",
                  "need": [[f"Vite M5×{s.hinge_len}", 1], ["Dado autobloccante M5", 1], ["Rondella M5", 1]]})
    steps.append({"title": "Monta l'asta", "twice": True,
                  "text": "Inserisci l'asta nella forcella sul retro del ripiano e fissala con il perno. "
                          "Le orecchie del piede si appoggiano nelle tacche.",
                  "need": [[f"Vite M5×{s.pivot_len}", 1], ["Dado autobloccante M5", 1], ["Rondella M5", 2]]})
    order = sorted(s.ANGLES, key=lambda a: s.foot_pos(a)[0])
    steps.append({"title": "Cambia angolo",
                  "text": "Solleva il retro dello strumento, sposta il piede nella tacca voluta su entrambi i "
                          "lati e riabbassa. Tacche dalla più avanti alla più indietro: "
                          + ", ".join(f"{fmt_angle(a)}°" for a in order) + ".", "need": []})
    for i, st in enumerate(steps, 1):
        pages.append({"kind": f"Passo {i}", "step": i, **st})
    for p in pages:
        p.setdefault("need", [])
        p.setdefault("twice", False)
    return pages


def run(params, name, title, progress):
    """genera (o riprende dalla cache) e ritorna la chiave del risultato"""
    key = params_key({**params, "_name": name})
    out = os.path.join(CACHE_DIR, key)
    res_file = os.path.join(out, "risultato.json")
    with _lock(key):
        if os.path.exists(res_file):
            os.utime(out)
            return key
        t0 = time.time()
        steps = {"calcolo tacche": (0.08, "Calcolo le tacche"), "geometria": (0.4, "Costruisco i pezzi"),
                 "verifica": (0.5, "Controllo collisioni e stabilità"), "anteprime": (0.75, "Esporto")}
        r = generate(params, out, name=name, previews=False, glb=False,
                     progress=lambda st: progress(*steps.get(st, (0.5, st))))
        res = {"key": key, "name": name, "title": title or name, "ok": r.ok, "message": r.message,
               "tune": r.tune.message if r.tune else None,
               "tune_errors": r.tune.last_errors if r.tune else [],
               "device": {k: params.get(k) for k in ("DEV_W", "DEV_D", "DEV_H", "DEV_KG")},
               "input": {"w": params["DEV_W"], "d": params["DEV_D"], "h": params["DEV_H"], "kg": params["DEV_KG"],
                         "angles": [fmt_angle(a) for a in params["ANGLES"]], "lip": params.get("LIP_H"),
                         "max_depth": params.get("MAX_DEPTH"),
                         "sp_min": (params.get("SPACING_RANGE") or (None, None))[0],
                         "sp_max": (params.get("SPACING_RANGE") or (None, None))[1]}}
        if r.stand is not None:
            s = r.stand
            _stands[key] = s
            sm = summary(s)
            res.update(
                angles=[fmt_angle(a) for a in s.ANGLES],
                summary={k: sm[k] for k in ("profondita_mm", "piano_davanti_mm", "bordino_mm", "filamento_g")},
                spacing=[round(v) for v in s.SPACING_RANGE],
                split=bool(s.SPLIT),
                parts=[{"file": n, "name": PART_NAMES.get(n.rpartition("_x")[0], n),
                        "qty": int(n.rpartition("_x")[2] or 1), "size": [round(v) for v in dims]}
                       for n, dims in sm["pezzi"].items()],
                bom=[{"qty": q, "item": it.name, "use": ", ".join(dict.fromkeys(uses)), "stock": it.stock}
                     for it, q, uses in s.bom().totals()],
                checks=[{"group": c.group, "label": c.label, "ok": bool(c.ok), "detail": str(c.detail or ""), "level": c.level}
                        for c in r.report.checks],
                guide=guide(s),
                files={k: os.path.relpath(v, out).replace(os.sep, "/") for k, v in r.files.items()},
            )
            progress(0.85, "Disegno la vista")
            web = os.path.join(out, "web")
            os.makedirs(web, exist_ok=True)
            blueprint.hero(s, os.path.join(web, "hero.png"))
        res["seconds"] = round(time.time() - t0, 1)
        os.makedirs(out, exist_ok=True)
        tmp = res_file + ".tmp"                      # scrittura atomica: mai un risultato a metà
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1, default=_np_default)
        os.replace(tmp, res_file)
    _prune_cache()
    return key


def make_pdf(key, progress):
    out = out_dir(key)
    res = read_result(key)
    if "summary" not in res:
        raise BadInput("Questo supporto non è valido: niente istruzioni")
    pdf = os.path.join(out, "istruzioni.pdf")
    pdir = os.path.join(out, "istruzioni")
    with _lock(key):
        if not (os.path.exists(pdf) and os.path.isdir(pdir)):
            progress(0.1, "Disegno le istruzioni")
            add_instructions(get_stand(key), out, res["name"], res.get("title"))
    return key


def submit(fn, *args):
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "state": "queued", "progress": 0.0, "stage": "In coda", "started": time.time()}
    _jobs[jid] = job

    def progress(frac, stage):
        job.update(progress=round(float(frac), 2), stage=stage)

    def work():
        job["state"] = "running"
        try:
            job["key"] = fn(*args, progress)
            job.update(state="done", progress=1.0, stage="Fatto")
        except BadInput as e:
            job.update(state="error", error=str(e))
        except Exception as e:                       # noqa: BLE001 - il messaggio va all'utente
            job.update(state="error", error=f"Errore interno: {e}")
        job["seconds"] = round(time.time() - job["started"], 1)

    _pool.submit(work)
    # tieni solo gli ultimi lavori
    for old in list(_jobs)[:-200]:
        _jobs.pop(old, None)
    return job


# ---------------------------------------------------------------- API

app = FastAPI(title="STAND", docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1000)

_PW = os.environ.get("APP_PASSWORD")
_USER = os.environ.get("APP_USER", "admin")


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if _PW and request.url.path != "/healthz":
        ok = False
        h = request.headers.get("authorization", "")
        if h.startswith("Basic "):
            try:
                u, _, p = base64.b64decode(h[6:]).decode().partition(":")
                ok = secrets.compare_digest(u, _USER) and secrets.compare_digest(p, _PW)
            except Exception:                        # noqa: BLE001
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="STAND"'})
    return await call_next(request)


@app.exception_handler(BadInput)
async def bad_input(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/presets")
def presets():
    out = []
    for k, p in PRESETS.items():
        sp = p.get("SPACING_RANGE") or (None, None)
        out.append({"id": k, "label": p["LABEL"], "group": PRESET_GROUP.get(k, "Altro"), "w": p["DEV_W"], "d": p["DEV_D"], "h": p["DEV_H"],
                    "kg": p["DEV_KG"], "angles": [fmt_angle(a) for a in p["ANGLES"]], "lip": p.get("LIP_H", 10),
                    "sp_min": sp[0], "sp_max": sp[1], "max_depth": p.get("MAX_DEPTH")})
    return out


@app.post("/api/generate")
async def api_generate(request: Request):
    body = await request.json()
    params = build_params(body)
    preset = body.get("preset") or None
    title = (body.get("title") or "").strip() or (PRESETS[preset]["LABEL"] if preset else "Strumento personalizzato")
    name = safe_name(body.get("name") or preset or title)
    key = params_key({**params, "_name": name})
    if os.path.isfile(os.path.join(CACHE_DIR, key, "risultato.json")):
        os.utime(os.path.join(CACHE_DIR, key))
        return {"key": key, "cached": True}
    return submit(run, params, name, title)


@app.get("/api/jobs/{jid}")
def api_job(jid: str):
    job = _jobs.get(jid)
    if not job:
        raise HTTPException(404, "Lavoro sconosciuto")
    return job


@app.get("/api/result/{key}")
def api_result(key: str):
    res = read_result(key)
    pdir = os.path.join(out_dir(key), "istruzioni")
    res["pdf"] = os.path.isfile(os.path.join(out_dir(key), "istruzioni.pdf"))
    res["pages"] = sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []
    return res


@app.post("/api/pdf/{key}")
def api_pdf(key: str):
    out_dir(key)
    if os.path.isfile(os.path.join(CACHE_DIR, key, "istruzioni.pdf")) and \
            os.path.isdir(os.path.join(CACHE_DIR, key, "istruzioni")):
        return {"key": key, "cached": True}
    return submit(make_pdf, key)


def _angle_of(s, text):
    for a in s.ANGLES:
        if fmt_angle(a) == text:
            return a
    raise HTTPException(404, "Angolo non previsto per questo supporto")


def _cached_file(key, rel, build):
    f = os.path.join(out_dir(key), "web", rel)
    if not os.path.exists(f):
        with _lock(key):
            if not os.path.exists(f):
                os.makedirs(os.path.dirname(f), exist_ok=True)
                root, ext = os.path.splitext(f)
                tmp = root + ".tmp" + ext
                build(tmp)
                os.replace(tmp, f)
    return f


@app.get("/api/draw/{key}/{what}.png")
def api_draw(key: str, what: str):
    s = get_stand(key)
    if what == "hero":
        f = _cached_file(key, "hero.png", lambda p: blueprint.hero(s, p))
    elif what.startswith("side_"):
        a = _angle_of(s, what[5:])
        f = _cached_file(key, f"side_{fmt_angle(a)}.png", lambda p: blueprint.side(s, p, a))
    elif what.startswith("part_"):
        name = what[5:]
        if name not in s.print_parts():
            raise HTTPException(404, "Pezzo sconosciuto")
        f = _cached_file(key, f"part_{name}.png", lambda p: blueprint.part(s, name, p))
    else:
        raise HTTPException(404, "Disegno sconosciuto")
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/mesh/{key}/{angle}.json")
def api_mesh(key: str, angle: str):
    s = get_stand(key)
    a = _angle_of(s, angle)

    def build(p):
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(blueprint.web_mesh(s, a), fh, separators=(",", ":"))

    f = _cached_file(key, f"mesh_{fmt_angle(a)}.json", build)
    return FileResponse(f, media_type="application/json", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/files/{key}/{path:path}")
def api_file(key: str, path: str):
    base = out_dir(key)
    f = os.path.realpath(os.path.join(base, path))
    if not f.startswith(os.path.realpath(base) + os.sep) or not os.path.isfile(f) or "/web/" in f.replace(os.sep, "/"):
        raise HTTPException(404, "File inesistente")
    name = os.path.basename(f)
    if path.startswith("stl/") or name.endswith((".zip", ".csv")):
        return FileResponse(f, filename=name)
    return FileResponse(f)


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 7860)))
