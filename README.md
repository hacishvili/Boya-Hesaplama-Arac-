# Toz Boya Hesabı

Mobilya, ev aksesuarı ve koltuk ayağı gibi parçalar için toz boya hesabı yapan bir Windows masaüstü programı.
DXF ya da STL çizimden **boyanacak alanı**, bu alandan **toz sarfiyatını** ve **maliyeti** hesaplar.
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

- **Çizim ekle (DXF / STL):** dosyadaki parçaları listeler. Çizim birimini, katmanları ve eklenecek parçaları
  siz seçersiniz. 2D açınımlarda sac kalınlığı, boyanan yüz (iki yüz / tek yüz) ve kesim kenarlarının boyanıp
  boyanmadığı da girilir. Dosyaları pencereye sürükleyip bırakmak da yeterlidir.
- **Kalıptan ekle:** yuvarlak boru, kutu profil, konik ayak, dolu çubuk, lama ve sac levha. Çizimden alan
  çıkmayan parçalar (teknik resim, boru ayaklar) için kullanılır.
- **Elle alan:** alanı bilinen parçalar için doğrudan m² girilir.
- **Ayrıntı paneli:** her parçanın adedi, maskesi (boyanmayan alan, cm²), tozu ve film kalınlığı.
- **Ayarlar ve tozlar:** transfer verimi, m² başına proses ücreti, para birimi ve toz kütüphanesi (yoğunluk,
  fiyat, varsayılan kalınlık). Bu ayarlar `%APPDATA%\TozBoyaHesap\ayarlar.json` dosyasında saklanır.
- **Proje dosyası:** `.tozboya`. Hesap için gereken her şey bu dosyanın içindedir; çizim dosyası taşınsa da
  proje açılır.

## Hesap

```
toz (kg)              = alan (m²) × kalınlık (µm) × yoğunluk (g/cm³) / 1000 / transfer verimi
teorik kaplama (m²/kg) = 1000 / (yoğunluk × kalınlık)
tutar                 = toz (kg) × toz fiyatı  +  alan (m²) × proses ücreti
```

Örnek: 0,25 m²'lik bir ayak, 70 µm kalınlık, 1,5 g/cm³ yoğunluk ve %65 verimle adet başına 40,4 g toz harcar.

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
- **Açık yüzey modeli:** sacın tek yüzü çizilmişse program bunu belirtir; ayrıntı panelinden "iki yüz" seçilir.
- **AutoCAD katıları (3DSOLID):** bütün yüzleri düz ve bütün kenarları doğru olan katıların alanı tam hesaplanır (köşeli delikler dahil).
  Eğri yüzü (silindir, koni, yuvarlatma) olan katılar ise ACIS çekirdeği olmadan ölçülemez. Program böyle bir
  gövdeye eksik alan vermez; gövde hata ile listelenir. Çözüm için çizimi STL olarak isteyin (AutoCAD'de
  `STLOUT` komutu) ya da parçayı kalıptan ekleyin.

**STL.** STL'de üçgen alanları toplanır. Dosyada birim yazmaz; mm sayılır ve içe aktarırken değiştirilebilir.
Eğri yüzeyler üçgenlerle yaklaşık temsil edildiği için alan gerçek yüzeyden çok az küçük çıkar.

**Birim.** DXF'teki `$INSUNITS` değeri okunur; birim yazmıyorsa mm sayılır. En büyük parça 5 m'den büyük ya da
2 mm'den küçük çıkarsa program birimin yanlış olabileceği uyarısını verir.

**Kalıplarda uçlar.**

- **açık:** uç halkaları boyanır, ayrıca toz her uçtan "iç boya derinliği" kadar içeri girer (varsayılan bir çap).
- **kapaklı:** kaynaklı kapakların dış yüzü boyanır.
- **tapalı:** uçlar ve iç boyanmaz.

**Dikkat.** 3D modelde borunun iç yüzeyi de alana girer. İçi boyanmıyorsa o kısmı maskeye yazın.

## Dosyalar

| Dosya | İçerik |
|---|---|
| `geometri.py` | kontur alanı / çevresi, iç içe yerleşim, çizgi zincirleme, 3D ağ alanı ve gövdeler |
| `dxf_oku.py` | DXF: birim, katman, kesikli çizgi, bloklar, 2D konturlar, 3D ağlar, ACIS katılar |
| `stl_oku.py` | ikili ve metin STL |
| `kaliplar.py` | boru, profil, konik ayak, çubuk, lama, sac formülleri |
| `hesap.py` | toz, kalem, ayarlar, özet |
| `proje.py`, `rapor.py` | `.tozboya` proje dosyası, ayarlar, CSV ve PDF raporun içeriği |
| `pencere.py`, `TozBoya.py` | arayüz ve başlatıcı (`--self-test`: paketin kendi denemesi) |
| `test_*.py` | testler: her alan formülle bağımsız olarak karşılaştırılır |
