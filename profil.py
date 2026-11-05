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
    kenarlar: List[frozenset] = field(default_factory=list)   # döngü başına kenar kimlikleri (komşuluk için)


@dataclass
class Profil:
    boy: float                        # eksen boyunca (mm)
    kesit: Tuple[float, float]        # kesitin dış ölçüleri (mm)
    dis: float = 0.0                  # mm²
    uc: float = 0.0
    ic: List[Tuple[float, float]] = field(default_factory=list)   # iç yüzler: (alan, eksen boyu)
    bosluk: float = 0.0               # boşluğun en büyük kesit ölçüsü (iç boya derinliği varsayılanı)
    koni: Optional[Dict] = None       # dış yüzü koni / silindirse açınım ölçüleri: d1, d2 (dış), boy, t
    kesit_alani: float = 0.0          # ortadaki kesitin metal alanı (dış kontur − boşluklar), mm²; 0: kurulamadı

    @property
    def ic_alan(self) -> float:
        return sum(a for a, _ in self.ic)

    def ic_boyanan(self, derinlik: float) -> float:
        """İç yüzeyin iki uçtan derinlik kadar giren kısmı."""
        return sum(a * min(1.0, 2.0 * max(derinlik, 0.0) / L) if L > 0 else a for a, L in self.ic)

    def sozluk(self) -> Dict:
        return {"boy": self.boy, "kesit": list(self.kesit), "dis": self.dis, "uc": self.uc,
                "ic": [list(x) for x in self.ic], "bosluk": self.bosluk, "koni": self.koni,
                "kesit_alani": self.kesit_alani}


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
    if dis_kontur is not None:  # yay izleri kirişle: yuvarlatılmış köşelerde yaklaşık
        pr.kesit_alani = max(0.0, dis_kontur.dis.alan - sum(d.alan for d in delikler))
    if delikler:
        pr.bosluk = max(max(d.kutu[2] - d.kutu[0], d.kutu[3] - d.kutu[1]) for d in delikler)
    daire_yuz = {i for i, _ in daireler}
    ic_koni: List[YuzBilgi] = []
    dis_koni: List[YuzBilgi] = []
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
                ic_koni.append(y)
            else:
                pr.dis += y.alan
                dis_koni.append(y)
        elif y.tur == "duzlem" and y.normal is not None and abs(_ic(y.normal, a)) > 0.2:
            pr.uc += y.alan
        else:
            pr.dis += y.alan
    pr.koni = _koni_olculeri([y for y in dis_koni if y.tur == "koni"], [y for y in ic_koni if y.tur == "koni"])
    return pr


def _koni_olculeri(dis: List[YuzBilgi], ic: List[YuzBilgi]) -> Optional[Dict]:
    """En büyük dış koni / silindir yüzünün uçlarındaki çaplar ve eksen boyu; eş eksenli iç yüz varsa sac
    kalınlığı (yarıçap farkı · cos α)."""
    adaylar = [y for y in dis if y.eksen is not None and y.merkez is not None and y.donguler]
    if not adaylar:
        return None
    y = max(adaylar, key=lambda y: y.alan)
    hh = [_ic(_cik(q, y.merkez), y.eksen) for d in y.donguler for q in d]
    h0, h1 = min(hh), max(hh)
    rho = lambda yz, h: yz.r0 + yz.egim * h
    sonuc = {"d1": 2 * rho(y, h0), "d2": 2 * rho(y, h1), "boy": h1 - h0, "t": None}
    for z in ic:
        if z.eksen is None or z.merkez is None or abs(abs(_ic(z.eksen, y.eksen)) - 1) > 1e-6:
            continue
        orta = 0.5 * (h0 + h1)
        p = tuple(y.merkez[i] + orta * y.eksen[i] for i in range(3))  # dış yüzün ekseninde, ortada
        hz = _ic(_cik(p, z.merkez), z.eksen)
        fark = rho(y, orta) - rho(z, hz)
        if fark > 0:
            sonuc["t"] = fark / math.sqrt(1 + y.egim ** 2)
            break
    return sonuc


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


# ---------------------------------------------------------------- delik, havşa ve kesikler

DELIK_TURLERI = ("yuvarlak", "kanal", "elips", "dikdörtgen", "serbest")


