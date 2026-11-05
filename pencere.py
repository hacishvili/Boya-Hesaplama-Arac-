# -*- coding: utf-8 -*-
"""Ana pencere: sipariş listesi (kalemler), seçili kalemin ayrıntısı ve önizlemesi, toplamlar.
Dosya ekleme (DXF / STEP / STL) içe aktarma penceresinden, kalıplar kalıp penceresinden geçer."""
from __future__ import annotations

import copy
import html
import math
import os
import zipfile
from typing import Dict, List, Optional

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QKeySequence, QPageLayout, QPageSize, QPainter,
                           QPainterPath, QPdfWriter, QPen, QPolygonF, QTextDocument)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                               QSpinBox, QSplitter, QStyle, QTableWidget, QTableWidgetItem, QToolBar,
                               QVBoxLayout, QWidget)

import dxf_oku
import kaliplar
import pdf_oku
import proje
import rapor
import step_oku
import stl_oku
from geometri import Ag, Parca2D
from hesap import (ISLEM_BIRIMLERI, ISLEM_KAYNAKLARI, Ayarlar, Islem, KaynakTeli, Kalem, Toz, agirlik_kg, islem_miktari,
                   otomatik_miktar, kalem_sonucu, kaynak_aciklamasi, kaynak_alani, kaynak_hacmi,
                   ozet, sayi, teorik_kaplama, yontem_ozeti)
from surum import SURUM

UYGULAMA = "Toz Boya Hesabı"
DOSYA_SUZGECI = ("Çizimler (*.dxf *.dwg *.step *.stp *.stl *.pdf);;DXF (*.dxf);;DWG (*.dwg);;STEP (*.step *.stp);;"
                 "STL (*.stl);;"
                 "PDF teknik resim (*.pdf)")


def _cift(en: float, boy: float, deger: float, basamak: int = 2, adim: float = 1.0, sonek: str = "") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(en, boy)
    s.setDecimals(basamak)
    s.setSingleStep(adim)
    s.setValue(deger)
    s.setKeyboardTracking(False)
    if sonek:
        s.setSuffix(" " + sonek)
    return s


# ---------------------------------------------------------------- önizleme

