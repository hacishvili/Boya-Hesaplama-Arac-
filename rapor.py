# -*- coding: utf-8 -*-
"""Çıktılar: Excel'in açtığı CSV (noktalı virgül, Türkçe ondalık, UTF-8 BOM) ve PDF raporun HTML'i.
PDF'e çevirme pencerede Qt ile yapılır (pdf_yaz)."""
from __future__ import annotations

import datetime
import html
from typing import List

from hesap import Ayarlar, Kalem, kalem_sonucu, kaynak_aciklamasi, ozet, sayi, yontem_ozeti

BASLIKLAR = ["Parça", "Açıklama", "Adet", "Alan / adet (m²)", "Toplam alan (m²)", "Toz", "Kalınlık (µm)",
             "Toz / adet (g)", "Toplam toz (kg)", "Toz tutarı", "Proses tutarı", "İşlem tutarı", "Tutar",
             "Adet fiyatı", "Ağırlık / adet (kg)", "Toplam ağırlık (kg)"]


def ek_aciklama(k: Kalem) -> str:
    """Maske ve kat bilgisi (açıklamaya eklenir)."""
    s = ""
    if k.maske_yuzde:
        s += f"; maske %{sayi(k.maske_yuzde, 1)}"
    if k.maske_cm2:
        s += f"; maske {sayi(k.maske_cm2, 1)} cm²"
    if k.kat > 1:
        s += f"; {k.kat} kat"
    return s


def agirlik_metni(x, basamak: int = 3) -> str:
    return "—" if x is None else sayi(x, basamak)


def satirlar(kalemler: List[Kalem], a: Ayarlar) -> List[List[str]]:
    out = []
    for k in kalemler:
        s = kalem_sonucu(k, a)
        islem = "".join(f"; {ad} {sayi(m, 3)}" for ad, (m, _) in s.islem_detay.items())
        out.append([k.ad, kaynak_aciklamasi(k.kaynak) + ek_aciklama(k) + islem,
                    str(k.adet), sayi(s.alan_m2, 4), sayi(s.toplam_m2, 3), a.toz(k.toz).ad,
                    "—" if s.kalinlik_um is None else sayi(s.kalinlik_um, 0),
                    sayi(s.toz_g_adet, 1), sayi(s.toz_kg, 3), sayi(s.toz_tl, 2), sayi(s.proses_tl, 2),
                    sayi(s.islem_tl, 2), sayi(s.tutar, 2), sayi(s.birim_fiyat, 2), agirlik_metni(s.agirlik_kg_adet),
                    agirlik_metni(s.agirlik_kg, 2)])
    return out


def csv_yaz(yol: str, kalemler: List[Kalem], a: Ayarlar) -> None:
    def hucre(x: str) -> str:
        x = str(x)
        return '"' + x.replace('"', '""') + '"' if any(c in x for c in ';"\n') else x

    o = ozet(kalemler, a)
    satir = [BASLIKLAR] + satirlar(kalemler, a)
    satir.append(["TOPLAM", "", str(o.toplam_adet), "", sayi(o.toplam_m2, 3), "", "", "", sayi(o.toz_kg, 3),
                  sayi(o.toz_tl, 2), sayi(o.proses_tl, 2), sayi(o.islem_tl, 2), sayi(o.tutar, 2), "", "",
                  sayi(o.agirlik_kg, 2)])
    satir.append([])
    satir.append(["Toz hesabı", yontem_ozeti(a)])
    satir.append(["Proses ücreti", f"{sayi(a.proses_tl_m2, 2)} {a.para}/m²"])
    for ad, kg in o.toz_bazinda.items():
        t = a.toz(ad)
        oran = (f"1 kg = {sayi(t.sarfiyat_m2_kg, 1)} m²" if a.pratik else f"yoğunluk {sayi(t.yogunluk, 2)} g/cm³")
        satir.append([f"Toz: {ad}", f"{sayi(kg, 3)} kg", oran, f"{sayi(t.fiyat, 2)} {a.para}/kg"])
    for ad, (m, tl) in o.islem_bazinda.items():
        i = next((x for x in a.islemler if x.ad == ad), None)
        satir.append([f"İşlem: {ad}", f"{sayi(m, 3)} {i.birim if i else ''}",
                      f"{sayi(a.birim_fiyati(i) if i else 0, 2)} {a.para}/{i.birim if i else ''}", f"{sayi(tl, 2)} {a.para}"])
    if o.tel_kg:
        t = a.kaynak_teli
        satir.append(["Kaynak teli", f"{sayi(o.tel_kg, 3)} kg", f"{sayi(t.cap_mm, 1)} mm, {sayi(t.kg_fiyat, 2)} {a.para}/kg",
                      f"{sayi(o.tel_kg / t.makara_kg if t.makara_kg else 0, 2)} makara ({sayi(t.makara_kg, 0)} kg)"])
    with open(yol, "w", encoding="utf-8-sig", newline="") as f:
        for s in satir:
            f.write(";".join(hucre(x) for x in s) + "\r\n")


