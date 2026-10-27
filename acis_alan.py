# -*- coding: utf-8 -*-
"""ACIS katı gövdelerinin (DXF 3DSOLID / BODY / REGION / SURFACE) yüzey alanı.

ezdxf yalnız kayıtları ayırmak için kullanılır (SAT metni ya da SAB ikili veri); alanların anlamı burada okunur.
ezdxf'in kendi ACIS nesneleri, AutoCAD'in yeni ASM sürümlerinin yazdığı ek alanlarda (köşe kaydındaki sayaç gibi)
ayrıştırma hatası verdiği ve eğri yüzeyleri hiç tanımadığı için kullanılmaz.

Her yüzün alanı, yüzeyin parametre düzleminde Green teoremiyle sınır döngülerinden bulunur (kenarlar gerçek
eğrilerinden örneklenir, üç sıklıkta hesaplanıp Romberg ile düzeltilir):

  düzlem          ½ ∮ (u dv − v du)
  silindir / koni ∮ L(h) dθ,  L = −√(1+k²) (r₀ h + k h²/2)     (ρ(h) = r₀ + k h)
  küre            ∮ −R² sin φ dθ
  torus           ∮ −r (R φ + r sin φ) dθ   (döngü φ yönünde dolanıyorsa ∮ r (R + r cos φ) θ dφ)
  spline (NURBS)  yüz bütün parametre alanını kaplıyorsa ∬ |S_u × S_v| du dv (Gauss); kırpılmış spline yüz
                  desteklenmez, gövde hata ile döner

Kenarlar: doğru, daire / elips, intcurve (içindeki B-spline yaklaşımı). Tek bir yüz hesaplanamazsa gövdenin alanı
verilmez (eksik alan sessizce toplanmaz)."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

V3 = Tuple[float, float, float]


class AcisHatasi(Exception):
    pass


# ---------------------------------------------------------------- vektör

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


def _boy(a):
    return math.sqrt(_ic(a, a))


def _birim(a):
    n = _boy(a)
    if n == 0.0:
        raise AcisHatasi("sıfır uzunlukta yön")
    return a[0] / n, a[1] / n, a[2] / n


def _dik_birim(a):
    """a'ya dik herhangi bir birim vektör."""
    x = (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)
    return _birim(_dis(a, x))


# ---------------------------------------------------------------- kayıtlar

class Kayit:
    """Bir ACIS kaydı: tür adı ve SAT / SAB'den aynı biçime getirilmiş öğeler.
    Öğeler: sayı (float), işaretçi (Kayit ya da None), sözcük (str: SAT sözcüğü; SAB'de 'T' / 'F' / 'enumN'),
    '{' ve '}' (alt tür sınırları)."""
    __slots__ = ("ad", "tur", "oge", "_ham")

    def __init__(self, ad: str):
        self.ad = ad
        parca = ad.split("-")
        # tcoedge-coedge, tedge-edge, tvertex-vertex: hoşgörülü (tolerant) türler, temel türün alanlarıyla başlar
        self.tur = parca[-1] if parca[-1] in ("coedge", "edge", "vertex") else ad
        self.oge: list = []

    def isaretciler(self) -> List[Optional["Kayit"]]:
        return [x for x in self.oge if isinstance(x, Kayit) or x is None]

    def sayilar(self) -> List[float]:
        """Alt tür ({ ... }) dışındaki sayılar, sırayla."""
        out, derin = [], 0
        for x in self.oge:
            if x == "{":
                derin += 1
            elif x == "}":
                derin -= 1
            elif derin == 0 and isinstance(x, float):
                out.append(x)
        return out

    def sozcukler(self) -> List[str]:
        return [x for x in self.oge if isinstance(x, str) and x not in ("{", "}")]


_BOS = object()


def kayitlari_oku(e) -> List[Kayit]:
    """DXF ACIS varlığının kayıtları (ezdxf'in ham ayrıştırıcısıyla)."""
    from ezdxf.acis import abstract

    if getattr(e, "has_binary_data", False):
        from ezdxf.acis import sab
        from ezdxf.acis.const import Tags
        veri = e.sab
        if not veri:
            raise AcisHatasi("ACIS verisi boş")
        ham = sab.parse_sab(veri).entities
        cevir = _sab_ogesi(Tags)
    else:
        from ezdxf.acis import sat
        veri = e.sat
        if not veri:
            raise AcisHatasi("ACIS verisi boş")
        ham = sat.parse_sat(veri).entities
        cevir = _sat_ogesi
    harita: Dict[int, Kayit] = {}
    kayitlar = []
    for h in ham:
        k = Kayit(h.name)
        harita[id(h)] = k
        kayitlar.append(k)
    for h, k in zip(ham, kayitlar):
        for x in h.data:
            for y in cevir(x):
                if y is _BOS:
                    continue
                if isinstance(y, abstract.AbstractEntity):
                    k.oge.append(None if y.is_null_ptr or id(y) not in harita else harita[id(y)])
                else:
                    k.oge.append(y)
    return kayitlar


def _sat_ogesi(x):
    from ezdxf.acis import abstract
    if isinstance(x, abstract.AbstractEntity):
        return (x,)
    s = str(x)
    try:
        return (float(s),)
    except ValueError:
        return (s,)


