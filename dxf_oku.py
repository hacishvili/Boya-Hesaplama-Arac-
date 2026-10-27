# -*- coding: utf-8 -*-
"""DXF okuma: birim, katmanlar, 2D kapalı konturlar (parça + delik) ve 3D gövdeler.

2D: çizgi, yay, daire, elips, spline, polyline. Kapalı olanlar doğrudan kontur; açık parçalar uç uca
eklenir (geometri.zincirle). Kesikli çizgi tipleri (eksen, gizli, büküm çizgisi) varsayılan olarak alınmaz.
Ölçü, yazı, tarama ve benzeri çizim öğeleri alana girmez.

3D: 3DFACE, POLYFACE / POLYMESH, MESH ağları; 3DSOLID / BODY / REGION / SURFACE (ACIS katı): düzlem, silindir,
koni, küre, torus ve kırpılmamış spline yüzler (acis_alan). Hesaplanamayan yüzü olan gövde hatasıyla döner,
eksik alan sessizce verilmez."""
from __future__ import annotations

import math
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from geometri import Ag, Kontur, Parca2D, yerlestir, zincirle

# $INSUNITS → mm (0: birimsiz; mm sayılır, pencere sorar)
BIRIMLER: Dict[int, Tuple[str, float]] = {
    0: ("birimsiz", 1.0), 1: ("inç", 25.4), 2: ("fit", 304.8), 4: ("mm", 1.0), 5: ("cm", 10.0),
    6: ("m", 1000.0), 8: ("mikroinç", 25.4e-6), 9: ("mil", 0.0254), 10: ("yarda", 914.4),
    13: ("mikron", 0.001), 14: ("dm", 100.0),
}
EGRI_TURLERI = {"LINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "LWPOLYLINE", "POLYLINE"}
ACIS_TURLERI = {"3DSOLID", "BODY", "REGION", "SURFACE", "EXTRUDEDSURFACE", "LOFTEDSURFACE",
                "REVOLVEDSURFACE", "SWEPTSURFACE", "PLANESURFACE"}
SUREKLI = {"", "CONTINUOUS", "BYBLOCK", "BYLAYER"}
KESIKLI_ADLAR = ("DASH", "HIDDEN", "CENTER", "DOT", "PHANTOM", "BORDER", "DIVIDE", "KESIK", "EKSEN", "GIZLI")



@dataclass
class Govde3D:
    ad: str
    tur: str                       # varlık türü (3DFACE, MESH, 3DSOLID, STL ...)
    katman: str = ""
    ag: Optional[Ag] = None
    hata: str = ""                 # dolu: alan hesaplanamadı, nedeni
    tani: str = ""                 # hata raporu için ham veri (ACIS yüzey kaydı)
    profil: Optional[object] = None  # profil.Profil (mm, mm²): dış / iç / uç yüzeyler
    sac: Optional[object] = None     # profil.Sac (mm, mm²): kalınlık, iki yüz, kesim kenarları

    @property
    def alan(self) -> float:
        return self.ag.alan if self.ag is not None and not self.hata else 0.0

    @property
    def kapali(self) -> bool:
        return self.ag is not None and self.ag.kapali_mi()


@dataclass
class DxfSonuc:
    birim_kodu: int = 0
    olcek: float = 1.0             # çizim birimi → mm
    katmanlar: Dict[str, int] = field(default_factory=dict)   # katman → alana girebilecek öğe sayısı
    parcalar: List[Parca2D] = field(default_factory=list)
    govdeler: List[Govde3D] = field(default_factory=list)
    atlanan: Counter = field(default_factory=Counter)        # alana girmeyen öğe türleri
    kesikli: int = 0               # alınmayan kesikli çizgi sayısı
    kullanilamayan: int = 0        # kontur kapatmayan açık çizgi sayısı
    uyarilar: List[str] = field(default_factory=list)

    @property
    def birim_adi(self) -> str:
        return BIRIMLER.get(self.birim_kodu, (f"kod {self.birim_kodu}", 1.0))[0]


ODA_INDIR = "https://www.opendesign.com/guestfiles/oda_file_converter"


class DwgHatasi(Exception):
    pass


def oda_bul(ayar_yolu: str = "") -> str:
    """ODA File Converter'ın yolu: ayardaki, yoksa Program Files\\ODA\\ODAFileConverter <sürüm>\\ (en yenisi)."""
    import glob
    import shutil
    adaylar = [ayar_yolu] if ayar_yolu else []
    for kok in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), os.environ.get("ProgramFiles(x86)")):
        if kok:
            adaylar += sorted(glob.glob(os.path.join(kok, "ODA", "ODAFileConverter*", "ODAFileConverter.exe")),
                              reverse=True)
    adaylar.append(shutil.which("ODAFileConverter") or "")
    return next((a for a in adaylar if a and os.path.isfile(a)), "")


