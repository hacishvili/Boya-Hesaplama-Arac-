# -*- coding: utf-8 -*-
"""STEP (ISO 10303-21: AP203 / AP214 / AP242) katıları. Sınır gösterimi (B-rep) ACIS kayıt düzenine çevrilir ve
DXF katılarıyla aynı yoldan hesaplanır (acis_alan): alan, profil / sac tanıma, delik ve havşa, kaynak kenarları,
yüzey seçimi.

Yüzeyler: düzlem, silindir, koni, küre, torus, B-spline (rasyonel de), doğrusal çekim ve dönel yüzey (B-spline'a
çevrilir). Eğriler: doğru, daire, elips, B-spline, çoklu çizgi. Montajda her parça yerleşimiyle (dönme + öteleme)
ayrı gövde olur; aynı parçanın kopyaları içe aktarmada adet olarak toplanır."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import acis_alan
from acis_alan import AcisHatasi, Bs3Egri, Bs3Yuzey, HazirKayit, Kayit

V3 = Tuple[float, float, float]


class StepHatasi(Exception):
    pass


# ---------------------------------------------------------------- ayrıştırma (Part 21)

class Ref(int):
    """#123"""


class Enum(str):
    """.T. / .MILLI."""


@dataclass
class Tipli:
    """Tipli değer: LENGTH_MEASURE(1.5)."""
    ad: str
    deger: list


@dataclass
class Varlik:
    no: int
    parcalar: Dict[str, list]          # tek varlıkta bir ad; karmaşık varlıkta (A() B() ...) hepsi
    ad: str = ""

    def __getitem__(self, ad: str) -> list:
        return self.parcalar[ad]

    def var(self, ad: str) -> bool:
        return ad in self.parcalar


_SOZ = re.compile(r"""
    (?P<s>'(?:[^']|'')*')                                  # metin
  | (?P<r>\#\d+)                                           # başvuru
  | (?P<e>\.[A-Za-z0-9_]+\.)                               # sayım değeri
  | (?P<n>[+-]?(?:\d+\.?\d*(?:[Ee][+-]?\d+)?|\.\d+(?:[Ee][+-]?\d+)?))
  | (?P<i>[A-Za-z_][A-Za-z0-9_]*)                          # ad
  | (?P<p>[(),=;$*])
  | (?P<b>\s+)
  | (?P<h>")                                               # ikili (kullanılmaz)
""", re.X)


def _yorumsuz(metin: str) -> str:
    """/* ... */ yorumları (metin içindekiler hariç) silinir."""
    if "/*" not in metin:
        return metin
    out, i, n = [], 0, len(metin)
    while i < n:
        c = metin[i]
        if c == "'":
            j = i + 1
            while j < n:
                if metin[j] == "'":
                    if j + 1 < n and metin[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append(metin[i:j + 1])
            i = j + 1
        elif metin.startswith("/*", i):
            j = metin.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            j = i
            while j < n and metin[j] != "'" and not metin.startswith("/*", j):
                j += 1
            out.append(metin[i:j])
            i = j
    return "".join(out)


def ayristir(metin: str) -> Dict[int, Varlik]:
    """DATA bölümündeki varlıklar: no → Varlik."""
    metin = _yorumsuz(metin)
    if "ISO-10303-21" not in metin[:2000].upper():
        raise StepHatasi("STEP dosyası değil (ISO-10303-21 başlığı yok).")
    bas = re.search(r"\bDATA\b\s*(\([^;]*\))?\s*;", metin)
    if not bas:
        raise StepHatasi("STEP dosyasında DATA bölümü yok.")
    sozler = _SOZ.finditer(metin, bas.end())
    varliklar: Dict[int, Varlik] = {}

    def sonraki():
        for m in sozler:
            t = m.lastgroup
            if t == "b":
                continue
            return t, m.group()
        return None, None

    def liste() -> list:
        """'(' okunduktan sonra ')' ye kadar değerler."""
        out = []
        while True:
            t, v = sonraki()
            if t is None:
                raise StepHatasi("STEP dosyası yarım (parantez kapanmıyor).")
            if v == ")":
                return out
            if v == ",":
                continue
            out.append(deger(t, v))

    def deger(t, v):
        if t == "s":
            return v[1:-1].replace("''", "'")
        if t == "r":
            return Ref(int(v[1:]))
        if t == "e":
            return Enum(v[1:-1].upper())
        if t == "n":
            return float(v)
        if v == "(":
            return liste()
        if v in ("$", "*"):
            return None
        if t == "i":
            t2, v2 = sonraki()
            if v2 != "(":
                raise StepHatasi(f"beklenmeyen öğe: {v} {v2}")
            return Tipli(v.upper(), liste())
        raise StepHatasi(f"beklenmeyen öğe: {v}")

    while True:
        t, v = sonraki()
        if t is None:
            break
        if t == "i" and v.upper() in ("ENDSEC", "END"):
            break
        if t != "r":
            continue
        no = int(v[1:])
        t, v = sonraki()
        if v != "=":
            raise StepHatasi(f"#{no}: '=' bekleniyordu")
        t, v = sonraki()
        parcalar: Dict[str, list] = {}
        if t == "i":
            ad = v.upper()
            if sonraki()[1] != "(":
                raise StepHatasi(f"#{no}: '(' bekleniyordu")
            parcalar[ad] = liste()
        elif v == "(":  # karmaşık varlık: (A(...) B(...) ...)
            ad = ""
            while True:
                t, v = sonraki()
                if v == ")":
                    break
                if t != "i" or sonraki()[1] != "(":
                    raise StepHatasi(f"#{no}: karmaşık varlık okunamadı")
                parcalar[v.upper()] = liste()
        else:
            raise StepHatasi(f"#{no}: varlık adı yok")
        t, v = sonraki()
        if v != ";":
            raise StepHatasi(f"#{no}: ';' bekleniyordu")
        varliklar[no] = Varlik(no, parcalar, ad)
    if not varliklar:
        raise StepHatasi("STEP dosyasında varlık yok.")
    return varliklar


# ---------------------------------------------------------------- vektör yardımcıları

def _cik(a, b):
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _top(a, b):
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def _kat(a, s):
    return a[0] * s, a[1] * s, a[2] * s


def _ic(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _dis(a, b):
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def _birim(a):
    n = math.sqrt(_ic(a, a))
    if n == 0:
        raise AcisHatasi("sıfır uzunlukta yön")
    return a[0] / n, a[1] / n, a[2] / n


def _dik(a):
    return _birim(_dis(a, (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)))


# Yerleşim: (R sütunları x, y, z; öteleme t); nokta → t + R p
Yer = Tuple[V3, V3, V3, V3]
BIRIM_YER: Yer = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0))


