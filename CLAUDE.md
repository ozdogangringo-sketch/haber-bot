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
| Post biçimi | **CAROUSEL** (kaydırmalı). Kapak + 9 haber = 10 slayt. Instagram sınırı 10. |
| Slayt oranı | **4:5 dikey (1080x1350)**. Carousel'de tüm slaytlar aynı oranda olmak zorunda. |
| Post sıklığı | **Günde 1 — akşam turu** (maliyet için 2'den 1'e indirildi) |
| Akşam turu | 20:00 hazırla → 21:00, 22:00 hatırlat → 23:00 havuza dön |
| Slayt görseli | Haberde kişi/kurum varsa **Wikimedia Commons**'tan gerçek fotoğraf, yoksa gradyan. AI **sadece kapakta**. |
| ~~Reels/video~~ | Elendi: müzik API'den eklenemiyor, ayrıca ffmpeg + video barındırma gerekiyordu. |
| Onay verilmezse | **Haber ELENMEZ**, havuza döner, sonraki turda yeniden yarışır |
| Bayatlama sınırı | Yayın tarihinden **48 saat** sonra aday olmayı bırakır |
| "Atla" butonu | Sıradaki haberi önerir, tur başına **5 hak** |
| Ekstra buton | **"🔄 Metni yeniden üret"** — aynı haber için Gemini'yi tekrar çalıştırır |
| Secrets | `.env` (yerel) + GitHub Actions Secrets (uzak). Koda gömülmez. |

---

## 4. ŞU ANKİ DURUM  (güncelleme: 14 Ağustos 2026)

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

**KALAN İŞ:**
1. `generate_text.py` prompt'una `gorsel_konu` alanı ekle (haberdeki ana kişi/kurum,
   yoksa null). Commons araması bununla beslenecek. Birkaç token, maliyeti yok.
2. `make_image.py`'ye kapak slaytı üretimi (`kapak_uret`) ekle.
3. Bir turda 9 slayt üreten üst seviye fonksiyon + test scripti.
4. Atıf metni (`fetch_photo.atif_metni`) caption'ın sonuna eklenmeli — CC BY için
   hukuken şart.

### SONRAKİ: Adım 4 — imgbb + Instagram CAROUSEL yayınlama

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
├── src/
│   ├── db.py                      # ✅ + metin_kaydet(), makale_metni kolonu
│   ├── fetch_news.py              # ✅ YAZILDI + TEST EDİLDİ
│   ├── fetch_article.py           # ✅ makale gövdesi çekici (Adım 2'nin kalbi)
│   └── generate_text.py           # ✅ Gemini ile IG metni
├── scripts/
│   ├── test_1_rss.py              # ✅ Adım 1 test scripti
│   ├── test_2_makale_metni.py     # ✅ gövde çekme ölçümü (DB'ye dokunmaz)
│   ├── test_3_metin_uret.py       # ✅ Adım 2 testi (DB'yi DEĞİŞTİRİR)
│   └── test_kaynak_erisim.py      # ✅ IP engeli teşhisi (DB'ye dokunmaz)
├── assets/fonts/                  # boş — Adım 3'te font ve şablon gelecek
├── data/output/                   # boş
└── logs/                          # boş
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

## 7. Kalan adımlar

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
| G | Cloudflare hesabı | ⏳ Adım 5'te |
| H | GitHub fine-grained PAT | ⏳ Adım 5'te |

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
