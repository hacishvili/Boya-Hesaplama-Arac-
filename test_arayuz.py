# -*- coding: utf-8 -*-
"""Pencereler ekransız (offscreen) açılır: içe aktarma, kalıp, ayrıntı düzenleme, PDF."""
import math
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
from hesap import kaynak_alani, kalem_sonucu  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402


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

    def test_delikler_panelde_ve_birlesikte(self):
        import test_profil
        doc = ezdxf.new("R2007")
        doc.header["$INSUNITS"] = 4
        for x in (0, 1):
            doc.modelspace().add_3dsolid().sat = test_profil.delikli_plaka([(20, 20, "havsa"), (60, 30, "duz")])
        yol = os.path.join(self.klasor, "delikli.dxf")
        doc.saveas(yol)
        w = pencere.AnaPencere()
        d = pencere.IceAktar(yol, w.ayar.tozlar[0].ad, w)
        ayri = d.kalemler()
        self.assertEqual(len(ayri[0].kaynak["delikler"]), 2)
        d.birlestir.setChecked(True)
        tek = d.kalemler()[0]
        self.assertEqual(len(tek.kaynak["delikler"]), 4)
        self.assertTrue(tek.geo.tel)                       # birleşik önizleme de kenar döngüleri (delikler görünür)
        self.assertGreater(len(tek.geo.vurgu), 0)
        w.kalemler.append(ayri[0])
        w._yenile(0)
        self.assertIn("2 delik (1 havşalı)", w.tablo.item(0, 1).text())
        panel = w.ayrinti_alan.widget()
        self.assertTrue(any("Ø6 havşa Ø12 × 90°" in l.text() for l in panel.findChildren(pencere.QLabel)))
        once = kalem_sonucu(w.kalemler[0], w.ayar).alan_m2
        cb = [c for c in panel.findChildren(pencere.QCheckBox) if c.text() == "Delik içleri boyanmaz"][0]
        cb.setChecked(True)
        duvar = sum(x["duvar"] for x in w.kalemler[0].kaynak["delikler"]) / 1e6
        self.assertAlmostEqual(kalem_sonucu(w.kalemler[0], w.ayar).alan_m2, once - duvar)
        w.degisti = False
        w.close()

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
        T.Acis.kare_yuz(None, g, T.Acis.spline(None, g, 10.0), 5.0, z=1.0)  # döngü yüzeyde değil: hesaplanmaz
        doc = ezdxf.new("R2007")
        doc.header["$INSUNITS"] = 4
        doc.modelspace().add_3dsolid().sat = g.satirlar()
        yol = os.path.join(self.klasor, "ayak.dxf")
        doc.saveas(yol)
        d = pencere.IceAktar(yol, "Polyester")
        self.assertFalse(d.rapor_dugmesi.isHidden())
        self.assertIn("exact_spl_sur", d.tablo.item(0, 6).toolTip())
        metin = d.hata_raporu_metni()
        self.assertIn("tanınmayan spline yüz (exact_spl_sur)", metin)
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

    def test_kat_maske_ve_agirlik_paneli(self):
        w = pencere.AnaPencere()
        w.kalemler.append(pencere.Kalem("boru", {"tur": "kalip", "kalip": "Yuvarlak boru", "deger": {}},
                                        toz=w.ayar.tozlar[0].ad))
        w.kalemler.append(pencere.Kalem("elle", {"tur": "elle", "alan_m2": 0.1}, toz=w.ayar.tozlar[0].ad))
        w._yenile(0)
        self.assertNotEqual(w.tablo.item(0, 9).text(), "—")   # kalıbın ağırlığı hesaplanır
        self.assertEqual(w.tablo.item(1, 9).text(), "—")
        self.assertIn("1 kalemin ağırlığı bilinmiyor", w.toplam.text())
        panel = w.ayrinti_alan.widget()
        kat = [s for s in panel.findChildren(pencere.QSpinBox) if s.toolTip().startswith("Astar")][0]
        kat.setValue(2)
        self.assertEqual(w.kalemler[0].kat, 2)
        self.assertIn("2 kat", w.tablo.item(0, 1).text())
        w.tablo.selectRow(1)
        w._secim()
        panel = w.ayrinti_alan.widget()
        elle = [c for c in panel.findChildren(pencere.QCheckBox) if c.text() == "Elle gir"][0]
        elle.setChecked(True)
        agk = [s for s in panel.findChildren(pencere.QDoubleSpinBox) if s.suffix().strip() == "kg"][0]
        agk.setValue(2.5)
        self.assertEqual(w.kalemler[1].agirlik_kg, 2.5)
        self.assertEqual(w.tablo.item(1, 9).text(), "2,500")
        self.assertNotIn("bilinmiyor", w.toplam.text())
        w.degisti = False
        w.close()

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

    def test_islem_fiyatlari(self):
        import test_profil
        w = pencere.AnaPencere()
        d = pencere.AyarPenceresi(w.ayar)
        self.assertEqual([i.ad for i in d.islemler()], ["Kaynak", "Havşa", "Polisaj"])
        d.islem.cellWidget(0, 2).setValue(40.0)   # kaynak 40 / m
        self.assertTrue(d.islem.cellWidget(0, 4).isChecked())   # kaynak teli eklenir
        self.assertIn("1 makara", d.tel_bilgi.text())
        d.tel_fiyat.setValue(0.0)                 # bu testte yalnız işçilik
        d.islem.cellWidget(1, 2).setValue(2.5)    # havşa 2,5 / adet
        d._islem_satiri(pencere.Islem("Kumlama", "m²", 50.0))
        w.ayar = d.ayar()
        self.assertEqual(len(w.ayar.islemler), 4)
        doc = ezdxf.new("R2007")
        doc.header["$INSUNITS"] = 4
        doc.modelspace().add_3dsolid().sat = test_profil.delikli_plaka([(20, 20, "havsa"), (40, 20, "havsa"),
                                                                        (60, 30, "duz")])
        yol = os.path.join(self.klasor, "islem.dxf")
        doc.saveas(yol)
        w.kalemler.extend(pencere.IceAktar(yol, w.ayar.tozlar[0].ad, w).kalemler())
        w.kalemler.append(pencere.Kalem("b", {"tur": "elle", "alan_m2": 0.1}, toz=w.ayar.tozlar[0].ad))
        w._yenile(0)
        s = kalem_sonucu(w.kalemler[0], w.ayar)
        self.assertEqual(s.islem_detay["Havşa"], (2.0, 5.0))           # çizimden 2 havşa
        panel = w.ayrinti_alan.widget()
        cb = [c for c in panel.findChildren(pencere.QCheckBox) if c.text() == "elle (çizimden 2 adet)"][0]
        cb.setChecked(True)
        sp = [x for x in panel.findChildren(pencere.QDoubleSpinBox) if x.isEnabled() and x.suffix() == " adet"][0]
        sp.setValue(3)
        self.assertEqual(w.kalemler[0].islemler["Havşa"], 3)
        cb.setChecked(False)                                           # çizime döner
        self.assertNotIn("Havşa", w.kalemler[0].islemler)
        elle = [c for c in panel.findChildren(pencere.QCheckBox) if c.text() == "elle (çizimden 0,000 m · 0,0 mm)"][0]
        elle.setChecked(True)                                          # tek gövde, dikiş seçilmemiş: elle
        kaynak = [x for x in panel.findChildren(pencere.QDoubleSpinBox) if x.suffix() == " m"][0]
        kaynak.setValue(0.5)
        self.assertAlmostEqual(kalem_sonucu(w.kalemler[0], w.ayar).islem_tl, 0.5 * 40 + 2 * 2.5)
        self.assertIn("Kaynak", w.toplam.text())
        self.assertTrue(w.tablo.item(0, 10).text().endswith(w.ayar.para))
        # çoklu seçimde polisaj hepsine
        w.tablo.setRangeSelected(pencere.QTableWidgetSelectionRange(0, 0, 1, len(pencere.SUTUNLAR) - 1), True)
        w._secim()
        sp = [x for x in w.ayrinti_alan.widget().findChildren(pencere.QDoubleSpinBox) if x.suffix() == " m²"][0]
        sp.setValue(0.2)
        self.assertEqual([k.islemler.get("Polisaj") for k in w.kalemler], [0.2, 0.2])
        w.degisti = False
        w.close()

    def test_kaynak_yerleri(self):
        import test_acis
        import test_profil
        doc = ezdxf.new("R2007")
        doc.header["$INSUNITS"] = 4
        m = doc.modelspace()
        m.add_3dsolid().sat = test_profil.delikli_plaka([])
        tasi = (1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0, 50.0, 30.0, 5.0, 1.0, "no_rotate", "no_reflect", "no_shear")
        m.add_3dsolid().sat = test_acis.silindir(10.0, 0.0, 95.0, donusum=tasi).satirlar()  # sacın üstünde Ø20 boru
        yol = os.path.join(self.klasor, "montaj.dxf")
        doc.saveas(yol)
        w = pencere.AnaPencere()
        for i in w.ayar.islemler:
            i.fiyat = {"Kaynak": 40.0}.get(i.ad, 0.0)
        d = pencere.IceAktar(yol, w.ayar.tozlar[0].ad, w)
        ayri = d.kalemler()
        cevre = 2 * math.pi * 10
        self.assertEqual(ayri[0].kaynak["kaynak_dikisleri"], [])          # sac: değme kenarı boru tarafında
        self.assertEqual(len(ayri[1].kaynak["kaynak_dikisleri"]), 1)     # borunun alt çemberi önerilir
        self.assertAlmostEqual(kalem_sonucu(ayri[1], w.ayar).islem_detay["Kaynak"][0], cevre / 1000, places=4)
        d.birlestir.setChecked(True)
        d.tablo.cellWidget(1, 5).setValue(4)                             # 4 boru: dikiş 4 kez
        tek = d.kalemler()[0]
        self.assertAlmostEqual(hesap_kaynak(tek), 4 * cevre, delta=0.05)
        self.assertEqual(len(tek.geo.oneri), 1)
        # pencere: öneri iki taraflı yapılır, sacın bir kenarı eklenir
        k = ayri[1]
        p = pencere.KaynakPenceresi(k.geo, k.kaynak["kaynak_dikisleri"])
        i = k.geo.oneri[0]
        from PySide6.QtTest import QTest
        from PySide6.QtCore import QPoint
        p.gorunum.resize(700, 500)
        p.gorunum.grab()
        q = p.gorunum._ekran[i][len(p.gorunum._ekran[i]) // 3].toPoint()
        QTest.mousePress(p.gorunum, Qt.LeftButton, pos=q)               # el titremesi (5 px): yine tıklama
        QTest.mouseMove(p.gorunum, q + QPoint(4, 3))
        QTest.mouseRelease(p.gorunum, Qt.LeftButton, pos=q + QPoint(4, 3))
        self.assertEqual(p.gorunum.secim.get(i), 2)
        p.gorunum.secim[i] = 1
        p.gorunum.tikla(i)                                               # tek → iki taraflı
        self.assertEqual(p.dikisler()[0][1], 2)
        self.assertIn("iki taraflı", p.ozet.text())
        p.gorunum.tikla(i)                                               # kaldır
        self.assertEqual(p.dikisler(), [])
        p._oneriler()
        self.assertEqual(len(p.dikisler()), 1)
        p.gorunum.resize(600, 400)
        p.gorunum.grab()                                                 # çizim hatasız
        g = p.gorunum                                                    # imleçte yakınlaştırma: imlecin altı yerinde
        f = g._izdus()
        q = k.geo.kenarlar[i][0]
        once = f(q)[0]
        g.yakinlastir(once, 3.0)
        sonra = g._izdus()(q)[0]
        self.assertAlmostEqual(once.x(), sonra.x(), places=6)
        self.assertAlmostEqual(once.y(), sonra.y(), places=6)
        self.assertAlmostEqual(g.zoom, 3.0)
        g.kay += QPointF(40, -10)                                        # kaydırma
        self.assertAlmostEqual(g._izdus()(q)[0].x(), sonra.x() + 40, places=6)
        g.sigdir()
        self.assertEqual((g.zoom, g.kay), (1.0, QPointF(0, 0)))
        p._temizle()                                                     # pencereyle seçim
        g.grab()
        tum = QRectF(0, 0, g.width(), g.height())
        g.pencere_sec(tum)                                               # hepsi içinde
        self.assertEqual(len(g.secim), len(k.geo.kenarlar))
        g.secim[i] = 2
        g.pencere_sec(tum)                                               # seçili olan değişmez
        self.assertEqual(g.secim[i], 2)
        g.pencere_sec(tum, cikar=True)                                   # Shift: çıkar
        self.assertEqual(g.secim, {})
        a = g._ekran[i]
        orta = a[len(a) // 2]
        kucuk = QRectF(orta.x() - 2, orta.y() - 2, 4, 4)
        g.pencere_sec(kucuk)                                             # soldan sağa: tamamı içinde değil
        self.assertNotIn(i, g.secim)
        g.pencere_sec(kucuk, capraz=True)                                # sağdan sola: değen kenar
        self.assertIn(i, g.secim)
        o = pencere.Onizleme()                                           # alt önizleme seçimleri gösterir
        o.resize(400, 300)
        o.goster(k.geo, "", {"kaynak_dikisleri": [[i, 2, 62.8]], "yuzey_secimi": {"Polisaj": [[0, 100.0]]}})
        self.assertEqual((o._dikis, o._yuzey), ({i: 2}, {0}))
        o.grab()
        w.degisti = False
        w.close()

    def test_polisaj_yuzeyleri(self):
        import test_acis
        import test_profil
        doc = ezdxf.new("R2007")
        doc.header["$INSUNITS"] = 4
        m = doc.modelspace()
        m.add_3dsolid().sat = test_profil.delikli_plaka([])
        tasi = (1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0, 50.0, 30.0, 5.0, 1.0, "no_rotate", "no_reflect", "no_shear")
        m.add_3dsolid().sat = test_acis.silindir(10.0, 0.0, 95.0, donusum=tasi).satirlar()
        yol = os.path.join(self.klasor, "polisaj.dxf")
        doc.saveas(yol)
        w = pencere.AnaPencere()
        d = pencere.IceAktar(yol, w.ayar.tozlar[0].ad, w)
        sac = d.kalemler()[0]
        ag = sac.geo
        self.assertEqual(len(ag.yuz_donguleri), len(ag.yuz_alanlari))
        self.assertAlmostEqual(sum(ag.yuz_alanlari), kaynak_alani(sac.kaynak), delta=0.5)
        p = pencere.YuzeyPenceresi(ag, [])
        p.gorunum.resize(600, 400)
        p.gorunum.pitch = math.pi / 2                                  # tepeden bakış: üst yüz en yakın
        p.gorunum.grab()
        ust = max(range(len(ag.yuz_alanlari)), key=lambda i: (ag.yuz_turleri[i] == "duzlem",
                                                              max(q[2] for dd in ag.yuz_donguleri[i] for q in dd),
                                                              ag.yuz_alanlari[i]))
        i = p.gorunum._en_yakin(QPointF(300, 200))
        self.assertEqual(i, ust)
        p.gorunum.tikla(i)
        self.assertEqual(p.secim(), [[i, round(ag.yuz_alanlari[i], 3)]])
        self.assertEqual(p.liste.item(i).checkState(), Qt.Checked)
        p.liste.item(i).setCheckState(Qt.Unchecked)                    # listeden bırak
        self.assertEqual(p.secim(), [])
        p.liste.item(i).setCheckState(Qt.Checked)
        self.assertIn("1</b> yüzey", p.ozet.text())
        tum = QRectF(0, 0, p.gorunum.width(), p.gorunum.height())
        p.gorunum.pencere_sec(tum)                                     # pencere: bütün yüzler
        self.assertEqual(len(p.secim()), len(ag.yuz_alanlari))
        p.gorunum.pencere_sec(tum, cikar=True)
        p.gorunum.pencere_sec(QRectF(299, 199, 2, 2), capraz=True)     # sağdan sola: değen (üst yüz)
        self.assertIn(i, p.gorunum.secili)
        p.gorunum.secili.clear()
        p.gorunum.secili.add(i)
        p._ozet()
        sac.kaynak["yuzey_secimi"] = {"Polisaj": p.secim()}
        w.ayar.islemler[2].fiyat = 100.0
        s = kalem_sonucu(sac, w.ayar)
        self.assertAlmostEqual(s.islem_detay["Polisaj"][0], ag.yuz_alanlari[i] / 1e6)
        d.birlestir.setChecked(True)                                   # birleşik: yüzler ve seçim taşınır
        d.tablo.cellWidget(0, 5).setValue(2)
        d.ogeler[0][2]["yuzey_secimi"] = {"Polisaj": p.secim()}
        tek = d.kalemler()[0]
        self.assertGreater(len(tek.geo.yuz_donguleri), len(ag.yuz_donguleri))
        self.assertAlmostEqual(kalem_sonucu(tek, w.ayar).islem_detay["Polisaj"][0], 2 * ag.yuz_alanlari[i] / 1e6,
                               places=6)
        w.degisti = False
        w.close()


def hesap_kaynak(k):
    from hesap import kaynak_boyu_mm
    return kaynak_boyu_mm(k.kaynak)


if __name__ == "__main__":
    unittest.main()