def _uygula(y: Yer, p: V3) -> V3:
    x, yy, z, t = y
    return (t[0] + x[0] * p[0] + yy[0] * p[1] + z[0] * p[2], t[1] + x[1] * p[0] + yy[1] * p[1] + z[1] * p[2],
            t[2] + x[2] * p[0] + yy[2] * p[1] + z[2] * p[2])


def _yon_uygula(y: Yer, d: V3) -> V3:
    return _cik(_uygula(y, d), y[3])


def _bilesik(a: Yer, b: Yer) -> Yer:
    """a ∘ b (önce b)."""
    return _yon_uygula(a, b[0]), _yon_uygula(a, b[1]), _yon_uygula(a, b[2]), _uygula(a, b[3])


def _ters(a: Yer) -> Yer:
    x, y, z, t = a  # dik matris: tersi devriği
    rx, ry, rz = (x[0], y[0], z[0]), (x[1], y[1], z[1]), (x[2], y[2], z[2])
    tt = (-_ic(x, t), -_ic(y, t), -_ic(z, t))
    return rx, ry, rz, tt


# ---------------------------------------------------------------- STEP → ACIS kayıtları

class Cevirici:
    def __init__(self, v: Dict[int, Varlik]):
        self.v = v
        self.uzunluk, self.aci = _birimler(v)   # (mm / birim, radyan / birim)
        self._kose: Dict[int, Kayit] = {}
        self._kenar: Dict[int, Kayit] = {}
        self._kenar_co: Dict[int, List[Kayit]] = {}
        self._yuzey: Dict[int, Kayit] = {}
        self._egri: Dict[int, object] = {}

    def boyut(self) -> float:
        """Modelin kaba büyüklüğünün iki katı (bütün noktaların en büyük mutlak koordinatı)."""
        if getattr(self, "_boyut", None) is None:
            m = 1.0
            for x in self.v.values():
                a = x.parcalar.get("CARTESIAN_POINT")
                if a and isinstance(a[1], list):
                    m = max(m, max((abs(float(c)) for c in a[1]), default=0.0))
            self._boyut = 2.0 * m
        return self._boyut

    def __call__(self, r) -> Varlik:
        try:
            return self.v[int(r)]
        except (KeyError, TypeError):
            raise AcisHatasi(f"STEP: #{r} yok")

    def ilk(self, r) -> Tuple[str, list]:
        x = self(r)
        ad = next(iter(x.parcalar))
        return ad, x.parcalar[ad]

    # -- temel öğeler
    def nokta(self, r) -> V3:
        ad, a = self.ilk(r)
        if ad != "CARTESIAN_POINT":
            raise AcisHatasi(f"STEP: nokta bekleniyordu ({ad})")
        c = [float(x) for x in a[1]] + [0.0, 0.0]
        return c[0], c[1], c[2]

    def yon(self, r) -> V3:
        ad, a = self.ilk(r)
        if ad == "VECTOR":
            return self.yon(a[1])
        c = [float(x) for x in a[1]] + [0.0, 0.0]
        return _birim((c[0], c[1], c[2]))

    def eksen(self, r) -> Tuple[V3, V3, V3]:
        """AXIS2_PLACEMENT_3D → (konum, x, z)."""
        ad, a = self.ilk(r)
        o = self.nokta(a[1])
        z = self.yon(a[2]) if len(a) > 2 and a[2] is not None else (0.0, 0.0, 1.0)
        x = self.yon(a[3]) if len(a) > 3 and a[3] is not None else _dik(z)
        x = _birim(_cik(x, _kat(z, _ic(x, z))))
        return o, x, z

    def yer(self, r) -> Yer:
        o, x, z = self.eksen(r)
        return x, _dis(z, x), z, o

    # -- eğriler: nokta(t), örnek sayısı, parametre bulma
    def egri(self, r):
        r = int(r)
        if r not in self._egri:
            self._egri[r] = self._egri_kur(r)
        return self._egri[r]

    def _egri_kur(self, r):
        x = self(r)
        if x.var("B_SPLINE_CURVE_WITH_KNOTS") or x.var("B_SPLINE_CURVE") or x.var("BEZIER_CURVE"):
            return SplineEgri(self._bs_egri(x))
        ad, a = self.ilk(r)
        if ad in ("SURFACE_CURVE", "SEAM_CURVE", "INTERSECTION_CURVE", "BOUNDED_SURFACE_CURVE"):
            return self.egri(a[1])
        if ad == "TRIMMED_CURVE":
            return self.egri(a[1])
        if ad == "LINE":
            return DogruEgri(self.nokta(a[1]), self.yon(a[2]))
        if ad == "CIRCLE":
            o, ex, z = self.eksen(a[1])
            R = float(a[2])
            return ElipsEgri(o, ex, _dis(z, ex), R, R)
        if ad == "ELLIPSE":
            o, ex, z = self.eksen(a[1])
            return ElipsEgri(o, ex, _dis(z, ex), float(a[2]), float(a[3]))
        if ad == "POLYLINE":
            pts = [self.nokta(p) for p in a[1]]
            dug = [0.0] + [float(i) for i in range(len(pts))] + [float(len(pts) - 1)]
            return SplineEgri(Bs3Egri(1, dug, pts, None))
        raise AcisHatasi(f"desteklenmeyen STEP eğrisi ({ad})")

    @staticmethod
    def _dugum(carpan: Sequence[float], dugum: Sequence[float]) -> List[float]:
        out = []
        for m, k in zip(carpan, dugum):
            out += [float(k)] * int(round(float(m)))
        return out

    def _bs_egri(self, x: Varlik) -> Bs3Egri:
        b = x["B_SPLINE_CURVE"] if x.var("B_SPLINE_CURVE") else x[next(iter(x.parcalar))]
        if not x.var("B_SPLINE_CURVE"):  # tek varlık: B_SPLINE_CURVE_WITH_KNOTS(ad, derece, noktalar, ...)
            b = b[1:]
        derece = int(b[0])
        pts = [self.nokta(p) for p in b[1]]
        if x.var("B_SPLINE_CURVE_WITH_KNOTS"):
            k = x["B_SPLINE_CURVE_WITH_KNOTS"]
            k = k[-3:] if x.var("B_SPLINE_CURVE") else k[-3:]
            dug = self._dugum(k[0], k[1])
        else:  # Bezier: açık düzgün
            dug = [0.0] * (derece + 1) + [1.0] * (derece + 1)
        w = [float(q) for q in x["RATIONAL_B_SPLINE_CURVE"][-1]] if x.var("RATIONAL_B_SPLINE_CURVE") else None
        try:
            return Bs3Egri(derece, dug, pts, w)
        except AcisHatasi:
            raise AcisHatasi("STEP B-spline eğrisinde düğüm / nokta sayısı uyuşmuyor")

    def _bs_yuzey(self, x: Varlik) -> Bs3Yuzey:
        tek = not x.var("B_SPLINE_SURFACE")
        b = x[next(iter(x.parcalar))][1:] if tek else x["B_SPLINE_SURFACE"]
        pu, pv = int(b[0]), int(b[1])
        izgara = [[self.nokta(p) for p in satir] for satir in b[2]]   # [u][v]
        nu, nv = len(izgara), len(izgara[0])
        if x.var("B_SPLINE_SURFACE_WITH_KNOTS"):
            k = x["B_SPLINE_SURFACE_WITH_KNOTS"][-5:]
            du, dv = self._dugum(k[0], k[2]), self._dugum(k[1], k[3])
        else:
            du = [0.0] * (pu + 1) + [1.0] * (pu + 1)
            dv = [0.0] * (pv + 1) + [1.0] * (pv + 1)
        P = [izgara[i][j] for j in range(nv) for i in range(nu)]   # u en hızlı
        w = None
        if x.var("RATIONAL_B_SPLINE_SURFACE"):
            ww = x["RATIONAL_B_SPLINE_SURFACE"][-1]
            w = [float(ww[i][j]) for j in range(nv) for i in range(nu)]
        return Bs3Yuzey(pu, pv, du, dv, nu, nv, P, w)

    # -- topoloji
    def kose(self, r) -> Kayit:
        r = int(r)
        if r not in self._kose:
            ad, a = self.ilk(r)
            k = Kayit("vertex")
            p = Kayit("point")
            p.oge = list(self.nokta(a[1]))
            k.oge = [None, None, p]
            self._kose[r] = k
        return self._kose[r]

    def kenar(self, r) -> Kayit:
        r = int(r)
        if r not in self._kenar:
            ad, a = self.ilk(r)
            if ad != "EDGE_CURVE":
                raise AcisHatasi(f"desteklenmeyen STEP kenarı ({ad})")
            v0, v1 = self.kose(a[1]), self.kose(a[2])
            p0, p1 = tuple(v0.oge[2].oge), tuple(v1.oge[2].oge)
            egri = self.egri(a[3])
            ayni = not (isinstance(a[4], str) and a[4].upper() == "F")
            k = HazirKayit("edge", KenarOrnek(egri, p0, p1, ayni, int(a[1]) == int(a[2])))
            k.oge = [None, v0, v1, None, None]
            v0.oge[1] = v0.oge[1] or k
            v1.oge[1] = v1.oge[1] or k
            self._kenar[r] = k
            self._kenar_co[r] = []
        return self._kenar[r]

    def yuzey(self, r) -> Kayit:
        r = int(r)
        if r not in self._yuzey:
            self._yuzey[r] = self._yuzey_kur(r)
        return self._yuzey[r]

    def _yuzey_kur(self, r) -> Kayit:
        x = self(r)
        if x.var("B_SPLINE_SURFACE_WITH_KNOTS") or x.var("B_SPLINE_SURFACE") or x.var("BEZIER_SURFACE"):
            return HazirKayit("spline-surface", self._bs_yuzey(x))
        ad, a = self.ilk(r)
        if ad == "PLANE":
            o, ex, z = self.eksen(a[1])
            k = Kayit("plane-surface")
            k.oge = [*o, *z, *ex, "forward_v", "I", "I", "I", "I"]
            return k
        if ad in ("CYLINDRICAL_SURFACE", "CONICAL_SURFACE"):
            o, ex, z = self.eksen(a[1])
            R = float(a[2])
            alfa = float(a[3]) * self.aci if ad == "CONICAL_SURFACE" else 0.0
            if R <= 0.0:  # tepesi konumda: eksen boyunca birim kaydırılır (ACIS konisinde yarıçap > 0)
                o, R = _top(o, z), math.tan(alfa)
            k = Kayit("cone-surface")
            k.oge = [*o, *z, *_kat(ex, R), 1.0, "I", "I", math.sin(alfa), math.cos(alfa), R, "forward",
                     "I", "I", "I", "I"]
            return k
        if ad == "SPHERICAL_SURFACE":
            o, ex, z = self.eksen(a[1])
            k = Kayit("sphere-surface")
            k.oge = [*o, float(a[2]), *ex, *z, "forward_v", "I", "I", "I", "I"]
            return k
        if ad == "TOROIDAL_SURFACE":
            o, ex, z = self.eksen(a[1])
            k = Kayit("torus-surface")
            k.oge = [*o, *z, float(a[2]), float(a[3]), *ex, "I", "I", "I", "I"]
            return k
        if ad == "SURFACE_OF_LINEAR_EXTRUSION":
            c = _nurbs(self.egri(a[1]))
            d = self.yon(self(a[2])["VECTOR"][1])
            L = self.boyut()  # sonsuz yüzey: modelin iki katı uzunlukta iki yöne; yüz kenarlarıyla kırpılır
            P = [_top(q, _kat(d, -L)) for q in c.P] + [_top(q, _kat(d, L)) for q in c.P]
            w = (list(c.w) + list(c.w)) if c.w else None
            return HazirKayit("spline-surface", Bs3Yuzey(c.p, 1, c.dug, [0.0, 0.0, 1.0, 1.0], c.n, 2, P, w))
        if ad == "SURFACE_OF_REVOLUTION":
            c = _nurbs(self.egri(a[1]))
            ea = self.ilk(a[2])[1]
            o = self.nokta(ea[1])
            z = self.yon(ea[2]) if len(ea) > 2 and ea[2] is not None else (0.0, 0.0, 1.0)
            return HazirKayit("spline-surface", _donel(c, o, z))
        raise AcisHatasi(f"desteklenmeyen STEP yüzeyi ({ad})")

    def kabuk(self, r, lump: Kayit, onceki: Optional[Kayit]) -> Kayit:
        """CLOSED_SHELL / OPEN_SHELL → ACIS shell (yüz zinciriyle)."""
        ad, a = self.ilk(r)
        if ad == "ORIENTED_CLOSED_SHELL":
            return self.kabuk(a[2], lump, onceki)
        sh = Kayit("shell")
        yuzler = [self.yuz(f, sh) for f in a[1]]
        for f, g in zip(yuzler, yuzler[1:] + [None]):
            f.oge[1] = g
        sh.oge = [None, None, None, yuzler[0] if yuzler else None, None, lump]
        if onceki is not None:
            onceki.oge[1] = sh
        return sh

    def yuz(self, r, shell: Kayit) -> Kayit:
        ad, a = self.ilk(r)
        if ad not in ("ADVANCED_FACE", "FACE_SURFACE"):
            raise AcisHatasi(f"desteklenmeyen STEP yüzü ({ad})")
        f = Kayit("face")
        try:
            yz = self.yuzey(a[2])
        except AcisHatasi as h:
            yz = Kayit(f"step:{h}")  # Yuzey() desteklenmeyen diye reddeder; nedeni adında
        donguler = []
        for b in a[1]:
            bad, ba = self.ilk(b)
            yon = not (isinstance(ba[2], str) and ba[2].upper() == "F")
            lad, la = self.ilk(ba[1])
            if lad == "VERTEX_LOOP":
                continue
            if lad == "POLY_LOOP":
                raise AcisHatasi("STEP çokgen döngüsü desteklenmez")
            oe = []
            for o in la[1]:
                oad, oa = self.ilk(o)
                oe.append((oa[3], not (isinstance(oa[4], str) and oa[4].upper() == "F")))
            if not yon:
                oe = [(e, not s) for e, s in reversed(oe)]
            loop = Kayit("loop")
            co = []
            for e, s in oe:
                c = Kayit("coedge")
                kenar = self.kenar(e)
                c.oge = [None, None, None, None, kenar, "forward" if s else "reversed", loop, None]
                self._kenar_co[int(e)].append(c)
                if kenar.oge[3] is None:
                    kenar.oge[3] = c
                co.append(c)
            for i, c in enumerate(co):
                c.oge[1], c.oge[2] = co[(i + 1) % len(co)], co[i - 1]
            loop.oge = [None, None, co[0] if co else None, f]
            donguler.append(loop)
        for l, m in zip(donguler, donguler[1:] + [None]):
            l.oge[1] = m
        ayni = not (isinstance(a[3], str) and a[3].upper() == "F") if len(a) > 3 else True
        f.oge = [None, None, donguler[0] if donguler else None, shell, None, yz,
                 "forward" if ayni else "reversed", "single"]
        return f

    def esle(self):
        """Coedge eşleri: aynı kenarı kullanan coedge'ler halkalanır."""
        for cos in self._kenar_co.values():
            if len(cos) >= 2:
                for i, c in enumerate(cos):
                    c.oge[3] = cos[(i + 1) % len(cos)]


