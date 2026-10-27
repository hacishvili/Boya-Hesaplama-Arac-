# -*- coding: utf-8 -*-
import math
import os
import shutil
import struct
import tempfile
import unittest

import kaliplar
import proje
import rapor
import stl_oku
from hesap import (Ayarlar, Kalem, Toz, kalem_sonucu, kaynak_alani, ozet, pratik_kg, sayi, teorik_kaplama, toz_kg,
                   yontem_ozeti)
from test_geometri import kup


class Toz_(unittest.TestCase):
    def test_formul(self):
        # 1 m², 70 µm, 1,5 g/cm³: 105 g; %65 verimle 161,5 g
        self.assertAlmostEqual(toz_kg(1.0, 70, 1.5, 1.0), 0.105)
        self.assertAlmostEqual(toz_kg(1.0, 70, 1.5, 0.65), 0.105 / 0.65)
        self.assertAlmostEqual(teorik_kaplama(1.5, 70), 9.5238, places=4)
        with self.assertRaises(ValueError):
            toz_kg(1, 70, 1.5, 0)

    def test_pratik_varsayilan(self):
        # atölye oranı: 1 kg tozla 6 m²
        a = Ayarlar()
        self.assertTrue(a.pratik)
        self.assertTrue(all(t.sarfiyat_m2_kg == 6.0 for t in a.tozlar))
        self.assertEqual(yontem_ozeti(a), "pratik sarfiyat: 1 kg = 6,0 m²")
        k = Kalem("ayak", {"tur": "elle", "alan_m2": 0.25}, adet=400, maske_cm2=50.0, toz=a.tozlar[0].ad,
                  kalinlik_um=120.0)  # kalınlık pratik yöntemde hesaba girmez
        s = kalem_sonucu(k, a)
        self.assertAlmostEqual(s.toplam_m2, 0.245 * 400)
        self.assertAlmostEqual(s.toz_kg, 0.245 * 400 / 6)
        self.assertAlmostEqual(s.toz_g_adet, 245 / 6)
        self.assertIsNone(s.kalinlik_um)
        a.tozlar[0].sarfiyat_m2_kg = 5.0  # metalik toz gibi daha az veren
        self.assertAlmostEqual(kalem_sonucu(k, a).toz_kg, 0.245 * 400 / 5)
        with self.assertRaises(ValueError):
            pratik_kg(1.0, 0.0)
        # eski ayar dosyası (yöntem ve sarfiyat yok): pratik, 6 m²/kg
        eski = Ayarlar.sozlukten({"verim": 0.7, "tozlar": [{"ad": "X", "yogunluk": 1.6}]})
        self.assertTrue(eski.pratik)
        self.assertEqual(eski.tozlar[0].sarfiyat_m2_kg, 6.0)

    def test_kalem_ve_ozet(self):
        a = Ayarlar(yontem="teorik", verim=0.5, proses_tl_m2=10.0,
                    tozlar=[Toz("A", 1.5, 200.0, 70.0), Toz("B", 1.2, 100.0, 60.0)])
        k1 = Kalem("plaka", {"tur": "2d", "yuz_alani": 50_000.0, "cevre": 1000.0, "kalinlik": 2.0,
                             "yuz_sayisi": 2, "kenar": True}, adet=10, maske_cm2=20.0, toz="A")
        self.assertAlmostEqual(kaynak_alani(k1.kaynak), 102_000.0)
        s = kalem_sonucu(k1, a)
        self.assertAlmostEqual(s.alan_m2, 0.102 - 0.002)
        self.assertAlmostEqual(s.toplam_m2, 1.0)
        self.assertAlmostEqual(s.toz_kg, 0.21)
        self.assertAlmostEqual(s.toz_tl, 42.0)
        self.assertAlmostEqual(s.proses_tl, 10.0)
        k2 = Kalem("elle", {"tur": "elle", "alan_m2": 0.5}, adet=2, toz="B", kalinlik_um=100.0)
        o = ozet([k1, k2], a)
        self.assertAlmostEqual(o.toplam_m2, 2.0)
        self.assertAlmostEqual(o.toz_bazinda["B"], 1.0 * 100 * 1.2 / 1000 / 0.5)
        self.assertEqual(o.toplam_adet, 12)
        # tek yüz, kenarsız
        k1.kaynak.update(yuz_sayisi=1, kenar=False)
        self.assertAlmostEqual(kaynak_alani(k1.kaynak), 50_000.0)
        # 3D açık yüzey iki yüz
        self.assertAlmostEqual(kaynak_alani({"tur": "3d", "alan": 300.0, "katsayi": 2.0}), 600.0)

    def test_maske_alandan_buyukse_sifir(self):
        k = Kalem("x", {"tur": "elle", "alan_m2": 0.001}, maske_cm2=50.0)
        self.assertEqual(kalem_sonucu(k, Ayarlar()).alan_m2, 0.0)

    def test_sayi(self):
        self.assertEqual(sayi(1234567.891, 2), "1.234.567,89")
        self.assertEqual(sayi(0.5, 0), "0")


