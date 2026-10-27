# -*- coding: utf-8 -*-
import math
import unittest

from geometri import Ag, Kontur, cokgen_alani, isaretli_alan, yerlestir, zincirle


def kare(x, y, a):
    return [(x, y), (x + a, y), (x + a, y + a), (x, y + a)]


def kup(x, y, z, a):
    p = [(x + i * a, y + j * a, z + k * a) for i in (0, 1) for j in (0, 1) for k in (0, 1)]
    yuz = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return [[p[i] for i in f] for f in yuz]


class Kontur2D(unittest.TestCase):
    def test_alan_cevre(self):
        self.assertAlmostEqual(isaretli_alan(kare(0, 0, 10)), 100.0)
        self.assertAlmostEqual(isaretli_alan(list(reversed(kare(0, 0, 10)))), -100.0)
        k = Kontur(kare(0, 0, 10) + [(0, 0)])  # tekrar eden son nokta atılır
        self.assertEqual(len(k.noktalar), 4)
        self.assertAlmostEqual(k.cevre, 40.0)

    def test_ic_ice(self):
        # parça, içinde iki delik, bir deliğin içinde ada (ayrı parça), yanında ikinci parça
        konturlar = [Kontur(kare(0, 0, 100)), Kontur(kare(10, 10, 30)), Kontur(kare(60, 60, 20)),
                     Kontur(kare(15, 15, 10)), Kontur(kare(200, 0, 50)), Kontur(kare(0, 0, 100))]
        p = yerlestir(konturlar)
        self.assertEqual(len(p), 3)
        self.assertAlmostEqual(p[0].yuz_alani, 10000 - 900 - 400)
        self.assertAlmostEqual(p[0].toplam_cevre, 400 + 120 + 80)
        self.assertEqual(sorted(x.yuz_alani for x in p), [100.0, 2500.0, 8700.0])


class Zincir(unittest.TestCase):
    def test_kapanir_bos_uc_ve_kopya_atilir(self):
        kenar = [[(0, 0), (100, 0)], [(100, 0), (100, 50)], [(0, 50), (100, 50.004)],  # tersi ve 0,004 açıklık
                 [(0, 50), (0, 0)], [(100, 0), (100, 50)],                              # kopya çizgi
                 [(50, 0), (50, 50)],                                                    # büküm çizgisi
                 [(300, 0), (400, 0)]]                                                   # boşta çizgi
        konturlar, atilan = zincirle(kenar, tol=0.01)
        self.assertEqual(len(konturlar), 1)
        self.assertAlmostEqual(Kontur(konturlar[0]).alan, 5000.0, delta=0.5)
        self.assertEqual(atilan, 2)

    def test_dallanan_dis_siniri_alinir(self):
        # ortak kenarlı iki üçgen: dış sınır (büyük üçgen) alınır, içteki ortak çizgi atılır
        kenar = [[(0, 0), (10, 0)], [(10, 0), (10, 10)], [(10, 10), (0, 0)], [(10, 0), (20, 0)], [(20, 0), (10, 10)]]
        konturlar, atilan = zincirle(kenar)
        self.assertEqual(len(konturlar), 1)
        self.assertAlmostEqual(Kontur(konturlar[0]).alan, 100.0, places=6)
        self.assertEqual(atilan, 1)

    def test_koprulu_sekiller_cozulmez(self):
        # iki kare ve köşelerini bağlayan tek çizgi: dış yürüyüş köprüden iki kez geçer; kontur uydurulmaz
        kare = lambda x: [[(x, 0), (x + 10, 0)], [(x + 10, 0), (x + 10, 10)], [(x + 10, 10), (x, 10)], [(x, 10), (x, 0)]]
        konturlar, atilan = zincirle(kare(0) + kare(50) + [[(10, 0), (50, 0)]])
        self.assertEqual(konturlar, [])
        self.assertEqual(atilan, 9)


class Ag3D(unittest.TestCase):
    def test_kup(self):
        a = Ag(kup(0, 0, 0, 10))
        self.assertAlmostEqual(a.alan, 600.0)
        self.assertTrue(a.kapali_mi())

    def test_acik_ve_govdeler(self):
        acik = Ag(kup(0, 0, 0, 10)[:5])
        self.assertFalse(acik.kapali_mi())
        iki = Ag(kup(0, 0, 0, 10) + kup(50, 0, 0, 2)).govdeler()
        self.assertEqual(sorted(round(g.alan) for g in iki), [24, 600])

    def test_egik_cokgen(self):
        # eğik düzlemde 3-4-5 dikdörtgen: alan 5 × 2
        self.assertAlmostEqual(cokgen_alani([(0, 0, 0), (3, 0, 4), (3, 2, 4), (0, 2, 0)]), 10.0)


if __name__ == "__main__":
    unittest.main()
