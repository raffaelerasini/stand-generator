"""Catalogo della viteria standard (vedi ../../VITERIA_STANDARD.md) e scelta delle viti.

Ogni giunto calcola la lunghezza che gli serve dalla geometria e prende la vite più adatta
dal catalogo. Se nessuna va bene, la scelta fallisce e il controllo lo segnala.
"""
from dataclasses import dataclass

WASHER_T = 1.0      # rondella 5x10
NUT_H = 4.0         # dado M5 normale
NYLOC_H = 5.0       # dado M5 autobloccante


@dataclass(frozen=True)
class Item:
    code: str        # chiave stabile
    name: str        # descrizione per la lista
    stock: int       # quantità nella scorta


# viti: (tipo, lunghezza) -> Item
SCREWS = {
    ("TCEI", 16): Item("M5x16", "Vite M5×16 brugola (DIN 912)", 30),
    ("TCEI", 20): Item("M5x20", "Vite M5×20 brugola (DIN 912)", 20),
    ("TCEI", 25): Item("M5x25", "Vite M5×25 brugola (DIN 912)", 15),
    ("TCEI", 30): Item("M5x30", "Vite M5×30 brugola (DIN 912)", 15),
    ("TE", 40): Item("M5x40TE", "Vite M5×40 testa esagonale (DIN 933)", 12),
    ("TE", 50): Item("M5x50TE", "Vite M5×50 testa esagonale (DIN 933)", 12),
}
NUT = Item("DADO_M5", "Dado M5", 60)
NYLOC = Item("NYLOC_M5", "Dado M5 autobloccante", 30)
WASHER = Item("RONDELLA_5x10", "Rondella M5 5×10", 100)
WASHER_L = Item("RONDELLA_5x20", "Rondella M5 larga 5×20", 15)

LENGTHS = sorted({l for _, l in SCREWS})


class NoScrew(ValueError):
    pass


def shortest_at_least(need, max_extra=None):
    """vite più corta con lunghezza >= need (mm). max_extra: sporgenza massima accettata."""
    for (kind, l), item in sorted(SCREWS.items(), key=lambda kv: kv[0][1]):
        if l >= need - 1e-6:
            if max_extra is not None and l - need > max_extra:
                break
            return l, item
    raise NoScrew(f"nessuna vite del catalogo è lunga {need:.1f} mm"
                  + (f" (con sporgenza max {max_extra} mm)" if max_extra is not None else ""))


def longest_at_most(limit, kinds=("TCEI",)):
    """vite più lunga con lunghezza <= limit (mm), solo dei tipi indicati."""
    best = None
    for (kind, l), item in SCREWS.items():
        if kind in kinds and l <= limit + 1e-6 and (best is None or l > best[0]):
            best = (l, item)
    if best is None:
        raise NoScrew(f"nessuna vite {'/'.join(kinds)} è lunga al massimo {limit:.1f} mm")
    return best


def screw_by_length(length):
    for (kind, l), item in SCREWS.items():
        if l == length:
            return item
    raise NoScrew(f"la M5×{length:g} non è nel catalogo standard (lunghezze: {LENGTHS})")


def screw_or_missing(length):
    """come screw_by_length, ma per una lunghezza fuori catalogo ritorna una voce con scorta 0"""
    try:
        return screw_by_length(length)
    except NoScrew:
        return Item(f"M5x{length:g}", f"Vite M5×{length:g} (NON nella scorta standard)", 0)


class Bom:
    """lista della ferramenta: righe (item, quantità, uso)."""

    def __init__(self):
        self.rows = []

    def add(self, item, qty, use):
        self.rows.append((item, qty, use))

    def totals(self):
        out = {}
        for item, qty, use in self.rows:
            if item.code not in out:
                out[item.code] = [item, 0, []]
            out[item.code][1] += qty
            out[item.code][2].append(use)
        return list(out.values())

    def shortages(self):
        return [(it, q) for it, q, _ in self.totals() if q > it.stock]

    def as_lines(self):
        return [f"{q}× {it.name} — {', '.join(dict.fromkeys(uses))}" for it, q, uses in self.totals()]

    def to_csv(self):
        lines = ["codice;descrizione;quantita;scorta;uso"]
        for it, q, uses in self.totals():
            lines.append(f"{it.code};{it.name};{q};{it.stock};{', '.join(dict.fromkeys(uses))}")
        return "\n".join(lines) + "\n"
