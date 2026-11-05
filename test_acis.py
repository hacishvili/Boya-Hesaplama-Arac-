# -*- coding: utf-8 -*-
"""ACIS katı alanları: test gövdeleri AutoCAD'in yazdığı SAT düzeninde (ASM 226) burada üretilir, alan formülle
karşılaştırılır. Döngü yönleri ACIS kuralıyla: yüze dışarıdan bakınca saat tersi."""
import math
import os
import shutil
import tempfile
import unittest

import ezdxf
from ezdxf.acis import api as acis
from ezdxf.render import forms

import acis_alan
import dxf_oku

TAM = 2 * math.pi


class P(int):
    """SAT işaretçisi."""


class Sat:
    def __init__(self):
        self.r = []

    def ekle(self, ad, *alan, desen=True):
        self.r.append([ad, list(alan), desen])
        return P(len(self.r) - 1)

    def doldur(self, i, *alan):
        self.r[i][1] = list(alan)

    def satirlar(self):
        out = [f"21200 {len(self.r)} 1 0", "16 Autodesk AutoCAD 20 ASM 226.0.0.65535 NT 0",
               "1 9.999999999999999547e-07 1.000000000000000036e-10"]
        for ad, alan, desen in self.r:
            ogeler = []
            for x in alan:
                if isinstance(x, P):
                    ogeler.append(f"${int(x)}")
                elif x is None:
                    ogeler.append("$-1")
                elif isinstance(x, float):
                    ogeler.append(repr(x))
                else:
                    ogeler.append(str(x))
            out.append(f"{ad} $-1 -1 " + ("$-1 " if desen else "") + " ".join(ogeler) + " #")
        return out


class Govde:
    """Tek gövde, tek kabuk: yüzler kenar listeleriyle verilir; coedge eşleri kendiliğinden bağlanır."""

    def __init__(self, donusum=None):
        self.s = Sat()
        self.s.ekle("asmheader", "@13", "226.0.0.65535", desen=False)
        self.body = self.s.ekle("body")
        self.lump = self.s.ekle("lump")
        self.shell = self.s.ekle("shell")
        self.tr = self.s.ekle("transform", *donusum) if donusum else None
        self.yuzler = []
        self.kenar_coedge = {}

    def kose(self, p):
        nokta = self.s.ekle("point", *map(float, p))
        return self.s.ekle("vertex", None, 0, nokta)  # kenar sonra; ASM 226 sayaç alanı (ezdxf'in okuyamadığı)

    def daire(self, c, n, M, oran=1.0):
        return self.s.ekle("ellipse-curve", *map(float, c), *map(float, n), *map(float, M), float(oran), "I", "I")

    def dogru(self, o, d):
        return self.s.ekle("straight-curve", *map(float, o), *map(float, d), "I", "I")

    def kenar(self, v0, t0, v1, t1, egri, ters=False):
        e = self.s.ekle("edge", v0, float(t0), v1, float(t1), None, egri, "reversed" if ters else "forward",
                        "@7", "unknown")
        self.kenar_coedge[e] = []
        for v in (v0, v1):
            ad, alan, d = self.s.r[v]
            alan[0] = e
        return e

    def yuz(self, yuzey, donguler, ters=False):
        self.yuzler.append((yuzey, donguler, ters))

    def satirlar(self):
        s = self.s
        face_ids = [s.ekle("face") for _ in self.yuzler]
        for fi, (yuzey, donguler, ters) in zip(face_ids, self.yuzler):
            loop_ids = [s.ekle("loop") for _ in donguler]
            for li, dongu in zip(loop_ids, donguler):
                co = [s.ekle("coedge") for _ in dongu]
                for j, (e, cters) in enumerate(dongu):
                    self.kenar_coedge[e].append(co[j])
                    s.doldur(co[j], co[(j + 1) % len(co)], co[j - 1], None, e, "reversed" if cters else "forward",
                             li, None)
                nxt = loop_ids[loop_ids.index(li) + 1] if loop_ids.index(li) + 1 < len(loop_ids) else None
                s.doldur(li, nxt, co[0], fi)
            if not donguler:
                loop_ids = [None]
            nf = face_ids[face_ids.index(fi) + 1] if face_ids.index(fi) + 1 < len(face_ids) else None
            s.doldur(fi, nf, loop_ids[0], self.shell, None, yuzey, "reversed" if ters else "forward", "single")
        for e, cos in self.kenar_coedge.items():
            if cos:
                s.r[e][1][4] = cos[0]
            if len(cos) == 2:
                s.r[cos[0]][1][2] = cos[1]
                s.r[cos[1]][1][2] = cos[0]
        s.doldur(self.body, self.lump, None, self.tr)
        s.doldur(self.lump, None, self.shell, self.body)
        s.doldur(self.shell, None, None, face_ids[0], None, self.lump)
        return s.satirlar()


