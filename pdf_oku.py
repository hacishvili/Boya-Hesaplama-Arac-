# -*- coding: utf-8 -*-
"""PDF teknik resimden yazı okuma: parça adı, ürün adı, renk, ölçüler, sac kalınlığı, adet ve notlar.

Yalnız PDF'in içindeki gerçek yazı okunur (CAD'den PDF'e yazdırılan çizimler); resim PDF'lerde (tarama, ekran
görüntüsü) yazı yoksa bunu bildirir. Çizgilerden kontur / alan okunmaz: sonuç taslak kalem içindir.

Antetteki "PARÇA ADI", "ÜRÜN ADI" gibi etiketlerin değeri aynı satırda sağındaki hücreden alınır (sayfa dönükse
görünen yöne göre). 'RENK: ...', 'K:6', 'P:ad' ve 'ADET: 4' gibi yazılar da okunur."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import dxf_oku

_TR = str.maketrans("ÇĞİIÖŞÜçğıöşü", "CGIIOSUcgiosu")
SATIR_TOLERANSI = 2.5   # etiket ile değerin aynı satırda sayılması (pt)


def _n(s: str) -> str:
    """Karşılaştırma için: Türkçe harfler sadeleştirilir, küçük harf, fazla boşluk atılır."""
    return " ".join(s.translate(_TR).lower().replace("i̇", "i").split())


@dataclass
class Parca:
    metin: str
    x: float        # görünen sayfada sağa (pt)
    y: float        # görünen sayfada aşağı (pt)


@dataclass
class PdfSonuc:
    ad: str = ""
    urun: str = ""
    renk: str = ""
    olculer: List[float] = field(default_factory=list)       # çizimdeki ölçü yazıları, büyükten küçüğe
    ad_olculeri: List[float] = field(default_factory=list)   # parça adında yazan AxBxC
    kalinlik: Optional[float] = None                         # mm; yalnız açıkça yazılmışsa (t=, K:, kalınlık)
    kalinlik_ipucu: List[Tuple[float, str]] = field(default_factory=list)  # yazıda geçen 'N mm' (emin değil)
    adet: Optional[int] = None
    notlar: List[str] = field(default_factory=list)
    uyarilar: List[str] = field(default_factory=list)
    sayfa: int = 1


def _gorunen(x: float, y: float, w: float, h: float, donus: int) -> Tuple[float, float]:
    """Sayfa içeriğindeki (x, y: yukarı) noktanın görünen sayfadaki (sağa, aşağı) konumu."""
    donus %= 360
    if donus == 90:
        return y, x
    if donus == 180:
        return w - x, y
    if donus == 270:
        return h - y, w - x
    return x, h - y


def parcalar(sayfa) -> List[Parca]:
    """Sayfadaki yazı parçaları (konumuyla). Birleşik yazılar (PDF'in bir seferde yazdığı dizge) tek parçadır."""
    out: List[Parca] = []
    w, h = float(sayfa.mediabox.width), float(sayfa.mediabox.height)
    donus = int(sayfa.rotation or 0)

    def ziyaretci(metin, cm, tm, fd, fs):
        if not metin.strip():
            return
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        gx, gy = _gorunen(x, y, w, h, donus)
        out.append(Parca(" ".join(metin.split()), gx, gy))

    sayfa.extract_text(visitor_text=ziyaretci)
    return out


ETIKETLER = {"parca adi": "ad", "urun adi": "urun"}
# anteti oluşturan diğer etiketler: not sayılmaz
ANTET = {"parca kodu", "urun kodu", "kontrol", "cizen", "tarih", "olcek", "onay", "imza", "resim no", "rev. no",
         "revizyon tarihi", "degisiklikler", "revizyon", "musteri", "proje", "malzeme", "sayfa"}
_SAYI = re.compile(r"^\d{1,5}(?:[.,]\d{1,2})?$")
_OLCU_AD = re.compile(r"(\d+(?:[.,]\d+)?)\s*[xX×]\s*(\d+(?:[.,]\d+)?)(?:\s*[xX×]\s*(\d+(?:[.,]\d+)?))?")
_RENK = re.compile(r"^(?:renk|rengi|color|colour|ral)\s*[:=]\s*(.+)$", re.I)
_ADET = re.compile(r"(?:^|\b)(?:adet|miktar|qty)\s*[:=]\s*(\d{1,6})\b|\b(\d{1,6})\s*(?:adet|ad\.?)\b", re.I)
_MM = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*mm\b", re.I)


def _sayi(s: str) -> float:
    return float(s.replace(",", "."))


def coz(par: List[Parca]) -> PdfSonuc:
    """Yazı parçalarından sonuç: etiket-değer eşleşmeleri, renk, ölçü, kalınlık, adet, notlar."""
    s = PdfSonuc()
    kullanilan = set()
    etiket_idx = {}
    # PDF aynı satırdaki "ETİKET değer" yazısını tek parça verdiyse etiket ile değeri ayır (değer sağ tarafa konur)
    ayrik: List[Parca] = []
    for p in par:
        n = _n(p.metin)
        ek = next((e for e in sorted(ETIKETLER, key=len, reverse=True) if n.startswith(e + " ") or n.startswith(e + ":")),
                  None)
        if ek is not None:
            kalan = p.metin[len(ek):].lstrip(" :")
            if kalan:
                ayrik += [Parca(p.metin[:len(ek)], p.x, p.y), Parca(kalan, p.x + 1.0, p.y)]
                continue
        ayrik.append(p)
    par = ayrik
    for i, p in enumerate(par):
        n = _n(p.metin).rstrip(" :")
        if n in ETIKETLER or n in ANTET:
            etiket_idx[i] = n
    # etiket -> aynı satırda sağdaki en yakın parça
    for i, n in etiket_idx.items():
        kullanilan.add(i)
        if n not in ETIKETLER:
            continue
        p = par[i]
        adaylar = [(q.x, j) for j, q in enumerate(par)
                   if j not in etiket_idx and abs(q.y - p.y) <= SATIR_TOLERANSI and q.x > p.x]
        if adaylar:
            _, j = min(adaylar)
            kullanilan.add(j)
            setattr(s, ETIKETLER[n], par[j].metin.strip())
    # anteti kapsayan bölge: etiketlerin satır aralığı; içindeki öbür parçalar (adlar, tarihler) not sayılmaz
    if etiket_idx:
        ys = [par[i].y for i in etiket_idx]
        xs = [par[i].x for i in etiket_idx]
        for j, q in enumerate(par):
            if min(ys) - SATIR_TOLERANSI <= q.y <= max(ys) + SATIR_TOLERANSI and q.x >= min(xs) - 150:
                kullanilan.add(j)

    for j, q in enumerate(par):
        if j in kullanilan:
            continue
        m = _RENK.match(q.metin)
        if m and not s.renk:
            s.renk = m.group(1).strip()
            continue
        if _SAYI.match(q.metin):
            v = _sayi(q.metin)
            if 1 <= v <= 10000:
                s.olculer.append(v)
            continue
        kal, ad = dxf_oku.etiket_oku(q.metin)           # K:6 / P:ad (kendi yazım düzeni)
        if kal is not None and s.kalinlik is None:
            s.kalinlik = kal
        if ad and not s.ad:
            s.ad = ad
        if s.kalinlik is None:
            k = dxf_oku._kalinlik_ara(q.metin)           # t=2, kalınlık 2 mm
            if k:
                s.kalinlik = k[0]
        a = _ADET.search(q.metin)
        if a and s.adet is None:
            s.adet = int(a.group(1) or a.group(2))
        for m in _MM.finditer(q.metin):
            v = _sayi(m.group(1))
            if 0.3 <= v <= 30:
                s.kalinlik_ipucu.append((v, q.metin))
        if (kal is None and not ad and re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]{3}", q.metin)
                and not _RENK.match(q.metin)):
            s.notlar.append(q.metin)
    s.olculer = sorted(set(s.olculer), reverse=True)
    if s.kalinlik is not None:  # kalınlık açıkça yazılmışsa belirsiz ipucu gerekmez
        s.kalinlik_ipucu = []
    m = _OLCU_AD.search(s.ad)
    if m:
        s.ad_olculeri = [_sayi(g) for g in m.groups() if g]
        if s.olculer and sorted(s.ad_olculeri, reverse=True) != s.olculer[:len(s.ad_olculeri)]:
            ol = " × ".join(f"{v:g}" for v in sorted(s.ad_olculeri, reverse=True))
            cz = " × ".join(f"{v:g}" for v in s.olculer)
            s.uyarilar.append(f"Parça adındaki ölçü ({ol}) çizimdeki ölçü yazılarıyla ({cz}) uyuşmuyor; kontrol edin.")
    if s.kalinlik is None and s.kalinlik_ipucu:
        s.uyarilar.append("Sac kalınlığı açıkça yazılmamış. Yazıda geçen ölçü: "
                          + "; ".join(f"“{t}”" for _, t in s.kalinlik_ipucu)
                          + " (sac kalınlığı olmayabilir: yüzey / malzeme ölçüsü), kontrol edip girin.")
    return s


def oku(yol: str) -> PdfSonuc:
    """PDF'in ilk yazılı sayfasından sonuç. Yazı yoksa (resim PDF) uyarıyla boş döner."""
    import pypdf
    logging.getLogger("pypdf").setLevel(logging.ERROR)   # bozuk sözlük uyarıları kullanıcıyı ilgilendirmez
    okuyucu = pypdf.PdfReader(yol)
    if okuyucu.is_encrypted:
        try:
            okuyucu.decrypt("")
        except Exception:
            raise ValueError("PDF şifreli; şifresiz kaydedip yeniden deneyin.") from None
    for no, sayfa in enumerate(okuyucu.pages, start=1):
        par = parcalar(sayfa)
        if par:
            s = coz(par)
            s.sayfa = no
            if len(okuyucu.pages) > 1:
                s.uyarilar.append(f"PDF {len(okuyucu.pages)} sayfa; yalnız {no}. sayfa okundu.")
            return s
    s = PdfSonuc()
    s.uyarilar.append("PDF'te okunabilir yazı yok (resim ya da taranmış sayfa). Ad, renk ve ölçüyü elle girin.")
    return s