def _sab_ogesi(Tags):
    def cevir(t):
        from ezdxf.acis import abstract
        if isinstance(t, abstract.AbstractEntity):
            return (t,)
        tag, v = t.tag, t.value
        if tag in (Tags.INT, Tags.DOUBLE, Tags.UNKNOWN_0x17):
            return (float(v),)
        if tag in (Tags.LOCATION_VEC, Tags.DIRECTION_VEC):
            return tuple(float(c) for c in v)
        if tag == Tags.POINTER:
            return (v,)
        if tag == Tags.BOOL_TRUE:
            return ("T",)
        if tag == Tags.BOOL_FALSE:
            return ("F",)
        if tag == Tags.SUBTYPE_START:
            return ("{",)
        if tag == Tags.SUBTYPE_END:
            return ("}",)
        if tag == Tags.ENUM:
            return (f"enum{v}",)
        if tag in (Tags.STR, Tags.LITERAL_STR):
            return (str(v),)
        return (_BOS,)
    return cevir


def _ters_mi(soz: str) -> bool:
    """Yön sözcüğü: SAT 'reversed', SAB BOOL_TRUE."""
    return soz in ("reversed", "T")


# ---------------------------------------------------------------- B-spline

class BSpline:
    """ACIS bs3 eğri / yüzey verisi: düğümler (çokluklarıyla, uçlardaki birer düğüm eksik yazılır)."""

    @staticmethod
    def dugumler(cift: Sequence[float], derece: int) -> List[float]:
        k = []
        for i in range(0, len(cift), 2):
            k += [cift[i]] * int(round(cift[i + 1]))
        return [k[0]] + k + [k[-1]]

    @staticmethod
    def taban(dug: Sequence[float], p: int, n: int, t: float):
        """t'nin aralığı ve sıfır olmayan p+1 taban fonksiyonu (Cox–de Boor)."""
        lo, hi = dug[p], dug[n]
        t = min(max(t, lo), hi)
        if t >= hi:
            span = n - 1
            while span > p and dug[span] == dug[span + 1]:
                span -= 1
        else:
            span = p
            a, b = p, n
            while b - a > 1:  # ikili arama
                m = (a + b) // 2
                if dug[m] <= t:
                    a = m
                else:
                    b = m
            span = a
        N = [1.0] + [0.0] * p
        sol, sag = [0.0] * (p + 1), [0.0] * (p + 1)
        for j in range(1, p + 1):
            sol[j] = t - dug[span + 1 - j]
            sag[j] = dug[span + j] - t
            kayan = 0.0
            for r in range(j):
                pay = sag[r + 1] + sol[j - r]
                tmp = N[r] / pay if pay != 0.0 else 0.0
                N[r] = kayan + sag[r + 1] * tmp
                kayan = sol[j - r] * tmp
            N[j] = kayan
        return span, N


class Bs3Egri:
    def __init__(self, derece: int, dug: List[float], noktalar: List[V3], agirlik: Optional[List[float]]):
        self.p, self.dug, self.P, self.w = derece, dug, noktalar, agirlik
        self.n = len(noktalar)
        if len(dug) != self.n + derece + 1:
            raise AcisHatasi("B-spline eğrisinde düğüm / kontrol noktası sayısı uyuşmuyor")
        self.t0, self.t1 = dug[derece], dug[self.n]

    def nokta(self, t: float) -> V3:
        span, N = BSpline.taban(self.dug, self.p, self.n, t)
        x = y = z = ws = 0.0
        for j in range(self.p + 1):
            i = span - self.p + j
            w = N[j] * (self.w[i] if self.w else 1.0)
            q = self.P[i]
            x += w * q[0]
            y += w * q[1]
            z += w * q[2]
            ws += w
        return x / ws, y / ws, z / ws


class Bs3Yuzey:
    def __init__(self, pu, pv, du, dv, nu, nv, noktalar, agirlik):
        self.pu, self.pv, self.du, self.dv, self.nu, self.nv = pu, pv, du, dv, nu, nv
        self.P, self.w = noktalar, agirlik
        if len(du) != nu + pu + 1 or len(dv) != nv + pv + 1 or len(noktalar) != nu * nv:
            raise AcisHatasi("B-spline yüzeyinde düğüm / kontrol noktası sayısı uyuşmuyor")
        self.u0, self.u1 = du[pu], du[nu]
        self.v0, self.v1 = dv[pv], dv[nv]

    def nokta(self, u: float, v: float) -> V3:
        su, Nu = BSpline.taban(self.du, self.pu, self.nu, u)
        sv, Nv = BSpline.taban(self.dv, self.pv, self.nv, v)
        x = y = z = ws = 0.0
        for b in range(self.pv + 1):
            iv = sv - self.pv + b
            for a in range(self.pu + 1):
                iu = su - self.pu + a
                k = iv * self.nu + iu  # u en hızlı değişen
                w = Nu[a] * Nv[b] * (self.w[k] if self.w else 1.0)
                q = self.P[k]
                x += w * q[0]
                y += w * q[1]
                z += w * q[2]
                ws += w
        return x / ws, y / ws, z / ws

    def alan(self, donus) -> float:
        """∬ |S_u × S_v| du dv, her düğüm aralığında 6 × 6 Gauss noktası; türevler merkezi farkla."""
        gx = [-0.9324695142, -0.6612093865, -0.2386191861, 0.2386191861, 0.6612093865, 0.9324695142]
        gw = [0.1713244924, 0.3607615730, 0.4679139346, 0.4679139346, 0.3607615730, 0.1713244924]
        ua = sorted(set(self.du[self.pu:self.nu + 1]))
        va = sorted(set(self.dv[self.pv:self.nv + 1]))
        S = lambda u, v: donus(self.nokta(u, v))
        toplam = 0.0
        for i in range(len(ua) - 1):
            a0, a1 = ua[i], ua[i + 1]
            hu = (a1 - a0) * 1e-5
            for j in range(len(va) - 1):
                b0, b1 = va[j], va[j + 1]
                hv = (b1 - b0) * 1e-5
                for x, wx in zip(gx, gw):
                    u = 0.5 * (a0 + a1) + 0.5 * (a1 - a0) * x
                    for y, wy in zip(gx, gw):
                        v = 0.5 * (b0 + b1) + 0.5 * (b1 - b0) * y
                        Su = _kat(_cik(S(u + hu, v), S(u - hu, v)), 0.5 / hu)
                        Sv = _kat(_cik(S(u, v + hv), S(u, v - hv)), 0.5 / hv)
                        toplam += wx * wy * 0.25 * (a1 - a0) * (b1 - b0) * _boy(_dis(Su, Sv))
        return toplam