def dwg_ac(yol: str, oda_yolu: str = ""):
    """DWG'yi ODA File Converter ile DXF 2010'a çevirip açar (katılar metin ACIS olarak gelir)."""
    import ezdxf
    exe = oda_bul(oda_yolu)
    if not exe:
        raise DwgHatasi("DWG dosyasını açmak için ücretsiz ODA File Converter gerekli. İndirip kurun (ya da yolunu "
                        f"Ayarlar'da gösterin): {ODA_INDIR}\nYa da çizimi AutoCAD'de DXF olarak kaydedin.")
    from ezdxf.addons import odafc
    ezdxf.options.set("odafc-addon", "win_exec_path" if os.name == "nt" else "unix_exec_path", exe)
    try:
        return odafc.readfile(yol, version="R2010")
    except odafc.ODAFCError as h:
        raise DwgHatasi(f"DWG dönüştürülemedi ({h}).") from h


def belge_ac(yol: str, oda_yolu: str = ""):
    """DXF'i açar (bozuk dosyada ezdxf'in onarıcı okuyucusuna geçer); DWG'yi ODA File Converter ile."""
    import ezdxf
    from ezdxf import recover
    if yol.lower().endswith(".dwg"):
        return dwg_ac(yol, oda_yolu)
    try:
        return ezdxf.readfile(yol)
    except ezdxf.DXFStructureError:
        doc, denetci = recover.readfile(yol)
        return doc


def _kesikli_mi(e, doc) -> bool:
    lt = str(e.dxf.get("linetype", "BYLAYER") or "BYLAYER")
    if lt.upper() == "BYLAYER":
        ad = e.dxf.get("layer", "0")
        katman = doc.layers.get(ad) if doc is not None and ad in doc.layers else None  # tabloda olmayabilir
        lt = str(katman.dxf.get("linetype", "CONTINUOUS")) if katman is not None else "CONTINUOUS"
    if lt.upper() in SUREKLI:
        return False
    tip = doc.linetypes.get(lt) if doc is not None and lt in doc.linetypes else None
    if tip is None:  # tabloda tanımı yok: adından karar ver (bilinmeyen ad sürekli sayılır, kontur kaybolmasın)
        return any(x in lt.upper() for x in KESIKLI_ADLAR)
    try:
        return any(abs(float(x)) > 0.0 for x in tip.simplified_line_pattern())
    except (AttributeError, TypeError, ValueError):
        return True


def _ozyinelemeli(alan, sayac: Counter, derinlik: int = 0):
    """Blokları (INSERT) açarak öğeleri verir; ölçü, açıklama ve benzeri blok gibi açılmaz, sayılıp atlanır."""
    for e in alan:
        tur = e.dxftype()
        if tur == "INSERT":
            if derinlik > 20:
                sayac["iç içe blok (20+)"] += 1
                continue
            try:
                yield from _ozyinelemeli(e.virtual_entities(), sayac, derinlik + 1)
            except Exception:  # ezdxf dönüştüremediği blok öğesinde hata atar (eğik ölçekli katı ...)
                sayac["açılamayan blok"] += 1
            continue
        yield e


def _bulge_noktalari(p0, p1, bulge: float, sapma: float):
    """p0 → p1 yaylı polyline kenarının noktaları (p0 hariç, p1 dahil), OCS 2D; sehim ≤ sapma."""
    x0, y0 = p0
    x1, y1 = p1
    c = math.hypot(x1 - x0, y1 - y0)
    if abs(bulge) < 1e-12 or c == 0.0:
        return [(x1, y1)]
    aci = 4.0 * math.atan(bulge)             # işaretli merkez açısı (+: saat tersi)
    r = c / (2.0 * math.sin(abs(aci) / 2.0))
    # kirişin ortasından merkeze: kirişe dik, yay yönüne göre sola / sağa
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    d = r * math.cos(abs(aci) / 2.0)         # 180°'den büyük yayda eksi: merkez kirişin öbür yanında
    ux, uy = (x1 - x0) / c, (y1 - y0) / c
    yon = 1.0 if aci > 0 else -1.0
    cx, cy = mx - uy * d * yon, my + ux * d * yon
    a0 = math.atan2(y0 - cy, x0 - cx)
    adim_aci = 2.0 * math.acos(max(-1.0, 1.0 - sapma / r)) if sapma < r else math.pi / 2
    n = max(2, int(math.ceil(abs(aci) / max(adim_aci, 1e-6))))
    out = [(cx + r * math.cos(a0 + aci * i / n), cy + r * math.sin(a0 + aci * i / n)) for i in range(1, n)]
    out.append((x1, y1))
    return out