@dataclass
class DogruEgri:
    o: V3
    d: V3

    def nokta(self, t):
        return _top(self.o, _kat(self.d, t))

    def param(self, p):
        return _ic(_cik(p, self.o), self.d)


@dataclass
class ElipsEgri:
    c: V3
    x: V3
    y: V3
    a: float
    b: float
    periyot: float = 2 * math.pi

    def nokta(self, t):
        return _top(self.c, _top(_kat(self.x, self.a * math.cos(t)), _kat(self.y, self.b * math.sin(t))))

    def param(self, p):
        d = _cik(p, self.c)
        return math.atan2(_ic(d, self.y) / self.b, _ic(d, self.x) / self.a)


class SplineEgri:
    def __init__(self, b: Bs3Egri):
        self.b = b
        self.t0, self.t1 = b.t0, b.t1
        self.kapali = math.dist(b.nokta(self.t0), b.nokta(self.t1)) <= 1e-9 * (1 + _olcu(b.P))
        self.periyot = (self.t1 - self.t0) if self.kapali else None

    def nokta(self, t):
        if self.kapali:
            t = self.t0 + (t - self.t0) % (self.t1 - self.t0) if t != self.t1 else t
        return self.b.nokta(t)

    def param(self, p):
        """Noktanın eğri parametresi: sık örnek, sonra altın oran araması."""
        n = max(64, 16 * len(self.b.P))
        ts = [self.t0 + (self.t1 - self.t0) * i / n for i in range(n + 1)]
        d = [math.dist(self.b.nokta(t), p) for t in ts]
        i = min(range(len(ts)), key=d.__getitem__)
        a, b = ts[max(0, i - 1)], ts[min(n, i + 1)]
        g = (math.sqrt(5) - 1) / 2
        for _ in range(60):
            c, e = b - g * (b - a), a + g * (b - a)
            if math.dist(self.b.nokta(c), p) < math.dist(self.b.nokta(e), p):
                b = e
            else:
                a = c
        return (a + b) / 2

    def araliklar(self, t0, t1) -> int:
        lo, hi = min(t0, t1), max(t0, t1)
        dug = self.b.dug
        say = sum(1 for x, y in zip(dug, dug[1:]) if y > x and lo <= x < hi)
        if self.kapali and hi - lo > self.t1 - self.t0 - 1e-12:
            say = sum(1 for x, y in zip(dug, dug[1:]) if y > x)
        return say


