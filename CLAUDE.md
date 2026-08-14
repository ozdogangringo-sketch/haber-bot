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
| Onay kanalı | **Telegram bot**, inline butonlarla |
| Onay tetikleme | **Cloudflare Worker** → `repository_dispatch` → anında yayın |
| Görsel hosting | **imgbb** (Instagram public URL zorunlu kılıyor) |
| Haber teması | Öncelik **Türkiye gündemi**; dünya haberi sadece önem puanı ≥8 ise |
| Post sıklığı | Günde 2 — sabah + akşam, her turda **tek** post |
| Sabah turu | 09:00 hazırla → 10:00, 11:00 hatırlat → 12:00 havuza dön |
| Akşam turu | 20:00 hazırla → 21:00, 22:00 hatırlat → 23:00 havuza dön |
| Onay verilmezse | **Haber ELENMEZ**, havuza döner, sonraki turda yeniden yarışır |
| Bayatlama sınırı | Yayın tarihinden **48 saat** sonra aday olmayı bırakır |
| "Atla" butonu | Sıradaki haberi önerir, tur başına **5 hak** |
| Ekstra buton | **"🔄 Metni yeniden üret"** — aynı haber için Gemini'yi tekrar çalıştırır |
| Secrets | `.env` (yerel) + GitHub Actions Secrets (uzak). Koda gömülmez. |

---

## 4. ŞU ANKİ DURUM

**Adım 1 kodu yazıldı ama kullanıcı henüz çalıştırmadı.**

İlk yapılacak: kullanıcıdan `python scripts/test_1_rss.py` çıktısını iste
(iki kez çalıştırması gerekiyor — ikincisinde `eklenen: 0` olmalı).

**Kritik:** Çıktıda hangi RSS kaynaklarının hata verdiğine bak. Bazı Türk haber
siteleri Cloudflare arkasında ve **GitHub Actions'ın veri merkezi IP'sinden 403
dönebilir** (kullanıcının ev IP'sinden çalışsa bile). Bu doğrulanmadan Adım 2'ye
geçme. Elenen kaynak olursa `config.yaml`'de `aktif: false` yap veya alternatif bul.

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
├── src/
│   ├── db.py                      # ✅ YAZILDI + TEST EDİLDİ
│   └── fetch_news.py              # ✅ YAZILDI + TEST EDİLDİ
├── scripts/
│   └── test_1_rss.py              # ✅ Adım 1 test scripti
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

### Adım 2 — Gemini ile metin (`src/generate_text.py`)
Girdi: `durum='yeni'` haberler. Çıktı: `ig_baslik`, `ig_caption`, `ig_hashtag`,
`onem_puani` (1-10) → `durum='metin_hazir'`.

- Model: `gemini-2.0-flash` veya güncel ücretsiz kota modeli (kullanmadan önce
  ai.google.dev'den doğrula, model adları değişiyor).
- **JSON çıktı zorla** (`response_mime_type: application/json` + şema).
- Prompt Türkçe olmalı; İngilizce dünya haberini Türkçeleştirmeli.
- Caption 2-3 cümle, hashtag 5-8 adet.
- `onem_puani` seçim algoritmasının kalbi — prompt'ta net kriter ver
  (ulusal etki, aciliyet, ilgi çekicilik).
- Taraflı/spekülatif başlık üretmemesi için prompt'ta açık talimat.

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

| # | Ne | Durum |
|---|---|---|
| A | Instagram Business + Facebook Page + Meta App + token | ⏳ bilinmiyor |
| B | Gemini API key | ⏳ bilinmiyor |
| C | Telegram bot token + chat ID | ⏳ bilinmiyor |
| D | imgbb API key | ⏳ bilinmiyor |
| E | GitHub private repo | ⏳ bilinmiyor |
| F | 1080x1080 görsel şablon | ❌ henüz yok |
| G | Cloudflare hesabı | ⏳ Adım 5'te |
| H | GitHub fine-grained PAT | ⏳ Adım 5'te |

Adım 1 hiçbirini gerektirmiyor. Başlarken durumu kullanıcıya sor.

---

## 10. Bilinen riskler

- Cloudflare korumalı haber siteleri GitHub runner IP'sine 403 dönebilir → Adım 1'de ölç
- Instagram token 60 gün → otomatik yenileme şart
- Gemini yanlış/taraflı başlık üretebilir → **onay adımı asla kaldırılmasın**
- Cron gecikmesi 5-30 dk, nadiren atlanır
- 09:59'da onay + 10:00 hatırlatma job'ı → gereksiz hatırlatma (nadir, zararsız)
- GitHub ToS teknik olarak repo-dışı iş yükünü hoş karşılamıyor (bu ölçekte pratikte sorun değil)
- Haber görseli kullanılmıyor, kendi şablon + kaynak adı → telif riski yok