def _cizgi_noktalari(e, sapma: float):
    """Eğrinin WCS noktaları: yay ve daire gerçek yay üstünden (sehim ≤ sapma); polyline yaylı köşeleriyle."""
    from ezdxf.math import Vec3
    tur = e.dxftype()
    if tur == "LINE":
        return [Vec3(e.dxf.start), Vec3(e.dxf.end)]
    if tur in ("ARC", "CIRCLE", "ELLIPSE", "SPLINE"):
        return [Vec3(p) for p in e.flattening(sapma)]
    if tur == "POLYLINE" and e.is_3d_polyline:
        pts = [Vec3(v.dxf.location) for v in e.vertices]
        if e.is_closed and pts:
            pts.append(pts[0])
        return pts
    if tur == "LWPOLYLINE":
        kose = [(x, y, b) for x, y, b in e.get_points("xyb")]
        z = float(e.dxf.get("elevation", 0.0) or 0.0)
    else:  # 2D POLYLINE
        kose = [(v.dxf.location[0], v.dxf.location[1], float(v.dxf.get("bulge", 0.0) or 0.0)) for v in e.vertices]
        z = float(e.dxf.get("elevation", (0, 0, 0))[2]) if e.dxf.hasattr("elevation") else 0.0
    if not kose:
        return []
    kapali = bool(e.closed) if tur == "LWPOLYLINE" else bool(e.is_closed)
    out = [(kose[0][0], kose[0][1])]
    son = len(kose) if kapali else len(kose) - 1
    for i in range(son):
        x0, y0, b = kose[i]
        x1, y1, _ = kose[(i + 1) % len(kose)]
        out.extend(_bulge_noktalari((x0, y0), (x1, y1), b, sapma))
    ocs = e.ocs()
    return [Vec3(ocs.to_wcs(Vec3(x, y, z))) for x, y in out]