def _olcu(P) -> float:
    return max((max(abs(c) for c in q) for q in P), default=1.0)


class KenarOrnek:
    """STEP kenarının noktaları (başlangıç köşesinden bitişe): ACIS kenar örneklemesiyle aynı sıklık."""

    def __init__(self, egri, p0: V3, p1: V3, ayni: bool, kapali: bool):
        self.egri, self.p0, self.p1 = egri, p0, p1
        t0, t1 = egri.param(p0), egri.param(p1)
        T = getattr(egri, "periyot", None)
        if T:
            if kapali or math.dist(p0, p1) <= 1e-9 * (1 + max(map(abs, p0))):
                t1 = t0 + (T if ayni else -T)
            elif ayni and t1 <= t0:
                t1 += T * math.ceil((t0 - t1) / T + 1e-12)
            elif not ayni and t1 >= t0:
                t1 -= T * math.ceil((t1 - t0) / T + 1e-12)
        self.t0, self.t1 = t0, t1

    def __call__(self, yogunluk: int) -> List[V3]:
        e = self.egri
        if isinstance(e, DogruEgri):
            n = 1
        elif isinstance(e, ElipsEgri):
            n = max(2, int(math.ceil(abs(self.t1 - self.t0) / (2 * math.pi) * 24 * yogunluk)))
        else:
            n = max(2, (e.araliklar(self.t0, self.t1) + 1) * 2 * yogunluk)
        ic = [e.nokta(self.t0 + (self.t1 - self.t0) * i / n) for i in range(1, n)]
        return [self.p0] + ic + [self.p1]


