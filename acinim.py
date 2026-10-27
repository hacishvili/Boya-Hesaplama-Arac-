# -*- coding: utf-8 -*-
"""Konik (kesik koni) ve silindirik sac parçaların açınımı, DXF olarak.

Açınım nötr eksen üzerinden: R_n = R_iç + K · t (K = 0,5: sac kalınlığının ortası). Çaplar dış, orta ya da iç
yüzeyden verilebilir. Uçların eksene dik kesildiği varsayılır.

  kesik koni: eğik boy s = √(H² + (R₂ − R₁)²), dış yay yarıçapı Rb = s · R₂ / (R₂ − R₁), iç yay Ra = Rb − s,
              dilim açısı θ = 360° · R₂ / Rb   (yay uzunlukları π D₁ₙ ve π D₂ₙ)
  silindir:   dikdörtgen π Dₙ × H"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

OLCULER = ("dış", "orta", "iç")


@dataclass
class Acinim:
    d1: float          # nötr çaplar (mm), d1 ≤ d2
    d2: float
    boy: float         # eksen boyu (H)
    t: float
    silindir: bool
    Ra: float = 0.0    # koni: iç yay yarıçapı
    Rb: float = 0.0    # koni: dış yay yarıçapı
    aci: float = 0.0   # koni: dilim açısı (derece)
    egik: float = 0.0  # eğik boy

    @property
    def alan(self) -> float:
        """Açınımın (bir yüz) alanı, mm²: π (R₁ + R₂) s."""
        if self.silindir:
            return math.pi * self.d1 * self.boy
        return math.pi * (self.d1 + self.d2) / 2 * self.egik

    @property
    def olcu(self) -> Tuple[float, float]:
        """Sacın kesileceği dikdörtgen (en × boy, mm)."""
        if self.silindir:
            return math.pi * self.d1, self.boy
        x, y = zip(*self.cevre(720))
        return max(x) - min(x), max(y) - min(y)

    def cevre(self, n: int = 180) -> List[Tuple[float, float]]:
        """Kapalı dış çizgi (önizleme ve ölçü için). Koni: tepe noktası (0, 0), dilim y eksenine simetrik."""
        if self.silindir:
            w = math.pi * self.d1
            return [(0.0, 0.0), (w, 0.0), (w, self.boy), (0.0, self.boy)]
        y = math.radians(self.aci) / 2
        a0, a1 = math.pi / 2 - y, math.pi / 2 + y
        dis = [(self.Rb * math.cos(a0 + (a1 - a0) * i / n), self.Rb * math.sin(a0 + (a1 - a0) * i / n))
               for i in range(n + 1)]
        ic = [(self.Ra * math.cos(a1 - (a1 - a0) * i / n), self.Ra * math.sin(a1 - (a1 - a0) * i / n))
              for i in range(n + 1)]
        return dis + ic


def hesapla(d_alt: float, d_ust: float, boy: float, t: float, olcu: str = "dış", k: float = 0.5) -> Acinim:
    """d_alt, d_ust: çaplar (olcu yüzeyinden), boy: eksen boyu, t: sac kalınlığı (mm)."""
    if boy <= 0 or t < 0 or min(d_alt, d_ust) <= 0:
        raise ValueError("Çaplar ve boy sıfırdan büyük, kalınlık sıfır ya da büyük olmalı.")
    if not 0.0 <= k <= 1.0:
        raise ValueError("K faktörü 0 ile 1 arasında olmalı.")
    kaydir = {"dış": -(1.0 - k) * t, "orta": (k - 0.5) * t, "iç": k * t}[olcu] * 2  # çapa
    d1, d2 = sorted((d_alt + kaydir, d_ust + kaydir))
    if d1 <= 0:
        raise ValueError("Sac kalınlığı çapa göre çok büyük.")
    if abs(d2 - d1) < 1e-9:
        return Acinim(d1, d2, boy, t, True)
    r1, r2 = d1 / 2, d2 / 2
    s = math.hypot(boy, r2 - r1)
    Rb = s * r2 / (r2 - r1)
    return Acinim(d1, d2, boy, t, False, Ra=Rb - s, Rb=Rb, aci=360.0 * r2 / Rb, egik=s)


def dxf_yaz(yol: str, a: Acinim, baslik: str = "") -> None:
    """Açınımı DXF'e yazar (mm): ACINIM katmanında kesim çizgisi, BILGI katmanında ölçüler."""
    import ezdxf
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.layers.add("ACINIM", color=7)
    doc.layers.add("BILGI", color=3)
    m = doc.modelspace()
    k = {"layer": "ACINIM"}
    if a.silindir:
        m.add_lwpolyline(a.cevre(), close=True, dxfattribs=k)
    else:
        y = a.aci / 2
        a0, a1 = 90.0 - y, 90.0 + y
        m.add_arc((0, 0), a.Rb, a0, a1, dxfattribs=k)
        m.add_arc((0, 0), a.Ra, a0, a1, dxfattribs=k)
        for aci in (a0, a1):
            c, s = math.cos(math.radians(aci)), math.sin(math.radians(aci))
            m.add_line((a.Ra * c, a.Ra * s), (a.Rb * c, a.Rb * s), dxfattribs=k)
    xs, ys = zip(*a.cevre(360))
    alt_x, alt_y = min(xs), min(ys) - 15.0
    satir = [baslik or "Açınım", f"t = {a.t:g} mm, nötr çaplar Ø{a.d1:.2f} / Ø{a.d2:.2f}, boy {a.boy:g} mm"]
    if not a.silindir:
        satir.append(f"R iç {a.Ra:.2f}  R dış {a.Rb:.2f}  açı {a.aci:.3f}°  eğik boy {a.egik:.2f}")
    w, h = a.olcu
    satir.append(f"sac ölçüsü {w:.1f} × {h:.1f} mm, alan {a.alan / 1e6:.4f} m² (bir yüz)")
    for i, s in enumerate(satir):
        m.add_text(s, height=5 if i == 0 else 3.5, dxfattribs={"layer": "BILGI"}).set_placement(
            (alt_x, alt_y - i * 7))
    doc.saveas(yol)
