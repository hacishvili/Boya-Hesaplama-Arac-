# -*- coding: utf-8 -*-
"""Pencereler ekransız (offscreen) açılır: içe aktarma, kalıp, ayrıntı düzenleme, PDF."""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ezdxf
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import pencere  # noqa: E402
from hesap import kalem_sonucu  # noqa: E402


class Arayuz(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp()
        os.environ["APPDATA"] = self.klasor  # kullanıcının gerçek ayarlarına dokunma

    def tearDown(self):
        shutil.rmtree(self.klasor, ignore_errors=True)

    def test_ice_aktar_ve_duzenle(self):
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 4
        m = doc.modelspace()
        m.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
        m.add_lwpolyline([(200, 0), (210, 0), (210, 10), (200, 10)], close=True)
        yol = os.path.join(self.klasor, "iki.dxf")
        doc.saveas(yol)
        w = pencere.AnaPencere()
        d = pencere.IceAktar(yol, w.ayar.tozlar[0].ad, w)
        self.assertEqual(d.tablo.rowCount(), 2)
        d.kalinlik.setValue(2.0)
        d.tablo.item(1, 0).setCheckState(pencere.Qt.Unchecked)
        yeni = d.kalemler()
        self.assertEqual(len(yeni), 1)
        self.assertAlmostEqual(yeni[0].kaynak["kalinlik"], 2.0)
        w.kalemler.extend(yeni)
        w._yenile(0)
        self.assertAlmostEqual(kalem_sonucu(w.kalemler[0], w.ayar).alan_m2, (2 * 5000 + 300 * 2) / 1e6)
        w._guncelle(0, adet=7)
        self.assertEqual(w.tablo.item(0, 2).text(), "7")
        w._kaynak(0, yuz_sayisi=1, kenar=False)
        self.assertEqual(w.tablo.item(0, 3).text(), "0,0050")
        pdf = os.path.join(self.klasor, "r.pdf")
        pencere.pdf_yaz(pdf, w.kalemler, w.ayar, "deneme")
        self.assertGreater(os.path.getsize(pdf), 1000)
        w.cogalt()
        self.assertEqual(len(w.kalemler), 2)
        w.degisti = False
        w.close()

    def test_parca_basina_sac_kalinligi(self):
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 4
        m = doc.modelspace()
        m.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
        m.add_lwpolyline([(200, 0), (210, 0), (210, 10), (200, 10)], close=True)
        yol = os.path.join(self.klasor, "iki.dxf")
        doc.saveas(yol)
        d = pencere.IceAktar(yol, "Polyester")
        d.kalinlik.setValue(2.0)                    # tümüne
        satir = {round(g.dis.alan): r for r, (_, g, *_) in enumerate(d.ogeler)}
        d.tablo.cellWidget(satir[100], 3).setValue(5.0)  # yalnız küçük parça
        k = {round(x.kaynak["yuz_alani"]): x.kaynak["kalinlik"] for x in d.kalemler()}
        self.assertEqual(k, {5000: 2.0, 100: 5.0})
        self.assertEqual(d.tablo.item(satir[100], 4).text(), "0,0004")  # 2 × 100 + 40 × 5 mm²
        d.kesikli.setChecked(True)                  # yeniden okuma: girilen kalınlıklar korunur
        k = {round(x.kaynak["yuz_alani"]): x.kaynak["kalinlik"] for x in d.kalemler()}
        self.assertEqual(k, {5000: 2.0, 100: 5.0})

    def test_ayni_parcalar_toplanir(self):
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 4
        m = doc.modelspace()
        for x in (0, 300, 600):  # üç aynı plaka (biri döndürülmüş)
            m.add_lwpolyline([(x, 0), (x + 100, 0), (x + 100, 50), (x, 50)], close=True)
        m.add_lwpolyline([(900, 0), (950, 0), (950, 100), (900, 100)], close=True)
        m.add_lwpolyline([(0, 200), (10, 200), (10, 210), (0, 210)], close=True)
        yol = os.path.join(self.klasor, "cok.dxf")
        doc.saveas(yol)
        d = pencere.IceAktar(yol, "Polyester")
        self.assertTrue(d.tablo.isColumnHidden(3) is False)
        self.assertEqual(sorted((round(k.kaynak["yuz_alani"]), k.adet) for k in d.kalemler()), [(100, 1), (5000, 4)])
        satir = [r for r, (_, g, *_) in enumerate(d.ogeler) if round(g.dis.alan) == 5000][0]
        d.tablo.cellWidget(satir, 3).setValue(3.0)  # kalınlığı farklı olan ayrı kalem
        self.assertEqual(sorted((round(k.kaynak["yuz_alani"]), k.adet) for k in d.kalemler()),
                         [(100, 1), (5000, 1), (5000, 3)])
        d.topla.setChecked(False)
        self.assertEqual(len(d.kalemler()), 5)

    def test_kalip_penceresi(self):
        k = pencere.KalipPenceresi("Polyester")
        k.secim.setCurrentText("Sac levha")
        self.assertTrue(k.tamam.isEnabled())
        k.form.alanlar["a"].setValue(0.0)
        self.assertFalse(k.tamam.isEnabled())
        k.form.alanlar["a"].setValue(100.0)
        self.assertEqual(k.kalem().kaynak["kalip"], "Sac levha")

    def test_ayar_penceresi(self):
        w = pencere.AnaPencere()
        d = pencere.AyarPenceresi(w.ayar)
        d.verim.setValue(90)
        self.assertAlmostEqual(d.ayar().verim, 0.9)
        self.assertEqual(len(d.ayar().tozlar), len(w.ayar.tozlar))
        w.degisti = False
        w.close()


if __name__ == "__main__":
    unittest.main()