def cozumle(doc, olcek: Optional[float] = None, haric: Iterable[str] = (), kesikli_al: bool = False,
            tol_mm: float = 0.01) -> DxfSonuc:
    """doc: ezdxf belgesi. olcek: çizim birimi → mm (None: $INSUNITS). haric: alınmayacak katmanlar."""
    from ezdxf.render import MeshBuilder

    kod = int(doc.header.get("$INSUNITS", 0) or 0)
    s = DxfSonuc(birim_kodu=kod)
    s.olcek = float(olcek) if olcek else BIRIMLER.get(kod, ("", 1.0))[1]
    k = s.olcek
    haric_set: Set[str] = {h.upper() for h in haric}
    sapma = 0.0005 / k  # yay → çokgen: en çok 0,0005 mm sehim (çizim biriminde)

    kapali: List[Kontur] = []
    acik: List[List[Tuple[float, float]]] = []
    yuz3: Dict[str, List[List[Tuple[float, float, float]]]] = {}
    sayac = Counter()

    for e in _ozyinelemeli(doc.modelspace(), s.atlanan):
        tur = e.dxftype()
        katman = str(e.dxf.get("layer", "0"))
        if tur in EGRI_TURLERI or tur in ACIS_TURLERI or tur in ("3DFACE", "MESH"):
            s.katmanlar[katman] = s.katmanlar.get(katman, 0) + 1
        else:
            s.atlanan[tur] += 1
            continue
        if katman.upper() in haric_set:
            continue

        if tur == "3DFACE":
            v = [tuple(p) for p in e.wcs_vertices()]
            if len(v) == 4 and math.dist(v[2], v[3]) < 1e-12:
                v = v[:3]
            yuz3.setdefault(katman, []).append([(p[0] * k, p[1] * k, p[2] * k) for p in v])
            continue
        if tur == "POLYLINE" and (e.is_poly_face_mesh or e.is_polygon_mesh):
            mb = MeshBuilder.from_polyface(e)
            sayac["ag"] += 1
            yuzler = [[(p.x * k, p.y * k, p.z * k) for p in f] for f in mb.faces_as_vertices()]
            for i, g in enumerate(Ag(yuzler).govdeler()):
                s.govdeler.append(Govde3D(f"{tur.title()} {sayac['ag']}" + (f".{i + 1}" if i else ""),
                                          "POLYFACE", katman, g))
            continue
        if tur == "MESH":
            mb = MeshBuilder.from_mesh(e)
            sayac["ag"] += 1
            yuzler = [[(p.x * k, p.y * k, p.z * k) for p in f] for f in mb.faces_as_vertices()]
            for i, g in enumerate(Ag(yuzler).govdeler()):
                s.govdeler.append(Govde3D(f"Mesh {sayac['ag']}" + (f".{i + 1}" if i else ""), tur, katman, g))
            if int(e.dxf.get("subdivision_levels", 0) or 0) > 0:
                s.uyarilar.append("MESH yumuşatma (subdivision) düzeyi var; alan kaba ağdan hesaplandı.")
            continue
        if tur in ACIS_TURLERI:
            sayac["katı"] += 1
            s.govdeler.extend(acis_govdeleri(e, f"{'Katı' if tur in ('3DSOLID', 'BODY') else tur.title()} "
                                                f"{sayac['katı']}", k, katman))
            continue

        # 2D eğri
        if not kesikli_al and _kesikli_mi(e, doc):
            s.kesikli += 1
            continue
        try:
            pts3 = _cizgi_noktalari(e, sapma)
        except (TypeError, ValueError, ArithmeticError):
            s.atlanan[tur] += 1
            continue
        if len(pts3) < 2:
            continue
        if max(q.z for q in pts3) - min(q.z for q in pts3) > 1e-6 * max(1.0, abs(pts3[0].z)) + tol_mm / k:
            s.atlanan["3B tel çizgi"] += 1
            continue
        pts = [(q.x * k, q.y * k) for q in pts3]
        if math.dist(pts[0], pts[-1]) <= 1e-9 * max(1.0, abs(pts[0][0]) + abs(pts[0][1])) and len(pts) > 3:
            kontur = Kontur(pts, katman)
            if tur == "CIRCLE":  # çokgen yayın içinde kalır; daire tam formülle
                r = float(e.dxf.radius) * k
                kontur.alan, kontur.cevre = math.pi * r * r, 2.0 * math.pi * r
            kapali.append(kontur)
        else:
            acik.append(pts)

    for katman, yuzler in yuz3.items():
        for i, g in enumerate(Ag(yuzler).govdeler()):
            s.govdeler.append(Govde3D(f"3DFACE {katman} {i + 1}", "3DFACE", katman, g))

    if acik:
        zincir, s.kullanilamayan = zincirle(acik, tol=tol_mm)
        kapali.extend(Kontur(z) for z in zincir)
    s.parcalar = yerlestir(kapali)
    if s.kullanilamayan:
        s.uyarilar.append(f"{s.kullanilamayan} açık çizgi kapalı bir kontura bağlanamadı ve alınmadı "
                          f"(büküm çizgisi, eksen ya da uçları {tol_mm} mm'den uzak çizgiler).")
    if kod == 0:
        s.uyarilar.append("Dosyada birim yazmıyor; mm sayıldı. Gerekirse birimi değiştirin.")
    olculer = [max(p.olcu) for p in s.parcalar]
    for g in s.govdeler:
        if g.ag is not None and g.ag.yuzler:
            a, b = g.ag.kutu()
            olculer.append(max(b[i] - a[i] for i in range(3)))
    u = birim_uyarisi(max(olculer) if olculer else 0.0)
    if u:
        s.uyarilar.append(u)
    return s


_SAYI = r"(\d+(?:[.,]\d+)?)"
_KALINLIK_DESEN = [
    rf"(?<![a-zçğıöşü])(?:t|s|thk|kal[ıi]nl[ıi]k|thickness|et)\s*[=:]\s*{_SAYI}\s*(?:mm)?",   # t=2, S: 1,5
    rf"(?<![a-zçğıöşü])(?:kal[ıi]nl[ıi]k|thickness|sac)\s+{_SAYI}\s*mm",                   # kalınlık 2 mm
    rf"{_SAYI}\s*mm\s*(?:sac|dkp|hrp|crp|paslanmaz|galvaniz|alüminyum|aluminyum)",          # 2 mm DKP
]


def _kalinlik_ara(metin: str, gevsek: bool = False) -> List[float]:
    """Metindeki sac kalınlığı yazımları (mm, 0,3 … 30). gevsek: katman / dosya adında yalnız '2mm', 'T2' de."""
    import re
    desenler = list(_KALINLIK_DESEN)
    if gevsek:
        desenler += [rf"(?<![\d.,]){_SAYI}\s*mm(?![a-z])", rf"(?<![a-zçğıöşü])t\s*{_SAYI}(?![\d])"]
    out = []
    for d in desenler:
        for m in re.finditer(d, metin.lower()):
            x = float(m.group(1).replace(",", "."))
            if 0.3 <= x <= 30:
                out.append(x)
    return out


