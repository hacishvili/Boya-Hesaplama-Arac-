# Toz Boya Hesabı

Mobilya, ev aksesuarı ve koltuk ayağı gibi parçalar için toz boya hesabı yapan bir Windows masaüstü programı.
DXF, DWG ya da STL çizimden **boyanacak alanı**, bu alandan **toz sarfiyatını** ve **maliyeti** hesaplar.
Sipariş listesi olarak çalışır: birden çok parça, adet ve toz/renk girilir. Toplamlar toz bazında çıkar,
böylece satın alma için kaç kg toz gerektiği görülür. Sonuç Excel (CSV) ve PDF olarak alınır.

## Kurulum (kaynak koddan)

1. Python 3.12 veya üstü, 64 bit (python.org; kurarken "Add python.exe to PATH" işaretli olmalı).
2. `KURULUM.cmd`: PySide6 ve ezdxf'i kurar.
3. `TEST_ALL.cmd`: bütün testler BAŞARILI olmalı.
4. Programı açmak için: `CALISTIR.cmd` (ya da DXF/STL dosyalarını `CALISTIR.cmd`'nin üstüne sürükleyin).

**Python gerektirmeyen paket:** `PAKETLE.cmd` çalıştırılınca `dist/TozBoyaHesap/TozBoyaHesap.exe` ve
`dist/TozBoyaHesap_<sürüm>.zip` oluşur. GitHub Actions her gönderide testleri çalıştırır ve paketi de üretir
(Actions → ilgili çalıştırma → Artifacts → `TozBoyaHesap-windows`).

## Kullanım

- **Çizim ekle (DXF / DWG / STL):** dosyadaki parçaları listeler. Çizim birimini, katmanları ve eklenecek
  parçaları siz seçersiniz. Dosyaları pencereye sürükleyip bırakmak da yeterlidir.
  - **2D açınımlar:** iki yüz ve kesim kenarları (çevre × kalınlık) boyanır. Sac kalınlığı çizimden okunur:
    yazıdaki "t=2", "S: 1,5", "kalınlık 2 mm", "2 mm DKP"; katman adındaki "2MM", "T1.5" (o katmanın parçaları);
    dosya adındaki "..._2mm". Bulunamazsa girilir. Her parçaya ayrı da girilebilir (tablodaki "Sac kalınlığı"
    sütunu; üstteki kutu hepsine birden uygular).
  - **3D saclar:** kalınlık modelden bulunur (paralel iki büyük yüzün arası); iki yüz ve kesim kenarları (delik
    duvarları dahil) ayrı gösterilir, hepsi boyanır. Yüzey modeli (sacın tek yüzü) iki yüz sayılır.
  - **Aynı parçalar:** alanı ve ölçüleri aynı olan kopyalar tek kalemde toplanır, adet kopya sayısı olur
    (istenirse kapatılır).
  - **DWG:** ücretsiz [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter) kurulu
    olmalıdır. Program onu `Program Files\ODA` altında kendisi bulur; başka yerdeyse Ayarlar'da gösterilir.
    Kurulu değilse çizimi AutoCAD'de DXF olarak kaydetmek de yeterlidir.
- **Kalıptan ekle:** yuvarlak boru, kutu profil, konik ayak, dolu çubuk, lama ve sac levha. Çizimden alan
  çıkmayan parçalar (teknik resim, boru ayaklar) için kullanılır.
- **Elle alan:** alanı bilinen parçalar için doğrudan m² girilir.
- **Ayrıntı paneli:** her parçanın adedi, maskesi (boyanmayan alan, cm²), tozu (teorik yöntemde film kalınlığı).
  Birden çok kalem seçilince (Ctrl / Shift) toz hepsine birden atanır.
- **Ayarlar ve tozlar:** hesap yöntemi (pratik / teorik), m² başına proses ücreti, para birimi, DWG için ODA
  dönüştürücüsünün yolu ve toz kütüphanesi (sarfiyat m²/kg, fiyat; teorik yöntem için yoğunluk, kalınlık). Bu ayarlar `%APPDATA%\TozBoyaHesap\ayarlar.json` dosyasında saklanır.
- **Proje dosyası:** `.tozboya`. Hesap için gereken her şey bu dosyanın içindedir; çizim dosyası taşınsa da
  proje açılır.

## Hesap

Varsayılan yöntem **pratik sarfiyattır**: atölyede ölçülen oran (1 kg tozla 6 m²; fire ve kayıplar içinde).
Oran her toz için Ayarlar ve tozlar penceresinde değiştirilebilir (ör. metalik toz daha az alan verir).

```
toz (kg) = alan (m²) ÷ sarfiyat (m²/kg)                       1 kg = 6 m²
tutar    = toz (kg) × toz fiyatı  +  alan (m²) × proses ücreti
```

Örnek: 0,25 m²'lik ayak, 400 adet: 100 m² → 16,7 kg toz (adet başına 41,7 g).

İstenirse ayarlardan **teorik** yönteme geçilir; o zaman film kalınlığı, yoğunluk ve transfer verimi kullanılır:

```
toz (kg)               = alan (m²) × kalınlık (µm) × yoğunluk (g/cm³) / 1000 / transfer verimi
teorik kaplama (m²/kg) = 1000 / (yoğunluk × kalınlık)
```

## Alan nasıl bulunur

**2D DXF (sac açınımı, lazer kesim çizimi).** Kapalı konturlar bulunur; iç içe olanlar parça ve delik
olarak ayrılır (deliğin içindeki ada ayrı parça sayılır). Kontur şu öğelerden oluşabilir:

- daire, elips, spline, yaylı polyline gibi kapalı öğeler;
- uç uca eklenmiş çizgi ve yaylar.

Hesap:

```
bir yüz = dış kontur − delikler
alan    = yüz sayısı × bir yüz  +  (dış çevre + delik çevreleri) × sac kalınlığı   (kenarlar boyanıyorsa)
```

Alana girmeyen öğeler:

- **Kesikli çizgiler** (eksen, gizli çizgi, büküm çizgisi). İsterseniz içe aktarırken bunları da aldırabilirsiniz.
- **Ölçü, yazı ve tarama.**
- **Kontur kapatmayan çizgiler.** Kaç tane olduğu uyarıda yazar.

Daireler tam formülle (πr²) hesaplanır. Yaylar en çok 0,0005 mm sehimle çokgene çevrilir.

**3D DXF.**

- **3DFACE, POLYFACE ve MESH:** alan tam hesaplanır.
- **Birden çok gövde:** dosyada birden fazla gövde varsa her biri ayrı parça olarak listelenir.
- **Açık yüzey modeli:** sacın tek yüzü çizilmişse iki yüz sayılır (sınırı uzun açık yüzey; küçük açıklıklı
  gövde değil).
- **AutoCAD katıları (3DSOLID, metin ya da ikili ACIS):** yüzeyin türüne göre:
  - **düzlem, silindir, koni, küre, torus (boru dirseği):** kesin formülle;
  - **spline (NURBS):** loft yapılmış konik / oval ayak gibi kırpılmamış yüzeyler sayısal integralle.

  Kırpılmış spline yüzler ve desteklenmeyen yüzey türleri hesaplanmaz. Program böyle bir gövdeye eksik alan
  vermez; gövde hata ile listelenir. O zaman çizimi STL olarak isteyin (AutoCAD'de `STLOUT`) ya da parçayı
  kalıptan ekleyin.

**Profiller (3D katı).** Boyu kesitinin en az 2,5 katı olan katılarda yüzeyler otomatik ayrılır:
- **dış yüzey:** ortadaki kesitin dış konturundaki yüzler;
- **iç yüzey:** boşluğun duvarları (kesitin içteki konturu);
- **uç kesitleri:** düz ya da gönyeli kesimler.

Varsayılan boyama: dış yüzey ve uç kesitleri tam; iç yüzey her uçtan boşluk ölçüsü kadar derinliğe (kalıplardaki
"açık uç" gibi). Ayrıntı panelinde iç yüzey "tamamı" ya da "boyanmaz" seçilebilir, derinlik ve uç kesitleri
değiştirilebilir. Plaka, dirsek gibi profil olmayan katıların bütün yüzeyi boyanmış sayılır.

**STL.** STL'de üçgen alanları toplanır. Dosyada birim yazmaz; mm sayılır ve içe aktarırken değiştirilebilir.
Eğri yüzeyler üçgenlerle yaklaşık temsil edildiği için alan gerçek yüzeyden çok az küçük çıkar.

**Birim.** DXF'teki `$INSUNITS` değeri okunur; birim yazmıyorsa mm sayılır. En büyük parça 5 m'den büyük ya da
2 mm'den küçük çıkarsa program birimin yanlış olabileceği uyarısını verir.

**Kalıplarda uçlar.**

- **açık:** uç halkaları boyanır, ayrıca toz her uçtan "iç boya derinliği" kadar içeri girer (varsayılan bir çap).
- **kapaklı:** kaynaklı kapakların dış yüzü boyanır.
- **tapalı:** uçlar ve iç boyanmaz.

**Dikkat.** STL ve yüzey (mesh) modellerinde iç yüzey ayrılmaz; borunun içi boyanmıyorsa o kısmı maskeye yazın.

## Dosyalar

| Dosya | İçerik |
|---|---|
| `geometri.py` | kontur alanı / çevresi, iç içe yerleşim, çizgi zincirleme, 3D ağ alanı ve gövdeler |
| `dxf_oku.py` | DXF / DWG: birim, katman, kesikli çizgi, bloklar, 2D konturlar, 3D ağlar, ACIS katılar |
| `profil.py` | profil katılarda dış / iç / uç yüzeylerin tanınması, iç yüzeyin uçlardan boyanan kısmı |
| `acis_alan.py` | ACIS (SAT / SAB) katı gövdelerin yüzey alanı: düzlem, silindir, koni, küre, torus, spline |
| `stl_oku.py` | ikili ve metin STL |
| `kaliplar.py` | boru, profil, konik ayak, çubuk, lama, sac formülleri |
| `hesap.py` | toz, kalem, ayarlar, özet |
| `proje.py`, `rapor.py` | `.tozboya` proje dosyası, ayarlar, CSV ve PDF raporun içeriği |
| `pencere.py`, `TozBoya.py` | arayüz ve başlatıcı (`--self-test`: paketin kendi denemesi) |
| `test_*.py` | testler: her alan formülle bağımsız olarak karşılaştırılır |

## Lisans

MIT lisansı, © 2026 Enes Özbek (`LICENSE`). Program ücretsizdir: herkes kullanabilir, değiştirebilir ve
paylaşabilir; tek koşul, kopyalarda lisans metninin kalmasıdır. Kullanılan açık kaynak bileşenler (Qt / PySide6:
LGPL-3.0, ezdxf: MIT ve diğerleri) kendi lisanslarıyla dağıtılır: `UCUNCU_TARAF_LISANSLARI.txt` ve
`ucuncu_taraf_lisanslari/`. Windows paketi bu dosyaları exe'nin yanına koyar.
