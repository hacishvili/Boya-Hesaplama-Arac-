# -*- coding: utf-8 -*-
"""STEP katıları: step_ornekleri/*.step Open CASCADE ile üretilmiş örnekler (step_ornekleri/uret.py); beklenen alanlar Open
CASCADE'in yüzey integralinden."""
import math
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import step_oku  # noqa: E402

KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "step_ornekleri")
OCC = {"plaka": 13653.984393604891, "fileto": 4563.822850925158, "donel": 2436.896063822144,
       "cekim": 851.6696697653824, "montaj": 24909.73355292326}


def coz(ad, k=None):
    m = step_oku.oku(os.path.join(KLASOR, ad + ".step"))
    return m, step_oku.cozumle(m, m.birim_mm if k is None else k)


class Step(unittest.TestCase):
    def test_alanlar(self):
        """Düzlem, silindir, koni, fileto (torus / B-spline), dönel ve çekim yüzeyi (B-spline'a çevrilir)."""
        for ad, beklenen in OCC.items():
            _, s = coz(ad)
            self.assertFalse([g.hata for g in s.govdeler if g.hata], ad)
            self.assertAlmostEqual(sum(g.alan for g in s.govdeler), beklenen, delta=beklenen * 1e-4, msg=ad)

    def test_kure_torus_koni(self):
        _, s = coz("cisimler")
        alan = sorted(g.alan for g in s.govdeler)
        R, r = 20, 5
        beklenen = sorted([4 * math.pi * 100, 4 * math.pi ** 2 * R * r, math.pi * 10 * (10 + math.hypot(10, 20))])
        for a, b in zip(alan, beklenen):
            self.assertAlmostEqual(a, b, delta=b * 1e-5)

    def test_delik_havsa_ve_birim(self):
        m, s = coz("plaka")
        self.assertEqual(m.birim_mm, 1.0)
        g = s.govdeler[0]
        self.assertIsNotNone(g.sac)
        self.assertAlmostEqual(g.sac.kalinlik, 5.0, places=6)
        delik = sorted((round(d.cap, 3), round(d.havsa_cap or 0, 3), round(d.havsa_aci or 0)) for d in g.delikler)
        self.assertEqual(delik, [(6.0, 0.0, 0), (6.0, 12.0, 90)])
        m, s = coz("plaka_inc")                     # dosya inç: mm'ye çevrilir
        self.assertAlmostEqual(m.birim_mm, 25.4)
        self.assertAlmostEqual(s.govdeler[0].alan, OCC["plaka"], delta=0.01)
        _, s = coz("plaka_inc", 1.0)                # kullanıcı birimi değiştirirse ölçek ona göre
        self.assertAlmostEqual(s.govdeler[0].alan, OCC["plaka"] / 25.4 ** 2, delta=0.01)

    def test_montaj_yerlesim_ad_ve_kaynak(self):
        """Montajda parça kopyaları yerleşimleriyle (dönme + öteleme) ayrı gövde; değme kenarları kaynak önerisi."""
        _, s = coz("masa")
        adlar = [g.ad for g in s.govdeler]
        self.assertEqual(adlar, ["AYAK (1)", "AYAK (2)", "AYAK (3)", "AYAK (4)", "TABLA"])
        kutular = sorted(tuple(round(c) for c in g.ag.kutu()[0]) for g in s.govdeler[:4])
        self.assertEqual(kutular, [(0, 0, -200), (0, 280, -200), (380, 0, -200), (380, 280, -200)])
        for g in s.govdeler[:4]:
            self.assertEqual(len(g.ag.oneri), 4)     # ayağın üst karesi tablaya değer
            self.assertEqual([round(d.cap, 3) for d in g.delikler], [8.0])
            self.assertEqual(len(g.ag.yuz_donguleri), len(g.ag.yuz_alanlari))
        self.assertAlmostEqual(s.govdeler[4].alan, 2 * (400 * 300 + 400 * 10 + 300 * 10), places=6)

    def test_ayristirici(self):
        metin = """ISO-10303-21;
HEADER; FILE_NAME('a;b','',(''),(''),'','',''); ENDSEC;
DATA;
/* yorum ; #9=X(); */
#1=CARTESIAN_POINT('it''s',(1.,-2.5E1,.5));
#2=(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.));
#3=MEASURE_REPRESENTATION_ITEM('',LENGTH_MEASURE(2.),#2);
ENDSEC; END-ISO-10303-21;"""
        v = step_oku.ayristir(metin)
        self.assertEqual(sorted(v), [1, 2, 3])
        self.assertEqual(v[1]["CARTESIAN_POINT"], ["it's", [1.0, -25.0, 0.5]])
        self.assertEqual(v[2]["SI_UNIT"], ["MILLI", "METRE"])
        self.assertEqual(v[3]["MEASURE_REPRESENTATION_ITEM"][1], step_oku.Tipli("LENGTH_MEASURE", [2.0]))
        with self.assertRaises(step_oku.StepHatasi):
            step_oku.ayristir("bu bir STEP değil")
        with self.assertRaises(step_oku.StepHatasi):
            step_oku.modelle(v)                      # katı yok

    def test_ice_aktarma(self):
        """Pencere: STEP birimi, aynı parçalar adet olarak, kaynak ve yüzey seçimi."""
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        import pencere
        from hesap import kalem_sonucu
        w = pencere.AnaPencere()
        d = pencere.IceAktar(os.path.join(KLASOR, "masa.step"), w.ayar.tozlar[0].ad, w)
        self.assertEqual(d.birim.currentText(), "mm")
        kalemler = d.kalemler()
        self.assertEqual(sorted((k.ad.split(" – ")[-1], k.adet) for k in kalemler), [("AYAK (1)", 4), ("TABLA", 1)])
        ayak = next(k for k in kalemler if k.adet == 4)
        w.ayar.islemler[0].fiyat = 10.0
        w.ayar.islemler[0].tel = False
        s = kalem_sonucu(ayak, w.ayar)
        self.assertAlmostEqual(s.islem_detay["Kaynak"][0], 0.08, places=6)   # üst kare 4 × 20 mm
        self.assertEqual(s.islem_detay.get("Havşa"), None)
        p = pencere.YuzeyPenceresi(ayak.geo, [])
        p.gorunum.tikla(0)
        self.assertEqual(len(p.secim()), 1)
        d2 = pencere.IceAktar(os.path.join(KLASOR, "plaka_inc.step"), w.ayar.tozlar[0].ad, w)
        self.assertEqual(d2.birim.currentText(), "inç")
        w.degisti = False
        w.close()


if __name__ == "__main__":
    unittest.main()
