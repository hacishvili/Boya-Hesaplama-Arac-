# -*- coding: utf-8 -*-
"""Profil yüzlerinin tanınması: kutu ve yuvarlak boruda dış / iç / uç; iç yüzeyin uçlardan boyanan kısmı."""
import math
import os
import shutil
import tempfile
import unittest

import ezdxf
from ezdxf.acis import api as acis
from ezdxf.render import MeshBuilder

import dxf_oku
import hesap
import profil
import test_acis as T


def kutu_boru(a=30.0, t=2.0, L=300.0, gonye=0.0):
    """a × a × t kutu profil, boy L (x ekseni boyunca); gonye: uç kesiminin eğimi (x kayması / y)."""
    mb = MeshBuilder()
    b = a / 2
    ic = b - t

    def k(x, y, z):
        return (x + gonye * y, y, z)

    def halka(r):
        return [(-r, -r), (r, -r), (r, r), (-r, r)]
    dis, ici = halka(b), halka(ic)
    for i in range(4):  # yan yüzler: dış dışa, iç içe bakar
        (y0, z0), (y1, z1) = dis[i], dis[(i + 1) % 4]
        mb.add_face([k(0, y0, z0), k(0, y1, z1), k(L, y1, z1), k(L, y0, z0)][::-1])
        (y0, z0), (y1, z1) = ici[i], ici[(i + 1) % 4]
        mb.add_face([k(0, y0, z0), k(0, y1, z1), k(L, y1, z1), k(L, y0, z0)])
    for x, ters in ((0.0, False), (L, True)):  # uç halkaları (dörder yamuk)
        for i in range(4):
            f = [k(x, *dis[i]), k(x, *dis[(i + 1) % 4]), k(x, *ici[(i + 1) % 4]), k(x, *ici[i])]
            mb.add_face(f[::-1] if ters else f)
    return mb