def _nurbs(e) -> Bs3Egri:
    """Eğri → B-spline (doğru: 1. derece; daire / elips: 9 noktalı rasyonel 2. derece)."""
    if isinstance(e, SplineEgri):
        return e.b
    if isinstance(e, DogruEgri):
        return Bs3Egri(1, [0.0, 0.0, 1.0, 1.0], [e.o, e.nokta(1.0)], None)
    if isinstance(e, ElipsEgri):
        s = math.sqrt(0.5)
        yon = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0)]
        P = [_top(e.c, _top(_kat(e.x, e.a * u), _kat(e.y, e.b * v))) for u, v in yon]
        w = [1.0, s, 1.0, s, 1.0, s, 1.0, s, 1.0]
        dug = [0.0, 0.0, 0.0, 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 1.0, 1.0, 1.0]
        return Bs3Egri(2, [d * 2 * math.pi for d in dug], P, w)
    raise AcisHatasi("eğri B-spline'a çevrilemedi")


def _donel(c: Bs3Egri, o: V3, z: V3) -> Bs3Yuzey:
    """Eğrinin eksen çevresinde tam dönüşü: u eğri, v 9 noktalı daire (rasyonel)."""
    s = math.sqrt(0.5)
    yon = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0)]
    wv = [1.0, s, 1.0, s, 1.0, s, 1.0, s, 1.0]
    P, w = [], []
    for (cu, sv), ww in zip(yon, wv):
        for i, q in enumerate(c.P):
            d = _cik(q, o)
            h = _ic(d, z)
            r = _cik(d, _kat(z, h))
            y = _dis(z, r)
            P.append(_top(_top(o, _kat(z, h)), _top(_kat(r, cu), _kat(y, sv))))
            w.append(ww * (c.w[i] if c.w else 1.0))
    dv = [d * 2 * math.pi for d in [0.0, 0.0, 0.0, 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 1.0, 1.0, 1.0]]
    return Bs3Yuzey(c.p, 2, c.dug, dv, c.n, 9, P, w)


