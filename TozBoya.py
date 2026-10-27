# -*- coding: utf-8 -*-
"""Toz Boya Hesabı — başlatıcı.

  TozBoya.py [proje.tozboya | çizim.dxf | çizim.dwg | çizim.stl ...]
  TozBoya.py --self-test     paketin kendi denemesi: örnek DXF'ler üretilir, okunur, hesaplanır, PDF yazılır
"""
import os
import sys


def kendini_dene() -> int:
    import math
    import tempfile

    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):  # pencereli pakette stdout yok
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    import ezdxf
    from ezdxf.acis import api as acis
    from ezdxf.render import forms

    import dxf_oku
    import pencere
    import rapor
    from hesap import Ayarlar, Kalem, kalem_sonucu

    hatalar = []
    klasor = tempfile.mkdtemp(prefix="tozboya_")
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (200, 0), (200, 100), (0, 100)], close=True)
    msp.add_circle((50, 50), 10)
    yol = os.path.join(klasor, "plaka.dxf")
    doc.saveas(yol)
    s = dxf_oku.cozumle(dxf_oku.belge_ac(yol))
    beklenen = 20000 - math.pi * 100
    if len(s.parcalar) != 1 or abs(s.parcalar[0].yuz_alani - beklenen) > 1e-6:
        hatalar.append("2D plaka alanı")
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    kati = doc.modelspace().add_3dsolid()
    acis.export_dxf(kati, [acis.body_from_mesh(forms.cube().scale(100, 50, 20))])
    yol3 = os.path.join(klasor, "kutu.dxf")
    doc.saveas(yol3)
    s3 = dxf_oku.cozumle(dxf_oku.belge_ac(yol3))
    if len(s3.govdeler) != 1 or abs(s3.govdeler[0].alan - 16000) > 1e-6:
        hatalar.append("3D katı alanı")
    try:  # DWG için ODA dönüştürücüsünü çağıran modül pakette olmalı
        from ezdxf.addons import odafc  # noqa: F401
    except ImportError:
        hatalar.append("DWG modülü (ezdxf.addons.odafc)")
    try:  # GitHub'dan güncelleme: HTTPS desteği pakette olmalı
        import ssl  # noqa: F401
        import guncelleme  # noqa: F401
    except ImportError:
        hatalar.append("güncelleme (ssl)")
    a = Ayarlar()
    k = Kalem("plaka", {"tur": "2d", "yuz_alani": beklenen, "cevre": 600 + 20 * math.pi, "olcu": [200, 100],
                        "kalinlik": 2.0}, 10, toz=a.tozlar[0].ad)
    if kalem_sonucu(k, a).toz_kg <= 0:
        hatalar.append("toz hesabı")
    pdf = os.path.join(klasor, "rapor.pdf")
    pencere.pdf_yaz(pdf, [k], a, "deneme")
    if not os.path.exists(pdf) or os.path.getsize(pdf) < 1000:
        hatalar.append("PDF rapor")
    rapor.csv_yaz(os.path.join(klasor, "rapor.csv"), [k], a)
    w = pencere.AnaPencere()
    w.kalemler.append(k)
    w._yenile(0)
    w.degisti = False
    w.close()
    print("KENDİ DENEMESİ: " + ("BAŞARILI" if not hatalar else "BAŞARISIZ: " + ", ".join(hatalar)))
    return 1 if hatalar else 0


def main() -> int:
    if "--self-test" in sys.argv:
        return kendini_dene()
    from PySide6.QtCore import QLocale
    from PySide6.QtWidgets import QApplication

    QLocale.setDefault(QLocale(QLocale.Turkish, QLocale.Turkey))
    app = QApplication(sys.argv)
    app.setApplicationName("Toz Boya Hesabı")
    app.setOrganizationName("TozBoyaHesap")
    app.setStyle("Fusion")
    import pencere

    w = pencere.AnaPencere()
    w.show()
    if getattr(sys, "frozen", False) and w.ayar.guncelleme:  # paketlenmiş programda açılışta yeni sürüm denetimi
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, w.guncelleme_denetle)
    dosyalar = [a for a in sys.argv[1:] if not a.startswith("-") and os.path.isfile(a)]
    projeler = [d for d in dosyalar if d.lower().endswith(".tozboya")]
    if projeler:
        w.ac(yol=projeler[0])
    cizimler = [d for d in dosyalar if d.lower().endswith((".dxf", ".dwg", ".stl"))]
    if cizimler:
        w.dosya_ekle(yollar=cizimler)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
