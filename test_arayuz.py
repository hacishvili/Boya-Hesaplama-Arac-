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
from PySide6.QtWidgets import QComboBox, QTableWidgetSelectionRange  # noqa: E402

pencere.QComboBox, pencere.QTableWidgetSelectionRange = QComboBox, QTableWidgetSelectionRange
from hesap import kalem_sonucu  # noqa: E402


class Arayuz(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp()
        os.environ["APPDATA"] = self.klasor  # kullanıcının gerçek ayarlarına dokunma

    def tearDown(self):
        shutil.rmtree(self.klasor, ignore_errors=True)

    def test_ice_aktar_adet_secilebilir(self):
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 4
        m = doc.modelspace()
        m.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
        m.add_lwpolyline([(200, 0), (210, 0), (210, 10), (200, 10)], close=True)
        yol = os.path.join(self.klasor, "adet.dxf")
        doc.saveas(yol)
        w = pencere.AnaPencere()
        d = pencere.IceAktar(yol, w.ayar.tozlar[0].ad, w)
        d.tablo.cellWidget(0, 5).setValue(4)
        d.tablo.cellWidget(1, 5).setValue(7)
        d._alanlari_yenile()  # kalınlık değişince tablo yenilenir: adetler korunmalı
        yeni = d.kalemler()
        self.assertEqual(sorted(k.adet for k in yeni), [4, 7])

    def test_ice_aktar_etiketten_ad_ve_kalinlik(self):
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 4
        m = doc.modelspace()
        m.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
        m.add_mtext("K:4\\PP:ÖN PLAKA", dxfattribs={"insert": (50, 25)})
        yol = os.path.join(self.klasor, "etiket.dxf")
        doc.saveas(yol)
        w = pencere.AnaPencere()
        d = pencere.IceAktar(yol, w.ayar.tozlar[0].ad, w)
        yeni = d.kalemler()
        self.assertEqual(yeni[0].ad, "ÖN PLAKA")
        self.assertAlmostEqual(yeni[0].kaynak["kalinlik"], 4.0)

    def test_pdf_taslak_kalem(self):
        import test_pdf
        yol = os.path.join(self.klasor, "sehpa.pdf")
        test_pdf.pdf_yaz(yol, test_pdf.YAZI)
        w = pencere.AnaPencere()
        w.ayar.tozlar.append(pencere.Toz("Metalik Kahve"))
        d = pencere.PdfAktar(yol, w.ayar.tozlar[0].ad, w.ayar, w)
        self.assertEqual(d.ad.text(), "400x400x240 SEHPA METALI")
        self.assertEqual(d.toz.currentText(), "Metalik Kahve")      # renk yazısından toz seçildi
        self.assertEqual(d.kalinlik.value(), 0.0)                    # belirsiz: atanmadı
        d.adet.setValue(2)
        # varsayılan seçenek abkant açınımı: üç ölçüden U biçimi tahmini, kalınlık girilmeden kalem eklenmez
        self.assertTrue(d._acinim_mi())
        self.assertEqual([d.abkant.deger()[x] for x in ("k1", "k2", "k3", "W")], [400.0, 500.0, 400.0, 240.0])
        self.assertFalse(d.tamam.isEnabled())
        d.abkant.alanlar["t"].setValue(6.0)
        self.assertTrue(d.tamam.isEnabled())
        k = d.kalem()
        self.assertEqual((k.adet, k.toz, k.kaynak["tur"]), (2, "Metalik Kahve", "kalip"))
        w.kalemler.append(k)
        w._yenile()
        self.assertIn("Abkant sac açınımı 1278", w.tablo.item(0, 1).text())
        self.assertAlmostEqual(kalem_sonucu(k, w.ayar).alan_m2, 0.6318, places=3)
        # ikinci seçenek: elle alan
        d.hesap.setCurrentIndex(1)
        self.assertTrue(d.tamam.isEnabled())
        d.alan.setValue(0.5)
        k2 = d.kalem()
        self.assertEqual(k2.kaynak["tur"], "elle")
        self.assertIn("500 × 400 × 240", k2.kaynak["pdf"])
        w.kalemler.append(k2)
        w._yenile()
        self.assertIn("PDF taslağı", w.tablo.item(1, 1).text())

    def test_ice_aktar_kirmizi_secenegi(self):
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 4
        m = doc.modelspace()
        for a, b in [((0, 0), (100, 0)), ((100, 0), (100, 50)), ((100, 50), (0, 50)), ((0, 50), (0, 0))]:
            m.add_line(a, b)
        m.add_line((0, 0), (100, 0), dxfattribs={"color": 1})   # üst üste kırmızı büküm çizgisi
        yol = os.path.join(self.klasor, "kirmizi.dxf")
        doc.saveas(yol)
        w = pencere.AnaPencere()
        d = pencere.IceAktar(yol, w.ayar.tozlar[0].ad, w)
        self.assertTrue(d.kirmizi.isChecked())
        self.assertEqual(d.sonuc.kirmizi, 1)
        d.kirmizi.setChecked(False)
        self.assertEqual(d.sonuc.kirmizi, 0)

    def _iki_kati(self):
        from ezdxf.acis import api as acis
        from ezdxf.render import forms
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 4
        for olcu in ((100, 50, 20), (50, 50, 20)):       # alanlar 16000 ve 9000 mm²
            kati = doc.modelspace().add_3dsolid()
            acis.export_dxf(kati, [acis.body_from_mesh(forms.cube().scale(*olcu))])
        yol = os.path.join(self.klasor, "iki_kati.dxf")
        doc.saveas(yol)
        return yol

    def test_3d_govdeler_tek_parca_olabilir(self):
        w = pencere.AnaPencere()
        d = pencere.IceAktar(self._iki_kati(), w.ayar.tozlar[0].ad, w)
        self.assertTrue(d.birlestir.isEnabled())
        ayri = d.kalemler()                                # varsayılan: gövdeler ayrı kalem
        self.assertEqual(sorted(round(k.kaynak["alan"]) for k in ayri), [9000, 16000])
        d.birlestir.setChecked(True)
        tek = d.kalemler()
        self.assertEqual(len(tek), 1)
        self.assertAlmostEqual(tek[0].kaynak["alan"], 25000, places=3)
        self.assertEqual(tek[0].adet, 1)
        self.assertIn("2 gövde", pencere.kaynak_aciklamasi(tek[0].kaynak))
        d.tablo.cellWidget(0, 5).setValue(2)               # ilk gövdeden 2 adet: alanına çarpılır
        self.assertAlmostEqual(d.kalemler()[0].kaynak["alan"], 2 * 16000 + 9000, places=3)
        d.tablo.item(1, 0).setCheckState(pencere.Qt.Unchecked)   # tek gövde kalınca bölünmüş davranış
        self.assertEqual(len(d.kalemler()), 1)
        self.assertNotIn("birleşik", d.kalemler()[0].kaynak["varlik"])

    def test_birlestir_tek_govdede_kapali(self):
        doc = ezdxf.new("R2018")
        doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
        yol = os.path.join(self.klasor, "tek2d.dxf")
        doc.saveas(yol)
        w = pencere.AnaPencere()
        d = pencere.IceAktar(yol, w.ayar.tozlar[0].ad, w)
        self.assertFalse(d.birlestir.isEnabled())

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

    def test_hata_raporu(self):
        import test_acis as T
        g = T.Govde()
        T.Acis.kare_yuz(None, g, T.Acis.spline(None, g, 10.0), 5.0)  # kırpılmış spline yüz: hesaplanmaz
        doc = ezdxf.new("R2007")
        doc.header["$INSUNITS"] = 4
        doc.modelspace().add_3dsolid().sat = g.satirlar()
        yol = os.path.join(self.klasor, "ayak.dxf")
        doc.saveas(yol)
        d = pencere.IceAktar(yol, "Polyester")
        self.assertFalse(d.rapor_dugmesi.isHidden())
        self.assertIn("exact_spl_sur", d.tablo.item(0, 6).toolTip())
        metin = d.hata_raporu_metni()
        self.assertIn("kırpılmış ya da tanınmayan spline yüz (exact_spl_sur)", metin)
        self.assertIn("{ exact_spl_sur 22600 full nubs 1 1", metin)

    def test_kalinlik_cizimden(self):
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 4
        m = doc.modelspace()
        m.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
        m.add_lwpolyline([(200, 0), (300, 0), (300, 50), (200, 50)], close=True, dxfattribs={"layer": "SAC_3MM"})
        m.add_mtext("MALZEME: DKP\\Pt=2").set_location((0, 80))
        m.add_text("ÖLÇEK 1:2").set_placement((0, 100))
        yol = os.path.join(self.klasor, "parca.dxf")
        doc.saveas(yol)
        d = pencere.IceAktar(yol, "Polyester")
        self.assertEqual(d.kalinlik.value(), 2.0)
        self.assertIn("yazıdan", d.kalinlik_notu.text())
        self.assertEqual(sorted(k.kaynak["kalinlik"] for k in d.kalemler()), [2.0, 3.0])  # katmandaki 3 mm
        # yazı yoksa dosya adından
        doc2 = ezdxf.new("R2018")
        doc2.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
        yol2 = os.path.join(self.klasor, "kapak_1,5mm.dxf")
        doc2.saveas(yol2)
        d2 = pencere.IceAktar(yol2, "Polyester")
        self.assertEqual(d2.kalinlik.value(), 1.5)
        self.assertIn("dosya adından", d2.kalinlik_notu.text())

    def test_adet_elle_degisir(self):
        w = pencere.AnaPencere()
        for i in range(3):
            w.kalemler.append(pencere.Kalem(f"P{i}", {"tur": "elle", "alan_m2": 0.1}, toz=w.ayar.tozlar[0].ad))
        w._yenile()
        # tabloda Adet hücresi düzenlenebilir, öbürleri değil
        self.assertTrue(w.tablo.item(0, 2).flags() & pencere.Qt.ItemIsEditable)
        self.assertFalse(w.tablo.item(0, 3).flags() & pencere.Qt.ItemIsEditable)
        w.tablo.item(1, 2).setText("12")
        self.assertEqual(w.kalemler[1].adet, 12)
        w.tablo.item(1, 2).setText("abc")      # geçersiz: eski değer kalır
        self.assertEqual(w.kalemler[1].adet, 12)
        self.assertEqual(w.tablo.item(1, 2).text(), "12")
        w.tablo.item(1, 2).setText("0")
        self.assertEqual(w.kalemler[1].adet, 12)
        self.assertIn("<b>14</b> adet", w.toplam.text())   # 1 + 12 + 1
        # çoklu seçimde hepsine birden
        w.tablo.selectRow(0)
        w.tablo.setRangeSelected(pencere.QTableWidgetSelectionRange(0, 0, 2, len(pencere.SUTUNLAR) - 1), True)
        sp = next(x for x in w.ayrinti_alan.widget().findChildren(pencere.QSpinBox))
        sp.setValue(5)
        self.assertEqual([k.adet for k in w.kalemler], [5, 5, 5])
        self.assertEqual(w.tablo.item(2, 2).text(), "5")

    def test_coklu_secimle_toz(self):
        w = pencere.AnaPencere()
        for i in range(3):
            w.kalemler.append(pencere.Kalem(f"P{i}", {"tur": "elle", "alan_m2": 0.1 * (i + 1)}, toz=w.ayar.tozlar[0].ad))
        w._yenile()
        w.tablo.selectRow(0)
        w.tablo.setRangeSelected(pencere.QTableWidgetSelectionRange(0, 0, 1, len(pencere.SUTUNLAR) - 1), True)
        self.assertEqual(w._secili_satirlar(), [0, 1])
        panel = w.ayrinti_alan.widget()
        toz = panel.findChild(pencere.QComboBox)
        toz.setCurrentText(w.ayar.tozlar[2].ad)
        self.assertEqual([k.toz for k in w.kalemler], [w.ayar.tozlar[2].ad] * 2 + [w.ayar.tozlar[0].ad])
        self.assertEqual(w.tablo.item(1, 4).text(), w.ayar.tozlar[2].ad)
        self.assertEqual(w._secili_satirlar(), [0, 1])  # seçim korunur
        w.degisti = False
        w.close()

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
