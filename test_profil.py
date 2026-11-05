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


def delikli_plaka(delikler, A=100.0, B=60.0, H=5.0):
    """A × B × H sac; delikler: (x, y, tür) — "duz" Ø8; "havsa" Ø6 + 90° havşa Ø12 (2 mm derin);
    "kademe" Ø6 + Ø12 silindirik kademe (3 mm derin, araya düz halka)."""
    g = T.Govde()
    k = [g.kose((x, y, z)) for z in (0, H) for x, y in ((0, 0), (A, 0), (A, B), (0, B))]
    p = [(0, 0), (A, 0), (A, B), (0, B)]

    def dogru(i, j):
        a, b = (*p[i % 4], 0 if i < 4 else H), (*p[j % 4], 0 if j < 4 else H)
        d = [b[t] - a[t] for t in range(3)]
        L = math.sqrt(sum(x * x for x in d))
        return g.kenar(k[i], 0, k[j], L, g.dogru(a, [x / L for x in d]))
    alt = [dogru(i, (i + 1) % 4) for i in range(4)]
    ust = [dogru(4 + i, 4 + (i + 1) % 4) for i in range(4)]
    dik = [dogru(i, 4 + i) for i in range(4)]

    def daire(x, y, z, r):
        v = g.kose((x + r, y, z))
        return g.kenar(v, 0, v, T.TAM, g.daire((x, y, z), (0, 0, 1), (r, 0, 0)))
    ust_d, alt_d = [[(e, False) for e in ust]], [[(e, True) for e in alt[::-1]]]
    yuzler = []

    def prizma(parcalar):
        """Boydan boya kesik: parcalar ("dogru", p0, p1) ya da ("yay", merkez, r, a0, a1) (radyan)."""
        bas = [pr[1] if pr[0] == "dogru" else (pr[1][0] + pr[2] * math.cos(pr[3]), pr[1][1] + pr[2] * math.sin(pr[3]))
               for pr in parcalar]
        vk = {z: [g.kose((x_, y_, z)) for x_, y_ in bas] for z in (0.0, H)}
        dik_ = [g.kenar(vk[0.0][i], 0, vk[H][i], H, g.dogru((*bas[i], 0.0), (0, 0, 1))) for i in range(len(bas))]
        kat = {}
        for z in (0.0, H):
            kat[z] = []
            for i, pr in enumerate(parcalar):
                j = (i + 1) % len(parcalar)
                if pr[0] == "dogru":
                    d = (pr[2][0] - pr[1][0], pr[2][1] - pr[1][1])
                    L = math.hypot(*d)
                    kat[z].append(g.kenar(vk[z][i], 0, vk[z][j], L, g.dogru((*pr[1], z), (d[0] / L, d[1] / L, 0))))
                else:
                    kat[z].append(g.kenar(vk[z][i], pr[3], vk[z][j], pr[4],
                                          g.daire((*pr[1], z), (0, 0, 1), (pr[2], 0, 0))))
        for i, pr in enumerate(parcalar):
            j = (i + 1) % len(parcalar)
            if pr[0] == "dogru":
                d = (pr[2][0] - pr[1][0], pr[2][1] - pr[1][1])
                yz = T.duzlem(g, (*pr[1], 0), (d[1], -d[0], 0), (d[0], d[1], 0))
            else:
                yz = T.koni(g, (*pr[1], 0), (0, 0, 1), (pr[2], 0, 0))
            yuzler.append((yz, [[(kat[0.0][i], False), (dik_[j], False), (kat[H][i], True), (dik_[i], True)]]))
        ust_d.append([(e, True) for e in kat[H][::-1]])
        alt_d.append([(e, False) for e in kat[0.0]])

    for x, y, tur in delikler:
        if tur in ("kanal", "dikdortgen", "ucgen"):
            if tur == "kanal":  # 30 × 8
                prizma([("dogru", (x - 11, y - 4), (x + 11, y - 4)), ("yay", (x + 11, y), 4, -math.pi / 2, math.pi / 2),
                        ("dogru", (x + 11, y + 4), (x - 11, y + 4)), ("yay", (x - 11, y), 4, math.pi / 2, 1.5 * math.pi)])
            elif tur == "dikdortgen":  # 20 × 10
                c_ = [(x - 10, y - 5), (x + 10, y - 5), (x + 10, y + 5), (x - 10, y + 5)]
                prizma([("dogru", c_[i], c_[(i + 1) % 4]) for i in range(4)])
            else:
                c_ = [(x - 6, y - 4), (x + 6, y - 4), (x, y + 6)]
                prizma([("dogru", c_[i], c_[(i + 1) % 3]) for i in range(3)])
            continue
        if tur == "elips":  # 20 × 10
            va, vb = g.kose((x + 10, y, H)), g.kose((x + 10, y, 0))
            a = g.kenar(va, 0, va, T.TAM, g.daire((x, y, H), (0, 0, 1), (10, 0, 0), 0.5))
            b = g.kenar(vb, 0, vb, T.TAM, g.daire((x, y, 0), (0, 0, 1), (10, 0, 0), 0.5))
            yz = g.s.ekle("cone-surface", float(x), float(y), 0.0, 0.0, 0.0, 1.0, 10.0, 0.0, 0.0, 0.5, "I", "I", 0.0,
                          1.0, 10.0, "forward", "I", "I", "I", "I")
            yuzler.append((yz, [[(a, False)], [(b, True)]]))
            ust_d.append([(a, True)])
            alt_d.append([(b, False)])
            continue
        if tur == "duz":
            a, b = daire(x, y, H, 4), daire(x, y, 0, 4)
            yuzler.append((T.koni(g, (x, y, 0), (0, 0, 1), (4, 0, 0)), [[(a, False)], [(b, True)]]))
        elif tur == "havsa":
            a, m, b = daire(x, y, H, 6), daire(x, y, H - 3, 3), daire(x, y, 0, 3)
            yuzler.append((T.koni(g, (x, y, H - 3), (0, 0, 1), (3, 0, 0), egim=1.0), [[(a, False)], [(m, True)]]))
            yuzler.append((T.koni(g, (x, y, 0), (0, 0, 1), (3, 0, 0)), [[(m, False)], [(b, True)]]))
        else:
            a, m6, m3, b = daire(x, y, H, 6), daire(x, y, H - 3, 6), daire(x, y, H - 3, 3), daire(x, y, 0, 3)
            yuzler.append((T.koni(g, (x, y, 0), (0, 0, 1), (6, 0, 0)), [[(a, False)], [(m6, True)]]))
            yuzler.append((T.duzlem(g, (x, y, H - 3), (0, 0, 1), (1, 0, 0)), [[(m6, False)], [(m3, True)]]))
            yuzler.append((T.koni(g, (x, y, 0), (0, 0, 1), (3, 0, 0)), [[(m3, False)], [(b, True)]]))
        ust_d.append([(a, True)])
        alt_d.append([(b, False)])
    g.yuz(T.duzlem(g, (0, 0, H), (0, 0, 1), (1, 0, 0)), ust_d)
    g.yuz(T.duzlem(g, (0, 0, 0), (0, 0, -1), (1, 0, 0)), alt_d)
    for i in range(4):
        d = (p[(i + 1) % 4][0] - p[i][0], p[(i + 1) % 4][1] - p[i][1], 0)
        g.yuz(T.duzlem(g, (*p[i], 0), (d[1], -d[0], 0), d),
              [[(alt[i], False), (dik[(i + 1) % 4], False), (ust[i], True), (dik[i], True)]])
    for yz, dl in yuzler:
        g.yuz(yz, dl, ters=True)  # delik yüzlerinin normali eksene doğru
    return g.satirlar()


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
        self.assertAlmostEqual(p.kesit_alani, 900 - 676, places=4)  # ağırlık: metal kesiti × boy
        k = {"tur": "3d", "alan": g.alan, "profil": p.sozluk()}
        self.assertAlmostEqual(hesap.kaynak_hacmi(k), 224 * 300, places=2)

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
        self.assertAlmostEqual(p.kesit_alani, math.pi * (R * R - r * r), delta=1e-3 * math.pi * (R * R - r * r))

    def test_sac_kalinligi_modelden(self):
        from ezdxf.render import forms
        g = self.oku(forms.cube().scale(100, 60, 2))
        self.assertIsNone(g.profil)
        self.assertAlmostEqual(g.sac.kalinlik, 2.0, places=9)
        self.assertAlmostEqual(g.sac.yuz, 2 * 6000, places=6)
        self.assertAlmostEqual(g.sac.kenar, 2 * 160 * 2, places=6)
        self.assertAlmostEqual(hesap.kaynak_hacmi({"tur": "3d", "sac": g.sac.sozluk()}), 100 * 60 * 2, places=6)
        self.assertIsNone(self.oku(forms.cube().scale(50, 50, 50)).sac)  # blok: sac değil

    def test_delik_ve_havsa(self):
        g = self.oku(delikli_plaka([(20, 20, "havsa"), (40, 20, "havsa"), (60, 30, "duz"), (80, 40, "kademe")]))
        self.assertIsNotNone(g.sac)
        ozet = profil.delik_ozeti([d.sozluk() for d in g.delikler])
        self.assertEqual(ozet, [(1, "Ø8"), (2, "Ø6 havşa Ø12 × 90°"), (1, "Ø6 kademe Ø12")])
        duz = next(d for d in g.delikler if abs(d.cap - 8) < 1e-6)
        self.assertAlmostEqual(duz.duvar, math.pi * 8 * 5, delta=1e-3)
        hv = next(d for d in g.delikler if d.havsa_aci)
        self.assertAlmostEqual(hv.duvar, math.pi * 6 * 2, delta=1e-3)                 # yalnız silindir
        self.assertAlmostEqual(hv.alan - hv.duvar, math.pi * (6 + 3) * 3 * math.sqrt(2), delta=1e-3)  # koni
        self.assertGreater(len(g.ag.vurgu), 0)
        k = {"tur": "3d", "alan": g.alan, "sac": g.sac.sozluk(), "delikler": [d.sozluk() for d in g.delikler]}
        self.assertIn("4 delik (3 havşalı)", hesap.kaynak_aciklamasi(k))
        tam = hesap.kaynak_alani(k)
        k["delik_ici_boyanmaz"] = True
        self.assertAlmostEqual(tam - hesap.kaynak_alani(k), sum(d.duvar for d in g.delikler), places=6)

    def test_kanal_elips_ve_kesikler(self):
        g = self.oku(delikli_plaka([(25, 15, "kanal"), (75, 15, "kanal"), (25, 45, "elips"), (75, 45, "dikdortgen"),
                                    (50, 30, "ucgen"), (50, 50, "duz")], A=100.0, B=60.0))
        ozet = dict((m, n) for n, m in profil.delik_ozeti([d.sozluk() for d in g.delikler]))
        serbest = [m for m in ozet if m.startswith("serbest kesik")]
        self.assertEqual(len(serbest), 1)
        self.assertIn("(çevre 35,3)", serbest[0])  # üçgen: taban 12, yükseklik 10
        del ozet[serbest[0]]
        self.assertEqual(ozet, {"Ø8": 1, "kanal 30 × 8": 2, "elips 20 × 10": 1, "dikdörtgen 20 × 10": 1})
        kanal = next(d for d in g.delikler if d.tur == "kanal")
        self.assertAlmostEqual(kanal.duvar, (2 * 22 + math.pi * 8) * 5, delta=1e-3)
        elips = next(d for d in g.delikler if d.tur == "elips")
        cevre = 4 * 10 * 1.2110560275684594  # elips çevresi a = 10, b = 5 (E(e), e² = 0,75)
        self.assertAlmostEqual(elips.duvar, cevre * 5, delta=1e-3)
        # plaka alanı: iki yüz − ağızlar + bütün duvarlar + dış kenar
        agiz = 2 * (22 * 8 + math.pi * 16) + math.pi * 50 + 200 + 60 + math.pi * 16
        duvar = sum(d.duvar for d in g.delikler)
        self.assertAlmostEqual(g.alan, 2 * (6000 - agiz) + duvar + 320 * 5, delta=1e-2)
        k = {"tur": "3d", "alan": g.alan, "delikler": [d.sozluk() for d in g.delikler]}
        self.assertIn("1 delik, 2 kanal, 1 elips, 1 dikdörtgen kesik, 1 serbest kesik", hesap.kaynak_aciklamasi(k))

    def test_deliksiz_govdede_delik_yok(self):
        from ezdxf.render import forms
        self.assertEqual(self.oku(forms.cube().scale(100, 60, 2)).delikler, [])
        g = self.oku(kutu_boru())
        self.assertEqual(g.delikler, [])

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