def duzlem(g, o, n, u):
    return g.s.ekle("plane-surface", *map(float, o), *map(float, n), *map(float, u), "forward_v", "I", "I", "I", "I")


def koni(g, c, a, M, egim=0.0):
    sn, cs = math.sin(math.atan(egim)), math.cos(math.atan(egim))
    return g.s.ekle("cone-surface", *map(float, c), *map(float, a), *map(float, M), 1.0, "I", "I", sn, cs,
                    float(math.hypot(*M)), "forward", "I", "I", "I", "I")


def silindir(r, z0, z1, merkez_z=0.0, donusum=None, egim=0.0):
    """z0 → z1 arası dönel gövde (egim ≠ 0: kesik koni, ρ = r + egim (z − merkez_z))."""
    g = Govde(donusum)
    r0 = r + egim * (z0 - merkez_z)
    r1 = r + egim * (z1 - merkez_z)
    vb, vt = g.kose((r0, 0, z0)), g.kose((r1, 0, z1))
    eb = g.kenar(vb, 0, vb, TAM, g.daire((0, 0, z0), (0, 0, 1), (r0, 0, 0)))
    et = g.kenar(vt, 0, vt, TAM, g.daire((0, 0, z1), (0, 0, 1), (r1, 0, 0)))
    g.yuz(duzlem(g, (0, 0, z1), (0, 0, 1), (1, 0, 0)), [[(et, False)]])
    g.yuz(duzlem(g, (0, 0, z0), (0, 0, -1), (1, 0, 0)), [[(eb, True)]])
    g.yuz(koni(g, (0, 0, merkez_z), (0, 0, 1), (r, 0, 0), egim), [[(et, True)], [(eb, False)]])
    return g


def dxf_kati(klasor, satirlar_listesi, ad="k.dxf"):
    doc = ezdxf.new("R2007")
    doc.header["$INSUNITS"] = 4
    for satirlar in satirlar_listesi:
        doc.modelspace().add_3dsolid().sat = satirlar
    yol = os.path.join(klasor, ad)
    doc.saveas(yol)
    return dxf_oku.cozumle(dxf_oku.belge_ac(yol))


