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
| Görsel hosting | **imgbb**, yedeği **catbox.moe** (Instagram public URL zorunlu kılıyor) |
| ⚠️ imgbb TEK ARIZA NOKTASIYDI | 21 Ağu 2026: imgbb bakıma girdi (`"Imgbb is currently down for maintenance."`, code 100) ve bot **hiçbir post atamaz** oldu — görsel yüklenemeyince ne tur ne tekil post çıkıyor. Tekrar denemek işe yaramıyor, servis kapalıyken 3 deneme de aynı cevabı veriyor. `gorsel.yedek_barindirici` ile catbox.moe devreye giriyor; Instagram'ın indirebildiği **gerçek container ile doğrulandı** (FINISHED). ⚠️ **catbox bot User-Agent'larını engelliyor**: `python-requests` ve UA'sız istek bağlantıyı kesiyor, `Mozilla/5.0` ve `facebookexternalhit` geçiyor — Instagram indirebiliyor ama bizim doğrulama isteklerimiz UA vermek zorunda. |
| Haber teması | Öncelik **Türkiye gündemi**; dünya haberi sadece önem puanı ≥8 ise |
| Post biçimi | **CAROUSEL** (kaydırmalı). **Kapak YOK, 10 haber** = 10 slayt. Instagram sınırı 10. |
| ~~Kapak slaytı~~ | **DENENDİ VE ELENDİ (15 Ağu 2026).** Kapak+9 haber düzeni üretilip gösterildi; kullanıcı 10 haberi tercih etti. `kapak_ciz`/`kapak_uret` kodu `make_image.py`'de DURUYOR — fikir değişirse `kapak_var: true` yeterli, yeniden yazma. |
| Slayt oranı | **4:5 dikey (1080x1350)**. Carousel'de tüm slaytlar aynı oranda olmak zorunda. |
| Güvenli alan | `dikey_guvenli_pay: 150`. Feed'de 4:5 tam görünüyor; risk profil ızgarasının kareye kırpması (üst/alt 135px). Instagram ızgarayı 2025'te dikey yaptı ama bayrak ve kaynak satırı tam sınırdaydı, içeri alındı. |
| ~~Post sıklığı: günde 2 tur~~ | ⚠️ **GEÇERSİZ (Ağu sonu).** Akşam çoklu tur cron'u `hazirla.yml`'de yorum satırına alındı. Yeni model: gün boyu **saat başı 5 haber önerisi**, seçilen haber 1 kapak + 2-3 detay slaytı. Aşağıdaki eski satır tarihsel kayıt olarak duruyor. |
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
| ⚠️ HABER FOTOĞRAFI EŞİĞİ 1000x560 (21 Ağu 2026) | Eşik `1080x800` iken haberin kendi fotoğrafı **hiç kullanılamıyordu**: ölçüldü, son 14 haberin **14'ü de** boyuttan elendi ve hepsi Pexels'e düştü. Sebep haber sitelerinin standart OG boyutlarının eşiğin altında olması — **1280x720** (16:9) ve **1200x630** (1.91:1). Kullanıcının *"görseller çok genel, hep aynı şeyler"* şikâyetinin asıl sebebi buydu. Yeni eşikle iki standart geçiyor (11/14), 864x486 gibi **1080'e BÜYÜTÜLMESİ** gerekenler eleniyor — büyütme bulanıklaştırır, küçültme kalite kaybettirmez. Etki: haber fotoğrafı **%0 → ~%79**. |
| ⚠️ Aynı Pexels fotoğrafı tekrar seçilmiyor | `gorsel_kaynak_id` kolonu + `slaytlar._kullanilmis_stok_idler()` + `fetch_stock.fotograf_ara(kullanilmis=…)`. Ölçüldü: aynı fotoğrafçının fotoğrafı **6, 5 ve 4 kez** tekrar etmişti — aynı arama terimi hep aynı sonucu veriyor ve biz en yüksek puanlıyı alıyorduk. Kullanılanlar **ELENMİYOR, listenin sonuna atılıyor**: havuz darsa hiç fotoğraf bulamamaktansa tekrar iyidir. Doğrulandı: aynı arama 3 kez çağrıldı, 3 farklı fotoğraf geldi. |
| ⚠️ Haber görseli (18 Ağu 2026) | Haberin kendi fotoğrafı artık EN ÜST katman (`fetch_article.og_gorseli_cek`). **TELİF RİSKİ TAŞIYOR** — ajans fotoğrafı olabiliyor, kaynak belirtmek izin yerine geçmiyor, Instagram şikayette postu kaldırır. Kullanıcı riski bilerek seçti; daha önce "kullanılmayacak" denmişti, karar 18 Ağu'da değişti. `og:image` seçilmesinin sebebi: sitenin sosyal medyada paylaşılsın diye koyduğu görsel bu. `gorsel.haber_gorseli_kullan: false` ile kapanır. 600px altındakiler eleniyor (site logosu olabiliyor). |
| ★ İNTERNET GÖRSEL ARAMASI KAPATILDI (3 Eyl 2026) | `fetch_web_image` 28 Ağu'da eklenmiş ve zincirin **1. sırasına** konmuştu — haberin kendi og:image'inin bile önüne. Başlığın ilk 6 kelimesiyle DuckDuckGo görsel araması yapıp **teknik testi geçen İLK** fotoğrafı basıyordu. ⚠️ **ALAKA DENETİMİ YOKTU**: test yalnızca piksel + netlik ölçüyor. Ölçüldü, 3 gerçek haberin **3'ü de yanlış**: "ABD İran'a saldırdı" → `a57.foxnews.com`'dan Trump portresi (*"Trump tells The Atlantic that he runs the country"*); "Milli Hızlı Tren" → 5G ihalesi görseli; "Akdeniz Oyunları" → halter e-ticaret blogu. Üçü de teknik testi GEÇTİ. |
| ⚠️ METİN TABANLI ALAKA KAPISI ÇÖZMÜYOR | Denendi ve ELENDİ: "aday başlığı haberle ortak özel isim taşısın" şartı kondu, **6 haberin 6'sı da geçti** — Fox News/Trump dahil. Sebep **döngüsel**: `gorsel_konu` "Donald Trump" olduğu için arama Trump'ı arıyor, dolayısıyla her sonuçta "Trump" geçiyor; kapı kendi kendini onaylıyor. Asıl kusur aramada değil **brief'te** — o haberin görsel öznesi Trump değildi. Bunu ancak görselin İÇİNE bakan bir denetim (Vision) çözer. |
| ⚠️ KAPATMANIN BEDELİ ÖLÇÜLDÜ | Yayınlanmış 10 `web_haber` postu tek tek denendi: **4'ü haberin KENDİ fotoğrafını bulurdu** (konuya garantili bağlı, daha iyi), 6'sı Pexels'e düşerdi (genel ama dürüst ve hukuken temiz). Yani 10 doğrulanamaz fotoğraf yerine 4 doğru + 6 temsili — net kazanç. Ayrıca slayt başına **12-16 sn** geri geldi (13 sorgu × 2 HTTP + aday indirmeleri). |
| ⚠️ `YASAKLI_STOK_SITELERI` YANLIŞ TARAFI ENGELLİYOR | Shutterstock/Getty engelli (sana **lisans satacak** siteler), ama `foxnews.com` ve haber ajansı CDN'leri serbest (sana **DMCA gönderecek** olanlar). Liste filigrana karşı yazılmış, telife karşı değil. |
| ★ GÖRSEL KÜNYESİ ZORUNLU | Gerçek fotoğraf basan her katman **atıf döndürmek zorunda**; atıf üretilemezse fotoğraf BASILMIYOR, alt katmana düşülüyor. `web_haber` artık `ARSIV_KATMANLARI`'nda (olayın belgesi olduğuna güvencemiz yok). `gorsel.web_gorsel_ara: false` ile kapalı; açılırsa **zincirin sonunda** çalışır. `test_7_sozlesme.test_gorsel_kunyesi_zorunlu` dördünü de AST ile denetliyor. ⚠️ Ayar denetimi **düz metin araması olamaz** — kasten bozularak ölçüldü: `if g.get("web_gorsel_ara")` silindiğinde test TEMİZ geçti, çünkü aynı dosyadaki `#` yorumunda kelime yazılıydı. Yorumlar AST'de bulunmuyor. |
| ★ GÖRSEL BRIEF — YÖNLENDİRME + GÜNCELLİK (3 Eyl 2026) | İki yeni alan: `gorsel_ozne_tipi` (kisi/kurum/urun/olay) ve `gorsel_baglam`. ⚠️ **BRIEF BOZUK DEĞİLDİ** — ölçüldü, bugünkü prompt `gorsel_konu`yu 6/6 doğru üretiyor. Kusur brief'in KULLANILMAMASIydı: 6 briefin 5'i yine genel Pexels stoğunda bitiyordu, çünkü her haber aynı sabit zincire sokuluyor ve "bu tarifi hangi kaynak karşılayabilir" diye sorulmuyordu. `olay` tipi artık Commons'ı atlıyor (ölçüldü: 8.4 → 5.5 sn, ayrıca "İSKİ → Macar sanatçı" tipi yanlış eşleşme riski kalkıyor). ⚠️ og:image yönlendirmeden MUAF — yangın haberinde yayıncının koyduğu fotoğraf gerçekten o yangındır. |
| ★ FOTOĞRAF ARTIK BAŞLIĞA KADAR İNİYOR (3 Eyl 2026) | Kullanıcı: *"neden yazının çok üstünde yatay bir şekilde duruyor resim, ayrık duruyor çok fazla, burada açıklamaya kadar resim olurdu"*. Eski kod yatay fotoğrafı **720px**'de kesiyordu, başlık 1140'ta başlıyordu → arada **~420px ölü bant**. Dört varyant (720/1150/1450/1920) üretilip yan yana gösterildi, **1150 seçildi**. ⚠️ Daha aşağısı ELENDİ: yatay fotoğrafı dikey tuvale yaymak onu büyütmek demek ve 1450'de kadraj bozuluyor (Fed madalyonu iki yandan kesiliyordu). `FOTO_HEDEF_ALT = 1150`. |
| ★ GÖL YANSIMASI — fotoğrafın alt kenarı (3 Eyl 2026) | Kullanıcı: *"bazı fotolarda fotoğrafın hemen altındaki alan çok keskin bir şekilde bitiyor, göl üzerinde yansıma gibi bir efekt ekleyebilir miyiz"*. Sebep: **büyütme tavanı**. Küçük kaynaklı fotoğraf 1150'ye ulaşamayıp erken bitiyor (450px'lik kaynak 855'te durur), altında bulanık ambiyans başlıyor ve arada **net bir çizgi** kalıyor — perde o noktada henüz şeffaf olduğu için gizlemiyor. `_yansima_ekle`: fotoğrafın alt şeridi dikey çevrilip altına konuyor. Maliyet **+3-8 ms**. |
| ★ KARDEŞ GÖRSEL HAVUZU (3 Eyl 2026) | Her kaynaktan **tek aday** alınıyordu. Ölçüldü: yayınladığımız haber başına ortalama **3.9 ek kayıt** aynı olayı işliyor ve her birinin kendi fotoğrafı var. ⚠️ **DAĞILIM KRİTİK**: rutin haberde 0 ek kaynak, ama BÜYÜK OLAYDA **6-12** (Silivri gemi çarpışması 12, İran saldırısı 12, voleybol 10). Yani tam da en çok erişim alan postlarda en çok aday boşta duruyordu. Kazanç ölçüldü: voleybol **1200x675 → 5877x3306** (24 kat piksel), Silivri 1200x708 → 1280x720. |
| ★ VISION DENETİMİ — görselin İÇİNE bakan tek katman (3 Eyl 2026) | `src/gorsel_denetim.py`. ⚠️ Projedeki bütün doğruluk denetimleri METNE bakıyordu (`dogrula.py`: sayı, isim, alıntı, suçlama dili); görsel tarafında ölçülen her şey TEKNİKTİ (piksel, netlik, dosya boyutu). Fox News/Trump portresi 1200x675, keskin, temizdi — teknik testin her sorusuna "evet" dedi. **CANLI ÖLÇÜLDÜ, 3/3 doğru:** Vlahovic + *"Beşiktaş forması"* → *"ACF Fiorentina eşofmanı"* RED · Vargas + *"milli takım forması"* → *"Fenerbahçe forması, 44 numara"* RED · Hakan Fidan (bağlamsız) KABUL. Uçtan uca doğrulandı: Commons reddedilince Pexels'e düşüyor. |
| ★ GÜNLÜK TEMİZLİK 19 GÜNDÜR ÇÖPE GİDİYORDU (4 Eyl 2026) | `gunluk-rapor.yml` `permissions: contents: read` taşıyordu ve **`db_kaydet` adımı YOKTU**. Ama `gunluk_rapor.py` her çalıştığında `db.eski_kayitlari_temizle` çağırıyor: silme runner'da GERÇEKTEN oluyor, log'a *"N eski kayıt silindi"* yazıyor, sonra commit edilmediği için buharlaşıyordu. ⚠️ **SESSİZ BAŞARISIZLIK deseninin ders kitabı örneği** — kod `0` döndü, log başarı yazdı, iş yapılmadı. Belirtisi: config `kayit_saklama_gun: 3` diyor ama veritabanında **19 günlük** kayıt duruyor. Ölçüldü: temizlik açılınca **9107 → 2517 satır, 11.5 → 3.7 MB**, yayınlanmış 277 kaydın hepsi korunuyor. `test_7_sozlesme.test_db_yazan_workflow_commit_ediyor` yedi workflow'u birden denetliyor. |
| ★ ÖLÜ KOD SİLİNDİ — `src/handlers/` ve `x_paylas.py` (4 Eyl 2026) | `src/handlers/` bir refactor denemesinden kalmıştı: `slayt_yonetimi.py` (26 satır) ve `tur_yonetimi.py` (28 satır) içinde **hiç fonksiyon yoktu**, `yayin_yonetimi.py` (158 satır) hiçbir yerden import edilmiyordu. Silmeden önce `onay_isle`'deki kopyalarla karşılaştırıldı: fark yalnızca **eklenen yorumlar ve `_` öneki** — kaybedilecek bir şey yok. `x_paylas.py` (141 satır) de `twitter.py` tarafından tamamen ikame edilmiş. Toplam **356 satır** silindi; `test_0` çağrı sayısı **773'te sabit kaldı** (yani hiçbir şeye katkıları yoktu). |
| ★ TESTLER `tests/` KLASÖRÜNE AYRILDI (4 Eyl 2026) | `scripts/` 33 dosyaydı: 10 test + 23 üretim/araç. Testler ayrı klasöre alındı, `scripts/` 23'e indi. Kök yolu `Path(__file__).parent.parent` olduğu için derinlik aynı kaldı, kod değişikliği gerekmedi. Güncellenenler: 3 workflow, `testler.yml` paths filtresi (`tests/**`), `test_0`un tarama listesi (`src, scripts, tests`), ölü modül taraması ve CLAUDE.md'de 19 atıf. |
| ★ YAZILIP OKUNMAYAN KAYIT — `hata_kayitlari.jsonl` (4 Eyl 2026) | 23 Ağustos'tan beri yazılıyordu, **hiçbir kod okumuyordu**. `hata_bildir.KATALOG` ile eşleştirilmiş teşhis (ne oldu / neden) orada birikiyordu; günlük rapordaki "başarısız iş" satırı ise GitHub Actions API'sinden geliyor ve yalnızca job ADINI veriyor. ⚠️ **Yazılıp okunmayan kayıt, hiç tutulmamış kayıttan kötüdür** — yer kaplar ve "kaydediliyor" diye yanlış güven verir. Günlük rapora son 24 saatin özeti eklendi. Ayrıca `data/tiktok_pkce_verifier.txt` (tek seferlik OAuth artığı, hiç okunmuyor) git'ten çıkarılıp `.gitignore`'a kondu. |
| ★ İKİ TELEGRAM DÜĞMESİ AYLARDIR KIRIKTI (4 Eyl 2026) | `scripts/ekonomi_turu.py` commit `2aaa220`'de bilerek silinmişti ("eski 11:15 ekonomi turu kaldırıldı") ama **ÜÇ yerde izi kalmıştı**: `yayinla.yml` onu çağırıyordu, `onay_isle.py:3308` (`ekonomi_hazirla`) ve `onay_isle.py:3552` (`hata:tur_tekrar`) `from scripts import ekonomi_turu` yapıyordu. Sonuç: **"📊 Ekonomi Turu Başlat"** düğmesi *"⏳ başlatılıyor"* deyip job'ı kırmızıya düşürüyordu ve — daha kötüsü — hata bildirimindeki **"🔄 Turu yeniden hazırla"** düğmesi de kırıktı. *Bir şey bozulduğunda basılan düğmenin kendisi bozuktu.* |
| ★ YOUTUBE JETONU 7 GÜNDE ÖLÜYOR — kök sebep "Testing" modu (4 Eyl 2026) | Kullanıcı *"son post neden youtube post atamadı"* diye sordu. Yayın log'u: `invalid_grant: Token has been expired or revoked`. ⚠️ **TAM 7 GÜN**: OAuth kurulumu 28 Ağu 10:00, ilk yayın 28 Ağu 17:10, **son başarılı 4 Eyl 06:44**, ilk başarısız 4 Eyl 08:44. Google, OAuth ekranı **"Testing"** yayın durumundaki uygulamaların refresh jetonunu **7 günde iptal ediyor**. ⚠️ **KALICI ÇÖZÜM JETONU YENİLEMEK DEĞİL** — Google Cloud Console → OAuth consent screen → **"PUBLISH APP" / In production**. Aksi hâlde her hafta ölür. `scripts/jeton_yenile.py` YouTube'u zaten hiç kapsamıyor (yalnızca IG + Threads) ve kapsasa da Testing modunda fark etmezdi. ✅ **ÇÖZÜLDÜ 4 Eyl 2026 14:03** — uygulama **In production**'a alındı ve jeton yenilendi. Doğrulama zinciri: `saglik_testi` → `durum: True` · kanal sorgusu → **DailyBrief / @dailybrief-y3t** (doğru kanal) · GitHub Secrets 3/3 yazıldı. ⚠️ **Publish için gereken ön şart üç URL'di** (ana sayfa + gizlilik + şartlar) — o yüzden önce site yayınlandı, bkz. bir alttaki satır. |
| ★ `dailybrief.ozbornstudio.com` YAYINDA (4 Eyl 2026) | `web/dailybrief/` → ana sayfa + `/privacy` + `/terms` (TR/EN sekmeli). ⚠️ **Bu sayfalar kozmetik değil, teknik bir ZORUNLULUKTU**: Google OAuth "Publish app" gizlilik ve şartlar URL'si olmadan tıklanamıyor ve o düğme olmadan YouTube jetonu her 7 günde ölüyordu. Cloudflare'de **statik dosya sunan bir Worker** olarak duruyor (klasik Pages projesi DEĞİL; yeni arayüzde ikisi birleşti). ⚠️ **Worker'a özel alan adı `+ Add Domain` ile eklenir, `+ Add Route` ile DEĞİL** — Route yalnızca mevcut bir zone'a yol deseni bağlıyor, DNS kaydını oluşturmuyor. Sertifikayı Cloudflare kendisi çıkarıyor. ⚠️ **Google'a LOGO YÜKLEME** — marka doğrulama sürecini tetikliyor ve uygulama haftalarca beklemede kalıyor; logosuz publish anında geçiyor. Authorized domain kök alan adı olmalı (`ozbornstudio.com`), alt alan adı değil. |
| ★ VİDEODA HEP AYNI 5 ETİKET BASILIYORDU (4 Eyl 2026) | Kullanıcı: *"reelslerde 5 tane # izin veriyor, açıklama metninde daha fazla var ve ilk 5'i alıp sonrakileri düz metin yazıyor, haliyle sürekli aynı 5 # kullanılıyor"*. Kök sebep tek satır: `caption.SABIT_HASHTAGLER` **tam 5 etiket** taşıyor ve `_hashtaglari_birlestir` onları **başa** koyuyor. ⚠️ **O SIRALAMA CAROUSEL İÇİN DOĞRU** — 30 etiket sığıyor ve kırpma sondan olsun diye bilerek böyle yazılmış; kusur mantıkta değil, o metnin videoya **olduğu gibi kopyalanmasında**. ÖLÇÜLDÜ (4 gerçek yayın): dördünde de sayılan 5 etiket aynıydı (gündem·haber·türkiye·sondakika·gününhaberleri) ve `derbi`, `gemikazasi`, `organnakli` hiç sayılmadı. Üstelik ABD'deki bir tıp haberine **`#türkiye`** basılıyordu — etkisiz değil, YANLIŞ. Çözüm `caption.video_aciklamasi` / `video_etiketleri`: **4 habere özel + 1 etkileşim etiketi**. Gövde (manşet, kaynak, **atıf**) onaylandığı gibi kalıyor, yalnızca hashtag kuyruğu değişiyor — CC BY atıfları hukuken kırpılamaz. |
| ⚠️ Etkileşim etiketi PLATFORMA GÖRE değişir | `config.yaml → sosyal.video_etiketleri`: YouTube **Shorts**, Reels/TikTok **keşfet**. Tek etiket üç platformda aynı işi görmüyor — `#Shorts` YouTube'da gerçek bir format/dağıtım sinyali, Instagram'da hiçbir anlamı yok. ⚠️ **HİÇBİRİ ÖLÇÜLMEDİ** — bunlar inanç, veri değil; bu yüzden koda gömülmedi, değiştirmek tek satır. Doğrulamanın tek yolu bir süre çalıştırıp erişimi karşılaştırmak. |
| ⚠️ Düzeltme DÖRT kod yolunda gerekti | YouTube asıl yayın · YouTube telafi · Instagram Reels telafi · TikTok. İlk üçü `aciklama`/`metin` alıyordu; **TikTok'ta ayrı açıklama alanı YOK**, etiketler başlığın içinde ve orada `#DailyBrief #Haber #SonDakika` **sabit kodluydu** — aynı hastalığın kardeşi. Sözleşme testi dördünü de AST ile denetliyor (`shorts_yukle(aciklama=)`, `reels_yayinla(arg1)`, `tiktok.video_yukle(etiketler=)`). Bu, 1j/1p/1f'nin tekrarı: *bir düzeltmeyi uygularken aynı işi yapan DİĞER kod yolunu da ara.* |
| ⚠️ TikTok başlığı MANŞETİ değil ETİKETİ kırpar | Sınır 150 karakter. Ölçüldü (8 gerçek başlık): manşet + 5 etiket en fazla **142**, hepsi sığıyor. Yine de uzun başlıkta etiket düşüyor, manşet asla kesilmiyor — okuyucu için değerli olan manşet. `tiktok.baslik_kur` bu yüzden **saf fonksiyona ayrıldı**: `video_yukle` içindeyken davranışı sınamanın tek yolu jeton + gerçek dosyaydı, yani hiç sınanmıyordu. |
| ⚠️ TEST, ÖLÇTÜĞÜ KURALI UYGULAYAN FONKSİYONU KULLANMAMALI | Tekrar denetimi ilk yazımda `caption._etiket_anahtari` ile yapılıyordu — yani ölçtüğü kuralın ta kendisiyle. Normalizer kasten silinince `#kesfet #keşfet` tekrarı **gerçekten oluştu** ama test **306/306 TEMİZ** geçti: bozuk fonksiyon hem üretiyor hem denetliyordu. Test `unicodedata` ile **bağımsız** bir normalizasyon kurunca hata anında yakalandı. ⚠️ Bu, görsel alaka kapısındaki döngüsellikle aynı sınıf (`gorsel_konu` 'Trump' olduğu için arama Trump getiriyor, kapı kendini onaylıyordu). |
| ⚠️ Türkçe karakter — DÖRDÜNCÜ kez | `casefold()` `kesfet` ile `keşfet`i ayrı sayıyor ve ikisi yan yana basılıyordu; Gemini aynı kelimeyi bazen şapkalı bazen şapkasız üretiyor. `caption._etiket_anahtari` yalnızca **karşılaştırma anahtarı** üretiyor, basılan etiket orijinal yazımını koruyor. (Önceki üçü: `_sadelestir` Commons soyadı denetimi, `dogrula` İ tuzağı, `_buyuk_harf` TÜRKIYE.) |
| ⚠️ İki test kasten bozulunca YANLIŞ GEÇTİ — veri tuzağı | (1) Tekrar testinin verisinde `kesfet` yoktu, kural hiç sınanmıyordu. (2) TikTok testi *"manşet bozulmadı mı"* diye bakıyordu; sondan kırpan bozuk sürümde 140 karakterlik manşet **yine sağlam** kalıyor, kesilen şey etiketin ortası oluyor (`#besikt`). Doğru ölçüt: çıktıdaki her etiket **TAM** ve verilen listeden olmalı. ⚠️ Beş bozma denendi, ikisi ilk turda yakalanmadı — **bozmadan yazılan test, yazılmamış testtir.** |
| ★ İÇERİK SİNYALİ ASIL AKIŞTA HİÇ ÇALIŞMIYORDU (4 Eyl 2026) | `son_dakika.taze_adaylar` — yani hangi habere Gemini metni üretileceğine karar veren, günde ~20 kez çalışan fonksiyon — düpedüz `ORDER BY agirlik DESC, yayin_tarihi DESC` diyordu. ⚠️ **ÖLÇÜLDÜ: pencereye giren 60 haberin 54'ünün ağırlığı 10**, yani ağırlık neredeyse hep berabere bitiyor ve sıralamayı fiilen **SAF TAZELİK** belirliyordu. Somut sonuç: *"Yaz bitti, işbaşı sendromunu nasıl atlatabilirsiniz?"* (içerik puanı **0**) metin alırken *"Girne'deki gemide can kaybı 12'ye yükseldi"* (içerik puanı **20**) **45. sırada** bekliyordu; *"42 gözaltı"* operasyonu 5., Polonya tren kazası 56. sıradaydı. `_icerik_puani` yıllardır var, bedava ve tam bu iş için yazılmış — bu yolda hiç çağrılmıyordu. |
| ⚠️ İYİLEŞTİRME ÖLÜ KOD YOLUNA YAPILMIŞ | Kusur önce `secim.on_eleme`de arandı ve orada gerçek bir kusur da bulundu (kategorinin 1.'si haber ne olursa olsun tam `katsayi` alıyor; ölçüldü — 7 haberlik `kultur` kategorisinde bir **banka sponsorluğundaki fotoğraf sergisi** ham skoru 32 puan yüksek bir habere galip geliyor). ⚠️ **AMA `on_eleme`'nin TEK ÇAĞIRANI `hazirla.py` ve onun cron'u KAPALI** — son 7 günde 6 kez, hepsi elle. Yani içerik sinyali, kategori katsayısı, üstel sıra cezası… hepsi günde ~1 kez çalışan bir yolda birikmiş, günde ~20 kez çalışan yol ise çıplak kalmış. ⚠️ **BİR KUSURU DÜZELTMEDEN ÖNCE O KOD YOLUNUN GERÇEKTEN NE SIKLIKTA ÇALIŞTIĞINI ÖLÇ** — `gh run list` ve çağıran taraması 10 saniye sürüyor, yanlış yere yapılan iyileştirme haftalarca fark edilmiyor. |
| ★ `secim.on_skor` — sıralamanın TEK KAPISI | `ağırlık×10 − yaş + içerik sinyali`. `on_eleme` ve `taze_adaylar` artık ikisi de bunu çağırıyor. ⚠️ Yaş cezası **saatte 1 puan** — kullanıcı kararı (4 Eyl 2026). Saatte 3 denendi ve ELENDİ: seçilenlerin hepsi 1.5 saatten yeni oluyor ama Girne gemi kazası gibi **gelişerek önem kazanan** haberler düşüyor; tazelik penceresi zaten 8 saat, yani o haber sistemin kendi tanımına göre hâlâ taze. Cezasız (A) varyantı da elendi: seçilen 3 haberin 2'si 7 saatlik çıkıyordu ve "son dakika" etiketiyle 7 saatlik haber paylaşmak ibareyi değersizleştirir. |
| ⚠️ `taze_adaylar`da SQL LIMIT'i KALDIRILDI — bilerek | Puanlama Python'da yapılıyor; `LIMIT` SQL'de kalsaydı yüksek içerik sinyalli ama sıralamada geride kalan haber **hiç puanlanmadan** elenirdi — kardeş görsel havuzunda birebir bu yaşanmıştı (ÖNCE EŞLEŞTİR, SONRA SIRALA). Maliyet ölçüldü: 8 saatlik pencerede **433 satır, 14 ms**. |
| ⚠️ ÖN ELEMEDE KATEGORİ %40 YANLIŞ — yapısal, düzeltilmedi | Ölçüldü (son 4 gün, 30 kayıt): Gemini kategorilerin **%40'ını** düzeltiyor, en sık `turkiye → dunya` ve `turkiye → yasam`. Ön eleme Gemini'den ÖNCE çalıştığı için beslemenin verdiği kategoriyi kullanmak zorunda; gerçekte `yasam` olan bir haber 546 haberlik `turkiye` kovasında yarışıp gömülüyor. ⚠️ Bu aynı zamanda `yasam`ın havuzda niye sadece 11 haberi olduğunu açıklıyor. Çözümü ucuz değil (anahtar kelimeyle kategori tahmini ya da ek LLM çağrısı) ve `db.metin_kaydet` `kategori = COALESCE(?, kategori)` ile beslemenin değerini SİLDİĞİ için geçmişe dönük ölçüm de yapılamıyor. **Açık kusur olarak kayıtta.** |
| ⚠️ ÜÇÜNCÜ KEZ: negatif test verisi yanlış sebeple tetikledi | Ön sınırlama denetimini önce *"düşük ağırlıklı (5) olay haberi seçilmeli"* diye yazdım ve test HAKLI OLARAK kırmızı verdi: ağırlık **×10** çarpanıyla giriyor, 50 puanlık farkı en fazla 20 puanlık içerik sinyali kapatamaz — test, tasarımın hiç vaat etmediği bir şeyi ölçüyordu. Doğru kurgu **aynı ağırlık + daha eski olay haberi**. (Aynı oturumda video etiketi testinde de iki kez oldu.) |
| ★ KURTARMA PANELİNİN İKİ DÜĞMESİ ÖLÜYDÜ (4 Eyl 2026) | `/durum` askıda kalan her tur için **dört** düğme basıyor. `kurtar:{id}` ve `yayin_kontrol:{id}` çalışıyordu ama **`yayinla:{id}` ve `iptal:{id}` hem Worker'ın `eylemMi` beyaz listesinde hem `onay_isle` router'ında YOKTU** — basılınca Telegram *"Tanınmayan komut"* deyip susuyordu. Yani **tur takıldığında açılan kurtarma panelinde, kurtaracak iki düğmenin ikisi de ölüydü.** 4 Eyl'deki *"bir şey bozulduğunda basılan düğmenin kendisi bozuktu"* vakasının aynısı. Üçüncü kusur: Worker'ın kendi menüsündeki **`🚨 Son Dakika Tara`** (`sondakika`) düğmesi de `EYLEMLER`de değildi — Worker kendi bastığı düğmeyi reddediyordu. |
| ⚠️ Düzeltme AYRI DAL DEĞİL, NORMALİZASYON | `onay_isle.main()` `yayinla:{id}` gördüğünde komutu düz adına çevirip `mesaj_id`'yi turunkiyle değiştiriyor; akışın geri kalanı olduğu gibi çalışıyor. Böylece **yayınlanmış-tur koruması (1u), `turu_getir` ve kanal seçimi kendiliğinden devreye giriyor** — ayrı bir dal yazmak o kuralları ikinci kez yazmak olurdu. ⚠️ Önek `yayinla:` (iki noktalı) olmalı: `yayinla_sonra:60` başına takılırsa bot **60 numaralı turu** yayınlamaya kalkar; o "60" dakika. Dört senaryo ölçüldü (`yayinla:656` → #656 · `iptal:777` → #777 · düz `yayinla` → panel id'si · `yayinla_sonra:60` → dokunulmuyor). |
| ★ `test_her_dugme_workerda_karsilaniyor` | Python'un ürettiği HER `callback_data` Worker'da karşılanıyor mu? 95 biçim çıkarılıp Worker **gerçekten yüklenerek** soruluyor. ⚠️ **"Worker reddediyor" tek başına kusur DEĞİL** — menü gezinme komutları (`slayt_menu:`, `kanal:`, `sec:`, `geri:`) bilerek GitHub'a gitmiyor, Worker onları yerel karşılıyor. Ölçüt `eylemMi` değil, **"herhangi bir yerde karşılanıyor mu"**. Test ayrıca **kendi ölçerini de sınıyor**: uydurma bir düğme kabul edilirse denetim her şeye "temiz" der. Üç bozma denendi, üçü de yakalandı. |
| ⚠️ ENVANTER ARACIM ÜÇ KEZ YANLIŞ ALARM VERDİ | Komut listelerini düz metin/regex ile çıkarmaya çalıştım ve üç tur boyunca sahte kusur raporladım: (1) çok satırlı JS dizisini yarım okudum — 23 komutun 4'ünü gördüm ve 9 komutu "Worker tanımıyor" sandım; (2) `ozel:` `dosya:` `ara:` gibi **iki nokta önekli** gönderimleri modellemedim, 7 çalışan komutu "kırık" saydım; (3) `/arsiv`'in **workflow dalında** (`yayinla.yml`) ele alındığını görmedim. ⚠️ **Doğru yöntem: Worker'ı node ile yükleyip `eylemMi`'yi ÇAĞIRMAK.** Kendi ölçüm aracın da bir iddiadır — kanıt değil. |
| ★ TANINMAYAN KOMUT SESSİZCE 0 DÖNÜYORDU (4 Eyl 2026) | `onay_isle.main()` hiçbir dala uymayan komutta fonksiyonun sonuna varıyordu: `None` → `SystemExit(None)` → **çıkış kodu 0**. Job YEŞİL, kullanıcıya mesaj yok, iş yapılmadı. İkinci düşüş noktası daha da yanıltıcıydı: işleyicisi olmayan bir MESAJSIZ komut `turu_getir(con, 0)`e düşüp *"bu mesaj artık geçerli değil"* diyordu — kullanıcı `/kota` yazmış, alakasız cevap alıyor. İki dal da eklendi. ⚠️ **`return 1` DEĞİL**: kırmızı job `hata_bildir`i tetikler ve İKİNCİ bir Telegram mesajı gider; bilgi aynı, gürültü iki katı. Menü geri konuyor, yoksa tur kilitlenir. ⚠️ Ölçüldü: 56 mesajsız komutun **50'si zaten cevap veriyordu**, sessiz düşen yoktu — dal bugün için değil, listeler ayrıştığı gün için. |
| ★ KOMUT DENETİMİ İKİ YÖNLÜ OLMALI | `test_her_dugme_workerda_karsilaniyor` **Python→Worker** (düğme var, Worker tanımıyor); `test_worker_komutlari_python_tarafinda_var` **Worker→Python** (beyaz listede var, işleyicisi yok). İkisi ayrı kusur sınıfı ve **ikisi de gerçekten yaşandı**: birincide kurtarma panelinin iki düğmesi ölüydü, ikincide `android_muzikli` beyaz listede kalmıştı (Android kümesi 4 Eyl'de silinmiş, girdi unutulmuş). ⚠️ Ters yön testi `yayinla.yml`in kendi komut dallarını da modellemeli — yoksa `arsiv` gibi workflow seviyesinde karşılanan komutlar "ölü" raporlanır. ⚠️ Sessiz düşüş denetimi **yapısal**: `main()`in `try` bloğunun son ifadesi `return` mü? Metin araması değil. |
| ★ KOMUTLAR GRUPLANDI — menü · yardım · Worker artık aynı şeyi söylüyor (4 Eyl 2026) | Worker **33 asıl slash komutu** tanıyordu, `KOMUT_MENUSU` yalnızca **21**'ini gösteriyordu: `/haber`, `/tamamla`, `/arsiv`, `/video`, `/fed`, `/makro`, `/menu`, `/haftalik`, `/ayar`, `/tur` çalışıyor ama hiçbir yerde YAZMIYORDU. `/yardim` metni de menüyle tutmuyordu (yardımda `/haber` var menüde yok; menüde `hisse`/`kripto`/`faiz`/`bulten` var yardımda yok). Menü **31 komut / 5 grup** oldu: ✍️ içerik üret · 📰 gündem · 📈 piyasa · 🎛 yönetim · ❓. ⚠️ **Telegram'da gerçek grup YOK** — menü düz liste; gruplama (1) SIRA ve (2) açıklamanın başındaki simge ile yapılıyor. `test_komut_menusu_tutarli` üçünü birden denetliyor. |
| ★ SLASH MENÜSÜ HİÇBİR YERDEN GÖNDERİLMİYORDU | `telegram_bot.komut_menusu_kaydet()` yazılmış ama **hiçbir kod onu çağırmıyordu**. `getMyCommands` ile ölçüldü: Telegram'da 21 komut kayıtlı ve bir zamanlar elle gönderilip orada donmuş. Yani `KOMUT_MENUSU`'ya komut eklemek Telegram'da HİÇBİR ŞEYİ değiştirmiyordu — *"yazılıp okunmayan kayıt"* deseninin menü hâli. Artık günlük raporda çağrılıyor: ucuz (tek HTTP), fikri sabit ve **kendini onaran** — menü elle bozulsa ertesi gün düzeliyor. Sözleşme testi çağrının varlığını AST ile denetliyor. |
| ⚠️ `/menu` PANELİNDE UYDURMA RAKAM VARDI | İki düğmenin `callback_data`'sı koda gömülü veri taşıyordu: `faiz:45 TCMB politika faizini yüzde 45 seviyesinde sabit bıraktı.` ve `enflasyon:61.78 …`. Bu metin `ozel_haber.makro_haber_uret` içinde **doğrudan Gemini prompt'una GİRDİ olarak** giriyor ve yayınlanabilir bir infografiğe dönüşüyor — yani düğmeye basan kişi **hiçbir kaynaktan gelmeyen bir merkez bankası faizi** yayınlıyordu. Projenin en temel kuralına aykırı (`/haber` notu: *kullanıcının yazdığı metinden post üretilmiyor*). Düğmeler artık post ÜRETMİYOR, komutun nasıl yazılacağını gösteriyor (`makro_yardim:` — Worker'da yerel, Actions uyanmıyor). ⚠️ Oranı **kullanıcı yazmalı**: `/faiz 47.5 TCMB faizi sabit`. |
| ⚠️ Düğme taraması WORKER'IN KENDİ düğmelerini de kapsamalı | `test_her_dugme_workerda_karsilaniyor` önce yalnızca Python'daki `callback_data`'ları tarıyordu. `/menu` panelini **Worker basıyor**; `sondakika` düğmesi yalnızca Python'da da tanımlı olduğu için ŞANS ESERİ yakalandı. Worker'a özel bir düğme (örn. `makro_yardim:`) o tarama olmadan görünmez kalırdı. Ölçüldü: 96 Python + 41 Worker düğmesi, 2'si yalnızca Worker'da. |
| ★ WORKER TESTİ DOSYANIN %57'SİNİ HİÇ AYRIŞTIRMIYORDU (4 Eyl 2026) | `test_worker_calisiyor` kaynağı `k.replace(/export default[\\s\\S]*$/,'')` ile kesiyordu. `export default` **528. satırda**, dosya **1234 satır** — yani bütün istek işleyicileri, `/yardim` metni ve düğme panelleri **denetim dışıydı**. Kanıt: `/yardim`i düzenlerken iki dizgiyi `+` olmadan yan yana yazdım (Python'da geçerli, JS'te değil, satır 657); `node --check` TEMİZ dedi, sözleşme testi **326/326** dedi, `wrangler deploy` ise `Expected \")\"` ile PATLADI. ⚠️ Düzeltme: kesmek yerine `export default` → `const _wd =` ataması; tüm dosya ayrıştırılıyor, ek bağımlılık yok. Sınırın **iki tarafına** da hata konarak doğrulandı. |
| ⚠️ `node --check` BU DOSYADA GÜVENİLMEZ — ölçüldü | Aynı hata üç yöntemle sınandı: `node --check` **kaçırdı** · kesilmiş kaynakla `new Function` **kaçırdı** · `export default` ataması ile `new Function` **yakaladı**. (`worker/package.json` yok, yani node dosyayı CJS sanıyor ve `export default`ta durup gerisini görmüyor olabilir.) ⚠️ Kesin doğrulama Cloudflare'in kendi parser'ı: `cd worker && npx esbuild index.js --bundle --format=esm --outfile=/dev/null` — 20 ms sürüyor ve `wrangler deploy` ile aynı sonucu veriyor. **Deploy etmeden önce bunu çalıştır.** |
| ⚠️ Bir doğrulama aracı ne kadarını GÖRÜYOR diye sor | Bu, "testin kendisi kanıt üretemez" dersinin en pahalı hâliydi: test yeşil, `node --check` yeşil, ama canlı derleme kırmızı. Test bir şeyi **okumuyorsa** hakkında hiçbir şey söylemiyor demektir — ve 326/326 görüntüsü tam tersini düşündürüyor. ⚠️ Kaynağı kırpan/filtreleyen her denetimde "kırpılan kısımda ne var?" diye sor. |
| ★ ETİKET KURALI YANLIŞ YERE UYGULANMIŞTI — asıl metin TELEGRAM'DAKİ (4 Eyl 2026) | Kullanıcı: *"telegrama düşen açıklama metnini ben paylaşırken manuel düzenliyorum, instagrama değil de telegrama düşene bak"*. ⚠️ **KAPSAM SORUSUNU YANLIŞ SORDUM**: "Instagram postu mu, video mu" diye sorunca "video" cevabı geldi ve düzeltme yalnızca YouTube/ Reels/TikTok'a uygulandı. Oysa kullanıcının ilk isteği (*"4 tane haberle ilgili hashtag + 1 etkileşim"*) **Telegram onay metnini** kastediyordu — post bot tarafından değil ELLE yayınlanıyor. ⚠️ **Instagram'daki metinlere bakarak ölçüm yapma**: onlar kullanıcının elle düzenlediği hâli, botun çıktısı değil. Belirtisi buydu — IG'de 5 temiz etiket görünüyordu ama DB kaydıyla tutmuyordu (`yasadisipanel` vs `yasadisypanel`) ve `ig_post_id` ile eşleşen kayıt YOKTU. |
| ⚠️ Kullanıcının ELLE yaptığı düzeltme, spec'in kendisidir | Üç yayında da birebir aynı işi yapmıştı: jenerik beşliyi (gündem·haber·türkiye·sondakika·gününhaberleri) silip habere özel etiketleri bırakmak. Bu, "kural nereye uygulanmalı" sorusunun cevabını doğrudan veriyordu. **Kullanıcının tekrar eden elle düzeltmesi bir hata raporu değil, tamamlanmamış bir otomasyondur.** |
| ★ `caption.etiketleri_sec` — etiket kuralının TEK KAPISI | Adı önce `video_etiketleri` idi ve kural yayıldıkça yanıltıcı hâle geldi ("ölü kodun asıl zararı yanlış harita" dersi). Artık dört yer de buradan geçiyor: `son_dakika_caption` · `caption_kur` · `aciklamayi_kur` (YouTube/Reels) · `tiktok.baslik_kur`. Config `sosyal.etkilesim_etiketleri` → youtube **Shorts**, reels/tiktok/instagram **keşfet**. |
| ⚠️ ÇOK HABERLİ TURDA ETİKET SIRAYLA ALINIR | `_hashtaglari_birlestir` etiketleri **haber haber** sıralıyor (önce 1. haberin hepsi, sonra 2.'nin…). Düz `[:4]` dilimi dördünü de İLK haberden alıyordu: 10 haberlik tur yalnızca `#skoda #skodapeaq #elektrikliarac #otomobil` ile etiketleniyor, kalan **9 haber hiç temsil edilmiyordu**. Artık sırayla alınıyor → `skoda · saturn · yasadisypanel · balikesir · keşfet`. ⚠️ Tek haberde davranış DEĞİŞMİYOR. |
| ⚠️ Gemini etiket yazımında hata yapabiliyor | Ölçüldü: `yasadisypanel` (i yerine y). Kullanıcı elle düzeltmiş. Etiketler `ig_hashtag`'ten olduğu gibi alınıyor, yazım denetimi YOK. Küçük ama tekrar edebilir — açık kusur olarak kayıtta. |
| ⚠️ KOMUT MENÜSÜ GRUP KAPSAMINA AYRICA YAZILMALI | Kullanıcı grupta "/" yazınca ESKİ menüyü görüyordu. Ölçüldü: `default` kapsamda 31 komut yazılı ve `getMyCommands` doğruluyordu, ama **`all_group_chats` ve `all_private_chats` BOŞTU**. Telegram komut listesini scope'lara göre çözüyor; `default` teorik olarak hepsini kapsıyor ama istemciler grup sohbetinde grup kapsamını ayrıca sorguluyor. `komut_menusu_kaydet` artık **üç kapsama birden** yazıyor — tek kaynak yine `KOMUT_MENUSU`, kapsam eklemek listeyi çoğaltmak değil. |
| ⚠️ Menü açıklaması telefonda ~40 KARAKTERDE kesiliyor | Gerçek ekran görüntüsüyle ölçüldü: *"/dosya ✍️ Konunun A'dan Z'ye kronolojik do…"* — sondaki kullanım ipucu (`(/dosya <konu>)`) HİÇ görünmüyordu ve 31 açıklamanın **13'ü** sınırı aşıyordu. Çözüm: parametre ipucu **başa** alındı (`✍️ <konu> kronolojik dosya haberi`), hepsi 38 karakterin altına indirildi. Sözleşme testi bunu koruyor. |
| ⚠️ "Komut çalıştı" ile "düzenleme uygulandı" aynı şey değil | Menü kapsam düzeltmesinde ilk yamam **sessizce uygulanmadı** (aranan metin dosyada yoktu) ama fonksiyon yine `True` döndü — eski kod çalışıyordu ve az kalsın "düzeldi" denecekti. Yakalanma sebebi: sonucu API'den TEKRAR okuyunca kapsamların hâlâ boş olduğu görüldü. **Bir düzenlemeden sonra dosyanın değiştiğini ayrıca doğrula** (satır sayısı, anahtar kelime sayısı) — çıktının başarılı görünmesi yetmiyor. |
| ★ KARDEŞ GÖRSEL HAVUZU TEKİL SLAYTTA HİÇ ÇALIŞMIYORDU (4 Eyl 2026) | Kullanıcı: *"ilk gelen görsel kalitesi düşük diye başka fotoğraf butonuna bastım, 2.'si çok genel eski bir fotoydu, 3.'sü alakasız — farklı takım görseli."* İKİ ayrı kusur çıktı. **(1)** `onay_isle`'deki **10 `slayt_uret` çağrısının HİÇBİRİ `con` geçmiyordu**; `con is None` olunca havuz sessizce atlanıyor. Yani 3 Eyl'de kurulup *"voleybolda 24 kat piksel"* diye ölçülen mekanizma tekil slayt üretiminde hiç devrede değildi — düşük çözünürlüğün sebebi buydu. ⚠️ **Sözleşme testi İMZAYI denetliyordu, ÇAĞRIYI değil**: `con=None` varsayılanı taşıyan imza, çağıranın onu geçtiğini göstermez. "Kapı var mı" ile "kapıdan geçiliyor mu" ayrı sorulardır. |
| ★ "BAŞKA FOTOĞRAF" ÖNCE KARDEŞLERİ GEZİYOR | **(2)** `atlanacak > 0` olduğunda og:image katmanı komple atlanıyor ve onunla birlikte kardeş havuzu da gidiyordu; kullanıcı ikinci basışta doğrudan Commons/Pexels'e düşüyordu. ⚠️ **Kullanıcı "bu yanlış" demiyor, "bu kalitesiz" diyor** — en iyi kaynağı terk etmek yanlış cevap. Yeni sıra: og:image → kardeş 1 → kardeş 2 → … tükenince Commons/Pexels. ⚠️ Alternatif seçimi ÇÖZÜNÜRLÜĞE göre değil SIRAYA göre: `atlanacak=0` yolundaki "en büyüğü al" davranışı korundu, ama alternatif isteyen kullanıcıya her basışta FARKLI fotoğraf lazım. CANLI ÖLÇÜLDÜ (GS-Başakşehir): 0→AA Spor · 1→**Borsa Gündem** (eskiden 2008 tarihli tifo) · 2→Pexels. |
| ⚠️ Pexels spor terimi KİMLİĞİ BELLİ FORMA getiriyor | Ölçüldü: `gorsel_temsili` = **`soccer match players stadium`** → Arjantin kulübünün forması. "players" istendiği an başka bir takımın forması gelmesi kaçınılmaz ve Galatasaray haberinin altında bu HATA gibi okunuyor. ⚠️ **Pexels Vision'dan MUAF** (temsili olduğunu söylüyor, ARŞİV ibaresi basılıyor) — yani bu katmanda yanlışı yakalayan hiçbir şey yok. Açık kusur; çözümü prompt'ta nötr sahne istemek (top, saha, file, boş tribün) ama **ölçülmedi**. |
| ★ "BAŞKA FOTOĞRAF" ARTIK ÜÇ ADAY SUNUYOR (4 Eyl 2026) | Kullanıcı isteği: *"başka fotoğraf seçeneğine basınca oluşturmadan önce bana 3 görsel sunsa seçtiğimle devam etsek"*. Eskiden TEK görsel üretilip "kullan / başka dene" soruluyordu; beğenilmezse job baştan uyanıyordu. ⚠️ **MALİYET LEHTE**: her aday ~8-11 sn (slayt + Vision + imgbb), üçü tek job'da ~90 sn; üç ayrı basış ise **üç ayrı Actions uyanması** (~210 sn + kuyruk). Ayrıca tek tek gösterilince *"bu mu daha iyiydi"* diye geri dönülemiyordu — yan yana görmek karşılaştırma sağlıyor. `config → gorsel.gorsel_aday_adedi: 3`. ⚠️ **AI (`slayt_ai`) çoklu üretmiyor** — her aday ~$0.04 ve kullanıcı zaten belirli bir şey istiyor. ⚠️ Aynı URL iki kez gelirse (zincir tükenip aynı Pexels fotoğrafını vermesi) liste şişmesin diye atlanıyor. |
| ⚠️ `sendMediaGroup` INLINE BUTON KABUL ETMİYOR | Albüm ayrı, seçim düğmeleri ayrı mesajda. Telegram kısıtı, tasarım tercihi değil — aynı kısıt onay mesajında da geçerli (bkz. Adım 5). Düğmeler `gorsel_sec:{aday}:{slayt}:{tur_id}` biçiminde ve **tur id'si komuta gömülü**: düğmeler ayrı mesajda durduğu için Worker'ın gönderdiği `mesaj_id` turu göstermiyor (bu tuzak projede beş kez tekrarladı). |
| ⚠️ Aday numarası KULLANICIDAN gelir — aralık denetimi şart | Liste bayatlamış olabilir (tur yenilenmiş, `gorsel_adaylari` silinmiş). O durumda sessizce yanlış görsel uygulamak yerine açıkça söyleniyor. İki koruma var (liste boş mu · numara aralıkta mı); sözleşme testi ikisini birden kaldırarak doğrulandı. |
| ★ TIKTOK'A HİÇ YAYIN YAPILMAMIŞ — hepsi TASLAK (4 Eyl 2026) | `tiktok.video_yukle` önce doğrudan yayını deniyor; reddedilirse **taslak kutusuna** düşüyor ve dönüşte `mod: "inbox_draft"` diyor. ⚠️ **Mesajlar bunu yok sayıp her durumda "yüklendi" yazıyordu.** Ölçüldü: yayınlanmış **TÜM** kayıtların `publish_id`'si `v_inbox_file~` ile başlıyor — yani doğrudan yayın **HİÇ çalışmamış**, 68 postun hepsi TikTok uygulamasında taslak olarak bekliyor ve kullanıcı hepsinde "yüklendi" gördü. ⚠️ CLAUDE.md'nin eski notu HAKLIYDI (*"onaysız uygulamalar yalnızca TASLAK gönderebiliyor"*), GEMINI.md'nin *"doğrudan profile otomatik yayınlanır"* iddiası YANLIŞ. Kalıcı çözüm TikTok **app audit** — kod tarafında yapılamaz. |
| ⚠️ TikTok engeli "izin yok" DEĞİL, **APP AUDIT** — ölçüldü | İlk teşhis *"`video.publish` izni yok"* idi ve **YANLIŞTI**. Jeton tazelenip izinleri okundu: **`video.upload, user.info.basic, video.publish`** — izin ZATEN VAR. Doğrudan yayın uç noktası denendiğinde gelen cevap: **HTTP 403 `unaudited_client_can_only_post_to_private_accounts`**. Yani TikTok'un denetiminden geçmemiş uygulamalar yalnızca **GİZLİ hesaplara** post atabiliyor; @DailyBrief.co herkese açık. ⚠️ **Jetonu tazelemek bunu DEĞİŞTİRMİYOR** — canlı denendi, aynı 403 geldi. Kalıcı çözüm `developers.tiktok.com` üzerinden **app audit başvurusu**; kod tarafında yapılabilecek bir şey yok. |
| ⚠️ Yapılmamış işi başarı diye raporlama — üçüncü tekrar | Threads yarım zinciri, sonra bu. Bilgi ZATEN dönüyordu (`"mod": mod`), tüketen taraf okumuyordu. Mesajlar artık ayırt ediyor: *"TASLAK olarak yüklendi — uygulamadan elle yayınla"* vs *"yayınlandı"*. ⚠️ Düzeltme **İKİ kod yolunda** gerekti (asıl yayın `onay_isle:492` + telafi `onay_isle:894`); sözleşme testi ikisini birden denetliyor (kasten bozularak doğrulandı). |
| ⚠️ Kanal patlaması SESSİZ — artık günlük raporda | Yayın job'ı YouTube hatasını yalnızca **WARNING** olarak loglayıp devam etti. Bu **doğru davranış** (bir kanal patlayınca post yine çıkmalı) ama arıza görünmez oldu; kullanıcı eksik postu gözüyle görünce sordu. ⚠️ **`saglik_testi` fonksiyonları ZATEN VARDI** (`youtube`, `tiktok`, `twitter`) — yalnızca hiç çağrılmıyordu; rapor Instagram ve Threads'e bakıyordu. Kod yazılmış, bağlanmamıştı. Rapor artık açık her kanalı denetliyor; `test_kanal_jetonlari_denetleniyor` bunu koruyor. |
| ★ `son-dakika.yml` ÇİFT TETİKLENİYORDU (4 Eyl 2026) | GitHub `schedule:` cron'ları (`"12 5-20 * * *"`, `"12 23,2 * * *"`) `worker/wrangler.toml`'dakilerle **BİREBİR AYNIYDI** ve Worker zaten `repository_dispatch` atıyordu. Ölçüldü (son 30 çalışma): **22'si Cloudflare'den** (hepsi dakikası dakikasına `:12:55`), **8'i GitHub'dan** (01:05, 07:08, 09:41, 14:28, 18:34, 21:40 — **90 dakikaya varan gecikme**). Yani gereksiz olan taraf aynı zamanda güvenilmez olandı. GitHub cron'ları kaldırıldı: günde ~8 gereksiz çalışma eksildi, `veritabani` kuyruğunda bir yer boşaldı (1ab). |
| ⚠️ Yedeği kaldırınca YOKLUK DENETİMİ ekle | GitHub cron'u aynı zamanda Worker'ın yedeğiydi; kaldırınca **Worker patlarsa saatlik kontrol hiç çalışmaz** ve kimse fark etmez. ⚠️ `basarisiz_isler` bunu YAKALAYAMAZ — o *patlayan* job arıyor, burada job hiç *başlamıyor*. **Yokluk, başarısızlıktan daha sessizdir.** `gunluk_rapor.kalp_atisi_eksik_mi()` eklendi: `son_dakika` 3 saattir hiç çalışmadıysa raporda uyarı çıkıyor. İki durumda da canlı doğrulandı (3 saat → sorun yok · 0 saat → uyarı). |
| ⚠️ Bir özelliği kaldırırken ÜÇ YERİ birden temizle | script · workflow dalı · Worker düğmesi/dispatch listesi. (1h/1k dersinin workflow karşılığı: kaynağı kapatmak ondan gelen KAYITLARI düzeltmiyordu; burada da script'i silmek onu ÇAĞIRANLARI düzeltmiyor.) Kullanıcı kararı: `/ekonomi` ve `ekonomi_hazirla` artık **canlı piyasa özetine** bağlı — `onay_isle`'de zaten çalışan `("piyasa", "piyasa_ozet", "ekonomi")` dalına katıldı. `hata:tur_tekrar` ise CLAUDE.md 1r(b)'ye uygun olarak `hazirla.main()` çağırıyor. |
| ★ `test_0` artık `from scripts import X` biçimini de denetliyor | ⚠️ **KÖR NOKTAYDI:** `modul_adlarini_bul` yalnızca `from src import X` ve `from . import X` eşliyordu; `from scripts import ekonomi_turu` + `ekonomi_turu.main()` **denetim dışı** kalıyordu. Aylardır silinmiş bir modüle yapılan iki çağrı bu yüzden test tarafından görülmedi. Kapsam açılınca denetlenen çağrı **774 → 785** oldu ve **ikinci kaçak (`hata:tur_tekrar`) anında yakalandı** — ilk düzeltmede onu gözden kaçırmıştım. |
| ★ `test_cagrilan_script_var_mi` | Workflow ve Worker'ın çağırdığı her `scripts/*.py` gerçekten var mı? Çağrılan script yoksa job "No such file" ile kırmızıya düşer; kullanıcı düğmeye basar, hiçbir şey olmaz. İki bozma ile doğrulandı. |
| ⚠️ `data/` durum dosyaları DB'ye TAŞINMADI — bilerek | Öneri `son_hata.txt` ve `yedek_anahtar_kullanimi.txt`'yi `ayarlar` tablosuna almaktı; **elendi**. Gerekçe: bunlar **arıza kaydı** ve veritabanı bozulduğunda tam da onlara bakılıyor. Arıza kaydını arızanın içine koymak yanlış. Commit yükü de zaten önemsiz (4 ve 9 commit). |
| ⚠️ Geniş `except Exception` KOD HATASINI yutuyor | Bu bölümü yazarken `json` import edilmemişti ve `except Exception` oluşan `NameError`'ı **sessizce yuttu**: rapor tertemiz göründü, bölüm hiç basılmadı, hiçbir uyarı çıkmadı. Ancak **taze bir kayıt eklenip elle sınanınca** fark edildi. `except` `(OSError, ImportError)` olarak daraltıldı — dosya okunamazsa rapor devam etsin ama KOD hatası yutulmasın. ⚠️ **"Hata vermedi" ile "çalıştı" aynı şey değil; yeni bir raporlama bölümü ekleyince onu tetikleyecek veriyi ELLE üret ve gör.** |
| ⚠️ `from src.X import SABIT` biçiminden kaçın | Bütünlük testinin çözümleyicisi `from src.hata_bildir import HATA_LOG_YOLU` gördüğünde sabiti **modül** sanıp `src.HATA_LOG_YOLU` diye çözmeye çalışıyor ve `HATA_LOG_YOLU.exists()` çağrısına yanlış alarm veriyor. Projenin her yerinde kullanılan biçim: `from src import hata_bildir` + `hata_bildir.HATA_LOG_YOLU`. (Kör nokta dar: yalnızca ithal edilen ad `X.y()` gibi çağrılınca tetikleniyor — `KOMUT_MENUSU` sorun çıkarmıyor.) |
| ★ TAŞIMA GİZLİ BİR HATAYI ORTAYA ÇIKARDI | Taşımadan sonra "ölü ayar" denetimi **`gorsel.haber_gorseli_asgari_genislik/yukseklik`** ikilisini yakaladı. Sebep: o ayarları **yalnızca `test_gorsel_cesitliligi` okuyordu**, üretim kodu hiç bakmıyordu — testler `scripts/` altındayken tarama onları "kullanılıyor" sayıyor ve denetim yıllarca TEMİZ geçiyordu. Boyut kapısı çoktan `gorsel_kalite.gorsel_kalite_denetle`e taşınmıştı. İki ayar kaldırıldı, test **gerçek kapıya** bağlandı. |
| ⚠️ "Ölü ayar" denetimi `tests/`i TARAMAMALI | Bir testin bir config anahtarını anması o ayarı CANLI yapmaz — yukarıdaki vakanın kök sebebi tam olarak buydu. Tarama kapsamı bilerek `src` + `scripts`. ⚠️ Aynı mantık kod denetimleri için de geçerli: **testin kendisi kanıt üretemez.** |
| ⚠️ Yeni kapı ESKİ KURALI koruyor — doğrulandı | `gorsel_kalite` düz genişlik/yükseklik yerine **kırpma sonrası piksel yoğunluğu** ölçüyor (`kirpma_olcegi_hesapla`); 1200x630 ile 630x1200 aynı piksel sayısına sahip ama dikey tuvale kırpıldığında bambaşka sonuç veriyor. CLAUDE.md'deki ölçülmüş kural yeni kapıda sınandı: **1280x720 ✓ · 1200x630 ✓ · 1920x1080 ✓ · 1200x675 ✓ · 864x486 ✗ · 640x360 ✗**. Sözleşme testi artık bunu ölçüyor. |
| ⚠️ Ölü kodun asıl zararı YER değil, YANLIŞ HARİTA | Video "eski görsel kullanıyor" hatası aranırken `handlers/yayin_yonetimi.py` görülüp **"kod ikilemesi var" diye yanlış teşhis kondu**. Üstelik `GEMINI.md` o klasörü *tamamlanmış modüler mimari* olarak anlatıyordu. Ölü kod okuyanı yanlış yöne gönderiyor. `test_7_sozlesme.test_olu_modul_yok` artık `src/` altındaki her modülün en az bir yerden import edildiğini denetliyor. |
| ⚠️ Ölü modül taraması `n.module`'A DA BAKMALI | Bu denetimin ilk yazımında yalnızca `a.name` inceleniyordu ve **`from src.komutlar import KOMUT_MENUSU`** biçimi kaçıyordu (`a.name` = "KOMUT_MENUSU", modül adı `n.module` içinde). Sonuç: `komutlar` ve `zaman` yanlışlıkla "ölü" raporlandı — gerçekte 2 ve 7 yerden kullanılıyorlar. **Az kalsın yaşayan iki modül silinecekti.** Test artık kendi taramasını da sınıyor: bilinen canlı modülleri (`db`, `komutlar`, `zaman`) görebiliyor mu? ⚠️ **Bir şeyi silmeden önce, silme kararını veren ARACIN doğru çalıştığını doğrula.** |
| ⚠️ `.git` 1.6 GB → 85 MB — ama sorun YERELDİ | ⚠️ **İLK TEŞHİS YANILTICIYDI.** `.git` gerçekten 1.6 GB'tı ama `git count-objects -vH` gösterdi ki bunun tamamı **paketlenmemiş gevşek nesne** (`count: 6290, size: 1.60 GiB` · `in-pack: 569, size-pack: 18 MB`). Düz `git gc --prune=now` **85 MB**'a indirdi — geçmişi yeniden yazmadan, `filter-repo` gerekmeden. ⚠️ **UZAKTAKİ GitHub deposu zaten 86 MB'tı** (`gh api repos/... --jq .size`); GitHub kendi paketlemesini düzgün yapıyor. Yani bu bir klon/disk sorunuydu, GitHub kotası sorunu değil. |
| ⚠️ Otomatik `gc` neden hiç çalışmadı | `gc.auto` varsayılanı **6700** gevşek nesne; bizde **6290** birikmişti — **kıl payı altında**. Yerel repoda `git config gc.auto 2000` yapıldı. ⚠️ Bu **yerel bir ayar**, klonlanınca gelmiyor; başka makinede `.git` şişerse önce `git count-objects -vH` ile gevşek/paketli ayrımına bak, `filter-repo`ya atlamadan önce `git gc` dene. |
| ~~Feed ve story için AYRI görsel~~ | **DENENDİ VE ELENDİ (4 Eyl 2026).** Slaytın altında 335px (%17) boş alan var; `dikey_guvenli_pay: 330` yüzünden. Feed'e özel, marjı küçük bir sürüm üretmek önerildi — fotoğraf daha çok yer kaplıyor, yazı büyüyor, ölü alan kayboluyor. **Kullanıcı REDDETTİ**: *"postların profilde standart bir şekilde durması için logoların başlıkların vs konumu sabit olmalı"*. ⚠️ **ÖLÇÜLDÜ VE KULLANICI HAKLI ÇIKTI, üstelik daha güçlü bir sebeple**: profil ızgarası 1080x1920'yi 4:5'e kırpıyor ve **üstten/alttan 285px atıyor**. Marj 110 olan sürümde logo (y≈110) ızgarada TAMAMEN kesiliyor; özet, kaynak satırı ve kanal ikonları da gidiyor, geriye yalnızca başlık kalıyor. |
| ⚠️ `dikey_guvenli_pay: 330` ÜÇ İŞ birden yapıyor | (1) Story'de Instagram'ın yanıt kutusunun altta kalan içeriği örtmesini engelliyor, (2) **profil ızgarasının 285px'lik kırpmasına karşı koyuyor**, (3) her postta logo/başlık/alt bilgi aynı yerde durduğu için hesap tutarlı görünüyor. ⚠️ Bu değeri düşürmeden önce ÜÇÜNÜ birden düşün — ilk bakışta yalnızca (1) görünüyor ve o gerekçeyle küçültmek ızgarayı bozar. |
| ⚠️ Vision YALNIZCA iddia taşıyan katmanlarda | `commons`, `commons_split`, `web_haber` — bunlar *"bu fotoğraf X kişisidir"* diyor. **og:image MUAF**: yayıncı o fotoğrafı o haber için koymuş, konuya bağlılığı yapı gereği garanti. **Pexels MUAF**: temsili olduğunu zaten söylüyor ve ARŞİV ibaresi basılıyor. Her denetim ~5.4 sn ve ~600 token; muafiyetler bunun içindir. |
| ⚠️ Denetim yapılamazsa KABUL — `otomatik_onay`ın TERSİ | Kota/ağ/anahtar yoksa fotoğraf kullanılır. Gerekçe: bu bir **ek güvence**, ön şart değil; soramadık diye postu görselsiz bırakmak, denetimden geçmemiş fotoğraf basmaktan kötü. Gece otomatik yayında "şüphede reddet" doğruydu çünkü orada **insan onayı olmadan yayın** yapılıyor; burada yalnızca fotoğraf seçiliyor ve zaten onaya gidiyor. |
| ⚠️ Yeniden deneme 2 (yani BİR alternatif) | Ölçüldü: Commons'ta aynı kişinin adayları çoğu zaman **aynı çekimden** geliyor (Melissa Vargas'ın dört fotoğrafı da aynı Fenerbahçe maçından) — bağlam uymuyorsa sıradaki de uymuyor. Üçüncü deneme nadiren kazandırıp her seferinde ~7 sn yiyor. |
| ⚠️ Görsel 512px'e küçültülerek gönderiliyor | "Bu fotoğrafta ne var" sorusu için fazlasıyla yeterli. Kardeş havuzu artık 5877x3306 gibi fotoğraflar getirebiliyor; tam boyut göndermek token ve süre yakar. Ölçüldü: 1536x2048 → 52 KB, küçültme 0.02 sn. |
| ⚠️ ONAYLANAN GÖRSEL ≠ VİDEODAKİ GÖRSEL (3 Eyl 2026) | Kullanıcı: *"başka fotolarla yeniden üret dedim ve onu paylaştığımda oluşturduğu videoları eski görüntülerle oluşturdu"*. `video.reels_dikey_gorselleri_uret` öncelik sırası **yerel dosya → yoksa SIFIRDAN yeniden üret → sonra onaylanan URL** idi. Yayın job'ı ayrı runner'da çalışıyor ve `data/output` .gitignore'da olduğu için yerel dosya **HİÇBİR ZAMAN yoktu** — yani her seferinde yeniden üretiliyordu. Üstelik `gorsel_deneme` okunmadan, yani kullanıcının "başka fotoğraf" seçimi yok sayılarak **orijinal fotoğrafla**. Onaylanan imgbb URL'leri parametre olarak GELİYOR ama 2. sıradaydı ve hiç ulaşılmıyordu. Yeni sıra: **onaylanan URL → DB URL → yerel/yeniden üretim**. |
| ⚠️ Bu, "Onaylanan metin ≠ yayınlanan metin" hatasının GÖRSEL KARDEŞİ | 18 Ağu'da `son_dakika_caption()` ile `caption_kur()` ayrışması aynı sınıftaydı: gözden geçirdiğin şey yayına çıkan şey değil, yani onay adımı işlevini kaybediyor. ⚠️ **Genel kural: onaylanan çıktı SAKLANMALI, yayın anında YENİDEN ÜRETİLMEMELİ.** Görsel katmanları deterministik değil — Pexels tekrar engeli, Commons aday sırası ve kardeş havuzu hepsi çalıştırma anına bağlı; aynı girdi aynı çıktıyı vermiyor. |
| ⚠️ Yeniden üretim yoluna düşülürse `gorsel_deneme` OKUNMALI | O kolon kullanıcının "başka fotoğraf" seçimini tutuyor (`atlanacak=deneme`, `haber_gorseli_atla=deneme>0`). Okunmazsa seçim sessizce yok sayılır. `test_onaylanan_gorsel_videoya_giriyor` ikisini de denetliyor: davranış testi (onaylanan KIRMIZI / yereldeki eski MAVİ — çıkan karenin rengine bakılıyor) + AST ile `gorsel_deneme` okunuyor mu. Hata kasten canlandırılarak doğrulandı (kare 31,30,220 çıktı = mavi). |
| ★ FOTOĞRAF SEÇİMİ TEK KAPIDAN — `slaytlar._secimi_uygula` | Video düzeltmesinden sonra **aynı hata iki yerde daha** bulundu: `_urlleri_dogrula_ve_onar` (süresi dolan URL'leri onarırken) ve `src/handlers/yayin_yonetimi.py` (aynı kodun kopyası). Slaytı yeniden üreten **20'den fazla çağrı yeri** var; her birine `atlanacak=` eklemek bir gün unutulur. Çözüm `aday.uygun_mu` ile aynı: kural tek kapıda uygulanıyor — `slayt_uret` ve `son_dakika_uret` artık `gorsel_deneme`'yi **kendileri okuyor**. |
| ⚠️ Varsayılan `0` DEĞİL `None` olmalı | `atlanacak: int = 0` iken "belirtilmedi" ile "orijinali istiyorum" ayırt edilemiyordu. `None` = kayıttan oku, sayı = çağıran açıkça belirtti (o kazanır — "başka fotoğraf" düğmesi sayacı artırıp geçiriyor ve DB henüz eski değeri tutuyor). Altı senaryo ölçüldü: kayıt 0/2, çağrı belirtmemiş/5/0, bozuk değer, kolon yok — altısı da doğru. Sözleşme testi varsayılanın `None` olduğunu denetliyor (kasten `0` yapılarak doğrulandı). |
| ⚠️ ÖNCE EŞLEŞTİR, SONRA SIRALA | İlk yazımda sorgu `ORDER BY agirlik DESC LIMIT 400` idi — en yüksek ağırlıklı 400 satır alınıp içinde eşleşme aranıyordu ve **aynı olayın haberleri o dilimin DIŞINDA kalabiliyordu**. Silivri'de havuzda 1920x1080 vardı, bulunamadı. Şimdi tüm pencere taranıp EŞLEŞENLER ağırlığa göre sıralanıyor. `test_kardes_gorsel_havuzu` bunu **düşük ağırlıklı kardeş** ile denetliyor. |
| ⚠️ İki maliyet freni ŞART | Her aday 0.7-3.8 sn. **(1)** Birincil og:image zaten ≥1600px ise kardeşler hiç taranmıyor. **(2)** Kardeşler arasında ≥1600px bulununca kalanlar taranmıyor — bu ikincisi voleybol maliyetini **+5.1 → +1.7 sn** düşürdü, sonuç aynı kaldı. Kardeşi olmayan rutin haberde ek maliyet **sıfır**. |
| ⚠️ `con` DÖRT fonksiyonda taşınmalı | `arkaplan_sec` · `slayt_uret` · `tur_uret` · `son_dakika_uret`. Bir halka `con`'u düşürürse kardeş havuzu **sessizce devre dışı kalır**, hata vermez. Sözleşme testi dördünü de imza üzerinden denetliyor (kasten düşürülerek doğrulandı). |
| ⚠️ Kardeş testinin verisi TUZAKLI | İlk yazımda "alakasız haber" olarak *"Ankara açıklarında hava durumu raporu"* kullanıldı ve **ortak özel isim şartı kaldırılınca test yine geçti** — çünkü o başlık zaten kelime sayısından eleniyordu, şart hiç sınanmıyordu. Doğru veri **3 ortak kelime taşıyıp ortak özel ismi olmayan** bir başlık: *"Marmara açıklarında yolcu gemisi kayalıklara çarpıştı"*. ⚠️ **Negatif test verisi, elemeyi DOĞRU SEBEPLE tetikliyor mu diye kontrol edilmeli.** |
| ⚠️ Yansıma hem SOLMALI hem BULANIKLAŞMALI | Sabit opaklıkta ayna görüntüsü yapay duruyor; gerçek su yansıması aşağı indikçe hem kaybolur hem dağılır. ⚠️ **Blur tek seferde uygulanamaz** — o zaman yansımanın ÜST ucu da bulanıklaşır ve birleşme yeri yine belli olur. Şerit 12 banda bölünüp her banda kendi yarıçapı veriliyor (0.6 → 5.6). |
| ⚠️ Bu testi KOD METNİNE bakarak yazma | `test_fotograf_alt_kenari_keskin_degil` **davranışa** bakıyor: küçük kaynakla slayt üretiyor ve fotoğrafın bittiği noktanın iki yanındaki parlaklık farkını ölçüyor (< 60 birim olmalı). Fonksiyon adı değişse, efekt başka yolla yapılsa bile geçerli kalır. Kasten yansıma kapatılarak doğrulandı. |
| ⚠️ BÜYÜTME TAVANI ZORUNLU | Zoom oranı = `hedef_yükseklik / kaynak_yükseklik`. 1200x709'luk tipik OG fotoğrafı 1150'ye çıkarken **1.62x** büyüyor ve temiz kalıyor; küçük kaynakta aynı hedef yumuşama yaratır. `FOTO_AZAMI_BUYUTME = 1.9` — fotoğraf yeterince büyük değilse **daha AZ iniyor**. Bulanık basmaktansa kısa dursun. (Ölçüldü: 2730x1536 ve 4496x2529 kaynaklar zaten 1x altında, hiç büyütülmüyor.) |
| ⚠️ Perde eğrisi SMOOTHSTEP | Kullanıcı: *"alt ve üst arasında renkleri bağlayıcı, biraz daha soft geçiş"*. Eski eğri `t**1.8` idi ve **başlangıcı keskindi** — türevi 0 noktasında sıfır olmadığı için perdenin başladığı yer ince bir çizgi olarak görünüyordu. `t*t*(3-2t)` iki uçta da türevi sıfır: ne başladığı ne bittiği belli oluyor. Perde fotoğrafın bittiği yerin ÜSTÜNDE (700) başlıyor ki fotoğrafın alt kenarı düz çizgi olarak durmasın. |
| ⚠️ Perde maskesi 262x hızlandı | Eski kod her piksel için `putpixel` çağırıyordu: 1080x1920 = **2 milyon Python çağrısı**, ölçüldü **0.78 sn/slayt**. Degrade yalnızca Y'ye bağlı olduğu için 1 piksel genişliğinde üretilip yatayda geriliyor → **0.003 sn**. `test_7_sozlesme` putpixel'in geri gelmesini AST ile engelliyor. |
| ⚠️ ÜÇÜNCÜ KEZ: düz metin araması docstring'e takıldı | Bu oturumda üç ayrı denetim önce düz metin aramasıyla yazıldı ve üçü de YANLIŞ SONUÇ verdi — çünkü aranan kelime aynı dosyanın `#` yorumunda ya da docstring'inde geçiyordu (`web_gorsel_ara`, `sonucu_yaz`, `putpixel`). **Kod denetimi yapan test AST kullanmalı**: yorumlar AST'de hiç bulunmaz, docstring ise `Constant` düğümüdür ve çağrıyla (`Attribute`) karışmaz. |
| ⚠️ ÖLÇÜM METODOLOJİSİ TUZAĞI | İlk teşhis *"gorsel_konu %46 yanlış"*ydı ve YANLIŞTI: örneklem **eski prompt'la üretilmiş** kayıtlardan geliyordu (prompt 31 Ağu ve 2 Eyl'de düzeltilmiş). Aynı makaleler bugünkü prompt'la denendiğinde "Ünal Üstel" yerine **"FİLOJET feribotu"**, "Haluk Görgün" yerine **"HÜRJET"** geldi. ⚠️ **Veritabanındaki üretilmiş alanlara bakarak prompt kalitesi ölçerken, o kaydın HANGİ PROMPT SÜRÜMÜYLE üretildiğine bak.** |
| ★ GÜNCELLİK: doğru kişinin ESKİ fotoğrafı da yanlıştır | Kullanıcı uyarısı (3 Eyl 2026): Vlahovic bu sezon **Beşiktaş'ta** ama Commons fotoğrafı Juventus formalı; Özgür Özel **YENİ Parti** genel başkanı ama model/insan hafızası onu CHP'de biliyor. `gorsel_baglam` bunun için var ve **yalnızca MAKALE METNİNDEN** doldurulur — hafıza bayat, makale güncel. Canlı doğrulandı: Beşiktaş derbi haberinde model `baglam: "Beşiktaş forması"` üretti. |
| ⚠️ Bağlam POZİTİF SEÇİM, negatif eleme DEĞİL | Bağlamı tutan adaya puan veriliyor (+45/kelime), tutmayan ELENMİYOR. Sebep: arşivde o bağlamda hiç fotoğraf olmayabilir ve o zaman eski fotoğraf, hiç fotoğraf olmamasından iyidir. ⚠️ **ETKİSİ ARŞİV ÇEŞİTLİLİĞİNE BAĞLI — ölçüldü:** Hakan Fidan'da işe yaradı (2026 fotoğrafı 2024'ün önüne geçti), ama **Vlahovic ve Melissa Vargas'ta ETKİSİZ** çünkü Commons'ta sırasıyla tek fotoğraf ve tek maçtan seri var. Sıralayacak alternatif yoksa sıralama değişmez. O vakaların gerçek çözümü Vision denetimi (İş 5). |
| ⚠️ Brief alanları DÖRT yerde yaşıyor | `CEVAP_SEMASI.properties` · `CEVAP_SEMASI.required` · `PROMPT` · `db.EK_KOLONLAR` + `metin_kaydet` SQL. Biri unutulursa **hata VERMEZ, alan sessizce NULL kalır**. `test_7_sozlesme.test_gorsel_brief_dort_yerde_tanimli` dördünü de denetliyor (kasten bozularak doğrulandı). Ayrıca şema `enum`'u ile `db.OZNE_TIPLERI` beyaz listesi AYNI olmalı — ayrışırsa geçerli değer sessizce elenir. |
| Haber çeşitliliği (18 Ağu 2026) | **İki kusur birlikte çözüldü.** (1) 8 kaynağın 6'sı Türkiye gündemiydi; bilim/teknoloji/spor/kültür/ekonomi kaynağı YOKTU, o konular seçime giremiyordu. 8 kaynak eklendi (AA ×4, NTV ×2, Habertürk ×2), 8/8 test edildi. (2) Seçim düz skor sıralamasıydı, aynı olayın haberleri üst üste diziliyordu — 16 Ağu turunda 10 haberin 6'sı İsrail/Gazze, 8'i tek kaynaktan. `secim.cesitlendir()`: aynı olaydan tek haber, kategori başına 3, kaynak başına 4. Ölçüldü: turkiye 8→4, tek kaynak 7→4, kategori çeşidi 3→7. **Kurallar turu eksik bırakmıyor**, havuz darsa gevşetiliyor. |
| ⚠️ Kaynak eklemeden ÖNCE ölç | `python scripts/kaynak_dogrula.py <url> <kategori>`. **Besleme adının kategoriyi doğru verdiğine GÜVENME.** TRT'nin "teknoloji" beslemesi 0/10 doğru kategori veriyordu (gündem 5, dünya 3) ve "Mustafa Bozbey CHP'den istifa etti" haberi slaytta **TRT TEKNOLOJİ** etiketiyle yayınlandı. Araç ayrıca tazeliği (TRT spor beslemesi 11 GÜN eskiydi) ve örtüşmeyi (Milliyet'in iki beslemesi birebir aynı) ölçüyor. |
| ⚠️ Kaynak sırası | **Kategori beslemeleri config'de ÖNCE.** `haberler.link` UNIQUE ve ilk gelen kaynak kazanıyor; genel akışlar (TRT sondakika, AA guncel) tüm kategorileri içerdiği için önce çekilirlerse ekonomi/bilim/kültür haberlerini "turkiye" etiketiyle kaydediyor ve kategori beslemeleri komple tekrar sayılıp eleniyor. Ölçüldü: 7 kaynaktan HİÇ haber girmemişti. |
| ⚠️ Magazin kaynağı YOK | Bilerek. İlgi çekiyor ama doğruluk riski yüksek ve dört katmanlı denetim dedikoduyu ayıklayamıyor. İstenirse `config.yaml → kaynaklar`'a eklenir. |
| Slayt düzeni (18 Ağu 2026) | Fotoğraf üstte NET, aşağı doğru `gorsel.perde_rengi`'ne dönüşüyor; **açıklama ve alt bilgi düz renk şeritte**, başlık FOTOĞRAFIN üstünde. Başlık okunmasını **gerçek bulanık gölgeden** alıyor (GaussianBlur) — eski 2px kaydırma açık/kalabalık fotoğrafta yetmiyordu. Başlık tavanı **72** (96→80→72; başlık fotoğrafı örttüğü için yer kaplaması artık doğrudan maliyet). |
| ⚠️ Kategori renkleri | `arkaplan_uret_yedek` her kategori için ayrı gradyan taşıyor. Yeni kategori eklerken **buraya da renk ekle**, yoksa sessizce "turkiye" rengine düşer. Tonlar bilerek yakın ve koyu: carousel kaydırılırken slaytlar farklı hesaptan gelmiş gibi durmasın. |
| ⚠️ Instagram medya hatası GEÇİCİ | `2207052` / `2207003` ("Only photo or video can be accepted" — mesaj yanıltıcı, Türkçesi doğruyu söylüyor: *medya indirme başarısız*). Instagram görseli imgbb'den KENDİSİ çekiyor ve o çekme patlıyor; görselde kusur yok. 18 Ağu'da bir tur 3 denemede geçemedi, 2 dakika sonra elle denendiğinde 5/5 sorunsuz yüklendi. `MEDYA_AZAMI_DENEME = 6` + **sabit** 15 sn bekleme (artan bekleme çözmüyor — Threads'te ölçüldü). ⚠️ `deneme_sayisi` config'de tanımlıydı ama kod onu HİÇ OKUMUYORDU, `range(1,4)` sabitti. |
| ⚠️ Instagram'da MÜZİK yok | Doğrulandı (18 Ağu 2026): `audio_name` parametresi var ama **yalnızca Reels için**. Foto ve carousel postlarına API'den müzik eklenemiyor; müzik kütüphanesi sadece resmi uygulamada. Müzikli haber hesapları postu ELLE paylaşıyor. Politika kısıtı, aşılamaz. |
| ⚠️ Commons'ta "başka fotoğraf" katman değiştiriyor (21 Ağu 2026) | Kullanıcı *"resmi değiştir dediğimde aynısı geldi"* dedi. Ölçüldü: **"Melissa Vargas" aramasının Commons'taki BÜTÜN adayları aynı maçtan** (Fenerbahçe forması, dosya 1-2-3-4) ve `adaylar[atlanacak % len]` modulo ile dönüyordu — düğme aynı serinin bir sonraki karesini veriyordu. Üstelik haber **milli takım** haberiydi, kulüp forması tutarsız duruyordu. `AZAMI_AYNI_KISI = 3`: üç denemeden sonra Commons atlanıyor ve Pexels'e düşülüyor. Doğrulandı — #0-2 commons, #3+ pexels. |
| Commons kuralı | **`gorsel_konu`ya SADECE kişi adı yazılır, kurum/örgüt/şehir ASLA.** Ölçüldü: "İSKİ"→Macar sanatçı portresi, "Taliban"→askeri harita, "Ankara Büyükşehir"→kale manzarası. Bunlar yayınlanamaz. Kurumu Pexels temsil ediyor ve iyi çalışıyor. |
| Caption | Tek post, 10 haber → `src/caption.py`. Tarih + numaralı manşet listesi + kaynaklar + atıf + hashtag. Sınır 2200 karakter / 30 hashtag; aşarsa sırayla hashtag → atıf → son maddeler kırpılır. |
| Atıf politikası | Commons atıfları **tek tek** yazılır (CC BY hukuken şart). Pexels'ler **tek satırda** toplanır — lisansı atıf istemiyor, 9 ayrı satır 700 karakter yiyordu. |
| ⚠️ Filtre SLAYTTA da çalışıyor (21 Ağu 2026) | Önce yalnızca caption'daydı; kullanıcı benzer hesapların (mhahaber) **görselin üstünde** sansürlediğini gösterip aynısını istedi. `icerik_filtresi.gorselde: true` + `slaytlar._slayt_metni()`. Slayt, story ve detay başlıkları filtreden geçiyor. ⚠️ **Vurgu rakamı kontrolü (satır ~431) HARİÇ** — orada başlık iç karşılaştırmaya giriyor, yıldızlı metin rakam eşleşmesini bozar. |
| ⚠️ FİLTREYE KISA KÖK YAZMA | Ölçüldü: `"vur"` → *v\*rgu, v\*rgun* · `"öl"` → *ö\*çüm, ö\*çek* · `"kan"` → *k\*nser, k\*nun, k\*nıt*. Kökler spesifik olmalı (`öldür`, `ölüm`, `vurarak`, `cinayet`, `ceset`…). 21 Ağu'da eklenen 16 kökün tamamı *"Ölçüm sonucu kanser taraması kanunla kanıtlandı, vurgu yapıldı"* cümlesinde sıfır yanlış eşleşme veriyor; `test_7_sozlesme` bunu denetliyor (kasten `öl` eklenerek doğrulandı). ⚠️ "hayatını kaybetti" gibi yumuşak ifadeler BİLEREK listede yok — onlar zaten riskli değil. |
| İçerik filtresi | Instagram shadowban'ine karşı `src/filtre.py`: riskli kelimeler yıldızlanır ("taciz"→"tac*z"), kısıtlı hashtag'ler **tamamen atılır** (etikette yıldız işe yaramaz). Liste `config.yaml`'de ve **bilerek kısa** — ölüm/kaza/cinayet gibi gündelik haber kelimeleri YOK, aşırı sansür amatör gösteriyor. |
| ~~Haber sitesi fotoğrafı kullanılmıyor~~ | **KARAR DEĞİŞTİ (18 Ağu 2026), artık KULLANILIYOR.** 15 Ağu'da telif riski anlatılıp vazgeçilmişti. Kullanıcı benzer hesapların bu görselleri rahatça kullandığını görüp yeniden istedi; risk ikinci kez anlatıldı ve karar kullanıcınındır. Ayrıntı: "⚠️ Haber görseli" satırı. Telif riski ortadan KALKMADI — yalnızca kabul edildi. |
| Beğenilmeyen görsel | Telegram'a **`🎨 Görseli AI ile üret`** butonu eklenecek. Varsayılan bedava katman; AI maliyeti ancak kullanıcı basarsa oluşuyor. |
| Slayt yazısı | Başlık + altında küçük puntoyla **tek cümlelik özet** (`slayt_ozet`). |
| ★ Önem puanı (18 Ağu 2026) | Prompt'un puan bandı örnekleri **yalnızca siyasiydi** ("9-10 = ülke gündemini belirleyen olay") ve model ölçeği ona kalibre ediyordu. Sonuç: "UltrAslan lideri uyuşturucu testi pozitif" 6, "James Webb 3 kara delik keşfetti" 6 alırken "Bakan X konuyu değerlendirdi" 7 alıyordu — tur resmi açıklamalarla doluyor, insanların okuduğu haberler 5-6 bandında bekliyordu. 7-8 bandına siyaset dışı çapalar yazıldı (bilim keşfi, sağlık uyarısı, büyük kaza, spor sonucu, tanınan ismin karıştığı olay) ve **açıklama/olay ayrımı** eklendi: "değerlendirdi/kınadı/temenni etti" 3-5, "karar alındı/yasa çıktı" yüksek. ⚠️ **ÖLÇÜLMEDİ** — Gemini kotası dolduğu için A/B testi yapılamadı, ilk fırsatta yapılmalı. |
| ★ Başlık kuralı | **Başlık haberin SONUCUNU söylemek zorunda.** Takipçiye link vermiyoruz, okuyacağı başka yer yok — slaytı kaydırıp geçen kişi haberi ÖĞRENMİŞ olmalı. "…ilişkin açıklama", "…değerlendirdi", "…anlattı" gibi 15 kalıp prompt'ta YASAK; `dogrula.basligi_denetle()` yakalayıp uyarıyor. Abartı ("şok", "bomba") da yasak — güveni düşürüyor. Ölçüldü: "Bakan Göktaş'tan taciz iddialarına ilişkin açıklama" → "…iddialarının vahim olduğunu belirtti". |
| `/haber <konu>` (20 Ağu 2026) | Telegram'a yazılan konu **havuzda aranıyor**, bulunanlar öneri olarak sunuluyor. ⚠️ **Kullanıcının yazdığı metinden post ÜRETİLMİYOR** — projenin en temel kuralı "yalnızca kaynak metinde yazanı kullan"; tek cümlelik istekten haber metni üretmek tam da onun yasakladığı şey, üstelik çıktı gerçek haber gibi görüneceği için en tehlikeli biçimde. Seçilen haberin metni her zaman kendi kaynağından üretiliyor. Arama skoru başlıkta geçmeye 10, özette geçmeye 2 puan veriyor; hiçbir kelimesi başlıkta geçmeyenler eleniyor (ölçüldü: bu eşik olmadan "asgari ücret" araması üç alakasız haber döndürüyordu). |
| `/guncelle` (21 Ağu 2026) | RSS'i **hemen** tarar, bir sonraki cron'u beklemez. Kullanıcı sabah duyduğu bir haberi arayıp bulamayınca istedi. ⚠️ **METİN ÜRETMİYOR** — yalnızca RSS çekiyor; Gemini kotası günde 20 ücretsiz istek ve elle tetiklenen her güncellemenin metin üretmesi kotayı bitirir. Çekilen haberler `durum='yeni'` olarak `/haber` aramasında zaten görünüyor. Arama sonuç vermezse mesaja **"🔄 Haber havuzunu güncelle"** düğmesi konuyor. |
| ⚠️ `/haber` YAZIM TOLERANSI | *"netenyahu"* aranınca havuzdaki **22 Netanyahu haberi** bulunamıyordu — arama tam eşleşme yapıyor. `difflib` ile benzerlik eklendi (`YAZIM_BENZERLIGI = 0.85`). ⚠️ **YALNIZCA HİÇ SONUÇ ÇIKMAYINCA** devreye giriyor: ölçüldü, doğru eşleşmeler 0.80-0.95 ve yanlış eşleşmeler 0.60-0.88 aralığında ve **çakışıyorlar** (*kayseri/kayseride* 0.88 yanlış, *trump/trumb* 0.80 doğru). Tek eşikle ayrılmıyorlar; sıralama çözüyor — "kayseride" zaten tam eşleşmede bulunuyor. 5 harften kısa kelimelerde hiç denenmiyor. ⚠️ **DİZİ BENZERLİĞİ TEK BAŞINA YETMİYOR** — harf SIRASI karışınca çöküyor: *"netenhay"/"netanyahu"* yalnızca **0.59** alıyor (hay ↔ yah). Sıradan bağımsız **harf kümesi** ölçütü eklendi (aynı çift 0.86). ⚠️ O da tek başına gevşek: ilk denemede "netenhay" **42 sonuç** getirdi ve ilki alakasızdı — **ilk üç harfin tutması** şartı eklendi. Dört yazım varyantı da (netenhay, netenyahu, netanhayu, netanyahu) artık aynı 24 sonucu veriyor. |
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
| ⚠️ `node --check` WORKER'I DOĞRULAMAZ | 21 Ağu 2026: bir düzenlemede satır sonları gerçek newline yerine **literal `\n`** yazıldı; `const HABER_SEC = …` satırı bir `//` yorumunun İÇİNDE kaldı. Sözdizimi kusursuzdu, `node --check` temiz geçti, ama Worker canlıda `ReferenceError: HABER_SEC is not defined` ile **500** döndü ve Telegram'daki HİÇBİR düğme çalışmadı. Belirtisi: `getWebhookInfo` → *"Wrong response from the webhook: 500"* ve Actions'ta **hiç `repository_dispatch` yok**. `test_7_sozlesme` artık Worker'ı gerçekten yükleyip `eylemMi`'yi çağırıyor. ⚠️ Teşhis sırası: (1) `webhook_kur.py --durum`, (2) `wrangler tail` ile canlı hata, (3) `wrangler deployments status` ile canlı sürüm. |
| ⚠️ WORKER GIT'LE DEPLOY OLMUYOR | `worker/index.js` değiştirilip push edilince Cloudflare'e **gitmiyor** — ayrı bir servis. `cd worker && npx wrangler deploy` şart. 19 Ağu 2026'da unutuldu: yeni `hazirla:` butonu Telegram'da "tanınmayan komut" verdi, kod doğruydu ama Worker eski sürümdeydi. Belirtisi tam olarak bu: buton çalışmıyor ama Actions'ta hiç kayıt yok, çünkü istek GitHub'a hiç ulaşmıyor. |
| ⚠️ Menü ikilemesi | Buton düzeni **iki yerde** tanımlı: `src/telegram_bot.py` ve `worker/index.js`. Birini değiştirirsen diğerini de değiştir. Slayt sayısı `callback_data`'ya gömülü (`slayt_menu:10`) — Worker'ın turda kaç slayt olduğunu bilmesinin başka yolu yok. |
| ⚠️ VERİTABANI TEMİZLİĞİ (21 Ağu 2026) | Önce **hiç temizlik yoktu**: 8 günde 3134 kayıt birikti ve **`.git` 237 MB** oldu — `haber.db` her job'da commit ediliyor ve ikili dosya git'te sıkışmıyor. Ölçüldü: **30 MB/gün**, 6 ay sonra ~5 GB (GitHub yumuşak limiti). `db.eski_kayitlari_temizle()` günlük raporda çalışıyor, `genel.kayit_saklama_gun: 7`. ⚠️ **YAYINLANMIŞ HABER ASLA SİLİNMEZ** — mükerrer engeli geçmişe bakıyor, silmek 1j/1z'yi geri getirir. ⚠️ `VACUUM` yalnızca 100+ kayıt silindiyse: dosyanın tamamını yeniden yazdığı için git'in delta sıkıştırmasını bozuyor. ⚠️ **Actions etkilenmiyor** — `actions/checkout@v4` sığ klon yapıyor (fetch-depth 1), job'lar 237 MB indirmiyor. ⚠️ Temizlik geçmişte birikmiş `.git` boyutunu KÜÇÜLTMEZ, yalnızca büyümeyi durdurur. |
| Secrets | `.env` (yerel) + GitHub Actions Secrets (uzak). Koda gömülmez. |

---

## 4. ŞU ANKİ DURUM

### 🟢 BOT YAYINDA — son güncelleme 4 Eylül 2026

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
✅ **YAPILDI** — günlük rapor artık `💰 ÜCRETLİ ANAHTAR: bugün N, toplam M kez` satırını basıyor (4 Eyl 2026'da doğrulandı).

**GitHub Actions:** 7 günlük ölçümle **1356 dk/ay**, private repo
kotası 2000 dk/ay → şu an **$0**, ama pay yalnızca %32. Aşım
Linux'ta $0.008/dk. Sıkışırsa `son-dakika.yml` cron'u 2 saatte bire
çekilir (bkz. 1b).

---

### 4b. GEMINI.md'DEN DEVRALINAN MİMARİ (4 Eyl 2026'da doğrulandı)

Proje bir dönem Gemini ile geliştirildi ve o oturum kendi notlarını
`GEMINI.md`'ye yazdı. Aşağısı o dosyadan alınıp **kod üzerinde tek tek
doğrulanmış** kısımdır. ⚠️ Doğrulanmayan iddialar da vardı, onlar
"GEMINI.md YANILIYOR" başlığı altında.

**YAYIN MODELİ DEĞİŞTİ — akşam çoklu tur KALDIRILDI.**
`hazirla.yml`'in `schedule:` cron'u yorum satırına alınmış. Artık gün
boyu saat başı Telegram'a **5 haber önerisi** düşüyor, seçilen haber
**1 kapak + 2-3 detay slaytı** olarak üretiliyor. ⚠️ Bu, CLAUDE.md'nin
üst kısmındaki "günde 2 tur" satırlarını GEÇERSİZ kılıyor; `secim.py`,
`caption.py` ve `cesitlendir()` artık yalnızca elle tetiklenen turlarda
çalışıyor.

**CLOUDFLARE EDGE CRON — asıl zamanlayıcı artık Worker.**
`worker/wrangler.toml` → `crons = ["8 7 * * 1-5", "20 15 * * 1-5",
"12 5-20 * * *", "12 23,2 * * *"]`. Worker `scheduled()` içinde
`repository_dispatch` atıyor: ilk iki cron `piyasa_bulteni`
(açılış/kapanış), kalanlar `son_dakika_calistir`.
⚠️ **Ölçüldü (4 Eyl 2026) — Cloudflare GitHub'dan ÇOK daha dakik:**
22 dispatch'in hepsi saat başı `:12:55`'te; GitHub'ın kendi
`schedule:`'ı ise 01:05, 07:08, 09:41, 14:28, 18:34, 21:40'ta —
**90 dakikaya varan gecikme**.

**PİYASA BÜLTENİ ALT SİSTEMİ** (CLAUDE.md'de hiç yoktu):
`src/piyasa.py` (Yahoo Finance canlı veri), `src/piyasa_kart.py`
(ısı haritası), `src/piyasa_tablo.py` (30 varlık karnesi),
`src/sparkline.py` (trend grafiği), `scripts/piyasa_otomatik.py`.
Hafta içi iki bülten. ⚠️ **Saat penceresi kodda sabit**
(`piyasa_otomatik.py:84-88`): açılış **09:55-11:30**, kapanış
**18:15-20:00** TR. Bu pencerelerin dışında yayın reddediliyor.

**ÖZEL HABER MOTORU** — `src/ozel_haber.py`: `/dosya`, `/kronoloji`,
`/link`, `/arastir`, `/ozel`. Verilen konunun kronolojisini derinlemesine
bültene çeviriyor.

**GÖRSEL KALİTE DENETİMİ** — `src/gorsel_kalite.py`: çözünürlük eşiği
(800x450 / 600x600), Laplacian netlik varyansı (≥35), taranmış
belge/PDF filtresi (doygunluk ≤15 **ve** parlaklık ≥175),
`kristal_netlestir` (UnsharpMask).

**VİDEO HATTI** — `src/video.py` + `youtube.py` + `tiktok.py`.
TikTok doğrudan profile yayınlıyor (Inbox'a düşmüyor). Sessiz videoya
**stereo AAC ses izi** gömülüyor (yoksa platformlar ikincil transcode
kuyruğuna atıp bildirimi geciktiriyor), 2 sn'lik sabit GOP
(`-g 60 -keyint_min 30 -sc_threshold 0`) ve `+faststart` moov atomu.
⚠️ **Hiçbir workflow video/youtube/tiktok çağırmıyor** — yalnızca
`onay_isle` üzerinden, yayın anında tetikleniyor.

**Alan adı:** `ozbornstudio.com` projeye ait; alt alan adları
(webhook, CDN, görsel barındırma) Cloudflare DNS'ten açılabilir.

---

### ⚠️ GEMINI.md YANILIYOR — kodla ölçülüp düzeltilen iddialar

| GEMINI.md ne diyor | Gerçek (4 Eyl 2026 ölçümü) |
|---|---|
| `STORY_GUVENLI_PAY = 285px` | **330.** `make_image.py:1288` ve `config.yaml:325`. |
| *"GitHub Actions'ın kendi `schedule:` cron'ları tamamen kaldırılmıştır"* | **KALDIRILMAMIŞ.** `son-dakika.yml` hâlâ `"12 5-20 * * *"` ve `"12 23,2 * * *"` taşıyor — Worker'ın cron'larıyla **birebir aynı**. Sonuç: aynı iş iki kaynaktan tetikleniyor, son 30 çalışmanın 8'i GitHub'dan gelmiş. Fazladan ~8 çalışma/gün. |
| *"Modüler Handler Katmanı (`src/handlers/`)"* tamamlanmış gibi anlatılıyor | **TERK EDİLMİŞ REFACTOR.** `slayt_yonetimi.py` 26 satır, `tur_yonetimi.py` 28 satır — ikisinde de **hiç fonksiyon yok**, sadece docstring ve import. `yayin_yonetimi.py` 158 satır ama **hiçbir yerden import edilmiyor**. `onay_isle.py` (3815 satır) hâlâ her işi kendi yapıyor. |
| 4 katmanlı görsel hiyerarşisinde **1. katman `fetch_web_image`** | **DEĞİŞTİ (3 Eyl 2026).** DuckDuckGo araması varsayılan olarak KAPALI ve zincirin SONUNA alındı. Gerekçe yukarıdaki "★ İNTERNET GÖRSEL ARAMASI KAPATILDI" satırında. |
| *"`gorsel_konu` … `Beşiktaş`, `Boeing 737`, `Silivri gemi kazası`"* | Kısmen geçerli ama artık `gorsel_ozne_tipi` ile birlikte çalışıyor; olay haberlerinde `konu` boş bırakılıp doğrudan temsili fotoğrafa gidiliyor. |

⚠️ **DERS:** iki ayrı yapay zeka oturumu iki ayrı doküman tutmuş ve
ikisi de kendi bildiğini "güncel" sanıyor. **Doküman iddiası kanıt
değildir** — bir davranışa bel bağlamadan önce kodda doğrula.

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
✅ **YAPILDI** — günlük rapor artık `💰 ÜCRETLİ ANAHTAR: bugün N, toplam M kez` satırını basıyor (4 Eyl 2026'da doğrulandı).

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

**1aa. ⚠️ ÜÇ SERVİS DE GEÇİCİ HATASINI 400 İLE VERİYOR (21 Ağu 2026).**

Kullanıcı bildirdi: *"tekli haberlerden 3 seçtim, 2'si oluşturulamadı"*
ve *"threads zincirini tamamlayamadı"*. Üç ayrı kusur çıktı.

**(a) imgbb `code 111 "Internal upload error"`.** HTTP 400 ile geliyor,
`GECICI_HATALAR = {429, 500, 502, 503, 504}` listesinde olmadığı için
**hiç tekrar denenmedi**. Kanıt log'da: 08:31'de patlayan yükleme
08:32'de sorunsuz geçti. `upload_image.GECICI_MESAJLAR` eklendi.

⚠️ Bu, projede **dördüncü** kez görülen desen — Instagram 2207052,
Telegram WEBPAGE_CURL_FAILED, Threads 4279009 ve şimdi imgbb 111.
Yeni bir dış servis eklerken ilk sorulacak soru: *"geçici hatasını
hangi HTTP koduyla veriyor?"*

**(b) Threads zinciri 2. halkada kesildi: `Media Not Found` (4279009).**
Container `FINISHED` dendikten saniyeler sonra publish onu bulamadı.

Publish normalde **bilerek tekrarlanmıyor**: HTTP 500 alan bir publish
aslında yayınlanmış olabiliyor ve tekrar denemek mükerrer gönderi
üretiyor (18 Ağu'da hesapta aynı turun üç kopyası oluştu). Ama bu alt
kod belirsiz DEĞİL — medya yoksa gönderi de yoktur. Yalnızca bu kod
için taze container'la yeniden deneniyor (`threads._medya_yok_mu`),
artı publish öncesi 2 saniyelik bekleme.

**(c) `nothing added to commit` YANLIŞ ALARMI.** Veritabanı
değişmemişti ama takip edilmeyen bir bayrak dosyası vardı; git
*"nothing ADDED to commit but untracked files present"* dedi, kod
`"nothing to commit"` arıyordu, eşleşmedi ve job **kırmızı oldu**.
Ortada hiçbir arıza yoktu. `db_senkron._degisiklik_yok()` artık dört
varyantı da tanıyor.

⚠️ Ayrıca `yayinla.yml` ve `hatirlat.yml` bayrak önbelleğini
kaydetmiyordu (`--ek assets/flags` yoktu) — indirilen bayrak repoya
girmeyince her yayında yeniden iniyordu.

**Yarım zincir artık tek tuşla tamamlanıyor.** Kesilme anında AYNI
JOB'DA bir kez `zinciri_tamamla` deneniyor (kesilme sebebi geçici
olduğu için çoğu zaman tutuyor); yine eksikse yayın sonucuna
**🔗 Threads zincirini tamamla** düğmesi konuyor. Eskiden yalnızca
`⚠️ 1/3 halka` yazıyordu — `/tamamla` komutu vardı ama mesajda ne
komut ne düğme geçiyordu ve kullanıcı eksik halkaları ELLE yazdı.

⚠️ **AYRI MESAJDAKİ DÜĞME TUR ID'SİNİ TAŞIMALI — bu tuzak DÖRT KEZ
tekrarladı**: `kaldir` (yayın sonucu), `haber_sec` (alternatif
mesajı), `gorsel_kabul` ve `gorsel_yeni` (görsel önizlemesi).
Worker basılan düğmenin **bulunduğu mesajın** id'sini gönderiyor;
ayrı bir mesajdaki düğme için bu değer turu göstermiyor.
21 Ağu 2026: kullanıcı görsel önizlemesindeki "🔄 Başka dene"ye bastı,
job *"mesaj_id=657 artık geçerli değil"* dedi — tur 656, önizleme
mesajı 657'ydi. `test_7_sozlesme` dördünü de denetliyor.

⚠️ **`th_yarim` KOŞULUN DIŞINDA tanımlı olmalı.** İlk yazımda bayrak
`if threadse_de_at and kullanilabilir_mi()` bloğunun içindeydi; Threads
kapalı olsaydı yayın sonucunu yazan satır `NameError` verecek ve
BAŞARILI bir yayın kırmızı job'a dönecekti. Bütünlük testi bunu
göremiyor (kod geçerli), `test_7_sozlesme` AST ile denetliyor.

**Eski onay mesajının düğmesi artık HATA DEĞİL.** Kapanmış/atlanmış
bir turun düğmesine basmak `return 1` veriyordu: job kırmızı, hata
bildirimi düşüyor ve gerçek arızalar arasında kayboluyordu. Artık
kullanıcıya ne olduğu ve **şu an hangi turun açık olduğu** söylenip
`return 0` dönülüyor.

**1ab. ⚠️ KOMUT KUYRUKTA SESSİZCE İPTAL EDİLİYORDU (21 Ağu 2026).**

Kullanıcı onay mesajında **"▶️ Şimdi"** düğmesine bastı ve hiçbir şey
olmadı. Actions'ta iz vardı ama `cancelled`:

```
12:34  hazirla:22835,22506   çalışıyor
12:35  yayinla               -> kuyruğa girdi
12:37  yayinla_sonra:60      -> kuyruğa girdi
       ↳ 12:35'teki İPTAL EDİLDİ
```

⚠️ **GitHub bir concurrency grubunda YALNIZCA BİR bekleyen job
tutuyor**; yeni gelen öncekini siliyor. `cancel-in-progress: false`
bunu engellemiyor — o yalnızca ÇALIŞAN job'ı koruyor, kuyruktakini
değil. Bütün workflow'lar `veritabani` grubunda olduğu için arka arkaya
basılan iki düğmeden ilki kayboluyordu.

Düzeltme iki katmanlı:
1. `yayinla.yml` **kendi kuyruğunda**: `group: veritabani-yayin`.
   Veritabanı çakışma riskini `db_senkron` zaten çözüyor; 1d'deki
   felaketin sebebi grup ayrımı DEĞİL, YAML'daki ham `git rebase`'ti
   ve o kod yolu `scripts/db_kaydet.py` ile kapatıldı.
2. `if: cancelled()` adımı — iptal artık Telegram'a bildiriliyor.
   Sessiz iptal, kullanıcının "düğme çalışmıyor" demesinin sebebiydi.

⚠️ Teşhis izi: Telegram'da düğmeye basılıyor, Actions'ta job
**"cancelled"** görünüyor ve hiçbir hata mesajı yok.

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

Araçlar: `tests/test_kaynak_erisim.py` (DB'ye dokunmaz) +
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

**⚠️ KURAL 21 AĞU 2026'DA GEVŞETİLDİ — aşağısı tarihsel kayıt.**
Kullanıcı *"görseller çok genel, hep aynı şeyler gibi"* dedi ve ölçüm
haklı çıkardı: arama terimlerinin **11/12'sinde "close up"** vardı,
hepsi yakın plan nesne olduğu için birbirine benziyordu.

Geniş kompozisyon denendi ve ELENDİ: orman yangını haberine *"aerial
view of forest canopy"* istendiğinde Pexels **yemyeşil huzurlu bir
orman** verdi — yangın haberinin altında yanlış his uyandırıyor.
*"storm clouds over empty field"* ise *"a road in Nagka, India"*
getirdi, yani kaçınılmak istenen coğrafi içerik geri geldi.

Yeni kural İKİ ŞARTI birden istiyor: **konuya doğrudan bağlı** olacak
VE **yazı/tabela içerebilecek sahne olmayacak**. Kompozisyon serbest,
"close up" artık zorunlu değil. Ölçüldü (3 gerçek haber): üçünde de
"close up" yok, üçü de konuya tam bağlı — *"military refueling
aircraft in flight"*, *"earthquake destroyed building rubble"*,
*"road bicycle race pack"*.

**PEXELS ARAMA KURALI (eski hâli) — ölçüldü, prompt'a yazıldı:**
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
- `tests/test_6_tur_gorsel.py` — bir turun tamamını üretir, maliyeti sıfır
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

⚠️ **Bu liste 4 Eyl 2026'da gerçek dosya sisteminden yeniden üretildi.**
Önceki hâli 43 dosyayı (76'nın yarısından fazlası) hiç içermiyordu —
piyasa alt sistemi, video hattı, Vision denetimi ve 20+ script listede yoktu.

```
instabot/
├── CLAUDE.md         # bu dosya — kararların ve ölçümlerin kaydı
├── GEMINI.md         # Gemini oturumunun notları ⚠️ bazı iddiaları YANLIŞ (bkz. 4b)
├── config.yaml       # RSS + eşikler + görsel ayarları (anahtar YOK)
├── .env              # ⚠️ git'te DEĞİL — tüm API anahtarları burada
├── .github/workflows/  # 11 workflow
├── worker/           # Cloudflare Worker: webhook + EDGE CRON
├── assets/           # font, logo, bayrak önbelleği
├── web/dailybrief/   # dailybrief.ozbornstudio.com — OAuth icin ZORUNLU
├── data/haber.db     # ⚠️ git'te İZLENİYOR — sahibi GitHub, yerel değil
└── data/output/      # üretilen görseller (.gitignore'da)
```

**`src/` — çekirdek ve altyapı**

| Dosya | Satır | Görevi |
|---|---|---|
| `src/db.py` | 523 | SQLite şeması + otomatik migration (EK_KOLONLAR). ORM YOK, düz SQL. |
| `src/db_senkron.py` | 196 | DB'yi git'e commit/push eder; ikili dosya çakışmasını çözer. |
| `src/zaman.py` | 105 | TR saati yardımcıları (UTC+3 sabit, DST yok). |
| `src/ayar.py` | 202 | Telegram'dan değiştirilebilen ayarlar (BEYAZ LİSTE zorunlu). |
| `src/hata_bildir.py` | 281 | Patlayan job'ı Telegram'a bildirir + düzeltme düğmeleri. |

**`src/` — haber**

| Dosya | Satır | Görevi |
|---|---|---|
| `src/fetch_news.py` | 337 | RSS/Atom çekimi. feedparser YOK, bilinçli tercih. |
| `src/fetch_article.py` | 415 | Makale gövdesi + og:image + HD URL çözümü. |
| `src/generate_text.py` | 878 | Gemini metin üretimi. 27 alanlık tek şema, ~17k karakter prompt. |
| `src/secim.py` | 555 | İki aşamalı haber seçimi (ön eleme + asıl skor). |
| `src/aday.py` | 388 | ⭐ Seçim kurallarının TEK KAPISI. Yeni akış buradan geçmeli. |
| `src/dogrula.py` | 375 | Uydurma sayı/isim, içi boş başlık, suçlama dili denetimi. |
| `src/filtre.py` | 147 | Shadowban kelime/etiket filtresi. |
| `src/otomatik_onay.py` | 335 | Gece otomatik yayın — dört katmanlı denetim. |
| `src/ozel_haber.py` | 529 | /dosya /kronoloji /link /arastir — derin konu bülteni. |

**`src/` — görsel**

| Dosya | Satır | Görevi |
|---|---|---|
| `src/slaytlar.py` | 923 | ⭐ Görsel KATMAN SEÇİCİ + tur üretici. Zincirin kalbi. |
| `src/make_image.py` | 2340 | Pillow çizim motoru (2200+ satır): tipografi, perde, yansıma. |
| `src/gorsel_kalite.py` | 142 | Çözünürlük, Laplacian netlik, taranmış belge filtresi. |
| `src/gorsel_denetim.py` | 184 | ⭐ Gemini Vision — fotoğrafın İÇİNE bakan tek katman. |
| `src/fetch_photo.py` | 444 | Wikimedia Commons (4 kat filtreli). |
| `src/fetch_stock.py` | 274 | Pexels temsili fotoğraf + tekrar engeli. |
| `src/fetch_web_image.py` | 252 | DuckDuckGo görsel arama. ⚠️ VARSAYILAN KAPALI. |
| `src/fetch_flag.py` | 128 | Ülke ve kuruluş bayrakları, önbellekli. |

**`src/` — piyasa**

| Dosya | Satır | Görevi |
|---|---|---|
| `src/piyasa.py` | 342 | Yahoo Finance canlı veri: BİST, döviz, emtia, kripto. |
| `src/piyasa_kart.py` | 670 | Piyasa ısı haritası slaytı (1080x1920). |
| `src/piyasa_tablo.py` | 382 | 30 varlık piyasa karnesi slaytı. |
| `src/sparkline.py` | 339 | Trend grafiği. ⚠️ Yalnızca finans haberlerinde basılır. |
| `src/makro_kart.py` | 360 | Makro emtia/gösterge kartı. |
| `src/haftalik_bulten.py` | 252 | Haftalık özet bülteni üretimi. |

**`src/` — yayın kanalları**

| Dosya | Satır | Görevi |
|---|---|---|
| `src/instagram.py` | 409 | Graph API carousel + story + kota + hesap koruması. |
| `src/facebook.py` | 167 | Aynı jetonla FB sayfa albümü + story. |
| `src/threads.py` | 524 | Zincir yayını (carousel DEĞİL). 60 günlük jeton. |
| `src/twitter.py` | 348 | X API v2. ⚠️ ÜCRETLİ, kredi gerekiyor. |
| `src/x_paylas.py` | 141 | Eski X paylaşım modülü (280 karakter kurulumu). |
| `src/youtube.py` | 185 | Shorts yükleme (Data API v3). |
| `src/tiktok.py` | 324 | TikTok Content Posting API, doğrudan profil yayını. |
| `src/video.py` | 325 | Slaytlardan 9:16 MP4. AAC ses izi + faststart. |
| `src/upload_image.py` | 261 | imgbb + catbox/uguu yedek barındırıcı. |
| `src/refresh_token.py` | 160 | Jeton ömrü kontrolü. |

**`src/` — Telegram**

| Dosya | Satır | Görevi |
|---|---|---|
| `src/telegram_bot.py` | 1041 | Onay mesajı, albüm, menüler, sonuç bildirimi. |
| `src/komutlar.py` | 115 | Komut sözlüğü, alias, mesajsız komutlar (tek merkez). |
| `src/yonetim.py` | 392 | /yonetim paneli. |
| `src/caption.py` | 633 | Carousel açıklaması (2200 kr / 30 hashtag yönetimi). |
| `src/handlers/` | — | ⚠️ TERK EDİLMİŞ REFACTOR — hiçbir yerden import edilmiyor. |

**`scripts/` — üretim ve bakım**

| Dosya | Satır | Görevi |
|---|---|---|
| `scripts/son_dakika.py` | 1048 | ⭐ ASIL AKIŞ: saatlik öneri + tekil post + gece yayını. |
| `scripts/onay_isle.py` | 3815 | ⚠️ 3815 satır. Telegram buton/komut işleyici — her iş burada. |
| `scripts/hazirla.py` | 290 | Çoklu haber turu. ⚠️ Cron'u KAPALI, elle tetikleniyor. |
| `scripts/piyasa_otomatik.py` | 273 | Piyasa bülteni. ⚠️ Saat penceresi kodda sabit. |
| `scripts/hatirlat.py` | 187 | Onaylanmayan turu hatırlat / havuza döndür. |
| `scripts/gunluk_rapor.py` | 242 | Sabah durum raporu + eski kayıt temizliği. |
| `scripts/haftalik_ozet.py` | 193 | Pazar haftalık özeti. |
| `scripts/hafta_sonu_raporu.py` | 122 | ⚠️ Hiçbir workflow çağırmıyor. |
| `scripts/db_kaydet.py` | 69 | DB commit+push. ⚠️ Workflow'da HAM git komutu yazma, bunu çağır. |
| `scripts/jeton_yenile.py` | 204 | Haftalık jeton tazeleme (IG + Threads). |
| `scripts/gecmisi_paylas.py` | 241 | Eski turları Threads'e taşır. |
| `scripts/haber_disa_aktar.py` | 180 | Excel dışa aktarım (insan puanlaması için). |
| `scripts/kaynak_dogrula.py` | 188 | ⭐ Kaynak eklemeden ÖNCE çalıştır. |
| `scripts/sessiz_basarisizlik_tara.py` | 88 | 'return 0 ama iş yapılmadı' desenini arar. |
| `scripts/webhook_kur.py` | 131 | Telegram webhook kur/kaldır/durum. |
| `scripts/anahtar_ekle.py` | 73 | '.env'e gizli girişle anahtar ekler. |
| `scripts/logo_indir.py` | 124 | Marka logosu indirme. |
| `scripts/tiktok_auth.py` | 188 | TikTok OAuth (tek seferlik). |
| `scripts/youtube_auth.py` | 173 | YouTube OAuth (tek seferlik). |
| `scripts/jeton_uzat.py` | 110 | IG jetonunu 60 güne çevirir. |
| `scripts/telegram_chat_id_bul.py` | 159 | ⚠️ Webhook kuruluyken ÇALIŞMAZ. |
| `scripts/varyasyon_uret.py` | 545 | Piyasa kartı renk varyasyonu üretici (tek seferlik araç). |
| `scripts/ton_varyasyon_uret.py` | 332 | Şerit tonu varyasyonu üretici (tek seferlik araç). |

**`tests/` — testler**

| Dosya | Satır | Görevi |
|---|---|---|
| `tests/test_0_butunluk.py` | 288 | ⭐ ÖNCE BUNU ÇALIŞTIR — çağrı/imza doğrulaması. |
| `tests/test_7_sozlesme.py` | 1636 | ⭐ 238 denetim — kuralların HER YERDE uygulandığını denetler. |
| `tests/test_1_rss.py` | 85 | RSS + veritabanı. |
| `tests/test_2_makale_metni.py` | 86 | Gövde çekme ölçümü. |
| `tests/test_3_metin_uret.py` | 84 | Gemini metin (DB'yi DEĞİŞTİRİR, kota yer). |
| `tests/test_4_gorsel.py` | 78 | Tek slayt. |
| `tests/test_5_instagram_baglanti.py` | 233 | Jeton + hesap doğrulama. |
| `tests/test_6_tur_gorsel.py` | 87 | Bir turun tamamı, maliyet sıfır. |
| `tests/test_kaynak_erisim.py` | 159 | IP engeli teşhisi. |
| `tests/test_barindirici.py` | 103 | Görsel barındırıcı testi. |

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

### ⚠️ EN SIK GÖRÜLEN HATA SINIFI: SESSİZ BAŞARISIZLIK

21 Ağustos 2026'da canlıda çıkan hataların **çoğu tek bir desendi**:
kod `0` (başarı) döndü ama iş yapılmadı ve kullanıcıya hiçbir şey
söylenmedi.

| Olay | Ne oldu |
|---|---|
| Kullanıcı 2 haber seçti | `main` 15 sn'de `0` döndü, hiçbir post üretilmedi — günlük sayaç yanlış hesaplanıyordu |
| `/haber netenhay` | Fuzzy 24 sonuç buldu, bir alt satır hepsini eledi, "bulunamadı" dendi |
| "▶️ Şimdi" düğmesi | Komut kuyrukta iptal edildi, job "cancelled", bildirim yok |
| Atlanan haber kuralı | `except: pass` bir `TypeError`'ı yutuyordu, kural hiç çalışmadı |

⚠️ **TESTLER BUNLARI GÖREMİYOR** — kod "çalışıyor", yalnızca yanlış
şeyi yapıyor.

**Karşı önlem: dönüş değerine değil GERÇEK ETKİYE bak.**
`oneriyi_hazirla` artık veritabanına soruyor — haber gerçekten
`onay_bekliyor` oldu mu, bir mesaja bağlandı mı? "Başarılı" demek
yetmiyor.

`scripts/sessiz_basarisizlik_tara.py` kodda bu deseni arıyor: bir iş
yapılmadan `return 0` ile çıkan ve kullanıcıya bildirim göndermeyen
dallar. ⚠️ Yanlış pozitif verir (bildirim çağrılan fonksiyonun içinde
olabilir, `--kuru` dalları bilerek sessizdir) — çıktısı bir liste
değil, **incelenecek adaylar**.

### İKİ TEST KATMANI — kod değiştirdikten sonra ikisini de çalıştır

```bash
python tests/test_0_butunluk.py    # çağrılar ve imzalar geçerli mi
python tests/test_7_sozlesme.py    # kurallar her yerde uygulanmış mı
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
`onem_puani` (1-10) → `durum='metin_hazir'`. Test: `tests/test_3_metin_uret.py`

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
python tests/test_1_rss.py                    # RSS + veritabanı
python tests/test_kaynak_erisim.py            # kaynak erişimi
python tests/test_5_instagram_baglanti.py     # Instagram + jeton
python tests/test_2_makale_metni.py           # makale metni çekme
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
