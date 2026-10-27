# -*- coding: utf-8 -*-
"""Windows paketi (Python gerektirmez): PyInstaller ile dist/TozBoyaHesap/TozBoyaHesap.exe ve
dist/TozBoyaHesap_<sürüm>.zip. Paket bitince exe "--self-test" ile çalıştırılır; başarısızsa paket hatalı sayılır.
Lisans dosyaları (LICENSE, üçüncü taraf lisansları) exe'nin yanına kopyalanır.

  python paketle.py            (önce: python -m pip install -r requirements-paket.txt)
"""
import os
import shutil
import subprocess
import sys

from surum import SURUM

AD = "TozBoyaHesap"
KOK = os.path.dirname(os.path.abspath(__file__))
LISANS_DOSYALARI = ["LICENSE", "UCUNCU_TARAF_LISANSLARI.txt", "ucuncu_taraf_lisanslari"]
# ezdxf eklentilerinin ve Qt'nin kullanılmayan parçaları (paket küçülür; kendi denemesi eksik kalanı yakalar)
GEREKSIZ = ["matplotlib", "tkinter", "PIL", "lxml", "yaml", "ezdxf.addons.drawing", "IPython",
            "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtNetwork", "PySide6.QtPdf", "PySide6.QtSvg",
            "PySide6.QtOpenGL", "PySide6.QtDBus", "PySide6.QtWebEngineCore", "PySide6.QtMultimedia"]


def main() -> int:
    # Windows konsolu (cp1252 / cp857) Türkçe harfleri yazamayıp çökmesin
    for akis in (sys.stdout, sys.stderr):
        if akis is not None and hasattr(akis, "reconfigure"):
            akis.reconfigure(encoding="utf-8", errors="replace")
    os.chdir(KOK)
    for k in ("build", os.path.join("dist", AD)):
        shutil.rmtree(k, ignore_errors=True)
    komut = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
             "--name", AD, "--collect-submodules", "ezdxf.entities", "--collect-submodules", "ezdxf.acis"]
    for m in GEREKSIZ:
        komut += ["--exclude-module", m]
    komut.append("TozBoya.py")
    print(" ".join(komut))
    if subprocess.call(komut) != 0:
        print("PyInstaller başarısız.")
        return 1
    exe = os.path.join("dist", AD, AD + (".exe" if os.name == "nt" else ""))
    ortam = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    if subprocess.call([exe, "--self-test"], env=ortam) != 0:
        print("PAKET KENDİ DENEMESİNDEN GEÇMEDİ.")
        return 1
    print("Paketin kendi denemesi başarılı.")
    hedef = os.path.join("dist", AD)
    for f in LISANS_DOSYALARI:
        (shutil.copytree if os.path.isdir(f) else shutil.copy2)(f, os.path.join(hedef, f))
    zip_yol = shutil.make_archive(os.path.join("dist", f"{AD}_{SURUM}"), "zip", "dist", AD)
    print("Hazır:", exe, "ve", zip_yol)
    return 0


if __name__ == "__main__":
    sys.exit(main())