class Onizleme(QWidget):
    """2D parça (dış kontur + delikler) ya da 3D gövdenin eş ölçülü görünüşü."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 180)
        self._p2: Optional[Parca2D] = None
        self._ag: Optional[Ag] = None
        self._yazi = ""

    def sizeHint(self):
        return QSize(320, 240)

    def goster(self, geo, yazi: str = ""):
        self._p2 = geo if isinstance(geo, Parca2D) else None
        self._ag = geo if isinstance(geo, Ag) else None
        self._yazi = yazi
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), self.palette().base())
        r = QRectF(self.rect()).adjusted(12, 12, -12, -28)
        if self._p2 is not None:
            self._ciz2(p, r)
        elif self._ag is not None:
            self._ciz3(p, r)
        else:
            p.setPen(self.palette().placeholderText().color())
            p.drawText(self.rect(), Qt.AlignCenter, self._yazi or "Önizleme yok")
            return
        if self._yazi:
            p.setPen(self.palette().text().color())
            p.drawText(QRectF(8, self.height() - 24, self.width() - 16, 20), Qt.AlignLeft | Qt.AlignVCenter, self._yazi)

    @staticmethod
    def _sigdir(pts, r: QRectF):
        xs = [x for x, _ in pts]
        ys = [y for _, y in pts]
        w, h = max(xs) - min(xs) or 1.0, max(ys) - min(ys) or 1.0
        s = min(r.width() / w, r.height() / h)
        ox = r.left() + (r.width() - w * s) / 2 - min(xs) * s
        oy = r.top() + (r.height() + h * s) / 2 + min(ys) * s
        return lambda x, y: QPointF(ox + x * s, oy - y * s)

    def _ciz2(self, p: QPainter, r: QRectF):
        donus = self._sigdir(self._p2.dis.noktalar, r)
        yol = QPainterPath()
        yol.setFillRule(Qt.OddEvenFill)
        for k in [self._p2.dis] + self._p2.delikler:
            yol.addPolygon(QPolygonF([donus(x, y) for x, y in k.noktalar]))
            yol.closeSubpath()
        p.setBrush(QColor(80, 140, 200, 70))
        p.setPen(QPen(QColor(30, 80, 140), 1.2))
        p.drawPath(yol)

    def _ciz3(self, p: QPainter, r: QRectF):
        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
        yuzler = self._ag.yuzler
        if len(yuzler) > 8000:
            adim = len(yuzler) // 8000 + 1
            yuzler = yuzler[::adim]
        proj = lambda q: ((q[0] - q[1]) * c, (q[0] + q[1]) * s + q[2])
        pts2 = [proj(q) for y in yuzler for q in y]
        if not pts2:
            return
        donus = self._sigdir(pts2, r)
        if self._ag.tel:  # ACIS katı: kenar döngüleri
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(30, 80, 140), 1.0))
            for y in yuzler:
                p.drawPolygon(QPolygonF([donus(*proj(q)) for q in y]))
            p.setPen(QPen(QColor(150, 170, 190), 0.6))
            for y in self._ag.yardimci:
                p.drawPolyline(QPolygonF([donus(*proj(q)) for q in y]))
            if self._ag.vurgu:  # delik ve havşa döngüleri
                p.setPen(QPen(QColor(220, 110, 0), 1.8))
                for y in self._ag.vurgu:
                    p.drawPolygon(QPolygonF([donus(*proj(q)) for q in y]))
            return
        isik = (-0.4, -0.5, 0.77)
        sirali = sorted(yuzler, key=lambda y: sum(q[0] + q[1] - q[2] * 0.0 for q in y) / len(y), reverse=True)
        kalem = QPen(QColor(30, 60, 90, 90), 0.5)
        for y in sirali:
            if len(y) < 3:
                continue
            ax, ay, az = (y[1][i] - y[0][i] for i in range(3))
            bx, by, bz = (y[2][i] - y[0][i] for i in range(3))
            n = (ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx)
            l = math.sqrt(sum(v * v for v in n)) or 1.0
            ton = abs(sum(n[i] * isik[i] for i in range(3)) / l)
            renk = QColor.fromRgbF(0.35 + 0.45 * ton, 0.5 + 0.4 * ton, 0.7 + 0.25 * ton)
            p.setBrush(renk)
            p.setPen(kalem)
            p.drawPolygon(QPolygonF([donus(*proj(q)) for q in y]))


# ---------------------------------------------------------------- içe aktarma

class IceAktar(QDialog):
    """DXF / STEP / STL'deki parçaları gösterir; kullanıcı birimi, katmanları ve eklenecekleri seçer."""

    def __init__(self, yol: str, varsayilan_toz: str, parent=None, oda_yolu: str = ""):
        super().__init__(parent)
        self.yol = yol
        self.dosya_adi = os.path.splitext(os.path.basename(yol))[0]
        self.stl = yol.lower().endswith(".stl")
        self.step = yol.lower().endswith((".step", ".stp"))
        self.dxf = not (self.stl or self.step)
        self.toz = varsayilan_toz
        self.setWindowTitle(f"Dosya ekle — {os.path.basename(yol)}")
        self.resize(980, 620)
        self.doc = dxf_oku.belge_ac(yol, oda_yolu) if self.dxf else None
        self.step_model = step_oku.oku(yol) if self.step else None
        self.sonuc: Optional[dxf_oku.DxfSonuc] = None
        self.ogeler: List = []   # (tür, geometri, kaynak, ad, hata)

        ana = QVBoxLayout(self)
        ust = QHBoxLayout()
        ana.addLayout(ust)
        form = QFormLayout()
        ust.addLayout(form, 1)
        self.birim = QComboBox()
        kod = int(self.doc.header.get("$INSUNITS", 0) or 0) if self.dxf else 0
        if self.step:
            kod = next((k for k, (_, o) in dxf_oku.BIRIMLER.items() if k and abs(o - self.step_model.birim_mm) < 1e-9), 4)
        for k, (ad, olcek) in dxf_oku.BIRIMLER.items():
            if k == 0:
                continue
            self.birim.addItem(ad, olcek)
        self.birim.setCurrentIndex(max(0, self.birim.findText(dxf_oku.BIRIMLER.get(kod, ("mm", 1))[0]
                                                              if kod else "mm")))
        birim_notu = ("STL'de birim yazmaz" if self.stl else
                      f"STEP dosyasında: {dxf_oku.BIRIMLER.get(kod, ('mm', 1))[0]}" if self.step else
                      f"dosyada: {dxf_oku.BIRIMLER.get(kod, (f'kod {kod}', 1))[0]}")
        satir = QHBoxLayout()
        satir.addWidget(self.birim)
        satir.addWidget(QLabel(birim_notu))
        satir.addStretch(1)
        form.addRow("Çizim birimi", satir)
        self.kalinlik = _cift(0.0, 100.0, 1.5, 2, 0.1, "mm")
        self.kalinlik.setToolTip("Bütün 2D parçalara uygulanır; parçaların kalınlığı tabloda ayrı ayrı da "
                                 "değiştirilebilir. Kenar alanı = çevre × kalınlık")
        self.kalinliklar: Dict[tuple, float] = {}  # parça anahtarı → sac kalınlığı (yeniden okumada korunur)
        self.kesikli = QCheckBox("Kesikli çizgileri de al (eksen, gizli, büküm)")
        self.kirmizi = QCheckBox("Kırmızı çizgileri (büküm çizgisi) alma")
        self.kirmizi.setChecked(True)
        self.kirmizi.setToolTip("Rengi kırmızı (AutoCAD renk 1) olan çizgiler büküm çizgisi sayılır ve konturlara katılmaz")
        self.topla = QCheckBox("Aynı parçaları tek satırda topla (adet olarak)")
        self.topla.setChecked(True)
        self.topla.setToolTip("Alanı, ölçüleri (ve 2D'de kalınlığı) aynı olan parçalar tek kalem olur; adet kopya sayısıdır")
        if self.dxf:
            self.kalinlik_notu = QLabel()
            self._kal_satir = QWidget()
            h = QHBoxLayout(self._kal_satir)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(self.kalinlik)
            h.addWidget(self.kalinlik_notu, 1)
            self._kal_bilgi = QLabel("Saclarda iki yüz ve kesim kenarları (çevre × kalınlık) boyanır.")
            form.addRow("Sac kalınlığı (2D, tümü)", self._kal_satir)
            form.addRow("", self._kal_bilgi)
            form.addRow("", self.kesikli)
            form.addRow("", self.kirmizi)
        self._form = form
        form.addRow("", self.topla)
        self.birlestir = QCheckBox("3D gövdeleri parçalara bölmeden tek parça olarak al (alanlar toplanır)")
        self.birlestir.setToolTip("Seçili bütün 3D gövdelerin boyanacak alanı toplanıp tek kalem olur; her gövdenin "
                                  "adedi alanına çarpılır. Hesaplanamayan gövde toplama girmez.")
        self.birlestir.setEnabled(False)
        self.birlestir.toggled.connect(self._uyari_yenile)
        form.addRow("", self.birlestir)
        self.katmanlar = QListWidget()
        self.katmanlar.setMaximumHeight(130)
        if self.dxf:
            kutu = QGroupBox("Katmanlar (işareti kaldırılan alınmaz)")
            v = QVBoxLayout(kutu)
            v.addWidget(self.katmanlar)
            ust.addWidget(kutu, 1)

        orta = QSplitter(Qt.Horizontal)
        ana.addWidget(orta, 1)
        self.tablo = QTableWidget(0, 7)
        self.tablo.setHorizontalHeaderLabels(["Ekle / ad", "Tür", "Ölçü (mm)", "Sac kalınlığı", "Alan / adet (m²)",
                                              "Adet", "Durum"])
        self.tablo.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.tablo.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tablo.verticalHeader().hide()
        self.tablo.itemSelectionChanged.connect(self._sec)
        orta.addWidget(self.tablo)
        self.onizleme = Onizleme()
        orta.addWidget(self.onizleme)
        orta.setSizes([620, 340])
        self.uyari = QLabel()
        self.uyari.setWordWrap(True)
        self.uyari.setStyleSheet("color: #8a5a00;")
        ana.addWidget(self.uyari)
        dugmeler = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.rapor_dugmesi = dugmeler.addButton("Hata ayrıntısını kaydet…", QDialogButtonBox.ActionRole)
        self.rapor_dugmesi.setToolTip("Hesaplanamayan gövdelerin nedeni ve ham verisi bir metin dosyasına yazılır")
        self.rapor_dugmesi.clicked.connect(self._hata_raporu)
        dugmeler.button(QDialogButtonBox.Ok).setText("Seçilenleri ekle")
        dugmeler.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        dugmeler.accepted.connect(self.accept)
        dugmeler.rejected.connect(self.reject)
        ana.addWidget(dugmeler)

        self.katman_kalinlik: Dict[str, float] = {}
        if self.dxf:
            t, kaynak, self.katman_kalinlik = dxf_oku.kalinlik_ipucu(self.doc, yol)
            if t is not None:
                self.kalinlik.setValue(t)
                self.kalinlik_notu.setText(f"{kaynak} okundu")
            elif self.katman_kalinlik:
                self.kalinlik_notu.setText("katman adlarındaki kalınlıklar o katmanın parçalarına uygulandı")
            else:
                self.kalinlik_notu.setText("çizimde yazmıyor: girin (parça parça da girilebilir)")
        self._katman_ilk = True
        self.birim.currentIndexChanged.connect(self.cozumle)
        self.kesikli.toggled.connect(self.cozumle)
        self.kirmizi.toggled.connect(self.cozumle)
        self.katmanlar.itemChanged.connect(self.cozumle)
        self.kalinlik.valueChanged.connect(self._kalinlik_tumu)
        self.cozumle()

    # -- çözümleme
    def cozumle(self, *_):
        olcek = float(self.birim.currentData() or 1.0)
        self.ogeler = []
        uyarilar = []
        if self.stl:
            try:
                govdeler = stl_oku.govdeler(self.yol, olcek)
            except (OSError, ValueError) as h:
                govdeler = []
                uyarilar.append(str(h))
            olculer = [max(b[j] - a[j] for j in range(3)) for a, b in (g.kutu() for g in govdeler)]
            u = dxf_oku.birim_uyarisi(max(olculer) if olculer else 0.0)
            if u:
                uyarilar.append(u)
            for i, g in enumerate(govdeler):
                ad = self.dosya_adi + (f" – gövde {i + 1}" if len(govdeler) > 1 else "")
                kaynak = {"tur": "3d", "alan": g.alan, "kapali": g.kapali_mi(),
                          "katsayi": 2.0 if g.sac_yuzeyi_mi() else 1.0, "varlik": "STL"}
                if g.hacim():
                    kaynak["hacim"] = g.hacim()
                self.ogeler.append(("3d", g, kaynak, ad, ""))
        else:
            haric = [self.katmanlar.item(i).text() for i in range(self.katmanlar.count())
                     if self.katmanlar.item(i).checkState() != Qt.Checked]
            if self.step:
                s = step_oku.cozumle(self.step_model, olcek)
            else:
                s = dxf_oku.cozumle(self.doc, olcek, haric, self.kesikli.isChecked(),
                                    kirmizi_haric=self.kirmizi.isChecked())
            self.sonuc = s
            if self._katman_ilk:
                self._katman_ilk = False
                self.katmanlar.blockSignals(True)
                for ad, n in sorted(s.katmanlar.items()):
                    it = QListWidgetItem(ad)
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Checked)
                    it.setToolTip(f"{n} öğe")
                    self.katmanlar.addItem(it)
                self.katmanlar.blockSignals(False)
            for i, g in enumerate(s.govdeler):
                ad = self.dosya_adi + (f" – {g.ad}" if len(s.govdeler) > 1 else "")
                kaynak = None if g.hata else {"tur": "3d", "alan": g.alan, "kapali": g.kapali,
                                              "katsayi": 2.0 if g.ag is not None and g.ag.sac_yuzeyi_mi() else 1.0,
                                              "varlik": g.tur}
                if kaynak and g.delikler:
                    kaynak["delikler"] = [d.sozluk() for d in g.delikler]
                if kaynak and g.ag is not None and g.ag.kenarlar:  # başka gövdeye değen kenarlar: önerilen kaynak
                    import profil
                    kaynak["kaynak_dikisleri"] = [[i, 1, round(profil.kenar_boyu(g.ag.kenarlar[i]), 3)]
                                                  for i in g.ag.oneri]
                if kaynak and g.ag is not None and g.ag.hacim():
                    kaynak["hacim"] = g.ag.hacim()  # kapalı çokgen ağ (3DFACE / polyface / mesh)
                if kaynak and g.sac is not None:
                    kaynak["sac"] = g.sac.sozluk()
                if kaynak and g.profil is not None:
                    # profil: dış, iç ve uç yüzeyler ayrı; iç yüzey uçlardan boşluk ölçüsü kadar boyanır
                    kaynak.update(profil=g.profil.sozluk(), ic_boya="uçlardan",
                                  ic_derinlik=round(g.profil.bosluk, 1), uc_boya=True)
                self.ogeler.append(("3d", g.ag, kaynak, ad, g.hata))
            for i, p in enumerate(s.parcalar):
                ad = p.ad or self.dosya_adi + (f" – parça {i + 1}" if len(s.parcalar) > 1 else "")
                self.ogeler.append(("2d", p, self._kaynak2d(p), ad, ""))
            if s.etiketli:
                self.kalinlik_notu.setText(f"{s.etiketli} parça yazıdaki K: (kalınlık) / P: (ad) etiketinden okundu")
            uyarilar += s.uyarilar
            if s.kesikli:
                uyarilar.append(f"{s.kesikli} kesikli çizgi alınmadı (eksen / gizli / büküm çizgisi).")
            atlanan = {k: v for k, v in s.atlanan.items() if k not in ("TEXT", "MTEXT", "DIMENSION", "HATCH",
                                                                       "POINT", "ATTDEF", "ATTRIB", "VIEWPORT",
                                                                       "SOLID", "LEADER", "MLEADER")}
            if atlanan:
                uyarilar.append("Alana girmeyen öğeler: " + ", ".join(f"{k} ×{v}" for k, v in atlanan.items()))
        if not self.ogeler:
            uyarilar.insert(0, "Dosyada alan hesaplanabilecek kapalı kontur ya da 3D gövde bulunamadı.")
        self._uyari_taban = "\n".join(uyarilar)
        self._tabloyu_doldur()
        self._uyari_yenile()

    def _uyari_yenile(self, *_):
        """Uyarı yazısı: çözümleme uyarıları; birleştirme açıkken hesaplanamayan gövde varsa toplamın eksik kalacağı."""
        metin = self._uyari_taban
        hatali = sum(1 for t, _g, _k, _a, h in self.ogeler if t == "3d" and h)
        if self.birlestir.isChecked() and hatali:
            metin += ("\n" if metin else "") + (f"{hatali} 3D gövde hesaplanamadı; tek parça toplamına girmez, "
                                                "toplam eksik olur.")
        self.uyari.setText(metin)

    @staticmethod
    def _anahtar(p: Parca2D) -> tuple:
        k = p.dis.kutu
        return round(p.yuz_alani, 3), round(p.toplam_cevre, 3), round(k[0], 3), round(k[1], 3)

    def _kaynak2d(self, p: Parca2D) -> Dict:
        w, h = p.olcu
        return {"tur": "2d", "yuz_alani": p.yuz_alani, "cevre": p.toplam_cevre, "olcu": [w, h],
                "delik": len(p.delikler),
                "kalinlik": self.kalinliklar.get(self._anahtar(p), p.kalinlik if p.kalinlik is not None else
                                                 self.katman_kalinlik.get(p.dis.katman.upper(), self.kalinlik.value())),
                "yuz_sayisi": 2, "kenar": True}

    def _kalinlik_tumu(self, x: float):
        for tur, geo, *_ in self.ogeler:
            if tur == "2d":
                self.kalinliklar[self._anahtar(geo)] = x
        self._alanlari_yenile()

    def _kalinlik_satir(self, r: int, x: float):
        tur, geo, kaynak, ad, hata = self.ogeler[r]
        self.kalinliklar[self._anahtar(geo)] = x
        kaynak = self._kaynak2d(geo)
        self.ogeler[r] = (tur, geo, kaynak, ad, hata)
        self.tablo.item(r, 4).setText(sayi(kaynak_alani(kaynak) / 1e6, 4))

    def _alanlari_yenile(self, *_):
        for i, (tur, geo, kaynak, ad, hata) in enumerate(self.ogeler):
            if tur == "2d":
                self.ogeler[i] = (tur, geo, self._kaynak2d(geo), ad, hata)
        self._tabloyu_doldur(koru=True)

    def _tabloyu_doldur(self, koru: bool = False):
        eski = {}
        if koru:
            for r in range(self.tablo.rowCount()):
                sp = self.tablo.cellWidget(r, 5)
                eski[r] = (self.tablo.item(r, 0).checkState(), self.tablo.item(r, 0).text(),
                           sp.value() if sp is not None else 1)
        uc_var = any(t == "3d" and k for t, _, k, _, _ in self.ogeler)
        self.tablo.setRowCount(len(self.ogeler))
        for r, (tur, geo, kaynak, ad, hata) in enumerate(self.ogeler):
            it = QTableWidgetItem(eski.get(r, (None, ad))[1])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
            if hata:
                it.setFlags(it.flags() & ~Qt.ItemIsUserCheckable & ~Qt.ItemIsEnabled)
                it.setCheckState(Qt.Unchecked)
            elif r in eski:
                it.setCheckState(eski[r][0])
            else:
                it.setCheckState(Qt.Checked if (tur == "3d" or not uc_var) else Qt.Unchecked)
            self.tablo.setItem(r, 0, it)
            self.tablo.removeCellWidget(r, 3)
            if tur == "2d":
                olcu = f"{sayi(geo.olcu[0], 1)} × {sayi(geo.olcu[1], 1)}"
                durum = f"{len(geo.delikler)} delik" if geo.delikler else ""
                kal = _cift(0.0, 100.0, float(kaynak["kalinlik"]), 2, 0.1, "mm")
                kal.valueChanged.connect(lambda x, r=r: self._kalinlik_satir(r, x))
                self.tablo.setCellWidget(r, 3, kal)
            elif geo is not None:
                (x0, y0, z0), (x1, y1, z1) = geo.kutu()
                olcu = f"{sayi(x1 - x0, 1)} × {sayi(y1 - y0, 1)} × {sayi(z1 - z0, 1)}"
                durum = hata or ("" if kaynak and kaynak["kapali"] else
                                 "açık yüzey: sac yüzeyi ise ayrıntıdan × 2 yüz seçin")
                if kaynak and kaynak.get("sac"):
                    durum = "sac (kalınlık modelden): iki yüz + kesim kenarları"
                elif kaynak and float(kaynak.get("katsayi", 1)) == 2:
                    durum = "açık yüzey modeli: iki yüz sayıldı"
                if kaynak and kaynak.get("profil"):
                    pr = kaynak["profil"]
                    durum = ("profil: dış, iç (uçlardan " + sayi(kaynak["ic_derinlik"], 0) + " mm), uç kesitleri"
                             if pr.get("ic") else "profil (dolu): dış, uç kesitleri")
            else:
                olcu, durum = "", hata
            alan = sayi(kaynak_alani(kaynak) / 1e6, 4) if kaynak else "—"
            kal = "" if tur == "2d" else (f"{sayi(kaynak['sac']['kalinlik'], 2)} mm" if kaynak and kaynak.get("sac")
                                          else "—")
            for c, x in zip((1, 2, 3, 4, 6), [("2D açınım" if tur == "2d" else "3D gövde"), olcu, kal, alan, durum]):
                h = QTableWidgetItem(x)
                h.setFlags(h.flags() & ~Qt.ItemIsEditable)
                if c == 4:
                    h.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if hata:
                    h.setForeground(QBrush(QColor(170, 40, 40)))
                    h.setToolTip(hata)
                self.tablo.setItem(r, c, h)
            adet = QSpinBox()
            adet.setRange(1, 10_000_000)
            adet.setValue(eski[r][2] if r in eski else 1)
            adet.setKeyboardTracking(False)
            adet.setEnabled(not hata)
            adet.setToolTip("Bu parçadan kaç adet boyanacak")
            self.tablo.setCellWidget(r, 5, adet)
            self.tablo.setItem(r, 5, QTableWidgetItem())
            self.tablo.item(r, 5).setFlags(Qt.NoItemFlags)
        self.tablo.setColumnHidden(3, not any(t == "2d" or (k and k.get("sac")) for t, _, k, *_ in self.ogeler))
        if self.dxf:  # 2D sac kalınlığı satırları yalnız 2D parça varken (3D sacın kalınlığı modelden)
            iki_d = any(t == "2d" for t, *_ in self.ogeler)
            self._form.setRowVisible(self._kal_satir, iki_d)
            self._form.setRowVisible(self._kal_bilgi, iki_d)
        self.birlestir.setEnabled(sum(1 for t, _, k, *_ in self.ogeler if t == "3d" and k) >= 2)
        self.rapor_dugmesi.setVisible(any(h for *_, h in self.ogeler))
        self.tablo.resizeColumnsToContents()
        if self.ogeler and not self.tablo.selectedItems():
            self.tablo.selectRow(0)
        self._sec()

    def hata_raporu_metni(self) -> str:
        from surum import SURUM
        satir = [f"Toz Boya Hesabı {SURUM} — hata raporu", f"Dosya: {os.path.basename(self.yol)}", ""]
        govdeler = {g.ad: g for g in (self.sonuc.govdeler if self.sonuc else [])}
        for tur, geo, kaynak, ad, hata in self.ogeler:
            if not hata:
                continue
            satir += [f"== {ad}", hata]
            g = govdeler.get(ad.split(" – ")[-1]) if " – " in ad else next(iter(govdeler.values()), None)
            if g is not None and g.tani:
                satir.append(g.tani)
            satir.append("")
        return "\n".join(satir)

    def _hata_raporu(self):
        yol, _ = QFileDialog.getSaveFileName(self, "Hata ayrıntısı", self.dosya_adi + "_hata.txt", "Metin (*.txt)")
        if yol:
            with open(yol, "w", encoding="utf-8") as f:
                f.write(self.hata_raporu_metni())

    def _sec(self):
        r = self.tablo.currentRow()
        if 0 <= r < len(self.ogeler):
            tur, geo, kaynak, ad, hata = self.ogeler[r]
            self.onizleme.goster(geo, hata[:80] if hata else "")
        else:
            self.onizleme.goster(None)

    @staticmethod
    def _imza(tur, geo, kaynak) -> tuple:
        """(seçenekler, sayılar): seçenekler birebir, sayılar (alan, çevre, ölçüler) toleransla karşılaştırılır."""
        if tur == "2d":
            return (("2d", kaynak["kalinlik"]),
                    [kaynak["yuz_alani"], kaynak["cevre"]] + sorted(kaynak["olcu"]))
        a, b = geo.kutu() if geo is not None else ((0, 0, 0), (0, 0, 0))
        return ("3d", kaynak.get("kapali")), [kaynak["alan"]] + sorted(b[i] - a[i] for i in range(3))

    @staticmethod
    def _ayni_mi(x: list, y: list) -> bool:
        """Alan ve çevre milyonda bir (en az 0,05), ölçüler 0,05 mm içinde."""
        return (all(abs(p - q) <= max(0.05, 1e-6 * abs(p)) for p, q in zip(x[:-3], y[:-3]))
                and all(abs(p - q) <= 0.05 for p, q in zip(x[-3:], y[-3:])) and len(x) == len(y))

    def _birlesik_kalem(self, satirlar: List[int]) -> Kalem:
        """Seçili 3D gövdeler tek kalem: adet başına alan = Σ (gövde alanı × gövde adedi); adet 1."""
        toplam, kapali, geolar, hacim, delikler = 0.0, True, [], 0.0, []
        kenarlar, carpan, dikis, oneri = [], [], [], []
        yd, ya, yt, ysec = [], [], [], {}
        for r in satirlar:
            _, geo, kaynak, _, _ = self.ogeler[r]
            n = self.tablo.cellWidget(r, 5).value()
            if isinstance(geo, Ag) and geo.kenarlar:
                dikis += [[d[0] + len(kenarlar), d[1], d[2] * n] for d in kaynak.get("kaynak_dikisleri", [])]
                oneri += [i + len(kenarlar) for i in geo.oneri]
                kenarlar += geo.kenarlar
                carpan += [n] * len(geo.kenarlar)
            if isinstance(geo, Ag) and geo.yuz_donguleri:
                for ad, sec in (kaynak.get("yuzey_secimi") or {}).items():
                    ysec.setdefault(ad, []).extend([x[0] + len(yd), x[1] * n] for x in sec)
                yd += geo.yuz_donguleri
                ya += [a * n for a in geo.yuz_alanlari]
                yt += geo.yuz_turleri
            delikler += list(kaynak.get("delikler", [])) * self.tablo.cellWidget(r, 5).value()
            toplam += kaynak_alani(kaynak) * self.tablo.cellWidget(r, 5).value()
            h = kaynak_hacmi(kaynak)
            hacim = None if h is None or hacim is None else hacim + h * self.tablo.cellWidget(r, 5).value()
            kapali = kapali and bool(kaynak.get("kapali", True))
            if isinstance(geo, Ag) and geo.yuzler:
                geolar.append(geo)
        kaynak = {"tur": "3d", "alan": toplam, "kapali": kapali, "katsayi": 1.0,
                  "varlik": f"birleşik, {len(satirlar)} gövde"}
        if hacim:
            kaynak["hacim"] = hacim
        if delikler:
            kaynak["delikler"] = delikler
        if kenarlar:
            kaynak["kaynak_dikisleri"] = dikis
        if ysec:
            kaynak["yuzey_secimi"] = ysec
        k = Kalem(self.dosya_adi, kaynak, toz=self.toz, dosya=self.yol)
        # ACIS katılarının önizlemesi kenar döngüleridir (tel): dolu çizilirse delik ve havşa döngüleri kapanır
        k.geo = Ag([y for g in geolar for y in g.yuzler], self.dosya_adi, tel=any(g.tel for g in geolar),
                   vurgu=[d for g in geolar for d in g.vurgu], kenarlar=kenarlar, kenar_carpan=carpan,
                   oneri=oneri, yardimci=[d for g in geolar for d in g.yardimci], yuz_donguleri=yd,
                   yuz_alanlari=ya, yuz_turleri=yt) if geolar else None
        return k

    def kalemler(self) -> List[Kalem]:
        out: List[Kalem] = []
        gruplar: List[tuple] = []   # (seçenekler, sayılar, kalem)
        uc_d = [r for r, (tur, _, kaynak, _, _) in enumerate(self.ogeler)
                if tur == "3d" and kaynak is not None and self.tablo.item(r, 0).checkState() == Qt.Checked]
        birlesik = self.birlestir.isChecked() and len(uc_d) >= 2
        for r, (tur, geo, kaynak, ad, hata) in enumerate(self.ogeler):
            it = self.tablo.item(r, 0)
            if kaynak is None or it.checkState() != Qt.Checked:
                continue
            if birlesik and tur == "3d":
                if r == uc_d[0]:               # birleşik kalem ilk 3D gövdenin yerine girer
                    out.append(self._birlesik_kalem(uc_d))
                continue
            secenek, sayilar = self._imza(tur, geo, kaynak)
            adet = self.tablo.cellWidget(r, 5).value()
            if self.topla.isChecked():
                es = next((k for s_, n_, k in gruplar if s_ == secenek and self._ayni_mi(n_, sayilar)), None)
                if es is not None:
                    es.adet += adet
                    continue
            k = Kalem(it.text().strip() or ad, copy.deepcopy(kaynak), toz=self.toz, dosya=self.yol)
            k.adet = adet
            k.geo = geo
            out.append(k)
            gruplar.append((secenek, sayilar, k))
        return out