def _alt_tur(oge: list) -> list:
    """Kaydın ilk { ... } bloğunun öğeleri (iç içe bloklar dahil, sınırlar hariç)."""
    out, derin, basladi = [], 0, False
    for x in oge:
        if x == "{":
            derin += 1
            if derin == 1:
                basladi = True
                continue
        elif x == "}":
            derin -= 1
            if derin == 0 and basladi:
                return out
        if basladi:
            out.append(x)
    raise AcisHatasi("alt tür verisi yok")


def _bs3_basi(o: list) -> Tuple[int, bool]:
    """B-spline verisinin başı: (rasyonellik sözcüğünün konumu, rasyonel mi). SAT'ta sözcük 'nubs' / 'nurbs';
    SAB'de sayı (enum) yazılır: o zaman ad ve 'full' sözcüğünden sonraki ikinci sözcük, rasyonel değil sayılır
    (yanlışsa kontrol noktaları sınır eğrileriyle uyuşmaz ve yüz reddedilir)."""
    for i, x in enumerate(o):
        if x in ("nubs", "nurbs"):
            return i, x == "nurbs"
    sozcuk = [i for i, x in enumerate(o) if isinstance(x, str) and i > 0]
    if len(sozcuk) >= 2:
        return sozcuk[1], False
    raise AcisHatasi("B-spline verisi bulunamadı (desteklenmeyen spline türü)")


def _sayi_dizisi(o: list, i: int) -> Tuple[List[float], int]:
    out = []
    while i < len(o) and isinstance(o[i], float):
        out.append(o[i])
        i += 1
    return out, i


def bs3_egri(k: Kayit) -> Bs3Egri:
    o = _alt_tur(k.oge)
    i, rasyonel = _bs3_basi(o)
    derece = int(o[i + 1])
    # form sözcüğü (open / closed / periodic), sonra düğüm sayısı
    j = i + 2
    while j < len(o) and not isinstance(o[j], float):
        j += 1
    nk = int(o[j])
    cift, j = _sayi_dizisi(o, j + 1)
    dug = BSpline.dugumler(cift[:2 * nk], derece)
    n = len(dug) - derece - 1
    kalan = cift[2 * nk:]
    adim = 4 if rasyonel else 3
    if len(kalan) < adim * n:
        raise AcisHatasi("B-spline eğrisinin kontrol noktaları eksik")
    P = [tuple(kalan[adim * m:adim * m + 3]) for m in range(n)]
    w = [kalan[adim * m + 3] for m in range(n)] if rasyonel else None
    return Bs3Egri(derece, dug, P, w)


def _bs3_yuzey_oku(o: list, i: int, rasyonel: bool) -> Bs3Yuzey:
    """o[i]: 'nubs' / 'nurbs' (ya da SAB enum); ardından derece u, derece v, biçimler, düğüm sayıları ..."""
    pu, pv = int(o[i + 1]), int(o[i + 2])
    j = i + 3
    while j < len(o) and not isinstance(o[j], float):  # biçimler ve tekillikler
        j += 1
    nku, nkv = int(o[j]), int(o[j + 1])
    sayi, j = _sayi_dizisi(o, j + 2)
    du = BSpline.dugumler(sayi[:2 * nku], pu)
    dv = BSpline.dugumler(sayi[2 * nku:2 * nku + 2 * nkv], pv)
    nu, nv = len(du) - pu - 1, len(dv) - pv - 1
    kalan = sayi[2 * nku + 2 * nkv:]
    adim = 4 if rasyonel else 3
    if len(kalan) < adim * nu * nv:
        raise AcisHatasi("B-spline yüzeyinin kontrol noktaları eksik")
    P = [tuple(kalan[adim * m:adim * m + 3]) for m in range(nu * nv)]
    w = [kalan[adim * m + 3] for m in range(nu * nv)] if rasyonel else None
    return Bs3Yuzey(pu, pv, du, dv, nu, nv, P, w)


