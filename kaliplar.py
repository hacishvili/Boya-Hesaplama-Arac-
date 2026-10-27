# -*- coding: utf-8 -*-
"""Çizimden alan çıkmayan parçalar için kalıplar: boru, kutu profil, konik ayak, dolu çubuk, lama, sac.

Uç durumu (boru ve profiller):
  açık    — uç halkaları boyanır; toz içeriye her uçtan "iç boya derinliği" kadar girer (varsayılan bir çap)
  kapaklı — uçlara kaynaklı kapak: kapakların dış yüzü boyanır, iç boyanmaz
  tapalı  — plastik tapa: uç ve iç boyanmaz
Bütün ölçüler mm, dönüş mm²."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

UC_DURUMLARI = ("açık", "kapaklı", "tapalı")


@dataclass
class Olcu:
    anahtar: str
    etiket: str
    varsayilan: float | str
    birim: str = "mm"
    secenekler: Optional[Sequence[str]] = None   # dolu: seçim kutusu
    ipucu: str = ""


@dataclass
class Kalip:
    ad: str
    olculer: List[Olcu]
    alan: Callable[[Dict], float]
    ozet: Callable[[Dict], str]
    not_: str = ""


def _d(d: Dict, k: str, kalip: "Kalip") -> float | str:
    for o in kalip.olculer:
        if o.anahtar == k:
            v = d.get(k, o.varsayilan)
            return v if o.secenekler else float(v)
    raise KeyError(k)


def _uc(uc: str, halka: float, kapak: float, ic_cevre: float, derinlik: float, boy: float) -> float:
    """Uçların ve için katkısı. halka: bir ucun kesit alanı, kapak: bir uç kapağının dış yüzü."""
    if uc == "açık":
        return 2.0 * halka + ic_cevre * min(2.0 * max(derinlik, 0.0), boy)
    if uc == "kapaklı":
        return 2.0 * kapak
    return 0.0


def _yuvarlak_boru(d: Dict) -> float:
    k = KALIPLAR["Yuvarlak boru"]
    D, t, L = _d(d, "D", k), _d(d, "t", k), _d(d, "L", k)
    _dogrula(D > 0 and L > 0 and 0 < t < D / 2, "Boru: Ø > 0, boy > 0, 0 < et < Ø/2 olmalı.")
    di = D - 2 * t
    h = _d(d, "h", k)
    return math.pi * D * L + _uc(_d(d, "uc", k), math.pi / 4 * (D * D - di * di), math.pi / 4 * D * D,
                                 math.pi * di, h, L)


def _profil_cevre_alan(a: float, b: float, r: float):
    r = max(0.0, min(r, a / 2, b / 2))
    return 2 * (a + b) - (8 - 2 * math.pi) * r, a * b - (4 - math.pi) * r * r


def _kutu_profil(d: Dict) -> float:
    k = KALIPLAR["Kutu profil"]
    a, b, t, L, r = (_d(d, x, k) for x in ("a", "b", "t", "L", "r"))
    _dogrula(a > 0 and b > 0 and L > 0 and 0 < t < min(a, b) / 2, "Profil: kenarlar > 0, 0 < et < kısa kenar/2.")
    p_dis, s_dis = _profil_cevre_alan(a, b, r)
    p_ic, s_ic = _profil_cevre_alan(a - 2 * t, b - 2 * t, max(r - t, 0.0))
    return p_dis * L + _uc(_d(d, "uc", k), s_dis - s_ic, s_dis, p_ic, _d(d, "h", k), L)


def _konik_boru(d: Dict) -> float:
    k = KALIPLAR["Konik ayak (boru)"]
    D1, D2, t, L = (_d(d, x, k) for x in ("D1", "D2", "t", "L"))
    _dogrula(D1 > 0 and D2 > 0 and L > 0 and 0 < t < min(D1, D2) / 2, "Konik: çaplar > 0, 0 < et < küçük Ø/2.")
    R1, R2 = D1 / 2, D2 / 2
    yan = math.pi * (R1 + R2) * math.hypot(L, R1 - R2)
    uc, h = _d(d, "uc", k), max(_d(d, "h", k), 0.0)
    halka = lambda D: math.pi / 4 * (D * D - (D - 2 * t) ** 2)
    if uc == "açık":
        h = min(h, L / 2)
        ek = halka(D1) + halka(D2) + math.pi * ((D1 - 2 * t) + (D2 - 2 * t)) * h
    elif uc == "kapaklı":
        ek = math.pi / 4 * (D1 * D1 + D2 * D2)
    else:
        ek = 0.0
    return yan + ek


def _dolu_yuvarlak(d: Dict) -> float:
    k = KALIPLAR["Dolu yuvarlak çubuk"]
    D, L = _d(d, "D", k), _d(d, "L", k)
    _dogrula(D > 0 and L > 0, "Çubuk: Ø ve boy > 0.")
    return math.pi * D * L + (2 * math.pi / 4 * D * D if _d(d, "uclar", k) == "boyanır" else 0.0)


def _lama(d: Dict) -> float:
    k = KALIPLAR["Lama / dolu kare"]
    a, b, L = _d(d, "a", k), _d(d, "b", k), _d(d, "L", k)
    _dogrula(a > 0 and b > 0 and L > 0, "Lama: ölçüler > 0.")
    return 2 * (a + b) * L + (2 * a * b if _d(d, "uclar", k) == "boyanır" else 0.0)


def _sac(d: Dict) -> float:
    k = KALIPLAR["Sac levha"]
    a, b, t = _d(d, "a", k), _d(d, "b", k), _d(d, "t", k)
    _dogrula(a > 0 and b > 0 and t >= 0, "Sac: ölçüler > 0.")
    yuz = 2 if _d(d, "yuz", k) == "iki yüz" else 1
    return yuz * a * b + 2 * (a + b) * t


def _dogrula(kosul: bool, mesaj: str):
    if not kosul:
        raise ValueError(mesaj)


_UC = Olcu("uc", "Uçlar", "açık", "", UC_DURUMLARI,
           "açık: uç halkaları ve içten derinlik kadar; kapaklı: kapak dış yüzleri; tapalı: boyanmaz")

KALIPLAR: Dict[str, Kalip] = {}


def _ekle(k: Kalip):
    KALIPLAR[k.ad] = k


_ekle(Kalip("Yuvarlak boru", [
    Olcu("D", "Dış çap Ø", 25.0), Olcu("t", "Et kalınlığı", 1.5), Olcu("L", "Boy", 400.0), _UC,
    Olcu("h", "İç boya derinliği (her uç)", 25.0, "mm", None, "açık uçta tozun içeri girdiği derinlik; yaklaşık bir çap"),
], _yuvarlak_boru, lambda d: f"Boru Ø{_s(d, 'D')} × {_s(d, 't')} × {_s(d, 'L')} mm, uçlar {d.get('uc', 'açık')}"))
_ekle(Kalip("Kutu profil", [
    Olcu("a", "Kenar a", 40.0), Olcu("b", "Kenar b", 20.0), Olcu("t", "Et kalınlığı", 1.5),
    Olcu("L", "Boy", 400.0), Olcu("r", "Dış köşe yarıçapı", 3.0), _UC,
    Olcu("h", "İç boya derinliği (her uç)", 40.0, "mm", None, "açık uçta tozun içeri girdiği derinlik"),
], _kutu_profil, lambda d: f"Profil {_s(d, 'a')} × {_s(d, 'b')} × {_s(d, 't')}, boy {_s(d, 'L')} mm, "
                           f"uçlar {d.get('uc', 'açık')}"))
_ekle(Kalip("Konik ayak (boru)", [
    Olcu("D1", "Üst çap Ø1", 40.0), Olcu("D2", "Alt çap Ø2", 25.0), Olcu("t", "Et kalınlığı", 1.5),
    Olcu("L", "Boy", 150.0), _UC, Olcu("h", "İç boya derinliği (her uç)", 30.0),
], _konik_boru, lambda d: f"Konik ayak Ø{_s(d, 'D1')} → Ø{_s(d, 'D2')}, boy {_s(d, 'L')} mm, "
                          f"uçlar {d.get('uc', 'açık')}"))
_ekle(Kalip("Dolu yuvarlak çubuk", [
    Olcu("D", "Çap Ø", 12.0), Olcu("L", "Boy", 300.0),
    Olcu("uclar", "Uç yüzleri", "boyanır", "", ("boyanır", "boyanmaz")),
], _dolu_yuvarlak, lambda d: f"Çubuk Ø{_s(d, 'D')} × {_s(d, 'L')} mm"))
_ekle(Kalip("Lama / dolu kare", [
    Olcu("a", "Genişlik a", 30.0), Olcu("b", "Kalınlık b", 5.0), Olcu("L", "Boy", 300.0),
    Olcu("uclar", "Uç yüzleri", "boyanır", "", ("boyanır", "boyanmaz")),
], _lama, lambda d: f"Lama {_s(d, 'a')} × {_s(d, 'b')} × {_s(d, 'L')} mm"))
_ekle(Kalip("Sac levha", [
    Olcu("a", "En", 300.0), Olcu("b", "Boy", 200.0), Olcu("t", "Kalınlık", 1.5),
    Olcu("yuz", "Boyanan yüz", "iki yüz", "", ("iki yüz", "tek yüz")),
], _sac, lambda d: f"Sac {_s(d, 'a')} × {_s(d, 'b')} × {_s(d, 't')} mm, {d.get('yuz', 'iki yüz')}"))


def _s(d: Dict, k: str) -> str:
    v = d.get(k)
    if v is None:
        return "?"
    v = float(v)
    return (f"{v:.0f}" if v == int(v) else f"{v:g}").replace(".", ",")


def varsayilanlar(ad: str) -> Dict:
    return {o.anahtar: o.varsayilan for o in KALIPLAR[ad].olculer}


def alan(ad: str, deger: Dict) -> float:
    if ad not in KALIPLAR:
        raise ValueError(f"bilinmeyen kalıp: {ad}")
    return KALIPLAR[ad].alan({**varsayilanlar(ad), **deger})


def aciklama(ad: str, deger: Dict) -> str:
    if ad not in KALIPLAR:
        return ad
    return KALIPLAR[ad].ozet({**varsayilanlar(ad), **deger})