class Kalip(unittest.TestCase):
    def test_boru(self):
        D, t, L, h = 25.0, 1.5, 400.0, 25.0
        di = D - 2 * t
        d = {"D": D, "t": t, "L": L, "h": h}
        self.assertAlmostEqual(kaliplar.alan("Yuvarlak boru", {**d, "uc": "tapalı"}), math.pi * D * L)
        self.assertAlmostEqual(kaliplar.alan("Yuvarlak boru", {**d, "uc": "kapaklı"}),
                               math.pi * D * L + 2 * math.pi / 4 * D * D)
        self.assertAlmostEqual(kaliplar.alan("Yuvarlak boru", {**d, "uc": "açık"}),
                               math.pi * D * L + 2 * math.pi / 4 * (D * D - di * di) + math.pi * di * 2 * h)
        # kısa boru: iç derinlik boyu aşamaz
        self.assertAlmostEqual(kaliplar.alan("Yuvarlak boru", {**d, "L": 30.0, "uc": "açık"}),
                               math.pi * D * 30 + 2 * math.pi / 4 * (D * D - di * di) + math.pi * di * 30)
        with self.assertRaises(ValueError):
            kaliplar.alan("Yuvarlak boru", {"D": 10, "t": 6})

    def test_profil(self):
        # keskin köşe: çevre 2(a+b); r = t: iç köşe keskin
        self.assertAlmostEqual(kaliplar.alan("Kutu profil", {"a": 40, "b": 20, "t": 2, "L": 100, "r": 0,
                                                             "uc": "tapalı"}), 12000.0)
        r = 3.0
        self.assertAlmostEqual(kaliplar.alan("Kutu profil", {"a": 40, "b": 20, "t": 2, "L": 100, "r": r,
                                                             "uc": "tapalı"}),
                               (120 - (8 - 2 * math.pi) * r) * 100)
        a = kaliplar.alan("Kutu profil", {"a": 40, "b": 20, "t": 2, "L": 100, "r": 0, "uc": "açık", "h": 10})
        self.assertAlmostEqual(a, 12000 + 2 * (800 - 36 * 16) + 2 * (36 + 16) * 20)

    def test_konik_ve_digerleri(self):
        # eşit çaplı konik = silindir
        self.assertAlmostEqual(kaliplar.alan("Konik ayak (boru)", {"D1": 30, "D2": 30, "L": 100, "uc": "tapalı"}),
                               math.pi * 30 * 100)
        R1, R2, L = 20.0, 12.5, 150.0
        self.assertAlmostEqual(kaliplar.alan("Konik ayak (boru)", {"D1": 40, "D2": 25, "L": L, "uc": "tapalı"}),
                               math.pi * (R1 + R2) * math.hypot(L, R1 - R2))
        self.assertAlmostEqual(kaliplar.alan("Dolu yuvarlak çubuk", {"D": 10, "L": 100}),
                               math.pi * 1000 + 2 * math.pi * 25)
        self.assertAlmostEqual(kaliplar.alan("Lama / dolu kare", {"a": 30, "b": 5, "L": 100, "uclar": "boyanmaz"}),
                               7000.0)
        self.assertAlmostEqual(kaliplar.alan("Sac levha", {"a": 300, "b": 200, "t": 1, "yuz": "tek yüz"}),
                               2 * 60000 + 1000)  # yüz seçimi yok: eski projedeki "tek yüz" yok sayılır
        self.assertIn("Ø40", kaliplar.aciklama("Konik ayak (boru)", {}))


class Stl(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.klasor, ignore_errors=True)

    def _ucgenler(self):
        out = []
        for y in kup(0, 0, 0, 10) + kup(100, 0, 0, 1):
            out += [[y[0], y[1], y[2]], [y[0], y[2], y[3]]]
        return out

    def test_ikili_ve_metin(self):
        tri = self._ucgenler()
        ikili = os.path.join(self.klasor, "b.stl")
        with open(ikili, "wb") as f:
            f.write(b"\0" * 80 + struct.pack("<I", len(tri)))
            for t in tri:
                f.write(struct.pack("<12fH", 0, 0, 0, *t[0], *t[1], *t[2], 0))
        metin = os.path.join(self.klasor, "a.stl")
        with open(metin, "w") as f:
            f.write("solid x\n")
            for t in tri:
                f.write("facet normal 0 0 0\n outer loop\n" + "".join(f"  vertex {p[0]} {p[1]} {p[2]}\n" for p in t)
                        + " endloop\nendfacet\n")
            f.write("endsolid x\n")
        for yol in (ikili, metin):
            g = stl_oku.govdeler(yol)
            self.assertEqual(sorted(round(x.alan, 6) for x in g), [6.0, 600.0])
            self.assertTrue(all(x.kapali_mi() for x in g))
        self.assertEqual(sorted(round(x.alan, 3) for x in stl_oku.govdeler(ikili, 10.0)), [600.0, 60000.0])