class Acis(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.klasor, ignore_errors=True)

    def tek(self, g):
        s = dxf_kati(self.klasor, [g.satirlar()])
        self.assertEqual(len(s.govdeler), 1)
        self.assertEqual(s.govdeler[0].hata, "")
        return s.govdeler[0]

    def test_silindir_ekseni_kaydirilmis(self):
        # koni merkezi parçanın dışında (AutoCAD böyle yazar): iki döngü de katkı verir, yönler sınanır
        g = self.tek(silindir(10, 20, 50, merkez_z=-37.5))
        self.assertAlmostEqual(g.alan, 2 * math.pi * 100 + TAM * 10 * 30, places=6)
        self.assertTrue(g.kapali)

    def test_kesik_koni_ve_egim_yonu(self):
        # alt r = 20 (z = 0), üst r = 10 (z = 40)
        for egim_isareti in (1, -1):  # dosyadaki sin işaretinden bağımsız: ölçülen yarıçapla belirlenir
            g = silindir(20, 0, 40, merkez_z=0, egim=-0.25)
            kayit = [r for r in g.s.r if r[0] == "cone-surface"][0]
            kayit[1][12] *= egim_isareti  # sin
            a = self.tek(g)
            s = math.hypot(40, 10)
            self.assertAlmostEqual(a.alan, math.pi * (20 + 10) * s + math.pi * (400 + 100), places=5)

    def test_sivri_koni(self):
        # tepe z = 40'ta (ρ = 0), taban r = 20: yan yüzün tek döngüsü var
        g = Govde()
        vb = g.kose((20, 0, 0))
        eb = g.kenar(vb, 0, vb, TAM, g.daire((0, 0, 0), (0, 0, 1), (20, 0, 0)))
        g.yuz(duzlem(g, (0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(eb, True)]])
        g.yuz(koni(g, (0, 0, 0), (0, 0, 1), (20, 0, 0), -0.5), [[(eb, False)]])
        a = self.tek(g)
        self.assertAlmostEqual(a.alan, math.pi * 20 * math.hypot(20, 40) + math.pi * 400, places=5)

    def test_kure_tam_ve_yarim(self):
        g = Govde()
        g.yuz(g.s.ekle("sphere-surface", 0.0, 0.0, 0.0, 15.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, "forward_v",
                       "I", "I", "I", "I"), [])
        self.assertAlmostEqual(self.tek(g).alan, 4 * math.pi * 225, places=6)
        for kuzey in (True, False):
            g = Govde()
            R = 15.0
            v = g.kose((R, 0, 0))
            e = g.kenar(v, 0, v, TAM, g.daire((0, 0, 0), (0, 0, 1), (R, 0, 0)))
            kure = g.s.ekle("sphere-surface", 0.0, 0.0, 0.0, R, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, "forward_v",
                            "I", "I", "I", "I")
            # kuzey yarım küre: ekvator döngüsü üstten bakınca saat tersi; taban diski aşağı bakar
            g.yuz(kure, [[(e, not kuzey)]])
            g.yuz(duzlem(g, (0, 0, 0), (0, 0, -1 if kuzey else 1), (1, 0, 0)), [[(e, kuzey)]])
            self.assertAlmostEqual(self.tek(g).alan, 2 * math.pi * R * R + math.pi * R * R, places=5)

    def test_torus_dirsek(self):
        # 90° boru dirseği: eksen yarıçapı 50, boru yarıçapı 10; uçları düz disk
        g = Govde()
        v0, v1 = g.kose((60, 0, 0)), g.kose((0, 60, 0))
        e0 = g.kenar(v0, 0, v0, TAM, g.daire((50, 0, 0), (0, 1, 0), (10, 0, 0)))
        e1 = g.kenar(v1, 0, v1, TAM, g.daire((0, 50, 0), (1, 0, 0), (0, 10, 0)))
        tor = g.s.ekle("torus-surface", 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 50.0, 10.0, 1.0, 0.0, 0.0, "forward_v",
                       "I", "I", "I", "I")
        g.yuz(tor, [[(e0, False)], [(e1, True)]])
        g.yuz(duzlem(g, (50, 0, 0), (0, -1, 0), (1, 0, 0)), [[(e0, True)]])
        g.yuz(duzlem(g, (0, 50, 0), (-1, 0, 0), (0, 1, 0)), [[(e1, False)]])
        a = self.tek(g)
        self.assertAlmostEqual(a.alan, (math.pi / 2) * TAM * 10 * 50 + 2 * math.pi * 100, places=4)

    def kare_yuz(self, g, yuzey, a, z=0.0):
        """a × a kare döngü (doğrularla)."""
        k = [g.kose((0, 0, z)), g.kose((a, 0, z)), g.kose((a, a, z)), g.kose((0, a, z))]
        d = [(1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0)]
        kenar = [g.kenar(k[i], 0, k[(i + 1) % 4], a, g.dogru(g.s.r[g.s.r[k[i]][1][2]][1], d[i])) for i in range(4)]
        g.yuz(yuzey, [[(e, False) for e in kenar]])
        return kenar

    def test_delikli_duzlem_yonu_bozuk_da_olsa(self):
        for delik_ters in (True, False):  # False: bozuk dosya, delik dış döngüyle aynı yönde
            g = Govde()
            yz = duzlem(g, (0, 0, 0), (0, 0, 1), (1, 0, 0))
            self.kare_yuz(g, yz, 40.0)
            v = g.kose((25, 20, 0))
            e = g.kenar(v, 0, v, TAM, g.daire((20, 20, 0), (0, 0, 1), (5, 0, 0)))
            g.yuzler[-1][1].append([(e, delik_ters)])
            a = dxf_kati(self.klasor, [g.satirlar()]).govdeler[0]
            self.assertAlmostEqual(a.alan, 1600 - math.pi * 25, places=6)
            self.assertFalse(a.kapali)  # tek yüz: kabuk açık

    def spline(self, g, a, derece_v=1):
        """a × a düz kare, B-spline yüzey (u: 1. derece, v: derece_v, kontrol noktaları u en hızlı)."""
        nv = derece_v + 1
        pts = []
        for j in range(nv):
            for i in range(2):
                pts += [float(i * a), float(j * a / derece_v), 0.0]
        return g.s.ekle("spline-surface", "forward", "{", "exact_spl_sur", 22600, "full", "nubs", 1, derece_v,
                        "open", "open", "none", "none", 2, 2, 0.0, 1, 1.0, 1, 0.0, derece_v, 1.0, derece_v, *pts,
                        "}", "I", "I", "I", "I")

    def test_sat_sert_bolunmus_satirlar(self):
        """Kayıtları 80 karakterde (sayı ortasından) bölünmüş SAT: sayı ikiye ayrılmadan okunur."""
        tam = silindir(10.0, 0.0, 30.0, egim=0.3).satirlar()
        bas, govde = list(tam[:3]), "".join(tam[3:])
        bol = [govde[i:i + 80] for i in range(0, len(govde), 80)]
        self.assertTrue(any(c[-1].isdigit() and n[0].isdigit() for c, n in zip(bol, bol[1:])))  # sayı bölünmüş
        a = dxf_kati(self.klasor, [tam]).govdeler[0]
        b = dxf_kati(self.klasor, [bas + bol], "bolunmus.dxf").govdeler[0]
        self.assertEqual(b.hata, "")
        self.assertAlmostEqual(b.alan, a.alan, places=6)
        # kayıt sonunda biten (normal) çok satırlı kayıt: satırlar boşlukla birleşir
        self.assertEqual(acis_alan.sat_satirlari(["1 2 3", "x", "y", "a 1", "2 #", "b #"])[3:], ["a 1 2 #", "b #"])

    def test_neredeyse_dairesel_koni(self):
        """Oranı 0,99998 olan koni (CAD artığı) daire sayılır; gerçekten eliptik koni hata verir."""
        for oran, hata in ((0.99998, ""), (0.9, "eliptik koni")):
            g = silindir(10.0, 0.0, 30.0, egim=0.3)
            [r for r in g.s.r if r[0] == "cone-surface"][0][1][9] = oran
            gv = dxf_kati(self.klasor, [g.satirlar()], f"k{oran}.dxf").govdeler[0]
            if hata:
                self.assertIn(hata, gv.hata)
            else:
                self.assertEqual(gv.hata, "")
                r0, r1 = 10.0, 10.0 + 0.3 * 30
                yan = math.pi * (r0 + r1) * math.hypot(30, r1 - r0) * (1 + oran) / 2
                self.assertAlmostEqual(gv.alan, yan + math.pi * (r0 ** 2 + r1 ** 2), delta=1e-3 * gv.alan)

    def test_spline_tam_ve_kirpilmis(self):
        for dv in (1, 3):
            g = Govde()
            self.kare_yuz(g, self.spline(g, 10.0, dv), 10.0)
            self.assertAlmostEqual(self.tek(g).alan, 100.0, places=6)
        g = Govde()
        self.kare_yuz(g, self.spline(g, 10.0), 5.0)  # kırpılmış: döngü yüzeyin yalnız bir kısmını alıyor
        self.assertAlmostEqual(self.tek(g).alan, 25.0, places=6)
        g = Govde()
        self.kare_yuz(g, self.spline(g, 10.0), 5.0, z=1.0)  # döngü yüzeyin üzerinde değil
        s = dxf_kati(self.klasor, [g.satirlar()])
        self.assertIn("tanınmayan spline yüz (exact_spl_sur)", s.govdeler[0].hata)
        self.assertEqual(s.govdeler[0].alan, 0.0)

    def test_kirpilmis_spline_boru(self):
        """Rasyonel B-spline silindir (u periyodik, z 0–50); yüz z = 10 ile z = 40 arasındaki çemberlerle kırpılmış:
        dolanan döngüler, dikiş kenarı yok."""
        r, w = 8.0, math.sqrt(0.5)
        halka = [(r, 0, 1), (r, r, w), (0, r, 1), (-r, r, w), (-r, 0, 1), (-r, -r, w), (0, -r, 1), (r, -r, w),
                 (r, 0, 1)]
        pts = []
        for z in (0.0, 50.0):
            for x, y, ag in halka:
                pts += [x, y, z, ag]
        g = Govde()
        yz = g.s.ekle("spline-surface", "forward", "{", "exact_spl_sur", 22600, "full", "nurbs", 2, 1,
                      "periodic", "open", "none", "none", 5, 2, 0.0, 2, 0.25, 2, 0.5, 2, 0.75, 2, 1.0, 2,
                      0.0, 1, 1.0, 1, *pts, "}", "I", "I", "I", "I")
        alt, ust = g.kose((r, 0, 10)), g.kose((r, 0, 40))
        e1 = g.kenar(alt, 0, alt, TAM, g.daire((0, 0, 10), (0, 0, 1), (r, 0, 0)))
        e2 = g.kenar(ust, 0, ust, TAM, g.daire((0, 0, 40), (0, 0, 1), (r, 0, 0)))
        g.yuz(yz, [[(e1, False)], [(e2, True)]])
        self.assertAlmostEqual(self.tek(g).alan, 2 * math.pi * r * 30, delta=1e-4 * 2 * math.pi * r * 30)

    def test_donusum_ve_olcek(self):
        c, sn = math.cos(0.7), math.sin(0.7)
        dondur = (c, sn, 0.0, -sn, c, 0.0, 0.0, 0.0, 1.0, 100.0, -50.0, 7.0, 1.0, "rotate", "no_reflect", "no_shear")
        a = self.tek(silindir(10, 20, 50, merkez_z=-5, donusum=dondur))
        self.assertAlmostEqual(a.alan, 2 * math.pi * 100 + TAM * 10 * 30, places=6)
        (x0, y0, z0), (x1, y1, z1) = a.ag.kutu()
        self.assertAlmostEqual(z1 - z0, 30.0, places=6)
        self.assertAlmostEqual((x0 + x1) / 2, 100.0, places=3)
        iki = (2.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 2.0, "no_rotate", "no_reflect", "no_shear")
        a = self.tek(silindir(10, 20, 50, donusum=iki))
        self.assertAlmostEqual(a.alan, 4 * (2 * math.pi * 100 + TAM * 10 * 30), places=5)

    def test_desteklenmeyen_yuzey_eksik_alan_vermez(self):
        g = silindir(10, 0, 30)
        kayit = [r for r in g.s.r if r[0] == "cone-surface"][0]
        kayit[0] = "rot_spl-surface"
        a = dxf_kati(self.klasor, [g.satirlar()]).govdeler[0]
        self.assertIn("3 yüzden 1 tanesi", a.hata)
        self.assertEqual(a.alan, 0.0)

    def test_sab_ikili(self):
        # DXF R2013+ ACIS'i ikili (SAB) yazar; düz yüzlü gövde ezdxf ile
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 4
        k = doc.modelspace().add_3dsolid()
        acis.export_dxf(k, [acis.body_from_mesh(forms.cube().scale(100, 50, 20))])
        yol = os.path.join(self.klasor, "sab.dxf")
        doc.saveas(yol)
        s = dxf_oku.cozumle(dxf_oku.belge_ac(yol))
        self.assertEqual(s.govdeler[0].hata, "")
        self.assertAlmostEqual(s.govdeler[0].alan, 16000.0, places=6)

    def test_birim_olcegi(self):
        g = silindir(1, 2, 5)  # cm
        doc = ezdxf.new("R2007")
        doc.header["$INSUNITS"] = 5
        doc.modelspace().add_3dsolid().sat = g.satirlar()
        yol = os.path.join(self.klasor, "cm.dxf")
        doc.saveas(yol)
        a = dxf_oku.cozumle(dxf_oku.belge_ac(yol)).govdeler[0]
        self.assertAlmostEqual(a.alan, 100 * (2 * math.pi + TAM * 3), places=5)


if __name__ == "__main__":
    unittest.main()