# ---------------------------------------------------------------- PDF taslağı

ABKANT = "Abkant sac (açınım)"


class PdfAktar(QDialog):
    """Teknik resim PDF'inden okunan yazıyla kalem: ad, renk (toz), ölçü, kalınlık. Alan iki yoldan: abkant
    açınımı (kenar ölçüleri + kalınlık + büküm payı → düz levha) ya da elle alan. Çizgilerden alan okunmaz."""

    def __init__(self, yol: str, varsayilan_toz: str, ayar: Ayarlar, parent=None):
        super().__init__(parent)
        self.yol = yol
        self.ayar = ayar
        self.sonuc = pdf_oku.oku(yol)
        s = self.sonuc
        self.setWindowTitle(f"PDF'ten taslak kalem — {os.path.basename(yol)}")
        self.resize(560, 520)
        v = QVBoxLayout(self)
        form = QFormLayout()
        self.ad = QLineEdit(s.ad or os.path.splitext(os.path.basename(yol))[0])
        form.addRow("Parça adı", self.ad)
        if s.urun:
            form.addRow("Ürün", QLabel(s.urun))
        form.addRow("Ölçüler (mm)", QLabel(" × ".join(f"{x:g}" for x in s.olculer) or "çizimde ölçü yazısı yok"))
        self.renk = QLineEdit(s.renk)
        form.addRow("Renk", self.renk)
        self.toz = QComboBox()
        self.toz.addItems([t.ad for t in ayar.tozlar])
        self.toz.setCurrentText(self._toz_bul(s.renk) or varsayilan_toz)
        form.addRow("Toz", self.toz)
        self.adet = QSpinBox()
        self.adet.setRange(1, 10_000_000)
        self.adet.setValue(s.adet or 1)
        form.addRow("Adet", self.adet)
        self.hesap = QComboBox()
        self.hesap.addItems(["Abkant açınımı (düz levha)", "Elle alan"])
        self.hesap.setToolTip("Abkantla bükülen sac ürünlerde açınım: kenar ölçüleri, kalınlık ve büküm payıyla düz "
                              "levha alanı hesaplanır")
        form.addRow("Alan hesabı", self.hesap)
        # elle alan seçeneği
        self.kalinlik = QDoubleSpinBox()
        self.kalinlik.setRange(0.0, 100.0)
        self.kalinlik.setDecimals(2)
        self.kalinlik.setSuffix(" mm")
        self.kalinlik.setSpecialValueText("yazmıyor")
        self.kalinlik.setValue(s.kalinlik or 0.0)
        form.addRow("Sac kalınlığı", self.kalinlik)
        self.alan = QDoubleSpinBox()
        self.alan.setRange(0.0, 1000.0)
        self.alan.setDecimals(4)
        self.alan.setSuffix(" m²")
        self.alan.setToolTip("Biliyorsanız adet başına boyanacak alanı girin")
        form.addRow("Boyanacak alan / adet", self.alan)
        self._form = form
        v.addLayout(form)
        # abkant seçeneği: kalıp formu; 3 ölçüden U biçimi tahmin edilir (üst = en büyük, bacaklar = ortanca,
        # genişlik = en küçük), çizime göre düzeltilir
        ol = s.olculer
        oneri = ({"k1": ol[1], "k2": ol[0], "k3": ol[1], "W": ol[2]} if len(ol) == 3 else
                 {"k1": ol[0], "k2": 0.0, "k3": 0.0, "W": ol[1]} if len(ol) == 2 else {"k1": 0.0, "k2": 0.0, "k3": 0.0})
        oneri.update(k4=0.0, k5=0.0, t=s.kalinlik or 0.0)
        self.abkant = KalipFormu(ABKANT, oneri)
        self.abkant_kutu = QGroupBox("Abkant açınımı")
        QVBoxLayout(self.abkant_kutu).addWidget(self.abkant)
        if len(ol) == 3:
            self.abkant_kutu.setToolTip(f"Ölçülerden tahmin: U biçimi {ol[1]:g} + {ol[0]:g} + {ol[1]:g}, "
                                        f"genişlik {ol[2]:g}. Çizime göre düzeltin.")
        v.addWidget(self.abkant_kutu)
        self.sonuc_etiketi = QLabel()
        self.sonuc_etiketi.setWordWrap(True)
        v.addWidget(self.sonuc_etiketi)
        self.abkant.degisti.connect(self._hesapla)
        self.hesap.currentIndexChanged.connect(self._hesapla)
        if s.uyarilar:
            u = QLabel("\n".join(s.uyarilar))
            u.setWordWrap(True)
            u.setStyleSheet("color: #8a5a00;")
            v.addWidget(u)
        if s.notlar:
            v.addWidget(QLabel("Çizimdeki notlar:"))
            n = QPlainTextEdit("\n".join(s.notlar))
            n.setReadOnly(True)
            n.setMaximumHeight(110)
            v.addWidget(n)
        v.addStretch(1)
        dugmeler = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.tamam = dugmeler.button(QDialogButtonBox.Ok)
        self.tamam.setText("Kalemi ekle")
        dugmeler.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        dugmeler.accepted.connect(self.accept)
        dugmeler.rejected.connect(self.reject)
        v.addWidget(dugmeler)
        self._hesapla()

    def _acinim_mi(self) -> bool:
        return self.hesap.currentIndex() == 0

    def _hesapla(self, *_):
        ac = self._acinim_mi()
        self._form.setRowVisible(self.kalinlik, not ac)
        self._form.setRowVisible(self.alan, not ac)
        self.abkant_kutu.setVisible(ac)
        self.sonuc_etiketi.setVisible(ac)
        self.tamam.setEnabled(True)
        if not ac:
            return
        try:
            d = self.abkant.deger()
            L, W = kaliplar.abkant_acinim(d)
            a = kaliplar.alan(ABKANT, d)
            self.sonuc_etiketi.setText(f"Açınım: <b>{sayi(L, 1)} × {sayi(W, 1)} mm</b> · boyanacak alan "
                                       f"<b>{sayi(a / 1e6, 4)} m²</b> / adet")
        except ValueError as h:
            self.sonuc_etiketi.setText(f"<span style='color:#a02020'>{h}</span>")
            self.tamam.setEnabled(False)

    def _toz_bul(self, renk: str) -> str:
        """Renk yazısı bir tozun adında geçiyorsa (ya da tersi) o toz; yoksa ''."""
        r = pdf_oku._n(renk)
        if not r:
            return ""
        for t in self.ayar.tozlar:
            n = pdf_oku._n(t.ad)
            if r in n or (len(n) >= 3 and n in r):
                return t.ad
        return ""

    def kalem(self) -> Kalem:
        s = self.sonuc
        ozet_ = [f"ölçü {' × '.join(f'{x:g}' for x in s.olculer)} mm"] if s.olculer else []
        if self.renk.text().strip():
            ozet_.append(f"renk {self.renk.text().strip()}")
        if self.kalinlik.value() > 0:
            ozet_.append(f"sac {self.kalinlik.value():g} mm")
        if s.urun:
            ozet_.append(f"ürün {s.urun}")
        if self._acinim_mi():
            kaynak = {"tur": "kalip", "kalip": ABKANT, "deger": self.abkant.deger()}
        else:
            kaynak = {"tur": "elle", "alan_m2": self.alan.value(), "pdf": "; ".join(ozet_)}
        k = Kalem(self.ad.text().strip() or "PDF parça", kaynak, adet=self.adet.value(), toz=self.toz.currentText(),
                  dosya=self.yol)
        return k


# ---------------------------------------------------------------- kalıp formu

class KalipFormu(QWidget):
    degisti = Signal()

    def __init__(self, ad: str, deger: Optional[Dict] = None, parent=None):
        super().__init__(parent)
        self.ad = ad
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.alanlar = {}
        deger = {**kaliplar.varsayilanlar(ad), **(deger or {})}
        for o in kaliplar.KALIPLAR[ad].olculer:
            if o.secenekler:
                w = QComboBox()
                w.addItems(list(o.secenekler))
                w.setCurrentText(str(deger[o.anahtar]))
                w.currentIndexChanged.connect(self.degisti)
            else:
                w = _cift(0.0, 100000.0, float(deger[o.anahtar]), 2, 1.0, o.birim)
                w.valueChanged.connect(self.degisti)
            if o.ipucu:
                w.setToolTip(o.ipucu)
            self.alanlar[o.anahtar] = w
            self.form.addRow(o.etiket, w)

    def deger(self) -> Dict:
        return {k: (w.currentText() if isinstance(w, QComboBox) else w.value()) for k, w in self.alanlar.items()}


class KaynakGorunum(QWidget):
    """3D gövdenin kenarları; fareyle döndürülür (sürükle), yakınlaştırılır (tekerlek). Tıklanan kenarın durumu
    döner: seçilmemiş → tek taraflı → iki taraflı → seçilmemiş. Önerilen kenarlar yeşil kesikli."""
    degisti = Signal()
    RENK = {1: QColor(230, 120, 0), 2: QColor(200, 30, 30)}

    def __init__(self, ag: Ag, secim: Dict[int, int], parent=None):
        super().__init__(parent)
        self.ag, self.secim = ag, secim
        self.setMinimumSize(560, 420)
        self.setMouseTracking(True)
        self.yaw, self.pitch, self.zoom = math.radians(-35), math.radians(30), 1.0
        pts = [q for k in ag.kenarlar for q in k] or [q for y in ag.yuzler for q in y] or [(0, 0, 0)]
        self.merkez = tuple((max(q[i] for q in pts) + min(q[i] for q in pts)) / 2 for i in range(3))
        self.boy = max(max(q[i] for q in pts) - min(q[i] for q in pts) for i in range(3)) or 1.0
        self._bas = None
        self._suruklendi = False
        self.ustteki = -1
        self._ekran: List[List[QPointF]] = []

    def _izdus(self):
        cy, sy, cp, sp = math.cos(self.yaw), math.sin(self.yaw), math.cos(self.pitch), math.sin(self.pitch)
        olcek = 0.8 * min(self.width(), self.height()) / self.boy * self.zoom
        ox, oy, mx, my, mz = self.width() / 2, self.height() / 2, *self.merkez

        def f(q):
            x, y, z = q[0] - mx, q[1] - my, q[2] - mz
            x1, y1 = cy * x - sy * y, sy * x + cy * y          # z ekseni çevresinde
            y2, z2 = cp * y1 - sp * z, sp * y1 + cp * z          # yatay eksen çevresinde
            return QPointF(ox + olcek * x1, oy - olcek * z2), y2  # y2: derinlik
        return f

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), self.palette().base())
        f = self._izdus()
        p.setPen(QPen(QColor(180, 190, 200), 0.8))
        if not self.ag.kenarlar:
            for y in self.ag.yuzler:
                p.drawPolygon(QPolygonF([f(q)[0] for q in y]))
        for y in self.ag.yardimci:
            p.drawPolyline(QPolygonF([f(q)[0] for q in y]))
        self._ekran = [[f(q)[0] for q in k] for k in self.ag.kenarlar]
        oneri = set(self.ag.oneri)
        for i, k in enumerate(self._ekran):
            taraf = self.secim.get(i, 0)
            if taraf:
                p.setPen(QPen(self.RENK[taraf], 4.0 if taraf == 2 else 3.0))
            elif i in oneri:
                p.setPen(QPen(QColor(40, 150, 60), 2.0, Qt.DashLine))
            else:
                p.setPen(QPen(QColor(30, 80, 140), 1.0))
            if i == self.ustteki:
                pen = p.pen()
                pen.setWidthF(pen.widthF() + 2)
                p.setPen(pen)
            p.drawPolyline(QPolygonF(k))
        p.setPen(self.palette().text().color())
        p.drawText(QRectF(8, self.height() - 22, self.width() - 16, 18), Qt.AlignLeft,
                   "Tıkla: tek taraf → iki taraf → kaldır · sürükle: döndür · tekerlek: yakınlaştır")

    def _en_yakin(self, pt: QPointF, esik: float = 7.0) -> int:
        en, sec = esik, -1
        for i, k in enumerate(self._ekran):
            for a, b in zip(k, k[1:]):
                dx, dy = b.x() - a.x(), b.y() - a.y()
                l2 = dx * dx + dy * dy
                t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((pt.x() - a.x()) * dx + (pt.y() - a.y()) * dy) / l2))
                d = math.hypot(pt.x() - a.x() - t * dx, pt.y() - a.y() - t * dy)
                if d < en:
                    en, sec = d, i
        return sec

    def mousePressEvent(self, e):
        self._bas = e.position()
        self._suruklendi = False

    def mouseMoveEvent(self, e):
        if self._bas is not None and e.buttons():
            d = e.position() - self._bas
            if abs(d.x()) + abs(d.y()) > 3:
                self._suruklendi = True
                self.yaw += d.x() * 0.01
                self.pitch = max(-math.pi / 2, min(math.pi / 2, self.pitch + d.y() * 0.01))
                self._bas = e.position()
                self.update()
            return
        i = self._en_yakin(e.position())
        if i != self.ustteki:
            self.ustteki = i
            self.update()

    def mouseReleaseEvent(self, e):
        if not self._suruklendi:
            self.tikla(self._en_yakin(e.position()))
        self._bas = None

    def tikla(self, i: int):
        if i < 0:
            return
        t = (self.secim.get(i, 0) + 1) % 3
        if t:
            self.secim[i] = t
        else:
            self.secim.pop(i, None)
        self.update()
        self.degisti.emit()

    def wheelEvent(self, e):
        self.zoom = max(0.2, min(20.0, self.zoom * (1.15 if e.angleDelta().y() > 0 else 1 / 1.15)))
        self.update()


