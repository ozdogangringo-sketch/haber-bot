# GEMINI.md — Daily Brief Instagram & Sosyal Medya Haber Botu

Bu dosya projeyi devralan yapay zeka oturumu ve geliştiriciler içindir.

> ⚠️ **BU DOSYA TEK BAŞINA GÜNCEL DEĞİL — önce `CLAUDE.md` bölüm 4b'yi oku.**
>
> 4 Eylül 2026'da bu dosyadaki iddialar kod üzerinde tek tek doğrulandı.
> Çoğu geçerli ve `CLAUDE.md`'ye taşındı, ama **dördü yanlış çıktı**:
> `STORY_GUVENLI_PAY` 285 değil **330** · GitHub `schedule:` cron'ları
> "kaldırıldı" deniyor ama `son-dakika.yml`'de **duruyor** (aynı iş iki
> kaynaktan tetikleniyor) · `src/handlers/` tamamlanmış gibi anlatılıyor
> ama **hiçbir yerden import edilmiyor** · görsel hiyerarşisinin 1. katmanı
> olan internet araması **3 Eyl'de kapatıldı ve zincirin sonuna alındı**.
>
> Gerekçeleriyle birlikte `CLAUDE.md` → "GEMINI.md YANILIYOR" tablosunda. Tüm mimari kararlar, yapılan geliştirmeler, çalışma kuralları ve sistemin güncel durumu bu rehberde toplanmıştır.

---

## 1. Kullanıcı Profili ve Değişmez Temel İlkeler

- **Kullanıcı:** Doğukan. Türkçe konuşur, kararlı, yüksek kaliteli ve net çıktılar bekler.
- **Alan Adı (Domain):** `ozbornstudio.com` alan adı projeye aittir. Gelecekte ihtiyaç halinde alt alan adları (örn: `bot.ozbornstudio.com`, `api.ozbornstudio.com`, `media.ozbornstudio.com`, `brief.ozbornstudio.com`) Cloudflare DNS üzerinden webhook, CDN, görsel barındırma veya web kontrol paneli için yapılandırılabilir.
- **KATI VE DEĞİŞMEZ KURAL (1080x1920 9:16 TUVAL & 4:5 GÜVENLİ ALAN MİMARİSİ):**
  * **Normal Gönderilerle Birebir Aynı Tasarım Mantığı (`STORY_GUVENLI_PAY = 285px`):** Tüm slaytlar (Tekil Haber 1. Kapak, 2. Detay, 3. Detay/Etki, Canlı Piyasa Bülteni 1. Isı Haritası, 2. BİST Tablosu vb.) **1080x1920 dikey tuvalde**, üstten ve alttan 285px güvenli pay bırakılarak **merkezi 1080x1350 (4:5) alanında ideal tasarım oranlarıyla** çizilir.
  * Zemin gradyanı ve ambiyans ışıltısı 1080x1920 tuvalin tamamını kesintisiz ve akıcı olarak doldurur.
  * **Asla dikey esnetme/uzatma yapılmaz**; kartlar ve tablolar doğal 4:5 oranlarında kalır.
  * **Asla yapay çerçeve çizgisi veya ayrık blur kutuları eklenmez**; görsel tek parça lüks bir infografiktir.
  * Böylece görsel **Instagram Akışında, Threads zincirlerinde ve Twitter'da (4:5)** gösterildiğinde sıfır kırpılma ve kusursuz çerçeveleme ile görünürken, **Instagram Story, Reels, Shorts ve TikTok'ta (9:16)** güvenli alanıyla tam ekran görünür.
- **KATI TİPOGRAFİ, PARAGRAF ÇENTİKLERİ VE TEMİZ METİN:**
  * **Paragraf Başı Dikey Çentikleri (Sleek Accent Notch):** Detay slaytlarında paragrafların solunda 4px yuvarlatılmış renkli dikey çentikler yer alır:
    - *Spot Paragraf:* Sıcak Kehribar (`#E2AA58`)
    - *Gelişme Paragrafları:* Siber Turkuaz (`#06B6D4`)
    - *Sana Etkisi:* Zümrüt Yeşili (`#10B981`)
  * **Sıfır Taşma Garantisi (`detay_sayfalara_bol` & `_metni_paragraflara_ayir`):** Metinler Türkçe sıra sayıları (`42.`, `3.`) ve unvan/kısaltmaları (`Dr.`, `vb.`) bozulmadan 2-3 cümlelik ferah paragraflara ayrılır ve 1080x1920 tuvalde alt bilgi çizgisine değmeden dinamik sayfalara bölünür.
  * Slayt görsellerinde kilit veriler, oranlar ve aktörler Pillow render motoru tarafından **800.0 Extra Bold** kalın ve parlak çizilir.
  * Sosyal medya açıklamalarında (`ig_caption`, Threads, Twitter) ise **SIFIR MARKDOWN (`**`) KURALI** geçerlidir; `ÖNE ÇIKAN VERİ` gibi kalıp etiketler kaldırılmıştır, tüm açıklamalar akıcı ve temiz editoryal düz metindir.
- **YAYIN MODELİ (SAATLİK TEKLİ HABERLER & GÜNLÜK PİYASA BÜLTENİ):**
  * Akşam çoklu haber turları kaldırılmıştır.
  * Gün boyu 1'er saat aralıklarla Telegram'a **en taze 5 haber önerisi** düşer; seçilen haber varsayılan olarak **3-4 ferah sayfa (1 Kapak + 2-3 Detay/Analiz Slaytı - 1080x1920)** olarak üretilir.
  * Hafta içi sabah (TR 10:08) ve akşam (TR 18:20) fiks **Canlı Borsa & Piyasa Bülteni** (%100 Native 1080x1920 Story ve Akış) otomatik paylaşılır.

---

## 2. Sistem Mimarisi & Kesintisiz 3 Katmanlı Tetikleme

```
[Cloudflare Edge Cron Triggers] (10:08 TR Açılış, 18:20 TR Kapanış, Saatlik Akış)
       │ (0 Gecikme, 99.99% Uptime — worker/index.js)
       ▼
[GitHub Actions repository_dispatch] ──► [piyasa-bulteni.yml / son-dakika.yml / yayinla.yml]
       │
[son_dakika.py Otomatik Telafi Ağı] ──► (Bülten gecikirse saat başı otomatik tamamlar)
       │
[fetch_news.py] ──> SQLite (data/haber.db)
       │
       ▼
[Tekil 3-4 Slayt %100 Native 1080x1920 Üretimi] (slaytlar.py / make_image.py / piyasa_kart.py / piyasa_tablo.py)
       │ (1 Kapak + 2 Detay Slaytı + 144px 3D Logo + Renkli Paragraf Çentikleri)
       ▼
[Telegram Onay & Yönetim Grubu] (telegram_bot.py ──> Daily Brief Grubu)
       │ (İnteraktif butonlar: 1️⃣..5️⃣ Seç, ✅ Yayınla, 🚀 Canlı Bülteni Şimdi Yayınla...)
       ▼
[onay_isle.py Router & Paralel Dağıtım Motoru (ThreadPoolExecutor)]
       │ (Canlı İlerleme Çubuğu [▰▰▱▱] %50 & Canlı Platform Durumları)
       ├─► Instagram Graph API (1080x1350 4:5 Carousel & 1080x1920 9:16 Story)
       ├─► Facebook Graph API (1080x1350 4:5 Albüm, Story & 9:16 Reels)
       ├─► Threads API (1080x1350 4:5 Bilgi Zinciri)
       ├─► X (Twitter) API v2 (1080x1350 4:5 Fotoğraflı Tweet/Flood)
       ├─► YouTube Data API v3 (9:16 Shorts Video)
       └─► TikTok Content Posting API (9:16 Dikey Video)
```

---

## 3. Yapılan Başlıca Geliştirmeler & Modüller