@dataclass
class Delik:
    cap: float                        # yuvarlak: en dar silindirin çapı; diğerleri: uzun ölçü (mm)
    havsa_cap: float = 0.0            # havşa / kademe ağzının çapı (0: yok)
    havsa_aci: float = 0.0            # konik havşanın tepe açısı (derece; 0: düz kademe)
    alan: float = 0.0                 # deliğin bütün yüzeyleri (duvar + havşa), mm²
    duvar: float = 0.0                # duvarlar, mm² (delik içi boyanmaz seçeneğinde düşülür)
    yuzler: List[int] = field(default_factory=list)
    tur: str = "yuvarlak"             # DELIK_TURLERI
    en: float = 0.0                   # kanal / elips / dikdörtgen: kısa ölçü (mm)
    cevre: float = 0.0                # serbest kesim: ağız çevresi (mm)
    agiz: List[List[V3]] = field(default_factory=list)   # önizleme için ağız döngüleri

    def sozluk(self) -> Dict:
        return {"cap": self.cap, "havsa_cap": self.havsa_cap, "havsa_aci": self.havsa_aci, "alan": self.alan,
                "duvar": self.duvar, "tur": self.tur, "en": self.en, "cevre": self.cevre}

    def olcekle(self, k: float) -> None:
        self.cap, self.havsa_cap, self.en, self.cevre = self.cap * k, self.havsa_cap * k, self.en * k, self.cevre * k
        self.alan, self.duvar = self.alan * k * k, self.duvar * k * k


def _dongu_alani(d: Sequence[V3], n: V3) -> float:
    s = (0.0, 0.0, 0.0)
    for i in range(len(d)):
        c = _dis(d[i], d[(i + 1) % len(d)])
        s = (s[0] + c[0], s[1] + c[1], s[2] + c[2])
    return abs(_ic(s, n)) / 2


def _taban(n: V3):
    e1 = _birim(_dis(n, (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)))
    return e1, _dis(n, e1)


