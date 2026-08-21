# CLAUDE.md — Instagram Haber Botu

Bu dosya projeyi devralan Claude Code oturumu içindir. Konuşma geçmişi yok,
ihtiyacın olan her şey burada.

---

## 1. Kullanıcı profili — ÖNCE BUNU OKU

- **Adı:** Doğukan. Türkçe konuşuyor, Türkçe cevap ver.
- **Seviyesi:** SQL'e hakim. **Python'a hakim DEĞİL.**
- **Çalışma şekli — bunlara uy:**
  - Kodu sen yaz, o çalıştırsın. "Şunu sen ekle" deme.
  - **Küçük parçalar halinde ilerle. Bir adım çalıştığı doğrulanmadan
    diğerine geçme.** Bu onun açık isteği.
  - Her adımı açıkla. Neden yaptığını da söyle, sadece ne yaptığını değil.
  - Kod içi yorumlar ve değişken/fonksiyon adları **Türkçe** (mevcut kod böyle,
    tutarlılığı bozma).
  - Uzun teknik anlatım yerine somut örnek ve benzetme daha iyi çalışıyor.
  - Bir karar noktasında varsayım yapma, sor. Ama seçenekleri ve
    tavsiyeni birlikte sun.
- **Bir şeyin gizli maliyeti/riski varsa açıkça söyle.** "Bilmediğim bir eksisi
  yok dimi" diye soruyor — dürüst ve eksiksiz cevap bekliyor.

---

## 2. Proje amacı

Günde 2 kez (sabah/akşam) otomatik Instagram haber postu:

```
RSS → en önemli haberi seç → Gemini ile TR başlık+caption+hashtag
    → 1080x1080 görsel → imgbb'ye yükle → Telegram'dan ONAY sor
    → onaylanınca Instagram Graph API ile yayınla
```

Sunucu ücreti ödemek istemiyor. Sürekli açık bir cihaz da istemiyor.

---

## 3. Kesinleşmiş kararlar — YENİDEN TARTIŞMA

Bunların hepsi kullanıcıyla konuşuldu ve karara bağlandı.

