# -*- coding: utf-8 -*-
"""GitHub Releases üzerinden güncelleme.

main'e yeni sürüm girince Actions paketi (TozBoyaHesap_<sürüm>.zip) ve SHA-256 özetini (.zip.sha256) v<sürüm>
etiketli sürüm olarak yayımlar. Program son sürümü GitHub API'sinden okur; yeniyse zip'i indirir, özeti doğrular,
geçici klasöre açar ve küçük bir .cmd ile program kapandıktan sonra dosyaları kendi klasörünün üstüne kopyalayıp
programı yeniden başlatır (çalışan exe'nin üzerine yazılamadığı için).

Sessiz güncelleme (varsayılan): açılışta yeni sürüm arka planda indirilip doğrulanır (hazirla), program kapanınca
kurulur (kur, baslat=False); bir sonraki açılış yeni sürümle olur. Kurulum hatası HATA_GUNLUGU dosyasına yazılır,
program sonraki açılışta bildirir."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

DEPO = "hacishvili/Boya-Hesaplama-Arac-"
API = f"https://api.github.com/repos/{DEPO}/releases/latest"
SAYFA = f"https://github.com/{DEPO}/releases/latest"
EXE = "TozBoyaHesap.exe"
HATA_GUNLUGU = os.path.join(tempfile.gettempdir(), "TozBoyaGuncelleme_hata.txt")


def indirme_klasoru() -> str:
    kok = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(kok, "TozBoyaHesap", "guncelleme")


@dataclass
class Surum:
    surum: str
    zip_url: str
    sha_url: str
    notlar: str = ""


def anahtar(s: str) -> Tuple[int, ...]:
    """'v0.10.2' → (0, 10, 2); karşılaştırma için."""
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3]) or (0,)


def yeni_mi(son: str, simdiki: str) -> bool:
    return anahtar(son) > anahtar(simdiki)


def surum_oku(veri: dict) -> Optional[Surum]:
    """GitHub 'latest release' yanıtından zip ve özet adresleri."""
    etiket = str(veri.get("tag_name", ""))
    zip_url = sha_url = ""
    for a in veri.get("assets", []):
        ad = str(a.get("name", ""))
        if ad.endswith(".zip"):
            zip_url = a.get("browser_download_url", "")
        elif ad.endswith(".zip.sha256"):
            sha_url = a.get("browser_download_url", "")
    if not etiket or not zip_url or not sha_url:
        return None
    return Surum(etiket.lstrip("vV"), zip_url, sha_url, str(veri.get("body") or ""))


def son_surum(zaman_asimi: float = 6.0) -> Optional[Surum]:
    """Son yayımlanan sürüm; ağ yoksa ya da yayın yoksa None."""
    istek = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                                 "User-Agent": "TozBoyaHesap"})
    try:
        with urllib.request.urlopen(istek, timeout=zaman_asimi) as y:
            return surum_oku(json.loads(y.read().decode("utf-8")))
    except (OSError, ValueError):
        return None


def indir(url: str, hedef: str, ilerleme: Optional[Callable[[int, int], bool]] = None) -> None:
    """ilerleme(alınan, toplam) False dönerse indirme iptal edilir (OSError)."""
    istek = urllib.request.Request(url, headers={"User-Agent": "TozBoyaHesap"})
    with urllib.request.urlopen(istek, timeout=30) as y, open(hedef, "wb") as f:
        toplam = int(y.headers.get("Content-Length") or 0)
        alinan = 0
        while True:
            parca = y.read(1 << 16)
            if not parca:
                break
            f.write(parca)
            alinan += len(parca)
            if ilerleme is not None and ilerleme(alinan, toplam) is False:
                raise OSError("İndirme iptal edildi.")


def ozet_dogru(dosya: str, ozet_metni: str) -> bool:
    """sha256sum biçimi: '<64 onaltılık>  <dosya adı>'."""
    m = re.search(r"\b([0-9a-fA-F]{64})\b", ozet_metni)
    if not m:
        return False
    h = hashlib.sha256()
    with open(dosya, "rb") as f:
        for parca in iter(lambda: f.read(1 << 20), b""):
            h.update(parca)
    return h.hexdigest().lower() == m.group(1).lower()


def hazirla(simdiki: str, klasor: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """Sessiz güncelleme: yeni sürüm varsa zip'i indirir ve özetini doğrular; (sürüm, zip yolu) ya da None.
    Daha önce indirilip doğrulanmış zip yeniden indirilmez; eski sürümlerin zip'leri silinir. Ağ hatasında None."""
    s = son_surum()
    if s is None or not yeni_mi(s.surum, simdiki):
        return None
    klasor = klasor or indirme_klasoru()
    try:
        os.makedirs(klasor, exist_ok=True)
        ad = f"TozBoyaHesap_{s.surum}.zip"
        zip_yolu = os.path.join(klasor, ad)
        for eski in os.listdir(klasor):
            if eski.startswith("TozBoyaHesap_") and not eski.startswith(ad):
                os.remove(os.path.join(klasor, eski))
        ozet_yolu = zip_yolu + ".sha256"
        indir(s.sha_url, ozet_yolu)
        with open(ozet_yolu, encoding="utf-8") as f:
            ozet = f.read()
        if not (os.path.exists(zip_yolu) and ozet_dogru(zip_yolu, ozet)):
            indir(s.zip_url, zip_yolu + ".part")
            if not ozet_dogru(zip_yolu + ".part", ozet):
                os.remove(zip_yolu + ".part")
                return None
            os.replace(zip_yolu + ".part", zip_yolu)
        return s.surum, zip_yolu
    except OSError:
        return None