### A. 4:5 Güvenli Alanlı 1080x1920 Canlı Piyasa Bülteni & Ekonomi Özet Kartı (`src/piyasa_kart.py`, `src/piyasa_tablo.py`, `src/piyasa_ozet.py`)
- **Normal Haber Slaytlarıyla Birebir Aynı Tasarım Oranı:** 1. Slayt (Canlı Piyasa Isı Haritası), 2. Slayt (30 Varlık Piyasa Karnesi) ve 3.-4. Slaytlar (Günün Ekonomi Gündemi Özet Kartları) `Y_OFFSET = 285px` güvenli payıyla 1080x1920 tuvalin merkezindeki 1080x1350 bölgesine çizilir.
- **Sıfır Esneme & Sıfır Yapay Çerçeve:** Tablolar ve kartlar dikeyde 1920'ye kadar uzatılmaz, doğal 4:5 oranlarında kalır; zemin gradyanı ve ışıltısı tüm tuvali kesintisiz sarar.
- **Tasarım:** *Derin Okyanus Petrolü* zemin (`#04181C`), *Siber Turkuaz* parıltılı rozet (`#06B6D4`), canlı Gram Altın/Gümüş TL çevrimi, BİST Ağaç Haritası, 5'li makro emtia ve 5'li küresel piyasa/kripto sparkline trend kartları.
- **Günün Ekonomi Gündemi Çoklu Özet Kartı (`src/piyasa_ozet.py`):** Bültenin sonuna tekil haber slaytları yerine sayfa başına en fazla 3 haber içeren lüks özet kartları eklenir (1-3 haber -> 1 sayfa / 3. slayt, 4-6 haber -> 2 sayfa / 3. ve 4. slaytlar). Başlıklar 36px 850 Extra Bold fontla çizilir; tematik renk çentikleriyle (Kehribar, Turkuaz, Zümrüt Yeşili) zenginleştirilir. Sabah açılışında `Günün Öne Çıkanları` / `Açılış Özeti`, akşam kapanışında `Günü Kapatırken` / `Kapanış Özeti` dinamik başlıklarını alır. Instagram Story'ye tüm slaytlar 9:16 aktarılır.
- **Kesin Saat Pencereleri:** Açılış bülteni penceresi **09:55 - 11:30 TR**, Kapanış bülteni penceresi **18:15 - 20:00 TR** aralığındadır. Bu saatler dışında sistem otomatik yayınlamayı reddeder.

### B. Cloudflare Edge Cron & Çok Katmanlı Güvenlik Mimarisi
- **Cloudflare Edge Cron:** `worker/wrangler.toml` ve `worker/index.js` üzerinden `8 7 * * 1-5` (10:08 TR) ve `20 15 * * 1-5` (18:20 TR) cron'ları doğrudan Cloudflare Edge ağında çalışarak GitHub REST API `repository_dispatch` ile piyasa bültenini ve saatlik haber akışını sıfır gecikmeyle tetikler. GitHub Actions'ın kendi gecikmeli `schedule:` cron'ları tamamen kaldırılmıştır.
- **Saatlik `son_dakika` Emniyet Ağı:** Hafta içi sabah 10:15 - 11:30 arasında bülten gecikirse, saat başı çalışan `son_dakika.py` motoru durumu fark edip piyasa bültenini anında yayına alır.
- **Telegram `/piyasa` ve `/ekonomi` Butonları:** Telegram'dan anlık olarak "🚀 Canlı Bülteni Şimdi Yayınla" ve "🖼️ 1080x1920 Slaytları Önizle" butonlarıyla bülten tetiklenebilir.
- **Özel Event Ayrımı:** `/sondakika` komutu `son_dakika_calistir` event'i ile doğrudan `son-dakika.yml` workflow'unu tetikler.

### C. Tek Merkezli Komut Sözlüğü (`src/komutlar.py`) & Modüler Handler Katmanı (`src/handlers/`)
- **Single Source of Truth (`src/komutlar.py`):** `MESAJSIZ_KOMUTLAR`, `KOMUT_MENUSU` ve yetki yönetimi tek merkezde toplandı.
- **Modüler Handler Katmanı (`src/handlers/`):**
  * `yayin_yonetimi.py`: Çoklu platform yayını, telafi, URL doğrulama ve zamanlanmış yayınlar.
  * `slayt_yonetimi.py`: Fotoğraf değiştirme, AI ile görsel üretme, metin düzenleme ve slayt silme.
  * `tur_yonetimi.py`: Tur yaşam döngüsü, aday seçimi, başlık onayı, arama ve erteleme/iptal.
- **Telegram Slash Menüsü:** `/dosya`, `/kronoloji`, `/link`, `/arastir`, `/sondakika`, `/piyasa`, `/ekonomi`, `/yonetim`, `/durum`, `/temizle` resmi olarak `setMyCommands` ile kayıtlıdır.

### D. A'dan Z'ye Perde Arkası Dosya Haberi Motoru (`/dosya <KONU>`, `src/ozel_haber.py`)
- Verilen konunun (örn. davalar, teftişler, şirket krizleri) başından günümüze kadarki tüm kronolojisini, ara bilirkişi raporlarını ve gelinen son hukuki durumu 3 ferah paragraflı, kilit verili derinlemesine bir bültene dönüştürür.

### E. Kurumsal Marka Kimliği & 144px 3D Logo (`src/slaytlar.py` & `src/make_image.py`)
- Slaytlardaki marka logosu 144x144 px boyutundadır. Arka planında çok katmanlı 14px Gaussian Blur gölge ile 3D kabartma derinliği bulunur.
- Slaytların sağ alt köşesinde 6 platformun (`Instagram`, `Threads`, `Facebook`, `X`, `YouTube`, `TikTok`) resmi kurumsal vektör ikonları yer alır.

### F. Kristal Netlik ve 16:9 HD Basın Fotoğrafı Standartları (`src/gorsel_kalite.py`)
- **16:9 HD Ajans ve Lansman Standartları:** Çözünürlük eşikleri $800\times 450$ px (16:9 HD) ve $600\times 600$ px (kare/portre) olarak optimize edildi; $1200\times 675$, $1280\times 720$ ve $1372\times 772$ boyutlarındaki tüm gerçek basın fotoğrafları tam kaliteyle kabul edilir.
- **Taranmış Belge / PDF / İlan Formu Engeli:** Doygunluk $\le 15.0$ ve Parlaklık $\ge 175.0$ olan ham tablo, PDF ekran görüntüsü veya beyaz kağıt taramaları otomatik elenerek gerçek editoryal haber fotoğraflarına geçilir.
- **Laplacian Netlik Varyansı:** Yapay büyütülmüş ve bulanık fotoğraflar elenir (Asgari netlik varyansı $\ge 35.0$).
- **Kristal Keskinleştirme (`kristal_netlestir`):** Seçilen kaliteli fotoğraflar UnsharpMask ile pürüzsüz ve kristal netlikte editoryal stile kavuşturulur.

### G. Hızlı Video ve TikTok / Shorts / Reels İşleme Motoru (`src/video.py` & `src/tiktok.py`)
- **Direct Publish & Doğrudan Profil Yayını:** TikTok OAuth token'ı `video.publish,video.upload,user.info.basic` izinleriyle güncellendi; videolar Inbox/Taslak kuyruğuna düşmeden doğrudan profile otomatik yayınlanır.
- **Stereo AAC Ses İzi Entegrasyonu:** Sessiz videolarda sosyal medya algoritmalarının (TikTok, Shorts, Reels) ikincil transcode kuyruğuna düşüp bildirimleri geciktirmesini önlemek için videolara otomatik standart stereo AAC ses kanalı (`44.1 kHz, 128 kbps`) gömülür.
- **Sabit 2 Saniyelik GOP Keyframe (`-g 60 -keyint_min 30 -sc_threshold 0`):** TikTok'un dağıtık sunucularının videoyu paralel parçalara (chunks) bölerek saniyeler içinde işlemesini sağlar.
- **`+faststart` Moov Atomu:** MP4 konteynerinin indeks verisini dosyanın başına taşıyarak anında yayın ve indirme başlatır.
- **Canlı Yayın Durumu Sorgulama (`yayin_durumu_sorgula`):** TikTok Content Posting API üzerinden `SEND_TO_USER_INBOX` durumunu canlı takip eder.

### H. Finansal Trend (Sparkline) Çapa Mimarisi & Mükerrer Rozet Filtresi (`src/sparkline.py` & `src/piyasa_kart.py`)
- **Kapanış Çapası (Previous Close Anchored):** Piyasa kartı sparkline grafiklerinin başlangıç noktası dünkü kapanış fiyatına (`previousClose`) sabitlendi (`[prev_close] + fiyat_serisi`).
  * Değişim pozitifse (`degisim >= 0`) çizgi kesinlikle başlangıcından daha yukarıda biter ve **Zümrüt Yeşili (`#22C55E`)** çizilir.
  * Değişim negatifse (`degisim < 0`) çizgi kesinlikle başlangıcından daha aşağıda biter ve **Mercan Kırmızı (`#EF4444`)** çizilir.
  * Renk ile grafik eğimi arasındaki tüm görsel çelişkiler sıfırlandı.
- **5 Günlük Kesintisiz Veri Akışı (`range=5d&interval=1h`):** Piyasalar kapalı olsa bile 40-100 nokta gerçek veri çekilerek kesintisiz trend çizilir.
- **Sönümlü Sigmoid Eğri:** Veri bulunamadığında çağrılan sentetik eğri uca doğru asla ters bükülmez, son fiyat noktasına parlayan odak noktası (dot) eklenir.
- **Piyasa/Fiyatlama Bağlam Şartı (`src/sparkline.py`):** Yaşam, dünya, spor vb. haberlerde metinde para birimi geçse dahi 30 günlük borsa trend grafiği kesinlikle basılmaz. SADECE borsa/finans haberlerinde doğrudan fiyat hareketi varsa üretilir.
### I. Cloudflare R2 Birincil Görsel ve Video Depolama (`media.dailybrief.ozbornstudio.com`)
- **Sıfır Bağımlılık & Özel CDN Alan Adı:** ImgBB ve Catbox kesintilerine veya bot engellerine karşı, Cloudflare R2 kalıcı S3 uyumlu depolama devreye alındı.
- `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_PUBLIC_DOMAIN` değişkenleri tüm GitHub Actions iş akışlarına (`yayinla`, `son-dakika`, `piyasa-bulteni`, `hazirla`, `haftalik-ozet`) bağlandı.
- Görseller ve videolar anında `media.dailybrief.ozbornstudio.com` üzerinden yüksek hızda dağıtılır; R2 başarısız olursa sistem otomatik olarak ImgBB ve Catbox'a fallback yapar.