def _zarf(p: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Dışbükey zarf (monoton zincir)."""
    p = sorted(set(p))
    if len(p) < 3:
        return p
    cap = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    alt, ust = [], []
    for q in p:
        while len(alt) >= 2 and cap(alt[-2], alt[-1], q) <= 0:
            alt.pop()
        alt.append(q)
    for q in reversed(p):
        while len(ust) >= 2 and cap(ust[-2], ust[-1], q) <= 0:
            ust.pop()
        ust.append(q)
    return alt[:-1] + ust[:-1]


def sekil(p: List[Tuple[float, float]]) -> Tuple[str, float, float, float]:
    """Düzlemdeki kapalı ağız konturunun biçimi: (tür, uzun ölçü, kısa ölçü, çevre). En küçük alanlı çevreleyen
    dikdörtgenin çerçevesinde noktalar denenir: elips (çember), kanal (iki ucu yarım daire), dikdörtgen; hiçbiri
    değilse serbest."""
    n = len(p)
    cevre = sum(math.dist(p[i], p[(i + 1) % n]) for i in range(n))
    z = _zarf(p)
    en_iyi = None
    for i in range(len(z)):
        a, b = z[i], z[(i + 1) % len(z)]
        L = math.dist(a, b)
        if L <= 0:
            continue
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        v = (-u[1], u[0])
        xs = [q[0] * u[0] + q[1] * u[1] for q in p]
        ys = [q[0] * v[0] + q[1] * v[1] for q in p]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if en_iyi is None or w * h < en_iyi[0]:
            en_iyi = (w * h, w, h, u, v, (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)
    if en_iyi is None:
        return "serbest", 0.0, 0.0, cevre
    _, w, h, u, v, cx, cy = en_iyi
    if h > w:
        w, h, u, v, cx, cy = h, w, v, (-u[0], -u[1]), cy, -cx
    sik = []  # doğru kenarlar iki noktayla gelir: aradaki noktalar da denensin (üçgen dikdörtgen sanılmasın)
    for i in range(n):
        a_, b_ = p[i], p[(i + 1) % n]
        sik += [(a_[0] + (b_[0] - a_[0]) * t / 8, a_[1] + (b_[1] - a_[1]) * t / 8) for t in range(8)]
    yerel = [(q[0] * u[0] + q[1] * u[1] - cx, q[0] * v[0] + q[1] * v[1] - cy) for q in sik]
    if h <= 0:
        return "serbest", w, h, cevre
    a_, b_ = w / 2, h / 2
    tol = 0.01
    if all(abs((x / a_) ** 2 + (y / b_) ** 2 - 1) < 2 * tol for x, y in yerel):
        return ("yuvarlak" if w - h <= tol * w else "elips"), w, h, cevre
    d = a_ - b_  # kanal: orta doğru parçasına uzaklık yarı genişlik
    if all(abs(math.hypot(max(abs(x) - d, 0.0), y) - b_) < tol * b_ for x, y in yerel):
        return "kanal", w, h, cevre
    if all(abs(max(abs(x) / a_, abs(y) / b_) - 1) < tol for x, y in yerel):
        return "dikdörtgen", w, h, cevre
    return "serbest", w, h, cevre


def delik_bul(yuzler: Sequence[YuzBilgi]) -> List[Delik]:
    """Delik ve iç kesikler.
    1. Yuvarlak: kenarı bir düz yüzün iç döngüsünde (ağız) olan silindir / koni yüzlerinden başlayıp kenar paylaşan
       eş eksenli silindir / konilerle büyüyen, eksen çevresinde tam dönen yüz kümeleri. Aynı eksendeki kümeler
       (kademe: araya düz halka girer) birleşir. Koni: havşa; büyük silindir: kademe.
    2. Diğer iç kesikler (kanal, oval, elips, dikdörtgen pencere, serbest): yuvarlak deliğe ait olmayan iç döngüler.
       Biçim ağız konturundan (sekil); karşı yüzdeki aynı ağız (boydan boya kesik) bir kez sayılır. Duvarlar: ağız
       kenarlarını paylaşan, kendisinde iç döngü olmayan yüzler."""
    pts = [q for y in yuzler for d in y.donguler for q in d]
    if not pts:
        return []
    olcu = max(max(q[i] for q in pts) - min(q[i] for q in pts) for i in range(3)) or 1.0
    tol = olcu * 1e-4
    ic_dongu = []  # (yüz, döngü sırası)
    for yi, y in enumerate(yuzler):
        if y.tur == "duzlem" and y.normal is not None and len(y.donguler) >= 2 and len(y.kenarlar) == len(y.donguler):
            alanlar = [_dongu_alani(d, y.normal) for d in y.donguler]
            dis = max(range(len(alanlar)), key=alanlar.__getitem__)
            ic_dongu += [(yi, i) for i in range(len(alanlar)) if i != dis]
    if not ic_dongu:
        return []
    ic_kenar = frozenset().union(*(yuzler[yi].kenarlar[i] for yi, i in ic_dongu))
    kenar = {i: frozenset().union(*y.kenarlar) if y.kenarlar else frozenset() for i, y in enumerate(yuzler)}
    out = _yuvarlak_delikler(yuzler, ic_kenar, kenar, tol)
    yuvarlak_kenar = frozenset().union(*(kenar[i] for d in out for i in d.yuzler)) if out else frozenset()
    ana = {yi for yi, _ in ic_dongu}  # iç döngüsü olan yüzler (sacın iki yüzü, kademe halkası)

    gorulen: List[Tuple[V3, V3, str, float, float, Delik]] = []  # (normal, merkez, tür, uzun, kısa, kesik)
    for yi, i in ic_dongu:
        k = yuzler[yi].kenarlar[i]
        if k & yuvarlak_kenar:
            continue
        y = yuzler[yi]
        d = y.donguler[i]
        e1, e2 = _taban(y.normal)
        tur, w, h, cevre = sekil([(_ic(q, e1), _ic(q, e2)) for q in d])
        m = tuple(sum(q[j] for q in d) / len(d) for j in range(3))
        duvar = [j for j, kj in kenar.items() if j != yi and j not in ana and kj & k]
        es = next((g for g in gorulen if abs(abs(_ic(g[0], y.normal)) - 1) < 1e-6 and g[2] == tur
                   and abs(g[3] - w) <= 10 * tol and abs(g[4] - h) <= 10 * tol
                   and _boy_dik(_cik(m, g[1]), y.normal) <= 10 * tol), None)
        if es is not None:  # karşı yüzdeki ağız: aynı kesik
            dl = es[5]
            for j in duvar:
                if j not in dl.yuzler:
                    dl.yuzler.append(j)
                    dl.duvar += yuzler[j].alan
            dl.alan = dl.duvar
            dl.agiz.append(d)
            continue
        dl = Delik(w, tur=tur, en=h, cevre=cevre, yuzler=list(duvar), agiz=[d])
        dl.duvar = dl.alan = sum(yuzler[j].alan for j in duvar)
        gorulen.append((y.normal, m, tur, w, h, dl))
        out.append(dl)
    return out


def _boy_dik(d: V3, n: V3) -> float:
    """d'nin n'ye dik bileşeninin boyu."""
    return math.sqrt(max(0.0, _ic(d, d) - _ic(d, n) ** 2))


def _yuvarlak_delikler(yuzler, ic_kenar, kenar, tol) -> List[Delik]:
    koni = [i for i, y in enumerate(yuzler) if y.tur == "koni" and y.eksen is not None and y.merkez is not None
            and y.kenarlar]

    def eksen_ayni(i, j):
        a, b = yuzler[i], yuzler[j]
        if abs(abs(_ic(a.eksen, b.eksen)) - 1.0) > 1e-6:
            return False
        return _boy_dik(_cik(b.merkez, a.merkez), a.eksen) <= tol

    tohum = [i for i in koni if kenar[i] & ic_kenar]
    kume: List[List[int]] = []
    goruldu = set()
    for t in tohum:
        if t in goruldu:
            continue
        k, yigin = [], [t]
        goruldu.add(t)
        while yigin:
            i = yigin.pop()
            k.append(i)
            for j in koni:
                if j not in goruldu and kenar[i] & kenar[j] and eksen_ayni(i, j):
                    goruldu.add(j)
                    yigin.append(j)
        for e in kume:  # aynı eksendeki önceki kümeye katılır (kademeli delik)
            if eksen_ayni(e[0], k[0]):
                e.extend(k)
                break
        else:
            kume.append(k)
    out = []
    for k in kume:
        a = yuzler[k[0]]
        e1, e2 = _taban(a.eksen)

        def yaricaplar(i):
            return [math.hypot(_ic(_cik(q, a.merkez), e1), _ic(_cik(q, a.merkez), e2))
                    for d in yuzler[i].donguler for q in d]
        acilar = sorted(math.atan2(_ic(_cik(q, a.merkez), e2), _ic(_cik(q, a.merkez), e1))
                        for i in k for d in yuzler[i].donguler for q in d)
        bosluk = max([b - c for c, b in zip(acilar, acilar[1:])] + [acilar[0] + 2 * math.pi - acilar[-1]])
        if bosluk > math.radians(30):  # tam dönmüyor: kanal ucu, yay köşe ... (kesik olarak bulunur)
            continue
        sil = [i for i in k if abs(yuzler[i].egim) < 1e-6]
        kon = [i for i in k if abs(yuzler[i].egim) >= 1e-6]
        r_sil = {i: sum(yaricaplar(i)) / max(1, len(yaricaplar(i))) for i in sil}
        cap = 2 * min(r_sil.values()) if sil else 2 * min(min(yaricaplar(i)) for i in kon)
        dl = Delik(cap, alan=sum(yuzler[i].alan for i in k), duvar=sum(yuzler[i].alan for i in sil), yuzler=list(k))
        if kon:
            dl.havsa_cap = 2 * max(max(yaricaplar(i)) for i in kon)
            dl.havsa_aci = 2 * math.degrees(math.atan(max(abs(yuzler[i].egim) for i in kon)))
        elif len(r_sil) > 1 and 2 * max(r_sil.values()) > cap + 2 * tol:
            dl.havsa_cap = 2 * max(r_sil.values())  # düz kademe (silindirik havşa)
        out.append(dl)
    return out


def _mm(x: float) -> str:
    return f"{round(x, 1):g}".replace(".", ",")


def delik_adi(d: Dict) -> str:
    tur = d.get("tur", "yuvarlak")
    if tur == "yuvarlak":
        m = f"Ø{_mm(d['cap'])}"
        if d.get("havsa_cap"):
            m += (f" havşa Ø{_mm(d['havsa_cap'])} × {round(d['havsa_aci']):g}°" if d.get("havsa_aci")
                  else f" kademe Ø{_mm(d['havsa_cap'])}")
        return m
    if tur == "serbest":
        return f"serbest kesik {_mm(d['cap'])} × {_mm(d.get('en', 0))} (çevre {_mm(d.get('cevre', 0))})"
    return f"{tur} {_mm(d['cap'])} × {_mm(d.get('en', 0))}"


def delik_ozeti(delikler: Sequence[Dict]) -> List[Tuple[int, str]]:
    """Aynı ölçülü delikler gruplanır: [(adet, 'Ø6 havşa Ø12 × 90°'), (2, 'kanal 30 × 8'), ...]."""
    say: Dict[str, int] = {}
    sira: Dict[str, Tuple] = {}
    for d in delikler:
        ad = delik_adi(d)
        say[ad] = say.get(ad, 0) + 1
        sira[ad] = (DELIK_TURLERI.index(d.get("tur", "yuvarlak")), -round(d["cap"], 1))
    return [(say[a], a) for a in sorted(say, key=lambda a: (*sira[a], -say[a]))]


def delik_sayimi(delikler: Sequence[Dict]) -> str:
    """Açıklama için: '3 delik (2 havşalı), 2 kanal, 1 elips'."""
    parca = []
    yuv = [d for d in delikler if d.get("tur", "yuvarlak") == "yuvarlak"]
    if yuv:
        h = sum(1 for d in yuv if d.get("havsa_cap"))
        parca.append(f"{len(yuv)} delik" + (f" ({h} havşalı)" if h else ""))
    for t, ad in (("kanal", "kanal"), ("elips", "elips"), ("dikdörtgen", "dikdörtgen kesik"),
                  ("serbest", "serbest kesik")):
        n = sum(1 for d in delikler if d.get("tur") == t)
        if n:
            parca.append(f"{n} {ad}")
    return ", ".join(parca)
