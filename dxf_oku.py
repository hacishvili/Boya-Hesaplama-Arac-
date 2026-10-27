# -*- coding: utf-8 -*-
"""DXF okuma: birim, katmanlar, 2D kapalı konturlar (parça + delik) ve 3D gövdeler.

2D: çizgi, yay, daire, elips, spline, polyline. Kapalı olanlar doğrudan kontur; açık parçalar uç uca
eklenir (geometri.zincirle). Kesikli çizgi tipleri (eksen, gizli, büküm çizgisi) varsayılan olarak alınmaz.
Ölçü, yazı, tarama ve benzeri çizim öğeleri alana girmez.

3D: 3DFACE, POLYFACE / POLYMESH, MESH ağları; 3DSOLID / BODY / REGION / SURFACE (ACIS katı) yalnız bütün
yüzleri düzlem ve bütün kenarları doğru olduğunda hesaplanır. Eğri yüzlü katının alanı (boru, yuvarlak
ayak) ACIS çekirdeği olmadan bulunamaz; o gövde hatasıyla döner, eksik alan sessizce verilmez."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from geometri import Ag, Kontur, Parca2D, cokgen_alani, vektor_alan, yerlestir, zincirle

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


def belge_ac(yol: str):
    """DXF'i açar; bozuk dosyada ezdxf'in onarıcı okuyucusuna geçer."""
    import ezdxf
    from ezdxf import recover
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

def _dongu_noktalari(loop, m) -> Optional[List[Tuple[float, float, float]]]:
    """Döngünün köşeleri; doğru olmayan kenar varsa None."""
    noktalar = []
    ilk = loop.coedge
    c = ilk
    adim = 0
    while not c.is_none:
        kenar = c.edge
        if kenar.is_none or kenar.curve.is_none or kenar.curve.type != "straight-curve":
            return None
        v = kenar.end_vertex if c.sense else kenar.start_vertex
        p = v.point.location
        if m is not None:
            p = m.transform(p)
        noktalar.append((p.x, p.y, p.z))
        c = c.next_coedge
        adim += 1
        if c is ilk:
            return noktalar
        if adim > 1_000_000:
            return None
    return None


def acis_govdeleri(e, ad: str, k: float, katman: str = "") -> List[Govde3D]:
    """ACIS varlığının her parçası (lump) bir gövde. Bütün yüzler düzlem ve kenarlar doğruysa alan kesin
    (delikli yüzlerde iç döngüler düşülür); değilse gövde hata ile döner."""
    from ezdxf.acis import api as acis
    try:
        bodies = acis.load_dxf(e)
    except Exception as hata:  # ezdxf bilinmeyen ACIS sürümünde çeşitli hatalar atar
        return [Govde3D(ad, e.dxftype(), katman, None, f"ACIS verisi okunamadı ({type(hata).__name__}).")]
    out: List[Govde3D] = []
    sira = 0
    for body in bodies:
        m = None if body.transform.is_none else body.transform.matrix
        lump = body.lump
        while not lump.is_none:
            sira += 1
            yuzler, toplam, egri, yuz_say = [], 0.0, 0, 0
            shell = lump.shell
            while not shell.is_none:
                face = shell.face
                while not face.is_none:
                    yuz_say += 1
                    if face.surface.type != "plane-surface":
                        egri += 1
                        face = face.next_face
                        continue
                    donguler, loop, bozuk = [], face.loop, False
                    while not loop.is_none:
                        d = _dongu_noktalari(loop, m)
                        if d is None:
                            bozuk = True
                            break
                        donguler.append([(x * k, y * k, z * k) for x, y, z in d])
                        loop = loop.next_loop
                    if bozuk or not donguler:
                        egri += 1
                    else:
                        alanlar = sorted((cokgen_alani(d) for d in donguler), reverse=True)
                        toplam += alanlar[0] - sum(alanlar[1:])
                        yuzler.extend(donguler)
                    face = face.next_face
                shell = shell.next_shell
            isim = ad if sira == 1 and lump.next_lump.is_none else f"{ad}.{sira}"
            if egri:
                out.append(Govde3D(isim, e.dxftype(), katman, Ag(yuzler) if yuzler else None,
                                   f"{yuz_say} yüzün {egri} tanesi eğri (silindir, koni, yay kenarı...). "
                                   "Eğri yüzlü katının alanı DXF'ten hesaplanamaz: çizimi STL olarak isteyin "
                                   "(AutoCAD: STLOUT komutu) ya da kalıptan ekleyin."))
            else:
                out.append(Govde3D(isim, e.dxftype(), katman, Ag(yuzler, alan_hazir=toplam)))
            lump = lump.next_lump
    if not out:
        out.append(Govde3D(ad, e.dxftype(), katman, None, "ACIS varlığında katı gövde yok."))
    return out
