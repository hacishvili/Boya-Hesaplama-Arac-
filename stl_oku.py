# -*- coding: utf-8 -*-
"""STL okuma (ikili ve metin). STL'de birim yazmaz; mm sayılır, pencere değiştirtir.

Eğri yüzeyler üçgenlerle yaklaşıktır (kiriş hatası): alan gerçek yüzeyden biraz küçük çıkar; ince ağda fark
binde birin altındadır."""
from __future__ import annotations

import struct
from typing import List, Tuple

from geometri import Ag


def ucgenler(yol: str) -> List[List[Tuple[float, float, float]]]:
    with open(yol, "rb") as f:
        veri = f.read()
    if len(veri) >= 84:
        n = struct.unpack_from("<I", veri, 80)[0]
        if 84 + 50 * n == len(veri):
            out = []
            for kayit in struct.iter_unpack("<12fH", veri[84:84 + 50 * n]):
                out.append([kayit[3:6], kayit[6:9], kayit[9:12]])
            return out
    metin = veri.decode("utf-8", errors="replace")
    if "facet" not in metin or "vertex" not in metin:
        raise ValueError("STL dosyası okunamadı (ne ikili ne metin STL).")
    out, yuz = [], []
    for satir in metin.splitlines():
        p = satir.split()
        if p and p[0] == "vertex" and len(p) >= 4:
            yuz.append((float(p[1]), float(p[2]), float(p[3])))
        elif p and p[0] == "endfacet":
            if len(yuz) >= 3:
                out.append(yuz)
            yuz = []
    return out


def govdeler(yol: str, olcek: float = 1.0) -> List[Ag]:
    """Dosyadaki her ayrık gövde ayrı (ortak köşesi olmayan üçgen grupları)."""
    tri = ucgenler(yol)
    if olcek != 1.0:
        tri = [[(x * olcek, y * olcek, z * olcek) for x, y, z in t] for t in tri]
    return Ag(tri).govdeler()