def html_rapor(kalemler: List[Kalem], a: Ayarlar, musteri: str = "", baslik: str = "Toz Boya Hesabı") -> str:
    e = html.escape
    o = ozet(kalemler, a)
    tarih = datetime.date.today().strftime("%d.%m.%Y")
    sag = {2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15}
    genislik = {0: 9, 1: 18, 5: 9}
    th = "".join(f"<th width={genislik.get(i, 6)}%>{e(b)}</th>" for i, b in enumerate(BASLIKLAR))
    govde = ""
    for r in satirlar(kalemler, a):
        govde += "<tr>" + "".join(f"<td{' align=right' if i in sag else ''}>{e(x)}</td>"
                                  for i, x in enumerate(r)) + "</tr>"
    govde += (f"<tr class=t><td><b>TOPLAM</b></td><td></td><td align=right><b>{o.toplam_adet}</b></td><td></td>"
              f"<td align=right><b>{sayi(o.toplam_m2, 3)}</b></td><td></td><td></td><td></td>"
              f"<td align=right><b>{sayi(o.toz_kg, 3)}</b></td><td align=right><b>{sayi(o.toz_tl, 2)}</b></td>"
              f"<td align=right><b>{sayi(o.proses_tl, 2)}</b></td><td align=right><b>{sayi(o.islem_tl, 2)}</b></td>"
              f"<td align=right><b>{sayi(o.tutar, 2)}</b></td><td></td>"
              f"<td></td><td align=right><b>{sayi(o.agirlik_kg, 2)}</b></td></tr>")
    oran = (lambda t: f"1 kg = {sayi(t.sarfiyat_m2_kg, 1)} m²") if a.pratik else \
        (lambda t: f"{sayi(t.yogunluk, 2)} g/cm³")
    tozlar = "".join(
        f"<tr><td>{e(ad)}</td><td align=right>{sayi(kg, 3)} kg</td><td align=right>{oran(a.toz(ad))}</td>"
        f"<td align=right>{sayi(a.toz(ad).fiyat, 2)} {e(a.para)}/kg</td></tr>"
        for ad, kg in o.toz_bazinda.items())
    birim = {i.ad: i for i in a.islemler}
    islemler = "".join(
        f"<tr><td>{e(ad)}</td><td align=right>{sayi(m, 3)} {e(birim[ad].birim if ad in birim else '')}</td>"
        f"<td align=right>{sayi(a.birim_fiyati(birim[ad]) if ad in birim else 0, 2)} {e(a.para)}</td>"
        f"<td align=right>{sayi(tl, 2)} {e(a.para)}</td></tr>" for ad, (m, tl) in o.islem_bazinda.items())
    t = a.kaynak_teli
    tel = (f"<p>Kaynak teli ({sayi(t.cap_mm, 1)} mm, {sayi(t.kg_fiyat, 2)} {e(a.para)}/kg): {sayi(o.tel_kg, 3)} kg"
           f" ≈ {sayi(o.tel_kg / t.makara_kg if t.makara_kg else 0, 2)} makara</p>" if o.tel_kg else "")
    islem_tablosu = (f"<p><b>İşlemler</b></p><table><tr><th>İşlem</th><th>Miktar</th><th>Birim fiyat</th>"
                     f"<th>Tutar</th></tr>{islemler}</table>" + tel if islemler else "")
    formul = ("Toz = alan ÷ sarfiyat (1 kg tozla boyanan m², fire dahil)." if a.pratik else
              "Toz = alan × kalınlık × yoğunluk ÷ transfer verimi.")
    return f"""<html><head><meta charset="utf-8"><style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 8pt; }}
h1 {{ font-size: 14pt; margin: 0; }} .alt {{ color: #555; }}
table {{ border-collapse: collapse; }} th {{ background: #e8edf2; text-align: left; }}
th, td {{ border: 1px solid #b8c2cc; padding: 3px 5px; }} tr.t td {{ background: #f3f5f7; }}
</style></head><body>
<h1>{e(baslik)}</h1>
<p class=alt>{e(musteri) + ' · ' if musteri else ''}{tarih}</p>
<table width=100%><tr>{th}</tr>{govde}</table>
<p><b>Toz ihtiyacı</b> ({e(yontem_ozeti(a))})</p>
<table><tr><th>Toz</th><th>Miktar</th><th>{"Sarfiyat" if a.pratik else "Yoğunluk"}</th><th>Fiyat</th></tr>{tozlar}</table>
{islem_tablosu}
<p class=alt>{formul} Alanlar çizimden (2D açınım, 3D gövde) ya da kalıptan
hesaplanmıştır; maskelenen yüzeyler düşülmüştür; çok katlı kalemlerde toz ve proses kat sayısıyla çarpılır.
Proses ücreti: {sayi(a.proses_tl_m2, 2)} {e(a.para)}/m² (kat başına). Ağırlık: metal hacmi × {sayi(a.metal_yogunluk, 2)}
g/cm³{f"; {o.agirliksiz} kalemin ağırlığı bilinmiyor (—)" if o.agirliksiz else ""}.</p>
</body></html>"""
