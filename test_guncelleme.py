# -*- coding: utf-8 -*-
"""GitHub'dan güncelleme: sürüm karşılaştırma, yayın yanıtı, özet doğrulama, kurulum betiği (ağ sahte)."""
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.request

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import guncelleme

YAYIN = {"tag_name": "v0.10.0", "body": "Yenilikler",
         "assets": [{"name": "TozBoyaHesap_0.10.0.zip", "browser_download_url": "https://x/z.zip"},
                    {"name": "TozBoyaHesap_0.10.0.zip.sha256", "browser_download_url": "https://x/z.zip.sha256"}]}


class Sahte(io.BytesIO):
    headers = {"Content-Length": "0"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Guncelleme(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp()
        self.asil = urllib.request.urlopen

    def tearDown(self):
        urllib.request.urlopen = self.asil
        shutil.rmtree(self.klasor, ignore_errors=True)

    def test_surum_karsilastirma(self):
        self.assertTrue(guncelleme.yeni_mi("v0.10.0", "0.9.3"))  # sayı olarak, metin olarak değil
        self.assertFalse(guncelleme.yeni_mi("0.6.0", "0.6.0"))
        self.assertFalse(guncelleme.yeni_mi("0.5.9", "0.6.0"))

    def test_yayin_okuma_ve_ag(self):
        s = guncelleme.surum_oku(YAYIN)
        self.assertEqual((s.surum, s.zip_url, s.sha_url), ("0.10.0", "https://x/z.zip", "https://x/z.zip.sha256"))
        self.assertIsNone(guncelleme.surum_oku({"tag_name": "v1.0.0", "assets": []}))  # paketsiz yayın
        urllib.request.urlopen = lambda *a, **k: Sahte(json.dumps(YAYIN).encode())
        self.assertEqual(guncelleme.son_surum().surum, "0.10.0")

        def yok(*a, **k):
            raise OSError("ağ yok")
        urllib.request.urlopen = yok
        self.assertIsNone(guncelleme.son_surum())

    def test_indirme_ve_ozet(self):
        veri = b"PK" + os.urandom(5000)
        urllib.request.urlopen = lambda *a, **k: Sahte(veri)
        yol = os.path.join(self.klasor, "z.zip")
        guncelleme.indir("https://x/z.zip", yol, lambda a, t: True)
        ozet = hashlib.sha256(veri).hexdigest()
        self.assertTrue(guncelleme.ozet_dogru(yol, f"{ozet}  TozBoyaHesap_0.10.0.zip\n"))
        self.assertFalse(guncelleme.ozet_dogru(yol, "0" * 64 + "  z.zip"))
        self.assertFalse(guncelleme.ozet_dogru(yol, "bozuk"))
        urllib.request.urlopen = lambda *a, **k: Sahte(veri)
        with self.assertRaises(OSError):  # iptal
            guncelleme.indir("https://x/z.zip", yol, lambda a, t: False)

    def test_kurulum_betigi(self):
        b = guncelleme.kurulum_betigi(r"C:\T\yeni\TozBoyaHesap", r"C:\Prog\TozBoyaHesap", r"C:\T\yeni", 4242)
        self.assertIn('tasklist /FI "PID eq 4242"', b)
        self.assertIn(r'robocopy "C:\T\yeni\TozBoyaHesap" "C:\Prog\TozBoyaHesap" /E', b)
        self.assertIn("TozBoyaHesap.exe", b)
        self.assertIn('rmdir /s /q "C:\\T\\yeni"', b)
        with self.assertRaises(OSError):  # kaynaktan çalışırken kendini güncellemez
            guncelleme.kur(os.path.join(self.klasor, "z.zip"))

    def test_sessiz_hazirlama(self):
        veri = b"PK" + os.urandom(3000)
        ozet = hashlib.sha256(veri).hexdigest() + "  TozBoyaHesap_0.10.0.zip\n"
        istek = []

        def ag(r, **k):
            url = r.full_url if hasattr(r, "full_url") else r
            istek.append(url)
            if "api.github.com" in url:
                return Sahte(json.dumps(YAYIN).encode())
            return Sahte(ozet.encode() if url.endswith(".sha256") else veri)
        urllib.request.urlopen = ag
        eski = os.path.join(self.klasor, "TozBoyaHesap_0.9.0.zip")
        open(eski, "wb").close()
        self.assertIsNone(guncelleme.hazirla("0.10.0", self.klasor))  # güncel
        surum, yol = guncelleme.hazirla("0.9.0", self.klasor)
        self.assertEqual(surum, "0.10.0")
        with open(yol, "rb") as f:
            self.assertEqual(f.read(), veri)
        self.assertFalse(os.path.exists(eski))  # eski sürümün zip'i silinir
        istek.clear()
        guncelleme.hazirla("0.9.0", self.klasor)  # zaten indirilmiş: zip yeniden indirilmez
        self.assertFalse(any(u.endswith(".zip") for u in istek))
        ozet = "0" * 64 + "  z.zip"  # bozuk indirme: kurulmaz
        os.remove(yol)
        self.assertIsNone(guncelleme.hazirla("0.9.0", self.klasor))
        self.assertEqual([a for a in os.listdir(self.klasor) if a.endswith((".zip", ".part"))], [])

    def test_sessiz_kurulum_betigi_ve_hata(self):
        b = guncelleme.kurulum_betigi(r"C:\T\y", r"C:\P", r"C:\T", 7, baslat=False)
        self.assertNotIn("start", b)
        self.assertNotIn("pause", b)  # pencere yok: hata günlüğe
        self.assertIn(guncelleme.HATA_GUNLUGU, b)
        self.assertIn("start", guncelleme.kurulum_betigi(r"C:\T\y", r"C:\P", r"C:\T", 7))
        with open(guncelleme.HATA_GUNLUGU, "w", encoding="utf-8") as f:
            f.write("yazilamiyor")
        self.assertEqual(guncelleme.hata_oku(), "yazilamiyor")
        self.assertEqual(guncelleme.hata_oku(), "")  # okununca silinir

    def test_pencere_kapanista_kurar(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        os.environ["APPDATA"] = self.klasor
        import pencere
        w = pencere.AnaPencere()
        kur = []
        asil = guncelleme.kur
        guncelleme.kur = lambda z, pid=None, baslat=True: kur.append((z, baslat))
        try:
            w._sessiz_hazir(None)
            self.assertIsNone(w._hazir)
            zip_yolu = os.path.join(self.klasor, "z.zip")
            open(zip_yolu, "wb").close()
            w._sessiz_hazir(("0.10.0", zip_yolu))
            self.assertIn("0.10.0", w.statusBar().currentMessage())
            w.degisti = False
            w.close()
        finally:
            guncelleme.kur = asil
        self.assertEqual(kur, [(zip_yolu, False)])

    def test_pencere_sessiz_denetim(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        os.environ["APPDATA"] = self.klasor
        import pencere
        w = pencere.AnaPencere()
        cagri = []
        w._guncellemeyi_kur = lambda s: cagri.append(s)
        w._surum_sonucu(None, True)                                   # ağ yok: sessiz
        w._surum_sonucu(guncelleme.Surum(pencere.SURUM, "a", "b"), True)  # güncel: sessiz
        self.assertEqual(cagri, [])
        w.degisti = False
        w.close()


if __name__ == "__main__":
    unittest.main()
