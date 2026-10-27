# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
import unittest

import pdf_oku


def pdf_yaz(yol, yazilar, donus=0, en=595, boy=842, ayri=True):
    """Standart yazı tipli tek sayfalık PDF. yazilar: (x, y, metin) — sayfa içeriği koordinatında (y yukarı)."""
    icerik = "BT /F1 10 Tf\n" + "".join(f"1 0 0 1 {x} {y} Tm ({m}) Tj\n" for x, y, m in yazilar) + "ET"
    nesneler = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {en} {boy}] /Rotate {donus} /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(icerik)} >>\nstream\n{icerik}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    cikti = bytearray(b"%PDF-1.4\n")
    konum = []
    for i, n in enumerate(nesneler, start=1):
        konum.append(len(cikti))
        cikti += f"{i} 0 obj\n{n}\nendobj\n".encode("latin-1")
    xref = len(cikti)
    cikti += f"xref\n0 {len(nesneler) + 1}\n0000000000 65535 f \n".encode()
    for k in konum:
        cikti += f"{k:010d} 00000 n \n".encode()
    cikti += f"trailer\n<< /Size {len(nesneler) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    with open(yol, "wb") as f:
        f.write(cikti)


# ANTET: görünen sayfada etiket solda, değeri aynı satırda sağında; "RENK" ve ölçü yazıları serbest
YAZI = [(300, 100, "PARCA ADI"), (400, 100, "400x400x240 SEHPA METALI"),
        (300, 80, "URUN ADI"), (400, 80, "MADRAS"), (300, 60, "TARIH"), (400, 60, "01.07.2026"),
        (50, 700, "500"), (50, 650, "400"), (50, 600, "240"), (200, 300, "PATIK OLACAK"),
        (200, 400, "MACCHIA VECCHIA 6MM PARLAK"), (200, 500, "RENK: METALIK KAHVE")]


class PdfOku(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.klasor, ignore_errors=True)

    def sonuc(self, yazilar, donus=0, ayri=True):
        yol = os.path.join(self.klasor, "c.pdf")
        pdf_yaz(yol, yazilar, donus, ayri=ayri)
        return pdf_oku.oku(yol)

    def test_antet_renk_olcu_not(self):
        s = self.sonuc(YAZI)
        self.assertEqual(s.ad, "400x400x240 SEHPA METALI")
        self.assertEqual(s.urun, "MADRAS")
        self.assertEqual(s.renk, "METALIK KAHVE")
        self.assertEqual(s.olculer, [500.0, 400.0, 240.0])
        self.assertIn("PATIK OLACAK", s.notlar)
        self.assertNotIn("MADRAS", s.notlar)
        # parça adındaki ölçü çizimdekiyle uyuşmuyor: uyarı
        self.assertTrue(any("uyuşmuyor" in u for u in s.uyarilar))

    def test_birlesik_satir_da_okunur(self):
        s = self.sonuc(YAZI, ayri=False)
        self.assertEqual((s.ad, s.urun, s.renk), ("400x400x240 SEHPA METALI", "MADRAS", "METALIK KAHVE"))

    def test_kalinlik_belirsiz_ipucu_olur_atanmaz(self):
        s = self.sonuc(YAZI)
        self.assertIsNone(s.kalinlik)
        self.assertEqual([v for v, _ in s.kalinlik_ipucu], [6.0])
        self.assertTrue(any("kalınlığı açıkça yazılmamış" in u for u in s.uyarilar))

    def test_kalinlik_ve_ad_etiketten(self):
        s = self.sonuc([(50, 700, "K:4 P:ON PLAKA"), (50, 650, "ADET: 3")])
        self.assertEqual((s.kalinlik, s.ad, s.adet), (4.0, "ON PLAKA", 3))
        self.assertEqual(self.sonuc([(50, 700, "t=2 sac")]).kalinlik, 2.0)

    def test_donuk_sayfada_gorunen_satir(self):
        # sayfa 270° döndürülmüş: görünen satır, içerikte sabit x'tir; etiketin değeri görünen yönde sağdadır
        yazi = [(85, 491, "PARCA ADI"), (85, 418, "SEHPA"), (50, 491, "URUN ADI"), (50, 418, "MADRAS"),
                (71, 491, "PARCA KODU"), (71, 418, "X1")]
        s = self.sonuc(yazi, donus=270)
        self.assertEqual((s.ad, s.urun), ("SEHPA", "MADRAS"))

    def test_yazisiz_pdf(self):
        yol = os.path.join(self.klasor, "bos.pdf")
        pdf_yaz(yol, [])
        s = pdf_oku.oku(yol)
        self.assertEqual(s.ad, "")
        self.assertTrue(any("okunabilir yazı yok" in u for u in s.uyarilar))


if __name__ == "__main__":
    unittest.main()