| Konu | Karar |
|---|---|
| Çalışma ortamı | **GitHub Actions, private repo** (telefon/Termux fikri elendi) |
| LLM | **Google Gemini** (ücretsiz kota, kredi kartı istemiyor) |
| Onay kanalı | **Telegram bot**, inline butonlarla → **"Daily Brief" GRUBUNA** (özel sohbete değil) |
| Onay yetkisi | **Gruptaki herkes** onaylayabilir/atlayabilir. Kullanıcı bilerek böyle istedi; kimin bastığını kontrol eden bir kısıt YOK. |
| Onay tetikleme | **Cloudflare Worker** → `repository_dispatch` → anında yayın |
| Görsel hosting | **imgbb** (Instagram public URL zorunlu kılıyor) |
| Haber teması | Öncelik **Türkiye gündemi**; dünya haberi sadece önem puanı ≥8 ise |
| Post biçimi | **CAROUSEL** (kaydırmalı). **Kapak YOK, 10 haber** = 10 slayt. Instagram sınırı 10. |
| ~~Kapak slaytı~~ | **DENENDİ VE ELENDİ (15 Ağu 2026).** Kapak+9 haber düzeni üretilip gösterildi; kullanıcı 10 haberi tercih etti. `kapak_ciz`/`kapak_uret` kodu `make_image.py`'de DURUYOR — fikir değişirse `kapak_var: true` yeterli, yeniden yazma. |
| Slayt oranı | **4:5 dikey (1080x1350)**. Carousel'de tüm slaytlar aynı oranda olmak zorunda. |
| Güvenli alan | `dikey_guvenli_pay: 150`. Feed'de 4:5 tam görünüyor; risk profil ızgarasının kareye kırpması (üst/alt 135px). Instagram ızgarayı 2025'te dikey yaptı ama bayrak ve kaynak satırı tam sınırdaydı, içeri alındı. |
| Post sıklığı | **Günde 2 tur (TR 08:07 + 20:07) + en fazla 10 tekil post** (`son_dakika_gunluk_azami: 10`) = günde en çok 12 post. 19 Ağu 2026'da tek tur + 2 tekil'den çıkıldı; havuzda yayınlanmayı bekleyen 100+ haber birikiyordu. |
| ★ Kategori bazlı tekil post eşiği | ⚠️ **TEK EŞİK SPOR VE EKONOMİYİ TAMAMEN DIŞLIYORDU.** Ölçüldü (son 3 gün): ekonomide 8+ puan alan haber **sıfır** (en yükseği 7), sporda **sıfır** (en yükseği 7). Eşik 8 iken o kategorilerden tekil post çıkması matematiksel olarak imkânsızdı. Önem puanı kategoriye göre farklı dağılıyor — "ülke gündemi" haberleri doğaları gereği yüksek alıyor. Çözüm `son_dakika_kategori_esikleri`: turkiye/dunya 8, diğerleri 7; gece hepsine +1. Ayrıca `son_dakika_kategori_azami: 3` — tek kategori günü domine etmesin, yoksa bütün tekil postlar yine "turkiye"den çıkardı. |
| ★ Actions GERÇEK harcama (20 Ağu 2026) | ⚠️ **"%88" bir TAHMİNDİ, harcama değil.** 1 Ağustos'tan 20 Ağustos'a gerçek harcama **616 dk / 3000 (%21)**. Ama 616'nın **615'i son 7 günde** oldu (proje 14 Ağu'da yoğunlaştı), yani güncel hız **88 dk/gün** → tam ay 2640 dk (%88). Ağustos rahat biter (~1584 dk); risk Eylül'dü. ⚠️ Ölçerken **7 günlük hızı aylığa çevirmek** ile **ay başından beri harcananı okumak** iki farklı sorudur; ikisini karıştırma. |
| ★ Kontrol sıklığı 90 dakikaya çekildi (20 Ağu 2026) | Gündüz `5 4,7,10,13,16,19` + `35 5,8,11,14,17` (11 çalışma), gece `5 20,23,2` (3 çalışma) = **günde 14** (önceden 36). Eylül tahmini **2640 → 2038 dk (%68)**. ⚠️ 90 dakika **tek cron satırıyla yazılamıyor** — dakika kayıyor (05, 35, 05…), tam saatler ve buçuklar ayrı satırda; birini değiştirirken diğerini de değiştir. |
| ⚠️ Faturalamanın %35'i YUVARLAMA KAYBI | GitHub her job'ı **dakikaya yukarı yuvarlıyor**. Ölçüldü (25 kontrol çalışması): 27,4 dakikalık gerçek iş **42 dakika** faturalandı. 61-102 saniye süren 9 çalışma tam 2 dakika yazıldı; 60 saniyenin altına inseler yarısını öderdik. Sabit yük zaten minimal (checkout+pip **9 sn**, pip önbelleği çalışıyor) — süre asıl adımda geçiyor. |
| ⚠️ GitHub cron'ları ATLIYOR | Ölçüldü (20 Ağu 2026): `5,35` yani 30 dakikalık cron gerçekte **ortalama 56 dakika** aralıkla çalıştı (9, 23, 47, 51, 58, 79, 98… dakika). Cron'da yazan süre bir **taban**, garanti değil. Zamanlanmış yayın penceresi bu yüzden cron aralığından geniş söyleniyor. |
| ⚠️ Kontrol job'ı Actions'ın en büyük kalemi | Son dakika kontrolünün ana adımı **26 sn ile 540 sn** arasında değişiyor; uzun olanlar aday bulunamayınca metin ürettiği çalışmalar. Günde ~20 kez koştuğu için aylık ~1518 dk — Pro kotasının yarısı. `son_dakika_ek_metin_adedi` 5'ten **3**'e indirildi; güvenli, çünkü artık günde 2 tur ~50 adaya metin üretiyor ve havuzda sürekli 100+ hazır metin duruyor. |
| ⚠️ Actions ölçümü — KUYRUK SÜRESİNİ SAYMA | Run seviyesindeki `run_started_at → updated_at` farkı **kuyrukta bekleme süresini de içeriyor** ve GitHub onu faturalandırmıyor. `veritabani` concurrency grubu joblari sıraya soktuğu için bu fark büyük. Doğru ölçüm **job seviyesinden**: `/runs/{id}/jobs` → her job'ın `started_at → completed_at` farkı. (`/timing` uç noktası bu repoda `total_ms: 0` dönüyor, kullanma.) |
| ⚠️ Gerçek Actions kullanımı (19 Ağu 2026) | Job seviyesinde ölçüldü: son dakika kontrolü **2.81 dk** (günde ~18 → ~1518 dk/ay, kotanın yarısı), tur **8.31 dk**, onay işleme **1.77 dk**, hatırlatma 0.18 dk. Toplam **~3022 dk/ay** ve Pro kotası 3000 — **TAM SINIRDA**. Hesap 17-18 Ağu verisine dayanıyor ve o günler arıza ayıklamasıyla şişkindi; sakin günde ~50 dk/gün görülüyor. Yine de en büyük kalem son dakika kontrolü ve çoğu "haber yok" deyip çıkıyor. |
| Plan | **GitHub Pro** (19 Ağu 2026'da yükseltildi) — Actions kotası 2000 → **3000 dk/ay**. |
| ★ Neden iki tur (19 Ağu 2026) | Kullanıcı başka bir hesabın geniş haber yelpazesini gösterip "bu haberleri biz görüyor muyuz" diye sordu. ÖLÇÜLDÜ: o hesabın 12 haberinin **10'u zaten havuzumuzdaydı** — sorun kaynak değil, KAPASİTE. Havuzda 1497 haber var, tek tur 25'ine metin üretip 10'unu yayınlıyordu (%0.7). Gece/sabah çıkan 346 haber akşama kadar bekleyip bayat halde yarışıyordu. Instagram carousel sınırı 10 (API dokümanından doğrulandı) olduğu için tek turda daha fazla slayt vermek MÜMKÜN DEĞİL; kapasiteyi artırmanın tek yolu tur sayısı. Maliyet ölçüldü: Gemini ~$3.25/ay, Actions 1584/2000 dk. 3 tur denenmedi — Actions kotasının %91'ini yiyordu. |
| ★ Ön eleme İKİ KATMANLI (19 Ağu 2026) | Haberler önce **kendi kategorisinde** yarışıyor (kaynak ağırlığı + tazelik + içerik sinyali), sonra kategori katsayısıyla ağırlıklandırılıyor (`config → secim.kategori_katsayilari`). Kota DEĞİL: tavan koymuyor, yalnızca kategoriler arası göreli öncelik veriyor. Ölçüldü: kategori çeşidi **2→5**, kaynak çeşidi **3→9** (öncesi turkiye 17 + ekonomi 8, tek listede 3 kaynak). |
| ⚠️ Sıra cezası kategori büyüklüğünden BAĞIMSIZ olmalı | İlk denemede kategori içi sıra, kategorideki haber sayısına bölünerek normalize edildi ve sonuç **yine %100 turkiye** çıktı: 592 haberlik kategoride 25. sıra 0.96 alırken 35 haberlik sporda 2. sıra 0.97'ye düşüyordu — büyük kategori otomatik avantajlı hale geliyordu. Doğrusu üstel ve sabit azalma (`kategori_sira_azalmasi: 0.88`). |
| ★ İçerik sinyali (bedava) | `_icerik_puani` başlığa bakıyor: rakam +8, olay fiili (tutuklandı/keşfetti/yangın/rekor) +12, açıklama kalıbı (değerlendirdi/kınadı/mesaj) −10. LLM YOK. Ön elemede `onem_puani` henüz üretilmemiş olduğu için bu kaba sinyal o boşluğu dolduruyor. Ölçüldü: "Dışişleri Bakanlığından Dünya İnsani Günü mesajı" geriledi, kazalar/operasyonlar öne çıktı. |
| Son dakika (16 Ağu 2026) | Gün içi tekil post, **2 slayt**: 1'inci dikkat çeker (fotoğraf+başlık+özet), 2'nci anlatır (sade zemin + 60-80 kelime detay). Günde en fazla 2. **Gündüz** (TR 07-23): saat başı, eşik 8, onay ömrü 1 saat. **Gece** (TR 23-07): 2 saatte bir, eşik **9**, onay sabah 08:00'e kadar. Gece neden farklı: onaylayacak kimse uyanık değil, 1 saatlik ömür orada anlamsız; ama sabaha kalan post 5-8 saatlik bir haber oluyor ve bu gecikmeyi ancak büyük bir olay hak ediyor. Detay slaytında **bilerek fotoğraf yok** — metin ağırlıklı olduğu için fotoğraf üstünde okunmuyor, perde koyulaştıkça zaten görünmez oluyor. |
| Gece otomatik yayın (17 Ağu 2026) | Gece (TR 23-07) **dört katmanlı denetimden geçen** haber insan onayı olmadan yayınlanıyor (`src/otomatik_onay.py`). ŞÜPHEDE REDDET: biri bile tereddüt ederse sabaha bırakılır. Yayınlanınca Telegram'a hangi katmanlardan geçtiği yazılıyor — beğenilmezse Instagram'dan silinebilir. `config.yaml → gece_otomatik_yayin: false` ile kapatılır. |
| Dört katman | **1** deterministik (sayı/isim/başlık/suçlama dili) · **2** kaynak güveni · **3** LLM çapraz denetim · **4** riskli kategori. Sıra ucuzdan pahalıya: LLM çağrısı en sonda, ilk üçten biri reddederse kota harcanmıyor. |
| ⚠️ Katman 2 neden gevşetildi | İlk hâli "ikinci kaynak da doğrulasın" istiyordu ve **8/8 haberi reddediyordu**. Ölçüldü: aynı olayı iki kaynağın AYNI ŞEKİLDE vermesi nadir — 136 haberlik havuzda tek eşleşme yok, her kaynak farklı açı seçiyor. Çözüm: `agirlik >= 9` olan kaynaklar (TRT, BBC Türkçe, AA) tek başına yeterli sayılıyor. |
| ⚠️ Katman 4 neden gevşetildi | İlk hâli "ölüm/saldırı geçen haberi reddet" diyordu — ama gece otomatik yayının yakalamak istediği büyük olaylar tam da bu kategorideydi, özellik kendi amacını baltalıyordu. Yeni kural: riskli konu tek başına ret sebebi DEĞİL; ret sebebi **riskli konuda sayıyı kesin dille vermek**. "47 kişi öldü" reddedilir, "en az 47 kişi" geçer. Prompt da artık "en az" yazdırıyor. |
| Son dakika sayfa sayısı | **Sabit değil.** Detay metni uzunsa sayfa ekleniyor: 1 haber + 1-4 ayrıntı sayfası. Punto SABİT 40 (sayfa başına ~75 kelime, ölçüldü); puntoyu küçültmek yerine sayfa eklemek tercih edildi — 28 puntoya inen slayt telefonda okunmuyor ve carousel'de zaten 10 slayt hakkı var. Sağ altta `2/3` göstergesi. |
| `detay_metni` | Gemini'nin ürettiği 120-220 kelimelik ayrıntılı anlatım, `ig_caption`'dan AYRI. **PARAGRAFLAR hâlinde** (3-5 paragraf, her biri 20-32 kelime, `\n\n` ile ayrık). İlk paragraf en çarpıcı bilgiyi taşır — gazetedeki "spot" mantığı. |
| Vurgu öğeleri (17 Ağu 2026) | Detay sayfalarında iki görsel çapa: **iri amber rakam** (`vurgu_sayi` + `vurgu_etiket`, sayfanın en üstünde, punto metne göre 92'den 46'ya otomatik iniyor) ve **alıntı bloğu** (`alinti` + `alinti_sahibi`, sol kenarda amber dikey çizgi). İkisi de opsiyonel — haberde yoksa Gemini boş bırakıyor, zorlama yok. |
| ⚠️ Alıntı doğrulaması | **Alıntı kaynakta birebir doğrulanmadan BASILMIYOR** (`dogrula.alintiyi_denetle`). Birinin ağzına söylemediği sözü koymak, yanlış sayı yazmaktan çok daha ağır bir hata — sayı düzeltilir, uydurma alıntı itibar meselesi. Kelimelerin %85'i kaynakta ardışık bir pencerede geçmeli; geçmezse alıntı sessizce atılıyor, slayt onsuz basılıyor. |
| Detay sayfası düzeni | Tek blok düz metin **tekdüze ve okunmuyordu**. Şimdi: giriş paragrafı 46 punto + beyaz (göz oraya takılsın), sonrakiler 37 punto + soluk gri, aralarında 24px nefes payı. Sayfa başına 2-3 paragraf. Paragraf ortasından bölünmüyor — sığmayan paragraf sonraki sayfaya iniyor. |
| ⚠️ Paragraf uzunluğu neden kısa | İlk denemede 25-45 kelime istendi; model 45'e yakın yazınca **her paragraf tek başına bir sayfayı dolduruyordu** ve düzen yine tekdüze oluyordu. 20-32 kelimeye çekildi, puntolar da dengelendi (spot 50→46, normal 40→37). |
| ⚠️ `detay_url` biçimi | **JSON listesi** (`["url1","url2"]`) — birden fazla ayrıntı sayfası olabildiği için. Eski kayıtlarda tek düz URL var; `onay_isle._detay_urlleri()` ikisini de kabul ediyor. |
| "SON DAKİKA" etiketi | Yalnızca `onem_puani >= 9`'da basılıyor (`son_dakika_etiket_esigi`). Tetikleme eşiği 8 ama etiket 9+: her önemli habere "son dakika" demek ibareyi değersizleştiriyor. Etiket yalnızca İLK ayrıntı sayfasında. |
| Son dakika onayı | **Onay ŞART ama 1 saatte onaylanmazsa kendiliğinden iptal.** Bayat bir "son dakika" postu atmak hiç atmamaktan kötü. Onaylanmayan haber ELENMEZ, akşam turunda normal haber olarak yeniden yarışır. Otomatik yayın bilerek REDDEDİLDİ: son dakika haberleri en çok düzeltilen haberler, kaynak 20 dk sonra sayıyı değiştiriyor. |
| Akşam turu | 20:00 hazırla → 21:00, 22:00 hatırlat → 23:00 havuza dön |
| Slayt görseli | **4 katman, sırayla:** haberin kendi `og:image`'ı → Commons (**yalnızca KİŞİ**) → Pexels (temsili) → gradyan. **Normal turda AI HİÇ çağrılmıyor, görsel maliyeti $0.** |
| ⚠️ Haber görseli (18 Ağu 2026) | Haberin kendi fotoğrafı artık EN ÜST katman (`fetch_article.og_gorseli_cek`). **TELİF RİSKİ TAŞIYOR** — ajans fotoğrafı olabiliyor, kaynak belirtmek izin yerine geçmiyor, Instagram şikayette postu kaldırır. Kullanıcı riski bilerek seçti; daha önce "kullanılmayacak" denmişti, karar 18 Ağu'da değişti. `og:image` seçilmesinin sebebi: sitenin sosyal medyada paylaşılsın diye koyduğu görsel bu. `gorsel.haber_gorseli_kullan: false` ile kapanır. 600px altındakiler eleniyor (site logosu olabiliyor). |
| Haber çeşitliliği (18 Ağu 2026) | **İki kusur birlikte çözüldü.** (1) 8 kaynağın 6'sı Türkiye gündemiydi; bilim/teknoloji/spor/kültür/ekonomi kaynağı YOKTU, o konular seçime giremiyordu. 8 kaynak eklendi (AA ×4, NTV ×2, Habertürk ×2), 8/8 test edildi. (2) Seçim düz skor sıralamasıydı, aynı olayın haberleri üst üste diziliyordu — 16 Ağu turunda 10 haberin 6'sı İsrail/Gazze, 8'i tek kaynaktan. `secim.cesitlendir()`: aynı olaydan tek haber, kategori başına 3, kaynak başına 4. Ölçüldü: turkiye 8→4, tek kaynak 7→4, kategori çeşidi 3→7. **Kurallar turu eksik bırakmıyor**, havuz darsa gevşetiliyor. |
| ⚠️ Kaynak eklemeden ÖNCE ölç | `python scripts/kaynak_dogrula.py <url> <kategori>`. **Besleme adının kategoriyi doğru verdiğine GÜVENME.** TRT'nin "teknoloji" beslemesi 0/10 doğru kategori veriyordu (gündem 5, dünya 3) ve "Mustafa Bozbey CHP'den istifa etti" haberi slaytta **TRT TEKNOLOJİ** etiketiyle yayınlandı. Araç ayrıca tazeliği (TRT spor beslemesi 11 GÜN eskiydi) ve örtüşmeyi (Milliyet'in iki beslemesi birebir aynı) ölçüyor. |
| ⚠️ Kaynak sırası | **Kategori beslemeleri config'de ÖNCE.** `haberler.link` UNIQUE ve ilk gelen kaynak kazanıyor; genel akışlar (TRT sondakika, AA guncel) tüm kategorileri içerdiği için önce çekilirlerse ekonomi/bilim/kültür haberlerini "turkiye" etiketiyle kaydediyor ve kategori beslemeleri komple tekrar sayılıp eleniyor. Ölçüldü: 7 kaynaktan HİÇ haber girmemişti. |
| ⚠️ Magazin kaynağı YOK | Bilerek. İlgi çekiyor ama doğruluk riski yüksek ve dört katmanlı denetim dedikoduyu ayıklayamıyor. İstenirse `config.yaml → kaynaklar`'a eklenir. |
| Slayt düzeni (18 Ağu 2026) | Fotoğraf üstte NET, aşağı doğru `gorsel.perde_rengi`'ne dönüşüyor; **açıklama ve alt bilgi düz renk şeritte**, başlık FOTOĞRAFIN üstünde. Başlık okunmasını **gerçek bulanık gölgeden** alıyor (GaussianBlur) — eski 2px kaydırma açık/kalabalık fotoğrafta yetmiyordu. Başlık tavanı **72** (96→80→72; başlık fotoğrafı örttüğü için yer kaplaması artık doğrudan maliyet). |
| ⚠️ Kategori renkleri | `arkaplan_uret_yedek` her kategori için ayrı gradyan taşıyor. Yeni kategori eklerken **buraya da renk ekle**, yoksa sessizce "turkiye" rengine düşer. Tonlar bilerek yakın ve koyu: carousel kaydırılırken slaytlar farklı hesaptan gelmiş gibi durmasın. |
| ⚠️ Instagram medya hatası GEÇİCİ | `2207052` / `2207003` ("Only photo or video can be accepted" — mesaj yanıltıcı, Türkçesi doğruyu söylüyor: *medya indirme başarısız*). Instagram görseli imgbb'den KENDİSİ çekiyor ve o çekme patlıyor; görselde kusur yok. 18 Ağu'da bir tur 3 denemede geçemedi, 2 dakika sonra elle denendiğinde 5/5 sorunsuz yüklendi. `MEDYA_AZAMI_DENEME = 6` + **sabit** 15 sn bekleme (artan bekleme çözmüyor — Threads'te ölçüldü). ⚠️ `deneme_sayisi` config'de tanımlıydı ama kod onu HİÇ OKUMUYORDU, `range(1,4)` sabitti. |
| ⚠️ Instagram'da MÜZİK yok | Doğrulandı (18 Ağu 2026): `audio_name` parametresi var ama **yalnızca Reels için**. Foto ve carousel postlarına API'den müzik eklenemiyor; müzik kütüphanesi sadece resmi uygulamada. Müzikli haber hesapları postu ELLE paylaşıyor. Politika kısıtı, aşılamaz. |
| Commons kuralı | **`gorsel_konu`ya SADECE kişi adı yazılır, kurum/örgüt/şehir ASLA.** Ölçüldü: "İSKİ"→Macar sanatçı portresi, "Taliban"→askeri harita, "Ankara Büyükşehir"→kale manzarası. Bunlar yayınlanamaz. Kurumu Pexels temsil ediyor ve iyi çalışıyor. |
| Caption | Tek post, 10 haber → `src/caption.py`. Tarih + numaralı manşet listesi + kaynaklar + atıf + hashtag. Sınır 2200 karakter / 30 hashtag; aşarsa sırayla hashtag → atıf → son maddeler kırpılır. |
| Atıf politikası | Commons atıfları **tek tek** yazılır (CC BY hukuken şart). Pexels'ler **tek satırda** toplanır — lisansı atıf istemiyor, 9 ayrı satır 700 karakter yiyordu. |
| İçerik filtresi | Instagram shadowban'ine karşı `src/filtre.py`: riskli kelimeler yıldızlanır ("taciz"→"tac*z"), kısıtlı hashtag'ler **tamamen atılır** (etikette yıldız işe yaramaz). Liste `config.yaml`'de ve **bilerek kısa** — ölüm/kaza/cinayet gibi gündelik haber kelimeleri YOK, aşırı sansür amatör gösteriyor. |
| ~~Haber sitesi fotoğrafı kullanılmıyor~~ | **KARAR DEĞİŞTİ (18 Ağu 2026), artık KULLANILIYOR.** 15 Ağu'da telif riski anlatılıp vazgeçilmişti. Kullanıcı benzer hesapların bu görselleri rahatça kullandığını görüp yeniden istedi; risk ikinci kez anlatıldı ve karar kullanıcınındır. Ayrıntı: "⚠️ Haber görseli" satırı. Telif riski ortadan KALKMADI — yalnızca kabul edildi. |
| Beğenilmeyen görsel | Telegram'a **`🎨 Görseli AI ile üret`** butonu eklenecek. Varsayılan bedava katman; AI maliyeti ancak kullanıcı basarsa oluşuyor. |
| Slayt yazısı | Başlık + altında küçük puntoyla **tek cümlelik özet** (`slayt_ozet`). |
| ★ Önem puanı (18 Ağu 2026) | Prompt'un puan bandı örnekleri **yalnızca siyasiydi** ("9-10 = ülke gündemini belirleyen olay") ve model ölçeği ona kalibre ediyordu. Sonuç: "UltrAslan lideri uyuşturucu testi pozitif" 6, "James Webb 3 kara delik keşfetti" 6 alırken "Bakan X konuyu değerlendirdi" 7 alıyordu — tur resmi açıklamalarla doluyor, insanların okuduğu haberler 5-6 bandında bekliyordu. 7-8 bandına siyaset dışı çapalar yazıldı (bilim keşfi, sağlık uyarısı, büyük kaza, spor sonucu, tanınan ismin karıştığı olay) ve **açıklama/olay ayrımı** eklendi: "değerlendirdi/kınadı/temenni etti" 3-5, "karar alındı/yasa çıktı" yüksek. ⚠️ **ÖLÇÜLMEDİ** — Gemini kotası dolduğu için A/B testi yapılamadı, ilk fırsatta yapılmalı. |
| ★ Başlık kuralı | **Başlık haberin SONUCUNU söylemek zorunda.** Takipçiye link vermiyoruz, okuyacağı başka yer yok — slaytı kaydırıp geçen kişi haberi ÖĞRENMİŞ olmalı. "…ilişkin açıklama", "…değerlendirdi", "…anlattı" gibi 15 kalıp prompt'ta YASAK; `dogrula.basligi_denetle()` yakalayıp uyarıyor. Abartı ("şok", "bomba") da yasak — güveni düşürüyor. Ölçüldü: "Bakan Göktaş'tan taciz iddialarına ilişkin açıklama" → "…iddialarının vahim olduğunu belirtti". |
| `/haber <konu>` (20 Ağu 2026) | Telegram'a yazılan konu **havuzda aranıyor**, bulunanlar öneri olarak sunuluyor. ⚠️ **Kullanıcının yazdığı metinden post ÜRETİLMİYOR** — projenin en temel kuralı "yalnızca kaynak metinde yazanı kullan"; tek cümlelik istekten haber metni üretmek tam da onun yasakladığı şey, üstelik çıktı gerçek haber gibi görüneceği için en tehlikeli biçimde. Seçilen haberin metni her zaman kendi kaynağından üretiliyor. Arama skoru başlıkta geçmeye 10, özette geçmeye 2 puan veriyor; hiçbir kelimesi başlıkta geçmeyenler eleniyor (ölçüldü: bu eşik olmadan "asgari ücret" araması üç alakasız haber döndürüyordu). |
| Telegram komutları | `/durum` · `/tur` · `/ayar` · `/tamamla` · `/arsiv` · `/yardim`. Buton menüsü yalnızca açık onay mesajı varken işe yarıyordu; tur kapanınca elde tutamak kalmıyordu. `/yardim` Worker'da anında cevaplanıyor. |
| Ayar paneli (18 Ağu 2026) | `/ayar` → çalışma ayarları Telegram'dan değiştirilebiliyor (`src/ayar.py`). **İki katman:** `config.yaml` varsayılan, `ayarlar` tablosu üste biner — DB her job sonunda commit edildiği için değişiklik kalıcı. ⚠️ **BEYAZ LİSTE ZORUNLU** (`DEGISTIRILEBILIR`, 6 anahtar): gruba herkes yazabildiği için keyfi anahtar kabul etmek botu grup üzerinden yönetilebilir kılardı. Alt menü Worker'da açılıyor ama seçenekler **düğmeye gömülü** (`ayarmenu:yol:true-false`) — menü üçüncü bir yerde tekrarlanmasın diye. |
| Haber dışa aktarımı | `scripts/haber_disa_aktar.py` → `data/disa-aktarim/haberler-TARİH.xlsx`. Kategori kategori ayrı sayfa + ÖZET sayfası. **SENİN PUANIN** ve **Notun** sütunları boş ve sarı: kullanıcı doldurup geri gönderiyor, Gemini'nin kalibrasyonu insan yargısıyla karşılaştırılabiliyor. `--gun N` / `--tumu`. |
| ★ Tekil post ÇOKLU SEÇİM (20 Ağu 2026) | Öneri mesajında numaralara basmak butona ✓ ekleyip çıkarıyor ve "Hazırla (N)" sayacını güncelliyor — **Worker'da, Actions hiç uyanmıyor**. Tek "Hazırla" basışında seçilenlerin hepsi tek dispatch ile gidiyor ve sırayla üretiliyor. Her seçimde Actions çalıştırmak 3 haber için 3 ayrı job (~5 dk) demekti. ⚠️ id'ler buton METİNLERİNDEN okunuyor, `callback_data`'dan değil — 64 baytlık sınıra takılmamak için. |
| ★ Tekil post İKİ AŞAMALI (19 Ağu 2026) | **1)** Kontrol job'ı taze başlıkları TEK Gemini isteğiyle toplu puanlıyor (~1500 token) ve eşiği geçenleri numaralı butonlarla öneriyor. **2)** Kullanıcı seçince tam metin + görsel + imgbb yalnızca o haber için üretiliyor. Eskiden her aday için tam metin (~4400 token) üretilip eşiği geçmezse ATILIYORDU. Ölçüldü: kontrol **2.81 → 0.55 dk**, sıklık **20 → 36/gün**, Actions **1686 → 594 dk/ay**. |
| ⚠️ Gece: yüksek puanlı haber öneriye DÜŞMEZ | Öneri akışı haberi `durum='yeni'` ve **metinsiz** bırakıyor, `aday_bul` ise yalnızca `metin_hazir` olanlara bakıyor. Yani gece gelen büyük bir haber öneriye düşerse otomatik yayınlanmaz, sabaha kadar bekler — tam da otomatik yayının önlemek istediği şey. Çözüm: toplu puanı `oneri_otomatik_uretim_esigi` (8) üstündeki başlık öneri yerine doğrudan metni üretilip normal akışa bırakılıyor. Eşik 8, çünkü toplu puan tam metin puanından ~1.6 düşük geliyor ve yayın eşiği 9 olan haber burada 7-8 görünüyor. |
| Gece öneri kuralı | Öneri eşiğinde gece **+1 YOK** (yayın eşiğinde var). Gerekçe: öneri yayın değil, insana sunma — mesaj gece gelir, kullanıcı sabah seçer. Gece kuralını öneriye de uygulamak, gece toplanan haberlerin hiç önerilmemesine ve sabaha kadar beklerken tazelik penceresini aşıp görünmez olmasına yol açıyordu. |
| ⚠️ Toplu puanlama ~1.6 puan DÜŞÜK veriyor | Ölçüldü: aynı habere tam metin puanlaması 8 verirken toplu puanlama 5 veriyor. Özeti 200→800 karaktere çıkarmak sapmayı yalnızca 0.2 iyileştirdi — sorun bilgi miktarı değil, **bağlam**: model 10 haberi yan yana görünce kıyaslayıp katılaşıyor. Prompta "her haberi kendi başına değerlendir" notu eklendi (1.8→1.6) ama kapanmadı. Bu yüzden `oneri_kategori_esikleri` tam metin eşiklerinden **2 puan düşük**. Güvenli: öneri eşiği yayın kararı değil, insana sunma kararı. |
| Günlük rapor | `scripts/gunluk_rapor.py` + workflow (TR 09:07). Dün ne yayınlandı, havuz, Instagram kotası, Threads erişimi, son 24 saatte patlayan job'lar, varsayılandan sapmış ayarlar. Bot sessiz çalıştığı için arıza ancak bir şey patlayınca fark ediliyordu. |
| Yayından kaldırma | Yayın sonucu mesajındaki `🗑 Bu yayını kaldır` düğmesi. ⚠️ **INSTAGRAM API'DEN SİLİNEMİYOR** — Graph API izin vermiyor (`(#10) Insufficient permissions`), orada silme yalnızca uygulamadan. Facebook ve Threads siliniyor, Instagram için bağlantı veriliyor. Kaldırılan tur `durum='kaldirildi'`, havuza DÖNMÜYOR. |
| `/tamamla` | Kesilen Threads zincirini kaldığı yerden sürdürür. `zincir_halkalari()` yanıtları **timestamp'e göre** sıralıyor — `/conversation` sırayı garanti etmiyor ve yanlış halkaya bağlamak zinciri ortasından dallandırır. Tam zincirde hiçbir şey yapmıyor. |
| `/arsiv` | Paylaşılmamış eski turları Threads'e gönderir, **bir seferde 3 tur**. Paylaşılan tur `threads_post_id` işaretiyle atlanıyor. |
| İşlem geri bildirimi | Butona basıldığı an Worker butonları kaldırıp `⏳ Yayınlanıyor…` yazıyor. Actions 40-90 sn sürüyor; o sessizlikte insan ikinci kez basıyordu ve "yayınla"da bu **çift post** demekti. Menü iş bitince (ve hata durumunda) geri konuyor, yoksa tur kilitleniyor. |
| Onay mesajı içeriği | Sıra: denetim uyarısı → özet tablo (sıra no + katman simgesi + başlık) → caption. Katman simgeleri: 📷 Commons (gerçek) · 🖼 Pexels (temsili) · ▪️ gradyan · 🎨 AI. Albümdeki her fotoğrafta da kendi numarası yazılı. |
| Ülke flaması | Sağ üstte, sağ kenara yapışık **kırlangıç kuyruklu flama**: bayrak üstte (54px), ülke adı altında (19 punto). V çentiğinin kırılımı flamanın ortasında değil, **bayrak/yazı ayrımının hizasında**. |
| Ülkesiz haber | **Flama basılmaz.** Bilim, teknoloji, uzay, borsa gibi coğrafyaya bağlı olmayan haberlerde `ulke_kodu` boş bırakılır — zorlama ülke atamak yanlış yer bilgisi vermek olur. |
| Kuruluş bayrağı | `ulke_kodu` yerine kuruluş kodu yazılabilir: `nato, un, eu, who, unesco, unicef, opec, oic, africanunion, arableague, commonwealth, redcross`. Commons'tan çekilir. **Spor kulübü / şirket / parti logosu YOK** — tescilli marka, haber sitesi fotoğrafıyla aynı gerekçe. |
| Arşiv ibaresi | Fotoğraf kullanılan slaytlarda alt bilgiye `· ARŞİV GÖRSELİ` ekleniyor — görsel o olayın belgesi değil. |
| Facebook (17 Ağu 2026) | Instagram'a yayınlanan içerik **aynı jetonla** Facebook sayfasına da gidiyor (`src/facebook.py`). Ek anahtar yok — `pages_manage_posts` izni uygulamaya eklendi ve mevcut sayfa jetonu onu kazandı. **Story de paylaşılıyor** (`/photo_stories`) — aynı 9:16 görsel, ayrı üretim yok. Carousel Facebook'ta **albüm**: görseller `published=false` ile yüklenip `/feed`'de `attached_media` ile tek posta bağlanıyor. İKİNCİL KANAL: patlarsa Instagram postu yayında kalır, Telegram sonucuna not düşülür. `config.yaml → sosyal.facebooka_da_at: false` ile kapatılır. |
| ⚠️ Çapraz paylaşım neden olmaz | Instagram'ın kendi "Facebook'a paylaş" ayarı denendi ve ELENDİ: o ayar Instagram UYGULAMASINDAN yapılan paylaşımlar için, API ile gidenleri tetiklemiyor. Ayrıca menüde yalnızca kişisel profil çıkıyor, sayfa çıkmıyor. |
| Kanal ikonları | Slayt alt bilgisinde Instagram / X / Facebook ikonları, `config.yaml → sosyal.kanallar`. Resmi logolar SVG ve Pillow SVG okumuyor; Unicode sembolleri de fontta yok (ölçüldü, "NO GLYPH" çıkıyor). Bu yüzden Pillow ile çizilen tanınabilir sadeleştirmeler kullanılıyor. |
| Threads (18 Ağu 2026) | **KURULDU, jeton alındı.** `src/threads.py`, carousel destekli (2-20 görsel). ⚠️ **Instagram/Facebook jetonu BURADA ÇALIŞMAZ** — `graph.threads.net` ayrı API, ayrı jeton: `THREADS_ACCESS_TOKEN` + `THREADS_USER_ID` (28048974518044795, @dailybrief.co). İkincil kanal: patlarsa Instagram postu yayında kalır. `config.yaml → sosyal.threadse_de_at: false` ile kapatılır. |
| ⚠️ Threads jetonu nasıl alındı | Uzun ve tuzaklı: **1** Threads use case → Permissions'tan `threads_basic` + `threads_content_publish`. **2** App roles → Add People → **"Threads Tester"** (Administrator YETMİYOR, ayrı rol). **3** Telefondan Threads → Ayarlar → Hesap → Web sitesi izinleri → Davetler'den kabul. **4** Settings sayfası → en altta User Token Generator → Generate token. OAuth yolu denendi ve ELENDİ: Redirect URL kaydedilemedi ("Form can't be saved"), tester yolu zaten daha iyi — app secret gerekmiyor ve jeton doğrudan uzun ömürlü geliyor. |
| ⚠️ Threads profili olmayabilir | En büyük tuzak buydu: @dailybrief.co'nun Threads profili HİÇ YOKTU. Belirtisi: "Generate token" → login ekranı → giriş → aynı ekrana geri düşüş, hata mesajı yok. threads.com/login "hesabını nasıl oluşturmak istersin" diyorsa profil yok demektir. Profil olmadan tester daveti gidecek yer bulamıyor. Hesap ayrıca **herkese açık** olmalı. |
| ⚠️ Threads CAROUSEL DEĞİL, ZİNCİR | **Threads metin platformu, sınırı 500 karakter.** 10 slaytlık carousel + kırpılmış caption oranın dili değil. Doğru biçim zincir (`threads.zincir_yayinla`): ana gönderi tarih + ilk manşet + hashtag, her haber ona bağlı bir yanıt. Son dakikada ayrıntı sayfaları zincirin devamı. Halkalar **birbirine** bağlanıyor, hepsi ana gönderiye değil — hepsi ana gönderiye bağlanırsa Threads sırayı garanti etmiyor. Zincir kurma: `caption.threads_halkalari()`. |
| ⚠️ Threads halka aralığı 15 sn | Threads art arda medya isteği kabul etmiyor. **Ölçüldü:** carousel'de 5 sn yetiyordu ama zincirde yetmedi — 10 halkalı zincirin 1. halkadan sonrası TAMAMEN düştü. Zincir daha ağır: her halka hem container hem publish çağırıyor. 12 sn'de 6/6 başarılı. ⚠️ Süreyi uzatmak tek başına çözmüyor: 10/20/30 sn denendi, sonuç hata/başarı/hata. Medya tarafı kararsız, asıl güvence **deneme sayısı** (`AZAMI_DENEME = 5`, sabit 15 sn bekleme). |
| ⚠️ Yarım zinciri başarı sayma | İlk sürümde `zincir_yayinla` kesintide yalnızca `ana_id` dönüyordu ve çağıran "✓ yayınlandı" yazıyordu. 18 Ağu 2026: 10 halkanın 1'i yayınlandı, ekranda başarı göründü, kullanıcı Threads'e bakınca fark etti. Artık `(id, yayinlanan_halka)` dönüyor ve eksikse açıkça bildiriliyor. **Yarım işi başarı diye raporlamak, hatayı hiç görmemekten kötü.** |
| Paylaşım bildirimi (18 Ağu 2026) | `telegram_bot.paylasim_bildir()` her paylaşımın sonucunu gruba yazıyor. Neden gerekti: yayın sonucu yalnızca onay mesajının içinde özetleniyordu, ama **Telegram'dan tetiklenmeyen** paylaşımlar (gece otomatik yayın, `gecmisi_paylas.py`) hiçbir bildirim üretmiyordu. |
| Arşiv paylaşımı | `scripts/gecmisi_paylas.py` — yayınlanmış turları Threads'e taşır. Her tur KENDİ tarihiyle (bugünün tarihiyle değil). `--kuru` önizler, `--adet N` kademeli gönderir. ⚠️ **2 günden eski turların görselleri yok** (`imgbb.omur_saniye: 172800`); o turlar atlanıyor. 15 Ağu turu bu yüzden paylaşılamadı. |
| ⚠️ Threads jetonu 60 GÜN | Instagram'daki süresiz sayfa jetonunun karşılığı Threads'te YOK. **Otomatik yenileme kuruldu** (18 Ağu 2026): haftalık `jeton-yenile.yml` artık iki jetonu da tazeliyor (`threads.jetonu_yenile` → `th_refresh_token`), yeni jeton `.env` ve GitHub Secret'a yazılıyor. Threads kalan süreyi sorgulatmadığı için **koşulsuz** yeniliyoruz — öğrenmenin tek yolu yenilemek. ⚠️ Jeton **24 saatten yeniyse** yenileme hata verir; bu beklenen, sonraki hafta düzelir. Yenilenmezse arıza SESSİZ: `kullanilabilir_mi()` True dönmeye devam eder, hata ancak yayın anında çıkar. |
| ~~WhatsApp Kanalı~~ | **İMKANSIZ.** WhatsApp Business API kanalları desteklemiyor; kanala yalnızca telefondan elle post atılabiliyor. Politika kısıtı, aşılamaz. |
| ~~TikTok~~ | **ERTELENDİ.** Fotoğraf paylaşım API'si var ama uygulama denetimi (audit) gerekiyor; onaysız uygulamalar yalnızca TASLAK gönderebiliyor, kullanıcı uygulamadan yayınlıyor. Yani tam otomatik değil. |
| ~~X/Twitter~~ | **ERTELENDİ (18 Ağu 2026) — ÜCRETLİ ÇIKTI.** Geliştirici hesabı açıldı (@dailybrief_co), 4 anahtar alındı, "Read and write" izni doğrulandı, `src/x_paylas.py` yazıldı. Sonra görüldü ki **X API artık kredi bazlı**: hesapta `Free credits $0.00`, bakiye $0, post atmak para istiyor. Eski "ayda 500 post ücretsiz" katmanı bu hesapta yok. Kullanıcı ücret ödemek istemediği için bırakıldı; **logosu da slayttan kaldırıldı** — sahip olmadığımız kanalın logosunu basmak yanlış. Ödeme yöntemi eklenmediği için istem dışı ücret riski YOK. Tekrar açmak için: kredi yükle → `config.yaml → sosyal.kanallar`'a `- x` ekle → `x_paylas.yayinla()`'yı akışa bağla. Anahtarlar `.env`'de duruyor. |
| ⚠️ X 280 karakter | Caption'lar 1100-1500 karakter, X'e SIĞMIYOR. `x_paylas.metni_kur()` bunun için var: kırpmak yerine baştan X'e uygun metin kuruyor (tarih + sığdığı kadar manşet + 3 hashtag). Kırpma denenmedi çünkü caption'ın sonu kaynak/atıf satırları ve onlar zaten sığmıyor. |
| Story (17 Ağu 2026) | Post ile birlikte **otomatik** paylaşılıyor, ayrı onay yok — içerik zaten onaylanan haberlerin listesi. Akşam turu → manşet listesi (9:16), son dakika → haberin kendisi. Story ikincil: patlarsa post yine çıkar, sonuç mesajına not düşülür. **CANLI TEST EDİLDİ**, uçtan uca çalıştı. |
| ⚠️ Story kısıtı | **API'den sticker/link/mention EKLENEMİYOR.** "Postu gör" diyemiyoruz, o yüzden story tek başına anlamlı olmak zorunda — akşam story'si manşetleri listeliyor, gören kişi postu açmasa bile gündemi öğreniyor. Elenen kapak tasarımı burada işe yaradı (carousel'de slayt yiyordu, story'de öyle bir maliyeti yok). |
| ~~Reels/video~~ | **ERTELENDİ (17 Ağu 2026), elenmedi.** Eski gerekçelerden ikisi geçersiz: runner'da ffmpeg ZATEN var, Cloudflare R2 bedava (hesap mevcut). Geçerli kalan tek engel: **müzik Graph API'den eklenemiyor** — Instagram'ın müzik kütüphanesi yalnızca resmi uygulamada, bu bir politika kısıtı, aşılamaz. Müziksiz/telifsiz müzikli Reels yapılabilir ama izlenme süresi düşük olacağı için erişim avantajının çoğu kaybolur. Kullanıcı "şimdilik her şey aynı kalsın" dedi. |
| ★ İki aşamalı tur (20 Ağu 2026) | Tur önce **BAŞLIK LİSTESİ** olarak sunuluyor (`genel.basliklari_once_sor`), onaylanınca slaytlar üretiliyor. Kullanıcı isteği: *"akşam turlarının da önce başlıklarını ver, okeylersem görselleri üretilsin"*. Ölçüldü: başlık önizlemesi **2 saniye**, tam tur ~60 saniye — beğenilmeyecek liste için görsel üretilmiyor. `hazirla.turu_tamamla()` ayrı fonksiyon; `onay_isle.tur_onayla` onu çağırıyor. ⚠️ `--kuru` bu dallanmayı ATLIYOR: kuru çalışmanın amacı slaytları görmek. ⚠️ `hatirlat.py` `baslik_onayi` durumunu da kapatıyor, yoksa tur sonsuza kadar açık kalır; `yayinla` bu durumdaki turu reddediyor (slaytı yok). |
| ★ Atlanan haber 12 saat gelmiyor | `atlanma_zamani` + `genel.atlanan_bekleme_saat`. ⚠️ **SKOR CEZASI TEK BAŞINA YETMEDİ**: `ERTELEME_CEZASI = 15` eklendikten sonra bile atlanan 10 haberin **5'i** bir sonraki turda geri geldi — havuz dar olduğu için 8 puanlık haber ceza yese de 6 puanlık taze haberin önünde kalıyor. "Atla" demek "sıralamada geri at" değil, "şimdi bunu istemiyorum". |
| ⚠️ SQLite `datetime('now')` SAAT DİLİMSİZ | `datetime.now(timezone.utc)` ile çıkarmak `TypeError` veriyor. İlk yazımda bu `except (TypeError, ValueError): pass` ile yutuluyordu ve atlama kuralı **SESSİZCE hiç çalışmadı** — atlanan 8 haber geri geldi, log'da tek uyarı yoktu. `aday._saat_gecti()` saat dilimsiz değeri UTC kabul ediyor ve okunamayan değeri **logluyor**. ⚠️ Ders: `except: pass` bir kuralı sessizce iptal edebilir. |
| Bayatlama sınırı | Yayın tarihinden **36 saat** (48'den çekildi, 20 Ağu 2026 kullanıcı isteği) |
| Onay verilmezse | **Haber ELENMEZ**, havuza döner, sonraki turda yeniden yarışır |
| Tur ne zaman kapanır | TR 23:00'te **veya** 6 saat onaysız beklerse (`hatirlat.AZAMI_BEKLEME_SAAT`). ⚠️ Saat kuralı tek başına yetmiyordu: sabah turu eklenince, onaylanmayan sabah turu akşam 23:00'e kadar açık kalıp akşam turuyla çakışıyordu. |
| ~~"Atla" butonu~~ | **GEÇERSİZ.** Tek-haber tasarımından kalmaydı; carousel'de 10 haber var, "sıradakini öner" anlamsız. Yerine aşağıdaki menü geldi. |
| ★ Zamanlanmış yayın (20 Ağu 2026) | `✅ Yayınla` artık **alt menü** açıyor: `▶️ Şimdi` / 30 dk / 1 / 2 / 3 / 4 saat, **iki sütun**. Seçilen an `planlanan_yayin` kolonuna UTC yazılıyor; zamanı gelen turu **son dakika kontrolü** yayınlıyor (`son_dakika.planli_yayinlari_isle`). ⚠️ **HASSASİYET ±30 DK** — o cron 30 dakikada bir çalışıyor, seçenekler bu yüzden 30'un katı. "15 dk" bilerek YOK: gerçekte 15-45 dk arası yayınlanır ve düğme yalan söylerdi. Ölçüldü: cron'u 15 dk'ya çekmek Actions'ı 594 → 1122 dk/ay yapıyor, kota zaten sınırda. Bu çözümün **ek Actions maliyeti sıfır** (tek SELECT); job içinde `sleep` beklemek 2 saatlik planda 120 dk kota yakardı. |
| ⚠️ Planlı tur İKİ zaman aşımından muaf | Yoksa yayın anı gelmeden ölürdü: `suresi_gecmisi_iptal_et` **60 dakikada** iptal ediyor (yani "1 saat sonra" planı bile kendini öldürürdü) ve `hatirlat.py` 6 saatte havuza döndürüp o ana kadar saat başı gereksiz hatırlatma atıyordu. İkisinin SELECT'ine `planlanan_yayin IS NULL` kondu; `test_7_sozlesme` bunu denetliyor (kasten bozularak doğrulandı). Plan üstünden **4 saat** geçmişse yayın yapılmıyor — cron atlanmış olabilir ve o karar artık kullanıcının verdiği karar değil. Yayın öncesi plan **önce siliniyor**: yayın yarıda patlarsa sonraki kontrol aynı turu ikinci kez yayınlamasın. |
| Onay butonları | İki katmanlı menü (15 Ağu 2026): **Ana menü** → `✅ Yayınla` / `🔄 Metinleri yeniden üret` / `🎨 Bir slaytın görselini değiştir` / `📋 Tekil atma, 10'lu tura bırak` / `❌ Bu turu atla`. ⚠️ "Tura bırak" ile "atla" farkı: atla haberi havuza döndürüyor ve haber yine tekil aday oluyor (bkz. 1s); "tura bırak" `sadece_tur=1` koyup tekil adaylıktan çıkarıyor. **Slayt menüsü** → 1-10 arası seçim → `🔀 Başka fotoğraf (bedava)` / `🎨 AI ile üret (~$0.04)`. |
| Menü gezinme nerede | **Worker'da, GitHub'da değil.** Actions'ı uyandırmak 30+ saniye sürüyor, menü açmak anında olmalı. Yalnızca gerçek eylemler (`yayinla`, `iptal`, `metin_yenile`, `slayt_ai:N`, `slayt_foto:N`) `repository_dispatch` ile GitHub'a gidiyor. |
| ⚠️ WORKER GIT'LE DEPLOY OLMUYOR | `worker/index.js` değiştirilip push edilince Cloudflare'e **gitmiyor** — ayrı bir servis. `cd worker && npx wrangler deploy` şart. 19 Ağu 2026'da unutuldu: yeni `hazirla:` butonu Telegram'da "tanınmayan komut" verdi, kod doğruydu ama Worker eski sürümdeydi. Belirtisi tam olarak bu: buton çalışmıyor ama Actions'ta hiç kayıt yok, çünkü istek GitHub'a hiç ulaşmıyor. |
| ⚠️ Menü ikilemesi | Buton düzeni **iki yerde** tanımlı: `src/telegram_bot.py` ve `worker/index.js`. Birini değiştirirsen diğerini de değiştir. Slayt sayısı `callback_data`'ya gömülü (`slayt_menu:10`) — Worker'ın turda kaç slayt olduğunu bilmesinin başka yolu yok. |
| Secrets | `.env` (yerel) + GitHub Actions Secrets (uzak). Koda gömülmez. |

---

## 4. ŞU ANKİ DURUM

### 🟢 BOT YAYINDA — son güncelleme 20 Ağustos 2026

Tüm adımlar bitti. Sistem kendi başına çalışıyor ve **gerçek postlar
yayınlandı**:

| Tarih | Post |
|---|---|
| 15 Ağu 19:04 | instagram.com/p/DcEmOj8m2cG |
| 16 Ağu 17:58 | instagram.com/p/DcHDZDbEhQF |
| 17 Ağu 23:06 | post `18071412488477132` + story + Facebook albüm + Facebook story |

17 Ağustos turu **dört ayrı arızayı** aştıktan sonra çıktı (bkz. 1d/1e).
Story, Facebook albümü ve Facebook story'si aynı akışta ilk kez birlikte
yayınlandı ve üçü de doğrulandı. Threads jeton beklediği için atlandı.

16 Ağustos turu **tamamen otomatikti**: cron 17:31'de hazırladı (7 dk),
Telegram'a düştü, onaylandı, 17:58'de yayınlandı.

**Maliyet (19 Ağu 2026'da ölçüldü) — "sıfır" DEĞİL, ~$2/ay.**

Görsel tarafı gerçekten bedava: normal turda AI hiç çağrılmıyor
(Commons/Pexels/gradyan), imgbb·Pexels·Telegram·Cloudflare ücretsiz
katmanda, Instagram jetonu süresiz.

Ücretli olan tek şey Gemini metin üretimi:

| | |
|---|---|
| Ücretsiz kota | model başına **günde 20 istek** — iki modelle günde 40 |
| Gerçek kullanım | ortalama **33 istek/gün** (yoğun günde 92) |
| Bedava kotayı aşan | ~300 istek/ay |
| Aylık maliyet | **~$1.81** (gemini-3.6-flash, 2026 fiyatı) |
| Her istek ücretli olsaydı | ~$6.95/ay |
| ⚠️ 1 Ocak 2027'den sonra | fiyat **iki katına** çıkıyor → ~$3.6/ay |

⚠️ **Kota hatası artık doğru raporlanıyor.** `_cevabi_coz` eskiden her
beklenmedik yapıya aynı cevabı veriyordu: *"Cevap beklenen yapıda değil
(finishReason=?)"*. Üç ayrı durum bu mesaja düşüyordu ve üçünün çözümü
farklıydı: API hata cevabı (429/403/400), sonucun **ikinci kez**
çözümlenmesi (çağıranın hatası), gerçek güvenlik filtresi. 19 Ağu'da bir
A/B ölçümü 20 istek harcayıp bu mesajla döndü ve kotanın dolduğu sanıldı;
gerçek sebep çift çözümlemeydi. Artık üçü ayrı ayrı ve çözümü söyleyerek
raporlanıyor.

⚠️ **Retry'lar da kotadan sayılıyor.** 429 alınan istek 3 kez
deneniyor ve üçü de kotadan düşüyor; bu yüzden bedava kota
göründüğünden erken bitiyor.

⚠️ **Maliyet SESSİZ oluşuyor.** Ücretsiz kota bitince kod yedek
(faturalı) anahtara geçiyor ve çalışmaya devam ediyor — log'a
"Gemini yedek anahtarı kullanıldı" yazıyor ama kimse bakmıyor.
Günlük rapora eklenmeli.

**GitHub Actions:** 7 günlük ölçümle **1356 dk/ay**, private repo
kotası 2000 dk/ay → şu an **$0**, ama pay yalnızca %32. Aşım
Linux'ta $0.008/dk. Sıkışırsa `son-dakika.yml` cron'u 2 saatte bire
çekilir (bkz. 1b).

---

### ⚠️ İKİ TUZAK — YENİ OTURUM BUNLARI BİLMELİ

**1. Veritabanının sahibi GitHub, yerel değil.**

Her job sonunda `data/haber.db` repoya commit ediliyor. Yerelde
`hazirla.py` çalıştırırsan yerel DB ilerler, GitHub'daki geride kalır ve
iki taraf ayrışır. Bu bir kez yaşandı: Telegram butonu GitHub'daki DB'ye
baktığı için "bu onay mesajına bağlı haber bulunamadı" hatası verdi.
Ayrıca hatırlatma job'ı artık var olmayan bir turu işaret etti.

Kural: **yerelde denemek gerekiyorsa `--kuru` kullan** (üretir, Telegram'a
göndermez, DB'ye durum yazmaz). Gerçek tur yerelde çalıştırıldıysa
bitince DB hemen commit+push edilmeli. Push çakışırsa hangi tarafın
güncel olduğuna BAK — yayın kaydı hangisindeyse o doğrudur.

**1b. GitHub Actions kotası artık sıkı.**

Ölçüldü (16 Ağu 2026): akşam turu + onay job'ları ~210 dk/ay. Son dakika
saat başı kontrolü **+1080 dk/ay** getiriyor → toplam ~1290 / 2000 dk
(%65). Sığıyor ama pay az. Sıkışırsa `son-dakika.yml` cron'unu
`"0 */2 * * *"` yap, yarıya iner.

Diğer servisler rahat: Gemini %7, Instagram 1/100, Pexels 481/25.000,
Cloudflare 10/100.000.

**1c. YARIŞ DURUMU — onay, veritabanı push'undan önce gelebiliyor.**

17 Ağu 2026, 16:53'te yaşandı: son dakika turu Telegram'a düştü,
16:54'te onaylandı, ama turu hazırlayan job'ın veritabanı commit'i
henüz push edilmemişti. Yayın job'ı checkout yaptığında turu göremedi:
"⚠️ Bu onay mesajına bağlı haber bulunamadı".

İki katmanlı çözüm (`src/db_senkron.py`):
1. `hemen_kaydet()` — Telegram mesajı gider gitmez veritabanı
   commit+push ediliyor, workflow sonundaki adım beklenmiyor.
2. `uzaktan_tazele()` — yayın job'ı turu bulamazsa en güncel
   veritabanını çekip bir kez daha bakıyor.

Workflow sonundaki commit adımı YERİNDE DURUYOR — birinci katman
patlarsa yedek.

**1d. ⚠️ `git pull --rebase` REPOYU KİLİTLİYOR — aynı akşam tekrarladı.**

17 Ağu 2026, 20:54'te akşam turu Telegram'a düştü ama veritabanı
GitHub'a HİÇ yazılamadı; onaya basılınca yine "bu onay mesajına bağlı
haber bulunamadı" geldi. 1c'deki çözüm bu sefer yetmedi çünkü sorun
zamanlama değil, **git'in kendisiydi.**

Zincir:
1. `hazirla` 17:40'ta `main` dalında başladı, 14 dakika sürdü.
2. 17:46'da kullanıcı bir **son dakika** haberini onayladı. Onay job'ı
   AYRI bir concurrency grubundaydı (`onay-islem`), araya girdi ve
   `data/haber.db`'yi push etti.
3. 17:54'te turun push'u reddedildi (uzak ilerlemişti).
4. Yedek olarak yazılmış `git pull --rebase` çalıştı → `haber.db`
   **ikili dosya, birleştirilemez** → rebase çakıştı ve YARIM KALDI.
5. Repo **detached HEAD**'de kilitlendi. Sonraki her `git push`
   "You are not currently on a branch" verdi — `hemen_kaydet()` de,
   workflow sonundaki yedek adım da. Turun 10 haberi kayboldu,
   sıfırdan hazırlamak gerekti.

Üç katmanlı çözüm:
1. **Tek concurrency grubu: `veritabani`.** Veritabanına yazan dört
   workflow (`hazirla`, `son-dakika`, `yayinla`, `hatirlat`) artık aynı
   grupta, aynı anda çalışamıyorlar. Asıl çözüm bu — ikili bir dosyada
   birleştirme diye bir şey yok, tek gerçek çare çakıştırmamak.
   **Yeni workflow DB'ye yazıyorsa bu gruba koy.**
2. **`git push origin HEAD:main`.** Düz `git push` bulunulan dala
   bağımlı; refspec vermek detached HEAD'de bile çalışıyor.
3. `db_senkron._birlestir()` çakışan rebase'i kendisi çözüyor
   (`--theirs` = bizim taze turumuz), çözemezse `rebase --abort` ile
   temizliyor. Repo asla yarım rebase'de bırakılmıyor.

⚠️ **`git pull --rebase`'i bu repoda çıplak kullanma.** Yerelde de
geçerli: `haber.db` her turda değiştiği için çakışma kuraldır, istisna
değil.

**1e. Aynı akşam çıkan diğer üç arıza (17 Ağu 2026) — hepsi düzeltildi.**

Turu kurtarırken arka arkaya patladılar; dördü de ayrı kusurdu.

| Belirti | Kök sebep | Düzeltme |
|---|---|---|
| Threads: `2207052 An unknown error occurred` | Instagram'daki 2207003'ün kardeşi. Kurulumda ölçüldü: aynı görsel 4 denemede reddedildi, sonra kendiliğinden geçti ve iki farklı barındırıcıdan yüklendi. Görselde kusur yoktu. | `threads.GECICI_ALT_KODLAR` + 15 sn'den başlayan bekleme. |
| `carousel 2-10 görsel ister, 13 verildi` | Onaylanmayan son dakika haberi havuza dönerken `detay_url` üstünde KALIYOR. Aynı haber akşam turunda seçilince eski 3 ayrıntı sayfası carousel'e sızdı. | `onay_isle.yayinla` ayrıntı sayfalarını yalnızca `son_dakika` işaretli haberde ekliyor. |
| `HTTP 400 Timeout / 2207003` | Instagram görseli imgbb'den KENDİSİ indiriyor, o indirme zaman aşımına uğradı. Cevapta `is_transient: false` yazıyor ama **yalan** — aynı URL saniyeler sonra iniyor. Retry yalnızca HTTP koduna baktığı için hiç denenmedi. | `instagram.GECICI_ALT_KODLAR` + medya hatasında 15 sn'den başlayan bekleme. |
| Yayın başarılı ama Telegram'da dönüt yok | Sonuç yalnızca `editMessageText` ile yazılıyordu. **Telegram düzenlemede bildirim ÜRETMİYOR**; onay mesajı sohbette yukarıda kalıyor, yayın 2 dk sürüyor, kullanıcı sonucu hiç görmüyor. | `sonucu_yaz(..., bildir=True)` sonucu ayrıca yeni mesaj olarak gönderiyor. Düzenleme yine yapılıyor — butonları kaldırmanın başka yolu yok. |

**Ayrıca:** `hatirlat.py` artık **90 dakikadan yeni turu kapatmıyor**
(`TAZE_TUR_DAKIKA`). Elle kurulan geç bir tur, 11 dakika sonraki
hatırlatmada "onay gelmedi" diye havuza dönüyordu. Normal 20:07 turunda
3 saatlik pay var, elle kurulanda yok.

Yoğun test edilen bir günde kota doldu ve tur yarıda kaldı. `hazirla.py
--metinsiz` bunun için var: Gemini'ye hiç gitmeden, metni ZATEN hazır
haberlerle tur kurar. Turu tamamen kaçırmaktansa elimizdekiyle devam.

Kota hatası alan haberler `durum='hata'` oluyor; bu haberin kusuru değil,
`durum='yeni'` yapılıp havuza döndürülmeli.

---

**1f. ⚠️ YAML'daki çıplak `git rebase` — 1d'nin TEKRARI (18 Ağu 2026).**

Akşam turu hazırlandı, Telegram'a HİÇ ulaşmadı, kayboldu. 1d'de
"çözüldü" denen arızanın aynısı, başka bir kod yolundan.

Zincir: `hazirla` 20:40'ta turu kurdu → push reddedildi (araya son
dakika job'ı girmişti) → yedek yol `git rebase origin/main` çalıştı →
`haber.db` ikili, çakışma çözülemedi → job kırmızı, tur yok oldu.

17 Ağu'da `db_senkron._birlestir()` yazılıp Python tarafı düzeltilmişti
ama **dört workflow YAML'ı kendi ham git komutlarını çalıştırmaya devam
ediyordu.** O gün CLAUDE.md'ye yazılan ders birebir tekrarladı:
*bir düzeltmeyi uygularken aynı işi yapan DİĞER kod yolunu da ara.*

Düzeltme: `scripts/db_kaydet.py` (yeni). Dört workflow artık onu
çağırıyor, o da `db_senkron.hemen_kaydet()` kullanıyor. Çakışmayı
çözüyor, çözemezse `rebase --abort` ile repoyu temiz bırakıyor.
⚠️ **Workflow'a veritabanı yazan yeni bir adım eklerken ham git
komutu YAZMA, `scripts/db_kaydet.py` çağır.**

**1g. Gemini günlük kotası turu düşürüyor — `--metinsiz` artık
Actions'tan tetiklenebiliyor.**

Aynı gece ücretsiz anahtar `GenerateRequestsPerDayPerProjectPerModel-
FreeTier` sınırına vurdu. Haber başına 3 model × 2 anahtar deneniyor,
hepsi 429; tur 20 dakika sürüp hiçbir yere varamadı.

`hazirla.py --metinsiz` bu iş için zaten vardı ama yalnızca komut
satırından erişiliyordu. `hazirla.yml`'e `metinsiz` girdisi eklendi:
Actions ekranından tetiklenebiliyor, Gemini'ye HİÇ gitmiyor, metni
hazır haberlerle tur kuruyor. Kota dolu gecelerde turu kurtarmanın en
hızlı yolu bu.

⚠️ Yedek (faturalı) anahtar devreye giriyor ve ÇALIŞIYOR — yani kota
dolduğunda sistem durmuyor, **para harcamaya başlıyor.** Sessiz bir
maliyet: log'a "yedek anahtar kullanıldı" yazıyor ama kimse bakmıyor.
Günlük rapora eklenmeli.

**1h. ⚠️ Kaynağı kapatmak, ondan gelmiş KAYITLARI düzeltmiyor.**

TRT Teknoloji kaldırıldıktan sonra da veritabanındaki 4 kayıt
`teknoloji` etiketiyle kaldı ve **ikisi ertesi akşamın turuna girdi** —
"Bozbey CHP'den istifa etti" yine TEKNOLOJİ etiketiyle yayınlanacaktı.
Havuz 48 saat aday tuttuğu için kaynak kapatmanın etkisi iki gün
gecikiyor.

Kural: bir kaynağı `config.yaml`'den çıkarırken
`UPDATE haberler SET kategori=... WHERE kaynak='<ad>'` ile eski
kayıtları da düzelt.

**1i2. Slaytta artık BESLEME adı değil YAYIN KURULUŞU yazıyor
(20 Ağu 2026, kısmi düzeltme).**

Kullanıcı sordu: *"ABD Katar yakıt ikmal uçağı haberi neden AA
ekonomi kategorisinde, normal mi?"* — haber savunma haberi ama
slaytta **AA EKONOMİ** yazıyordu.

Sebep 1k'nin devamı: slayta basılan `kaynak` alanı ve o alan RSS
BESLEMESİNİN adı ("AA Ekonomi", "TRT Dünya", "NTV Teknoloji").
Besleme adı bizim iç kaydımız — tekrar engeli, ağırlık ve ölçüm ona
bakıyor — ama okuyucuya gösterilmesi gereken yayın kuruluşu.

Çözüm: `config.yaml → kaynaklar[].gosterim_adi` (11 kaynağa eklendi)
+ `make_image.kaynak_gosterim_adi()`. Slayt, story ve caption'daki
kaynak listesi bu adı kullanıyor; tanımsızsa besleme adı olduğu gibi
kalıyor. `haberler.kaynak` DEĞİŞMEDİ, yani geçmiş kayıtlar ve tekrar
engeli bozulmadı (1h/1k'da eski kayıtları düzeltmek gerekmişti,
burada gerekmiyor — tam da bu yüzden ayrı alan seçildi).

⚠️ Bu, kategori kusurunun yalnızca GÖRÜNEN yüzü. `kategori` kolonu
hâlâ beslemeden geliyor ve şerit rengini, ön elemedeki kategori
payını o belirliyor — aşağıdaki madde hâlâ geçerli.

**1i3. ✅ KATEGORİ ARTIK HABERİN İÇERİĞİNDEN GELİYOR (20 Ağu 2026).**

Aşağıdaki 1i kusuru KAPATILDI. `CEVAP_SEMASI`'na `kategori` alanı
eklendi ve Gemini haberin tam metnine bakarak seçiyor.

Ölçüldü: *"ABD'den Katar'a 4,5 milyar dolarlık yakıt ikmal uçağı
satışına onay"* — besleme `ekonomi` diyordu, Gemini **`dunya`**
dedi. Zaten doğru olan haberlere dokunmuyor (AA Spor'dan gelen maç
haberi `spor`, TMO haşhaş alımı `ekonomi` kaldı).

**Ek Gemini maliyeti YOK** — zaten yapılan çağrıya bir alan eklendi.

⚠️ **KATEGORİ LİSTESİ ÜÇ YERDE YAŞIYOR** ve üçü de aynı olmalı:
`generate_text.KATEGORILER` · `gorsel.serit_renkleri` ·
`secim.kategori_katsayilari`. Biri eksik kalırsa hata VERMEZ, sessizce
yanlış çalışır: renksiz kategori "turkiye" rengine düşer, katsayısız
kategori varsayılan ağırlıkla yarışır. `test_7_sozlesme` bunu
denetliyor (kültür rengi kasten silinerek doğrulandı).

⚠️ İki savunma katmanı var: şemada `enum` **ve** `db._gecerli_kategori`
beyaz listesi. Şema tek başına yeterli değil — model şemayı ihlal
edebiliyor ve eski kayıtlar başka yollardan geliyor.

⚠️ Eski kayıtlar OLDUĞU GİBİ kaldı (1h dersi): kategori yalnızca metni
YENİ üretilen haberlerde düzeliyor. Havuzdaki eski haberler beslemeden
gelen etiketini taşımaya devam ediyor.

**1i. ⚠️ KATEGORİ HABERİN DEĞİL, KAYNAĞIN ÖZELLİĞİ (açık kusur — 1i3
ile KAPATILDI, aşağısı tarihsel kayıt).**

`fetch_news.py:292` → `kategori=kaynak["kategori"]`. Haberin içeriğine
hiç bakılmıyor. Sonuç: Venezuela depremi ve Batı Şeria baskını
`turkiye` kategorisinde görünüyor, çünkü TRT genel akışından geldiler.

Etkilediği yerler: slayttaki kategori etiketi, şerit rengi, ön
elemedeki kategori payı. Gemini haberin tam metnini zaten okuyor;
`CEVAP_SEMASI`'na `kategori` alanı eklenip ona sordurulabilir.
**Henüz yapılmadı.**

**1j. ⚠️ AYNI OLAY ÜÇÜNCÜ KEZ TURA GİRDİ — `link` UNIQUE yetmiyor.**

18 Ağu 2026: "Bozbey CHP'den istifa etti" haberi aynı gün İKİ KEZ
yayınlandı (14:47 ve 16:48, ayrı postlar) ve akşam turunda ÜÇÜNCÜ kez
seçilmişti. Kullanıcı fark etti.

Aynı olayın **beş ayrı kaydı** vardı: Sözcü, TRT, BBC, Independent
hepsi kendi haberini yazmıştı. `haberler.link` UNIQUE tekrar engeli
sanılıyor ama yalnızca AYNI LİNKİ engelliyor — farklı kaynakların aynı
olayı farklı linklerle vermesi tekrar sayılmıyordu. `cesitlendir()` de
yalnızca tur İÇİNDEKİ haberleri karşılaştırıyordu.

Çözüm: `secim.yayinlanmis_konular()` son 2 günün yayınlarını getiriyor,
`cesitlendir` onlara karşı da eliyor.

⚠️ **Geçmiş denetimi tur içi denetimden FARKLI çalışmalı.** İki ek şart:
eşik daha yüksek (3 vs 2) **ve ortak ÖZEL İSİM zorunlu**. Ölçüldü:
yalnızca kelime saymak yanlış pozitif veriyordu — iki tamamen farklı
mevzuat haberi *"Resmi Gazete'de yayımlandı"* üzerinden, Venezuela
depremi *"daki/kaybı/yükseldi"* üzerinden eşleşti. Amaç devam eden
olayı engellemek değil (İsrail-Gazze her gün gelişiyor), aynı haberin
tekrarını engellemek.

**1k. ⚠️ SLAYTTA BASILAN ŞEY KATEGORİ DEĞİL, KAYNAK ADI.**

`make_image.py:614` → `alt_metin = _buyuk_harf(kaynak)`.

1h'deki düzeltmede yalnızca `kategori` sütunu düzeltilmişti ve slaytta
hâlâ **TRT TEKNOLOJİ** yazıyordu. Kaynak adı ayrı bir sütun ve slayta
basılan o. Kayıtların `kaynak` alanı da `TRT Haber` yapıldı.

Kural: bir kaynağı kapatırken **iki sütunu birden** düzelt —
`kategori` (şerit rengi, ön eleme) ve `kaynak` (slaytta görünen ad).

**1l. ⚠️ GECE OTOMATİK YAYIN PRATİKTE HİÇ ÇALIŞMIYOR — eşik ulaşılamaz.**

Kullanıcı bildirdi (19 Ağu 2026): "gece hiç yayınlanmıyor haber".
Özellik açık (`genel.gece_otomatik_yayin: true`), cron'lar gece
düzenli çalışıyor, dört katman da sağlam — ama yayın çıkmıyor.

Ölçüldü, sebep tek: **gece eşiği 9 ve hiçbir haber 9 almıyor.**

| saat (TR) | eşik | sonuç |
|---|---|---|
| 23:33 · 01:33 · 04:47 · 06:05 | 9 (gece) | dördünde de "haber yok" |
| 07:46 · 08:40 | 8 (gündüz) | ikisinde de hemen onaya sunuldu |

Son 24 saatte **11 haber 8+ aldı, 9 alan SIFIR**. Sabah eşik 8'e
düşer düşmez haber bulunuyor — yani havuz dolu, kapı kapalı.

⚠️ Bu, "★ Önem puanı" satırındaki kalibrasyon sorununun ikinci yüzü:
prompt siyasi ölçeğe kalibre olduğu için 9 neredeyse hiç verilmiyor
ve 9'a bağlı HER ŞEY sessizce ölüyor — gece yayını da,
`son_dakika_etiket_esigi` (SON DAKİKA ibaresi) de.

Dört katman ayrıca ÖLÇÜLDÜ ve gerçekten ayıklıyor: 6 adayın 3'ü
geçti, 3'ü reddedildi (1 riskli kategori, 2 çapraz denetim). Yani
eşiği düşürmek "kontrolsüz yayın" demek değil, asıl süzgeç katmanlar.

**Karar (19 Ağu):** eşik 9'da BIRAKILDI. Önce yeni önem promptunun
puan dağılımını yükseltip yükseltmediği ölçülecek; 9 gerçekten
ulaşılabilir hale geldiyse eşiğe hiç dokunulmayacak. Yükselmezse
eşik 8'e indirilecek.

**1m. ⚠️ KATEGORİ BESLEMELERİ SON DAKİKA FİLTRESİNE TAKILIP YOK
OLUYORDU — spor ve kültür veritabanında hiç oluşmadı.**

19 Ağu 2026, kullanıcı "haber çeşitliliği ne durumda" diye sorunca
ölçüldü: **AA Kültür ve AA Spor 3 GÜNDE SIFIR haber yazmıştı.** Oysa
ikisi de sağlıklı çalışıyor ve 30'ar haber veriyor (URL testi temiz).

Zincir:
1. `son_dakika_asgari_agirlik: 9` filtresi ağırlığı 8 olan AA Kültür
   ve AA Spor'u eliyordu.
2. Ama AA'nın **genel akışının** ağırlığı 9 ve o geçiyordu.
3. Genel akış aynı haberleri `turkiye` etiketiyle ÖNCE kaydediyor.
4. `haberler.link` UNIQUE → kategori beslemesi sonradan geldiğinde
   "tekrar" sayılıp eleniyor.
5. Kontrol günde 20 kez, tur günde 2 kez çalıştığı için genel akış
   **her zaman** önce davranıyordu.

Sonuç: kategori bazlı ön eleme spor/kültüre yer ayırsa bile ortada
haber yoktu. Çeşitlilik sorununun asıl sebebi buydu — kaynak listesi
değil, çekme sırası.

Düzeltme (`fetch_news.haberleri_cek`): ağırlık filtresi artık yalnızca
**gündem akışlarına** tam uygulanıyor; kategori beslemeleri daha düşük
bir eşikle (`KATEGORI_ASGARI_AGIRLIK = 7`) taranıyor. Dünya kategorisi
zaten TRT/AA ile temsil edildiği için ağırlığı 4-5 olan akışlar
(BBC World, Al Jazeera) yine saat başı taranmıyor.

⚠️ 1h dersi burada da uygulandı: **eski KAYITLAR da düzeltildi.**
Yanlış etiketlenmiş 81 haber (58 spor + 23 kültür) link segmentine
bakılarak doğru kaynak/kategoriye taşındı.

Ölçüldü (son 3 gün): **spor 50 → 100, kultur 0 → 21.**

**1r. ⚠️ TELEGRAM AKIŞI DERİN İNCELEME (20 Ağu 2026) — dört kusur.**

Kullanıcı "sürekli Telegram'da hata alıyoruz, çok yavaş" deyince
uçtan uca ölçüldü. Başarı oranı 34/40 idi; kalan 6 hatanın hepsi
aşağıdaki dört sebepten geliyordu.

**(a) `NameError: name 'oneri_esigi' is not defined`** — fonksiyon bir
düzenleme sırasında silinmiş, çağrısı kalmıştı. Son dakika kontrolü
HER çalıştığında patlıyordu.

⚠️ **Bütünlük testi bunu göremedi**: yalnızca `modul.fonksiyon()`
biçimindeki çağrıları denetliyordu, düz `fonksiyon()` çağrıları
kapsam dışıydı. Kod sözdizimi açısından geçerliydi, test TEMİZ
geçiyordu. `test_0_butunluk.tanimsiz_isimleri_bul()` eklendi — aynı
dosyada çağrılan ama hiçbir yerde tanımlanmayan isimleri yakalıyor.
Doğrulandı: fonksiyon kasten silinince test hatayı buluyor.

**(b) Hata düğmesi yanlış hedefi vuruyordu.** `hata_bildir`'de
yalnızca `tur_tekrar` ve `tur_metinsiz` vardı, ikisi de AKŞAM TURUNU
kuruyordu. Kullanıcı "Son dakika turu hazırlanamadı" mesajındaki
"🔄 Turu yeniden hazırla"ya bastı ve 10 slaytlık akşam turu geldi.
Artık `_butonlar()` hatanın geldiği yere (`nerede`) bakıyor;
son dakika hatalarında `hata:sondakika_tekrar` → `son_dakika_calistir`
event'i, `son-dakika.yml` bunu dinliyor.

**(c) Yavaşlığın sebebi kuyruk değil, ÖLÜ KAPIYI ÇALMAK.** Ölçüldü:
tur 13 dakika sürüyor ve %92'si metin üretiminde. Kuyrukta bekleme
yalnızca 4-58 saniye. Gerçek sebep: ücretsiz kota günde 20 istek,
tur 25 adaya metin üretiyor. Kota bitince her haber aynı tükenmiş
model/anahtarı 3 kez deniyordu (2+4+6 sn), yani haber başına ~12
saniye saf bekleme. `generate_text._TUKENMIS` kümesi eklendi: günlük
kota hatası veren (model, anahtar) ikilisi aynı süreçte bir daha
denenmiyor. Kazanım: 25 adaylık turda 20 dk → 0.4 dk boşa bekleme.

**(d)** Mükerrer yayın — bkz. 1p.

**1p. ⚠️ TURDA YAYINLANAN HABER BİR SAAT SONRA TEKİL POST OLARAK ÇIKTI.**

20 Ağu 2026, kullanıcı bildirdi. Aynı olay iki gönderi:
* 05:55 (tur) — "Rusya'nın Kiev ve Jitomir'e füzeli saldırısında en
  az 10 kişi hayatını kaybetti"
* 06:56 (tekil) — "Rus ordusu Kiev'i füzelerle vurdu: En az 8 kişi
  hayatını kaybetti"

Kural doğru çalışsaydı elerdi (4 ortak kelime + ortak özel isim
"kiev"). Sorun kuralın kendisinde değil, **nerede uygulandığındaydı**:
`secim.yayinlanmis_konular()` denetimi `onerileri_gonder` ve
`secim.tur_icin_sec` içinde vardı ama **`aday_bul`'da YOKTU**. Metni
hazır bir haber, turda yayınlanan olayın benzeri olsa bile tekil post
adayı olabiliyordu.

⚠️ Bu, 1j'deki dersin tekrarı: *bir düzeltmeyi uygularken aynı işi
yapan DİĞER kod yolunu da ara.* Mükerrer engeli üç yerde gerekiyordu,
ikisine konmuştu.

Ölçüldü: denetim aşırı değil — son 24 saatte metni hazır 78 haberin
yalnızca 6'sı (%8) eleniyor ve elenenler gerçekten daha önce
yayınlanmış konuların varyasyonları.

**1o. ⚠️ "database is locked" — BAĞLANTI KAPATILMIYORDU.**

20 Ağu 2026, kullanıcı bildirdi: "2 tanesini seçtim, birini oluşturdu
ama birini oluşturamadı". Çoklu seçimde ilk haber üretiliyor, ikincisi
`sqlite3.OperationalError: database is locked` ile düşüyordu.

Kök sebep: `son_dakika.main()` bir bağlantı açıyor ama **hiç
kapatmıyordu**. Tek çalıştırmada zararsız (süreç bitince kapanır), ama
`onay_isle` çoklu seçimde bu fonksiyonu ARKA ARKAYA çağırıyor —
birinci çağrının bağlantısı hâlâ açıkken ikincisi yeni bağlantı açıp
yazmaya çalışıyor ve kilide takılıyor.

⚠️ **WAL modu tek başına YETMİYOR.** İlk denemede `journal_mode=WAL`
açıldı ve hata devam etti. Ölçüldü: WAL okuyucu-yazar eşzamanlılığını
çözüyor, **İKİ YAZARI değil**. Commit edilmemiş bir yazma işlemi
WAL'da da tüm veritabanını kilitliyor.

Üç katman birlikte gerekiyor:
1. `finally: con.close()` — asıl düzeltme
2. `onay_isle` her üretimden önce `con.commit()` (kilidi bırakır)
3. `journal_mode=WAL` + `busy_timeout=30000` (okuma/yazma çakışmasına)

⚠️ WAL modu DOSYADA saklanıyor, `PRAGMA` ile her açılışta ayarlamak
yetmiyor: başka bağlantı açıkken WAL'a geçiş özel kilit isteyip
başarısız oluyor ve veritabanı sessizce `delete` modunda kalıyor.
Bu yüzden `data/haber.db` WAL modunda commit edildi.

⚠️ WAL yan etkisi: yazılanlar önce `haber.db-wal` dosyasına gidiyor,
git'e yalnızca `haber.db` commit ediliyor. `db_senkron._wal_bosalt()`
commit öncesi checkpoint alıyor — alınmasaydı o turda yazılan HER ŞEY
kaybolurdu.

**1n. ⚠️ TEKİL POST 5 SAAT BOYUNCA HİÇ ÇIKMADI — havuz doluydu, hepsi
"bayat" sayılıyordu.**

19 Ağu 2026, kullanıcı bildirdi: "gün içinde attığımız tekli haber
sayısı azaldı, 5-6 saattir atmıyoruz". Bugün 7 tekil post çıkmıştı
(limit 10), sonuncusu TR 17:50'de.

Eleme zinciri ölçüldü:

| aşama | adet |
|---|---|
| metni hazır, henüz tekil olmamış | 228 |
| ⛔ 3 saatten eski (bayat) | **224** |
| ⛔ puan eşiğini geçemedi | 4 |
| ✓ aday | **0** |

Yani sorun eşik ya da kategori limiti DEĞİLDİ — hazır metinlerin
%98'i tazelik filtresine takılıyordu. Aynı anda son 3 saatte gelen
**44 haberin metni hiç üretilmemişti.**

Kök sebep: kontrol job'ı metin üretecek haberi `secim.on_eleme` ile
seçiyordu. `on_eleme` "en İYİ haberi" seçiyor (kaynak ağırlığı +
kategori katsayısı + içerik sinyali); son dakika için gereken ise
"en TAZE haber". İkisi farklı soru. on_eleme havuzdaki eski ama
yüksek skorlu haberleri seçip duruyordu, onlar da zaten bayat
oldukları için aday olamıyordu — kısır döngü.

Düzeltme (`son_dakika.taze_adaylar`): kontrol job'ı artık doğrudan
tazelik sorguluyor — son `son_dakika_tazelik_saat` içinde yayınlanmış,
metni üretilmemiş haberler, kaynak ağırlığına göre sıralı.

Ayrıca `TAZELIK_SAAT` sabit 3'tü ve config'den okunmuyordu; artık
`son_dakika_tazelik_saat: 5` ile ayarlanıyor, ek metin adedi 3→4.

**1s. ⚠️ AYNI HABER TEKRAR TEKRAR TEKİL POST OLARAK SUNULUYORDU.**

20 Ağu 2026, kullanıcı bildirdi: "Türkiye'de yağışlar son 66 yılın
zirvesinde" haberi **23 dakika arayla iki kez** onaya düştü
(mesaj 404 ve 410).

Sebep tasarımdaydı: "Bu turu atla" haberi havuza döndürüyor
(`durum='metin_hazir'`, `son_dakika=0`) ve haber bir sonraki
kontrolde YİNE tekil aday oluyordu. "Onay verilmezse haber ELENMEZ"
kararı doğru — ama tekil post olarak ısrar etmek yanlış.

Çözüm: **`sadece_tur` kolonu + yeni düğme.** Onay menüsünde
"📋 Tekil atma, 10'lu tura bırak" haberi tekil adaylıktan çıkarıyor
ama havuzda bırakıyor; carousel turunda yarışmaya devam ediyor.
`aday_bul` ve öneri havuzu bu işareti filtreliyor.

**1t. ⚠️ `--kuru` VERİTABANINA YAZIYORDU — havuzu tüketiyordu.**

`onerileri_gonder` toplu puanları kuru modda da DB'ye yazıyordu.
`--kuru`nun sözleşmesi net: *üretir, Telegram'a göndermez,
veritabanına yazmaz*. 20 Ağu'daki yapısal çalışmanın kuru testleri
**82 haberi** öneri havuzundan düşürdü.

Artık kuru modda puanlar yalnızca bellekte taşınıyor (`dict(h,
onem_puani=...)`), eleme yine gerçek puanlarla yapılıyor ama kalıcı
iz bırakmıyor.

⚠️ Ayrıca öneri havuzu filtresinde `onem_puani IS NULL` şartı vardı
ve bir haberi **bir kez puanlamak onu havuzdan düşürüyordu**. Puanın
varlığı haberin değerlendirilmiş olduğunu göstermez —
`oneri_gonderildi` işareti onu gösterir. Filtre düzeltildi ve kota
israfı da önlendi: artık yalnızca puansız başlıklara Gemini çağrısı
yapılıyor.

**1u. ⚠️ YAYINLANMIŞ TUR ÜZERİNDE İŞLEM YAPILABİLİYORDU — bot postu
yayınladığını UNUTUYORDU.**

20 Ağu 2026, kullanıcı "o haber Instagram'da paylaşılmış" diye ısrar
etti; veritabanı `durum='metin_hazir'` diyordu. Instagram API'ye
sorulunca haklı çıktı: post 10:00:23'te yayınlanmıştı
(instagram.com/p/DcQf4w1nJA7).

Zincir:
1. 09:59 — tur başarıyla yayınlandı: Instagram + Facebook + story +
   Threads 4/4, veritabanı yazıldı ve **push edildi** (log doğruladı).
2. 10:00 — aynı onay mesajından `ertele` komutu geldi ve
   **YAYINLANMIŞ haberin durumunu `ertelendi` yaptı.**
3. Haber havuza döndü; sistem onu "yayınlanmamış" sandı.
4. 11:33 ve 11:56 — aynı haber iki kez daha tekil post olarak onaya
   sunuldu. Kullanıcının bildirdiği mükerrer sunumun kök sebebi buydu.

`turu_getir` durum filtresi yapmıyor ve hiçbir komut "bu tur zaten
yayınlandı mı" diye bakmıyordu.

Düzeltme: değiştirici komutlar (`yayinla`, `iptal`, `ertele`,
`tura_birak`, `metin_yenile`, `slayt_*`) yayınlanmış turda
**reddediliyor** ve kullanıcıya post bağlantısı gösteriliyor.
`kaldir` hariç — o zaten yayınlanmış turu hedefliyor.

⚠️ Bu aynı zamanda **ÇİFT YAYIN** riskini de kapatıyor: "Yayınla" iki
kez basılırsa ikincisi reddediliyor.

⚠️ **DERS: veritabanı gerçeğin tek kaynağı değil.** Bot Instagram'a
yayın yapıyor ama kayıt sonradan bozulabiliyor. "Yayınlandı mı?"
sorusunun kesin cevabı Instagram API'sinde:
`GET /{ig_user_id}/media?fields=id,caption,timestamp`.

**1z. ⚠️ MÜKERRER ENGELİ VERİTABANINA GÜVENİYORDU — Instagram'da
yayınlanmış haber akşam turuna geri girdi.**

20 Ağu 2026, kullanıcı bildirdi: "gündüz tekli attıklarımızdan var
10'lu tur arasında". Ölçüldü ve haklı çıktı — Instagram'da
**TR 17:47 "Merkez Bankası rezervleri"**, **TR 17:19 "TUFAN Kamikaze
İDA"** yayınlanmıştı ve ikisi de 20:58 turunda yeniden vardı.

Kök sebep kuralın kendisi DEĞİL: aynı turdaki **Endonezya depremi
YAKALANDI** çünkü onun kaydı veritabanında doğru şekilde
`durum='yayinlandi'` idi. Diğer ikisinde DB'de HİÇBİR kayıt
'yayinlandi' değildi — yayın gerçekleşmiş ama kayıt bozulmuştu
(1u'daki olayın aynısı). Yani **kural sağlamdı, beslendiği veri
eksikti.**

Düzeltme: `secim.yayinlanmis_konular` artık DB'ye ek olarak
`instagram.son_yayinlanan_basliklar()` çağırıyor — caption'lardaki
manşetler de geçmiş sayılıyor. İmza sayısı 55 → 120 oldu, elenme
oranı **%13.3'te sabit kaldı** (aşırı eleme yok), üç mükerrer de
yakalandı. Instagram'a ulaşılamazsa denetim DB ile devam ediyor,
tur durmuyor.

⚠️ **Caption ayrıştırması POST BAZINDA olmalı.** İlk yazımda
"numarasız caption'ın ilk satırı manşettir" kuralı GLOBAL listeye
bakıyordu; ilk posttan sonra liste hep dolu olduğu için tekil
postların manşetleri HİÇ okunmadı ve düzeltme sessizce çalışmadı.

⚠️ **Sözleşme testi bu yüzden ağa çıkmaya başladı.** `main()` artık
`secim._IG_GECMIS_ONBELLEK = []` ile API yolunu kapatıyor — test
0.14 saniyede bitiyor ve jeton olmadan da çalışıyor.

**1y2. ⚠️ "1 SAAT ERTELE" TURU KİLİTLİYORDU.**

20 Ağu 2026: kullanıcı 20:58'de erteledi, 21:58'de hatırlatma geldi
("Yukarıdaki mesajdan yayınlayabilirsin") ama o mesajda **hiçbir
düğme kalmamıştı.** Tur ne yayınlanabiliyor ne atlanabiliyordu.

Sebep: `ertele()` sonucu `telegram_bot.sonucu_yaz()` ile yazıyordu ve
o fonksiyon **butonları bilerek kaldırıyor** (çift yayını engellemek
için, yayın/iptal gibi turu BİTİREN işlemlerde doğru davranış). Ama
erteleme turu bitirmiyor.

Düzeltme: `ertele()` artık `menuyu_geri_koy()` çağırıyor ve ertelemeyi
ayrı bir mesajla bildiriyor. Sözleşme testi `telegram_bot.sonucu_yaz(`
çağrısını denetliyor — ⚠️ düz metin araması yanlış alarm veriyordu,
çünkü fonksiyonun docstring'inde "sonucu_yaz KULLANMA" uyarısı yazılı.

**1z2. ⚠️ TÜRKÇE EKLER MÜKERRER DENETİMİNİ DELİYOR + gündüz
yayınlanan haber turda EN SONA.**

20 Ağu 2026, gece kurulan turda iki ayrı sorun çıktı.

**(a) Aynı PFDK kararının iki haberi tek tura girdi.**
`"…kulübe para CEZASI verdi"` ve `"…kulüplere CEZA"` — düz küme
kesişimi bunları farklı kelime saydı, ortak kelime yalnızca "pfdk"
(1) çıktı ve eşik 2'ydi. Türkçe sondan eklemeli; `kelimeler1 &
kelimeler2` bu dilde zayıf kalıyor.

Çözüm `secim._ayni_kok` + `secim.ortak_kelime`: ortak önek, kısa
kelimenin **%80'i ve en az 4 harf** ise aynı kabul ediliyor. Stemming
kütüphanesi EKLENMEDİ — bu iş için gereğinden ağır.
Ölçüldü: elenme oranı **%14.7 → %15.5** (+1 haber), "ankara/antalya"
ve "istanbul/izmir" eşleşmiyor. `aday.uygun_mu` iki denetimde de
(liste içi + geçmiş) buna geçti.

**(b) Gündüz tekil atılan haber turun BAŞINDA çıkıyordu.**
9+ puanlı haberler geçmiş denetiminden muaf (`gecmis_muafiyet_puani`)
ve bu kullanıcının kendi isteğiydi: *"9 üzerindeyse akşam özetinde
olabilir yine"*. Ama muafiyetle giren haber `onem_puani DESC`
sıralamasında ilk slayt oluyordu.

Kullanıcı kararı: **"kalsın havuzda ama gündüz yayınlandıysa en son
sırada olsun"**. `daha_once_yayinlandi` kolonu eklendi;
`tur_icin_sec` seçim sonrası işaretliyor ve sona sıralıyor,
`onay_isle.turu_getir` aynı sıralamayı kullanıyor.
⚠️ **İKİ SIRALAMA AYNI OLMALI** — biri değişirse slayt sırası ile
caption'daki manşet sırası birbirini tutmaz.

⚠️ **SLAYT NUMARASI KIRILGAN.** Sıra değişince "slayt 9" başka bir
haberi işaret ediyor; gönderilmiş bir alternatif mesajı yanlış slaytı
değiştirir. Sıralamayı değiştiren bir işlemden sonra açık alternatif
mesajları geçersizdir. Kalıcı çözüm düğmelere slayt numarası yerine
haber id'si gömmek — **henüz yapılmadı.**

**1v. ⚠️ PARAMETRELİ KOMUTLARDA ÖN EKE BAKILMALI.**

`/haber istanbulda hava` komutu `ara:istanbulda hava` olarak geliyor
ama `MESAJSIZ_KOMUTLAR` düz üyelik testi yapıyordu (`"ara"` listede mi).
Eşleşme tutmadığı için komut "MESAJ_ID eksik" ile ölüyordu — Worker
"aranıyor…" diyor, job sessizce hata veriyordu. Aynı desen `/durum`
için de yaşanmıştı. Artık `komut.split(":", 1)[0]` ile ön eke
bakılıyor.

**1y. İki kez atlanan haber tekil olarak dayatılmıyor.**

"Bu turu atla" haberi havuza döndürüyor ve haber bir sonraki
kontrolde yine tekil aday oluyordu. `iptal()` artık
`ertelenme_sayisi` sayacını artırıyor; **iki atlamadan sonra**
`sadece_tur = 1` konuyor, yani haber yalnızca 10'lu turda yarışıyor.
Haber kaybolmuyor, sadece tekil post olarak ısrar edilmiyor.

### Geçmiş notlar (güncelleme: 14 Ağustos 2026)

**Adım 1 BİTTİ ve kullanıcının makinesinde doğrulandı.** 8/8 kaynak çalışıyor,
tekrar engeli teyit edildi (2. çalıştırmada 0 yeni, 99 tekrar).

Yol boyunca çözülenler:
- **PyYAML 6.0.2 → 6.0.3.** Kullanıcı Python 3.14 kurdu; 6.0.2'nin 3.14 için
  hazır paketi yok, pip derlemeye kalkıp "Visual C++ gerekiyor" hatası verdi.
- **TRT Haber ayrıştırma hatası.** Feed kendini `encoding="UTF-8"` ilan edip
  içine UTF-8 olmayan bayt karıştırıyor (TRT'nin kendi hatası). Tek karakter
  yüzünden 15 haberin tamamı kayboluyordu. `_bozuk_baytlari_onar()` eklendi —
  **sadece normal ayrıştırma patladığında** devreye giriyor, yani çalışan
  kaynaklara dokunma riski yok. Doğrulandı: 15/15 başlıkta Türkçe karakterler
  sağlam, 0 bozuk karakter.
- Zararsız `MarkupResemblesLocatorWarning` susturuldu (log gürültüsüydü).

### Cloudflare / veri merkezi IP ölçümü — ÖLÇÜLDÜ, SORUN YOK ✅

| Ortam | IP | Sonuç |
|---|---|---|
| Ev (TurkNet, İstanbul) | 95.70.229.210 | 8/8 `200 ok` |
| GitHub runner (Azure, Phoenix US) | 20.168.119.242 | **8/8 `200 ok`** |

Hiçbir kaynak veri merkezi IP'sini engellemiyor. `config.yaml`'de kaynak
kapatmaya veya alternatif aramaya gerek kalmadı. En yavaş kaynak Anadolu
Ajansı (3.5 sn) — 15 sn'lik zaman aşımının çok altında.

**Ama tek ölçüm = garanti değil.** Bu tek bir anda, GitHub'ın IP havuzundaki
tek bir adresten alındı. Cloudflare engeli aralıklı olabilir ve başka bir
runner IP'si farklı davranabilir. İyi haber: kaynak izolasyonu zaten test
edilmiş — bir kaynak patlarsa diğerleri etkilenmiyor, yani risk "bot çöker"
değil "o turda bir kaynak eksik olur". Yayına geçince ara ara
`data/kaynak-erisim-raporu.txt`'ye bakmakta fayda var.

Araçlar: `scripts/test_kaynak_erisim.py` (DB'ye dokunmaz) +
`.github/workflows/test-kaynak-erisim.yml`. Workflow raporu
`data/kaynak-erisim-raporu.txt` olarak repo'ya geri commit ediyor —
Adım 6'daki veritabanı commit deseninin çalışan provası bu.

### GitHub durumu

- Repo: `https://github.com/ozdogangringo-sketch/haber-bot` (**private**, doğrulandı)
- `main` dalı push edildi, Actions çalışıyor ve repo'ya yazabiliyor.
- Actions ücretsiz kotası private repo'da 2000 dk/ay. Planlanan cron'lar
  (günde 2 hazırlama + 7 hatırlatma) kabaca 450-600 dk/ay → sınırın altında.

### Adım 2 — BİTTİ ✅ (14 Ağu 2026)

`GEMINI_API_KEY` alındı, `.env`'de duruyor, çalışıyor. Gemini API'nin Google
Cloud projesinde ayrıca "Enable" edilmesi gerekti — anahtar tek başına yetmedi.

Uçtan uca test: 3/3 haber başarılı, üçü de tam makale metniyle,
üretilen her iddia kaynak metinde doğrulandı. Detay için Bölüm 7'ye bak.

### Adım 3 — Görsel: BÜYÜK ÖLÇÜDE ÇALIŞIYOR, birleştirme kaldı

Yapıldı ve doğrulandı:
- `assets/fonts/Inter-Variable.ttf` (Türkçe karakterler gerçek render ile test edildi)
- `src/make_image.py` — başlık yerleşimi, otomatik satır kırma/punto, okuma perdesi,
  AI soyut arka plan, bedava gradyan yedeği, **günlük maliyet sayacı**
- `src/fetch_photo.py` — Wikimedia Commons'tan lisansı uygun fotoğraf

**Commons hakkında öğrenilenler (tekrar keşfetme):**
- KİŞİ/KURUM aramaları iyi: Trump → Ocak 2025 resmi başkanlık portresi (kamu malı).
  OLAY aramaları kullanılamaz: "Istanbul earthquake" → 1509 gravürü. Bu yüzden
  sadece kişi/kurum araması yapılıyor.
- "Lisansı uygun ilk sonuç" almak YETMİYOR — ilk denemede Trump için lise yıllığı
  fotoğrafı geldi. `_aday_puani()` ile puanlama şart (istenmeyen kelime listesi,
  yıl tercihi, çözünürlük, en-boy oranı).
- Wikimedia iletişim bilgisi içeren User-Agent istiyor + istekler arası bekleme
  şart, yoksa 429. `_istek()` bunu hallediyor.
- Lisans etiketlerine körlemesine güvenme: yıllık fotoğrafı "kamu malı" etiketliydi
  ama ticari bir arşive atıf veriyordu. NC/ND elenmesi `_lisans_uygun_mu()`'da.
- Tanınmayan kişilerde (ör. sıradan bir milletvekili) fotoğraf bulunmuyor →
  gradyana düşmek DOĞRU davranış, zorlama.

### 15 Ağustos 2026 — macOS'a taşındı, görsel katmanı genişletildi

**Ortam:** Proje Windows'tan MacBook'a taşındı (`/Users/macbook/Dogukan/instabot`).
Zip iç içe açıldığı için klasör `instabot/haber-bot/haber-bot/` olmuştu, kök dizine
düzleştirildi. Windows'ta üretilmiş `.venv` (içinde `Scripts\`) macOS'ta çalışmıyordu,
silinip yeniden kuruldu. Python 3.14.7, 12 paketin hepsi hazır tekerlekle geldi.

Taşıma sonrası doğrulandı: RSS 8/8, makale gövdesi 16/16, Gemini iki anahtar da
geçerli, Instagram jetonu sağlam (@dailybrief.co, kota 0/100), font Türkçe render.

**YENİ: Pexels katmanı** (`src/fetch_stock.py`)

Commons sadece kişi/kurum aramalarında iyi; "Ankara'da zam" gibi haberlerde
gradyandan başka seçenek yoktu. Pexels temsili fotoğraf sağlıyor: ticari kullanıma
açık, atıf zorunlu değil, anahtar bedava, kota 25.000 istek/saat (bize günde ~9).

**PEXELS ARAMA KURALI — ölçüldü, prompt'a yazıldı:**
Geniş mekân fotoğrafları hep bir ülkeye ait ve tabelaları yabancı dilde çıkıyor.
Türkiye haberinde İspanyolca hastane tabelası özensiz görünüyor.
```
KÖTÜ "hospital corridor" -> İspanyolca tabelalar (Camas, SALIDA)
KÖTÜ "city bus stop"     -> Kiril alfabeli tabelalar
KÖTÜ "courthouse"        -> Latince kitabe (DOMVS IVSTITIAE)
İYİ  "stethoscope close up", "turkish lira coins close up", "judge gavel close up"
İYİ  doğa/doku sahneleri ("dry cracked earth") — coğrafi olarak nötr
```
Kural: **yakın plan nesne iste, geniş mekân isteme.** İnsan yüzü de isteme.

**Görsel tasarımında düzeltilenler:**
- **Perde artık arka plana göre ayarlanıyor** (`_perde_taban_alfa`). Eskiden sabit
  bir orandan (%30) başlayıp karesel artıyordu; başlığın üst satırları perdenin
  şeffaf bölgesine denk geldiği için açık bir fotoğrafta yazı eriyordu. Artık önce
  yazının yeri ölçülüyor, perde ona göre çiziliyor. Ölçüm: gradyanın yazı bölgesi
  parlaklığı ~43 (perde çizilmiyor, bant bırakıyordu), açık portre ~123.
- **Türkçe büyük harf** (`_buyuk_harf`). Python'un `.upper()` metodu "Türkiye"yi
  "TÜRKIYE" yapıyordu. Bir haber hesabında bu hata kötü görünür.
- Geçiş payı sabit değil: perde koyulaştıkça uzuyor (`190 + taban`), yoksa açık
  zeminde düz siyah blok gibi başlıyordu.

### Adım 3 — BİTTİ ✅ (15 Ağu 2026)

Klasör düzleştirildi: proje artık `/Users/macbook/Dogukan/instabot` **kökünde**
(zip iç içe açıldığı için `instabot/haber-bot/haber-bot/` olmuştu; CLAUDE.md
otomatik yüklenmiyordu). Windows'ta üretilmiş `.venv` silinip yeniden kuruldu.

Uçtan uca doğrulandı: 10 haber → metin → 10 slayt → caption. Görsel maliyeti $0.

**Yazılan/tamamlanan modüller:**
- `src/slaytlar.py` — katman seçici + tur üretici (`tur_uret`, `arkaplan_sec`)
- `src/caption.py` — carousel'in tek açıklaması (2200 karakter / 30 hashtag yönetimi)
- `src/secim.py` — iki aşamalı haber seçimi
- `src/filtre.py` — Instagram shadowban kelime/etiket filtresi
- `src/fetch_stock.py` — Pexels katmanı
- `src/fetch_flag.py` — ülke + kuruluş bayrakları
- `scripts/test_6_tur_gorsel.py` — bir turun tamamını üretir, maliyeti sıfır
- `scripts/anahtar_ekle.py` — `.env`'e anahtar ekler (getpass; terminal
  geçmişine sızmaz). `.env` gizli dosya olduğu için kullanıcı Finder'da bulamıyordu.

**COMMONS'IN YANLIŞ FOTOĞRAF SORUNU — dört katmanlı çözüm, hiçbirini kaldırma:**

İlk turda 6 Commons görselinin en az 3'ü yayınlanamazdı (Macar sanatçı portresi,
askeri harita, kale manzarası). Kök sebep: `gorsel_konu`ya kurum adı yazılması.

1. **Prompt:** `gorsel_konu` yalnızca kişi adı-soyadı. En etkili katman bu.
2. **Kısaltma engeli** (`fetch_photo.fotograf_ara`): tek kelimelik ve tamamı
   büyük harf olan konu Commons'a hiç sorulmuyor (İSKİ, TRT, ECOWAS).
3. **Soyadı doğrulaması** (`_isim_tutuyor_mu`): iki+ kelimelik aramada soyadı
   dosya adında geçmeli.
4. **Şema/harita elemesi** (`ISTENMEYEN`): "situation on", "government of",
   "org chart" vb. `map` kelimesi geçmeyen harita/şemaları da yakalar.

⚠️ **TÜRKÇE KARAKTER TUZAĞI:** Soyadı doğrulaması ilk hâlinde DOĞRU portreleri
eliyordu — Commons dosya adları Latin harfle yazılıyor ("Erdoğan" dosyada
"Erdogan", "Gürlek" → "Gurlek"). `_sadelestir()` bunu çözüyor. Bu fonksiyona
dokunursan Commons katmanı sessizce hiç çalışmaz hâle gelir.

**Katman dağılımı (10 haberlik gerçek tur):** 1 Commons, 9 Pexels, 0 gradyan.
Pexels'in baskın olması beklenen — günlük haberlerin çoğunda merkezde
tanınmış bir isim yok.

### Adım 4, 5, 6, 7 — BİTTİ ✅ (15 Ağu 2026)

**Adım 4a (imgbb):** 10 görsel 10.8 saniyede yükleniyor, hepsi public
`image/jpeg`. `hepsini_yukle()` biri patlarsa tamamını iptal ediyor —
eksik slaytla post atmak hiç atmamaktan kötü.

**Adım 4b (Instagram):** `src/instagram.py`. Hesap doğrulaması ve kota
okuması gerçek API'yle test edildi (@dailybrief.co, 0/100). Yanlış hesap
koruması da test edildi: `edmyapi` yazılınca yayını reddediyor.
⚠️ **GET'te parametreler query string'e gider.** Gövdede gönderilince
Graph API onları hiç okumuyor ve `(#200) Provide valid app ID` gibi
tamamen alakasız bir hata veriyor — bu hatayı bir kez ayıkladık.

**Adım 5 (Telegram + Worker):**
- Worker canlı: `https://haber-bot-onay.ezanplus.workers.dev`
- Webhook kurulu, yalnızca `callback_query` iletiliyor
- Güvenlik test edildi: parolasız/yanlış parolalı istek 401, geçersiz
  komut GitHub'a geçmiyor (`slayt_ai:99`, `../../etc` reddedildi)
- Cloudflare hesabı: ozdogandogukan@gmail.com

**Adım 6 (Actions):** 5 workflow aktif — `hazirla.yml` (TR 20:07),
`hatirlat.yml` (TR 21:07/22:07/23:07), `yayinla.yml` (repository_dispatch),
`jeton-yenile.yml` (pazartesi TR 12:07), `test-kaynak-erisim.yml`.
10 secret eklendi.

**Adım 7 (jeton) — SÜRESİZ SAYFA JETONUNA GEÇİLDİ ✅**

⚠️ **USER JETONUNA GERİ DÖNME.** 15 Ağu 2026'da ölçüldü: uzun ömürlü
USER jetonunu `fb_exchange_token` ile yeniden takas etmek **yeni bir 60
gün VERMİYOR**. Jeton değişiyor (farklı değer) ama `expires_at` aynı
kalıyor — süre orijinal girişe bağlı. Otomatik yenileme kurulmuş olsa
bile bot Ekim'de duracaktı. Bu test edilmeseydi anlaşılmazdı.

Çözüm: `/me/accounts` ile alınan **SAYFA jetonu süresiz**
(`expires_at = 0`) ve `instagram_content_publish` dahil tüm izinleri
taşıyor. Yayın için çalıştığı doğrulandı (hesap + kota, ikisi de 200).
`.env` ve GitHub Secrets'taki `IG_ACCESS_TOKEN` artık bu.

Sayfa jetonu yine de ölebilir: Facebook parolası değişirse, uygulama
izni geri çekilirse, sayfa yöneticiliği kalkarsa. Haftalık kontrol bu
yüzden duruyor — yenilemek için değil, öldüğünü ERKEN haber vermek için.

PAT'e `Secrets: write` izni verildi (403 → 200 doğrulandı), yani jeton
bir gün süreli hale gelirse otomatik yazma da çalışır.

⚠️ Secret adı `REPO_PAT`, `GITHUB_PAT` DEĞİL: GitHub `GITHUB_` ile
başlayan secret adlarını rezerve tutuyor ve 422 ile reddediyor.

### Referans: Adım 4 — imgbb + Instagram CAROUSEL akışı

Carousel akışı tekli posttan farklı: her görsel için `is_carousel_item=true`
container → sonra `media_type=CAROUSEL` + `children=[id1,id2,...]` → publish.

---

## 5. Mevcut dosyalar

```
haber-bot/
├── CLAUDE.md                      # bu dosya
├── config.yaml                    # RSS listesi + ayarlar (key YOK, git'e girer)
├── requirements.txt               # requests, PyYAML, bs4, python-dateutil, python-dotenv
├── .env.example                   # doldurulacak key şablonu
├── .gitignore                     # .env, __pycache__, data/output/, logs/
│                                  #   NOT: data/haber.db BİLEREK ignore edilmedi
├── .github/workflows/
│   └── test-kaynak-erisim.yml     # ✅ elle tetiklenir (workflow_dispatch)
├── worker/                        # ✅ Cloudflare Worker (Adım 5)
│   ├── index.js                   #   buton + /komut → GitHub dispatch
│   ├── wrangler.toml              #   secret YOK, git'e girer
│   └── KURULUM.md                 #   sıfırdan kurulum adımları
├── src/
│   ├── db.py                      # ✅ 31 kolon, otomatik migration
│   ├── dogrula.py                 # ✅ DOĞRULUK DENETİMİ (aşağıda anlatıldı)
│   ├── instagram.py               # ✅ carousel yayınlama + hesap koruması
│   ├── telegram_bot.py            # ✅ onay mesajı, özet tablo, menüler
│   ├── refresh_token.py           # ✅ jeton ömrü (artık süresiz sayfa jetonu)
│   ├── fetch_news.py              # ✅ RSS/Atom
│   ├── fetch_article.py           # ✅ makale gövdesi çekici (Adım 2'nin kalbi)
│   ├── generate_text.py           # ✅ Gemini ile IG metni + görsel alanları
│   ├── secim.py                   # ✅ iki aşamalı haber seçimi
│   ├── make_image.py              # ✅ slayt çizimi (+ kullanılmayan kapak kodu)
│   ├── fetch_photo.py             # ✅ Commons katmanı (4 kat filtreli)
│   ├── fetch_stock.py             # ✅ Pexels katmanı
│   ├── fetch_flag.py              # ✅ ülke + kuruluş bayrağı, önbellekli
│   ├── slaytlar.py                # ✅ katman seçici + tur üretici
│   ├── caption.py                 # ✅ carousel'in tek açıklaması
│   ├── filtre.py                  # ✅ shadowban kelime/etiket filtresi
│   └── upload_image.py            # ✅ imgbb (Adım 4a)
├── scripts/
│   ├── hazirla.py                 # ✅ TURUN TAMAMI (RSS→metin→slayt→Telegram)
│   │                              #    --kuru: Telegram'a göndermez, DB'ye yazmaz
│   │                              #    --metinsiz: Gemini'ye hiç gitmez
│   ├── onay_isle.py               # ✅ Telegram buton/komut işleyici
│   ├── hatirlat.py                # ✅ onaylanmayan turu hatırlat / havuza dön
│   ├── jeton_yenile.py            # ✅ jeton ömrü kontrolü (--sadece-bak zararsız)
│   ├── webhook_kur.py             # ✅ Telegram webhook kur/kaldır/durum
│   ├── test_0_butunluk.py         # ✅ ÖNCE BUNU ÇALIŞTIR (aşağıda anlatıldı)
│   ├── test_1_rss.py              # ✅ RSS + veritabanı
│   ├── test_2_makale_metni.py     # ✅ gövde çekme ölçümü (DB'ye dokunmaz)
│   ├── test_3_metin_uret.py       # ✅ Gemini metin (DB'yi DEĞİŞTİRİR, kota yer)
│   ├── test_4_gorsel.py           # ✅ tek slayt
│   ├── test_5_instagram_baglanti.py # ✅ jeton + hesap doğrulama
│   ├── test_6_tur_gorsel.py       # ✅ BİR TURUN TAMAMI — maliyeti sıfır
│   ├── test_kaynak_erisim.py      # ✅ IP engeli teşhisi (DB'ye dokunmaz)
│   ├── anahtar_ekle.py            # ✅ .env'e anahtar ekler (gizli giriş)
│   ├── jeton_uzat.py              # ✅ IG jetonunu 60 güne çevirir
│   └── telegram_chat_id_bul.py    # ✅ (webhook kurulunca ÇALIŞMAZ)
├── assets/fonts/Inter-Variable.ttf  # ✅ Türkçe karakterler test edildi
├── assets/flags/                  # ✅ indirilen bayrak önbelleği (repoya girer)
├── data/output/                   # üretilen slaytlar (.gitignore'da)
└── logs/
```

Dokümanlar (kullanıcıya gönderildi, referans): `00-YOL-HARITASI.md`,
`TASARIM-onay-akisi.md`, `ADIM-1-NASIL-CALISTIRILIR.md`, `NASIL-CALISIYOR.html`

---

## 6. Teknik notlar — `src/`

### `db.py`
- Düz SQL, ORM yok (kullanıcı SQL biliyor, okuyabilsin diye bilinçli tercih).
- `kur()` şemayı kurar **ve otomatik migration yapar**: `EK_KOLONLAR` sözlüğüne
  yeni kolon ekleyip `kur()` çağırmak yeterli, kullanıcının DB silmesi gerekmez.
  Yeni kolon eklerken bu sözlüğü kullan.
- `ayarlar` tablosu: basit key/value (`ayar_oku` / `ayar_yaz`).
- **Tekrar engeli:** `haberler.link` UNIQUE + `INSERT OR IGNORE`.
  `haber_ekle()` gerçekten eklendiyse `True` döner.

**`durum` akışı:**
```
yeni → metin_hazir → gorsel_hazir → onay_bekliyor → yayinlandi
                                                  → atlandi
                                                  → ertelendi  (havuza döner)
herhangi bir yerde → hata
```

**Kolonlar:** `id, kaynak, kategori, agirlik, baslik_orj, link (UNIQUE),
ozet_orj, yayin_tarihi, cekilme_zamani, ig_baslik, ig_caption, ig_hashtag,
onem_puani, gorsel_yolu, gorsel_url, tur, telegram_message_id, gonderim_zamani,
hatirlatma_sayisi, ertelenme_sayisi, durum, ig_post_id, hata_mesaji`

### ⚠️ 18 Ağustos 2026 — troubleshooting bulguları

Üçü de **sessiz** kusurdu: hiçbiri hata vermiyordu.

| Bulgu | Neden tehlikeliydi |
|---|---|
| **Onaylanan metin ≠ yayınlanan metin.** `son_dakika.py` hazırlarken `son_dakika_caption()` kuruyor ve Telegram'da onu gösteriyordu; `onay_isle.py` yayınlarken `caption_kur()` çağırıyordu. Son dakika postu "Günün gündemi" diye çıktı. | Gözden geçirdiğin şey yayına çıkan şey değil — onay adımı işlevini kaybediyor. |
| **Gece otomatik yayını geri alınamıyordu.** Facebook id'si atılıyor, Threads id'si yalnızca loga yazılıyor, `telegram_message_id` hiç atanmıyordu. | Kaldırmanın en çok gerektiği senaryo tam da bu: post insan onayı olmadan çıkıyor. |
| **Bütünlük testinin dosya listesi elle tutuluyordu.** Sonradan eklenen `ayar.py`, `threads.py`, yeni scriptler denetim dışıydı; `instagram.kota_durumu()` diye var olmayan bir çağrı testten TEMİZ geçti. | Testin kendisi yanlış güven veriyordu. Liste otomatik keşfe çevrildi: 11 dosya/161 çağrı → 42 dosya/206 çağrı. |

**Ders:** bir düzeltmeyi uygularken aynı işi yapan DİĞER kod yolunu da ara.
Tarih düzeltmesi ve caption seçimi, ikisi de yalnızca bir dosyaya uygulandı;
onaylı yayınlar başka dosyadan çıktığı için düzeltme onlara hiç işlemedi.

### `scripts/son_dakika.py` yapısı

`main()` 334 satırdı; tek fonksiyonda RSS çekme, puanlama, öneri,
görsel üretimi, gece otomatik yayın ve Telegram onayı vardı — test
edilemez, güvenle değiştirilemez. Bölündü (20 Ağu 2026), **206 satır**:

| fonksiyon | işi |
|---|---|
| `onerileri_gonder` | taze başlıkları toplu puanlayıp Telegram'a öneriyor |
| `aday_bul` | metni hazır haberlerden tekil post adayı seçiyor |
| `gece_otomatik_yayinla` | dört katmanlı denetim + gece yayını |
| `onaya_sun` | Telegram onay mesajı + veritabanı |

⚠️ `gece_otomatik_yayinla` **`(yayinlandi, katman_raporu)`** dönüyor,
yalnızca bool değil: yayın reddedildiğinde haber onaya sunuluyor ve o
mesajda HANGİ katmanın reddettiği yazılı olmalı. İlk bölme denemesinde
yalnızca bool dönüyordu ve rapor sessizce kayboluyordu — kod taşınırken
sözdizimi bozulmuyor, testler geçiyor, ama bir BİLGİ akmayı bırakıyor.

### `src/aday.py` — seçim kurallarının TEK kapısı

"Bu haber şu bağlamda yayınlanabilir mi?" sorusu artık tek yerde
cevaplanıyor. Bağlamlar: `tur` (carousel), `tekil` (gün içi post),
`oneri` (Telegram başlık önerisi).

```python
baglam = aday.Baglam.kur("tekil", ayarlar, con)
secilen = aday.sec(havuz, baglam, adet=1)
```

⚠️ **NİYE GEREKTİ:** bu projedeki kusurların çoğu "kural yanlıştı"
değil, **"kural doğru ama bir yerde uygulanmamıştı"** hatasıydı —
1j, 1p, tazelik sabiti. Kurallar tek kapıda toplanınca o hata sınıfı
yapısal olarak imkânsızlaşıyor: yeni akış `uygun_mu()` çağırıyor ve
bütün kurallar otomatik geliyor.

**Yan kazanç — teşhis.** `aday.sec` elenme sebeplerini sayıp
logluyor:

```
[tekil] eleme: bayat=247, bu konu son günlerde yayınlandı=2, puan yetersiz=12
```

"Tekil post 5 saat çıkmadı" olayında havuzun %98'inin tazelik
filtresine takıldığı ancak elle sorgu yazılarak bulunmuştu; artık log
doğrudan söylüyor.

⚠️ **`konu_imzasi` vs `_ozel_isimler`** — tekrar denetiminde
`secim.konu_imzasi()` kullanılır. Farkı: başlığın İLK kelimesini de
sayar. `_ozel_isimler` onu bilerek atlıyor (her başlık büyük harfle
başlar) ama haber başlıkları çok sık yer adıyla başlıyor
("Kolombiya'da…", "Ankara'da…") ve ilk kelime atlanınca ortak özel
isim kalmıyor, tekrar YAKALANAMIYOR. Sözleşme testi bu kusuru
`aday.py`'nin ilk sürümünde yakaladı.

### İKİ TEST KATMANI — kod değiştirdikten sonra ikisini de çalıştır

```bash
python scripts/test_0_butunluk.py    # çağrılar ve imzalar geçerli mi
python scripts/test_7_sozlesme.py    # kurallar her yerde uygulanmış mı
```

`.github/workflows/testler.yml` ikisini de her push'ta çalıştırıyor —
`src/`, `scripts/`, `worker/`, `config.yaml` değişince tetikleniyor.
Ağa çıkmıyor, veritabanına dokunmuyor, saniyeler sürüyor.

⚠️ **Neden İKİ katman:** bütünlük testi kodun ÇAĞRILABİLİR olduğunu
denetliyor (fonksiyon var mı, imza uyuyor mu). Sözleşme testi kodun
DOĞRU DAVRANDIĞINI denetliyor. Bu projedeki kusurların çoğu ikinci
kategoride ve ortak desenleri şu: **aynı kural birden fazla yerde
yaşıyor ve biri unutuluyor.**

`test_7_sozlesme.py` şu anda 46 denetim yapıyor ve hepsi gerçek bir
olaydan doğdu:

| denetim | hangi olaydan doğdu |
|---|---|
| mükerrer engeli her akışta var mı | 1p — aynı olay bir saat arayla iki kez yayınlandı |
| config'deki her ayar okunuyor mu | `instagram.deneme_sayisi` ölü ayardı |
| sabit kodlanmış eşik yok | `TAZELIK_SAAT=3` config'i eziyordu |
| prompt kopyaları tutarlı | puan bandı bir prompta uygulandı, ikincisi unutuldu |
| Worker ↔ Python buton uyumu | yeni buton Telegram'da "tanınmayan komut" verdi |
| YAML'da çıplak `git rebase` yok | 1d/1f — repoyu detached HEAD'de kilitledi |
| öneri eşiği < yayın eşiği | toplu puanlama 1.6 puan düşük veriyor |

⚠️ **Testi yazarken yanlış pozitife dikkat:** ilk sürüm YAML'lardaki
*uyarı yorumlarını* ihlal sanıp 4 sahte hata verdi. Yorum satırları
atlanıyor. Yanlış alarm veren test, hiç olmayan testten kötüdür —
insan onu görmezden gelmeye başlar.

### `test_0_butunluk.py` — ÖNCE BUNU ÇALIŞTIR

Scriptleri **çalıştırmadan** ayrıştırıp her `modul.fonksiyon()` çağrısının
gerçekten var olduğunu ve argümanların imzaya uyduğunu denetler. Ağa
çıkmaz, DB'ye dokunmaz, para harcamaz.

**Neden var:** üç kez aynı hataya düşüldü — `fetch_news.hepsini_cek`
(yok), `metinleri_uret(con, ...)` (yanlış imza), `slayt_uret(..., con=con)`
(öyle bir parametre yok). Üçü de sözdizimi açısından geçerliydi, diğer
testler geçiyordu, ama ilk gerçek çalıştırmada patladılar. Python modül
çağrısını ancak o satır çalışınca çözümlüyor; gözetimsiz bir botta bu
"gece yarısı job patlar, sabah fark edilir" demek.

Kod değiştirdikten sonra ilk çalıştırılacak şey budur.

### `dogrula.py` — uydurma ve içi boş başlık denetimi

Onay mesajı gönderilmeden ÖNCE çalışıp uyarıları mesajın başına koyuyor.
İki ayrı şeye bakıyor:

1. **Kaynakta doğrulanamayan sayı/isim.** Üretilen metindeki sayılar ve
   özel adlar makale gövdesinde geçiyor mu? Geçmiyorsa işaretleniyor.
   Yuvarlama olabilir, o yüzden uyarı — otomatik eleme değil.
2. **İçi boş başlık kalıpları** (`basligi_denetle`). "…ilişkin açıklama",
   "…değerlendirdi", "…anlattı" gibi konuyu duyurup sonucu saklayan 15
   kalıp + abartı kalıpları.
3. **Suçlama dili** (`suclama_dili_denetle`). Kaynakta "soruşturma /
   iddia / şüpheli" varken üretilen metin kesin dille yazılmışsa uyarır.
   Ölçüldü: suçlama içeren 10 haberin 3'ünde ihtiyat düşmüştü; biri
   gerçek riskti ("iade edilen SUÇ ÖRGÜTÜ ELEBAŞI" — kırmızı bülten
   suçluluk değil). Sayı/isim denetimi bunu yakalayamıyor: her şey
   kaynakla uyuyor, sadece dil kesinleşmiş oluyor.
   Atıflı başlıklar ("BM:", "Savcılık:") hariç — iddia zaten birine
   dayandırılmış oluyor.

**NE YAKALAMIYOR (bilinçli sınır):** anlam kayması. "reddetti" ile
"kabul etti" aynı sayı ve isimleri taşıyor; ayırmak için ikinci bir LLM
çağrısı gerekir. Bunu yakalayan tek şey insan onayı.

⚠️ **TÜRKÇE `İ` TUZAĞI:** `"İlişkin".lower()` Python'da `"i̇lişkin"`
üretiyor (noktalı i) ve düz karşılaştırma TUTMUYOR. İlk yazımda tarama
sessizce hiçbir şey yakalamıyor, her şey "temiz" görünüyordu.
Karşılaştırma `_sadelestir()` üzerinden yapılmalı.

### `secim.py` — tavuk-yumurta sorunu
Seçim skoru `onem_puani`ye dayanıyor ama o puanı Gemini üretiyor. Havuzdaki
234 haberin hepsine metin ürettirmek kotayı ve turu (234 makale indirmek)
katlıyor. İki aşama:
1. `on_eleme()` — **LLM yok, bedava.** Yaş + kaynak ağırlığı + kategori ile
   havuzu slayt sayısının 2.5 katına indirir (10 slayt → 25 aday).
2. `tur_icin_sec()` — yalnızca adaylara metin üretildikten sonra gerçek skorla
   en iyi 10'u alır.

Elenen haberler ya bayat ya düşük ağırlıklı kaynaktan; ikisi de asıl skorda
zaten dibe düşecekti.

### `caption.py`
Instagram sınırları **ölçüldü ve uyulması zorunlu**: 2200 karakter, 30 hashtag,
ilk ~125 karakter sonrası "daha fazla" arkasına gizleniyor (o yüzden tarih ve
ilk manşet en başta). Sınır aşılırsa kesme sırası: hashtag → atıf → son
maddeler. Manşetler en değerli kısım, en son onlara dokunuluyor.

Gerçek turda ölçülen: **1086/2200 karakter, 30/30 hashtag.** Rahat sığıyor.

### `fetch_news.py`
- `feedparser` **kullanılmıyor** — `requests` + `xml.etree.ElementTree` +
  `dateutil` ile yazıldı. Bağımlılık azaltmak için bilinçli tercih. Bozma.
- RSS 2.0 **ve** Atom destekli.
- Tarayıcı User-Agent'ı şart (haber siteleri `python-requests`'i engelliyor).
- Tarihler UTC'ye normalize edilip ISO 8601 olarak saklanıyor.
  Saat dilimi belirtilmemişse UTC+3 varsayılıyor.
- Bir kaynak patlarsa (404/timeout/bozuk XML) diğerleri etkilenmiyor;
  hata rapora yazılıyor.

**Doğrulanmış testler:** Atom+RSS ayrıştırma, CDATA, HTML temizliği,
Türkçe karakterler, tarih normalizasyonu, yaş filtresi, tekrar engeli
(2. çalıştırmada 0 yeni), kaynak izolasyonu, eski şemadan migration.

---

## 7. Adımların referansı

> **Bütün adımlar BİTTİ (16 Ağu 2026).** Aşağısı artık "yapılacaklar"
> değil, her adımın nasıl çalıştığının referansı. Bir şey bozulduğunda
> ilgili bölüme bak.
>
> **Gerçekten kalan tek iş:** günlük işleyişi izlemek. Bot çalışıyor;
> ara sıra `data/kaynak-erisim-raporu.txt`'ye ve Telegram'daki hata
> bildirimlerine bakmak yeterli.

### ✅ Adım 2 — Gemini ile metin (`src/generate_text.py`) — BİTTİ

Girdi: `durum='yeni'` haberler. Çıktı: `ig_baslik`, `ig_caption`, `ig_hashtag`,
`onem_puani` (1-10) → `durum='metin_hazir'`. Test: `scripts/test_3_metin_uret.py`

**EN ÖNEMLİ BULGU — bunu bozma:**
RSS özetleri teaser; haberlerin **%76'sının özeti 200 karakterin altında**.
Bu kadar az bilgiyle üç ayrı Gemini modeli de kaynakta OLMAYAN iddialar
uydurdu ("suçlamaları reddetti", "konuyu yargıya taşıdı") — üstelik adı geçen
gerçek bir milletvekili ve cinsel taciz suçlaması hakkında. Yayınlansa iftira.

Çözüm: `src/fetch_article.py` haberin sitesine gidip **tam gövdeyi** çekiyor
(16/16 kaynakta başarılı, ortalama 10-30 kat daha fazla metin). Tam metinle
tekrar denendiğinde üretilen her cümle kaynakta doğrulandı.

Gövde çekilemezse RSS özetine düşüyor **ve prompt'a "elindeki bilgi az, tek
cümle yaz, uydurma" uyarısı ekleniyor** (`AZ_BILGI_UYARISI`). Bu yedek yolu
kaldırma.

**Telegram onayı bu riski çözmez** — uydurma metin akıcı ve inandırıcı görünür.
O yüzden `makale_metni` kolonunda kaynak metni saklıyoruz; Adım 5'te onay
mesajında gösterilmeli ki kullanıcı karşılaştırabilsin.

Diğer notlar:
- Model `config.yaml` → `gemini.model`. Koda gömülü değil, değiştirmek tek satır.
- Seçim: `gemini-3.6-flash` (birincil), `gemini-3.5-flash` (yedek).
  `gemini-3.7-flash` gerçek boyutlu isteklerde 3 denemenin 2'sinde 503 verdi.
- JSON çıktı `responseSchema` ile zorlanıyor — düz metin dönme sorunu yok.
- Anahtar URL'ye değil `x-goog-api-key` başlığına konuyor (loga sızmasın).
- 503/429/500/502/504'te bekleyip tekrar deniyor, sonra yedek modele geçiyor.
  Gözetimsiz çalışan bir bot için şart.
- **`gemini-2.0-flash` artık YOK** (eski notlardaki öneri geçersiz). Model
  adlarını varsaymak yerine `v1beta/models` uç noktasından listele.

**Seçim skoru** (`src/secim.py` veya `run.py` içinde):
```
skor = onem_puani * 10 + agirlik - (yas_saat * 1)
       - 15 eğer kategori == 'dunya' ve onem_puani < 8
```
`yayin_yasi_siniri_saat` (48) geçmiş haber aday olmaz.

### Adım 3 — Görsel (`src/make_image.py`)
- Pillow, 1080x1080, `assets/template.jpg` üstüne başlık.
- **Türkçe karakter destekli font şart** (ğ ş ı İ ç ö ü). Inter/Roboto TTF.
  `assets/fonts/` içine koy, sistem fontuna güvenme (GitHub runner'da yok).
- Uzun başlık için otomatik satır kırma + font boyutu küçültme.
- **Çıktı JPEG olmalı** — Instagram PNG kabul etmiyor.
- Kullanıcı henüz şablon vermedi; yoksa geçici bir tane üret.

### Adım 4a — imgbb (`src/upload_image.py`)
`POST https://api.imgbb.com/1/upload`, base64 gövde, dönen `data.url` saklanır.

### Adım 4b — Instagram (`src/instagram.py`)
```
POST /v21.0/<IG_USER_ID>/media          image_url, caption  → container id
POST /v21.0/<IG_USER_ID>/media_publish  creation_id         → post id
```
- İzinler: `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
  `pages_read_engagement`, `business_management`.
- Kendi hesabına post attığı ve app admin'i olduğu için **App Review gerekmiyor.**
- Sadece **JPEG**, görsel **public URL** olmalı.
- Limit: 24 saatte 100 post. `GET /<IG_USER_ID>/content_publishing_limit` ile bakılır.
- Container hazır olmayabilir → `status_code` FINISHED olana kadar kısa bekleme.
- **Token 60 günde ölür** → `src/refresh_token.py` (Adım 7).

### Adım 5 — Telegram + Cloudflare Worker
- `src/telegram_bot.py`: `sendPhoto` + inline keyboard
  (`✅ Yayınla` / `⏭ Atla` / `🔄 Metni yeniden üret`), `editMessageCaption`
  ile sonucu güncelle. `telegram_message_id` DB'ye yazılır.
- **Onay GRUBA gidiyor** (`TELEGRAM_CHAT_ID=-5501804510`, "Daily Brief").
  Gruptaki herkes basabilir — kullanıcının açık tercihi, yetki kontrolü yok.
- **SUPERGROUP TUZAĞI:** Grup şu an normal `group` türünde. Telegram bir
  grubu supergroup'a yükselttiğinde chat ID DEĞİŞİR ve bot sessizce mesaj
  atamaz olur. `sendMessage` hata cevabında
  `parameters.migrate_to_chat_id` alanıyla yeni ID'yi veriyor —
  `telegram_bot.py` bunu yakalayıp `.env`/DB'yi güncellemeli. Yoksa bir
  gün onay mesajları gelmez ve sebebi anlaşılmaz.
- Carousel onayı: tek görsel değil 10 slayt var. `sendMediaGroup` ile
  hepsini gönderip ayrı bir mesajda butonları koymak gerekebilir —
  `sendMediaGroup` inline keyboard KABUL ETMİYOR. Adım 5'te çöz.
- **ÖNEMLİ:** Webhook kurulunca `getUpdates` çalışmaz. Bu bilinçli —
  saat başı job'lar Telegram'ı okumuyor, sadece DB'ye bakıp hatırlatma atıyor.
- Cloudflare Worker: Telegram webhook'unu alır → `secret_token` header'ını
  doğrular → GitHub `POST /repos/{owner}/{repo}/dispatches`
  (`event_type: telegram_onay`, `client_payload: {haber_id, karar}`) →
  `answerCallbackQuery` ile butonu durdurur.
- Worker secret'ları: `TELEGRAM_BOT_TOKEN`, `GITHUB_PAT`, `WEBHOOK_SECRET`.
- GitHub PAT: fine-grained, **sadece bu repo**, `Contents: write`.

### Adım 6 — GitHub Actions
`.github/workflows/` altında:
- `hazirla.yml` — cron `0 6 * * *` ve `0 17 * * *` (UTC! TR = UTC+3, DST yok)
- `hatirlat.yml` — cron `0 7,8,9,17,18,19,20 * * *` (UTC)
- `yayinla.yml` — `on: repository_dispatch: types: [telegram_onay]`
- **Her job sonunda `data/haber.db` repo'ya commit edilmeli** — runner ephemeral,
  DB başka türlü kaybolur. Bu aynı zamanda 60-gün inaktivite kapanmasını da önler.
- Cron gecikmesi normal (5-30 dk). `:00` yerine `:07` gibi dakikalar daha iyi.

### Adım 7 — Token yenileme + hata bildirimi
- Long-lived token 60 gün. Haftalık cron ile `GET /refresh_access_token`
  (`grant_type=ig_refresh_token`). Yenilenen token GitHub Secret'a yazılmalı
  (PAT ile `PUT /repos/{owner}/{repo}/actions/secrets/{name}`, libsodium ile şifreli).
- Herhangi bir job patlarsa Telegram'a hata mesajı.

---

## 8. `.env` / GitHub Secrets

```
IG_USER_ID, IG_ACCESS_TOKEN, META_APP_ID, META_APP_SECRET
GEMINI_API_KEY
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
IMGBB_API_KEY
```
Worker tarafı ayrıca: `GITHUB_PAT`, `WEBHOOK_SECRET`.

---

## 9. Kullanıcının hazırlık durumu

Güncelleme: 14 Ağustos 2026 — hepsi test edilerek doğrulandı.

| # | Ne | Durum |
|---|---|---|
| A | Instagram Business + FB Page + Meta App + jeton | ✅ **@dailybrief.co**, jeton 13 Eki 2026'ya kadar |
| B | Gemini API key (metin, ücretsiz proje) | ✅ çalışıyor |
| B2 | Gemini API key (görsel, **faturalı** proje) | ✅ `GEMINI_IMAGE_API_KEY`, bütçe uyarısı kurulu |
| C | Telegram bot token + chat ID | ✅ @dailybriefinstaBot, test mesajı ulaştı |
| D | imgbb API key | ✅ yükleme + genel erişim doğrulandı |
| E | GitHub private repo | ✅ ozdogangringo-sketch/haber-bot |
| F | Görsel şablon | ✅ gerek kalmadı — Commons fotoğrafı / gradyan / AI kapak |
| G | Cloudflare hesabı | ✅ ozdogandogukan@gmail.com, Worker canlı |
| H | GitHub fine-grained PAT | ✅ `Contents: write` + `Secrets: write` |
| I | Pexels API key | ✅ `PEXELS_API_KEY`, bedava kota 200 istek/saat |

**DİKKAT — Instagram hesabı seçimi:** Jetonun 3 sayfaya erişimi var
(DailyBrief, Animarch Studio, Edm Yapı). Hedef hesap `config.yaml` →
`instagram.hesap_kullanici_adi` ile açıkça belirtiliyor. Kod hesabı
ASLA tahmin etmemeli — ilk yazdığım script "son bulduğunu" seçmişti ve
emlak şirketinin hesabını hedeflemişti. Bu korumayı kaldırma.

`.env` anahtarlarının HEPSİ dolu ve test edildi: `GEMINI_API_KEY`,
`GEMINI_IMAGE_API_KEY`, `IMGBB_API_KEY`, `IG_USER_ID`, `IG_ACCESS_TOKEN`,
`META_APP_ID`, `META_APP_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

**Telegram zamanlama tuzağı:** `scripts/telegram_chat_id_bul.py`
`getUpdates` kullanıyor. Adım 5'te webhook kurulunca `getUpdates`
ÇALIŞMAZ (Telegram ikisine aynı anda izin vermiyor). Chat ID zaten
alındı (6333892758), ama webhook kurulduktan sonra bu scripti
çalıştırmaya kalkarsan neden boş döndüğünü bilirsin — script bunu
kendisi de uyarıyor.

---

## 10. Başka bir bilgisayarda çalışmaya devam etme

Repo her şeyi taşıyor — **`.env` hariç.** O bilerek git'e girmiyor
(içinde tüm anahtarlar var). Veritabanı `data/haber.db` repo'da,
yani haber geçmişi de geliyor.

```bash
# 1) Python kur — python.org/downloads
#    Kurulumda "Add python.exe to PATH" kutusunu MUTLAKA işaretle.
#    (3.12 en sorunsuzu; 3.14'te PyYAML derleme sorunu çıkmıştı,
#     requirements.txt'te çözüldü ama 3.12 hâlâ daha az sürprizli.)

# 2) Git kur — git-scm.com

# 3) Repo'yu klonla (private, GitHub girişi isteyecek)
git clone https://github.com/ozdogangringo-sketch/haber-bot.git
cd haber-bot

# 4) Sanal ortam + kütüphaneler
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
```

**5) `.env` dosyasını taşı.** Bu en kritik adım.

Güvenli yollar: USB bellek, parola yöneticisindeki güvenli not, ya da
her servisten anahtarları yeniden üretmek.

**Yapma:** e-posta, WhatsApp, sohbet penceresi, bulut not defteri.
Bunlar anahtarları üçüncü taraflara bırakır.

Anahtarları yeniden üretmek gerekirse:
- `GEMINI_API_KEY`, `GEMINI_IMAGE_API_KEY` → aistudio.google.com/apikey
  (dikkat: ikisi FARKLI projelerden — biri faturasız, biri faturalı)
- `IMGBB_API_KEY` → imgbb.com/api
- `TELEGRAM_BOT_TOKEN` → @BotFather → `/mybots`
- `IG_ACCESS_TOKEN` → Graph API Explorer'dan yeniden al, sonra
  `python scripts/jeton_uzat.py` ile 60 güne çevir
- `META_APP_ID`, `META_APP_SECRET` → App settings → Basic

**6) Her şeyin çalıştığını doğrula** (sırayla, hepsi zararsız):

```bash
python scripts/test_1_rss.py                    # RSS + veritabanı
python scripts/test_kaynak_erisim.py            # kaynak erişimi
python scripts/test_5_instagram_baglanti.py     # Instagram + jeton
python scripts/test_2_makale_metni.py           # makale metni çekme
```

Hepsi yeşilse kaldığın yerden devam edebilirsin. Jeton süresi dolmuşsa
`test_5` bunu söyler.

---

## 11. Bilinen riskler

- ~~Cloudflare korumalı siteler GitHub runner IP'sine 403 dönebilir~~ →
  **ölçüldü, 14 Ağu 2026'da 8/8 temiz.** Tek ölçüm olduğu için ara ara
  tekrar bakılmalı; kaynak izolasyonu sayesinde en kötü ihtimal
  "bir kaynak eksik", "bot çöker" değil.
- Instagram token 60 gün → otomatik yenileme şart
- Gemini yanlış/taraflı başlık üretebilir → **onay adımı asla kaldırılmasın**
- Cron gecikmesi 5-30 dk, nadiren atlanır
- 09:59'da onay + 10:00 hatırlatma job'ı → gereksiz hatırlatma (nadir, zararsız)
- GitHub ToS teknik olarak repo-dışı iş yükünü hoş karşılamıyor (bu ölçekte pratikte sorun değil)
- Haber görseli kullanılmıyor, kendi şablon + kaynak adı → telif riski yok