def hata_oku() -> str:
    """Önceki sessiz kurulumun hatası (varsa); okununca silinir."""
    try:
        with open(HATA_GUNLUGU, encoding="utf-8", errors="replace") as f:
            metin = f.read().strip()
        os.remove(HATA_GUNLUGU)
        return metin
    except OSError:
        return ""


def kurulum_betigi(yeni: str, hedef: str, gecici: str, pid: int, baslat: bool = True) -> str:
    """Program kapanınca yeni dosyaları hedefe kopyalayan (baslat: sonra programı açan) .cmd içeriği. Betik pencere
    açmadan çalışır: hata ekrana değil HATA_GUNLUGU'na yazılır."""
    return "\r\n".join([
        "@echo off",
        "chcp 65001 >nul",
        ":bekle",
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto bekle)',
        f'robocopy "{yeni}" "{hedef}" /E /NFL /NDL /NJH /NJS /NP /R:5 /W:1 >nul',
        "if %ERRORLEVEL% GEQ 8 (",
        f'  echo Guncelleme kopyalanamadi: "{hedef}" klasorune yazilamiyor olabilir. > "{HATA_GUNLUGU}"',
        f'  rmdir /s /q "{gecici}"',
        '  (goto) 2>nul & del "%~f0"',
        ")",
        *([f'start "" "{os.path.join(hedef, EXE)}"'] if baslat else []),
        f'rmdir /s /q "{gecici}"',
        '(goto) 2>nul & del "%~f0"',
        "",
    ])


def kur(zip_yolu: str, pid: Optional[int] = None, baslat: bool = True) -> str:
    """Zip'i açar, kurulum betiğini yazar ve başlatır; betiğin yolunu döner. Çağıran program hemen kapanmalı.
    baslat=False: kurulumdan sonra program açılmaz (sessiz güncelleme, kapanışta)."""
    if not getattr(sys, "frozen", False) or os.name != "nt":
        raise OSError("Kendini güncelleme yalnız Windows paketinde çalışır; kaynaktan çalışıyorsanız 'git pull'.")
    hedef = os.path.dirname(os.path.abspath(sys.executable))
    gecici = tempfile.mkdtemp(prefix="TozBoyaGuncelleme_")
    with zipfile.ZipFile(zip_yolu) as z:
        z.extractall(gecici)
    yeni = gecici
    for kok, _, dosyalar in os.walk(gecici):  # zip içinde TozBoyaHesap\ klasörü
        if EXE in dosyalar:
            yeni = kok
            break
    else:
        raise OSError("İndirilen pakette program bulunamadı.")
    betik = os.path.join(tempfile.gettempdir(), f"TozBoyaGuncelle_{pid or os.getpid()}.cmd")  # gecici silinecek
    with open(betik, "w", encoding="utf-8") as f:
        f.write(kurulum_betigi(yeni, hedef, gecici, pid or os.getpid(), baslat))
    subprocess.Popen(["cmd", "/c", betik], creationflags=0x08000000, close_fds=True)  # pencere açmadan
    return betik