def kalinlik_ipucu(doc, dosya_adi: str = "") -> Tuple[Optional[float], str, Dict[str, float]]:
    """Çizimden sac kalınlığı: (varsayılan, kaynağı, katman → kalınlık). Yazılarda tek bir değer varsa o;
    yoksa dosya adında. Katman adında kalınlık yazıyorsa o katmandaki parçalar için ayrıca."""
    katman: Dict[str, float] = {}
    adlar = {l.dxf.name for l in doc.layers} | {e.dxf.get("layer", "0") for e in doc.modelspace()}
    for ad in adlar:  # tablodaki ve öğelerin kullandığı (tabloda olmayabilir) katmanlar
        v = set(_kalinlik_ara(ad, gevsek=True))
        if len(v) == 1:
            katman[ad.upper()] = v.pop()
    yazi = set()
    for e in doc.modelspace():
        if e.dxftype() == "TEXT":
            yazi |= set(_kalinlik_ara(e.dxf.get("text", "")))
        elif e.dxftype() == "MTEXT":
            yazi |= set(_kalinlik_ara(e.plain_text()))
    if len(yazi) == 1:
        return yazi.pop(), "çizimdeki yazıdan", katman
    if dosya_adi:
        v = set(_kalinlik_ara(os.path.splitext(os.path.basename(dosya_adi))[0], gevsek=True))
        if len(v) == 1:
            return v.pop(), "dosya adından", katman
    if len(set(katman.values())) == 1 and katman:
        return next(iter(katman.values())), "katman adından", katman
    return None, "", katman


def birim_uyarisi(en_buyuk_mm: float) -> str:
    """Mobilya parçası için olağandışı büyüklük: birim büyük olasılıkla yanlış (m yazıp mm çizmek gibi)."""
    if en_buyuk_mm > 5000.0:
        return (f"En büyük parça {en_buyuk_mm / 1000:.1f} m".replace(".", ",") + ": çizim birimi yanlış olabilir "
                "(dosyada m ya da inç yazıp mm çizilmiş olabilir). Birimi kontrol edin.")
    if 0.0 < en_buyuk_mm < 2.0:
        return (f"En büyük parça {en_buyuk_mm:.3f}".replace(".", ",")
                + " mm: çizim birimi yanlış olabilir. Birimi kontrol edin.")
    return ""


# ---------------------------------------------------------------- ACIS

def acis_govdeleri(e, ad: str, k: float, katman: str = "") -> List[Govde3D]:
    """ACIS varlığının her parçası (lump) bir gövde (acis_alan). Bir yüzü bile hesaplanamayan gövde hatasıyla
    döner; alanı eksik verilmez."""
    import acis_alan
    try:
        govdeler = acis_alan.govdeler(e)
    except Exception as hata:  # bozuk / bilinmeyen ACIS verisi: ezdxf'in ayrıştırıcısı çeşitli hatalar atar
        return [Govde3D(ad, e.dxftype(), katman, None, f"ACIS verisi okunamadı ({hata}).")]
    out: List[Govde3D] = []
    for i, g in enumerate(govdeler):
        isim = ad if len(govdeler) == 1 else f"{ad}.{i + 1}"
        donguler = [[(x * k, y * k, z * k) for x, y, z in d] for d in g.donguler]
        ag = Ag(donguler, alan_hazir=g.alan * k * k, tel=True, kapali_hazir=g.kapali) if donguler or not g.hata else None
        hata = ""
        if g.hata:
            hata = (g.hata + ". Bu gövdenin alanı DXF'ten hesaplanamıyor: çizimi STL olarak isteyin "
                    "(AutoCAD: STLOUT) ya da parçayı kalıptan ekleyin.")
        pr = None
        if g.profil is not None and not hata:
            pr = g.profil
            pr.boy, pr.kesit, pr.bosluk = pr.boy * k, (pr.kesit[0] * k, pr.kesit[1] * k), pr.bosluk * k
            pr.dis, pr.uc = pr.dis * k * k, pr.uc * k * k
            pr.ic = [(a * k * k, L * k) for a, L in pr.ic]
        sac = None
        if g.sac is not None and not hata:
            sac = g.sac
            sac.kalinlik, sac.yuz, sac.kenar = sac.kalinlik * k, sac.yuz * k * k, sac.kenar * k * k
        out.append(Govde3D(isim, e.dxftype(), katman, ag, hata, "\n\n".join(g.tani), pr, sac))
    return out
