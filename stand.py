"""
Supporti inclinabili LOW PROFILE: comando sopra il motore `standgen`.

    python stand.py                       # tutti i profili predefiniti -> <profilo>/
    python stand.py virus_ti              # un profilo
    python stand.py --params mio.json --out mio   # parametri propri (tacche calcolate se mancano)
    python stand.py --no-preview ...      # senza anteprime PNG
    python stand.py --no-pdf ...          # senza istruzioni illustrate (istruzioni.pdf)

Profili predefiniti in standgen/model.py (PRESETS).
"""
import argparse
import os
import sys

from standgen import PRESETS, generate, load_params

HERE = os.path.dirname(os.path.abspath(__file__))


def run(name, params, out, previews, pdf=True):
    print(f"\n=== {name} ===")
    r = generate(params, out, name=name, previews=previews, make_zip=False, instructions=pdf)
    if r.tune is not None:
        print(f"  tacche calcolate: {r.tune.message} ({r.tune.seconds:.1f} s)")
    if r.stand is None:
        print("  !!!", r.message)
        return False
    i = r.report.info
    print(f"  profondità base {i['profondita_mm']:.0f} mm, piano davanti a {i['piano_davanti_mm']:.0f} mm, "
          f"~{i['filamento_g']} g PETG")
    for c in r.report.checks:
        if not c.ok:
            print(f"  {'!!!' if c.level == 'error' else ' ! '} {c.group} {c.label}: {c.detail}")
    print("  " + ("OK: verifica superata" if r.ok else "!!! NON VALIDO"))
    for l in r.stand.bom().as_lines():
        print("   -", l)
    return r.ok


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("profiles", nargs="*")
    ap.add_argument("--params")
    ap.add_argument("--out")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args(argv)
    ok = True
    if a.params:
        name = a.out or os.path.splitext(os.path.basename(a.params))[0]
        ok &= run(name, load_params(a.params), os.path.join(HERE, name), not a.no_preview, not a.no_pdf)
    else:
        for n in (a.profiles or list(PRESETS)):
            ok &= run(n, PRESETS[n], os.path.join(HERE, n), not a.no_preview, not a.no_pdf)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
