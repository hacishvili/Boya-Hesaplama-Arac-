# -*- coding: utf-8 -*-
"""DXF okuma: örnek çizimler ezdxf ile üretilir, sonuç formülle karşılaştırılır."""
import math
import os
import shutil
import tempfile
import unittest

import ezdxf
from ezdxf.acis import api as acis
from ezdxf.render import forms

import dxf_oku


def yeni(birim=4):
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = birim
    return doc


class Iki(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.klasor, ignore_errors=True)

    def oku(self, doc, **kw):
        yol = os.path.join(self.klasor, "c.dxf")
        doc.saveas(yol)
        return dxf_oku.cozumle(dxf_oku.belge_ac(yol), **kw)

    def test_delikli_plaka_olcu_kesikli_atlanir(self):
        doc = yeni()
        m = doc.modelspace()
        for a, b in [((0, 0), (200, 0)), ((200, 0), (200, 100)), ((200, 100), (0, 100)), ((0, 100), (0, 0))]:
            m.add_line(a, b)
        for x, y in [(20, 20), (180, 20), (20, 80), (180, 80)]:
            m.add_circle((x, y), 5)
        m.add_line((100, 0), (100, 100), dxfattribs={"linetype": "DASHED"})
        m.add_linear_dim(base=(0, -20), p1=(0, 0), p2=(200, 0)).render()
        m.add_text("PARÇA 1").set_placement((10, 110))
        s = self.oku(doc)
        self.assertEqual(len(s.parcalar), 1)
        p = s.parcalar[0]
        self.assertEqual(len(p.delikler), 4)
        self.assertAlmostEqual(p.yuz_alani, 20000 - 4 * math.pi * 25, places=6)
        self.assertAlmostEqual(p.toplam_cevre, 600 + 4 * 10 * math.pi, places=6)
        self.assertEqual(s.kesikli, 1)
        self.assertEqual(s.kullanilamayan, 0)
        self.assertIn("DIMENSION", s.atlanan)

    def test_az_egik_cizgi_2b_sayilir(self):
        # 3B görünümden alınmış gibi Z'si birkaç yüzde mm oynayan çizgiler: parça yine kapanmalı
        doc = yeni()
        m = doc.modelspace()
        m.add_line((0, 0, 255.00), (200, 0, 255.04))
        m.add_line((200, 0, 255.04), (200, 100, 255.02))
        m.add_line((200, 100, 255.02), (0, 100, 255.00))
        m.add_line((0, 100, 255.00), (0, 0, 255.00))
        m.add_line((50, 0, 0), (50, 100, 100))  # gerçek 3B tel: alınmaz
        s = self.oku(doc)
        self.assertEqual(len(s.parcalar), 1)
        self.assertAlmostEqual(s.parcalar[0].yuz_alani, 20000, places=6)
        self.assertEqual(s.atlanan["3B tel çizgi"], 1)

    def test_yayli_polyline(self):
        # 100 × 60 dikdörtgen, köşeleri r = 10 yaylı (bulge)
        r, a, b = 10.0, 100.0, 60.0
        t = math.tan(math.radians(90) / 4)
        pts = [(r, 0, 0), (a - r, 0, t), (a, r, 0), (a, b - r, t), (a - r, b, 0), (r, b, t), (0, b - r, 0), (0, r, t)]
        doc = yeni()
        doc.modelspace().add_lwpolyline(pts, format="xyb", close=True)
        s = self.oku(doc)
        self.assertEqual(len(s.parcalar), 1)
        self.assertAlmostEqual(s.parcalar[0].yuz_alani, a * b - (4 - math.pi) * r * r, delta=0.05)
        self.assertAlmostEqual(s.parcalar[0].toplam_cevre, 2 * (a + b) - (8 - 2 * math.pi) * r, delta=0.01)

    def test_yay_yonleri_ve_eski_polyline(self):
        doc = yeni()
        m = doc.modelspace()
        # yarım daire uçlu yuva (kanal): 2 × 50 düz + iki yarım daire r = 10, saat yönünde çizilmiş
        m.add_lwpolyline([(0, 20, 0), (50, 20, -1), (50, 0, 0), (0, 0, -1)], format="xyb", close=True)
        # 2D POLYLINE, 3/4 daire + kiriş (bulge = tan(270°/4) > 1)
        b = math.tan(math.radians(270) / 4)
        p = m.add_polyline2d([(100, 0), (110, 10)], close=True)
        p.vertices[0].dxf.bulge = b
        s = self.oku(doc)
        alanlar = sorted(x.yuz_alani for x in s.parcalar)
        r = 10.0
        self.assertAlmostEqual(alanlar[1], 50 * 20 + math.pi * r * r, delta=0.05)  # kiriş: ≤ 0,0005 mm sehim
        rr = math.hypot(10, 10) / (2 * math.sin(math.radians(135)))
        self.assertAlmostEqual(alanlar[0], 0.75 * math.pi * rr * rr + 0.5 * rr * rr, delta=0.05)

    def test_ters_normal(self):
        # CAM programlarının sık yazdığı ters çevrilmiş (extrusion 0,0,−1) çizimler
        doc = yeni()
        m = doc.modelspace()
        m.add_lwpolyline([(0, 0, 0), (40, 0, 0), (40, 30, 1), (0, 30, 0)], format="xyb", close=True,
                         dxfattribs={"extrusion": (0, 0, -1), "elevation": 5})
        m.add_circle((10, 10), 4, dxfattribs={"extrusion": (0, 0, -1)})  # OCS: ikisi de aynalı
        s = self.oku(doc)
        self.assertEqual(len(s.parcalar), 1)
        self.assertAlmostEqual(s.parcalar[0].yuz_alani, 1200 + math.pi * 20 * 20 / 2 - math.pi * 16, delta=0.05)

    def test_birim_ve_blok(self):
        # cm çizim; blok iki kez, biri 2 kat ölçekli
        doc = yeni(5)
        blk = doc.blocks.new("P")
        blk.add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True)
        m = doc.modelspace()
        m.add_blockref("P", (0, 0))
        m.add_blockref("P", (50, 0), dxfattribs={"xscale": 2, "yscale": 2})
        s = self.oku(doc)
        self.assertEqual(s.olcek, 10.0)
        self.assertEqual(sorted(round(p.yuz_alani) for p in s.parcalar), [5000, 20000])
        s = self.oku(doc, olcek=1.0)  # kullanıcı mm dedi
        self.assertEqual(sorted(round(p.yuz_alani) for p in s.parcalar), [50, 200])

    def test_katman_haric(self):
        doc = yeni()
        m = doc.modelspace()
        m.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True, dxfattribs={"layer": "KESIM"})
        m.add_lwpolyline([(0, 0), (300, 0), (300, 200), (0, 200)], close=True, dxfattribs={"layer": "ANTET"})
        s = self.oku(doc, haric=["antet"])
        self.assertEqual([round(p.yuz_alani) for p in s.parcalar], [100])
        self.assertEqual(set(s.katmanlar), {"KESIM", "ANTET"})

    def test_tanimsiz_cizgi_tipi(self):
        doc = yeni()
        m = doc.modelspace()
        m.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True, dxfattribs={"linetype": "Solid"})
        m.add_line((0, 5), (10, 5), dxfattribs={"linetype": "HIDDEN2"})  # ikisi de tabloda tanımsız
        s = self.oku(doc)
        self.assertEqual([round(p.yuz_alani) for p in s.parcalar], [100])
        self.assertEqual(s.kesikli, 1)

    def test_birim_uyarisi(self):
        doc = yeni(6)  # m yazıyor, mm çizilmiş
        doc.modelspace().add_lwpolyline([(0, 0), (400, 0), (400, 300), (0, 300)], close=True)
        s = self.oku(doc)
        self.assertTrue(any("birimi yanlış" in u for u in s.uyarilar))
        self.assertEqual(dxf_oku.birim_uyarisi(400.0), "")