class KaynakPenceresi(QDialog):
    """3D gövdeden kaynak dikişi seçimi: seçilen kenarların boyu (iki taraflı ×2) toplanır."""

    def __init__(self, ag: Ag, dikisler: List[list], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kaynak yerleri")
        self.resize(900, 640)
        self.ag = ag
        secim = {int(d[0]): int(d[1]) for d in dikisler if 0 <= int(d[0]) < len(ag.kenarlar)}
        v = QVBoxLayout(self)
        self.gorunum = KaynakGorunum(ag, secim)
        v.addWidget(self.gorunum, 1)
        self.ozet = QLabel()
        v.addWidget(self.ozet)
        h = QHBoxLayout()
        oneri = QPushButton(f"Önerileri seç ({len(ag.oneri)})")
        oneri.setToolTip("Başka gövdeye değen kenarlar (yeşil kesikli): tek taraflı seçilir")
        oneri.setEnabled(bool(ag.oneri))
        oneri.clicked.connect(self._oneriler)
        temizle = QPushButton("Seçimi temizle")
        temizle.clicked.connect(self._temizle)
        h.addWidget(oneri)
        h.addWidget(temizle)
        h.addStretch(1)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.button(QDialogButtonBox.Ok).setText("Tamam")
        b.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        h.addWidget(b)
        v.addLayout(h)
        self.gorunum.degisti.connect(self._ozet)
        self._ozet()

    def boy(self, i: int) -> float:
        import profil
        c = self.ag.kenar_carpan[i] if i < len(self.ag.kenar_carpan) else 1
        return profil.kenar_boyu(self.ag.kenarlar[i]) * c

    def dikisler(self) -> List[list]:
        return [[i, t, round(self.boy(i), 3)] for i, t in sorted(self.gorunum.secim.items())]

    def _ozet(self):
        d = self.dikisler()
        tek = sum(x[2] for x in d if x[1] == 1)
        cift = sum(x[2] for x in d if x[1] == 2)
        self.ozet.setText(f"<b>{len(d)}</b> dikiş: tek taraflı {sayi(tek, 1)} mm, "
                          f"<span style='color:#c81e1e'>iki taraflı {sayi(cift, 1)} mm (×2)</span> · "
                          f"toplam kaynak <b>{sayi((tek + 2 * cift) / 1000, 3)} m</b>")

    def _oneriler(self):
        for i in self.ag.oneri:
            self.gorunum.secim.setdefault(i, 1)
        self.gorunum.update()
        self._ozet()

    def _temizle(self):
        self.gorunum.secim.clear()
        self.gorunum.update()
        self._ozet()


YUZ_ADLARI = {"duzlem": "Düzlem", "silindir": "Silindir", "koni": "Koni", "kure": "Küre", "torus": "Simit",
              "spline": "Serbest yüzey", "eliptik": "Eliptik silindir"}


def _zarf2(pts: List[QPointF]) -> List[QPointF]:
    """Ekrandaki noktaların dışbükey zarfı (eğri yüzün izdüşümü için)."""
    p = sorted({(q.x(), q.y()) for q in pts})
    if len(p) < 3:
        return [QPointF(*q) for q in p]

    def cap(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    alt, ust = [], []
    for q in p:
        while len(alt) >= 2 and cap(alt[-2], alt[-1], q) <= 0:
            alt.pop()
        alt.append(q)
    for q in reversed(p):
        while len(ust) >= 2 and cap(ust[-2], ust[-1], q) <= 0:
            ust.pop()
        ust.append(q)
    return [QPointF(*q) for q in alt[:-1] + ust[:-1]]


class YuzeyGorunum(KaynakGorunum):
    """3D gövdenin yüzleri: tıklanan yüz seçilir / bırakılır (polisaj vb. alanı). Düzlem yüz döngüleriyle
    (delikler boş), eğri yüz izdüşümünün zarfıyla tutulur; üst üste binende bakana en yakın olan seçilir."""
    SECILI = QColor(230, 120, 0, 130)

    def __init__(self, ag: Ag, secim: set, parent=None):
        super().__init__(ag, {}, parent)
        self.secili = secim
        self._yollar: List[tuple] = []   # (QPainterPath, derinlik)

    def _yol(self, i: int, f) -> tuple:
        donguler = self.ag.yuz_donguleri[i]
        izd = [[f(q) for q in d] for d in donguler]
        derin = [z for d in izd for _, z in d]
        yol = QPainterPath()
        yol.setFillRule(Qt.OddEvenFill)
        tur = self.ag.yuz_turleri[i] if i < len(self.ag.yuz_turleri) else ""
        if tur == "duzlem":
            for d in izd:
                yol.addPolygon(QPolygonF([q for q, _ in d]))
                yol.closeSubpath()
        else:
            yol.addPolygon(QPolygonF(_zarf2([q for d in izd for q, _ in d])))
            yol.closeSubpath()
        return yol, (sum(derin) / len(derin) if derin else 0.0)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), self.palette().base())
        f = self._izdus()
        self._yollar = [self._yol(i, f) for i in range(len(self.ag.yuz_donguleri))]
        sira = sorted(range(len(self._yollar)), key=lambda i: -self._yollar[i][1])  # uzaktan yakına
        p.setPen(Qt.NoPen)
        for i in sira:
            if i in self.secili or i == self.ustteki:
                p.setBrush(self.SECILI if i in self.secili else QColor(60, 140, 220, 70))
                p.drawPath(self._yollar[i][0])
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(180, 190, 200), 0.8))
        for y in self.ag.yardimci:
            p.drawPolyline(QPolygonF([f(q)[0] for q in y]))
        p.setPen(QPen(QColor(30, 80, 140), 1.0))
        for k in self.ag.kenarlar or [d for y in self.ag.yuz_donguleri for d in y]:
            p.drawPolyline(QPolygonF([f(q)[0] for q in k]))
        p.setPen(self.palette().text().color())
        p.drawText(QRectF(8, self.height() - 22, self.width() - 16, 18), Qt.AlignLeft,
                   "Tıkla: yüzeyi seç / bırak · sürükle: döndür · tekerlek: yakınlaştır")

    def _en_yakin(self, pt: QPointF, esik: float = 0.0) -> int:
        if not self._yollar:
            self._yollar = [self._yol(i, self._izdus()) for i in range(len(self.ag.yuz_donguleri))]
        adaylar = [(z, i) for i, (yol, z) in enumerate(self._yollar) if yol.contains(pt)]
        return min(adaylar)[1] if adaylar else -1

    def tikla(self, i: int):
        if i < 0:
            return
        self.secili ^= {i}
        self.update()
        self.degisti.emit()

    def resizeEvent(self, e):
        self._yollar = []
        super().resizeEvent(e)


