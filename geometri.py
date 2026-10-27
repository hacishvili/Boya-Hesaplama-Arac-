# -*- coding: utf-8 -*-
"""Saf geometri: kapalı konturların alanı ve çevresi, iç içe yerleşim (parça / delik), açık çizgilerin
uç uca eklenip kontura dönmesi, üçgen / çokgen ağların alanı, kapalılığı ve gövdelere ayrılması.

Bütün uzunluklar mm, alanlar mm²; DXF birimi okuyucuda mm'ye çevrilir."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

Nokta = Tuple[float, float]
Nokta3 = Tuple[float, float, float]


# ---------------------------------------------------------------- 2D kontur

def isaretli_alan(pts: Sequence[Nokta]) -> float:
    """Kapalı çokgenin işaretli alanı (saat yönünün tersi +). Son nokta ilkini tekrar etmek zorunda değil."""
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    x0, y0 = pts[-1]
    for x1, y1 in pts:
        s += x0 * y1 - x1 * y0
        x0, y0 = x1, y1
    return 0.5 * s


def cevre(pts: Sequence[Nokta], kapali: bool = True) -> float:
    n = len(pts)
    if n < 2:
        return 0.0
    s = sum(math.dist(pts[i], pts[i + 1]) for i in range(n - 1))
    if kapali:
        s += math.dist(pts[-1], pts[0])
    return s


def icinde_mi(x: float, y: float, pts: Sequence[Nokta]) -> bool:
    """Işın yöntemi; sınırın üstündeki nokta iki taraftan birine düşer."""
    ic = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y):
            xk = xi + (y - yi) * (xj - xi) / (yj - yi)
            if x < xk:
                ic = not ic
        j = i
    return ic


@dataclass
class Kontur:
    noktalar: List[Nokta]
    katman: str = ""

    def __post_init__(self):
        if len(self.noktalar) > 1 and math.dist(self.noktalar[0], self.noktalar[-1]) < 1e-12:
            self.noktalar = self.noktalar[:-1]
        self.alan = abs(isaretli_alan(self.noktalar))
        self.cevre = cevre(self.noktalar)
        xs = [p[0] for p in self.noktalar] or [0.0]
        ys = [p[1] for p in self.noktalar] or [0.0]
        self.kutu = (min(xs), min(ys), max(xs), max(ys))

    def icinde(self, diger: "Kontur") -> bool:
        """diger bu konturun içinde mi: kutu, sonra köşelerin çoğu (en çok 7 örnek) içeride."""
        a, b = self.kutu, diger.kutu
        if b[0] < a[0] - 1e-9 or b[1] < a[1] - 1e-9 or b[2] > a[2] + 1e-9 or b[3] > a[3] + 1e-9:
            return False
        pts = diger.noktalar
        adim = max(1, len(pts) // 7)
        ornek = pts[::adim][:7]
        say = sum(1 for p in ornek if icinde_mi(p[0], p[1], self.noktalar))
        return say * 2 > len(ornek)


@dataclass
class Parca2D:
    """Bir dış kontur ve içindeki delikler (sac açınımı ya da levha)."""
    dis: Kontur
    delikler: List[Kontur] = field(default_factory=list)

    @property
    def yuz_alani(self) -> float:
        return self.dis.alan - sum(d.alan for d in self.delikler)

    @property
    def toplam_cevre(self) -> float:
        return self.dis.cevre + sum(d.cevre for d in self.delikler)

    @property
    def olcu(self) -> Tuple[float, float]:
        k = self.dis.kutu
        return k[2] - k[0], k[3] - k[1]


def yerlestir(konturlar: Iterable[Kontur]) -> List[Parca2D]:
    """İç içe konturlardan parçalar: derinliği çift olan kontur parça, onun hemen içindekiler delik.
    Delik içindeki ada yine ayrı parçadır. Aynı konturun kopyaları (üst üste çizilmiş) bir sayılır."""
    tekil: List[Kontur] = []
    for k in sorted(konturlar, key=lambda k: -k.alan):
        if k.alan <= 1e-9:
            continue
        if any(abs(k.alan - t.alan) <= 1e-6 * max(1.0, t.alan)
               and all(abs(a - b) <= 1e-4 for a, b in zip(k.kutu, t.kutu)) for t in tekil):
            continue
        tekil.append(k)
    ebeveyn: List[Optional[int]] = []
    for i, k in enumerate(tekil):
        p = None
        for j in range(i - 1, -1, -1):  # büyükten küçüğe sıralı: en yakın (en küçük) kapsayan
            if tekil[j].alan > k.alan and tekil[j].icinde(k):
                p = j
                break
        ebeveyn.append(p)
    derinlik = []
    for i in range(len(tekil)):
        d, p = 0, ebeveyn[i]
        while p is not None:
            d += 1
            p = ebeveyn[p]
        derinlik.append(d)
    parcalar: Dict[int, Parca2D] = {}
    for i, k in enumerate(tekil):
        if derinlik[i] % 2 == 0:
            parcalar[i] = Parca2D(k)
    for i, k in enumerate(tekil):
        if derinlik[i] % 2 == 1:
            parcalar[ebeveyn[i]].delikler.append(k)
    return [parcalar[i] for i in sorted(parcalar)]


def zincirle(parcalar: Sequence[Sequence[Nokta]], tol: float = 0.01) -> Tuple[List[List[Nokta]], int]:
    """Açık çizgileri (çizgi, yay, açık polyline) uçlarından birleştirip kapalı konturlar yapar.
    Dönüş: (konturlar, kullanılamayan çizgi sayısı). Bir konturun ortasına değen ya da boşta kalan
    çizgiler (büküm çizgisi, eksen) ayıklanır; üst üste çizilmiş kopya çizgiler bir sayılır.
    Üç ve daha çok çizginin buluştuğu düğüm çözülemez; o bölüm kullanılamayan sayılır."""
    kova: Dict[Tuple[int, int], List[int]] = {}
    dugum_xy: List[Nokta] = []

    def dugum(p: Nokta) -> int:
        kx, ky = int(math.floor(p[0] / tol)), int(math.floor(p[1] / tol))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for n in kova.get((kx + dx, ky + dy), ()):
                    if math.dist(dugum_xy[n], p) <= tol:
                        return n
        n = len(dugum_xy)
        dugum_xy.append(p)
        kova.setdefault((kx, ky), []).append(n)
        return n

    kenarlar: List[Tuple[int, int, List[Nokta]]] = []
    gorulen = set()
    for pts in parcalar:
        if len(pts) < 2:
            continue
        a, b = dugum(pts[0]), dugum(pts[-1])
        orta = pts[len(pts) // 2] if len(pts) > 2 else ((pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2)
        anahtar = (min(a, b), max(a, b), round(orta[0] / tol), round(orta[1] / tol))
        if anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        kenarlar.append((a, b, list(pts)))  # a == b: kendi üstüne kapanan çizgi, tek başına kontur

    canli = [True] * len(kenarlar)
    komsu: Dict[int, List[int]] = {}
    for i, (a, b, _) in enumerate(kenarlar):
        komsu.setdefault(a, []).append(i)
        komsu.setdefault(b, []).append(i)

    def derece(n: int) -> int:
        return sum(1 for e in komsu.get(n, ()) if canli[e])

    # boşta kalan uçları budayarak sil
    yigin = [n for n in komsu if derece(n) == 1]
    budanan = 0
    while yigin:
        n = yigin.pop()
        if derece(n) != 1:
            continue
        e = next(e for e in komsu[n] if canli[e])
        canli[e] = False
        budanan += 1
        a, b, _ = kenarlar[e]
        diger = b if a == n else a
        if derece(diger) == 1:
            yigin.append(diger)

    konturlar: List[List[Nokta]] = []
    cozulemeyen = 0
    for i in range(len(kenarlar)):
        if not canli[i]:
            continue
        # bileşeni topla
        bilesen, ugr, dugumler = [], [i], set()
        canli_bilesen = set()
        while ugr:
            e = ugr.pop()
            if e in canli_bilesen or not canli[e]:
                continue
            canli_bilesen.add(e)
            bilesen.append(e)
            for n in kenarlar[e][:2]:
                dugumler.add(n)
                ugr.extend(x for x in komsu[n] if canli[x] and x not in canli_bilesen)
        for e in bilesen:
            canli[e] = False
        if any(sum(1 for e in komsu[n] if e in canli_bilesen) != 2 for n in dugumler):
            cozulemeyen += len(bilesen)
            continue
        # tek döngü: yürü
        e0 = bilesen[0]
        a, b, pts = kenarlar[e0]
        yol = list(pts)
        bas, simdi, onceki = a, b, e0
        kullanilan = {e0}
        while simdi != bas:
            e = next(x for x in komsu[simdi] if x in canli_bilesen and x != onceki and x not in kullanilan)
            ea, eb, epts = kenarlar[e]
            if ea == simdi:
                yol.extend(epts[1:])
                simdi = eb
            else:
                yol.extend(list(reversed(epts))[1:])
                simdi = ea
            kullanilan.add(e)
            onceki = e
        konturlar.append(yol)
    return konturlar, budanan + cozulemeyen


# ---------------------------------------------------------------- 3D ağ

def _cikar(a: Nokta3, b: Nokta3) -> Nokta3:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _carp(a: Nokta3, b: Nokta3) -> Nokta3:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def vektor_alan(pts: Sequence[Nokta3]) -> Nokta3:
    """Düzlemsel çokgenin vektör alanı (yarım Σ pᵢ × pᵢ₊₁); büyüklüğü alan, yönü normal."""
    sx = sy = sz = 0.0
    n = len(pts)
    for i in range(n):
        c = _carp(pts[i], pts[(i + 1) % n])
        sx += c[0]
        sy += c[1]
        sz += c[2]
    return 0.5 * sx, 0.5 * sy, 0.5 * sz


def cokgen_alani(pts: Sequence[Nokta3]) -> float:
    return math.sqrt(sum(c * c for c in vektor_alan(pts)))


@dataclass
class Ag:
    """Çokgen yüzlerden ağ (3DFACE, polyface, MESH, STL, düz yüzlü ACIS). yuzler: köşe listeleri."""
    yuzler: List[List[Nokta3]]
    ad: str = ""
    alan_hazir: Optional[float] = None  # doğrudan hesaplanmış alan (mm²; ACIS katılar)
    tel: bool = False                   # yuzler yalnız kenar döngüleri (önizlemede doldurulmaz)
    kapali_hazir: Optional[bool] = None

    @property
    def alan(self) -> float:
        if self.alan_hazir is not None:
            return self.alan_hazir
        return sum(cokgen_alani(y) for y in self.yuzler)

    def _anahtar(self, p: Nokta3, tol: float) -> Tuple[int, int, int]:
        return round(p[0] / tol), round(p[1] / tol), round(p[2] / tol)

    def kapali_mi(self, tol: float = 1e-4) -> bool:
        """Her kenar tam iki yüzde mi (su geçirmez kabuk). Açık yüzey modeli sacın tek yüzü olabilir."""
        if self.kapali_hazir is not None:
            return self.kapali_hazir
        say: Dict[Tuple, int] = {}
        for y in self.yuzler:
            ks = [self._anahtar(p, tol) for p in y]
            for i in range(len(ks)):
                a, b = ks[i], ks[(i + 1) % len(ks)]
                if a == b:
                    continue
                k = (a, b) if a < b else (b, a)
                say[k] = say.get(k, 0) + 1
        return bool(say) and all(v == 2 for v in say.values())

    def kutu(self) -> Tuple[Nokta3, Nokta3]:
        pts = [p for y in self.yuzler for p in y] or [(0.0, 0.0, 0.0)]
        return (tuple(min(p[i] for p in pts) for i in range(3)),
                tuple(max(p[i] for p in pts) for i in range(3)))

    def govdeler(self, tol: float = 1e-4) -> List["Ag"]:
        """Ortak köşesi olan yüzleri bir gövdede toplar (bir dosyada birden çok parça)."""
        ata = list(range(len(self.yuzler)))

        def bul(i):
            while ata[i] != i:
                ata[i] = ata[ata[i]]
                i = ata[i]
            return i

        sahip: Dict[Tuple, int] = {}
        for i, y in enumerate(self.yuzler):
            for p in y:
                k = self._anahtar(p, tol)
                j = sahip.setdefault(k, i)
                ri, rj = bul(i), bul(j)
                if ri != rj:
                    ata[ri] = rj
        gruplar: Dict[int, List[List[Nokta3]]] = {}
        for i, y in enumerate(self.yuzler):
            gruplar.setdefault(bul(i), []).append(y)
        return [Ag(g) for g in gruplar.values()]
