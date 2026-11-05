# -*- coding: utf-8 -*-
"""Toz boya hesabı: boyanacak alan → toz sarfiyatı → maliyet. İki yöntem (Ayarlar.yontem):

  pratik (varsayılan)  toz (kg) = alan (m²) / sarfiyat (m²/kg)       atölyenin ölçtüğü oran: 1 kg toz ile 6 m²;
                                                                      fire ve kayıplar oranın içinde
  teorik               toz (kg) = alan (m²) · kalınlık (µm) · yoğunluk (g/cm³) / 1000 / transfer verimi
                       teorik kaplama (m²/kg) = 1000 / (yoğunluk · kalınlık)

Kalemin alanı kaynağından gelir (kaynak_alani): 2D açınım, 3D gövde, kalıp ya da elle girilen alan. Maske (cm²
ve %) düşülür; kat sayısı tozu ve prosesi çarpar (astar + son kat: 2). Ağırlık = metal hacmi × yoğunluk
(kaynak_hacmi; bilinmiyorsa kalemde elle girilir).
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
    kalinlik_um: float = 70.0    # varsayılan film kalınlığı (teorik yöntem)
    sarfiyat_m2_kg: float = 6.0  # pratik yöntem: 1 kg tozla boyanan alan (kayıplar dahil)

    @property
    def teorik_kaplama(self) -> float:
        """m²/kg (verim hariç)."""
        return teorik_kaplama(self.yogunluk, self.kalinlik_um)


@dataclass
class Ayarlar:
    yontem: str = "pratik"       # "pratik": alan / sarfiyat;  "teorik": kalınlık · yoğunluk / verim
    verim: float = 0.65          # transfer verimi (teorik yöntem; geri kazanımlı hatta 0,90–0,95)
    proses_tl_m2: float = 0.0    # ön işlem + fırın + işçilik, m² başına (0: yalnız toz maliyeti)
    para: str = "TL"
    oda_yolu: str = ""           # ODA File Converter (DWG açmak için); boş: kendiliğinden aranır
    guncelleme: bool = True      # açılışta GitHub'da yeni sürüm denetlenir
    metal_yogunluk: float = 7.85  # g/cm³ (çelik; alüminyum 2,70, paslanmaz 7,93), ağırlık için
    tozlar: List[Toz] = field(default_factory=lambda: [
        Toz("Polyester (dış mekân)", 1.5, 0.0, 70.0, 6.0),
        Toz("Epoksi-polyester (iç mekân)", 1.45, 0.0, 60.0, 6.0),
        Toz("Epoksi", 1.5, 0.0, 70.0, 6.0),
        Toz("Metalik / efektli", 1.4, 0.0, 70.0, 6.0),
    ])

    @property
    def pratik(self) -> bool:
        return self.yontem != "teorik"

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
        a.yontem = "teorik" if d.get("yontem") == "teorik" else "pratik"
        a.verim = float(d.get("verim", a.verim))
        a.proses_tl_m2 = float(d.get("proses_tl_m2", a.proses_tl_m2))
        a.para = str(d.get("para", a.para))
        a.oda_yolu = str(d.get("oda_yolu", ""))
        a.guncelleme = bool(d.get("guncelleme", True))
        a.metal_yogunluk = float(d.get("metal_yogunluk", 7.85))
        if d.get("tozlar"):
            a.tozlar = [Toz(str(t["ad"]), float(t.get("yogunluk", 1.5)), float(t.get("fiyat", 0.0)),
                            float(t.get("kalinlik_um", 70.0)), float(t.get("sarfiyat_m2_kg", 6.0)))
                        for t in d["tozlar"]]
        return a


def teorik_kaplama(yogunluk: float, kalinlik_um: float) -> float:
    return 1000.0 / (yogunluk * kalinlik_um) if yogunluk > 0 and kalinlik_um > 0 else 0.0


def pratik_kg(alan_m2: float, sarfiyat_m2_kg: float) -> float:
    if sarfiyat_m2_kg <= 0:
        raise ValueError("Toz sarfiyatı (m²/kg) sıfırdan büyük olmalı.")
    return alan_m2 / sarfiyat_m2_kg


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
        # delik içi boyanmaz: silindir duvarları düşülür (havşa ağzı boyanır)
        duvar = sum(float(d.get("duvar", 0.0)) for d in k.get("delikler", [])) if k.get("delik_ici_boyanmaz") else 0.0
        if k.get("profil"):
            import profil
            return max(0.0, profil.profil_alani(k["profil"], k.get("ic_boya", "uçlardan"),
                                                float(k.get("ic_derinlik", 0.0)), bool(k.get("uc_boya", True))) - duvar)
        return max(0.0, float(k["alan"]) * float(k.get("katsayi", 1.0)) - duvar)
    if tur == "kalip":
        return kaliplar.alan(k["kalip"], k.get("deger", {}))
    if tur == "elle":
        return float(k.get("alan_m2", 0.0)) * 1e6
    raise ValueError(f"bilinmeyen kaynak türü: {tur}")


def kaynak_hacmi(k: Dict[str, Any]) -> Optional[float]:
    """Bir adedin metal hacmi (mm³); kaynaktan çıkmıyorsa None (dolu ACIS gövdesi, elle alan)."""
    tur = k.get("tur")
    try:
        if tur == "2d":
            t = float(k.get("kalinlik", 0.0))
            return float(k["yuz_alani"]) * t if t > 0 else None
        if tur == "3d":
            if k.get("sac"):
                return float(k["sac"]["kalinlik"]) * float(k["sac"]["yuz"]) / 2.0
            if k.get("profil") and float(k["profil"].get("kesit_alani", 0.0)) > 0:
                return float(k["profil"]["kesit_alani"]) * float(k["profil"]["boy"])
            return float(k["hacim"]) if k.get("hacim") else None
        if tur == "kalip":
            return kaliplar.hacim(k["kalip"], k.get("deger", {}))
    except (ValueError, KeyError, TypeError):
        return None
    return None


def kaynak_aciklamasi(k: Dict[str, Any]) -> str:
    s = _kaynak_aciklamasi(k)
    if k.get("tur") == "3d" and k.get("delikler"):
        import profil
        s += "; " + profil.delik_sayimi(k["delikler"])
        if k.get("delik_ici_boyanmaz"):
            s += ", delik içi boyanmaz"
    return s


def _kaynak_aciklamasi(k: Dict[str, Any]) -> str:
    tur = k.get("tur")
    if tur == "2d":
        w, h = k.get("olcu", (0, 0))
        yuz = "iki yüz" if int(k.get("yuz_sayisi", 2)) == 2 else "tek yüz"  # eski projelerde tek yüz olabilir
        kenar = f" + kesim kenarları (t = {sayi(k.get('kalinlik', 0), 2)} mm)" if k.get("kenar", True) else ", kenarsız"
        delik = f", {k.get('delik', 0)} delik" if k.get("delik") else ""
        return f"2D açınım {sayi(w, 1)} × {sayi(h, 1)} mm{delik}; {yuz}{kenar}"
    if tur == "3d" and k.get("profil"):
        p = k["profil"]
        ic = k.get("ic_boya", "uçlardan")
        s = f"3D profil {sayi(p['kesit'][0], 1)} × {sayi(p['kesit'][1], 1)}, boy {sayi(p['boy'], 0)} mm"
        if p.get("ic"):
            s += ("; iç yüzey " + (f"uçlardan {sayi(float(k.get('ic_derinlik', 0)), 0)} mm" if ic == "uçlardan"
                                   else ic))
        if not k.get("uc_boya", True):
            s += "; uç kesitleri boyanmaz"
        return s
    if tur == "3d" and k.get("sac"):
        return f"3D sac t = {sayi(k['sac']['kalinlik'], 2)} mm; iki yüz + kesim kenarları"
    if tur == "3d":
        s = f"3D gövde ({k.get('varlik', '')})"
        if not k.get("kapali", True):
            s += ", açık yüzey" + (" × 2 yüz" if float(k.get("katsayi", 1)) == 2 else "")
        return s
    if tur == "kalip":
        return kaliplar.aciklama(k["kalip"], k.get("deger", {}))
    if tur == "elle":
        pdf = k.get("pdf")
        return "elle girilen alan" + (f" (PDF taslağı: {pdf})" if pdf else "")
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
    kat: int = 1                 # kat sayısı (astar + son kat: 2); tozu ve prosesi çarpar
    maske_yuzde: float = 0.0     # boyanmayan alan, çizim alanının yüzdesi
    agirlik_kg: Optional[float] = None    # adet başına, elle; None: kaynaktan hesaplanır

    def sozluk(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def sozlukten(cls, d: Dict[str, Any]) -> "Kalem":
        return cls(str(d["ad"]), dict(d["kaynak"]), int(d.get("adet", 1)), float(d.get("maske_cm2", 0.0)),
                   str(d.get("toz", "")), None if d.get("kalinlik_um") is None else float(d["kalinlik_um"]),
                   str(d.get("dosya", "")), int(d.get("kat", 1)), float(d.get("maske_yuzde", 0.0)),
                   None if d.get("agirlik_kg") is None else float(d["agirlik_kg"]))


@dataclass
class Sonuc:
    alan_m2: float               # adet başına, maske düşülmüş
    toplam_m2: float
    kalinlik_um: Optional[float]  # pratik yöntemde None (hesaba girmez)
    toz_g_adet: float
    toz_kg: float
    toz_tl: float
    proses_tl: float
    kat: int = 1
    agirlik_kg_adet: Optional[float] = None   # None: bilinmiyor
    agirlik_kg: Optional[float] = None        # toplam (adet ile)
    agirlik_elle: bool = False

    @property
    def tutar(self) -> float:
        return self.toz_tl + self.proses_tl


def agirlik_kg(k: "Kalem", a: Ayarlar) -> Optional[float]:
    """Adet başına ağırlık (kg): elle girilen, yoksa metal hacmi × yoğunluk."""
    if k.agirlik_kg is not None:
        return k.agirlik_kg
    v = kaynak_hacmi(k.kaynak)
    return None if v is None else v * a.metal_yogunluk * 1e-6  # mm³ · g/cm³ = 1e-3 g


def kalem_sonucu(k: Kalem, a: Ayarlar) -> Sonuc:
    toz = a.toz(k.toz)
    if k.kat < 1:
        raise ValueError("Kat sayısı en az 1 olmalı.")
    if not 0.0 <= k.maske_yuzde <= 100.0:
        raise ValueError("Maske yüzdesi 0 ile 100 arasında olmalı.")
    alan = max(0.0, kaynak_alani(k.kaynak) / 1e6 * (1.0 - k.maske_yuzde / 100.0) - k.maske_cm2 / 1e4)
    toplam = alan * k.adet
    if a.pratik:
        t = None
        kg_adet = pratik_kg(alan, toz.sarfiyat_m2_kg)
    else:
        t = toz.kalinlik_um if k.kalinlik_um is None else k.kalinlik_um
        kg_adet = toz_kg(alan, t, toz.yogunluk, a.verim)
    kg_adet *= k.kat
    kg = kg_adet * k.adet
    ag = agirlik_kg(k, a)
    return Sonuc(alan, toplam, t, 1000.0 * kg_adet, kg, kg * toz.fiyat, toplam * a.proses_tl_m2 * k.kat, k.kat,
                 ag, None if ag is None else ag * k.adet, k.agirlik_kg is not None)


@dataclass
class Ozet:
    toplam_m2: float = 0.0
    toplam_adet: int = 0
    toz_kg: float = 0.0
    toz_tl: float = 0.0
    proses_tl: float = 0.0
    toz_bazinda: Dict[str, float] = field(default_factory=dict)   # toz adı → kg (satın alma için)
    agirlik_kg: float = 0.0      # ağırlığı bilinen kalemlerin toplamı
    agirliksiz: int = 0          # ağırlığı bilinmeyen kalem sayısı

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
        if s.agirlik_kg is None:
            o.agirliksiz += 1
        else:
            o.agirlik_kg += s.agirlik_kg
        ad = a.toz(k.toz).ad
        o.toz_bazinda[ad] = o.toz_bazinda.get(ad, 0.0) + s.toz_kg
    return o


def yontem_ozeti(a: Ayarlar) -> str:
    """Raporlar ve toplam satırı için: hangi yöntemle, hangi oranla."""
    if a.pratik:
        oranlar = {t.sarfiyat_m2_kg for t in a.tozlar}
        if len(oranlar) == 1:
            return f"pratik sarfiyat: 1 kg = {sayi(next(iter(oranlar)), 1)} m²"
        return "pratik sarfiyat (toza göre m²/kg)"
    return f"teorik: kalınlık × yoğunluk, verim %{sayi(a.verim * 100, 0)}"


def sayi(x: float, basamak: int = 2) -> str:
    """Türkçe yazım: 1.234,56"""
    s = f"{float(x):,.{basamak}f}"
    return s.replace(",", "\u0001").replace(".", ",").replace("\u0001", ".")
