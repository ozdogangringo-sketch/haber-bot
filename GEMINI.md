# GEMINI.md — Daily Brief Instagram & Sosyal Medya Haber Botu

Bu dosya projeyi devralan yapay zeka oturumu ve geliştiriciler içindir. Tüm mimari kararlar, yapılan geliştirmeler, çalışma kuralları ve sistemin güncel durumu bu rehberde toplanmıştır.

---

## 1. Kullanıcı Profili ve Değişmez Temel İlkeler

- **Kullanıcı:** Doğukan. Türkçe konuşur, kararlı, yüksek kaliteli ve net çıktılar bekler.
- **Alan Adı (Domain):** `ozbornstudio.com` alan adı projeye aittir. Gelecekte ihtiyaç halinde alt alan adları (örn: `bot.ozbornstudio.com`, `api.ozbornstudio.com`, `media.ozbornstudio.com`, `brief.ozbornstudio.com`) Cloudflare DNS üzerinden webhook, CDN, görsel barındırma veya web kontrol paneli için yapılandırılabilir.
- **KATI VE DEĞİŞMEZ KURAL (ZERO 4:5 & 100% NATIVE 1080x1920 9:16):**
  * **4:5 (1080x1350) görsel üretimi TAMAMEN KALDIRILMIŞTIR!**
  * Hiçbir slayt 4:5 çizilmez; tüm slaytlar (Tekil Haber 1. Kapak, 2. Detay, 3. Detay/Etki, Canlı Piyasa Bülteni 1. Isı Haritası, 2. BİST Tablosu, Özel Dosya Haberleri vb.) **doğrudan 1080x1920 piksel tuvalde %100 SAF NATIVE FULL-BLEED infografik ve slayt olarak sıfırdan çizilir**.
  * Instagram (Akış & Story), Facebook (Albüm & Story), Threads, X, YouTube Shorts ve TikTok paylaşımları doğrudan bu 1080x1920 native dikey slaytlar üzerinden yürütülür.
  * **ASLA VE ASLA** yapay çerçeve veya blur kenarlık eklenmeyecektir.
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
  * Gün boyu 1'er saat aralıklarla Telegram'a **en taze 5 haber önerisi** düşer; seçilen haber varsayılan olarak **3 ferah sayfa (1 Kapak + 2 Detay/Analiz Slaytı - 1080x1920)** olarak üretilir.
  * Hafta içi sabah (TR 10:08) ve akşam (TR 18:20) fiks **Canlı Borsa & Piyasa Bülteni** (%100 Native 1080x1920 Story ve Akış) otomatik paylaşılır.

---

## 2. Sistem Mimarisi & Kesintisiz 3 Katmanlı Tetikleme

```
[Cloudflare Edge Cron Triggers] (10:08 TR Açılış, 18:20 TR Kapanış, Saatlik Akış)
       │ (0 Gecikme, 99.99% Uptime — worker/index.js)
       ▼
[GitHub Actions repository_dispatch] ──► [piyasa-bulteni.yml / son-dakika.yml]
       │
[son_dakika.py Otomatik Telafi Ağı] ──► (Bülten gecikirse saat başı otomatik tamamlar)
       │
[fetch_news.py] ──> SQLite (data/haber.db)
       │
       ▼
[Tekil 3 Slayt %100 Native 1080x1920 Üretimi] (slaytlar.py / make_image.py / piyasa_kart.py / piyasa_tablo.py)
       │ (1 Kapak + 2 Detay Slaytı + 144px 3D Logo + Renkli Paragraf Çentikleri)
       ▼
[Telegram Onay & Yönetim Grubu] (telegram_bot.py ──> Daily Brief Grubu)
       │ (İnteraktif butonlar: 1️⃣..5️⃣ Seç, ✅ Yayınla, 🚀 Canlı Bülteni Şimdi Yayınla...)
       ▼
[onay_isle.py Router]
       │
       ├─► Instagram Graph API (1080x1920 Carousel & 1080x1920 Story)
       ├─► Facebook Graph API (1080x1920 Albüm & 1080x1920 Story)
       ├─► Threads API (6 Halkalı Bilgi Zinciri)
       ├─► X (Twitter) API v2 (1080x1920 Fotoğraflı Tweet)
       ├─► YouTube Data API v3 (9:16 Shorts Video)
       └─► TikTok Content Posting API (9:16 Dikey Video)
```