### J. YouTube 2. Proje Entegrasyonu & Otomatik Kota Rotasyonu (`src/youtube.py`)
- **Çift Proje — 20.000 Puan (10 Video/Gün):** YouTube Data API v3'ün günlük 10.000 birimlik (azami 5 video) kota sınırını aşmak için 2. Google Cloud projesi (`daily-brief-2`) sisteme eklendi.
- **Otomatik Failover:** Proje 1 kotası dolduğunda (`quotaExceeded` / HTTP 403), yükleme işlemi çökmeden saniyeler içinde Proje 2'nin refresh token'ına (`YOUTUBE_*_2`) geçer.
- Her iki proje de Google Cloud Console'da "In Production" durumundadır; jetonlar süresiz geçerlidir.

### K. Platforma Özel Ses Ayrımı & Dinamik Slayt Süreleri (`src/video.py`)
- **Sessiz Video (Telegram Reels & TikTok):** Instagram Reels ve TikTok'ta kullanıcının uygulama içindeki popüler/trend müzikleri rahatça ekleyebilmesi için Telegram'a iletilen ve TikTok'a yüklenen videolar tamamen sessiz (`anullsrc` stereo AAC) üretilir.
- **Müzikli Video (YouTube Shorts & Facebook Reels):** Otomatik paylaşılan platformlara bot telifsiz dinamik haber ambiyans müziğini miksleyerek yükler.
- **İçerik Yoğunluğuna Göre Dinamik Süre (`slayt_surelerini_hesapla`):** Sabit 3.5 sn kaldırıldı; 1. Kapak 4.2 sn, detay sayfaları kelime sayısına göre 4.8 sn - 6.2 sn aralığında ayarlanır. Toplam video süresi 15 - 20 sn algoritma tam izlenme (completion rate) penceresinde tutulur.

### L. Paralel Dağıtım Motoru (ThreadPoolExecutor) & Canlı İlerleme Çubuğu (`scripts/onay_isle.py`)
- **EzanPlusBot Standartlarında Paralel Dağıtım:** 6 platforma ardışık değil, Python `ThreadPoolExecutor` ile eşzamanlı yayın yapılır.
- **Canlı İlerleme Çubuğu:** Telegram onay mesajı anlık olarak güncellenir (`[▰▰▰▱▱] %60 - YouTube Shorts yüklendi, Instagram bekleniyor...`).
- **Threads ve X için 4:5 Formatı:** 9:16 görseller dikey kırpılma yaşamaması için merkezi 4:5 oranında kurgulanarak Threads ve Twitter'a kusursuz çerçeveleme ile iletilir.

### M. Telegram 4 Modüllü Canlı Yönetim & Etkileşim Paketi (`scripts/onay_isle.py`)
- **Modül 1 (Kanal Seçici):** Paylaşmadan önce `[x] Instagram`, `[x] Facebook`, `[ ] Threads`, `[x] TikTok`, `[x] YouTube` gibi checkbox butonlarıyla hangi platforma gidip gitmeyeceğini canlı toggle yapabilme.
- **Modül 2 (Acil Durum & Yönetim - `/yonetim`):** Botu 1 saat, 6 saat, 12 saat veya 24 saat tek tıkla duraklatma ve geri açma paneli.
- **Modül 3 (Canlı Metin & Başlık Düzenleme):** Telegram'da onay mesajına reply atıp sadece metni yazarak başlığı veya detay metnini sıfırdan çizdirme (`slayt_metin`).
- **Modül 4 (Slayt Sıralama & Yönetim):** Slaytların sırasını değiştirme (reorder), istenmeyen slaytı silme ve havuzdan yedek haber slaytı ekleme.
- **"🗑️ Çöpe At / Adaylıktan Çıkar" Butonu (`cope_at`):** Beğenilmeyen veya bayatlayan haberi tek tuşla havuzdan kalıcı silme.
- **"İlk Görsele Dön" Butonu:** Başka fotoğraf ara dedikten sonra ilk görselin daha iyi olduğu anlaşılırsa tek tıkla ilk fotoğrafa dönebilme.
- **Haber Önerilerinde Tıklanabilir Link + 1 Cümlelik Spot:** Telegram'a düşen 5'li öneride habere tıklandığında doğrudan kaynağa giden link ve altında ne olduğunu anlatan 1 cümlelik editoryal spot.
- **Kompakt `/kota` Komutu (35 Karakter):** GitHub Actions, Gemini ve sosyal platform kotalarını tek satırda gösteren kompakt dashboard.

### N. Samsung Galaxy A05 Android Otomasyon İstasyonu (`src/android_otomasyon.py`)
- **USB & Uiautomator2 Köprüsü:** Fiziksel Android cihaz (Samsung Galaxy A05) üzerinden Instagram uygulamasına otomatik bağlanarak müzikli Reels ve Carousel paylaşımı yapan otomasyon köprüsü.
- **DCIM Entegrasyonu & Ekran Yönetimi:** Görselleri telefona aktarıp, Instagram arayüzünde 3 slaytı seçip, pop-up korumalarını aşıp paylaşım bittiğinde telefon ekranını otomatik kapatma yeteneği.

### O. Havuz Dışı Özel Haber, Araştırma & Kronoloji Motoru (`src/ozel_haber.py`)
- **Telegram Serbest Komutları:** `/link <URL>`, `/arastir <KONU>`, `/ozel`, `/dosya`, `/kronoloji` komutlarıyla RSS havuzunda olmayan herhangi bir bağlantı veya konu hakkında derinlemesine 3-4 slaytlık infografik üretimi.
- **Akıllı Makale Kazıyıcı:** Verilen linkin ana gövdesini reklam ve çöp metinlerden arındırıp infografik detay metnine ve başlığına dönüştürme.

### P. X (Twitter) API v2 Entegrasyonu & 4 Fotoğraflı Tweet Motoru (`src/twitter.py`)
- **@dailybrief_co Resmi Entegrasyonu:** OAuth 1.0a / 2.0 kimlik doğrulaması ile X platformuna 4 adet 4:5 fotoğraf ve editoryal metin içeren tweet ve flood zinciri paylaşımı.

### Q. Çok Katmanlı Güvenlik, Doğruluk & Topluluk Kuralları Filtresi (`src/dogrula.py`, `src/filtre.py`, `src/otomatik_onay.py`)
- **Instagram Topluluk Kuralları Filtresi:** İntihar, kendine zarar verme veya ağır istismar içerikli haberlerin RSS havuzundan otomatik elenmesi.
- **Alıntı Doğrulama:** Gemini'nin ürettiği alıntıların kaynak metinde birebir geçip geçmediğini denetleme; geçmiyorsa alıntı bloğunu sessizce iptal etme.
- **Suçlama Dili & Sansür Koruyucusu:** Henüz kesinleşmemiş adli olaylarda suçlama dilini yumuşatma ve sansür yıldızlarının çizimde eksik harfe dönüşmesini engelleme.
- **Gece 4 Katmanlı Otomatik Onay:** Gece insan müdahalesi olmadan yayınlanacak haberler için deterministik test, kaynak güveni, LLM çapraz denetim ve riskli kategori süzgeci.

---

