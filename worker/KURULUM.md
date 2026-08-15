# Cloudflare Worker kurulumu

Telegram'daki butonları çalışır hâle getiren adım. Yaklaşık 15 dakika.

Buradaki her şey **bedava katmanda** kalıyor: Cloudflare Worker günde
100.000 istek veriyor, bizim ihtiyacımız günde ~5.

---

## 1. Cloudflare hesabı aç

[dash.cloudflare.com/sign-up](https://dash.cloudflare.com/sign-up)

E-posta + parola yeterli. **Kredi kartı istemiyor.** Alan adı almana da
gerek yok — Worker'lar `*.workers.dev` altında ücretsiz adres alıyor.

---

## 2. GitHub PAT üret

Worker'ın GitHub'a "yayınla" komutu gönderebilmesi için bir anahtar lazım.

[github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new)

Şu ayarlarla:

| Alan | Değer |
|---|---|
| Token name | `haber-bot-worker` |
| Expiration | 1 yıl (takvimine not al, yenilemen gerekecek) |
| Repository access | **Only select repositories** → `haber-bot` |
| Permissions → Contents | **Read and write** |

**Neden bu kadar dar:** Worker'ın adresi internette açık. Ele geçirilse
bile bu anahtarla yapılabilecek tek şey `haber-bot` reposunu etkilemek.
Hesabının geri kalanına, diğer repolarına dokunamaz. `Contents: write`
`repository_dispatch` için gereken en düşük izin.

Üretilen anahtarı bir yere kopyala — sayfadan çıkınca bir daha göremezsin.

---

## 3. Webhook parolası üret

Telegram'dan gelen isteklerin gerçekten Telegram'dan geldiğini
doğrulamak için rastgele bir parola. Terminalde:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Çıkan değeri kopyala. Buna `WEBHOOK_SECRET` diyeceğiz.

**Neden gerekli:** Worker'ın adresi herkese açık. Bu doğrulama olmasa,
adresi bilen biri Worker'a "yayınla" isteği gönderip hesabına post
attırabilirdi.

---

## 4. Worker'ı yayına al

Terminalde, proje klasöründe:

```bash
cd /Users/macbook/Dogukan/instabot/worker
npx wrangler login
```

Tarayıcı açılıp Cloudflare girişi isteyecek, onayla.

Sonra secret'ları ekle — her komut sana değeri soracak, yapıştırıp
Enter'a bas (ekranda görünmez, normal):

```bash
npx wrangler secret put TELEGRAM_BOT_TOKEN
```

```bash
npx wrangler secret put GITHUB_PAT
```

```bash
npx wrangler secret put WEBHOOK_SECRET
```

Sonra yayına al:

```bash
npx wrangler deploy
```

Çıktının sonunda şuna benzer bir adres verecek:

```
https://haber-bot-onay.<kullanıcı-adın>.workers.dev
```

**Bu adresi kopyala.** Bir sonraki adımda lazım.

---

## 5. Telegram webhook'unu kur

Proje kökünde:

```bash
python scripts/webhook_kur.py https://haber-bot-onay.XXX.workers.dev
```

(Adresi kendi Worker adresinle değiştir. Script `WEBHOOK_SECRET`'ı
soracak — 3. adımda ürettiğin değeri gir.)

---

## ⚠️ Webhook kurulduktan sonra

`getUpdates` **çalışmaz olur** — Telegram ikisine aynı anda izin
vermiyor. Yani `scripts/telegram_chat_id_bul.py` boş dönecek. Bu bir
arıza değil, beklenen davranış. Chat ID zaten `.env`'de kayıtlı.

Webhook'u kaldırmak istersen:

```bash
python scripts/webhook_kur.py --kaldir
```