class Dwg(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp()
        self.dwg = os.path.join(self.klasor, "ayak.dwg")
        with open(self.dwg, "wb") as f:
            f.write(b"AC1032" + b"\0" * 100)

    def tearDown(self):
        shutil.rmtree(self.klasor, ignore_errors=True)

    def test_oda_yoksa_acik_uyari(self):
        eski = dict(os.environ)
        try:
            for k in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
                os.environ[k] = self.klasor
            os.environ["PATH"] = self.klasor
            with self.assertRaises(dxf_oku.DwgHatasi) as h:
                dxf_oku.belge_ac(self.dwg)
            self.assertIn(dxf_oku.ODA_INDIR, str(h.exception))
        finally:
            os.environ.clear()
            os.environ.update(eski)

    def test_oda_ile_donusturur(self):
        from ezdxf.addons import odafc
        exe = os.path.join(self.klasor, "ODA", "ODAFileConverter 26.4.0", "ODAFileConverter.exe")
        os.makedirs(os.path.dirname(exe))
        open(exe, "w").close()
        eski_ortam, eski_oku = dict(os.environ), odafc.readfile
        cagri = {}

        def sahte(yol, version=None, audit=False):
            cagri.update(yol=yol, version=version, exe=ezdxf.options.get("odafc-addon", "win_exec_path" if os.name ==
                                                                          "nt" else "unix_exec_path"))
            return yeni()
        try:
            os.environ["ProgramFiles"] = self.klasor
            self.assertEqual(dxf_oku.oda_bul(), exe)
            odafc.readfile = sahte
            doc = dxf_oku.belge_ac(self.dwg)
        finally:
            odafc.readfile = eski_oku
            os.environ.clear()
            os.environ.update(eski_ortam)
        self.assertEqual(cagri, {"yol": self.dwg, "version": "R2010", "exe": exe})
        self.assertEqual(doc.dxfversion, "AC1032")


class Uc(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.klasor, ignore_errors=True)

    def oku(self, doc):
        yol = os.path.join(self.klasor, "c.dxf")
        doc.saveas(yol)
        return dxf_oku.cozumle(dxf_oku.belge_ac(yol))

    def test_kati_kutu_mesh_3dface_polyface(self):
        doc = yeni()
        m = doc.modelspace()
        k = m.add_3dsolid()
        acis.export_dxf(k, [acis.body_from_mesh(forms.cube().scale(100, 50, 20))])
        mesh = m.add_mesh()
        with mesh.edit_data() as d:
            c = forms.cube().scale(10, 10, 10).translate(500, 0, 0)
            d.vertices, d.faces = list(c.vertices), list(c.faces)
        for f in forms.cube().scale(2, 2, 2).translate(900, 0, 0).faces_as_vertices():
            m.add_3dface(f)
        for f in forms.cube().scale(3, 3, 3).translate(1200, 0, 0).faces_as_vertices():
            m.add_3dface(f)
        pf = m.add_polyface()
        pf.append_faces(list(forms.cube().scale(4, 4, 4).translate(1500, 0, 0).faces_as_vertices()))
        s = self.oku(doc)
        alanlar = sorted(round(g.alan, 6) for g in s.govdeler)
        self.assertEqual(alanlar, [24.0, 54.0, 96.0, 600.0, 16000.0])
        self.assertTrue(all(g.kapali and not g.hata for g in s.govdeler))
        self.assertEqual(s.parcalar, [])


if __name__ == "__main__":
    unittest.main()