def bs3_yuzeyler(k: Kayit) -> Tuple[str, List[Bs3Yuzey]]:
    """Spline yüzey kaydındaki okunabilen bütün B-spline yüzeyler (alt tür adıyla). exact_spl_sur'da tek yüzey
    vardır; loft / süpürme gibi yöntem yüzeylerinde tanım eğrilerinin yanında yaklaşık yüzey de saklanır: hangisinin
    yüzün kendisi olduğuna sınır denetimi karar verir (yuz_alani)."""
    o = _alt_tur(k.oge)
    ad = str(o[0]) if o else "?"
    adaylar: List[Bs3Yuzey] = []
    yerler = [(i, x == "nurbs") for i, x in enumerate(o) if x in ("nubs", "nurbs")]
    if not yerler:  # SAB: rasyonellik sözcük değil sayı
        try:
            yerler = [_bs3_basi(o)]
        except AcisHatasi:
            yerler = []
    for i, rasyonel in yerler:
        try:
            if isinstance(o[i + 1], float) and isinstance(o[i + 2], float):
                adaylar.append(_bs3_yuzey_oku(o, i, rasyonel))
        except (AcisHatasi, IndexError, ValueError, TypeError):
            continue
    if not adaylar:
        raise AcisHatasi(f"spline yüzey verisi okunamadı ({ad})")
    return ad, adaylar


def bs3_yuzey(k: Kayit) -> Bs3Yuzey:
    return bs3_yuzeyler(k)[1][0]


# ---------------------------------------------------------------- eğriler

def _aralik_atla(s: List, i: int) -> int:
    """SAT 'I' / 'F x' (SAB 'T' / 'F' x) aralığını atlar."""
    if i < len(s) and s[i] in ("I", "T"):
        return i + 1
    if i < len(s) and s[i] == "F":
        return i + 2
    return i


class Egri:
    """Kenar eğrisi: nokta(t) ACIS eğri parametresinde."""

    def __init__(self, k: Kayit):
        self.k = k
        s = k.sayilar()
        if k.ad == "straight-curve":
            self.tur = "dogru"
            self.o, self.d = tuple(s[0:3]), tuple(s[3:6])
        elif k.ad == "ellipse-curve":
            self.tur = "elips"
            self.c, n, self.M, self.oran = tuple(s[0:3]), _birim(tuple(s[3:6])), tuple(s[6:9]), s[9]
            self.N = _kat(_dis(n, self.M), self.oran)
        elif k.ad == "intcurve-curve":
            self.tur = "spline"
            self.b = bs3_egri(k)
        else:
            raise AcisHatasi(f"desteklenmeyen kenar eğrisi ({k.ad})")

    def nokta(self, t: float) -> V3:
        if self.tur == "dogru":
            return _top(self.o, _kat(self.d, t))
        if self.tur == "elips":
            return _top(self.c, _top(_kat(self.M, math.cos(t)), _kat(self.N, math.sin(t))))
        return self.b.nokta(t)

    def ornek_sayisi(self, t0: float, t1: float, yogunluk: int) -> int:
        if self.tur == "dogru":
            return 1
        if self.tur == "elips":
            return max(2, int(math.ceil(abs(t1 - t0) / (2 * math.pi) * 24 * yogunluk)))
        araliklar = sum(1 for a, b in zip(self.b.dug, self.b.dug[1:]) if b > a and min(t0, t1) <= a < max(t0, t1))
        return max(2, (araliklar + 1) * 2 * yogunluk)


def _kenar_noktalari(kenar: Kayit, yogunluk: int, tol: float, onbellek: dict) -> List[V3]:
    """Kenarın başından sonuna noktaları (kenar yönünde). Parametre eşlemesi köşe noktalarıyla doğrulanır."""
    anahtar = (id(kenar), yogunluk)
    if anahtar in onbellek:
        return onbellek[anahtar]
    p = kenar.isaretciler()
    s = kenar.sayilar()
    w = kenar.sozcukler()
    # edge: [desen, başlangıç köşesi, bitiş köşesi, coedge, eğri]; sayılar: [başlangıç t, bitiş t, ...]
    if len(p) < 5 or len(s) < 2 or p[4] is None:
        raise AcisHatasi("kenar kaydı eksik")
    a, b = _kose(p[1]), _kose(p[2])
    egri = _egri(p[4], onbellek)
    ters = bool(w) and _ters_mi(w[0])
    t0, t1 = s[0], s[1]
    adaylar = [(-t0, -t1), (t0, t1)] if ters else [(t0, t1), (-t0, -t1)]
    secilen = None
    for x0, x1 in adaylar:
        if _boy(_cik(egri.nokta(x0), a)) <= tol and _boy(_cik(egri.nokta(x1), b)) <= tol:
            secilen = (x0, x1)
            break
    if secilen is None:
        raise AcisHatasi("kenar parametreleri köşe noktalarıyla uyuşmuyor")
    x0, x1 = secilen
    n = egri.ornek_sayisi(x0, x1, yogunluk)
    out = [a] + [egri.nokta(x0 + (x1 - x0) * i / n) for i in range(1, n)] + [b]
    onbellek[anahtar] = out
    return out


def _kose(v: Optional[Kayit]) -> V3:
    # vertex: [desen, kenar, (sayaç), nokta]; point: x y z
    if v is None:
        raise AcisHatasi("köşe yok")
    pts = [x for x in v.isaretciler() if x is not None and x.ad == "point"]
    if not pts:
        raise AcisHatasi("köşenin noktası yok")
    s = pts[-1].sayilar()
    return s[0], s[1], s[2]


def _egri(k: Kayit, onbellek: dict) -> Egri:
    a = ("egri", id(k))
    if a not in onbellek:
        onbellek[a] = Egri(k)
    return onbellek[a]


# ---------------------------------------------------------------- yüzeyler

