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
| Post sıklığı | **Günde 1 akşam turu + en fazla 2 son dakika** = günde en çok 3 post |
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
| Slayt görseli | **3 katman, sırayla:** Commons (**yalnızca KİŞİ**) → Pexels (temsili) → gradyan. **Normal turda AI HİÇ çağrılmıyor, görsel maliyeti $0.** |
| Commons kuralı | **`gorsel_konu`ya SADECE kişi adı yazılır, kurum/örgüt/şehir ASLA.** Ölçüldü: "İSKİ"→Macar sanatçı portresi, "Taliban"→askeri harita, "Ankara Büyükşehir"→kale manzarası. Bunlar yayınlanamaz. Kurumu Pexels temsil ediyor ve iyi çalışıyor. |
| Caption | Tek post, 10 haber → `src/caption.py`. Tarih + numaralı manşet listesi + kaynaklar + atıf + hashtag. Sınır 2200 karakter / 30 hashtag; aşarsa sırayla hashtag → atıf → son maddeler kırpılır. |
| Atıf politikası | Commons atıfları **tek tek** yazılır (CC BY hukuken şart). Pexels'ler **tek satırda** toplanır — lisansı atıf istemiyor, 9 ayrı satır 700 karakter yiyordu. |
| İçerik filtresi | Instagram shadowban'ine karşı `src/filtre.py`: riskli kelimeler yıldızlanır ("taciz"→"tac*z"), kısıtlı hashtag'ler **tamamen atılır** (etikette yıldız işe yaramaz). Liste `config.yaml`'de ve **bilerek kısa** — ölüm/kaza/cinayet gibi gündelik haber kelimeleri YOK, aşırı sansür amatör gösteriyor. |
| Haber sitesi fotoğrafı | **KULLANILMIYOR.** Kullanıcı istedi, telif riski anlatıldı, vazgeçildi. Ajans fotoğrafı (AA/Reuters/AFP) ticari lisanslı; "kaynak belirtmek" izin yerine geçmiyor, Instagram telif şikayeti hesabı kapattırabilir. |
| Beğenilmeyen görsel | Telegram'a **`🎨 Görseli AI ile üret`** butonu eklenecek. Varsayılan bedava katman; AI maliyeti ancak kullanıcı basarsa oluşuyor. |
| Slayt yazısı | Başlık + altında küçük puntoyla **tek cümlelik özet** (`slayt_ozet`). |
| ★ Başlık kuralı | **Başlık haberin SONUCUNU söylemek zorunda.** Takipçiye link vermiyoruz, okuyacağı başka yer yok — slaytı kaydırıp geçen kişi haberi ÖĞRENMİŞ olmalı. "…ilişkin açıklama", "…değerlendirdi", "…anlattı" gibi 15 kalıp prompt'ta YASAK; `dogrula.basligi_denetle()` yakalayıp uyarıyor. Abartı ("şok", "bomba") da yasak — güveni düşürüyor. Ölçüldü: "Bakan Göktaş'tan taciz iddialarına ilişkin açıklama" → "…iddialarının vahim olduğunu belirtti". |
| Telegram komutları | `/durum` (havuz + onay bekleyen + son yayın), `/tur` (elle tur kur), `/yardim`. Buton menüsü yalnızca açık onay mesajı varken işe yarıyordu; tur kapanınca elde tutamak kalmıyordu. `/yardim` Worker'da anında cevaplanıyor. |
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
| ⚠️ Threads jetonu 60 GÜN | Instagram'daki süresiz sayfa jetonunun karşılığı Threads'te YOK. **Otomatik yenileme kuruldu** (18 Ağu 2026): haftalık `jeton-yenile.yml` artık iki jetonu da tazeliyor (`threads.jetonu_yenile` → `th_refresh_token`), yeni jeton `.env` ve GitHub Secret'a yazılıyor. Threads kalan süreyi sorgulatmadığı için **koşulsuz** yeniliyoruz — öğrenmenin tek yolu yenilemek. ⚠️ Jeton **24 saatten yeniyse** yenileme hata verir; bu beklenen, sonraki hafta düzelir. Yenilenmezse arıza SESSİZ: `kullanilabilir_mi()` True dönmeye devam eder, hata ancak yayın anında çıkar. |
| ~~WhatsApp Kanalı~~ | **İMKANSIZ.** WhatsApp Business API kanalları desteklemiyor; kanala yalnızca telefondan elle post atılabiliyor. Politika kısıtı, aşılamaz. |
| ~~TikTok~~ | **ERTELENDİ.** Fotoğraf paylaşım API'si var ama uygulama denetimi (audit) gerekiyor; onaysız uygulamalar yalnızca TASLAK gönderebiliyor, kullanıcı uygulamadan yayınlıyor. Yani tam otomatik değil. |
| ~~X/Twitter~~ | **ERTELENDİ (18 Ağu 2026) — ÜCRETLİ ÇIKTI.** Geliştirici hesabı açıldı (@dailybrief_co), 4 anahtar alındı, "Read and write" izni doğrulandı, `src/x_paylas.py` yazıldı. Sonra görüldü ki **X API artık kredi bazlı**: hesapta `Free credits $0.00`, bakiye $0, post atmak para istiyor. Eski "ayda 500 post ücretsiz" katmanı bu hesapta yok. Kullanıcı ücret ödemek istemediği için bırakıldı; **logosu da slayttan kaldırıldı** — sahip olmadığımız kanalın logosunu basmak yanlış. Ödeme yöntemi eklenmediği için istem dışı ücret riski YOK. Tekrar açmak için: kredi yükle → `config.yaml → sosyal.kanallar`'a `- x` ekle → `x_paylas.yayinla()`'yı akışa bağla. Anahtarlar `.env`'de duruyor. |
| ⚠️ X 280 karakter | Caption'lar 1100-1500 karakter, X'e SIĞMIYOR. `x_paylas.metni_kur()` bunun için var: kırpmak yerine baştan X'e uygun metin kuruyor (tarih + sığdığı kadar manşet + 3 hashtag). Kırpma denenmedi çünkü caption'ın sonu kaynak/atıf satırları ve onlar zaten sığmıyor. |
| Story (17 Ağu 2026) | Post ile birlikte **otomatik** paylaşılıyor, ayrı onay yok — içerik zaten onaylanan haberlerin listesi. Akşam turu → manşet listesi (9:16), son dakika → haberin kendisi. Story ikincil: patlarsa post yine çıkar, sonuç mesajına not düşülür. **CANLI TEST EDİLDİ**, uçtan uca çalıştı. |
| ⚠️ Story kısıtı | **API'den sticker/link/mention EKLENEMİYOR.** "Postu gör" diyemiyoruz, o yüzden story tek başına anlamlı olmak zorunda — akşam story'si manşetleri listeliyor, gören kişi postu açmasa bile gündemi öğreniyor. Elenen kapak tasarımı burada işe yaradı (carousel'de slayt yiyordu, story'de öyle bir maliyeti yok). |
| ~~Reels/video~~ | **ERTELENDİ (17 Ağu 2026), elenmedi.** Eski gerekçelerden ikisi geçersiz: runner'da ffmpeg ZATEN var, Cloudflare R2 bedava (hesap mevcut). Geçerli kalan tek engel: **müzik Graph API'den eklenemiyor** — Instagram'ın müzik kütüphanesi yalnızca resmi uygulamada, bu bir politika kısıtı, aşılamaz. Müziksiz/telifsiz müzikli Reels yapılabilir ama izlenme süresi düşük olacağı için erişim avantajının çoğu kaybolur. Kullanıcı "şimdilik her şey aynı kalsın" dedi. |
| Onay verilmezse | **Haber ELENMEZ**, havuza döner, sonraki turda yeniden yarışır |
| Bayatlama sınırı | Yayın tarihinden **48 saat** sonra aday olmayı bırakır |
| ~~"Atla" butonu~~ | **GEÇERSİZ.** Tek-haber tasarımından kalmaydı; carousel'de 10 haber var, "sıradakini öner" anlamsız. Yerine aşağıdaki menü geldi. |
| Onay butonları | İki katmanlı menü (15 Ağu 2026): **Ana menü** → `✅ Yayınla` / `🔄 Metinleri yeniden üret` / `🎨 Bir slaytın görselini değiştir` / `❌ Bu turu atla`. **Slayt menüsü** → 1-10 arası seçim → `🔀 Başka fotoğraf (bedava)` / `🎨 AI ile üret (~$0.04)`. |
| Menü gezinme nerede | **Worker'da, GitHub'da değil.** Actions'ı uyandırmak 30+ saniye sürüyor, menü açmak anında olmalı. Yalnızca gerçek eylemler (`yayinla`, `iptal`, `metin_yenile`, `slayt_ai:N`, `slayt_foto:N`) `repository_dispatch` ile GitHub'a gidiyor. |
| ⚠️ Menü ikilemesi | Buton düzeni **iki yerde** tanımlı: `src/telegram_bot.py` ve `worker/index.js`. Birini değiştirirsen diğerini de değiştir. Slayt sayısı `callback_data`'ya gömülü (`slayt_menu:10`) — Worker'ın turda kaç slayt olduğunu bilmesinin başka yolu yok. |
| Secrets | `.env` (yerel) + GitHub Actions Secrets (uzak). Koda gömülmez. |

---

## 4. ŞU ANKİ DURUM

### 🟢 BOT YAYINDA — 16 Ağustos 2026

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

**Günlük maliyet: $0.** Normal turda AI hiç çağrılmıyor (Commons/Pexels/
gradyan bedava), Gemini metin ücretsiz kotada, jeton süresiz.

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
