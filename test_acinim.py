# -*- coding: utf-8 -*-
"""Açınım: yay uzunlukları nötr çevrelere eşit; DXF geri okununca alan formülle aynı."""
import math
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import acinim
import dxf_oku


class Acinim(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.klasor, ignore_errors=True)

    def test_kesik_koni(self):
        a = acinim.hesapla(25, 40, 150, 1.5, "dış")
        self.assertAlmostEqual(a.d1, 23.5)  # dış çap − t (K = 0,5)
        self.assertAlmostEqual(a.d2, 38.5)
        self.assertAlmostEqual(math.radians(a.aci) * a.Ra, math.pi * a.d1, places=9)
        self.assertAlmostEqual(math.radians(a.aci) * a.Rb, math.pi * a.d2, places=9)
        self.assertAlmostEqual(a.Rb - a.Ra, math.hypot(150, 7.5), places=9)
        self.assertAlmostEqual(a.alan, math.pi * (23.5 + 38.5) / 2 * math.hypot(150, 7.5), places=6)
        # çap yüzeyi ve K
        self.assertAlmostEqual(acinim.hesapla(25, 40, 150, 1.5, "iç").d1, 26.5)
        self.assertAlmostEqual(acinim.hesapla(25, 40, 150, 1.5, "orta").d1, 25.0)
        self.assertAlmostEqual(acinim.hesapla(25, 40, 150, 2.0, "dış", k=0.3).d1, 25 - 2 * 0.7 * 2)
        with self.assertRaises(ValueError):
            acinim.hesapla(1, 40, 150, 1.5)  # nötr çap eksi

    def test_silindir(self):
        a = acinim.hesapla(30, 30, 200, 2)
        self.assertTrue(a.silindir)
        self.assertEqual(a.olcu, (math.pi * 28, 200))

    def test_dxf_geri_okunur(self):
        for d_alt, d_ust in ((25, 40), (40, 40), (10, 300)):  # 300: dilim 180°'den büyük
            a = acinim.hesapla(d_alt, d_ust, 150, 1.5)
            yol = os.path.join(self.klasor, "a.dxf")
            acinim.dxf_yaz(yol, a, "Konik ayak")
            s = dxf_oku.cozumle(dxf_oku.belge_ac(yol))
            self.assertEqual(len(s.parcalar), 1)
            self.assertAlmostEqual(s.parcalar[0].yuz_alani, a.alan, delta=a.alan * 1e-5)
            self.assertEqual(s.olcek, 1.0)

    def test_pencere_kalip_ve_3d(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        import pencere
        from hesap import Kalem
        k = Kalem("ayak", {"tur": "kalip", "kalip": "Konik ayak (boru)", "deger": {"D1": 40.0, "D2": 25.0, "L": 150.0,
                                                                                   "t": 1.5}})
        o = pencere.acinim_olculeri(k)
        self.assertEqual(o, {"d1": 25.0, "d2": 40.0, "boy": 150.0, "t": 1.5})
        d = pencere.AcinimPenceresi(o, "ayak")
        self.assertAlmostEqual(d.a.alan, acinim.hesapla(25, 40, 150, 1.5).alan)
        d.t.setValue(30.0)  # Ø25 dış çapa 30 mm sac: nötr çap eksi, kaydedilemez
        self.assertFalse(d.kaydet_dugmesi.isEnabled())
        # 3D yuvarlak boru: ölçüler modelden (dış çap, boy, kalınlık)
        import test_profil
        t = test_profil.Profil("test_yuvarlak_boru")
        t.setUp()
        try:
            import test_acis as T
            g = T.Govde()
            R, r, L = 20.0, 18.0, 200.0
            vo0, vo1, vi0, vi1 = g.kose((R, 0, 0)), g.kose((R, 0, L)), g.kose((r, 0, 0)), g.kose((r, 0, L))
            eo0 = g.kenar(vo0, 0, vo0, T.TAM, g.daire((0, 0, 0), (0, 0, 1), (R, 0, 0)))
            eo1 = g.kenar(vo1, 0, vo1, T.TAM, g.daire((0, 0, L), (0, 0, 1), (R, 0, 0)))
            ei0 = g.kenar(vi0, 0, vi0, T.TAM, g.daire((0, 0, 0), (0, 0, 1), (r, 0, 0)))
            ei1 = g.kenar(vi1, 0, vi1, T.TAM, g.daire((0, 0, L), (0, 0, 1), (r, 0, 0)))
            g.yuz(T.koni(g, (0, 0, -30), (0, 0, 1), (R, 0, 0)), [[(eo1, True)], [(eo0, False)]])
            g.yuz(T.koni(g, (0, 0, -30), (0, 0, 1), (r, 0, 0)), [[(ei1, False)], [(ei0, True)]], ters=True)
            g.yuz(T.duzlem(g, (0, 0, L), (0, 0, 1), (1, 0, 0)), [[(eo1, False)], [(ei1, True)]])
            g.yuz(T.duzlem(g, (0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(eo0, True)], [(ei0, False)]])
            koni = t.oku(g.satirlar()).profil.koni
        finally:
            t.tearDown()
        self.assertAlmostEqual(koni["d1"], 40.0, places=6)
        self.assertAlmostEqual(koni["d2"], 40.0, places=6)
        self.assertAlmostEqual(koni["boy"], 200.0, places=6)
        self.assertAlmostEqual(koni["t"], 2.0, places=6)


if __name__ == "__main__":
    unittest.main()
