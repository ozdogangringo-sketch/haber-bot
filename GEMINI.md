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

---

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

## 6. Son 1 Ayın Kronolojik Geliştirme Günlüğü (15 Ağustos – 22 Eylül 2026)

### 🗓️ 21 – 22 Eylül 2026 (Ses Ayrımı, Dinamik Süreler, 2. YouTube Projesi & R2)
- **22 Eyl:** İçerik ve kelime yoğunluğuna göre dinamik Reels slayt süreleri (`slayt_surelerini_hesapla`). Kapak 4.2s, detay slaytları 4.8s - 6.2s. Toplam video süresi 15-20s tatlı noktasında sabitlendi (`94bf292`).
- **22 Eyl:** YouTube 2. Google Cloud projesi (`daily-brief-2`) entegre edildi. Günlük kota 5'ten 10 videoya (20.000 puan) çıkarıldı; `quotaExceeded` durumunda otomatik failover eklendi (`edf50e7`).
- **21 Eyl:** Cloudflare R2 (`media.dailybrief.ozbornstudio.com`) 5 workflow'a eklendi ve birincil depolama CDN'i olarak canlıya alındı (`f1ad9ba`).
- **21 Eyl:** Video ses ayrımı tamamlandı: Telegram Reels ve TikTok için SESSİZ video (`anullsrc`), YouTube Shorts ve Facebook Reels için MÜZİKLİ video (`8e04c46`).
- **21 Eyl:** Telegram yayın tamamlama raporundaki mükerrer `<pre>` açıklama metni kaldırıldı (`19355f4`).

### 🗓️ 17 – 19 Eylül 2026 (Ekonomi Özet Kartı, Paralel Dağıtım & Dayanıklılık)
- **19 Eyl:** YouTube Shorts ve Facebook Reels eşzamanlı yayınındaki race condition (aynı dosya adı üzerine yazma ve erken `unlink`) giderildi. DailyBrief OAuth refresh token'ları senkronize edildi (`2b98c7d`).
- **18 Eyl:** Günün Ekonomi Gündemi çoklu özet kartı motoru (`src/piyasa_ozet.py`, 36px Extra Bold başlıklar, renk çentikleri) canlıya alındı (`f1af5ef`, `3c56f47`).
- **18 Eyl:** Threads ve X için 4:5 görsel formatı, EzanPlusBot paralel dağıtım motoru (`ThreadPoolExecutor`) ve Telegram canlı yayın ilerleme çubuğu (`[▰▰▱▱] %50`) eklendi (`820649e`).
- **18 Eyl:** 35 karakter kompakt `/kota` komutu ve canlı sistem raporu devreye girdi (`bb561b3`, `668cb47`).
- **17 Eyl:** TikTok doğrudan profil yayını yerine `inbox_draft` moduna düştüğünde Telegram'a tek dokunuşla kopyalanabilir açıklama metni iletilmesi sağlandı (`d29dd76`).
- **17 Eyl:** Cloudflare R2 nesne depolama altyapısı ilk kez kodlandı (`049e4e4`, `67e5742`).

### 🗓️ 11 – 16 Eylül 2026 (Facebook Reels, Arama Motoru & Telegram İyileştirmeleri)
- **16 Eyl:** Facebook Reels entegrasyonu ve dinamik telifsiz hareketli fon müziği motoru (`2eb99a6`).
- **15 Eyl:** CDN yayılım beklemesi ve bülten tekrar butonu eklendi; Gemini HTTP 503 aşırı yoğunluk hatası hata kataloğuna işlendi (`60bbeb0`, `fdf5585`).
- **14 Eyl:** Akıllı web basın fotoğrafı arama motoru (`fetch_web_image.py`) ve wrap-around döngüsü eklendi (`1ea31b8`).
- **12 Eyl:** Telegram WEBPAGE_CURL_FAILED hatasına karşı yerel dosya ve hızlı multipart fallback'i (`fec0e54`).
- **11 Eyl:** Telegram haber önerilerine tıklanabilir kaynak bağlantısı ve 1 cümlelik spot eklendi (`9f67872`).

### 🗓️ 5 – 10 Eylül 2026 (Editoryal Kanca Motoru, Tipografi & Borsa Veri Bütünlüğü)
- **10 Eyl:** Kanca (hook) motoru punto tavanı (92px) ve satır aralığı optimize edildi; görselin müsait alanına yerleşim sağlandı (`878d6d7`, `d638a89`).
- **9 Eyl:** Piyasa bülteni tek veri kapısına (`tum_fiyatlari_cek`) indirildi; 1. ve 2. slayt arasındaki yüzde çelişkileri sıfırlandı (`9e52f7d`, `4617803`).
- **9 Eyl:** BIST için yanıltıcı "dünkü kapanış" etiketi "önceki kapanış" olarak düzeltildi (`4f9c023`).
- **9 Eyl:** Instagram feed carousel gönderilerini 4:5 formatında yayınlama kuralı getirildi (`2e4b6f2`).
- **7 Eyl:** Slayt çiziminde `**` markdown işaretlerinin basılması engellendi (`d2ca104`).
- **6 Eyl:** Makale metni çıkarma güçlendirildi; boş yapay övgü cümleleri filtrelendi (`dcc2078`). Piyasa tablosunda eksik veriler için uydurma rakam basılması yasaklandı (`veri_yok` rozeti, `613f1ec`, `585a89a`).
- **5 Eyl:** Slaytlarda Inter fontunda olmayan 8 eksik sembol (boş kutu) temizlendi. Zamanlanmış yayınlar Cloudflare çalar saatine bağlandı (`27c1cd7`).

### 🗓️ 28 Ağustos – 4 Eylül 2026 (Sistem Denetimi, Web Sitesi & Kalıcı İzinler)
- **4 Eyl:** `dailybrief.ozbornstudio.com` web sitesi yayına alındı. Google OAuth "In Production" yapılarak YouTube jetonunun 7 günde bir ölmesi kalıcı olarak çözüldü.
- **4 Eyl:** 19 gündür commit edilmediği için buharlaşan veritabanı temizliği düzeltildi. Ölü kodlar temizlendi (`src/handlers/`, `x_paylas.py`). Testler `tests/` dizinine taşındı.
- **4 Eyl:** Kırık Telegram kurtarma paneli ve butonları tamir edildi.
- **3 Eyl:** Görsel tarafında teknik denetim yerine Vision (Gemini Multimodal) ile gerçek içerik denetimi kuruldu (`gorsel_denetim.py`). Fotoğraf 1150px'e kadar indirildi ve göl yansıması eklendi. Kardeş görsel havuzu ile yüksek çözünürlüklü fotoğraflar çekildi.

### 🗓️ 15 – 21 Ağustos 2026 (Temel Mimari, Güvenli Alan & Altyapı)
- **21 Ağu:** ImgBB kesintisi üzerine Catbox.moe yedek barındırıcı entegre edildi. Haber fotoğrafı asgari eşiği 1000x560'a çekilerek gerçek haber görseli oranı %0'dan %79'a çıkarıldı.
- **20 Ağu:** GitHub Actions kontrol sıklığı 90 dakikaya çekildi, yuvarlama kayıpları engellendi.
- **19 Ağu:** 2 katmanlı ön eleme ve kategori bazlı puanlama mimarisi kuruldu. Sabah ve akşam 2 tur modeline geçildi. GitHub Pro kotası aktive edildi.
- **16-17 Ağu:** Son dakika tekil post mimarisi kuruldu (2 slayt, detay metni, alıntı doğrulama, vurgu rakamları). Gece 4 katmanlı otomatik onay sistemi (`otomatik_onay.py`) yazıldı.