def _dongu(loop: Kayit, yogunluk: int, tol: float, onbellek: dict) -> List[V3]:
    """Döngünün kapalı nokta dizisi (coedge yönünde; son nokta ilkini tekrar etmez)."""
    p = loop.isaretciler()
    # loop: [desen, sonraki döngü, coedge, yüz]
    ilk = p[2] if len(p) > 2 else None
    if ilk is None:
        raise AcisHatasi("döngünün coedge'i yok")
    out: List[V3] = []
    c, adim = ilk, 0
    while True:
        cp = c.isaretciler()
        # coedge: [desen, sonraki, önceki, eş, kenar, döngü, pcurve]
        kenar = cp[4] if len(cp) > 4 else None
        if kenar is None:
            raise AcisHatasi("coedge'in kenarı yok")
        pts = _kenar_noktalari(kenar, yogunluk, tol, onbellek)
        if _ters_mi(c.sozcukler()[0] if c.sozcukler() else "forward"):
            pts = pts[::-1]
        if out and _boy(_cik(out[-1], pts[0])) > tol:
            raise AcisHatasi("döngü kopuk (kenarlar uç uca gelmiyor)")
        out.extend(pts[1:] if out else pts)
        c = cp[1]
        adim += 1
        if c is None:
            raise AcisHatasi("döngü kapanmıyor")
        if c is ilk:
            break
        if adim > 100000:
            raise AcisHatasi("döngü kapanmıyor")
    if len(out) > 1 and _boy(_cik(out[0], out[-1])) <= tol:
        out.pop()
    return out


def _sar(a: float) -> float:
    while a > math.pi:
        a -= 2 * math.pi
    while a <= -math.pi:
        a += 2 * math.pi
    return a


class Yuzey:
    def __init__(self, k: Kayit):
        self.ad = k.ad
        s = k.sayilar()
        if k.ad == "plane-surface":
            self.tur = "duzlem"
            self.o, self.n = tuple(s[0:3]), _birim(tuple(s[3:6]))
            u = tuple(s[6:9]) if len(s) >= 9 and _boy(tuple(s[6:9])) > 0 else _dik_birim(self.n)
            self.U = _birim(_cik(u, _kat(self.n, _ic(u, self.n))))
            self.V = _dis(self.n, self.U)
        elif k.ad == "cone-surface":
            self.tur = "koni"
            self.c, self.a, M, oran = tuple(s[0:3]), _birim(tuple(s[3:6])), tuple(s[6:9]), s[9]
            if abs(oran - 1.0) > 1e-9:
                raise AcisHatasi("eliptik silindir / koni desteklenmez")
            self.r0 = _boy(M)
            self.e1 = _birim(M)
            self.e2 = _dis(self.a, self.e1)
            # oran'dan sonra aralıklar, sonra sin, cos
            oge = [x for x in k.oge if not isinstance(x, Kayit) and x is not None]
            i = [j for j, x in enumerate(oge) if isinstance(x, float)][9] + 1
            i = _aralik_atla(oge, _aralik_atla(oge, i))
            sn, cs = float(oge[i]), float(oge[i + 1])
            self.egim = sn / cs if abs(cs) > 1e-15 else None
            if self.egim is None:
                raise AcisHatasi("düzlemsel koni desteklenmez")
            self.olcum: List[Tuple[float, float]] = []
        elif k.ad == "sphere-surface":
            self.tur = "kure"
            self.c, self.R = tuple(s[0:3]), abs(s[3])
            self.ice = s[3] < 0  # ACIS: eksi yarıçap, normal içe (boşluk)
            self.a = _birim(tuple(s[7:10])) if len(s) >= 10 and _boy(tuple(s[7:10])) > 0 else (0.0, 0.0, 1.0)
            self.e1 = _dik_birim(self.a)
            self.e2 = _dis(self.a, self.e1)
        elif k.ad == "torus-surface":
            self.tur = "torus"
            self.c, self.a, self.R, self.r = tuple(s[0:3]), _birim(tuple(s[3:6])), s[6], abs(s[7])
            u = tuple(s[8:11]) if len(s) >= 11 and _boy(tuple(s[8:11])) > 0 else _dik_birim(self.a)
            self.e1 = _birim(_cik(u, _kat(self.a, _ic(u, self.a))))
            self.e2 = _dis(self.a, self.e1)
        elif k.ad == "spline-surface":
            self.tur = "spline"
            self.alt_tur, self.adaylar = bs3_yuzeyler(k)
        else:
            raise AcisHatasi(f"desteklenmeyen yüzey ({k.ad})")

    # -- Green: döngü başına ∮ katkısı (işaretli)
    def dongu_integrali(self, pts: List[V3]) -> Tuple[float, int, int]:
        """(∮ katkısı, θ dolanma sayısı, φ dolanma sayısı)."""
        n = len(pts)
        if self.tur == "duzlem":
            uv = [(_ic(_cik(p, self.o), self.U), _ic(_cik(p, self.o), self.V)) for p in pts]
            s = 0.0
            for i in range(n):
                x0, y0 = uv[i]
                x1, y1 = uv[(i + 1) % n]
                s += x0 * y1 - x1 * y0
            return 0.5 * s, 0, 0
        if self.tur == "koni":
            k = self.egim
            olcek = math.sqrt(1.0 + k * k)
            h, th = [], []
            for p in pts:
                d = _cik(p, self.c)
                h.append(_ic(d, self.a))
                th.append(math.atan2(_ic(d, self.e2), _ic(d, self.e1)))
                if k != 0.0:
                    # yarıçap eksen boyunca hangi yönde değişiyor: ölçülen ρ ile r₀ ± k h karşılaştırılır
                    rho = math.hypot(_ic(d, self.e1), _ic(d, self.e2))
                    self.olcum.append((h[-1], rho))
            if k == 0.0:  # silindir
                L = lambda z: -self.r0 * z
            else:  # ρ = r₀ + k h; tepede (ρ = 0) sıfır olan biçim: sivri koninin tek döngüsü de doğru alanı verir
                L = lambda z: -olcek * (self.r0 + k * z) ** 2 / (2.0 * k)
            s, dol = 0.0, 0.0
            for i in range(n):
                j = (i + 1) % n
                dt = _sar(th[j] - th[i])
                dol += dt
                s += 0.5 * (L(h[i]) + L(h[j])) * dt
            return s, int(round(dol / (2 * math.pi))), 0
        if self.tur == "kure":
            R = self.R
            fi, th = [], []
            for p in pts:
                d = _cik(p, self.c)
                fi.append(math.asin(max(-1.0, min(1.0, _ic(d, self.a) / R))))
                th.append(math.atan2(_ic(d, self.e2), _ic(d, self.e1)))
            s, dol = 0.0, 0.0
            for i in range(n):
                j = (i + 1) % n
                dt = _sar(th[j] - th[i])
                dol += dt
                s += 0.5 * (-R * R * math.sin(fi[i]) - R * R * math.sin(fi[j])) * dt
            # L = −R² sin φ kutuplarda sıfır değil: içinde kutup olan yüzde (döngü eksen çevresinde dolanır) kutbun
            # katkısı yüz_alani'nda eklenir (kutup_payi)
            return s, int(round(dol / (2 * math.pi))), 0
        if self.tur == "torus":
            R, r = self.R, self.r
            th, fi = [], []
            for p in pts:
                d = _cik(p, self.c)
                z = _ic(d, self.a)
                x, y = _ic(d, self.e1), _ic(d, self.e2)
                th.append(math.atan2(y, x))
                fi.append(math.atan2(z, math.hypot(x, y) - R))
            dth = [_sar(th[(i + 1) % n] - th[i]) for i in range(n)]
            dfi = [_sar(fi[(i + 1) % n] - fi[i]) for i in range(n)]
            dol_t, dol_f = int(round(sum(dth) / (2 * math.pi))), int(round(sum(dfi) / (2 * math.pi)))
            # açılmış (sürekli) açılar
            tu, fu = [th[0]], [fi[0]]
            for i in range(n - 1):
                tu.append(tu[-1] + dth[i])
                fu.append(fu[-1] + dfi[i])
            s = 0.0
            if dol_f == 0:  # ∮ −r (R φ + r sin φ) dθ
                L = lambda f: -r * (R * f + r * math.sin(f))
                for i in range(n):
                    f0, f1 = fu[i], fu[i] + dfi[i]
                    s += 0.5 * (L(f0) + L(f1)) * dth[i]
            else:  # ∮ r (R + r cos φ) θ dφ   (θ dolanmıyor olmalı)
                M = lambda t, f: r * (R + r * math.cos(f)) * t
                for i in range(n):
                    t0, t1 = tu[i], tu[i] + dth[i]
                    f0, f1 = fu[i], fu[i] + dfi[i]
                    s += 0.5 * (M(t0, f0) + M(t1, f1)) * dfi[i]
            return s, dol_t, dol_f
        raise AcisHatasi("bu yüzey türünde döngü integrali yok")


