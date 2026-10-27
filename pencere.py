# -*- coding: utf-8 -*-
"""Ana pencere: sipariş listesi (kalemler), seçili kalemin ayrıntısı ve önizlemesi, toplamlar.
Dosya ekleme (DXF / STL) içe aktarma penceresinden, kalıplar kalıp penceresinden geçer."""
from __future__ import annotations

import copy
import math
import os
from typing import Dict, List, Optional

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QKeySequence, QPageLayout, QPageSize, QPainter,
                           QPainterPath, QPdfWriter, QPen, QPolygonF, QTextDocument)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea,
                               QSpinBox, QSplitter, QStyle, QTableWidget, QTableWidgetItem, QToolBar,
                               QVBoxLayout, QWidget)

import dxf_oku
import kaliplar
import proje
import rapor
import stl_oku
from geometri import Ag, Parca2D
from hesap import (Ayarlar, Kalem, Toz, kalem_sonucu, kaynak_aciklamasi, kaynak_alani, ozet, sayi, teorik_kaplama,
                   yontem_ozeti)
from surum import SURUM

UYGULAMA = "Toz Boya Hesabı"
DOSYA_SUZGECI = "Çizimler (*.dxf *.dwg *.stl);;DXF (*.dxf);;DWG (*.dwg);;STL (*.stl)"


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
    """DXF / STL'deki parçaları gösterir; kullanıcı birimi, katmanları ve eklenecekleri seçer."""

    def __init__(self, yol: str, varsayilan_toz: str, parent=None, oda_yolu: str = ""):
        super().__init__(parent)
        self.yol = yol
        self.dosya_adi = os.path.splitext(os.path.basename(yol))[0]
        self.stl = yol.lower().endswith(".stl")
        self.toz = varsayilan_toz
        self.setWindowTitle(f"Dosya ekle — {os.path.basename(yol)}")
        self.resize(980, 620)
        self.doc = None if self.stl else dxf_oku.belge_ac(yol, oda_yolu)
        self.sonuc: Optional[dxf_oku.DxfSonuc] = None
        self.ogeler: List = []   # (tür, geometri, kaynak, ad, hata)

        ana = QVBoxLayout(self)
        ust = QHBoxLayout()
        ana.addLayout(ust)
        form = QFormLayout()
        ust.addLayout(form, 1)
        self.birim = QComboBox()
        kod = 0 if self.stl else int(self.doc.header.get("$INSUNITS", 0) or 0)
        for k, (ad, olcek) in dxf_oku.BIRIMLER.items():
            if k == 0:
                continue
            self.birim.addItem(ad, olcek)
        self.birim.setCurrentIndex(max(0, self.birim.findText(dxf_oku.BIRIMLER.get(kod, ("mm", 1))[0]
                                                              if kod else "mm")))
        birim_notu = ("STL'de birim yazmaz" if self.stl else
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
        self.topla = QCheckBox("Aynı parçaları tek satırda topla (adet olarak)")
        self.topla.setChecked(True)
        self.topla.setToolTip("Alanı, ölçüleri (ve 2D'de kalınlığı) aynı olan parçalar tek kalem olur; adet kopya sayısıdır")
        if not self.stl:
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
        self._form = form
        form.addRow("", self.topla)
        self.katmanlar = QListWidget()
        self.katmanlar.setMaximumHeight(130)
        if not self.stl:
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
        if not self.stl:
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
                self.ogeler.append(("3d", g, {"tur": "3d", "alan": g.alan, "kapali": g.kapali_mi(),
                                              "katsayi": 2.0 if g.sac_yuzeyi_mi() else 1.0, "varlik": "STL"}, ad, ""))
        else:
            haric = [self.katmanlar.item(i).text() for i in range(self.katmanlar.count())
                     if self.katmanlar.item(i).checkState() != Qt.Checked]
            s = dxf_oku.cozumle(self.doc, olcek, haric, self.kesikli.isChecked())
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
                if kaynak and g.sac is not None:
                    kaynak["sac"] = g.sac.sozluk()
                if kaynak and g.profil is not None:
                    # profil: dış, iç ve uç yüzeyler ayrı; iç yüzey uçlardan boşluk ölçüsü kadar boyanır
                    kaynak.update(profil=g.profil.sozluk(), ic_boya="uçlardan",
                                  ic_derinlik=round(g.profil.bosluk, 1), uc_boya=True)
                self.ogeler.append(("3d", g.ag, kaynak, ad, g.hata))
            for i, p in enumerate(s.parcalar):
                ad = self.dosya_adi + (f" – parça {i + 1}" if len(s.parcalar) > 1 else "")
                self.ogeler.append(("2d", p, self._kaynak2d(p), ad, ""))
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
        self.uyari.setText("\n".join(uyarilar))
        self._tabloyu_doldur()

    @staticmethod
    def _anahtar(p: Parca2D) -> tuple:
        k = p.dis.kutu
        return round(p.yuz_alani, 3), round(p.toplam_cevre, 3), round(k[0], 3), round(k[1], 3)

    def _kaynak2d(self, p: Parca2D) -> Dict:
        w, h = p.olcu
        return {"tur": "2d", "yuz_alani": p.yuz_alani, "cevre": p.toplam_cevre, "olcu": [w, h],
                "delik": len(p.delikler),
                "kalinlik": self.kalinliklar.get(self._anahtar(p),
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
        if not self.stl:  # 2D sac kalınlığı satırları yalnız 2D parça varken (3D sacın kalınlığı modelden)
            iki_d = any(t == "2d" for t, *_ in self.ogeler)
            self._form.setRowVisible(self._kal_satir, iki_d)
            self._form.setRowVisible(self._kal_bilgi, iki_d)
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

    def kalemler(self) -> List[Kalem]:
        out: List[Kalem] = []
        gruplar: List[tuple] = []   # (seçenekler, sayılar, kalem)
        for r, (tur, geo, kaynak, ad, hata) in enumerate(self.ogeler):
            it = self.tablo.item(r, 0)
            if kaynak is None or it.checkState() != Qt.Checked:
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
        self.setWindowTitle("Ayarlar ve toz kütüphanesi")
        self.resize(820, 480)
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
        self.guncelleme = QCheckBox("Açılışta yeni sürümü denetle (GitHub)")
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

    def _sil(self):
        r = self.tablo.currentRow()
        if r >= 0 and self.tablo.rowCount() > 1:
            self.tablo.removeRow(r)

    def _tamam(self):
        adlar = [(self.tablo.item(r, 0).text() or "").strip() for r in range(self.tablo.rowCount())]
        if any(not a for a in adlar) or len(set(adlar)) != len(adlar):
            QMessageBox.warning(self, UYGULAMA, "Her tozun boş olmayan ve diğerlerinden farklı bir adı olmalı.")
            return
        self.accept()

    def ayar(self) -> Ayarlar:
        a = Ayarlar(yontem="teorik" if self.yontem.currentIndex() == 1 else "pratik",
                    verim=self.verim.value() / 100.0, proses_tl_m2=self.proses.value(),
                    para=self.para.text().strip() or "TL", oda_yolu=self.oda.text().strip(),
                    guncelleme=self.guncelleme.isChecked(), tozlar=[])
        for r in range(self.tablo.rowCount()):
            w = lambda c: self.tablo.cellWidget(r, c).value()
            a.tozlar.append(Toz(self.tablo.item(r, 0).text().strip(), yogunluk=w(3), fiyat=w(2), kalinlik_um=w(4),
                                sarfiyat_m2_kg=w(1)))
        return a


# ---------------------------------------------------------------- ana pencere

SUTUNLAR = ["Parça", "Açıklama", "Adet", "Alan / adet (m²)", "Toz", "Kalınlık (µm)", "Toz / adet (g)",
            "Toplam toz (kg)", "Tutar"]


class AnaPencere(QMainWindow):
    _surum_geldi = Signal(object, bool)  # (guncelleme.Surum ya da None, sessiz)

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
        self.tablo.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tablo.verticalHeader().hide()
        self.tablo.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tablo.itemSelectionChanged.connect(self._secim)
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

        eylem("Çizim ekle (DXF / DWG / STL)", self.dosya_ekle, QStyle.SP_DialogOpenButton, "Ctrl+D", menu_kalem)
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
            veri = [k.ad, kaynak_aciklamasi(k.kaynak), str(k.adet), sayi(s.alan_m2, 4), self.ayar.toz(k.toz).ad,
                    "—" if s.kalinlik_um is None else sayi(s.kalinlik_um, 0), sayi(s.toz_g_adet, 1), sayi(s.toz_kg, 3),
                    f"{sayi(s.tutar, 2)} {self.ayar.para}"]
        except ValueError as h:
            veri = [k.ad, f"HATA: {h}", str(k.adet), "—", "", "", "", "", ""]
        for c, x in enumerate(veri):
            it = QTableWidgetItem(x)
            if c in (2, 3, 5, 6, 7, 8):
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tablo.setItem(r, c, it)

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
            f"{tozlar}<br>Toz {sayi(o.toz_tl, 2)} {p} + proses {sayi(o.proses_tl, 2)} {p} = <b>{sayi(o.tutar, 2)} {p}</b>"
            + uyari)

    def _secili(self) -> int:
        r = self.tablo.currentRow()
        return r if 0 <= r < len(self.kalemler) and self.tablo.selectedItems() else -1

    # -- ayrıntı paneli
    def _ayrinti_bos(self):
        w = QLabel("Bir kalem seçin ya da ekleyin.\n\nÇizim ekle: DXF / DWG (2D açınım, 3D yüzey / katı) ya da STL.\n"
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

    def _ayrinti_sonuc(self, r: int):
        k = self.kalemler[r]
        try:
            s = kalem_sonucu(k, self.ayar)
            ham = kaynak_alani(k.kaynak) / 1e6
            p = self.ayar.para
            self._sonuc_etiketi.setText(
                f"Boyanacak alan: <b>{sayi(s.alan_m2, 4)} m²</b> / adet"
                + (f" (çizim {sayi(ham, 4)} − maske {sayi(k.maske_cm2 / 1e4, 4)})" if k.maske_cm2 else "")
                + f"<br>Toz: <b>{sayi(s.toz_g_adet, 1)} g</b> / adet · toplam <b>{sayi(s.toz_kg, 3)} kg</b>"
                + f"<br>Tutar: {sayi(s.toz_tl, 2)} + {sayi(s.proses_tl, 2)} = <b>{sayi(s.tutar, 2)} {p}</b>")
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
                    d = IceAktar(yol, self._varsayilan_toz(), self, self.ayar.oda_yolu)
                finally:
                    QApplication.restoreOverrideCursor()
            except Exception as h:  # bozuk / desteklenmeyen dosya: ezdxf çeşitli hatalar atar
                QMessageBox.warning(self, UYGULAMA, f"{os.path.basename(yol)} açılamadı:\n{h}")
                continue
            if d.exec() == QDialog.Accepted:
                yeni = d.kalemler()
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
        except OSError as h:
            ilerleme.close()
            QMessageBox.warning(self, UYGULAMA, f"Güncelleme yapılamadı:\n{h}\n\nElle indirmek için: "
                                f"{guncelleme.SAYFA}")
            return
        self.degisti = False
        QApplication.quit()

    def hakkinda(self):
        QMessageBox.about(self, UYGULAMA,
                          f"<b>{UYGULAMA}</b> {SURUM}<br><br>Toz = alan ÷ sarfiyat (m²/kg) ya da (teorik) "
                          "alan × kalınlık × yoğunluk ÷ transfer verimi."
                          "<br>Alan DXF / DWG'den (2D açınım, 3D yüzey ve katı), STL'den ya da kalıptan."
                          "<br><br>© 2026 Enes Özbek · MIT lisansı (LICENSE)<br>Qt / PySide6 (LGPL-3.0), ezdxf (MIT) ve "
                          "diğer bileşenler: UCUNCU_TARAF_LISANSLARI.txt")

    # -- sürükle bırak / kapanış
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        yollar = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        projeler = [y for y in yollar if y.lower().endswith(".tozboya")]
        cizimler = [y for y in yollar if y.lower().endswith((".dxf", ".dwg", ".stl"))]
        if projeler:
            self.ac(yol=projeler[0])
        if cizimler:
            self.dosya_ekle(yollar=cizimler)

    def closeEvent(self, e):
        if self._kaydedilsin_mi():
            e.accept()
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