---

## 3. Yapılan Başlıca Geliştirmeler & Modüller

### A. 4:5 Destekli 1080x1920 Canlı Piyasa Bülteni (`src/piyasa_kart.py` & `src/piyasa_tablo.py`)
- **4:5 Destekli 1080x1920 (9:16):** 1. Slayt (Piyasa Isı Haritası) ve 2. Slayt (30 Varlık Piyasa Karnesi) 1080x1920 tuvalde, merkezi 1080x1350 (4:5) içerik güvenli bölgesine yerleştirilir.
  * Instagram Carousel Akışında (4:5) tüm tablolar ve rozetler sıfır taşmayla ve dikey bozulma olmadan görünür.
  * Story ve Dikey formatlarda (9:16) üst ve alt alanlar sinematik degrade ve derinlik gölgesiyle tam ekranı doldurur.
- **Tasarım:** *Derin Okyanus Petrolü* zemin (`#04181C`), *Siber Turkuaz* parıltılı rozet (`#06B6D4`), canlı Gram Altın/Gümüş TL çevrimi ve 30 günlük Yahoo Finance sparkline trend çizgileri.
- **Kesin Saat Pencereleri:** Açılış bülteni penceresi **09:55 - 11:30 TR**, Kapanış bülteni penceresi **18:15 - 20:00 TR** aralığındadır. Bu saatler dışında sistem otomatik yayınlamayı reddeder.

### B. Cloudflare Edge Cron & Çok Katmanlı Güvenlik Mimarisi
- **Cloudflare Edge Cron:** `worker/wrangler.toml` ve `worker/index.js` üzerinden `8 7 * * 1-5` (10:08 TR) ve `20 15 * * 1-5` (18:20 TR) cron'ları doğrudan Cloudflare Edge ağında çalışarak GitHub REST API `repository_dispatch` ile piyasa bültenini ve saatlik haber akışını sıfır gecikmeyle tetikler. GitHub Actions'ın kendi gecikmeli `schedule:` cron'ları tamamen kaldırılmıştır.
- **Saatlik `son_dakika` Emniyet Ağı:** Hafta içi sabah 10:15 - 11:30 arasında bülten gecikirse, saat başı çalışan `son_dakika.py` motoru durumu fark edip piyasa bültenini anında yayına alır.
- **Telegram `/piyasa` ve `/ekonomi` Butonları:** Telegram'dan anlık olarak "🚀 Canlı Bülteni Şimdi Yayınla" ve "🖼️ 1080x1920 Slaytları Önizle" butonlarıyla bülten tetiklenebilir.

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

### F. Kristal Netlik ve Taranmış Belge/Tablo Filtresi (`src/gorsel_kalite.py`)
- **Taranmış Belge / PDF / İlan Formu Engeli:** Doygunluk $\le 15.0$ ve Parlaklık $\ge 175.0$ olan ham tablo, PDF ekran görüntüsü veya beyaz kağıt taramaları otomatik elenerek gerçek editoryal haber fotoğraflarına geçilir.
- **Dikey Kırpma Piksel Yoğunluğu Denetimi:** 16:9 yatay görsellerin 9:16'ya kırpılırken piksellenmesi engellenir. Dikey kırpma ölçeği $< 0.88x$ olan veya büyütme (upscale) gerektiren fotoğraflar elenir.
- **Laplacian Netlik Varyansı:** Yapay büyütülmüş, düşük bitrate'li TV ekran yakalamaları ve bulanık fotoğraflar elenir (Asgari netlik varyansı $\ge 90.0$).
- **Kristal Keskinleştirme (`kristal_netlestir`):** Seçilen kaliteli fotoğraflar UnsharpMask ile pürüzsüz ve kristal netlikte editoryal stile kavuşturulur.