def yuz_alani(face: Kayit, donus, tol: float, onbellek: dict) -> Tuple[float, List[List[V3]]]:
    """Yüzün alanı (yerel birimde) ve önizleme için döngüleri (dünya koordinatında)."""
    p = face.isaretciler()
    # face: [desen, sonraki yüz, döngü, kabuk, alt kabuk, yüzey]
    if len(p) < 6 or p[5] is None:
        raise AcisHatasi("yüzün yüzeyi yok")
    yuzey = _yuzey(p[5], onbellek)
    donguler = []
    loop = p[2]
    while loop is not None:
        donguler.append(loop)
        loop = loop.isaretciler()[1]
    if not donguler:  # döngüsüz yüz: yüzeyin tamamı (kapalı yüzeylerde)
        if yuzey.tur == "kure":
            return 4 * math.pi * yuzey.R ** 2, []
        if yuzey.tur == "torus":
            return 4 * math.pi ** 2 * yuzey.R * yuzey.r, []
        raise AcisHatasi("yüzün döngüsü yok")
    yuz_ters = bool(face.sozcukler()) and _ters_mi(face.sozcukler()[0])

    if yuzey.tur == "spline":
        pts = [_dongu(l, 4, tol, onbellek) for l in donguler]
        for b in yuzey.adaylar:
            try:
                _spline_tam_mi(b, pts, tol)
            except AcisHatasi:
                continue
            return b.alan(lambda q: q), [[donus(q) for q in d] for d in pts]
        raise AcisHatasi(f"kırpılmış ya da tanınmayan spline yüz ({yuzey.alt_tur})")

    if yuzey.tur == "koni" and yuzey.egim != 0.0:
        yuzey.olcum = []
        for l in donguler:
            yuzey.dongu_integrali(_dongu(l, 2, tol, onbellek))
        hata = lambda k: max(abs(rho - (yuzey.r0 + k * hh)) for hh, rho in yuzey.olcum)
        if hata(-yuzey.egim) < hata(yuzey.egim):
            yuzey.egim = -yuzey.egim
        if hata(yuzey.egim) > max(tol * 10, 1e-6 * yuzey.r0):
            raise AcisHatasi("koni yüzeyi kenar noktalarıyla uyuşmuyor")

    def hesap(yog):
        """(alan, yedek alan, döngüler). Yedek: düzlemde en büyük döngüden diğerleri (yönü bozuk dosyalar için)."""
        dl = [_dongu(l, yog, tol, onbellek) for l in donguler]
        toplam, dol_t, dol_f, ayri = 0.0, 0, 0, []
        for d in dl:
            s, a, b = yuzey.dongu_integrali(d)
            toplam += s
            ayri.append(abs(s))
            dol_t += abs(a)
            dol_f += abs(b)
        if yuzey.tur == "torus" and dol_t and dol_f:
            tam = 4 * math.pi ** 2 * yuzey.R * yuzey.r  # tam torus (iki yönde dolanan döngüler)
            return tam, tam, dl
        if yuzey.tur == "kure":
            net = sum(yuzey.dongu_integrali(d)[1] for d in dl)
            if net:
                # Döngüler dışarıdan bakınca saat tersi: dışa bakan yüzde net dolanma + ise kuzey kutbu içeride.
                # Kuzey kutbunda L = −R² sin φ yerine R² (1 − sin φ) (kutupta sıfır): fark R² ∮ dθ = 2π R² net.
                disa = (not yuzey.ice) != yuz_ters
                kuzey = (net > 0) == disa
                toplam += (1.0 if kuzey else -1.0) * 2 * math.pi * yuzey.R ** 2 * net
        ayri.sort(reverse=True)
        return abs(toplam), ayri[0] - sum(ayri[1:]), dl

    def romberg(a, b, c):
        """Üç sıklıktaki (n, 2n, 4n) değerden: çokgen hatası n⁻², n⁻⁴ terimleri düşer."""
        r1, r2 = (4 * b - a) / 3, (4 * c - b) / 3
        return (16 * r2 - r1) / 15

    a1, y1, _ = hesap(2)
    a2, y2, _ = hesap(4)
    a3, y3, dl = hesap(8)
    alan = romberg(a1, a2, a3)
    if yuzey.tur == "duzlem" and len(dl) > 1:
        # delikler dış döngüye ters yönlü olmalı; değilse (yönü bozuk dosya) en büyük döngüden diğerleri düşülür
        yedek = romberg(y1, y2, y3)
        if abs(alan - yedek) > 1e-6 * max(1.0, alan):
            alan = yedek
    return alan, [[donus(q) for q in d] for d in dl]


