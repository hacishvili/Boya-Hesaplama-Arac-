# -*- coding: utf-8 -*-
"""Toz boya hesabı: boyanacak alan → toz sarfiyatı → maliyet.

    toz (kg) = alan (m²) · kalınlık (µm) · yoğunluk (g/cm³) / 1000 / transfer verimi
    teorik kaplama (m²/kg) = 1000 / (yoğunluk · kalınlık)

Kalemin alanı kaynağından gelir (kaynak_alani): 2D açınım, 3D gövde, kalıp ya da elle girilen alan.
Kaynakta hesaba yetecek sayılar saklanır (çizim dosyası olmadan da proje açılır ve yeniden hesaplanır)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import kaliplar


@dataclass
class Toz:
    ad: str
    yogunluk: float = 1.5        # g/cm³ (teknik föy)
    fiyat: float = 0.0           # TL/kg
    kalinlik_um: float = 70.0    # varsayılan film kalınlığı

    @property
    def teorik_kaplama(self) -> float:
        """m²/kg (verim hariç)."""
        return teorik_kaplama(self.yogunluk, self.kalinlik_um)


@dataclass
class Ayarlar:
    verim: float = 0.65          # transfer verimi (geri kazanımlı hatta 0,90–0,95)
    proses_tl_m2: float = 0.0    # ön işlem + fırın + işçilik, m² başına (0: yalnız toz maliyeti)
    para: str = "TL"
    oda_yolu: str = ""           # ODA File Converter (DWG açmak için); boş: kendiliğinden aranır
    tozlar: List[Toz] = field(default_factory=lambda: [
        Toz("Polyester (dış mekân)", 1.5, 0.0, 70.0),
        Toz("Epoksi-polyester (iç mekân)", 1.45, 0.0, 60.0),
        Toz("Epoksi", 1.5, 0.0, 70.0),
        Toz("Metalik / efektli", 1.4, 0.0, 70.0),
    ])

    def toz(self, ad: str) -> Toz:
        for t in self.tozlar:
            if t.ad == ad:
                return t
        return self.tozlar[0] if self.tozlar else Toz("Toz")

    def sozluk(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def sozlukten(cls, d: Dict[str, Any]) -> "Ayarlar":
        a = cls()
        a.verim = float(d.get("verim", a.verim))
        a.proses_tl_m2 = float(d.get("proses_tl_m2", a.proses_tl_m2))
        a.para = str(d.get("para", a.para))
        a.oda_yolu = str(d.get("oda_yolu", ""))
        if d.get("tozlar"):
            a.tozlar = [Toz(str(t["ad"]), float(t.get("yogunluk", 1.5)), float(t.get("fiyat", 0.0)),
                            float(t.get("kalinlik_um", 70.0))) for t in d["tozlar"]]
        return a


def teorik_kaplama(yogunluk: float, kalinlik_um: float) -> float:
    return 1000.0 / (yogunluk * kalinlik_um) if yogunluk > 0 and kalinlik_um > 0 else 0.0


def toz_kg(alan_m2: float, kalinlik_um: float, yogunluk: float, verim: float) -> float:
    if verim <= 0:
        raise ValueError("Transfer verimi sıfırdan büyük olmalı.")
    return alan_m2 * kalinlik_um * yogunluk / 1000.0 / verim


# ---------------------------------------------------------------- kaynak → alan

def kaynak_alani(k: Dict[str, Any]) -> float:
    """Bir adedin boyanacak alanı (mm², maske düşülmeden)."""
    tur = k.get("tur")
    if tur == "2d":
        yuz = float(k["yuz_alani"]) * int(k.get("yuz_sayisi", 2))
        kenar = float(k["cevre"]) * float(k.get("kalinlik", 0.0)) if k.get("kenar", True) else 0.0
        return yuz + kenar
    if tur == "3d":
        return float(k["alan"]) * float(k.get("katsayi", 1.0))
    if tur == "kalip":
        return kaliplar.alan(k["kalip"], k.get("deger", {}))
    if tur == "elle":
        return float(k.get("alan_m2", 0.0)) * 1e6
    raise ValueError(f"bilinmeyen kaynak türü: {tur}")


def kaynak_aciklamasi(k: Dict[str, Any]) -> str:
    tur = k.get("tur")
    if tur == "2d":
        w, h = k.get("olcu", (0, 0))
        yuz = "iki yüz" if int(k.get("yuz_sayisi", 2)) == 2 else "tek yüz"
        kenar = f", kenarlar (t = {sayi(k.get('kalinlik', 0), 2)} mm)" if k.get("kenar", True) else ", kenarsız"
        delik = f", {k.get('delik', 0)} delik" if k.get("delik") else ""
        return f"2D açınım {sayi(w, 1)} × {sayi(h, 1)} mm{delik}; {yuz}{kenar}"
    if tur == "3d":
        s = f"3D gövde ({k.get('varlik', '')})"
        if not k.get("kapali", True):
            s += ", açık yüzey" + (" × 2 yüz" if float(k.get("katsayi", 1)) == 2 else "")
        return s
    if tur == "kalip":
        return kaliplar.aciklama(k["kalip"], k.get("deger", {}))
    if tur == "elle":
        return "elle girilen alan"
    return ""


@dataclass
class Kalem:
    ad: str
    kaynak: Dict[str, Any]
    adet: int = 1
    maske_cm2: float = 0.0       # boyanmayan (maskelenen) alan, adet başına
    toz: str = ""
    kalinlik_um: Optional[float] = None   # None: tozun varsayılanı
    dosya: str = ""              # çizim dosyası (önizleme için; hesap kaynakta)

    def sozluk(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def sozlukten(cls, d: Dict[str, Any]) -> "Kalem":
        return cls(str(d["ad"]), dict(d["kaynak"]), int(d.get("adet", 1)), float(d.get("maske_cm2", 0.0)),
                   str(d.get("toz", "")), None if d.get("kalinlik_um") is None else float(d["kalinlik_um"]),
                   str(d.get("dosya", "")))


@dataclass
class Sonuc:
    alan_m2: float               # adet başına, maske düşülmüş
    toplam_m2: float
    kalinlik_um: float
    toz_g_adet: float
    toz_kg: float
    toz_tl: float
    proses_tl: float

    @property
    def tutar(self) -> float:
        return self.toz_tl + self.proses_tl


def kalem_sonucu(k: Kalem, a: Ayarlar) -> Sonuc:
    toz = a.toz(k.toz)
    t = toz.kalinlik_um if k.kalinlik_um is None else k.kalinlik_um
    alan = max(0.0, kaynak_alani(k.kaynak) / 1e6 - k.maske_cm2 / 1e4)
    toplam = alan * k.adet
    kg = toz_kg(toplam, t, toz.yogunluk, a.verim)
    return Sonuc(alan, toplam, t, 1000.0 * toz_kg(alan, t, toz.yogunluk, a.verim), kg, kg * toz.fiyat,
                 toplam * a.proses_tl_m2)


@dataclass
class Ozet:
    toplam_m2: float = 0.0
    toplam_adet: int = 0
    toz_kg: float = 0.0
    toz_tl: float = 0.0
    proses_tl: float = 0.0
    toz_bazinda: Dict[str, float] = field(default_factory=dict)   # toz adı → kg (satın alma için)

    @property
    def tutar(self) -> float:
        return self.toz_tl + self.proses_tl


def ozet(kalemler: List[Kalem], a: Ayarlar) -> Ozet:
    o = Ozet()
    for k in kalemler:
        s = kalem_sonucu(k, a)
        o.toplam_m2 += s.toplam_m2
        o.toplam_adet += k.adet
        o.toz_kg += s.toz_kg
        o.toz_tl += s.toz_tl
        o.proses_tl += s.proses_tl
        ad = a.toz(k.toz).ad
        o.toz_bazinda[ad] = o.toz_bazinda.get(ad, 0.0) + s.toz_kg
    return o


def sayi(x: float, basamak: int = 2) -> str:
    """Türkçe yazım: 1.234,56"""
    s = f"{float(x):,.{basamak}f}"
    return s.replace(",", "\u0001").replace(".", ",").replace("\u0001", ".")