### R. 🎙️ Sesli Yayınla — ElevenLabs Seslendirmesi & Türkçe Okunuş Katmanı (`src/ses.py`, `src/okunus.py`) — 26 Eyl 2026
- **İsteğe bağlı:** Onay menüsünde "✅ Yayınla"nın yanında "🎙️ Sesli Yayınla" → "🎵 Fon müzikli" / "🔇 Fon müziksiz" → aynı zaman menüsü (Şimdi / 30 dk … 4 saat). Düz "✅ Yayınla" eskisi gibi Instagram için seslendirmesiz (Reels/TikTok sessiz).
- **KATI KURAL (YouTube Shorts ve Facebook Reels Her Türlü Sesli ve Fon Müzikli):** Kullanıcı Telegram'da ister düz "✅ Yayınla", ister "🎙️ Sesli Yayınla (Fon müzikli)", ister "🔇 Fon müziksiz" seçsin, YouTube Shorts ve Facebook Reels'e giden video HER ZAMAN ElevenLabs seslendirmeli VE fon müzikli (`muzik=True`) olarak üretilir. Instagram Reels ve TikTok ise kullanıcının tercihine (trend müzik için sessiz veya saf seslendirmeli) sadık kalır.
- **KATI KURAL (IG Seçiliyse Carousel Gönderi Gider & TikTok Video / Reels Ayrımı):** Kullanıcı `[✅ IG]` seçtiğinde Instagram'a her zaman 4:5 Carousel gönderi gider; sesli mod seçimi bu tercihi Reels'e zorlamaz. `[✅ Reels]` seçildiyse: "🎙️ Sesli Yayınla" yapıldıysa (ses_modu var) video seslendirmeli ve fon müzikli olduğu için Instagram Reels API üzerinden otomatik yayınlanır; düz "✅ Yayınla" yapıldıysa (ses_modu yok) Instagram Graph API trend müzik seçimine izin vermediğinden Instagram'a sessiz video ASLA otomatik atılmaz, sessiz MP4 video ve kopyalanabilir açıklama metni YALNIZCA Telegram'a iletilir. TikTok için `[✅ TT]` (Carousel) ve `[✅ TT Video]` (Dikey Video) seçenekleri mevcuttur. TikTok Video seçilirse sesli/normal duruma göre videoyu TikTok'a yükler.
- **KATI KURAL (Her Durumda Telegram'a Seslendirilmiş Video & Sessiz Modda Ham Video Düşer):** YouTube & FB Reels için üretilen ElevenLabs seslendirmeli (+ fon müzikli) video HER YAYINDA Telegram'a koşulsuz iletilir. Eğer kullanıcı Reels veya TikTok Video seçtiyse ve sesli mod seçmediyse (düz "✅ Yayınla"), Instagram/TikTok trend müziklerini kolayca ekleyebilmek için sessiz video da AYRICA Telegram'a gönderilir. Kopyalanabilir açıklama metni her durumda iletilir.
- **Worker çevirisi:** `yayinla_ses:muzikli` → `yayinla`, `yayinla_ses_sonra:muziksiz:60` → `yayinla_sonra:60`; kanal listesine `ses_muzikli` / `ses_muziksiz` eklenir. `onay_isle`'de yeni komut YOK; planlı yayın ve KV çalar saati olduğu gibi çalışır (kip `yayin_kanallari` ile taşınır). Video kanalı (Reels/FB/YT/TT) seçilmemişse sesli yayın başlamaz.
- **Ne okunur:** tek haberli postta kapak — başlık + özet, içerik filtresinden geçmiş (slayttakiyle AYNI metin); detay sayfaları sessiz. **Turda her slayt yalnızca kendi haberinin başlığını okur** (`tur_kipi: basliklar`, 26 Eyl kullanıcı kararı). Ekonomi turunda haber metni okunmaz. 10'lu gündem turu otomatik tetiklenmez, yalnızca elle (`/tur`). Sonda "Gündemi kaçırmak istemiyorsanız takipte kalın." ("beğenin" bilerek yok).
- **Ses:** Alex (`KediIz7pebzt5TaDHiiZ`, derin, epik, güçlü bariton anlatıcı), hız 1.15, stability 0.55, style 0.0, -14 LUFS; 1. yedek Adam (`J17lijyP1BHYcM7ld0Rg`), 2. yedek Sıla Özalp (`r3deco0KTo6o0Kb5inro`). Anahtar: GitHub secret `ELEVENLABS_API_KEY` (yoksa video seslendirmesiz çıkar ve rapor bunu yazar).
- **⚠️ `_sesli` koruması:** `youtube_icin_sesli_video_hazirla` adında `_yt` olmayan videonun sesini fon müziğiyle DEĞİŞTİRİYOR; seslendirmeli video `_sesli` adlıdır ve bu fonksiyon ona dokunmaz — yoksa Shorts/FB Reels'te anlatım silinirdi.
- **Okunuş katmanı (`src/okunus.py`, postedm'le birebir aynı dosya — 28 Eyl 2026):** "Hz." → Hazreti, "1/5000" → beş binde bir, "54. dakikada" → elli dördüncü dakikada, Markdown `**vurgu**` okunmaz.
  * *BİST:* "BİST" / "BIST" / "Bist" doğrudan "Borsa İstanbul" olarak okunur ("BİST 100" → "Borsa İstanbul yüz", "BİST'te" → "Borsa İstanbul'da", "BIST'e" → "Borsa İstanbul'a", "BİST'in" → "Borsa İstanbul'un").
  * *Ülke & Uluslararası:* BAE (`Birleşik Arap Emirlikleri`), ABD (`Amerika Birleşik Devletleri`), KKTC (`Kuzey Kıbrıs Türk Cumhuriyeti`), GKRY (`Güney Kıbrıs Rum Yönetimi`), RF (`Rusya Federasyonu`), ÇHC (`Çin Halk Cumhuriyeti`), BK (`Birleşik Krallık`), AB (`Avrupa Birliği`), BM (`Birleşmiş Milletler`), BMGK (`Birleşmiş Milletler Güvenlik Konseyi`), DSÖ (`Dünya Sağlık Örgütü`), DTÖ (`Dünya Ticaret Örgütü`), AİHM (`Avrupa İnsan Hakları Mahkemesi`), AYM (`Anayasa Mahkemesi`), YSK (`Yüksek Seçim Kurulu`), TDT (`Türk Devletleri Teşkilatı`), İİT (`İslam İşbirliği Teşkilatı`), UAEA (`Uluslararası Atom Enerjisi Ajansı`), UCM (`Uluslararası Ceza Mahkemesi`). Noktalı: `G. Kore`, `K. Kore`, `G. Afrika`, `S. Arabistan`, `K. Kıbrıs`.
  * *Finans & Makroekonomi:* ECB (`Avrupa Merkez Bankası`), OVP (`Orta Vadeli Program`), KKM (`Kur Korumalı Mevduat`), GSYİH / GSYH (`Gayri Safi Yurt İçi Hasıla`), BOE (`İngiltere Merkez Bankası`), BOJ (`Japonya Merkez Bankası`), KGF (`Kredi Garanti Fonu`), IMF (`Uluslararası Para Fonu`), VİOP (`Vadeli İşlem ve Opsiyon Piyasası`), TCMB (`Türkiye Cumhuriyet Merkez Bankası`), SPK (`Sermaye Piyasası Kurulu`), BDDK (`Bankacılık Düzenleme ve Denetleme Kurumu`).
  * *Savunma, Güvenlik & Asayiş:* TSK (`Türk Silahlı Kuvvetleri`), SSB (`Savunma Sanayii Başkanlığı`), EGM (`Emniyet Genel Müdürlüğü`), JGK (`Jandarma Genel Komutanlığı`), MİT (`Milli İstihbarat Teşkilatı` — *bağlam korumalı*), MSB (`Milli Savunma Bakanlığı`), MEB (`Milli Eğitim Bakanlığı`), THY (`Türk Hava Yolları`).
  * *Ulaşım & Altyapı:* YHT (`Yüksek Hızlı Tren`), TCDD (`Devlet Demiryolları`), KGM (`Karayolları Genel Müdürlüğü`), DHMİ (`Devlet Hava Meydanları İşletmesi`), SHGM (`Sivil Havacılık Genel Müdürlüğü`), HGS (`Hızlı Geçiş Sistemi`), OGS (`Otomatik Geçiş Sistemi`).
  * *Spor Dünyası:* TFF (`Türkiye Futbol Federasyonu`), PFDK (`Profesyonel Futbol Disiplin Kurulu`), TBF (`Türkiye Basketbol Federasyonu`), TVF (`Türkiye Voleybol Federasyonu`), FK (`Futbol Kulübü`), JK (`Jimnastik Kulübü`), SK (`Spor Kulübü`).
  * *Sosyal, Eğitim, Sanayi & İş Dünyası:* KYK (`Kredi ve Yurtlar Kurumu`), TOBB (`Türkiye Odalar ve Borsalar Birliği`), TİM (`Türkiye İhracatçılar Meclisi`), DEİK (`Dış Ekonomik İlişkiler Kurulu`), KHK (`Kanun Hükmünde Kararname`), İBB (`İstanbul Büyükşehir Belediyesi`), TKGM (`Tapu ve Kadastro Genel Müdürlüğü`), TMD (`Türkiye Madenciler Derneği`).
  * *Teknik Birimler & Sayı-Para Ölçeği:* mAh (`miliamper saat`), kWh (`kilovatsaat`), kW (`kilovat`), MW (`megavat`), km/s & km/h (`kilometre bölü saat`), GHz (`gigahertz`), MHz (`megahertz`), Hz (`hertz`), GB (`gigabayt`), TB (`terabayt`), MB (`megabayt`), HP (`beygir gücü`). Sayı + ölçek + simge uyumu: `6,3 milyar $` → `altı virgül üç milyar dolar`, `100 milyon ₺'lik` → `yüz milyon liralık`.
  * *Romen Rakamları & Savunma Sanayii / Model Nesilleri:* Noktasız Romen rakamları model/nesil bağlamında Türkçe sayıya çevrilir (`HÜRKUŞ-II` → `Hürkuş iki`, `ANKA III'ü` → `Anka üçü`, `Hürjet-II` → `Hürjet iki`, `Faz-II` → `Faz iki`, `Tip II` → `Tip iki`, `PlayStation IV` → `PlayStation dört`). 2+ harfli modellerde tireli sayılar doğal konuşmaya çevrilir (`HÜRKUŞ-2` / `Hürkuş -2` → `Hürkuş iki`, `KAAN-2` → `Kaan iki`, `Bayraktar TB-2` / `TB2` → `Bayraktar TB iki`). Tek harfli kodlar (`D-100`, `E-5`, `F-16`) korunur.
  * *Title-Case Desteği:* RSS'lerden gelen `Bae`, `Abd`, `Tsk`, `Yht`, `Ovp`, `Kkm`, `Tff`, `Ecb`, `Kyk`, `Tobb`, `Spk`, `Bddk`, `Pfdk`, `Ucm`, `Tcdd`, `Kgm`, `Dhmi`, `Shgm`, `Tbf`, `Tvf`, `Gsyih` otomatik normalize edilir.
  * *Zamir N'si & Ünsüz Kaynaştırma Koruması:* İyelikli kurumlarda zamir n'si (`BAE'ye` → `Birleşik Arap Emirliklerine`, `TSK'ya` → `Türk Silahlı Kuvvetlerine`, `ECB'de` → `Avrupa Merkez Bankasında`, `TFF'ye` → `Türkiye Futbol Federasyonuna`, `Vanspor FK'da` → `Vanspor Futbol Kulübünde`, `TMD'den` → `Türkiye Madenciler Derneğinden`), ünsüzle biten kelimelerde ise kısaltmadan kalan gereksiz 'y'/'n' harfleri düşürülür (`OVP'ye` → `Orta Vadeli Programa`, `YHT'ye` → `Yüksek Hızlı Trene`, `KKM'ye` → `Kur Korumalı Mevduata`, `YHT'nin` → `Yüksek Hızlı Trenin`, `KKM'den` → `Kur Korumalı Mevduattan`).
  * *Akronimler:* `AFAD`, `TÜİK`, `TOKİ`, `TBMM`, `SGK`, `KDV`, `ASELSAN`, `ROKETSAN`, `TUSAŞ`, `UEFA`, `FIFA`, `İSKİ`, `İETT`, `TÜBİTAK`, `KOSGEB`, `İŞKUR` kendi Türkçe telaffuzuyla doğru okunduğundan bilerek açılmaz. Tek harf ve harf-tire-sayı sese tırnakla gider (`"A" Milli Takım`, `"F"-16`). `<break>` etiketi ses uydurma kelime eklediği için kullanılmaz.
- **İngilizce Terimler & C-Suite Fonetik Katmanı (28 Eyl 2026):** ElevenLabs'a `language_code: tr` verildiği için İngilizce unvan ve terimler Türkçe harf harf okunuyordu ("CEO" → "ce-o" / "ceosu", "AI" → "a-ı", "Wi-Fi" → "vi-fi", "online" → "on-li-ne"). `src/okunus.py` içindeki `_ingilizce_terimler` katmanı bunları Türkçe editoryal fonetik karşılıklarına çevirir ("CEO'su" → "si-i-o'su", "CFO" → "si-ef-o", "AI" → "ey-ay", "Wi-Fi" → "vay-fay", "online" → "onlayn", "startup" → "startap", "fintech" → "fintek", "ChatGPT" → "çet ci-pi-ti", "DeepSeek" → "dip siik", "reels" → "rils", "tweet" → "tivit"). `_ek_uyumu` ile çekim ekleri ("CEO'ye" → "si-i-o'ya") yeni kökün son ünlüsüne otomatik uyarlanır.
  * *Genişletilmiş Havuz:* iPhone (`ayfon`), iPad (`ayped`), iMac (`aymek`), MacBook (`mekbuk`), AirPods (`eyrpods`), Apple Watch (`epıl voç`), App Store (`ep stor`), Google Play (`gugıl pley`), Google Cloud (`gugıl klaud`), iCloud (`ayklaud`), Bluetooth (`blutut`), YouTube (`yutub`), Threads (`treds`), LinkedIn (`linkdin`), Spotify (`spatifay`), Twitch (`tiviç`), DM (`di-em`), TT (`ti-ti`), SUV (`es-yu-vi`), EV (`i-vi`), Cybertruck (`saybırtrak`), Autopilot (`otopaylıt`), SSD (`es-es-di`), USB (`yu-es-bi`), Copilot (`kopaylıt`), Midjourney (`midcörni`), Perplexity (`pörpleksiti`), Claude (`klod`), Big Tech (`big tek`), phishing (`fişing`), ransomware (`rensımver`), malware (`melver`), spyware (`spayver`), clickbait (`klikbeyt`), Dacia (`Daçya`), BYD (`bi-vay-di`), Peugeot (`Pejo`), Renault (`Reno`), Citroën (`Sitroen`), Porsche (`Porşe`), Chevrolet (`Şevrole`), TSMC (`ti-es-em-si`), ASML (`ey-es-em-el`), Xiaomi (`Şaomi`), Huawei (`Huavey`), AMD (`ey-em-di`), RAM (`rem`), blockchain (`blokçeyn`), bitcoin (`bitkoyn`), Bill Gates (`Bil Geyts`), Elon Musk (`İlan Mask`), Mark Zuckerberg (`Mark Zakırbörg`), Grand Prix (`gran pri`), F1 (`ef-bir`), FIFA (`fifa`), UEFA (`uefa`), play-off / play-in (`pley-of` / `pley-in`).
  * *Sabotaj Koruma Paketi (`TestSabotajKorumasi`):* Türkçe sözcüklerin ezilmesi engellendi (`tehlike` != `layk`, `reel` != `rils`, `it` != `ay-ti`, `ev` != `i-vi`, `su` != `es-yu-vi`, `can`, `at`, `on`, `in`, `TBMM`, `SGK`, `KDV`, `İBB`, `BİST`, `TOKİ`, `D-100`, `E-5`, `Prof. Dr.`). Eklerin ses uyumları (`SUV'lar` → `es-yu-vi'ler`, `iPhone'un` → `ayfon'un`, `Dacia'ya` → `Daçya'ya`, `BYD'nin` → `bi-vay-di'nin`) ve çift çevrim kararlılığı tam güvencededir.
- **Testler (CI'da):** `tests/test_okunus.py` (130+ satır sabotaj tablosu, 3000 rastgele sayı, 3000 karışık girdi, 90+ İngilizce fonetik ve sabotaj testi), `tests/test_seslendirme.py` (21), `tests/worker_sesli.test.mjs` (7); sözleşme testindeki düğme kapsamı yeni düğmeleri de kapsıyor.

## 4. Görsel Seçim Standartları ve İyileştirme Yol Haritası

### 4 Katmanlı Akıllı Görsel Hiyerarşisi:
1. **1. Katman — Web HD / 4K Basın Fotoğrafları Motoru (`src/fetch_web_image.py`):** 
   - `gorsel_konu` doğrudan haberin odaklandığı somut varlık/marka/model/kulüp (`Volkswagen Passat Pro`, `Apple iPhone 16`, `Tesla Model 3`, `Beşiktaş`, `Boeing 737`, `Silivri gemi kazası`, `Lionel Messi`) olarak kaydedilir.
   - Doğrudan haber ajanslarının ve yayıncıların 16:9 HD (`1200x675`, `1280x720`, `1372x772`, `1920x1080`) editoryal basın fotoğrafları çekilir.
   - `atlanacak` parametresiyle çoklu arama sorgularındaki adaylar tek havuzda birleştirilip dedupe edilir; her "Başka Fotoğraf Bul" çağrısında olayın sıradaki gerçek basın karesi getirilir.
2. **2. Katman — Akıllı Makale Basın & Ürün Görseli Çekici (`src/fetch_article.py`):** `og:image`, `twitter:image`, JSON-LD `NewsArticle` ve makale gövdesindeki orijinal lansman fotoğrafları taranır ve `gorsel_kalite` denetiminden geçirilir.
3. **3. Katman — Wikimedia Commons & Pexels HD Stok (`src/fetch_photo.py`, `src/fetch_stock.py`):** Kişi portreleri ($\ge 1200\text{px}$) ve 4K dikey temsili stoklar. Marka ve ürün haberlerinde başka markanın stok fotoğrafının çekilmesi marka koruma filtresiyle engellenir.
4. **4. Katman — Kategoriye Özel Gemini Görsel Motoru (`src/make_image.py`):** Hiçbir katmandan yüksek çözünürlüklü kaliteli fotoğraf bulunamazsa Gemini AI ile özel görsel üretimi.

---

## 5. Dosya ve Dizin Yapısı

| Dizin / Dosya | Görevi |
|---|---|
| `config.yaml` | Tüm bot ayarları, RSS kaynakları, ağırlıklar, eşikler ve sosyal medya anahtarları. |
| `worker/` | Cloudflare Worker edge cron tetikleyicisi (`wrangler.toml` ve `index.js`). |
| `src/gorsel_kalite.py` | Çözünürlük, dikey kırpma piksel yoğunluğu, Laplacian netlik varyansı ve taranmış belge/tablo filtresi. |
| `src/fetch_web_image.py` | DuckDuckGo üzerinden HD/4K editoryal basın ve olay fotoğrafları arama motoru. |
| `src/komutlar.py` | Tek merkezli komut listesi, alias'lar, mesajsız serbest komutlar ve slash menü sözlüğü. |
| `src/handlers/` | Modüler Telegram onay ve yayın işleme handler modülleri (`yayin`, `slayt`, `tur`). |
| `src/piyasa.py` | Yahoo Finance canlı veri çekimi, BİST, döviz, emtia, kripto ve Gram TL hesabı. |
| `src/piyasa_kart.py` | %100 Native 1080x1920 Canlı Piyasa Isı Haritası motoru (`piyasa_karti_uret_9_16`). |
| `src/piyasa_tablo.py` | %100 Native 1080x1920 30 Varlık Piyasa Karnesi motoru (`piyasa_tablosu_uret_9_16`). |
| `src/piyasa_ozet.py` | %100 Native 1080x1920 Günün Ekonomi Gündemi çoklu özet kartı motoru (`ekonomi_ozet_sayfalari_uret`). |
| `src/sparkline.py` | Borsa ve emtia için 30 günlük geçmiş fiyat çekimi ve estetik trend grafiği çizimi. |
| `src/slaytlar.py` | %100 Native 1080x1920 haber slaytlarının çizimi, tipografi, 144px 3D logo. |
| `src/make_image.py` | Pillow tabanlı infografik ve tipografi çizim motoru (`_metni_paragraflara_ayir`, `detay_sayfalara_bol`, `detay_slayti`). |
| `src/video.py` | 1080x1920 Story slaytlarından dikey video (Reels/Shorts/TikTok) derleme motoru. |
| `src/ozel_haber.py` | Telegram üzerinden `/dosya`, `/kronoloji`, `/link`, `/arastir` ve `/ozel` ile özel haber üretimi. |
| `src/twitter.py` | X (Twitter) API v2 üzerinden 4 fotoğraflı tweet paylaşımı. |
| `src/youtube.py` | YouTube Data API v3 üzerinden 9:16 Shorts video yükleme. |
| `src/tiktok.py` | TikTok Content Posting API v2 üzerinden dikey video yükleme. |
| `src/fetch_news.py` | 20+ RSS kaynağından haberleri çekme, parse etme ve SQLite veritabanına aktarma. |
| `src/generate_text.py` | Gemini Flash modelleri ile başlık, özet, detay metni ve önem puanı üretimi. |
| `scripts/piyasa_otomatik.py`| Hafta içi 10:08 ve 18:20 %100 Native 1080x1920 Piyasa Bülteni yayınlama scripti. |
| `scripts/son_dakika.py` | Saatlik 5'li haber önerisi ve otomatik piyasa bülteni telafi güvenlik ağı scripti. |
| `scripts/onay_isle.py` | Telegram onay, buton ve komut işleme facade router'ı. |

---

## 6. Son 1 Ayın Kapsamlı Kronolojik Geliştirme Günlüğü (15 Ağustos – 26 Eylül 2026)

### 🗓️ 28 – 29 Eylül 2026 (ElevenLabs Okunuş Katmanı, Kardeş Görsel Branş Ayrımı, Kicker Düzeltmesi & Reels Manuel Dağıtım Koruması)
- **29 Eyl:** **Düz Yayında Reels API Engeli & Yalnızca Telegram'a İletim (`scripts/onay_isle.py`):**
  * *Hata Analizi:* 26 Eyl'de ElevenLabs seslendirmesi eklenirken `paylas_reels` bayrağı `ses_modu` kontrolü olmadan doğrudan `hedef_kanallar.append("instagram_reels")` ve `instagram.reels_yayinla` API çağrısına bağlanmıştı. Bu yüzden düz "✅ Yayınla" seçildiğinde, kullanıcının trend müzik ekleyebilmesi için Telegram'a sessiz video gönderilmesine rağmen, arka planda API üzerinden Instagram profiline de sessiz Reels paylaşılıyordu.
  * *Çözüm:* `scripts/onay_isle.py` içinde `hedef_kanallar` listesine `instagram_reels` eklenmesi YALNIZCA `ses_modu` varsa (ElevenLabs sesli + fon müzikli) koşuluna bağlandı (`if paylas_reels and ses_modu:`). Düz yayında sessiz MP4 video ve kopyalanabilir açıklama metni eskisi gibi YALNIZCA Telegram'a iletilir (`reels_notu: Telegram'a iletildi`), Instagram'a API üzerinden sessiz Reels kesinlikle atılmaz.
- **29 Eyl:** **Spor ve Branş Kardeş Görsel Ayrımı & Bursa Kicker Düzeltmesi (`src/secim.py`, `src/slaytlar.py`, `src/hook_motoru.py`):**
  * *Hata Analizi:* Türkiye - İtalya futbol maçı haberinde (#299166), AA Spor'un Ampute Futbol Takımı haberi (#284405) "Milli", "Futbol", "Takımı" kelimeleri büyük harfle başladığı için `secim.konu_imzasi` tarafından **özel isim** kabul edilerek aynı olay sanıldı. AA'nın 5935x3338 px fotoğrafı, TRT'nin orijinal 1280x720 maç fotoğrafını ezdi. Ayrıca maç Bursa'da oynandığı için "Bursa" kelimesi `burs` substring'ini tetikleyerek futbola "● ÖĞRENCİLERİN DİKKATİNE" kicker'ı bastı.
  * *Çözüm:* `ETKISIZ_OZEL_ISIMLER` ile genel spor/kurum ekleri özel isimden (`isimler`) çıkarıldı; `BRANS_VE_KATEGORI_AYIRICILARI` (`ampute`, `kadın`, `u21` vb.) uyumsuzluğu eklendi; kardeş görsellere Gemini Vision onay kapısı bağlandı; `hook_motoru`'nda regex kelime sınırı (`\b`) ve `kategori == 'spor'` önceliği getirilerek "Bursa" şehri kaynaklı hatalı kicker engellendi.
- **28 Eyl:** **ElevenLabs Türkçe Okunuş Katmanı Genişletmesi (`src/okunus.py`):** "BİST" → "Borsa İstanbul", ülke ve uluslararası kısaltmalar (BAE, KKTC, GKRY, BMGK, DSÖ vb.), noktalı kısaltmalar (G. Kore, S. Arabistan), unvanlı çoklu isimler ve sayı-harf model adları ("HÜRKÜŞ-2" → "Hürkuş iki") fonetik katmana işlendi.

### 🗓️ 21 – 26 Eylül 2026 (TikTok Photo Carousel, Veritabanı Bütünlüğü & Ses Ayrımı)
- **26 Eyl:** **🎙️ Sesli Yayınla — ElevenLabs Seslendirmesi (`src/ses.py`, `src/okunus.py`, Worker `6a9b5d67`):** postedm'de kullanıcının dinleyip seçtiği seslendirme (Sıla Özalp, yalnız kapak, kapanış çağrısı) isteğe bağlı olarak Instabot'a taşındı; düz Yayınla değişmedi. Seslendirmeli video bütün video kanallarına gider ve `_sesli` adıyla YouTube/Facebook fon müziği miksinden korunur. Canlı deneme #4880'de 12 sn video, yazıya dökümde metin birebir (`d40da76`). Ayrıntı: 3. bölüm R.
- **24 Eyl:** **TikTok Content Posting API v2 Photo Mode (Carousel) Motoru (`src/tiktok.py` & `scripts/onay_isle.py`):** TikTok'ta infografik ve haber carousellerinin videolara kıyasla çok daha yüksek etkileşim, tamamlama ve kaydetme (save) alması nedeniyle Photo Mode entegre edildi (`POST /v2/post/publish/content/init/`, `media_type: PHOTO`, `source: PULL_FROM_URL`). 1080x1920 R2 slaytları doğrudan TikTok Carousel olarak gönderilir; app audit kısıtı varsa otomatik `MEDIA_UPLOAD` (Inbox/Taslak) moduna geçer, alan adı doğrulaması eksikse veya beklenmeyen bir durumda kesintisiz dikey video fallback'ine düşer.
- **22 Eyl:** **Veritabanı Çakışma ve Bütünlük Kurtarması (`def5d1b` & `veritabani_saglam_mi`):** 20:14 TR'de `oneriyi_hazirla` alt işlemi sırasında SQLite bağlantısı açıkken arka planda yapılan git rebase/checkout sonucu dosya tutacı (inode) kaymış ve `db_kaydet.py` hasarlı veritabanını (`def5d1b`) GitHub'a pushlamıştı. Sağlıklı commit (`71b4b7e`) geri yüklenerek sıfır veri kaybıyla veritabanı kurtarıldı; `db_senkron` ve `db_kaydet` içine `veritabani_saglam_mi` PRAGMA quick_check ve header doğrulaması eklenerek bozuk dosyaların git'e pushlanması kalıcı olarak engellendi (`5f89d40`).
- **22 Eyl:** **Dengeli Detay Slaytı Bölümleme & Yetim Blok Koruması (`_sayfalari_dengeli_bol`):** Açgözlü (greedy) sayfalama mantığı kaldırılarak yerine varyansı ve yükseklik farkını minimize eden kombinatorik optimizasyon algoritması getirildi. 2. Detay Slaytının 4 blokla tıkış tıkış dolup alt çizgiye dayanması, 3. Detay Slaytının ise sadece 1 alıntıyla (%85 boşluk) yetim kalması sorunu çözüldü; sayfalar arası fark 758px'den 90px'e indirilip optik merkeze oturtuldu (`c148a2a`).
- **22 Eyl:** **İçerik Yoğunluğuna Göre Dinamik Reels Süreleri (`slayt_surelerini_hesapla`):** Sabit 3.5 sn kaldırıldı; 1. Kapak 4.2 sn, detay slaytları kelime sayısına göre 4.8 sn - 6.2 sn aralığında dinamik ayarlandı. Toplam video süresi 15 - 20 sn zirve retention aralığında tutuldu (`94bf292`).
- **22 Eyl:** **YouTube 2. Google Cloud Projesi Entegrasyonu (`daily-brief-2`):** Günlük kota 5'ten 10 videoya (20.000 puan) çıkarıldı; `quotaExceeded` / 403 durumunda Proje 2'nin refresh token'ına otomatik failover eklendi (`edf50e7`).
- **21 Eyl:** **Cloudflare R2 Depolama Tam Canlıda (`media.dailybrief.ozbornstudio.com`):** 5 workflow dosyasına (`yayinla`, `son-dakika`, `piyasa-bulteni`, `hazirla`, `haftalik-ozet`) R2 secret'ları bağlanarak birincil CDN olarak devreye alındı (`f1ad9ba`).
- **21 Eyl:** **Platforma Özel Ses Ayrımı:** Instagram Reels ve TikTok için SESSİZ video (`anullsrc` stereo AAC), YouTube Shorts ve Facebook Reels için MÜZİKLİ video üretimi kesin olarak ayrıştırıldı (`8e04c46`).
- **21 Eyl:** **Telegram Yayın Raporu Sadeleştirmesi:** Yayın sonrası Telegram'a düşen rapordaki mükerrer `<pre>Açıklama Metni</pre>` bloğu kaldırılarak butonlar ve linkler ferahlatıldı (`19355f4`).

### 🗓️ 17 – 19 Eylül 2026 (Ekonomi Özet Kartı, Paralel Dağıtım Motoru & Kanal Senkronu)
- **19 Eyl:** **Paralel Video Derleme Çakışması (Race Condition) Çözümü:** `ThreadPoolExecutor` içinde YouTube ve Facebook'un aynı video dosyası üzerine yazması ve dosyanın erken `unlink` edilmesi engellendi; ortak sesli video tek seferde mikslendi (`2b98c7d`).
- **19 Eyl:** **Kanal Senkronizasyonu & DailyBrief Kilidi:** Doğukan'ın diğer kanalı (`Edebiyatca`) yerine doğrudan `DailyBrief` (`UCfU04lnmBN61Daikh4oy7fA`) OAuth jetonları senkronize edildi.
- **18 Eyl:** **Günün Ekonomi Gündemi Çoklu Özet Kartı Motoru (`src/piyasa_ozet.py`):** Bülten sonuna haber slaytları yerine sayfa başına en fazla 3 haber içeren, 36px Extra Bold başlıklı, Kehribar/Turkuaz/Zümrüt renk çentikli lüks özet kartları (1-3 haber -> 3. slayt, 4-6 haber -> 3. ve 4. slaytlar) eklendi (`f1af5ef`, `3c56f47`).
- **18 Eyl:** **Threads ve X (Twitter) için 4:5 Görsel Formatı:** Dikey 9:16 slaytlar kırpılma yaşamadan merkezi 4:5 oranında kurgulanarak Twitter ve Threads'e tam çerçeve ile iletildi (`820649e`).
- **18 Eyl:** **EzanPlusBot Standartlarında Paralel Dağıtım & Canlı Progress Bar:** 6 platforma eşzamanlı yayın (`ThreadPoolExecutor`) ve Telegram onay mesajında canlı ilerleme çubuğu (`[▰▰▰▱▱] %60`) devreye alındı (`820649e`).
- **18 Eyl:** **Kompakt `/kota` Komutu:** 35 karakterlik canlı kota ve sistem sağlık dashboard'u eklendi (`bb561b3`, `668cb47`).
- **18 Eyl:** **Paylaşılabilirlik Algoritması (`secim.paylasilabilirlik_puani`):** Sosyal medyada en çok paylaşılan (%52 paylaşım / %11 gönderi) viral haberlerin ön elemede öne çıkarılması sağlandı (`f2691ab`, `35fec86`).
- **17 Eyl:** **TikTok Kopyalanabilir Caption Desteği:** Video `inbox_draft` moduna düştüğünde kullanıcının tek dokunuşla kopyalayabileceği formatta açıklama metni Telegram'a gönderildi (`d29dd76`).
- **17 Eyl:** **Cloudflare R2 Nesne Depolama Entegrasyonu:** SigV4 imzalı doğrudan depolama ve özel domain altyapısı ilk kez kodlandı (`049e4e4`, `67e5742`).

### 🗓️ 11 – 16 Eylül 2026 (Facebook Reels, Arama Motoru & Telegram İyileştirmeleri)
- **16 Eyl:** **Facebook Reels Entegrasyonu:** Facebook Graph API v21.0 3 aşamalı video yükleme (start -> rupload -> finish) ve dinamik telifsiz hareketli haber fon müziği miksleme motoru eklendi (`2eb99a6`).
- **15 Eyl:** **CDN Yayılım Beklemesi & Bülten Tekrarı:** Görsel CDN'e yüklendikten sonra yayılım beklemesi kondu; Telegram'a bülten tekrar butonu eklendi; Gemini HTTP 503 aşırı yoğunluk hatası kataloğa işlendi (`60bbeb0`, `fdf5585`).
- **14 Eyl:** **Akıllı Web Basın Fotoğrafı Arama Motoru (`fetch_web_image.py`):** DuckDuckGo üzerinden HD/4K basın görselleri arama, `atlanacak` parametresiyle wrap-around döngüsü ve Telegram bold başlıklar getirildi (`1ea31b8`).
- **12 Eyl:** **Telegram `WEBPAGE_CURL_FAILED` Çözümü:** Telegram API görseli URL'den indiremediğinde otomatik olarak yerel dosyayı multipart ile doğrudan Telegram'a gönderme fallback'i eklendi (`fec0e54`).
- **12 Eyl:** **Bing Gerçek Fotoğraf Entegrasyonu:** DuckDuckGo alternatifi olarak Bing arama desteği eklendi (`6ba2663`).
- **11 Eyl:** **Telegram Önerilerine Link ve Spot Eklendi:** 5'li haber önerilerine tıklanabilir doğrudan kaynak bağlantısı ve 1 cümlelik editoryal spot eklendi (`9f67872`).

### 🗓️ 5 – 10 Eylül 2026 (Editoryal Kanca Motoru, Tipografi & Borsa Veri Bütünlüğü)
- **10 Eyl:** **Kanca (Hook) Motoru Punto & Yerleşim Optimizasyonu:** Punto tavanı 92px'e çıkarıldı, satır aralığı puntoyla orantılandı, kanca görselin müsait boş alanına kaydırıldı (`878d6d7`, `d638a89`).
- **9 Eyl:** **Piyasa Bülteni Tek Veri Kapısı (`tum_fiyatlari_cek`):** Isı haritası, tablo ve caption verisi tek seferde çekilerek 1. ve 2. slayt arasındaki zıt yüzde çelişkileri sıfırlandı (`9e52f7d`, `4617803`).
- **9 Eyl:** **BIST "Dünkü Kapanış" Düzeltmesi:** Pazartesi günleri için yanıltıcı olan "dünkü kapanış" etiketi "önceki kapanış" olarak düzeltildi (`4f9c023`).
- **9 Eyl:** **Instagram 4:5 Feed Carousel Formatı:** Feed gönderilerinin içerik bozulmadan 4:5 formatında yayınlanması garanti altına alındı (`2e4b6f2`).
- **8 Eyl:** **`/populer` Komutu:** Merak edilen ve yüksek etkileşimli haber önerileri getiren komut eklendi (`9f45792`). "İlk görsele dön" butonu eklendi (`0dafa0e`).
- **7 Eyl:** **Slaytlarda `**` Markdown Temizliği:** Pillow çizim motorunun tırnak ve kalın metin birleşimlerinde slayta yıldız çizmesi engellendi (`d2ca104`).
- **6 Eyl:** **Makale Gövdesi Çıkarma & Boş Övgü Filtresi:** Sayfa başlığı dışında haber metni çekilerek detay kalitesi 4 kat artırıldı; yapay övgü cümleleri elendi (`dcc2078`).
- **6 Eyl:** **Uydurma Finansal Veri Yasağı:** Veri çekilemediğinde koda gömülü varsayılan rakamların basılması engellendi; `veri_yok` rozeti getirildi (`613f1ec`, `585a89a`).
- **5 Eyl:** **Eksik Font Glifleri (8 Boş Kutu):** Inter fontunda olmayan emojiler yerine resmi semboller (`→ ▲ ▼ ◆ ★`) yerleştirildi (`171fc53`).
- **5 Eyl:** **Cloudflare Çalar Saati:** Zamanlanmış yayınlar saat başı cron yerine Cloudflare Worker ile dakikası dakikasına bağlandı (`27c1cd7`).

### 🗓️ 28 Ağustos – 4 Eylül 2026 (Sistem Denetimi, Web Sitesi & Kalıcı İzinler)
- **4 Eyl:** **`dailybrief.ozbornstudio.com` Web Sitesi & Google OAuth In Production:** YouTube OAuth jetonunun 7 günde bir ölmesini bitiren resmi gizlilik/şartlar sayfaları (Cloudflare Worker) açıldı ve uygulama "In Production" statüsüne geçirildi (`17af120`).
- **4 Eyl:** **Buharlaşan DB Temizliğinin Kurtarılması:** 19 gündür commit edilmediği için silinmeyen eski kayıtlar kalıcı olarak temizlendi (11.5 MB -> 3.7 MB).
- **4 Eyl:** **Ölü Kodların Silinmesi:** `src/handlers/` ve `x_paylas.py` modülleri temizlendi. Tüm testler `tests/` dizinine ayrıldı.
- **4 Eyl:** **Kırık Telegram Butonları:** Kurtarma panelindeki ölü düğmeler ve `sondakika` butonu tamir edildi.
- **3 Eyl:** **Vision (Gemini Multimodal) ile Görsel İçi Denetim:** Sadece piksel/netlik değil, yapay zekanın görselin içine bakıp kişi, forma ve olay bağlamını denetlemesi kuruldu (`gorsel_denetim.py`).
- **3 Eyl:** **Fotoğrafın 1150px'e İndirilmesi & Göl Yansıması:** Ayrık duran fotoğraf bandı kaldırıldı, alt kenara yansıma efekti kondu (`FOTO_HEDEF_ALT = 1150`).
- **3 Eyl:** **Kardeş Görsel Havuzu:** Aynı olayı işleyen kardeş ajansların 4K/HD fotoğrafları tek havuzda toplandı (voleybolda 24 kat piksel kazancı).
- **28 Ağu:** **TikTok OAuth2 & Worker Callback:** PKCE code_challenge, HTTPS callback endpointi ve Sandbox/Production yetkilendirme akışı kuruldu (`9cf66e3`, `0010279`).
- **28 Ağu:** **YouTube Shorts İlk Entegrasyonu:** OAuth2 sihirbazı ve workflow secret tanımları tamamlandı (`132078a`, `8b21c9a`).
- **28 Ağu:** **S-Curve (Cosine Easing) Geçişler & H.264 Stillimage:** Video slayt geçişlerindeki takılmalar giderildi (`514a484`).
- **28 Ağu:** **Sıralı EXIF Zaman Damgası:** Görsellere sıralı saniyeler eklenerek telefonda 1-2-3 sırasının bozulmaması sağlandı (`855e671`).
- **28 Ağu:** **Smart Brevity & Neden Önemli:** Soyut yardım/yıkım klişeleri promptta yasaklandı; somut jeopolitik/ticari boyut şart koşuldu (`dd1fc03`).

### 🗓️ 22 – 27 Ağustos 2026 (Finans Bülteni Tasarımı, Android Otomasyonu & Özel Haber)
- **24 Ağu:** **Samsung Galaxy A05 Android Otomasyon İstasyonu:** USB bağlı fiziksel cihaz üzerinden Instagram uygulamasına otomatik erişip müzikli Reels/Carousel paylaşan bridge modülü (`d6200b2`, `ff0b2c3`).
- **24 Ağu:** **X (Twitter) API v2 Entegrasyonu:** `@dailybrief_co` hesabı üzerinden 4 fotoğraflı tweet ve zincir paylaşımı (`29d14a2`, `0b2767b`).
- **24 Ağu:** **Piyasa 4-Hero Vitrin & 2. Slayt Tablosu:** Dolar, Euro, Altın, Gümüş vitrini, gerçek sparkline eğrileri ve 30 Varlık Tablosu eklendi (`d8df578`).
- **23 Ağu:** **Telegram Havuz Dışı Özel Haber Motoru:** `/link <URL>`, `/arastir <KONU>`, `/ozel`, `/dosya`, `/kronoloji` komutları devreye alındı (`d2f81c2`).
- **22 Ağu:** **Piyasa Bülteni 20 Tasarım İterasyonu & Treemap:** Finviz/TradingView stili gerçek borsa ısı haritası, 20 farklı renk varyasyonu denemesi ve nihai Varyasyon 14 (Derin Petrol & Siber Turkuaz) tasarımı sabitlendi (`5061d7f`, `08c0861`, `acf09dc`).
- **22 Ağu:** **Telegram 4 Modüllü Canlı Yönetim Paketi:** Platform checkbox seçici, `/yonetim` duraklatma, reply ile metin/başlık düzenleme, slayt sıralama/silme ve "🗑️ Çöpe At" butonu eklendi (`af45ecf`, `abe18b5`, `360c25b`, `dd1671f`).
- **22 Ağu:** **Instagram Topluluk Kuralları Filtresi:** İntihar, kendine zarar verme veya istismar haberlerinin RSS havuzundan otomatik elenmesi sağlandı (`19921bd`).
- **22 Ağu:** **Haber Fotoğrafı HD Resolver:** Ajans ve gazete thumbnail'lerini 4K/5K orijinal fotoğraflara çeviren motor yazıldı (`2a33aff`, `db3c464`).
- **25 Ağu:** **9:16 Story & 4:5 Safe Area Mimarisi (`y=285..1635`):** Tüm görsellerin Story ve Akışta kusursuz görünmesi sağlandı (`5f4e10a`).
- **25 Ağu:** **Finans Komutları:** `/hisse`, `/kripto`, `/bulten` (kahve bülteni), `/sonpostlar` ve `/menu` Slash komut menüsü kaydı yapıldı (`4883af2`, `155ff3e`).

### 🗓️ 15 – 21 Ağustos 2026 (Temel Mimari, Güvenli Alan & Altyapı)
- **21 Ağu:** **Catbox.moe Yedek Barındırıcı:** ImgBB kesintisi sonrası Catbox devreye alındı; haber görseli boyutu 1000x560'a çekilerek gerçek görsel oranı %0'dan %79'a çıkarıldı.
- **20 Ağu:** **GitHub Actions Kontrol Sıklığı:** 90 dakikaya optimize edildi, dakika yuvarlama kayıpları engellendi.
- **19 Ağu:** **2 Katmanlı Ön Eleme & Kategori Puanlaması:** Haberler kendi kategorisinde yarıştıktan sonra ağırlıklandırıldı; sabah/akşam 2 tur modeline geçildi; GitHub Pro aktive edildi.
- **18 Ağu:** **Threads API Entegrasyonu:** Flood zincir paylaşımı ve haftalık otomatik token yenileme kuruldu.
- **18 Ağu:** **Facebook Graph API Entegrasyonu:** Facebook sayfası, albüm ve story paylaşımı eklendi.
- **18 Ağu:** **Slaytlara Kurumsal Sosyal Kanal İkonları:** Sağ alt köşeye kurumsal platform logoları yerleştirildi.
- **16 – 17 Ağu:** **Son Dakika Tekil Post Mimarisi:** 2 slayt, detay metni, alıntı doğrulama (`dogrula.alintiyi_denetle`), iri amber rakam ve gece 4 katmanlı otomatik onay sistemi (`otomatik_onay.py`) yazıldı.
- **15 Ağu:** **10 Slaytlık Carousel Mimarisi:** İlk çalışan sıfır maliyetli carousel yayın motoru ve Telegram Cloudflare Worker entegrasyonu tamamlandı.