def _spline_tam_mi(b: Bs3Yuzey, donguler: List[List[V3]], tol: float):
    """Spline yüz bütün parametre alanını kaplıyor mu: döngü noktaları alanın kenar eğrilerinde mi, kenar eğrileri
    (dikiş ve tekil uçlar hariç) döngülerle örtülüyor mu."""
    m = 200
    kenarlar = []
    for v in (b.v0, b.v1):
        kenarlar.append([b.nokta(b.u0 + (b.u1 - b.u0) * i / m, v) for i in range(m + 1)])
    for u in (b.u0, b.u1):
        kenarlar.append([b.nokta(u, b.v0 + (b.v1 - b.v0) * i / m) for i in range(m + 1)])
    olcu = max(_boy(_cik(q, kenarlar[0][0])) for e in kenarlar for q in e) or 1.0
    esik = max(tol * 20, olcu * 2e-4)
    kenar_parca = [(e[i], e[i + 1]) for e in kenarlar for i in range(m)]
    dongu_parca = [(d[i], d[(i + 1) % len(d)]) for d in donguler for i in range(len(d))]

    def uzak(q, parcalar):
        """q'nun çoklu çizgiye (doğru parçalarına) en kısa uzaklığı."""
        en = float("inf")
        for a, b in parcalar:
            ab = _cik(b, a)
            l2 = _ic(ab, ab)
            t = 0.0 if l2 == 0.0 else max(0.0, min(1.0, _ic(_cik(q, a), ab) / l2))
            en = min(en, _boy(_cik(q, _top(a, _kat(ab, t)))))
        return en

    for d in donguler:
        for q in d[::max(1, len(d) // 60)]:
            if uzak(q, kenar_parca) > esik:
                raise AcisHatasi("kırpılmış spline yüz desteklenmez")
    for e in kenarlar:
        uzunluk = sum(_boy(_cik(e[i + 1], e[i])) for i in range(m))
        if uzunluk <= esik:  # tekil (sivri) uç
            continue
        if all(uzak(q, dongu_parca) <= esik for q in e[::10]):
            continue
        # döngülerle örtülmeyen kenar yalnız periyodik dikişse (u0 ile u1 aynı eğri) kabul
        esi = kenarlar[3] if e is kenarlar[2] else kenarlar[2] if e is kenarlar[3] else None
        if esi is not None and all(_boy(_cik(x, y)) <= esik for x, y in zip(e, esi)):
            continue
        raise AcisHatasi("kırpılmış spline yüz desteklenmez")


def _yuzey(k: Kayit, onbellek: dict) -> Yuzey:
    a = ("yuzey", id(k))
    if a not in onbellek:
        onbellek[a] = Yuzey(k)
    return onbellek[a]


# ---------------------------------------------------------------- gövde

class Govde:
    def __init__(self):
        self.alan = 0.0                     # mm² (ölçekli)
        self.donguler: List[List[V3]] = []  # önizleme
        self.hata = ""
        self.yuz_sayisi = 0
        self.kapali = True
        self.tani: List[str] = []           # hesaplanamayan yüzlerin ham yüzey verisi (hata raporu için)


def _donusum(tr: Optional[Kayit]):
    """ACIS transform: 3 × 3 dönme satırları, öteleme, ölçek. Nokta → dünya (satır vektörü düzeni)."""
    if tr is None:
        return (lambda q: q), 1.0
    s = tr.sayilar()
    if len(s) < 12:
        return (lambda q: q), 1.0
    m = s[0:9]
    t = s[9:12]
    olcek = s[12] if len(s) > 12 else 1.0

    def donus(q):
        x, y, z = q
        return (x * m[0] + y * m[3] + z * m[6] + t[0], x * m[1] + y * m[4] + z * m[7] + t[1],
                x * m[2] + y * m[5] + z * m[8] + t[2])
    # dönme matrisinin satır uzunluğu ölçeği taşır (ACIS ölçeği ayrıca da yazar)
    satir = math.sqrt(m[0] ** 2 + m[1] ** 2 + m[2] ** 2)
    return donus, (satir if abs(satir - 1.0) > 1e-9 else olcek)


def govdeler(e) -> List[Govde]:
    """DXF ACIS varlığındaki her parça (lump) bir gövde; alan mm² değil çizim biriminin karesi."""
    kayitlar = kayitlari_oku(e)
    out: List[Govde] = []
    for body in (k for k in kayitlar if k.ad == "body"):
        bp = body.isaretciler()
        # body: [desen, lump, wire, transform]
        donus, olcek = _donusum(bp[3] if len(bp) > 3 else None)
        lump = bp[1] if len(bp) > 1 else None
        while lump is not None:
            g = Govde()
            onbellek: dict = {}
            turler: Dict[str, int] = {}
            try:
                lp = lump.isaretciler()
                # lump: [desen, sonraki lump, kabuk, gövde]
                shell = lp[2]
                yuzler = []
                while shell is not None:
                    sp = shell.isaretciler()
                    # shell: [desen, sonraki kabuk, alt kabuk, yüz, tel, lump]
                    face = sp[3]
                    while face is not None:
                        yuzler.append(face)
                        face = face.isaretciler()[1]
                    shell = sp[1]
                boyut = _boyut(yuzler)
                tol = max(1e-6, boyut * 1e-6) * 50
                for face in yuzler:
                    g.yuz_sayisi += 1
                    yz = face.isaretciler()[5]
                    ad = yz.ad if yz is not None else "?"
                    try:
                        a, d = yuz_alani(face, donus, tol, onbellek)
                        g.alan += a
                        g.donguler.extend(d)
                    except AcisHatasi as h:
                        turler[f"{ad}: {h}"] = turler.get(f"{ad}: {h}", 0) + 1
                        if len(g.tani) < 3 and yz is not None:
                            g.tani.append(f"{ad}: {h}\n{_ham_metin(yz)}")
                g.kapali = _kapali_mi(yuzler)
            except (AcisHatasi, IndexError, ValueError, TypeError, AttributeError) as h:
                g.hata = f"ACIS verisi okunamadı ({h})"
            if turler and not g.hata:
                ozet = "; ".join(f"{n} yüz — {t}" for t, n in turler.items())
                g.hata = f"{g.yuz_sayisi} yüzden {sum(turler.values())} tanesi hesaplanamadı ({ozet})"
            g.alan *= olcek * olcek
            out.append(g)
            lump = lump.isaretciler()[1] if lump.isaretciler() else None
    if not out:
        g = Govde()
        g.hata = "ACIS verisinde katı gövde yok"
        out.append(g)
    return out


def _ham_metin(k: Kayit, sinir: int = 6000) -> str:
    """Kaydın öğeleri metin olarak (işaretçiler '$'), hata raporu için."""
    parca = []
    for x in k.oge:
        parca.append("$" if isinstance(x, Kayit) else "$-1" if x is None else
                     f"{x:.10g}" if isinstance(x, float) else str(x))
    m = f"{k.ad} " + " ".join(parca)
    return m if len(m) <= sinir else m[:sinir] + " …"


def _boyut(yuzler: List[Kayit]) -> float:
    """Gövdenin kaba büyüklüğü (köşe noktalarının kutusu), tolerans için."""
    pts = []
    for f in yuzler[:200]:
        loop = f.isaretciler()[2]
        say = 0
        while loop is not None and say < 50:
            c = loop.isaretciler()[2]
            if c is not None:
                kenar = c.isaretciler()[4]
                if kenar is not None:
                    try:
                        pts.append(_kose(kenar.isaretciler()[1]))
                    except AcisHatasi:
                        pass
            loop = loop.isaretciler()[1]
            say += 1
    if not pts:
        return 1.0
    return max(max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3)) or 1.0


def _kapali_mi(yuzler: List[Kayit]) -> bool:
    """Her coedge'in bir eşi (partner) varsa kabuk kapalıdır."""
    for f in yuzler:
        loop = f.isaretciler()[2]
        while loop is not None:
            ilk = loop.isaretciler()[2]
            c, n = ilk, 0
            while c is not None:
                if c.isaretciler()[3] is None:
                    return False
                c = c.isaretciler()[1]
                n += 1
                if c is ilk or n > 100000:
                    break
            loop = loop.isaretciler()[1]
    return True