# ---------------------------------------------------------------- birimler, montaj

def _birimler(v: Dict[int, Varlik]) -> Tuple[float, float]:
    """(uzunluk birimi → mm, açı birimi → radyan): ilk bağlamın birimleri."""
    uzunluk, aci = None, None
    for x in v.values():
        if x.var("LENGTH_UNIT") and uzunluk is None:
            uzunluk = _birim_degeri(v, x, "LENGTH")
        if x.var("PLANE_ANGLE_UNIT") and aci is None:
            aci = _birim_degeri(v, x, "ANGLE")
    return uzunluk or 1.0, aci or 1.0


ONEK = {"MILLI": 1e-3, "CENTI": 1e-2, "DECI": 1e-1, "MICRO": 1e-6, "KILO": 1e3, "NANO": 1e-9}


def _birim_degeri(v, x: Varlik, tur: str, derin: int = 0) -> Optional[float]:
    if x.var("SI_UNIT"):
        onek = x["SI_UNIT"][0]
        k = ONEK.get(str(onek), 1.0) if onek else 1.0
        return k * 1000.0 if tur == "LENGTH" else k   # uzunluk mm'ye; açı radyan
    if x.var("CONVERSION_BASED_UNIT") and derin < 4:
        ad, olcu = x["CONVERSION_BASED_UNIT"][0], x["CONVERSION_BASED_UNIT"][1]
        try:
            m = v[int(olcu)]
            mad = next(iter(m.parcalar))
            deger, alt = m.parcalar[mad][0], m.parcalar[mad][1]
            d = float(deger.deger[0]) if isinstance(deger, Tipli) else float(deger)
            a = _birim_degeri(v, v[int(alt)], tur, derin + 1)
            if a is not None:
                return d * a
        except (KeyError, TypeError, ValueError, IndexError, StopIteration):
            pass
        ad = str(ad).upper()
        return {"INCH": 25.4, "FOOT": 304.8, "DEGREE": math.pi / 180, "DEGREES": math.pi / 180}.get(ad)
    return None


