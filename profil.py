# -*- coding: utf-8 -*-
"""Profil gövdelerde yüzlerin otomatik tanınması: dış yüzey, iç (boşluk) yüzeyi, uç kesitleri.

Profil: bir eksen boyunca uzanan (boyu kesitinin en az 2,5 katı) gövde: kutu / yuvarlak boru, dolu çubuk, lama.
  1. Eksen: profil eksenine paralel silindir yüzü varsa onun ekseni; yoksa yüz normalleri eksene dik büyük iki
     düzlemin normallerinin vektörel çarpımı; o da yoksa noktaların ana ekseni.
  2. Gövde ortasından eksene dik kesit alınır: yanal yüzlerin kesitteki parçaları (doğru parçası, yay, tam daire)
     uç uca eklenip kesit konturları kurulur; içteki konturlar (delik) boşluğun duvarlarıdır.
  3. Kesiti geçen yüz: kontur dışsa "dış", delikse "iç". Kesiti geçmeyen ve normali eksene yakın düz yüz "uç"
     (düz ya da gönyeli kesim); geri kalanlar (delik, pah ...) "dış" sayılır.
İç yüzeyin uçlardan h derinliğe kadar boyanan kısmı: Σ alan · min(2h, L) / L (L: o yüzün eksen boyu)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from geometri import Kontur, yerlestir, zincirle

V3 = Tuple[float, float, float]


def _cik(a, b):
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _ic(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _dis(a, b):
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def _birim(a):
    n = math.sqrt(_ic(a, a))
    return (a[0] / n, a[1] / n, a[2] / n) if n > 0 else (0.0, 0.0, 0.0)


@dataclass
class YuzBilgi:
    alan: float                       # mm²
    donguler: List[List[V3]]          # dünya koordinatında (mm)
    tur: str                          # duzlem / koni / kure / torus / spline / ag
    normal: Optional[V3] = None       # düzlem
    eksen: Optional[V3] = None        # koni / silindir
    merkez: Optional[V3] = None
    r0: float = 0.0                   # koni: merkezdeki yarıçap; ρ(h) = r0 + egim h
    egim: float = 0.0


@dataclass
class Profil:
    boy: float                        # eksen boyunca (mm)
    kesit: Tuple[float, float]        # kesitin dış ölçüleri (mm)
    dis: float = 0.0                  # mm²
    uc: float = 0.0
    ic: List[Tuple[float, float]] = field(default_factory=list)   # iç yüzler: (alan, eksen boyu)
    bosluk: float = 0.0               # boşluğun en büyük kesit ölçüsü (iç boya derinliği varsayılanı)

    @property
    def ic_alan(self) -> float:
        return sum(a for a, _ in self.ic)

    def ic_boyanan(self, derinlik: float) -> float:
        """İç yüzeyin iki uçtan derinlik kadar giren kısmı."""
        return sum(a * min(1.0, 2.0 * max(derinlik, 0.0) / L) if L > 0 else a for a, L in self.ic)

    def sozluk(self) -> Dict:
        return {"boy": self.boy, "kesit": list(self.kesit), "dis": self.dis, "uc": self.uc,
                "ic": [list(x) for x in self.ic], "bosluk": self.bosluk}


def profil_alani(p: Dict, ic_boya: str, derinlik: float, uc_boya: bool) -> float:
    """Kaynak sözlüğündeki profil verisinden boyanacak alan (mm²)."""
    ic = p.get("ic", [])
    if ic_boya == "tamamı":
        ic_alan = sum(a for a, _ in ic)
    elif ic_boya == "boyanmaz":
        ic_alan = 0.0
    else:
        ic_alan = sum(a * min(1.0, 2.0 * max(derinlik, 0.0) / L) if L > 0 else a for a, L in ic)
    return p.get("dis", 0.0) + (p.get("uc", 0.0) if uc_boya else 0.0) + ic_alan


def _eksen(yuzler: Sequence[YuzBilgi]) -> Optional[V3]:
    pts = [q for y in yuzler for d in y.donguler for q in d]
    if len(pts) < 4:
        return None
    # noktaların ana ekseni (kovaryansın en büyük öz vektörü, kuvvet yöntemiyle)
    n = len(pts)
    c = tuple(sum(p[i] for p in pts) / n for i in range(3))
    C = [[sum((p[i] - c[i]) * (p[j] - c[j]) for p in pts) / n for j in range(3)] for i in range(3)]
    v = (1.0, 0.7, 0.3)
    for _ in range(100):
        w = tuple(sum(C[i][j] * v[j] for j in range(3)) for i in range(3))
        v = _birim(w)
        if v == (0.0, 0.0, 0.0):
            return None
    ana = v
    # silindir ekseni ana eksene yakınsa ondan (kesin)
    koniler = sorted((y for y in yuzler if y.tur == "koni" and y.eksen is not None and abs(_ic(y.eksen, ana)) > 0.98),
                     key=lambda y: -y.alan)
    if koniler:
        e = koniler[0].eksen
        return e if _ic(e, ana) > 0 else (-e[0], -e[1], -e[2])
    # eksene dik büyük iki düzlem: normallerinin çarpımı
    duz = sorted((y for y in yuzler if y.tur == "duzlem" and y.normal is not None and abs(_ic(y.normal, ana)) < 0.1),
                 key=lambda y: -y.alan)
    for i in range(len(duz)):
        for j in range(i + 1, len(duz)):
            x = _dis(duz[i].normal, duz[j].normal)
            if math.sqrt(_ic(x, x)) > 0.3:
                e = _birim(x)
                return e if _ic(e, ana) > 0 else (-e[0], -e[1], -e[2])
    return ana


def coz(yuzler: Sequence[YuzBilgi], oran: float = 2.5) -> Optional[Profil]:
    """Gövde profilse yüzlerinin sınıflaması; değilse None."""
    a = _eksen(yuzler)
    if a is None:
        return None
    e1 = _birim(_dis(a, (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)))
    e2 = _dis(a, e1)
    pts = [q for y in yuzler for d in y.donguler for q in d]
    s = [_ic(q, a) for q in pts]
    u = [_ic(q, e1) for q in pts]
    v = [_ic(q, e2) for q in pts]
    boy = max(s) - min(s)
    kesit = (max(u) - min(u), max(v) - min(v))
    if boy < oran * max(kesit) or max(kesit) <= 0:
        return None
    orta = 0.5 * (max(s) + min(s))
    tol = max(kesit) * 1e-3

    def iki_b(q):
        return _ic(q, e1), _ic(q, e2)

    # 2. kesit: her yanal yüzün ortadaki izi
    parcalar: List[List[Tuple[float, float]]] = []   # zincirlenecek parçalar
    daireler: List[Tuple[int, Kontur]] = []          # tam daire izi olan yüzler
    iz: Dict[int, Optional[tuple]] = {}              # yüz → kesitteki izi (iki uç; daire için None)
    for i, y in enumerate(yuzler):
        kes = []
        for d in y.donguler:
            for j in range(len(d)):
                p, q = d[j], d[(j + 1) % len(d)]
                sp, sq = _ic(p, a) - orta, _ic(q, a) - orta
                if (sp < 0) != (sq < 0) and sp != sq:
                    t = sp / (sp - sq)
                    kes.append(iki_b(tuple(p[k] + t * (q[k] - p[k]) for k in range(3))))
        if y.tur == "koni" and y.eksen is not None and abs(_ic(y.eksen, a)) > 0.999 and not kes:
            # profil eksenine paralel, ortadan geçen tam silindir / koni yüzü (yuvarlak boru): izi daire
            if y.merkez is None:
                continue
            h = (orta - _ic(y.merkez, a)) * (1 if _ic(y.eksen, a) > 0 else -1)  # yüzün kendi ekseninde
            r = y.r0 + y.egim * h
            s_lo = min(_ic(q, a) for d in y.donguler for q in d) if y.donguler else orta
            s_hi = max(_ic(q, a) for d in y.donguler for q in d) if y.donguler else orta
            if r > 0 and s_lo < orta < s_hi:
                cx, cy = iki_b(y.merkez)
                daire = [(cx + r * math.cos(2 * math.pi * k / 96), cy + r * math.sin(2 * math.pi * k / 96))
                         for k in range(96)]
                daireler.append((i, Kontur(daire)))
                iz[i] = None
            continue
        if len(kes) >= 2:
            # en uzak iki nokta: yüzün kesitteki izi (yay ise kirişi; zincir için uçlar yeter)
            b0, b1 = max(((p, q) for p in kes for q in kes), key=lambda pq: math.dist(*pq))
            if math.dist(b0, b1) > tol:
                parcalar.append([b0, b1])
                iz[i] = (b0, b1)

    zincir, _ = zincirle(parcalar, tol=tol * 5)
    konturlar = [Kontur(z) for z in zincir] + [k for _, k in daireler]
    parca = yerlestir(konturlar)
    # kesit kurulamadıysa (yanal yüzü tek parça spline olan dolu ayak gibi) boşluk aranamaz: yanal yüzler dış
    dis_kontur = max(parca, key=lambda p: p.dis.alan) if parca else None
    delikler = dis_kontur.delikler if dis_kontur else []

    def uzaklik(m, k: Kontur) -> float:
        n = k.noktalar
        en = float("inf")
        for j in range(len(n)):
            p, q = n[j], n[(j + 1) % len(n)]
            dx, dy = q[0] - p[0], q[1] - p[1]
            l2 = dx * dx + dy * dy
            t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((m[0] - p[0]) * dx + (m[1] - p[1]) * dy) / l2))
            en = min(en, math.hypot(m[0] - p[0] - t * dx, m[1] - p[1] - t * dy))
        return en

    pr = Profil(boy=boy, kesit=kesit)
    if delikler:
        pr.bosluk = max(max(d.kutu[2] - d.kutu[0], d.kutu[3] - d.kutu[1]) for d in delikler)
    daire_yuz = {i for i, _ in daireler}
    for i, y in enumerate(yuzler):
        if i in iz:
            if i in daire_yuz:
                k = next(k for j, k in daireler if j == i)
                ic = any(k is d for d in delikler)
            else:
                b0, b1 = iz[i]
                m = ((b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2)
                ic = bool(delikler) and min(uzaklik(m, d) for d in delikler) < uzaklik(m, dis_kontur.dis)
            if ic:
                ss = [_ic(q, a) for d in y.donguler for q in d]
                pr.ic.append((y.alan, (max(ss) - min(ss)) if ss else boy))
            else:
                pr.dis += y.alan
        elif y.tur == "duzlem" and y.normal is not None and abs(_ic(y.normal, a)) > 0.2:
            pr.uc += y.alan
        else:
            pr.dis += y.alan
    return pr


# ---------------------------------------------------------------- sac

@dataclass
class Sac:
    kalinlik: float                   # mm (modelden)
    yuz: float                        # iki yüz (büküm yüzleri dahil), mm²
    kenar: float                      # kesim kenarları ve delik duvarları, mm²

    def sozluk(self) -> Dict:
        return {"kalinlik": self.kalinlik, "yuz": self.yuz, "kenar": self.kenar}


def sac_coz(yuzler: Sequence[YuzBilgi]) -> Optional[Sac]:
    """Sac parça mı (düz ya da bükümlü): paralel düz yüz çiftlerinin aralığı kalınlıktır. Alanca en
    ağır aralık seçilir; çiftlere giren yüzler toplam alanın yarısından çoksa ve kalınlık parçanın ikinci büyük
    ölçüsünün dörtte birinden küçükse sac sayılır. Eş eksenli, yarıçap farkı kalınlık kadar silindirler büküm
    yüzüdür; geri kalan yüzler (kesim kenarları, delik duvarları) kenardır."""
    toplam = sum(y.alan for y in yuzler)
    pts = [q for y in yuzler for d in y.donguler for q in d]
    if toplam <= 0 or len(pts) < 4:
        return None
    olcu = sorted(max(q[i] for q in pts) - min(q[i] for q in pts) for i in range(3))
    duz = [(i, y) for i, y in enumerate(yuzler) if y.tur == "duzlem" and y.normal is not None and y.donguler]
    adaylar = []  # (aralık, ağırlık, i, j)
    for x in range(len(duz)):
        i, a = duz[x]
        for z in range(x + 1, len(duz)):
            j, b = duz[z]
            if abs(_ic(a.normal, b.normal)) > 0.9995:  # paralel (AutoCAD iki yüzü aynı normalle, yönü yüzde yazar)
                d = abs(_ic(_cik(b.donguler[0][0], a.donguler[0][0]), a.normal))
                if d > 1e-6:
                    adaylar.append((d, min(a.alan, b.alan), i, j))
    if not adaylar:
        return None
    kume: List[List[tuple]] = []
    for c in sorted(adaylar):
        if kume and abs(c[0] - kume[-1][0][0]) <= max(0.01, 1e-3 * c[0]):
            kume[-1].append(c)
        else:
            kume.append([c])
    en = max(kume, key=lambda k: sum(c[1] for c in k))
    t = sum(c[0] * c[1] for c in en) / sum(c[1] for c in en)
    yuz_id = {i for c in en for i in c[2:]}
    # büküm: eş eksenli iki silindir, yarıçap farkı ≈ t
    koni = [(i, y) for i, y in enumerate(yuzler) if y.tur == "koni" and y.eksen is not None and y.merkez is not None]
    for x in range(len(koni)):
        i, a = koni[x]
        for j, b in koni[x + 1:]:
            if abs(abs(_ic(a.eksen, b.eksen)) - 1) > 1e-6:
                continue
            fark = _cik(b.merkez, a.merkez)
            yanal = _cik(fark, tuple(_ic(fark, a.eksen) * c for c in a.eksen))
            if math.sqrt(_ic(yanal, yanal)) <= max(0.01, 1e-3 * t) and abs(abs(a.r0 - b.r0) - t) <= max(0.01, 1e-3 * t):
                yuz_id |= {i, j}
    yuz = sum(yuzler[i].alan for i in yuz_id)
    if yuz < 0.5 * toplam or t > 0.25 * olcu[1]:
        return None
    return Sac(t, yuz, toplam - yuz)