class Dosyalar(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.klasor, ignore_errors=True)

    def test_proje_ve_csv(self):
        a = Ayarlar(verim=0.7, tozlar=[Toz("Siyah mat; RAL 9005", 1.6, 250.0, 80.0, 5.5)])
        k = [Kalem("ayak", {"tur": "kalip", "kalip": "Yuvarlak boru", "deger": {"D": 30.0, "L": 150.0}}, 400,
                   5.0, "Siyah mat; RAL 9005"),
             Kalem("plaka", {"tur": "2d", "yuz_alani": 1000.0, "cevre": 130.0, "kalinlik": 2.0, "olcu": [50, 20]},
                   2, toz="yok", kalinlik_um=90.0)]
        yol = os.path.join(self.klasor, "p.tozboya")
        proje.kaydet(yol, k, a, "Müşteri A")
        k2, a2, m = proje.ac(yol)
        self.assertEqual(m, "Müşteri A")
        self.assertEqual([x.sozluk() for x in k2], [x.sozluk() for x in k])
        self.assertEqual(a2.sozluk(), a.sozluk())
        self.assertAlmostEqual(ozet(k2, a2).toz_kg, ozet(k, a).toz_kg)
        csv = os.path.join(self.klasor, "r.csv")
        rapor.csv_yaz(csv, k, a)
        with open(csv, "rb") as f:
            ham = f.read()
        self.assertTrue(ham.startswith(b"\xef\xbb\xbf"))
        metin = ham.decode("utf-8-sig")
        self.assertIn('"Siyah mat; RAL 9005"', metin)
        self.assertIn("TOPLAM", metin)
        self.assertIn("1 kg = 5,5 m²", metin)
        self.assertIn("Müşteri A", rapor.html_rapor(k, a, "Müşteri A"))

    def test_yabanci_dosya(self):
        yol = os.path.join(self.klasor, "x.tozboya")
        with open(yol, "w") as f:
            f.write('{"tur": "baska"}')
        with self.assertRaises(ValueError):
            proje.ac(yol)


class Abkant(unittest.TestCase):
    AD = "Abkant sac (açınım)"

    def test_u_profil_acinimi_ve_alani(self):
        import kaliplar
        d = {"k1": 400, "k2": 500, "k3": 400, "W": 240, "t": 6, "ri": 6, "K": 0.4}
        # BA = π/2 (6 + 2,4) = 13,195; BD = 2 (6 + 6) − BA = 10,805; L = 1300 − 2 BD
        L, W = kaliplar.abkant_acinim(d)
        self.assertAlmostEqual(L, 1300 - 2 * (24 - math.pi / 2 * 8.4), places=6)
        self.assertEqual(W, 240)
        self.assertAlmostEqual(kaliplar.alan(self.AD, d), 2 * L * W + 2 * (L + W) * 6, places=6)
        # ri = 0: kalınlığa eşit sayılır
        self.assertAlmostEqual(kaliplar.abkant_acinim({**d, "ri": 0})[0], L, places=9)

    def test_kesik_alan_ve_kenarlari(self):
        import kaliplar
        d = {"k1": 400, "k2": 500, "k3": 400, "W": 240, "t": 6}
        L, W = kaliplar.abkant_acinim(d)
        tam = kaliplar.alan(self.AD, d)
        kes = kaliplar.alan(self.AD, {**d, "kesik": 2 * 60000, "kesik_c": 2 * 1000})
        self.assertAlmostEqual(kes, tam - 2 * 2 * 60000 + 2 * 1000 * 6, places=6)

    def test_gecersiz_girdiler(self):
        import kaliplar
        with self.assertRaises(ValueError):
            kaliplar.alan(self.AD, {"k1": 400, "W": 240})            # kalınlık yok (varsayılan 0)
        with self.assertRaises(ValueError):
            kaliplar.alan(self.AD, {"k1": 5, "k2": 5, "k3": 0, "W": 100, "t": 6})   # kenarlar büküm payından küçük
        with self.assertRaises(ValueError):
            kaliplar.alan(self.AD, {"k1": 100, "k2": 0, "k3": 0, "W": 10, "t": 1, "kesik": 1e6})


if __name__ == "__main__":
    unittest.main()