class Profil(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.klasor, ignore_errors=True)

    def oku(self, mb_ya_da_sat, birim=4):
        doc = ezdxf.new("R2018" if isinstance(mb_ya_da_sat, MeshBuilder) else "R2007")
        doc.header["$INSUNITS"] = birim
        k = doc.modelspace().add_3dsolid()
        if isinstance(mb_ya_da_sat, MeshBuilder):
            acis.export_dxf(k, [acis.body_from_mesh(mb_ya_da_sat)])
        else:
            k.sat = mb_ya_da_sat
        yol = os.path.join(self.klasor, "p.dxf")
        doc.saveas(yol)
        g = dxf_oku.cozumle(dxf_oku.belge_ac(yol)).govdeler
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0].hata, "")
        return g[0]

    def test_kutu_profil(self):
        g = self.oku(kutu_boru())
        p = g.profil
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p.boy, 300.0, places=6)
        self.assertAlmostEqual(p.dis, 4 * 30 * 300, places=4)
        self.assertAlmostEqual(p.ic_alan, 4 * 26 * 300, places=4)
        self.assertAlmostEqual(p.uc, 2 * (900 - 676), places=4)
        self.assertAlmostEqual(p.bosluk, 26.0, places=6)
        self.assertAlmostEqual(p.dis + p.ic_alan + p.uc, g.alan, places=4)
        # uçlardan 26 mm: iç yüzeyin 52/300'ü
        self.assertAlmostEqual(p.ic_boyanan(26.0), 4 * 26 * 52, places=4)
        self.assertAlmostEqual(p.ic_boyanan(1000.0), p.ic_alan, places=6)

    def test_gonyeli_ve_cm(self):
        p = self.oku(kutu_boru(a=3.0, t=0.2, L=30.0, gonye=1.0), birim=5).profil  # cm çizim, 45° kesim
        self.assertAlmostEqual(p.bosluk, 26.0, places=4)
        self.assertGreater(p.ic_alan, 0)
        self.assertAlmostEqual(p.uc, 2 * (900 - 676) * math.sqrt(2), places=3)  # gönyeli kesit √2 büyük

    def test_dolu_cubuk_ve_kisa_parca(self):
        from ezdxf.render import forms
        mb = forms.cube().scale(300, 20, 10)
        p = self.oku(mb).profil
        self.assertEqual(p.ic, [])
        self.assertAlmostEqual(p.uc, 2 * 200, places=6)
        self.assertAlmostEqual(p.dis, 2 * 300 * 30, places=6)
        self.assertIsNone(self.oku(forms.cube().scale(60, 40, 6)).profil)  # plaka: profil değil

    def test_yuvarlak_boru(self):
        # Ø40 × 2, boy 200 (z ekseni); silindir yüzleri iki daire döngülü (AutoCAD gibi), uçlar halka düzlem
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
        a = self.oku(g.satirlar())
        p = a.profil
        self.assertAlmostEqual(p.dis, 2 * math.pi * R * L, places=4)
        self.assertAlmostEqual(p.ic_alan, 2 * math.pi * r * L, places=4)
        self.assertAlmostEqual(p.uc, 2 * math.pi * (R * R - r * r), places=4)
        self.assertAlmostEqual(p.bosluk, 2 * r, delta=0.01)

    def test_sac_kalinligi_modelden(self):
        from ezdxf.render import forms
        g = self.oku(forms.cube().scale(100, 60, 2))
        self.assertIsNone(g.profil)
        self.assertAlmostEqual(g.sac.kalinlik, 2.0, places=9)
        self.assertAlmostEqual(g.sac.yuz, 2 * 6000, places=6)
        self.assertAlmostEqual(g.sac.kenar, 2 * 160 * 2, places=6)
        self.assertIsNone(self.oku(forms.cube().scale(50, 50, 50)).sac)  # blok: sac değil

    def test_sac_bukum_yuzleri(self):
        # 90° bükümlü sac kesitinin eş eksenli iki silindiri (r = 3 ve 5, t = 2) yüz sayılır, delik duvarı kenar
        Y = profil.YuzBilgi
        kare = lambda z: [[(0, 0, z), (10, 0, z), (10, 10, z), (0, 10, z)]]
        yuzler = [Y(100.0, kare(0), "duzlem", normal=(0, 0, 1)), Y(100.0, kare(2), "duzlem", normal=(0, 0, -1)),
                  Y(30.0, kare(0), "koni", eksen=(1, 0, 0), merkez=(0, 0, 9), r0=3.0),
                  Y(50.0, kare(0), "koni", eksen=(-1, 0, 0), merkez=(5, 0, 9), r0=5.0),
                  Y(8.0, kare(0), "koni", eksen=(0, 0, 1), merkez=(5, 5, 0), r0=1.0),
                  Y(20.0, kare(0), "duzlem", normal=(1, 0, 0))]
        s = profil.sac_coz(yuzler)
        self.assertAlmostEqual(s.kalinlik, 2.0)
        self.assertAlmostEqual(s.yuz, 280.0)
        self.assertAlmostEqual(s.kenar, 28.0)

    def test_acik_yuzey_iki_yuz(self):
        from geometri import Ag
        tek = Ag([[(0, 0, 0), (100, 0, 0), (100, 50, 0), (0, 50, 0)]])
        self.assertTrue(tek.sac_yuzeyi_mi())
        from test_geometri import kup
        delikli = Ag(kup(0, 0, 0, 100)[:5] + [[(0, 0, 100), (100, 0, 100), (100, 100, 100)]])  # küçük açıklık
        self.assertFalse(delikli.sac_yuzeyi_mi())
        self.assertFalse(Ag(kup(0, 0, 0, 10)).sac_yuzeyi_mi())

    def test_hesap_secenekleri(self):
        pr = {"boy": 300.0, "kesit": [30, 30], "dis": 36000.0, "uc": 448.0, "ic": [[31200.0, 300.0]], "bosluk": 26.0}
        k = {"tur": "3d", "alan": 67648.0, "profil": pr, "ic_boya": "uçlardan", "ic_derinlik": 30.0, "uc_boya": True}
        self.assertAlmostEqual(hesap.kaynak_alani(k), 36000 + 448 + 31200 * 60 / 300)
        k["ic_boya"] = "tamamı"
        self.assertAlmostEqual(hesap.kaynak_alani(k), 67648.0)
        k.update(ic_boya="boyanmaz", uc_boya=False)
        self.assertAlmostEqual(hesap.kaynak_alani(k), 36000.0)
        self.assertIn("iç yüzey boyanmaz", hesap.kaynak_aciklamasi(k))
        self.assertIn("uç kesitleri boyanmaz", hesap.kaynak_aciklamasi(k))


if __name__ == "__main__":
    unittest.main()