### G. Hızlı Video ve TikTok / Shorts / Reels İşleme Motoru (`src/video.py` & `src/tiktok.py`)
- **Direct Publish & Doğrudan Profil Yayını:** TikTok OAuth token'ı `video.publish,video.upload,user.info.basic` izinleriyle güncellendi; videolar Inbox/Taslak kuyruğuna düşmeden doğrudan profile otomatik yayınlanır.
- **Stereo AAC Ses İzi Entegrasyonu:** Sessiz videolarda sosyal medya algoritmalarının (TikTok, Shorts, Reels) ikincil transcode kuyruğuna düşüp bildirimleri geciktirmesini önlemek için videolara otomatik standart stereo AAC ses kanalı (`44.1 kHz, 128 kbps`) gömülür.
- **Sabit 2 Saniyelik GOP Keyframe (`-g 60 -keyint_min 30 -sc_threshold 0`):** TikTok'un dağıtık sunucularının videoyu paralel parçalara (chunks) bölerek saniyeler içinde işlemesini sağlar.
- **`+faststart` Moov Atomu:** MP4 konteynerinin indeks verisini dosyanın başına taşıyarak anında yayın ve indirme başlatır.
- **Canlı Yayın Durumu Sorgulama (`yayin_durumu_sorgula`):** TikTok Content Posting API üzerinden `SEND_TO_USER_INBOX` durumunu canlı takip eder.

### H. Fiyat Trend Grafiği (Sparkline) & Mükerrer Veri Kartı Filtreleri (`src/sparkline.py` & `src/dogrula.py`)
- **Piyasa/Fiyatlama Bağlam Şartı (`src/sparkline.py`):** Yaşam, dünya, spor, teknoloji vb. haberlerde metinde para birimi ("4.500 Euro maaş", "100 milyon dolar yatırım") geçse dahi 30 günlük borsa/döviz trend grafiği kesinlikle basılmaz. Grafik SADECE `ekonomi`/`borsa`/`finans` kategorisinde ve doğrudan kur/hisse/emtia fiyat hareketi varsa üretilir.
- **Mükerrer Rozet Engeli (`dogrula.veri_karti_baslikta_var_mi`):** Başlıkta veya spotta zaten yer alan skorlar (örn: "6-2 yendi"), maaşlar ("4.500 Euro") veya üye sayıları ("600 bin") sağ üstteki rozete mükerrer olarak basılmaz (`veri_karti = None`). Sadece başlıkta olmayan arka plan karşılaştırmaları gösterilir.
- **Hata Kataloğu & Kapsam Güvenliği (`src/hata_bildir.py`):** `UnboundLocalError` ve `NameError` gibi Python çalıştırma hataları resmi hata kataloğuna eklendi; Telegram üzerinden anında teşhis ve tek tıkla yeniden deneme butonları sağlandı.

---

## 4. Görsel Seçim Standartları ve İyileştirme Yol Haritası

### 4 Katmanlı Akıllı Görsel Hiyerarşisi:
1. **1. Katman — Web HD / 4K Basın Fotoğrafları Motoru (`src/fetch_web_image.py`):** Doğrudan haber ajanslarının (AA, Reuters, AP, AFP) ve yayıncıların 16:9 HD (`1200x675`, `1280x720`, `1920x1080`) editoryal basın fotoğrafları çekilir. `atlanacak` parametresiyle çoklu arama sorgularındaki adaylar tek havuzda birleştirilip dedupe edilir; her "Başka Fotoğraf Bul" çağrısında olayın sıradaki gerçek basın karesi getirilir.
2. **2. Katman — Akıllı Makale Basın & Ürün Görseli Çekici (`src/fetch_article.py`):** `og:image`, `twitter:image`, JSON-LD `NewsArticle` ve makale gövdesindeki orijinal lansman fotoğrafları taranır ve `gorsel_kalite` denetiminden geçirilir.
3. **3. Katman — Wikimedia Commons & Pexels HD Stok (`src/fetch_photo.py`, `src/fetch_stock.py`):** Kişi portreleri ($\ge 1200\text{px}$) ve 4K dikey temsili stoklar (yalnızca webde gerçek olay/ürün fotoğrafı bulunamazsa fallback).
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