def _temsiller(v: Dict[int, Varlik]):
    """Katılar, bulundukları temsil ve temsillerin dünyadaki yerleşimleri."""
    temsil_ogeleri: Dict[int, list] = {}
    for no, x in v.items():
        for ad, a in x.parcalar.items():
            if ad.endswith("REPRESENTATION") and len(a) >= 2 and isinstance(a[1], list) and \
                    not ad.startswith("SHAPE_DEFINITION") and not ad.startswith("PROPERTY_DEFINITION"):
                temsil_ogeleri[no] = [int(r) for r in a[1] if isinstance(r, Ref)]
    # özdeş bağlar (dönüşümsüz temsil ilişkisi): aynı grup
    ata = {no: no for no in temsil_ogeleri}

    def bul(a):
        while ata.get(a, a) != a:
            ata[a] = ata.get(ata[a], ata[a])
            a = ata[a]
        return a
    ust: List[Tuple[int, int, Yer]] = []   # (çocuk grup, üst grup, yerleşim)
    c = Cevirici.__new__(Cevirici)
    c.v = v
    for no, x in v.items():
        rr = next((a for ad, a in x.parcalar.items() if ad.endswith("REPRESENTATION_RELATIONSHIP") and len(a) >= 4
                   and isinstance(a[2], Ref) and isinstance(a[3], Ref)), None)
        if rr is None:
            continue
        r1, r2 = int(rr[2]), int(rr[3])
        if x.var("REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION"):
            t = int(x["REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION"][0])
            tv = v.get(t)
            if tv is not None and tv.var("ITEM_DEFINED_TRANSFORMATION"):
                it = tv["ITEM_DEFINED_TRANSFORMATION"]
                try:
                    T = _bilesik(c.yer(it[3]), _ters(c.yer(it[2])))
                except (AcisHatasi, KeyError, IndexError, TypeError):
                    T = BIRIM_YER
                ust.append((r1, r2, T))
                continue
        if r1 in ata and r2 in ata:
            ata[bul(r1)] = bul(r2)
    for no, x in v.items():  # MAPPED_ITEM: temsil başka temsilde yerleştirilir
        if x.var("MAPPED_ITEM"):
            mi = x["MAPPED_ITEM"]
            sahip = [t for t, ogeler in temsil_ogeleri.items() if no in ogeler]
            harita = v.get(int(mi[1]))
            if not sahip or harita is None or not harita.var("REPRESENTATION_MAP"):
                continue
            hm = harita["REPRESENTATION_MAP"]
            try:
                T = _bilesik(c.yer(mi[2]), _ters(c.yer(hm[0])))
            except (AcisHatasi, KeyError, IndexError, TypeError):
                T = BIRIM_YER
            ust.append((int(hm[1]), sahip[0], T))
    ust = [(bul(a), bul(b), T) for a, b, T in ust if a in ata and b in ata]
    yerler: Dict[int, List[Yer]] = {}

    def yerlesim(g, yol=()):
        if g in yerler:
            return yerler[g]
        if g in yol or len(yol) > 30:
            return [BIRIM_YER]
        ustler = [(b, T) for a, b, T in ust if a == g]
        out = [BIRIM_YER] if not ustler else [_bilesik(P, T) for b, T in ustler for P in yerlesim(b, yol + (g,))]
        yerler[g] = out
        return out
    katilar: List[Tuple[int, int]] = []    # (katı, grup)
    gorulen = set()
    for t, ogeler in temsil_ogeleri.items():
        for o in ogeler:
            x = v.get(o)
            if x is not None and (x.var("MANIFOLD_SOLID_BREP") or x.var("BREP_WITH_VOIDS")
                                  or x.var("SHELL_BASED_SURFACE_MODEL")) and o not in gorulen:
                gorulen.add(o)
                katilar.append((o, bul(t)))
    for no, x in v.items():  # temsile bağlanmamış katı
        if (x.var("MANIFOLD_SOLID_BREP") or x.var("BREP_WITH_VOIDS")) and no not in gorulen:
            katilar.append((no, -1))
    return katilar, (lambda g: [BIRIM_YER] if g < 0 else yerlesim(g)), _urun_adlari(v, bul, temsil_ogeleri)