class YuzeyPenceresi(QDialog):
    """3D gövdeden yüzey seçimi (polisaj vb.): seçilen yüzlerin alanı toplanır (m²)."""

    def __init__(self, ag: Ag, secim: List[list], islem: str = "Polisaj", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{islem} yüzeyleri")
        self.resize(1000, 640)
        self.ag = ag
        n = len(ag.yuz_donguleri)
        v = QVBoxLayout(self)
        ust = QHBoxLayout()
        v.addLayout(ust, 1)
        self.gorunum = YuzeyGorunum(ag, {int(x[0]) for x in secim if 0 <= int(x[0]) < n})
        ust.addWidget(self.gorunum, 1)
        self.liste = QListWidget()
        self.liste.setMaximumWidth(260)
        for i in range(n):
            tur = ag.yuz_turleri[i] if i < len(ag.yuz_turleri) else ""
            it = QListWidgetItem(f"{i + 1}. {YUZ_ADLARI.get(tur, tur or 'Yüz')} – {sayi(ag.yuz_alanlari[i], 0)} mm²")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            self.liste.addItem(it)
        self.liste.itemChanged.connect(self._listeden)
        self.liste.currentRowChanged.connect(self._vurgula)
        ust.addWidget(self.liste)
        self.ozet = QLabel()
        v.addWidget(self.ozet)
        h = QHBoxLayout()
        hepsi = QPushButton("Hepsini seç")
        hepsi.clicked.connect(lambda: self._ata(set(range(n))))
        temizle = QPushButton("Seçimi temizle")
        temizle.clicked.connect(lambda: self._ata(set()))
        h.addWidget(hepsi)
        h.addWidget(temizle)
        h.addStretch(1)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.button(QDialogButtonBox.Ok).setText("Tamam")
        b.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        h.addWidget(b)
        v.addLayout(h)
        self.gorunum.degisti.connect(self._ozet)
        self._ozet()

    def secim(self) -> List[list]:
        return [[i, round(self.ag.yuz_alanlari[i], 3)] for i in sorted(self.gorunum.secili)]

    def _ata(self, s: set):
        self.gorunum.secili.clear()
        self.gorunum.secili.update(s)
        self.gorunum.update()
        self._ozet()

    def _listeden(self, it: QListWidgetItem):
        i = self.liste.row(it)
        if (it.checkState() == Qt.Checked) != (i in self.gorunum.secili):
            self.gorunum.tikla(i)

    def _vurgula(self, i: int):
        self.gorunum.ustteki = i
        self.gorunum.update()

    def _ozet(self):
        self.liste.blockSignals(True)
        for i in range(self.liste.count()):
            self.liste.item(i).setCheckState(Qt.Checked if i in self.gorunum.secili else Qt.Unchecked)
        self.liste.blockSignals(False)
        s = self.secim()
        self.ozet.setText(f"<b>{len(s)}</b> yüzey seçili · toplam <b>{sayi(sum(x[1] for x in s) / 1e6, 4)} m²</b>"
                          f" (parçanın tümü {sayi(sum(self.ag.yuz_alanlari) / 1e6, 4)} m²)")


class KalipPenceresi(QDialog):
    def __init__(self, toz: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kalıptan ekle")
        self.toz = toz
        v = QVBoxLayout(self)
        ust = QFormLayout()
        v.addLayout(ust)
        self.secim = QComboBox()
        self.secim.addItems(list(kaliplar.KALIPLAR))
        ust.addRow("Parça tipi", self.secim)
        self.ad = QLineEdit()
        ust.addRow("Parça adı", self.ad)
        self.adet = QSpinBox()
        self.adet.setRange(1, 10_000_000)
        ust.addRow("Adet", self.adet)
        self.kutu = QGroupBox("Ölçüler")
        self.kutu_duzen = QVBoxLayout(self.kutu)
        v.addWidget(self.kutu)
        self.sonuc = QLabel()
        v.addWidget(self.sonuc)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.button(QDialogButtonBox.Ok).setText("Ekle")
        b.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        self.tamam = b.button(QDialogButtonBox.Ok)
        v.addWidget(b)
        self.form = None
        self.secim.currentTextChanged.connect(self._kur)
        self._kur(self.secim.currentText())

    def _kur(self, ad: str):
        if self.form is not None:
            self.form.setParent(None)
        self.form = KalipFormu(ad)
        self.form.degisti.connect(self._hesapla)
        self.kutu_duzen.addWidget(self.form)
        self.ad.setPlaceholderText(ad)
        self._hesapla()

    def _hesapla(self):
        try:
            a = kaliplar.alan(self.form.ad, self.form.deger())
            self.sonuc.setText(f"Boyanacak alan: <b>{sayi(a / 1e6, 4)} m²</b> / adet  ({sayi(a / 100, 1)} cm²)")
            self.tamam.setEnabled(True)
        except ValueError as h:
            self.sonuc.setText(f"<span style='color:#a02020'>{h}</span>")
            self.tamam.setEnabled(False)

    def kalem(self) -> Kalem:
        d = self.form.deger()
        return Kalem(self.ad.text().strip() or kaliplar.aciklama(self.form.ad, d),
                     {"tur": "kalip", "kalip": self.form.ad, "deger": d}, self.adet.value(), toz=self.toz)


# ---------------------------------------------------------------- açınım

def acinim_olculeri(k: Optional[Kalem]) -> Optional[Dict]:
    """Seçili kalemden açınım ölçüleri (dış çaplar): konik ayak / yuvarlak boru kalıbı ya da 3D konik profil."""
    if k is None:
        return None
    ky = k.kaynak
    if ky.get("tur") == "kalip" and ky.get("kalip") in ("Konik ayak (boru)", "Yuvarlak boru"):
        d = {**kaliplar.varsayilanlar(ky["kalip"]), **ky.get("deger", {})}
        if ky["kalip"] == "Yuvarlak boru":
            return {"d1": d["D"], "d2": d["D"], "boy": d["L"], "t": d["t"]}
        return {"d1": d["D2"], "d2": d["D1"], "boy": d["L"], "t": d["t"]}
    koni = (ky.get("profil") or {}).get("koni")
    if ky.get("tur") == "3d" and koni:
        return dict(koni)
    return None


class AcinimPenceresi(QDialog):
    """Konik / silindirik sac açınımı: ölçüler, önizleme, DXF."""

    def __init__(self, olcu: Optional[Dict] = None, ad: str = "", parent=None):
        super().__init__(parent)
        import acinim
        self.acinim = acinim
        self.ad = ad
        self.setWindowTitle("Açınım (DXF)")
        self.resize(760, 520)
        ana = QHBoxLayout(self)
        sol = QVBoxLayout()
        ana.addLayout(sol)
        f = QFormLayout()
        sol.addLayout(f)
        o = olcu or {}
        self.d_alt = _cift(0.1, 100000.0, float(o.get("d1") or 25.0), 2, 1, "mm")
        self.d_ust = _cift(0.1, 100000.0, float(o.get("d2") or 40.0), 2, 1, "mm")
        self.boy = _cift(0.1, 100000.0, float(o.get("boy") or 150.0), 2, 1, "mm")
        self.t = _cift(0.0, 100.0, float(o.get("t") or 1.5), 2, 0.1, "mm")
        self.yuzey = QComboBox()
        self.yuzey.addItems(["dış", "orta", "iç"])
        self.k = _cift(0.0, 1.0, 0.5, 2, 0.05)
        self.k.setToolTip("Nötr eksenin içten uzaklığı / kalınlık. 0,5: kalınlığın ortası")
        f.addRow("Alt çap", self.d_alt)
        f.addRow("Üst çap", self.d_ust)
        f.addRow("Boy (eksen)", self.boy)
        f.addRow("Sac kalınlığı", self.t)
        f.addRow("Çaplar hangi yüzeyden", self.yuzey)
        f.addRow("K faktörü", self.k)
        if o:
            not_ = QLabel("Ölçüler seçili parçadan alındı" + ("" if o.get("t") else "; kalınlık modelde yok, girin")
                          + ".")
            not_.setWordWrap(True)
            sol.addWidget(not_)
        self.sonuc = QLabel()
        self.sonuc.setWordWrap(True)
        sol.addWidget(self.sonuc)
        sol.addStretch(1)
        b = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        b.button(QDialogButtonBox.Save).setText("DXF kaydet…")
        b.button(QDialogButtonBox.Close).setText("Kapat")
        b.accepted.connect(self.kaydet)
        b.rejected.connect(self.reject)
        self.kaydet_dugmesi = b.button(QDialogButtonBox.Save)
        sol.addWidget(b)
        self.onizleme = Onizleme()
        self.onizleme.setMinimumWidth(380)
        ana.addWidget(self.onizleme, 1)
        for w in (self.d_alt, self.d_ust, self.boy, self.t, self.k):
            w.valueChanged.connect(self.hesapla)
        self.yuzey.currentIndexChanged.connect(self.hesapla)
        self.a = None
        self.hesapla()

    def hesapla(self, *_):
        try:
            self.a = self.acinim.hesapla(self.d_alt.value(), self.d_ust.value(), self.boy.value(), self.t.value(),
                                         self.yuzey.currentText(), self.k.value())
        except ValueError as h:
            self.a = None
            self.sonuc.setText(f"<span style='color:#a02020'>{h}</span>")
            self.onizleme.goster(None)
            self.kaydet_dugmesi.setEnabled(False)
            return
        a = self.a
        w, h = a.olcu
        if a.silindir:
            ayr = f"Dikdörtgen: <b>{sayi(w, 2)} × {sayi(h, 2)} mm</b> (nötr çap Ø{sayi(a.d1, 2)})"
        else:
            ayr = (f"Halka dilimi: iç R <b>{sayi(a.Ra, 2)}</b>, dış R <b>{sayi(a.Rb, 2)}</b> mm, açı "
                   f"<b>{sayi(a.aci, 3)}°</b><br>eğik boy {sayi(a.egik, 2)} mm, nötr çaplar Ø{sayi(a.d1, 2)} / "
                   f"Ø{sayi(a.d2, 2)}<br>Sac ölçüsü {sayi(w, 1)} × {sayi(h, 1)} mm")
        self.sonuc.setText(ayr + f"<br>Açınım alanı (bir yüz): {sayi(a.alan / 1e6, 4)} m²")
        from geometri import Kontur, Parca2D
        self.onizleme.goster(Parca2D(Kontur(a.cevre(180))), "")
        self.kaydet_dugmesi.setEnabled(True)

    def kaydet(self):
        if self.a is None:
            return
        yol, _ = QFileDialog.getSaveFileName(self, "Açınım DXF", (self.ad or "acinim") + "_acinim.dxf", "DXF (*.dxf)")
        if not yol:
            return
        if not yol.lower().endswith(".dxf"):
            yol += ".dxf"
        try:
            self.acinim.dxf_yaz(yol, self.a, self.ad)
        except OSError as h:
            QMessageBox.warning(self, UYGULAMA, f"Yazılamadı:\n{h}")


# ---------------------------------------------------------------- ayarlar

class AyarPenceresi(QDialog):
    def __init__(self, ayar: Ayarlar, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ayarlar, toz ve işlem fiyatları")
        self.resize(860, 640)
        v = QVBoxLayout(self)
        f = QFormLayout()
        v.addLayout(f)
        self.yontem = QComboBox()
        self.yontem.addItems(["Pratik: alan ÷ sarfiyat (1 kg tozla boyanan m²)",
                              "Teorik: kalınlık × yoğunluk ÷ transfer verimi"])
        self.yontem.setCurrentIndex(0 if ayar.pratik else 1)
        self.yontem.setToolTip("Pratik oran atölyede ölçülür (ör. 1 kg ile 6 m²); fire ve kayıplar içindedir.")
        f.addRow("Toz hesabı", self.yontem)
        self.verim = _cift(1.0, 100.0, ayar.verim * 100, 0, 1, "%")
        self.verim.setToolTip("Teorik yöntemde: tabancadan çıkan tozun parçada kalan oranı. Geri kazanımsız tek geçiş "
                              "%50–70, geri kazanımlı hat %90–95.")
        f.addRow("Transfer verimi", self.verim)
        self.proses = _cift(0.0, 1e6, ayar.proses_tl_m2, 2, 1)
        self.proses.setToolTip("Ön işlem, fırın, askı ve işçilik; m² başına. Yalnız toz maliyeti için 0.")
        f.addRow("Proses ücreti (/m²)", self.proses)
        self.para = QLineEdit(ayar.para)
        self.para.setMaximumWidth(80)
        f.addRow("Para birimi", self.para)
        self.metal = _cift(0.5, 25.0, ayar.metal_yogunluk, 2, 0.05, "g/cm³")
        self.metal.setToolTip("Parça ağırlığı için: çelik 7,85; paslanmaz 7,93; alüminyum 2,70")
        f.addRow("Metal yoğunluğu", self.metal)
        t = ayar.kaynak_teli
        self.tel_cap = _cift(0.3, 5.0, t.cap_mm, 2, 0.1, "mm")
        self.tel_fiyat = _cift(0.0, 1e6, t.kg_fiyat, 2, 1, f"{ayar.para}/kg")
        self.tel_makara = _cift(0.5, 1000.0, t.makara_kg, 1, 1, "kg")
        self.tel_bilgi = QLabel()
        h = QHBoxLayout()
        for ad, w in (("çap", self.tel_cap), ("fiyat", self.tel_fiyat), ("makara", self.tel_makara)):
            h.addWidget(QLabel(ad))
            h.addWidget(w)
        h.addStretch(1)
        f.addRow("Kaynak teli", h)
        f.addRow("", self.tel_bilgi)
        for w in (self.tel_cap, self.tel_fiyat, self.tel_makara, self.metal):
            w.valueChanged.connect(self._tel)
        self._tel()
        self.oda = QLineEdit(ayar.oda_yolu)
        self.oda.setPlaceholderText(dxf_oku.oda_bul() or "bulunamadı — DWG için kurun")
        self.oda.setToolTip("DWG açmak için ücretsiz ODA File Converter. Boş bırakılırsa Program Files\\ODA altında "
                            f"aranır. İndirme: {dxf_oku.ODA_INDIR}")
        gozat = QPushButton("Gözat…")
        gozat.clicked.connect(self._oda_sec)
        h = QHBoxLayout()
        h.addWidget(self.oda, 1)
        h.addWidget(gozat)
        f.addRow("ODA File Converter", h)
        self.guncelleme = QCheckBox("Yeni sürümü GitHub'dan sessizce indir, program kapanınca kur")
        self.guncelleme.setChecked(ayar.guncelleme)
        f.addRow("Güncelleme", self.guncelleme)
        v.addWidget(QLabel("Tozlar (sarfiyat atölyeden; yoğunluk ve kalınlık teknik föyden, yalnız teorik yöntemde):"))
        self.tablo = QTableWidget(0, 6)
        self.tablo.setHorizontalHeaderLabels(["Ad", "Sarfiyat (m²/kg)", "Fiyat (/kg)", "Yoğunluk (g/cm³)",
                                              "Kalınlık (µm)", "Teorik kaplama (m²/kg)"])
        self.tablo.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tablo.verticalHeader().hide()
        v.addWidget(self.tablo, 1)
        for t in ayar.tozlar:
            self._satir(t)
        h = QHBoxLayout()
        ekle, sil = QPushButton("Toz ekle"), QPushButton("Seçili tozu sil")
        ekle.clicked.connect(lambda: self._satir(Toz("Yeni toz")))
        sil.clicked.connect(self._sil)
        h.addWidget(ekle)
        h.addWidget(sil)
        h.addStretch(1)
        v.addLayout(h)
        v.addWidget(QLabel("İşlem fiyatları (boya dışı: kaynak, havşa, polisaj ...); kalemde adet başına miktar girilir:"))
        self.islem = QTableWidget(0, 5)
        self.islem.setHorizontalHeaderLabels(["İşlem", "Birim", "Birim fiyat", "Miktar nereden", "Tel"])
        self.islem.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.islem.setColumnWidth(3, 200)
        self.islem.verticalHeader().hide()
        v.addWidget(self.islem, 1)
        for i in ayar.islemler:
            self._islem_satiri(i)
        h = QHBoxLayout()
        ekle, sil = QPushButton("İşlem ekle"), QPushButton("Seçili işlemi sil")
        ekle.clicked.connect(lambda: self._islem_satiri(Islem("Yeni işlem")))
        sil.clicked.connect(lambda: self.islem.currentRow() >= 0 and self.islem.removeRow(self.islem.currentRow()))
        h.addWidget(ekle)
        h.addWidget(sil)
        h.addStretch(1)
        v.addLayout(h)
        self.kalici = QCheckBox("Bu ayarları yeni projeler için de sakla")
        self.kalici.setChecked(True)
        v.addWidget(self.kalici)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.button(QDialogButtonBox.Ok).setText("Tamam")
        b.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        b.accepted.connect(self._tamam)
        b.rejected.connect(self.reject)
        v.addWidget(b)
        self.yontem.currentIndexChanged.connect(self._yontem)
        self._yontem()

    def _yontem(self, *_):
        """Seçili yöntemin kullanmadığı alanlar pasif."""
        teorik = self.yontem.currentIndex() == 1
        self.verim.setEnabled(teorik)
        for r in range(self.tablo.rowCount()):
            self.tablo.cellWidget(r, 1).setEnabled(not teorik)
            for c in (3, 4):
                self.tablo.cellWidget(r, c).setEnabled(teorik)

    def kaynak_teli(self) -> KaynakTeli:
        return KaynakTeli(self.tel_cap.value(), self.tel_fiyat.value(), self.tel_makara.value())

    def _tel(self, *_):
        t, y = self.kaynak_teli(), self.metal.value()
        self.tel_bilgi.setText(f"1 m kaynak = 1 m tel = {sayi(t.kg_m(y) * 1000, 2)} g → {sayi(t.kg_m(y) * t.kg_fiyat, 2)}"
                               f" /m · 1 makara ≈ {sayi(t.makara_m(y), 0)} m kaynak. \"Tel\" işaretli işlemin metre "
                               "fiyatına eklenir (birim fiyat: işçilik).")

    def _oda_sec(self):
        yol, _ = QFileDialog.getOpenFileName(self, "ODA File Converter", "", "ODAFileConverter (ODAFileConverter*)")
        if yol:
            self.oda.setText(yol)

    def _satir(self, t: Toz):
        r = self.tablo.rowCount()
        self.tablo.insertRow(r)
        self.tablo.setItem(r, 0, QTableWidgetItem(t.ad))
        ss = _cift(0.1, 100.0, t.sarfiyat_m2_kg, 2, 0.1)
        fs = _cift(0.0, 1e6, t.fiyat, 2, 1)
        ys, ks = _cift(0.5, 5.0, t.yogunluk, 2, 0.05), _cift(10, 1000, t.kalinlik_um, 0, 5)
        for c, w in ((1, ss), (2, fs), (3, ys), (4, ks)):
            self.tablo.setCellWidget(r, c, w)
        kap = QTableWidgetItem()
        kap.setFlags(kap.flags() & ~Qt.ItemIsEditable)
        self.tablo.setItem(r, 5, kap)
        yenile = lambda *_: kap.setText(sayi(teorik_kaplama(ys.value(), ks.value()), 2))
        ys.valueChanged.connect(yenile)
        ks.valueChanged.connect(yenile)
        yenile()
        if hasattr(self, "yontem"):
            self._yontem()

    def _islem_satiri(self, i: Islem):
        r = self.islem.rowCount()
        self.islem.insertRow(r)
        self.islem.setItem(r, 0, QTableWidgetItem(i.ad))
        birim = QComboBox()
        birim.addItems(list(ISLEM_BIRIMLERI))
        birim.setCurrentText(i.birim)
        birim.setToolTip("sabit: kalemde 1 girilirse adet başına bir kez")
        self.islem.setCellWidget(r, 1, birim)
        self.islem.setCellWidget(r, 2, _cift(0.0, 1e7, i.fiyat, 2, 1))
        kaynak = QComboBox()
        for k, ad in ISLEM_KAYNAKLARI.items():
            kaynak.addItem(ad, k)
        kaynak.setCurrentIndex(max(0, kaynak.findData(i.kaynak)))
        self.islem.setCellWidget(r, 3, kaynak)
        tel = QCheckBox()
        tel.setChecked(i.tel)
        tel.setToolTip("Metre fiyatına kaynak teli maliyeti eklenir (birim m olmalı)")
        self.islem.setCellWidget(r, 4, tel)

    def islemler(self) -> List[Islem]:
        out = []
        for r in range(self.islem.rowCount()):
            ad = (self.islem.item(r, 0).text() or "").strip()
            if ad:
                out.append(Islem(ad, self.islem.cellWidget(r, 1).currentText(), self.islem.cellWidget(r, 2).value(),
                                 self.islem.cellWidget(r, 3).currentData() or "",
                                 self.islem.cellWidget(r, 4).isChecked()))
        return out

    def _sil(self):
        r = self.tablo.currentRow()
        if r >= 0 and self.tablo.rowCount() > 1:
            self.tablo.removeRow(r)

    def _tamam(self):
        adlar = [(self.tablo.item(r, 0).text() or "").strip() for r in range(self.tablo.rowCount())]
        if any(not a for a in adlar) or len(set(adlar)) != len(adlar):
            QMessageBox.warning(self, UYGULAMA, "Her tozun boş olmayan ve diğerlerinden farklı bir adı olmalı.")
            return
        adlar = [i.ad for i in self.islemler()]
        if len(set(adlar)) != len(adlar):
            QMessageBox.warning(self, UYGULAMA, "İşlem adları birbirinden farklı olmalı.")
            return
        self.accept()

    def ayar(self) -> Ayarlar:
        a = Ayarlar(yontem="teorik" if self.yontem.currentIndex() == 1 else "pratik",
                    verim=self.verim.value() / 100.0, proses_tl_m2=self.proses.value(),
                    para=self.para.text().strip() or "TL", oda_yolu=self.oda.text().strip(),
                    guncelleme=self.guncelleme.isChecked(), metal_yogunluk=self.metal.value(), tozlar=[],
                    islemler=self.islemler(), kaynak_teli=self.kaynak_teli())
        for r in range(self.tablo.rowCount()):
            w = lambda c: self.tablo.cellWidget(r, c).value()
            a.tozlar.append(Toz(self.tablo.item(r, 0).text().strip(), yogunluk=w(3), fiyat=w(2), kalinlik_um=w(4),
                                sarfiyat_m2_kg=w(1)))
        return a


# ---------------------------------------------------------------- ana pencere

SUTUNLAR = ["Parça", "Açıklama", "Adet", "Alan / adet (m²)", "Toz", "Kalınlık (µm)", "Toz / adet (g)",
            "Toplam toz (kg)", "Tutar", "Ağırlık / adet (kg)", "Adet fiyatı"]


class AnaPencere(QMainWindow):
    _surum_geldi = Signal(object, bool)  # (guncelleme.Surum ya da None, sessiz)
    _guncelleme_hazir = Signal(object)    # (sürüm, zip yolu) ya da None: sessiz güncelleme indirildi

    def __init__(self):
        super().__init__()
        self.ayar = proje.ayarlari_oku()
        self.kalemler: List[Kalem] = []
        self.yol = ""
        self.musteri = ""
        self.degisti = False
        self.resize(1280, 760)
        self.setAcceptDrops(True)
        self._eylemler()

        bolme = QSplitter(Qt.Horizontal)
        self.setCentralWidget(bolme)
        sol = QWidget()
        sv = QVBoxLayout(sol)
        sv.setContentsMargins(6, 6, 6, 6)
        ust = QHBoxLayout()
        ust.addWidget(QLabel("Müşteri / iş:"))
        self.musteri_kutu = QLineEdit()
        self.musteri_kutu.textEdited.connect(self._musteri)
        ust.addWidget(self.musteri_kutu, 1)
        sv.addLayout(ust)
        self.tablo = QTableWidget(0, len(SUTUNLAR))
        self.tablo.setHorizontalHeaderLabels(SUTUNLAR)
        self.tablo.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tablo.setSelectionMode(QAbstractItemView.ExtendedSelection)  # Ctrl / Shift ile çoklu seçim
        # yalnız Adet sütunu elle düzenlenir (çift tık ya da F2); öbür hücrelerin düzenleme bayrağı kapalı
        self.tablo.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.tablo.verticalHeader().hide()
        self.tablo.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tablo.itemSelectionChanged.connect(self._secim)
        self.tablo.itemChanged.connect(self._adet_yazildi)
        sv.addWidget(self.tablo, 1)
        self.toplam = QLabel()
        self.toplam.setTextFormat(Qt.RichText)
        self.toplam.setFrameShape(QFrame.StyledPanel)
        self.toplam.setMargin(6)
        sv.addWidget(self.toplam)
        bolme.addWidget(sol)

        self.ayrinti_alan = QScrollArea()
        self.ayrinti_alan.setWidgetResizable(True)
        self.ayrinti_alan.setMinimumWidth(360)
        bolme.addWidget(self.ayrinti_alan)
        bolme.setSizes([880, 400])
        self._ayrinti_bos()
        self._yenile()
        self._surum_geldi.connect(self._surum_sonucu)
        self._guncelleme_hazir.connect(self._sessiz_hazir)
        self._hazir = None  # (sürüm, zip yolu): kapanışta kurulacak

    # -- eylemler
    def _eylemler(self):
        st = self.style()
        arac = QToolBar("Araçlar")
        arac.setMovable(False)
        arac.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(arac)
        menu_dosya = self.menuBar().addMenu("&Dosya")
        menu_kalem = self.menuBar().addMenu("&Parça")
        menu_yardim = self.menuBar().addMenu("&Yardım")

        def eylem(ad, islev, simge=None, kisayol=None, menu=None, aracta=True):
            a = QAction(ad, self)
            if simge is not None:
                a.setIcon(st.standardIcon(simge))
            if kisayol:
                a.setShortcut(QKeySequence(kisayol))
            a.triggered.connect(islev)
            if menu is not None:
                menu.addAction(a)
            if aracta:
                arac.addAction(a)
            return a

        eylem("Çizim ekle (DXF / DWG / STEP / STL / PDF)", self.dosya_ekle, QStyle.SP_DialogOpenButton, "Ctrl+D", menu_kalem)
        eylem("Kalıptan ekle", self.kalip_ekle, QStyle.SP_FileDialogDetailedView, "Ctrl+K", menu_kalem)
        eylem("Elle alan", self.elle_ekle, QStyle.SP_FileDialogNewFolder, None, menu_kalem)
        eylem("Açınım (DXF)", self.acinim, None, None, menu_kalem)
        eylem("Çoğalt", self.cogalt, None, "Ctrl+Shift+D", menu_kalem, aracta=False)
        eylem("Sil", self.sil, QStyle.SP_TrashIcon, QKeySequence.Delete, menu_kalem)
        arac.addSeparator()
        eylem("Yeni", self.yeni, None, QKeySequence.New, menu_dosya, aracta=False)
        eylem("Aç…", self.ac, QStyle.SP_DirOpenIcon, QKeySequence.Open, menu_dosya, aracta=False)
        eylem("Kaydet", self.kaydet, QStyle.SP_DialogSaveButton, QKeySequence.Save, menu_dosya)
        eylem("Farklı kaydet…", lambda: self.kaydet(farkli=True), None, QKeySequence.SaveAs, menu_dosya, aracta=False)
        menu_dosya.addSeparator()
        eylem("Excel'e aktar (CSV)", self.csv, None, None, menu_dosya)
        eylem("PDF rapor", self.pdf, None, "Ctrl+P", menu_dosya)
        menu_dosya.addSeparator()
        eylem("Çıkış", self.close, None, QKeySequence.Quit, menu_dosya, aracta=False)
        arac.addSeparator()
        eylem("Ayarlar ve tozlar", self.ayarlar, QStyle.SP_FileDialogInfoView, None, menu_dosya)
        eylem("Güncellemeleri denetle", lambda: self.guncelleme_denetle(sessiz=False), None, None, menu_yardim,
              aracta=False)
        eylem("Hakkında", self.hakkinda, None, None, menu_yardim, aracta=False)

    # -- başlık / durum
    def _baslik(self):
        ad = os.path.basename(self.yol) if self.yol else "Yeni proje"
        self.setWindowTitle(f"{'*' if self.degisti else ''}{ad} — {UYGULAMA} {SURUM}")

    def _degisti(self):
        self.degisti = True
        self._baslik()

    def _musteri(self, t: str):
        self.musteri = t
        self._degisti()

    # -- tablo
    def _yenile(self, sec: Optional[int] = None):
        self.tablo.blockSignals(True)
        self.tablo.setRowCount(len(self.kalemler))
        for r in range(len(self.kalemler)):
            self._satir(r)
        self.tablo.blockSignals(False)
        self.tablo.setColumnHidden(5, self.ayar.pratik)  # kalınlık yalnız teorik yöntemde hesaba girer
        for c in range(len(SUTUNLAR)):
            if c != 1:
                self.tablo.resizeColumnToContents(c)
        if sec is not None and 0 <= sec < len(self.kalemler):
            self.tablo.selectRow(sec)
        self._secim()
        self._toplam()
        self._baslik()

    def _satir(self, r: int):
        k = self.kalemler[r]
        try:
            s = kalem_sonucu(k, self.ayar)
            veri = [k.ad, kaynak_aciklamasi(k.kaynak) + rapor.ek_aciklama(k), str(k.adet), sayi(s.alan_m2, 4),
                    self.ayar.toz(k.toz).ad, "—" if s.kalinlik_um is None else sayi(s.kalinlik_um, 0),
                    sayi(s.toz_g_adet, 1), sayi(s.toz_kg, 3), f"{sayi(s.tutar, 2)} {self.ayar.para}",
                    rapor.agirlik_metni(s.agirlik_kg_adet), f"{sayi(s.birim_fiyat, 2)} {self.ayar.para}"]
        except ValueError as h:
            veri = [k.ad, f"HATA: {h}", str(k.adet), "—", "", "", "", "", "", "", ""]
        for c, x in enumerate(veri):
            it = QTableWidgetItem(x)
            if c in (2, 3, 5, 6, 7, 8, 9, 10):
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if c != 2:
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            else:
                it.setToolTip("Çift tıklayıp adedi yazın")
            self.tablo.setItem(r, c, it)

    def _adet_yazildi(self, it: QTableWidgetItem):
        """Tabloda Adet hücresine elle yazılan sayı kalemin adedi olur; geçersizse eski değere döner."""
        r = it.row()
        if it.column() != 2 or not 0 <= r < len(self.kalemler):
            return
        try:
            x = int(round(float(it.text().strip().replace(",", "."))))
        except ValueError:
            x = 0
        if 1 <= x <= 10_000_000:
            self.kalemler[r].adet = x
            self._degisti()
        self.tablo.blockSignals(True)
        self._satir(r)
        self.tablo.blockSignals(False)
        self._toplam()
        self._secim()

    def _toplam(self):
        try:
            o = ozet(self.kalemler, self.ayar)
        except ValueError as h:
            self.toplam.setText(f"<span style='color:#a02020'>{h}</span>")
            return
        tozlar = " · ".join(f"{ad}: <b>{sayi(kg, 2)} kg</b>" for ad, kg in o.toz_bazinda.items())
        p = self.ayar.para
        fiyatsiz = sorted({self.ayar.toz(k.toz).ad for k in self.kalemler if self.ayar.toz(k.toz).fiyat <= 0})
        uyari = (f"<br><span style='color:#8a5a00'>Fiyatı girilmemiş toz: {', '.join(fiyatsiz)} "
                 "(Ayarlar ve tozlar)</span>" if fiyatsiz else "")
        self.toplam.setText(
            f"<b>{len(self.kalemler)}</b> kalem, <b>{o.toplam_adet}</b> adet · Toplam alan <b>{sayi(o.toplam_m2, 2)} m²</b>"
            f" · Toz <b>{sayi(o.toz_kg, 2)} kg</b> ({yontem_ozeti(self.ayar)})<br>"
            f"{tozlar}<br>Toz {sayi(o.toz_tl, 2)} {p} + proses {sayi(o.proses_tl, 2)} {p}"
            + (" + işlem " + " · ".join(f"{html.escape(ad)} {sayi(tl, 2)}" for ad, (_, tl) in o.islem_bazinda.items())
               + f" {p}" if o.islem_tl else "")
            + (f" (kaynak teli {sayi(o.tel_kg, 2)} kg ≈ "
               f"{sayi(o.tel_kg / self.ayar.kaynak_teli.makara_kg if self.ayar.kaynak_teli.makara_kg else 0, 2)} makara)"
               if o.tel_kg else "")
            + f" = <b>{sayi(o.tutar, 2)} {p}</b>"
            f" · Ağırlık <b>{sayi(o.agirlik_kg, 1)} kg</b>"
            + (f" ({o.agirliksiz} kalemin ağırlığı bilinmiyor)" if o.agirliksiz else "") + uyari)

    def _secili(self) -> int:
        r = self.tablo.currentRow()
        return r if 0 <= r < len(self.kalemler) and self.tablo.selectedItems() else -1

    # -- ayrıntı paneli
    def _ayrinti_bos(self):
        w = QLabel("Bir kalem seçin ya da ekleyin.\n\nÇizim ekle: DXF / DWG (2D açınım, 3D yüzey / katı), STEP ya da STL.\n"
                   "Kalıptan ekle: boru, profil, konik ayak, çubuk, lama, sac.\n\nDosyaları pencereye sürükleyip "
                   "bırakabilirsiniz.")
        w.setAlignment(Qt.AlignCenter)
        w.setWordWrap(True)
        self.ayrinti_alan.setWidget(w)

    def _secili_satirlar(self) -> List[int]:
        return sorted({i.row() for i in self.tablo.selectedItems() if 0 <= i.row() < len(self.kalemler)})

    def _secim(self):
        satirlar = self._secili_satirlar()
        if len(satirlar) > 1:
            self.ayrinti_alan.setWidget(self._coklu(satirlar))
            return
        r = self._secili()
        if r < 0:
            self._ayrinti_bos()
            return
        self.ayrinti_alan.setWidget(self._ayrinti(r))

    def _coklu(self, satirlar: List[int]) -> QWidget:
        """Birden çok kalem seçiliyken: toz (teorik yöntemde film kalınlığı) hepsine birden."""
        w = QWidget()
        v = QVBoxLayout(w)
        kalemler = [self.kalemler[r] for r in satirlar]
        b = QGroupBox(f"{len(kalemler)} kalem seçili ({sum(k.adet for k in kalemler)} adet)")
        f = QFormLayout(b)
        toz = QComboBox()
        tozlar = [t.ad for t in self.ayar.tozlar]
        ortak = {self.ayar.toz(k.toz).ad for k in kalemler}
        if len(ortak) > 1:
            toz.addItem("— karışık —")
        toz.addItems(tozlar)
        if len(ortak) == 1:
            toz.setCurrentText(next(iter(ortak)))

        def toz_ata(ad_):
            if ad_ not in tozlar:
                return
            for r in satirlar:
                self.kalemler[r].toz = ad_
            if toz.itemText(0) == "— karışık —":
                toz.blockSignals(True)
                toz.removeItem(0)
                toz.setCurrentText(ad_)
                toz.blockSignals(False)
            self._coklu_sonrasi(satirlar, sonuc)
        toz.currentTextChanged.connect(toz_ata)
        f.addRow("Toz (hepsine)", toz)
        adet = QSpinBox()
        adet.setRange(1, 10_000_000)
        adet.setValue(kalemler[0].adet if len({k.adet for k in kalemler}) == 1 else 1)
        adet.setKeyboardTracking(False)
        if len({k.adet for k in kalemler}) > 1:
            adet.setToolTip("Adetler farklı; değer girerseniz seçili kalemlerin hepsine yazılır")

        def adet_ata(x):
            for r in satirlar:
                self.kalemler[r].adet = x
            self._coklu_sonrasi(satirlar, sonuc)
            b.setTitle(f"{len(kalemler)} kalem seçili ({sum(k.adet for k in kalemler)} adet)")
        adet.valueChanged.connect(adet_ata)
        f.addRow("Adet (hepsine)", adet)
        for i in self.ayar.islemler:  # boya dışı işlem miktarı hepsine (çizimden gelen değer ezilir)
            basamak = 0 if i.birim in ("adet", "sabit") else 3
            ms = {islem_miktari(k, i)[0] for k in kalemler}
            sp = _cift(0.0, 1e6, next(iter(ms)) if len(ms) == 1 else 0.0, basamak, 1 if basamak == 0 else 0.1,
                       "" if i.birim == "sabit" else i.birim)
            if len(ms) > 1:
                sp.setToolTip("Miktarlar farklı; değer girerseniz seçili kalemlerin hepsine yazılır")

            def islem_ata(x, ad=i.ad):
                for r in satirlar:
                    self.kalemler[r].islemler = {**self.kalemler[r].islemler, ad: x}
                self._coklu_sonrasi(satirlar, sonuc)
            sp.valueChanged.connect(islem_ata)
            f.addRow(f"{i.ad} (hepsine)", sp)
        if not self.ayar.pratik:
            kal = _cift(10.0, 1000.0, self.ayar.toz(kalemler[0].toz).kalinlik_um, 0, 5, "µm")

            def kal_ata(x):
                for r in satirlar:
                    self.kalemler[r].kalinlik_um = x
                self._coklu_sonrasi(satirlar, sonuc)
            kal.valueChanged.connect(kal_ata)
            f.addRow("Film kalınlığı (hepsine)", kal)
        v.addWidget(b)
        sonuc = QLabel()
        sonuc.setWordWrap(True)
        v.addWidget(sonuc)
        v.addStretch(1)
        self._coklu_ozet(satirlar, sonuc)
        return w

    def _coklu_ozet(self, satirlar: List[int], etiket: QLabel):
        try:
            o = ozet([self.kalemler[r] for r in satirlar], self.ayar)
        except ValueError as h:
            etiket.setText(f"<span style='color:#a02020'>{h}</span>")
            return
        etiket.setText(f"Seçilenler: <b>{sayi(o.toplam_m2, 3)} m²</b> · toz <b>{sayi(o.toz_kg, 3)} kg</b> · "
                       f"<b>{sayi(o.tutar, 2)} {self.ayar.para}</b>")

    def _coklu_sonrasi(self, satirlar: List[int], etiket: QLabel):
        self.tablo.blockSignals(True)
        for r in satirlar:
            self._satir(r)
        self.tablo.blockSignals(False)
        self._coklu_ozet(satirlar, etiket)
        self._toplam()
        self._degisti()

    def _ayrinti(self, r: int) -> QWidget:
        k = self.kalemler[r]
        w = QWidget()
        v = QVBoxLayout(w)
        f = QFormLayout()
        v.addLayout(f)
        ad = QLineEdit(k.ad)
        ad.textEdited.connect(lambda t: self._guncelle(r, ad=t))
        f.addRow("Parça adı", ad)
        if k.dosya:
            dl = QLabel(os.path.basename(k.dosya))
            dl.setToolTip(k.dosya)
            f.addRow("Dosya", dl)

        kaynak = k.kaynak
        g = QGroupBox({"2d": "2D açınım", "3d": "3D gövde", "kalip": f"Kalıp: {kaynak.get('kalip', '')}",
                       "elle": "Elle alan"}.get(kaynak["tur"], "Kaynak"))
        gf = QFormLayout(g)
        if kaynak["tur"] == "2d":
            gf.addRow("Ölçü", QLabel(f"{sayi(kaynak['olcu'][0], 1)} × {sayi(kaynak['olcu'][1], 1)} mm, "
                                     f"{kaynak.get('delik', 0)} delik"))
            gf.addRow("Bir yüz", QLabel(f"{sayi(kaynak['yuz_alani'] / 1e6, 4)} m²; çevre {sayi(kaynak['cevre'], 1)} mm"))
            t = _cift(0.0, 100.0, float(kaynak.get("kalinlik", 0.0)), 2, 0.1, "mm")
            t.valueChanged.connect(lambda x: self._kaynak(r, kalinlik=x))
            gf.addRow("Sac kalınlığı", t)
            gf.addRow("Boyanan", QLabel("iki yüz + kesim kenarları (çevre × kalınlık)"))
        elif kaynak["tur"] == "3d" and kaynak.get("profil"):
            pr = kaynak["profil"]
            ic_alan = sum(a for a, _ in pr.get("ic", []))
            g.setTitle("3D profil (yüzeyler otomatik tanındı)")
            gf.addRow("Ölçü", QLabel(f"{sayi(pr['kesit'][0], 1)} × {sayi(pr['kesit'][1], 1)} mm, boy "
                                     f"{sayi(pr['boy'], 1)} mm"))
            gf.addRow("Dış yüzey", QLabel(f"{sayi(pr['dis'] / 1e6, 4)} m²"))
            gf.addRow("Uç kesitleri", QLabel(f"{sayi(pr['uc'] / 1e6, 4)} m²"))
            if pr.get("ic"):
                gf.addRow("İç yüzey", QLabel(f"{sayi(ic_alan / 1e6, 4)} m² (boşluk {sayi(pr.get('bosluk', 0), 1)} mm)"))
                icb = QComboBox()
                icb.addItems(["Uçlardan derinlik kadar", "Tamamı", "Boyanmaz"])
                secim = ["uçlardan", "tamamı", "boyanmaz"]
                icb.setCurrentIndex(secim.index(kaynak.get("ic_boya", "uçlardan")))
                der = _cift(0.0, 10000.0, float(kaynak.get("ic_derinlik", 0.0)), 1, 5, "mm")
                der.setToolTip("Toz açık uçtan içeri bu derinliğe kadar girer (her uçtan); yaklaşık boşluk ölçüsü kadar")
                der.setEnabled(icb.currentIndex() == 0)
                icb.currentIndexChanged.connect(lambda i: (der.setEnabled(i == 0), self._kaynak(r, ic_boya=secim[i])))
                der.valueChanged.connect(lambda x: self._kaynak(r, ic_derinlik=x))
                gf.addRow("İç yüzey boyası", icb)
                gf.addRow("İç boya derinliği", der)
            ucb = QCheckBox("Uç kesitleri boyanır")
            ucb.setChecked(bool(kaynak.get("uc_boya", True)))
            ucb.toggled.connect(lambda b: self._kaynak(r, uc_boya=b))
            gf.addRow("", ucb)
        elif kaynak["tur"] == "3d" and kaynak.get("sac"):
            sc = kaynak["sac"]
            g.setTitle("3D sac (kalınlık ve yüzler modelden)")
            gf.addRow("Sac kalınlığı", QLabel(f"{sayi(sc['kalinlik'], 2)} mm"))
            gf.addRow("İki yüz", QLabel(f"{sayi(sc['yuz'] / 1e6, 4)} m²"))
            gf.addRow("Kesim kenarları", QLabel(f"{sayi(sc['kenar'] / 1e6, 4)} m² (delik duvarları dahil, boyanır)"))
        elif kaynak["tur"] == "3d":
            gf.addRow("Yüzey alanı", QLabel(f"{sayi(kaynak['alan'] / 1e6, 4)} m² ({kaynak.get('varlik', '')})"))
            if float(kaynak.get("katsayi", 1)) == 2:
                gf.addRow(QLabel("Açık yüzey modeli (sacın tek yüzü): iki yüz sayıldı."))
            else:
                gf.addRow(QLabel("Modeldeki bütün yüzeyler sayıldı."))
        elif kaynak["tur"] == "kalip":
            form = KalipFormu(kaynak["kalip"], kaynak.get("deger", {}))
            form.degisti.connect(lambda: self._kaynak(r, deger=form.deger()))
            gf.addRow(form)
        elif kaynak["tur"] == "elle":
            a = _cift(0.0, 1e6, float(kaynak.get("alan_m2", 0.0)), 4, 0.01, "m²")
            a.valueChanged.connect(lambda x: self._kaynak(r, alan_m2=x))
            gf.addRow("Alan / adet", a)
        if kaynak["tur"] == "3d" and kaynak.get("delikler"):
            import profil
            satir = [f"{n} × {m}" for n, m in profil.delik_ozeti(kaynak["delikler"])]
            alan_ = sum(d["alan"] for d in kaynak["delikler"])
            duvar = sum(d["duvar"] for d in kaynak["delikler"])
            dl = QLabel("<br>".join(satir) + f"<br><span style='color:#666'>yüzey {sayi(alan_ / 100, 1)} cm² (duvar "
                        f"{sayi(duvar / 100, 1)}, havşa {sayi((alan_ - duvar) / 100, 1)}); önizlemede turuncu</span>")
            dl.setWordWrap(True)
            gf.addRow("Delikler", dl)
            dib = QCheckBox("Delik içleri boyanmaz")
            dib.setToolTip("Küçük deliklerin içine toz girmez (Faraday kafesi); işaretlenirse bütün delik ve kesiklerin "
                           "duvarları alandan düşülür, havşa ağzı boyanır")
            dib.setChecked(bool(kaynak.get("delik_ici_boyanmaz")))
            dib.toggled.connect(lambda b_: self._kaynak(r, delik_ici_boyanmaz=b_))
            gf.addRow("", dib)
        v.addWidget(g)

        b = QGroupBox("Boya")
        bf = QFormLayout(b)
        adet = QSpinBox()
        adet.setRange(1, 10_000_000)
        adet.setValue(k.adet)
        adet.setKeyboardTracking(False)
        adet.valueChanged.connect(lambda x: self._guncelle(r, adet=x))
        bf.addRow("Adet", adet)
        maske = _cift(0.0, 1e7, k.maske_cm2, 1, 1, "cm²")
        maske.setToolTip("Boyanmayan yüzeyler (dişli delik, oturma yüzü, borunun boyanmayan içi), adet başına")
        maske.valueChanged.connect(lambda x: self._guncelle(r, maske_cm2=x))
        bf.addRow("Maske (adet başına)", maske)
        maske_y = _cift(0.0, 100.0, k.maske_yuzde, 1, 1, "%")
        maske_y.setToolTip("Boyanmayan alan, çizim alanının yüzdesi olarak (cm² maskeyle birlikte düşülür)")
        maske_y.valueChanged.connect(lambda x: self._guncelle(r, maske_yuzde=x))
        bf.addRow("Maske (%)", maske_y)
        kat = QSpinBox()
        kat.setRange(1, 5)
        kat.setValue(k.kat)
        kat.setToolTip("Astar + son kat gibi çok katlı işlerde: toz ve proses kat sayısıyla çarpılır")
        kat.valueChanged.connect(lambda x: self._guncelle(r, kat=x))
        bf.addRow("Kat sayısı", kat)
        toz = QComboBox()
        toz.addItems([t.ad for t in self.ayar.tozlar])
        toz.setCurrentText(self.ayar.toz(k.toz).ad)
        bf.addRow("Toz", toz)
        kal = _cift(10.0, 1000.0, k.kalinlik_um if k.kalinlik_um is not None else self.ayar.toz(k.toz).kalinlik_um,
                    0, 5, "µm")
        kal.valueChanged.connect(lambda x: self._guncelle(r, kalinlik_um=x))
        sarf = QLabel()
        if self.ayar.pratik:  # pratik yöntemde kalınlık hesaba girmez; tozun sarfiyatı gösterilir
            kal.hide()
            bf.addRow("Sarfiyat", sarf)
        else:
            bf.addRow("Film kalınlığı", kal)

        def sarfiyat_yaz():
            sarf.setText(f"1 kg = {sayi(self.ayar.toz(k.toz).sarfiyat_m2_kg, 1)} m²  (Ayarlar ve tozlar)")
        sarfiyat_yaz()

        def toz_degisti(ad_):
            eski_varsayilan = k.kalinlik_um is None
            self._guncelle(r, toz=ad_)
            sarfiyat_yaz()
            if eski_varsayilan:
                kal.blockSignals(True)
                kal.setValue(self.ayar.toz(ad_).kalinlik_um)
                kal.blockSignals(False)
        toz.currentTextChanged.connect(toz_degisti)
        v.addWidget(b)

        if self.ayar.islemler:
            v.addWidget(self._islem_kutusu(r))

        ag = QGroupBox("Ağırlık")
        af = QFormLayout(ag)
        hesapli = agirlik_kg(Kalem(k.ad, k.kaynak), self.ayar)
        elle = QCheckBox("Elle gir")
        elle.setChecked(k.agirlik_kg is not None)
        agk = _cift(0.0, 1e6, k.agirlik_kg if k.agirlik_kg is not None else (hesapli or 0.0), 3, 0.1, "kg")
        agk.setEnabled(elle.isChecked())
        bilgi = QLabel(f"çizimden: {sayi(hesapli, 3)} kg (metal hacmi × {sayi(self.ayar.metal_yogunluk, 2)} g/cm³)"
                       if hesapli is not None else "çizimden hesaplanamadı (dolu gövde ya da elle alan): elle girin")
        bilgi.setWordWrap(True)
        elle.toggled.connect(lambda b_: (agk.setEnabled(b_), self._guncelle(r, agirlik_kg=agk.value() if b_ else None)))
        agk.valueChanged.connect(lambda x: elle.isChecked() and self._guncelle(r, agirlik_kg=x))
        af.addRow(bilgi)
        af.addRow(elle, agk)
        v.addWidget(ag)

        self._sonuc_etiketi = QLabel()
        self._sonuc_etiketi.setWordWrap(True)
        v.addWidget(self._sonuc_etiketi)
        self._onizleme = Onizleme()
        v.addWidget(self._onizleme, 1)
        self._ayrinti_sonuc(r)
        geo = getattr(k, "geo", None)
        self._onizleme.goster(geo, "" if geo is not None else
                              ("Önizleme yalnız çizimden eklenen kalemlerde" if k.kaynak["tur"] != "kalip"
                               else kaliplar.aciklama(k.kaynak["kalip"], k.kaynak.get("deger", {}))))
        return w

    def _islem_kutusu(self, r: int) -> QGroupBox:
        """Boya dışı işlemler: adet başına miktar. Çizimden gelen (havşa) değer "elle" işaretlenince değiştirilir."""
        k = self.kalemler[r]
        g = QGroupBox("İşlemler (adet başına)")
        f = QFormLayout(g)
        p = self.ayar.para

        def yaz(ad, x):
            d = dict(k.islemler)
            if x is None:
                d.pop(ad, None)
            else:
                d[ad] = x
            self._guncelle(r, islemler=d)

        for i in self.ayar.islemler:
            m, elle = islem_miktari(k, i)
            basamak = 0 if i.birim in ("adet", "sabit") else 3
            sp = _cift(0.0, 1e6, m, basamak, 1 if basamak == 0 else 0.1, "" if i.birim == "sabit" else i.birim)
            sp.setToolTip(f"Birim fiyat {sayi(self.ayar.birim_fiyati(i), 2)} {p}/{i.birim}"
                          + (f" (işçilik {sayi(i.fiyat, 2)} + tel {sayi(self.ayar.tel_tl_m, 2)})" if i.tel else "")
                          + " (Ayarlar)")
            h = QHBoxLayout()
            h.addWidget(sp, 1)
            oto = otomatik_miktar(k, i)
            geo = getattr(k, "geo", None)
            if i.kaynak == "kaynak" and isinstance(geo, Ag) and geo.kenarlar:
                sec = QPushButton("Seç…")
                sec.setToolTip("3D çizimde kaynak yapılacak kenarları seçin (iki taraflı da olabilir)")
                sec.clicked.connect(lambda _=False: self._kaynak_sec(r))
                h.addWidget(sec)
            if i.kaynak == "yuzey" and isinstance(geo, Ag) and geo.yuz_donguleri:
                sec = QPushButton("Seç…")
                sec.setToolTip(f"3D çizimde {i.ad.lower()} yapılacak yüzeyleri seçin; alanları toplanır")
                sec.clicked.connect(lambda _=False, ad=i.ad: self._yuzey_sec(r, ad))
                h.addWidget(sec)
            if i.kaynak and oto is not None:
                cb = QCheckBox(f"elle (çizimden {sayi(oto, basamak)})")
                cb.setChecked(elle)
                sp.setEnabled(elle)

                def degis(b_, ad=i.ad, sp=sp, oto=oto):
                    sp.setEnabled(b_)
                    if not b_:
                        sp.blockSignals(True)
                        sp.setValue(oto)
                        sp.blockSignals(False)
                    yaz(ad, sp.value() if b_ else None)
                cb.toggled.connect(degis)
                sp.valueChanged.connect(lambda x, ad=i.ad, cb=cb: cb.isChecked() and yaz(ad, x))
                h.addWidget(cb)
            else:
                sp.valueChanged.connect(lambda x, ad=i.ad: yaz(ad, x if x else None))
            f.addRow(i.ad + (" (1: uygulanır)" if i.birim == "sabit" else ""), h)
        return g

    def _kaynak_sec(self, r: int):
        k = self.kalemler[r]
        d = KaynakPenceresi(k.geo, k.kaynak.get("kaynak_dikisleri", []), self)
        if d.exec() != QDialog.Accepted:
            return
        k.kaynak["kaynak_dikisleri"] = d.dikisler()
        for i in self.ayar.islemler:  # elle girilmiş kaynak metresi çizimden gelene bırakılır
            if i.kaynak == "kaynak":
                k.islemler.pop(i.ad, None)
        self._sonrasi(r)
        self.ayrinti_alan.setWidget(self._ayrinti(r))

    def _yuzey_sec(self, r: int, ad: str):
        k = self.kalemler[r]
        d = YuzeyPenceresi(k.geo, (k.kaynak.get("yuzey_secimi") or {}).get(ad, []), ad, self)
        if d.exec() != QDialog.Accepted:
            return
        k.kaynak["yuzey_secimi"] = {**(k.kaynak.get("yuzey_secimi") or {}), ad: d.secim()}
        k.islemler.pop(ad, None)  # elle girilmiş miktar seçime bırakılır
        self._sonrasi(r)
        self.ayrinti_alan.setWidget(self._ayrinti(r))

    def _ayrinti_sonuc(self, r: int):
        k = self.kalemler[r]
        try:
            s = kalem_sonucu(k, self.ayar)
            ham = kaynak_alani(k.kaynak) / 1e6
            p = self.ayar.para
            self._sonuc_etiketi.setText(
                f"Boyanacak alan: <b>{sayi(s.alan_m2, 4)} m²</b> / adet"
                + (f" (çizim {sayi(ham, 4)} m², maske düşüldü)" if k.maske_cm2 or k.maske_yuzde else "")
                + f"<br>Toz: <b>{sayi(s.toz_g_adet, 1)} g</b> / adet" + (f" ({s.kat} kat)" if s.kat > 1 else "")
                + f" · toplam <b>{sayi(s.toz_kg, 3)} kg</b>"
                + ("" if s.agirlik_kg is None else
                   f"<br>Ağırlık: <b>{sayi(s.agirlik_kg_adet, 3)} kg</b> / adet · toplam {sayi(s.agirlik_kg, 2)} kg")
                + "".join(f"<br>{html.escape(ad)}: {sayi(m, 3)} / adet → {sayi(tl, 2)} {p}" for ad, (m, tl) in s.islem_detay.items())
                + f"<br>Tutar: toz {sayi(s.toz_tl, 2)} + proses {sayi(s.proses_tl, 2)}"
                + (f" + işlem {sayi(s.islem_tl, 2)}" if s.islem_tl else "")
                + f" = <b>{sayi(s.tutar, 2)} {p}</b> · adet başına <b>{sayi(s.birim_fiyat, 2)} {p}</b>")
        except ValueError as h:
            self._sonuc_etiketi.setText(f"<span style='color:#a02020'>{h}</span>")

    def _guncelle(self, r: int, **alan):
        k = self.kalemler[r]
        for a, x in alan.items():
            setattr(k, a, x)
        self._sonrasi(r)

    def _kaynak(self, r: int, **alan):
        self.kalemler[r].kaynak.update(alan)
        self._sonrasi(r)

    def _sonrasi(self, r: int):
        self.tablo.blockSignals(True)
        self._satir(r)
        self.tablo.blockSignals(False)
        self._ayrinti_sonuc(r)
        self._toplam()
        self._degisti()

    # -- ekleme / silme
    def _varsayilan_toz(self) -> str:
        r = self._secili()
        if r >= 0:
            return self.ayar.toz(self.kalemler[r].toz).ad
        return self.ayar.tozlar[0].ad if self.ayar.tozlar else ""

    def dosya_ekle(self, *_, yollar: Optional[List[str]] = None):
        if not yollar:
            yollar, _ = QFileDialog.getOpenFileNames(self, "Çizim ekle", "", DOSYA_SUZGECI)
        for yol in yollar:
            try:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    if yol.lower().endswith(".pdf"):
                        d = PdfAktar(yol, self._varsayilan_toz(), self.ayar, self)
                    else:
                        d = IceAktar(yol, self._varsayilan_toz(), self, self.ayar.oda_yolu)
                finally:
                    QApplication.restoreOverrideCursor()
            except Exception as h:  # bozuk / desteklenmeyen dosya: ezdxf çeşitli hatalar atar
                QMessageBox.warning(self, UYGULAMA, f"{os.path.basename(yol)} açılamadı:\n{h}")
                continue
            if d.exec() == QDialog.Accepted:
                yeni = [d.kalem()] if isinstance(d, PdfAktar) else d.kalemler()
                if yeni:
                    self.kalemler.extend(yeni)
                    self._degisti()
                    self._yenile(len(self.kalemler) - 1)

    def kalip_ekle(self):
        d = KalipPenceresi(self._varsayilan_toz(), self)
        if d.exec() == QDialog.Accepted:
            self.kalemler.append(d.kalem())
            self._degisti()
            self._yenile(len(self.kalemler) - 1)

    def elle_ekle(self):
        self.kalemler.append(Kalem(f"Parça {len(self.kalemler) + 1}", {"tur": "elle", "alan_m2": 0.1},
                                   toz=self._varsayilan_toz()))
        self._degisti()
        self._yenile(len(self.kalemler) - 1)

    def acinim(self):
        """Konik / silindirik sac açınımı; seçili kalem konik ayak, boru ya da 3D konik profilse ölçüleri ondan."""
        r = self._secili()
        k = self.kalemler[r] if r >= 0 else None
        AcinimPenceresi(acinim_olculeri(k), k.ad if k else "", self).exec()

    def cogalt(self):
        r = self._secili()
        if r < 0:
            return
        k = self.kalemler[r]
        y = Kalem.sozlukten(copy.deepcopy(k.sozluk()))
        y.ad += " (kopya)"
        y.geo = getattr(k, "geo", None)
        self.kalemler.insert(r + 1, y)
        self._degisti()
        self._yenile(r + 1)

    def sil(self):
        satirlar = sorted({i.row() for i in self.tablo.selectedItems()}, reverse=True)
        if not satirlar:
            return
        for r in satirlar:
            del self.kalemler[r]
        self._degisti()
        self._yenile(min(satirlar[-1], len(self.kalemler) - 1))

    # -- dosya
    def _kaydedilsin_mi(self) -> bool:
        if not self.degisti or not self.kalemler:
            return True
        c = QMessageBox.question(self, UYGULAMA, "Değişiklikler kaydedilsin mi?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if c == QMessageBox.Save:
            return self.kaydet()
        return c == QMessageBox.Discard

    def yeni(self):
        if not self._kaydedilsin_mi():
            return
        self.kalemler, self.yol, self.musteri, self.degisti = [], "", "", False
        self.musteri_kutu.setText("")
        self._yenile()

    def ac(self, *_, yol: str = ""):
        if not self._kaydedilsin_mi():
            return
        if not yol:
            yol, _ = QFileDialog.getOpenFileName(self, "Proje aç", "", "Toz boya projesi (*.tozboya)")
        if not yol:
            return
        try:
            self.kalemler, self.ayar, self.musteri = proje.ac(yol)
        except (OSError, ValueError, KeyError, TypeError) as h:
            QMessageBox.warning(self, UYGULAMA, f"Proje açılamadı:\n{h}")
            return
        self.yol, self.degisti = yol, False
        self.musteri_kutu.setText(self.musteri)
        self._yenile(0)

    def kaydet(self, farkli: bool = False) -> bool:
        yol = self.yol
        if farkli or not yol:
            yol, _ = QFileDialog.getSaveFileName(self, "Projeyi kaydet", self.musteri or "proje",
                                                 "Toz boya projesi (*.tozboya)")
            if not yol:
                return False
            if not yol.lower().endswith(".tozboya"):
                yol += ".tozboya"
        try:
            proje.kaydet(yol, self.kalemler, self.ayar, self.musteri)
        except OSError as h:
            QMessageBox.warning(self, UYGULAMA, f"Kaydedilemedi:\n{h}")
            return False
        self.yol, self.degisti = yol, False
        self._baslik()
        return True

    def _cikti_adi(self, uzanti: str) -> str:
        temel = os.path.splitext(self.yol)[0] if self.yol else (self.musteri or "toz_boya_hesabi")
        return temel + uzanti

    def csv(self):
        yol, _ = QFileDialog.getSaveFileName(self, "Excel'e aktar", self._cikti_adi(".csv"), "CSV (*.csv)")
        if yol:
            try:
                rapor.csv_yaz(yol, self.kalemler, self.ayar)
            except (OSError, ValueError) as h:
                QMessageBox.warning(self, UYGULAMA, f"Yazılamadı:\n{h}")

    def pdf(self):
        yol, _ = QFileDialog.getSaveFileName(self, "PDF rapor", self._cikti_adi(".pdf"), "PDF (*.pdf)")
        if yol:
            try:
                pdf_yaz(yol, self.kalemler, self.ayar, self.musteri)
            except (OSError, ValueError) as h:
                QMessageBox.warning(self, UYGULAMA, f"Yazılamadı:\n{h}")

    def ayarlar(self):
        d = AyarPenceresi(self.ayar, self)
        if d.exec() != QDialog.Accepted:
            return
        self.ayar = d.ayar()
        if d.kalici.isChecked():
            try:
                proje.ayarlari_yaz(self.ayar)
            except OSError as h:
                QMessageBox.warning(self, UYGULAMA, f"Ayarlar saklanamadı:\n{h}")
        self._degisti()
        self._yenile(self._secili())

    # -- güncelleme (GitHub Releases)
    def guncelleme_denetle(self, sessiz: bool = True):
        """Son sürümü arka planda sorar; sonuç _surum_sonucu'na gelir."""
        import threading
        import guncelleme
        threading.Thread(target=lambda: self._surum_geldi.emit(guncelleme.son_surum(), sessiz), daemon=True).start()

    def sessiz_guncelleme(self):
        """Açılışta: önceki kurulumun hatasını bildirir; yeni sürümü arka planda indirir (kapanışta kurulur)."""
        import threading
        import guncelleme
        hata = guncelleme.hata_oku()
        if hata:
            QMessageBox.warning(self, UYGULAMA, f"Son güncelleme kurulamadı:\n{hata}\n\nProgramı yazılabilir bir "
                                f"klasöre (ör. Belgeler) taşıyın ya da elle indirin: {guncelleme.SAYFA}")
        threading.Thread(target=lambda: self._guncelleme_hazir.emit(guncelleme.hazirla(SURUM)), daemon=True).start()

    def _sessiz_hazir(self, sonuc):
        if sonuc is None:
            return
        self._hazir = sonuc
        self.statusBar().showMessage(f"Yeni sürüm {sonuc[0]} indirildi; program kapanınca kurulacak.")

    def _kapanista_kur(self):
        import guncelleme
        if self._hazir is None:
            return
        zip_yolu = self._hazir[1]
        self._hazir = None
        try:
            guncelleme.kur(zip_yolu, baslat=False)
            os.remove(zip_yolu)  # kur zip'i açtı; gerisini betik kopyalar
        except Exception:  # noqa: BLE001 — kapanışta hiçbir hata programı tutmamalı; sonraki açılışta yeniden denenir
            pass

    def _surum_sonucu(self, s, sessiz: bool):
        import guncelleme
        if s is None:
            if not sessiz:
                QMessageBox.information(self, UYGULAMA, "Güncelleme bilgisi alınamadı (internet bağlantısı yok ya da "
                                        f"henüz yayımlanmış sürüm yok).\n{guncelleme.SAYFA}")
            return
        if not guncelleme.yeni_mi(s.surum, SURUM):
            if not sessiz:
                QMessageBox.information(self, UYGULAMA, f"Program güncel ({SURUM}).")
            return
        notlar = s.notlar.strip()[:1500]
        c = QMessageBox.question(self, UYGULAMA, f"Yeni sürüm var: {s.surum} (kullandığınız {SURUM}).\n\n"
                                 + (notlar + "\n\n" if notlar else "") + "Şimdi indirilip kurulsun mu? Program "
                                 "kapanıp yeni sürümle yeniden açılır.")
        if c == QMessageBox.Yes:
            self._guncellemeyi_kur(s)

    def _guncellemeyi_kur(self, s):
        import tempfile
        import guncelleme
        from PySide6.QtWidgets import QProgressDialog
        if not self._kaydedilsin_mi():
            return
        ilerleme = QProgressDialog("Yeni sürüm indiriliyor…", "Vazgeç", 0, 100, self)
        ilerleme.setWindowModality(Qt.WindowModal)
        ilerleme.setMinimumDuration(0)

        def adim(alinan, toplam):
            if toplam:
                ilerleme.setValue(int(100 * alinan / toplam))
            QApplication.processEvents()
            return not ilerleme.wasCanceled()
        klasor = tempfile.mkdtemp(prefix="TozBoyaIndir_")
        zip_yolu = os.path.join(klasor, f"TozBoyaHesap_{s.surum}.zip")
        ozet_yolu = zip_yolu + ".sha256"
        try:
            guncelleme.indir(s.sha_url, ozet_yolu)
            guncelleme.indir(s.zip_url, zip_yolu, adim)
            with open(ozet_yolu, encoding="utf-8") as f:
                if not guncelleme.ozet_dogru(zip_yolu, f.read()):
                    raise OSError("İndirilen dosyanın SHA-256 özeti tutmuyor; dosya bozuk ya da değiştirilmiş.")
            ilerleme.close()
            guncelleme.kur(zip_yolu)
        except (OSError, zipfile.BadZipFile) as h:
            ilerleme.close()
            QMessageBox.warning(self, UYGULAMA, f"Güncelleme yapılamadı:\n{h}\n\nElle indirmek için: "
                                f"{guncelleme.SAYFA}")
            return
        self.degisti = False
        self._hazir = None  # betik zaten kuruyor
        QApplication.quit()

    def hakkinda(self):
        QMessageBox.about(self, UYGULAMA,
                          f"<b>{UYGULAMA}</b> {SURUM}<br><br>Toz = alan ÷ sarfiyat (m²/kg) ya da (teorik) "
                          "alan × kalınlık × yoğunluk ÷ transfer verimi."
                          "<br>Alan DXF / DWG'den (2D açınım, 3D yüzey ve katı), STEP / STL'den ya da kalıptan."
                          "<br><br>© 2026 Enes Özbek · MIT lisansı (LICENSE)<br>Qt / PySide6 (LGPL-3.0), ezdxf (MIT) ve "
                          "diğer bileşenler: UCUNCU_TARAF_LISANSLARI.txt")

    # -- sürükle bırak / kapanış
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        yollar = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        projeler = [y for y in yollar if y.lower().endswith(".tozboya")]
        cizimler = [y for y in yollar if y.lower().endswith((".dxf", ".dwg", ".step", ".stp", ".stl", ".pdf"))]
        if projeler:
            self.ac(yol=projeler[0])
        if cizimler:
            self.dosya_ekle(yollar=cizimler)

    def closeEvent(self, e):
        if self._kaydedilsin_mi():
            e.accept()
            self._kapanista_kur()
        else:
            e.ignore()


def pdf_yaz(yol: str, kalemler: List[Kalem], ayar: Ayarlar, musteri: str = "") -> None:
    yazici = QPdfWriter(yol)
    yazici.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Landscape,
                                     QMarginsF(12, 12, 12, 12), QPageLayout.Millimeter))
    yazici.setTitle("Toz Boya Hesabı")
    belge = QTextDocument()
    belge.setHtml(rapor.html_rapor(kalemler, ayar, musteri))
    belge.print_(yazici)
