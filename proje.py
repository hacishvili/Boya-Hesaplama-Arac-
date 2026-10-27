# -*- coding: utf-8 -*-
"""Proje dosyası (.tozboya, JSON) ve kullanıcının kalıcı ayarları (toz kütüphanesi, verim, proses ücreti)."""
from __future__ import annotations

import json
import os
from typing import List, Tuple

from hesap import Ayarlar, Kalem

SURUM = 1


def kaydet(yol: str, kalemler: List[Kalem], ayar: Ayarlar, musteri: str = "") -> None:
    veri = {"tur": "toz-boya-hesap", "surum": SURUM, "musteri": musteri, "ayarlar": ayar.sozluk(),
            "kalemler": [k.sozluk() for k in kalemler]}
    gecici = yol + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=1)
    os.replace(gecici, yol)


def ac(yol: str) -> Tuple[List[Kalem], Ayarlar, str]:
    with open(yol, encoding="utf-8") as f:
        veri = json.load(f)
    if veri.get("tur") != "toz-boya-hesap":
        raise ValueError("Bu dosya bir toz boya projesi değil.")
    return ([Kalem.sozlukten(k) for k in veri.get("kalemler", [])], Ayarlar.sozlukten(veri.get("ayarlar", {})),
            str(veri.get("musteri", "")))


def ayar_klasoru() -> str:
    kok = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(kok, "TozBoyaHesap")


def ayar_yolu() -> str:
    return os.path.join(ayar_klasoru(), "ayarlar.json")


def ayarlari_oku() -> Ayarlar:
    try:
        with open(ayar_yolu(), encoding="utf-8") as f:
            return Ayarlar.sozlukten(json.load(f))
    except (OSError, ValueError, KeyError, TypeError):
        return Ayarlar()


def ayarlari_yaz(a: Ayarlar) -> None:
    os.makedirs(ayar_klasoru(), exist_ok=True)
    gecici = ayar_yolu() + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(a.sozluk(), f, ensure_ascii=False, indent=1)
    os.replace(gecici, ayar_yolu())