def _urun_adlari(v, bul, temsil_ogeleri) -> Dict[int, str]:
    """Temsil grubu → ürün (parça) adı."""
    out: Dict[int, str] = {}
    for x in v.values():
        if not x.var("SHAPE_DEFINITION_REPRESENTATION"):
            continue
        a = x["SHAPE_DEFINITION_REPRESENTATION"]
        try:
            pds = v[int(a[0])]["PRODUCT_DEFINITION_SHAPE"]
            pd = v[int(pds[2])]
            pdad = next(iter(pd.parcalar))
            form = v[int(pd.parcalar[pdad][2])]
            urun = v[int(form.parcalar[next(iter(form.parcalar))][2])]["PRODUCT"]
            ad = str(urun[1] or urun[0] or "").strip()
        except (KeyError, IndexError, TypeError, ValueError, StopIteration):
            continue
        if ad and int(a[1]) in temsil_ogeleri:
            out.setdefault(bul(int(a[1])), ad)
    return out


# ---------------------------------------------------------------- dışa açılan

@dataclass
class StepModel:
    birim_mm: float                       # dosyanın uzunluk birimi (mm)
    govdeler: list = field(default_factory=list)     # acis_alan.Govde (dosya biriminde)
    adlar: List[str] = field(default_factory=list)


def oku(yol: str) -> StepModel:
    with open(yol, "rb") as f:
        ham = f.read()
    metin = ham.decode("utf-8", errors="replace")
    return modelle(ayristir(metin))


def modelle(v: Dict[int, Varlik]) -> StepModel:
    c = Cevirici(v)
    katilar, yerlesim, urun = _temsiller(v)
    bodies: List[Kayit] = []
    adlar: List[str] = []
    lumplar: Dict[int, Kayit] = {}
    hatali: Dict[int, str] = {}
    for kati, grup in katilar:
        x = v[kati]
        try:
            if kati not in lumplar:
                lump = Kayit("lump")
                if x.var("SHELL_BASED_SURFACE_MODEL"):
                    kabuklar = list(x["SHELL_BASED_SURFACE_MODEL"][1])
                elif x.var("BREP_WITH_VOIDS"):
                    kabuklar = [x["BREP_WITH_VOIDS"][1]] + list(x["BREP_WITH_VOIDS"][2])
                else:
                    kabuklar = [x["MANIFOLD_SOLID_BREP"][1]]
                onceki, ilk = None, None
                for k in kabuklar:
                    onceki = c.kabuk(k, lump, onceki)
                    ilk = ilk or onceki
                lump.oge = [None, None, ilk, None]
                lumplar[kati] = lump
        except (AcisHatasi, KeyError, IndexError, TypeError, ValueError) as h:
            hatali[kati] = str(h)
            continue
        yerler = yerlesim(grup)
        kati_adi = str(x.parcalar[next(iter(x.parcalar))][0] or "").strip()
        temel = urun.get(grup) or kati_adi or f"katı {len(adlar) + 1}"
        for i, Y in enumerate(yerler):
            b = Kayit("body")
            tr = Kayit("transform")
            xx, yy, zz, t = Y
            tr.oge = [*xx, *yy, *zz, *t, 1.0]
            lump = lumplar[kati] if i == 0 else _kopya_lump(lumplar[kati])
            b.oge = [None, lump, None, tr]
            lump.oge[3] = b
            bodies.append(b)
            adlar.append(temel)
    c.esle()
    govdeler = acis_alan.kayit_govdeleri(bodies) if bodies else []
    if len(govdeler) != len(bodies):  # gövdede lump zinciri yok: ad sayısı tutmaz
        adlar = [f"katı {i + 1}" for i in range(len(govdeler))]
    for kati, h in hatali.items():
        g = acis_alan.Govde()
        g.hata = f"STEP katısı okunamadı ({h})"
        govdeler.append(g)
        adlar.append(f"katı #{kati}")
    if not govdeler:
        raise StepHatasi("STEP dosyasında katı (B-rep) yok. Tel çerçeve ya da yalnız yüzey modeli olabilir.")
    return StepModel(c.uzunluk, govdeler, _benzersiz(adlar))


def _kopya_lump(lump: Kayit) -> Kayit:
    """Aynı parçanın başka yerleşimi: lump kaydı ayrı (gövdesi farklı), kabuk ve yüzler ortak."""
    k = Kayit("lump")
    k.oge = list(lump.oge)
    return k


def _benzersiz(adlar: List[str]) -> List[str]:
    say: Dict[str, int] = {}
    for a in adlar:
        say[a] = say.get(a, 0) + 1
    sira: Dict[str, int] = {}
    out = []
    for a in adlar:
        if say[a] > 1:
            sira[a] = sira.get(a, 0) + 1
            out.append(f"{a} ({sira[a]})")
        else:
            out.append(a)
    return out


def cozumle(model: StepModel, k: float):
    """dxf_oku.DxfSonuc: STEP'teki gövdeler mm'de (k: dosya birimi → mm)."""
    import copy

    import dxf_oku
    from geometri import yerlestir  # noqa: F401  (2D yok)
    s = dxf_oku.DxfSonuc(olcek=k)
    s.govdeler = dxf_oku.govde3d_listesi(copy.deepcopy(model.govdeler), list(model.adlar), "STEP", k,
                                         cozum="parçayı STL olarak dışa aktarın ya da kalıptan ekleyin")
    dxf_oku._kaynak_onerisi(s.govdeler)
    return s
