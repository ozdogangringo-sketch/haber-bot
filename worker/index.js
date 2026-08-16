/**
 * Cloudflare Worker — Telegram butonu ile GitHub Actions arasındaki köprü.
 *
 * NEDEN VAR:
 *   Telegram bir butona basıldığında bunu bir adrese POST etmek istiyor
 *   (webhook). Sürekli açık sunucumuz yok. Worker sadece istek geldiğinde
 *   çalışıyor, boştayken hiçbir şey tüketmiyor. Bedava katman günde
 *   100.000 istek; bizim ihtiyacımız günde ~5.
 *
 * AKIŞ:
 *   Telegram butonu -> bu Worker -> GitHub repository_dispatch
 *                                -> .github/workflows/yayinla.yml
 *
 * GÜVENLİK:
 *   Worker'ın adresi herkese açık. Doğrulama yapmazsak adresi bilen
 *   herkes "yayınla" komutu gönderebilir. İki katman var:
 *     1. secret_token başlığı — Telegram her istekte gönderiyor,
 *        webhook kurulurken belirlediğimiz değerle karşılaştırıyoruz.
 *     2. Beklenen komut listesi — tanımadığımız callback_data reddediliyor,
 *        yani GitHub'a keyfi event_type geçirilemiyor.
 *
 *   GITHUB_PAT fine-grained olmalı ve YALNIZCA bu repoya, yalnızca
 *   "Contents: write" iznine sahip olmalı. Worker ele geçse bile
 *   yapılabilecek en kötü şey bu repoyu etkilemek.
 */

// GitHub'a iletilecek gerçek eylemler. İş yapan komutlar.
// "durum" ve "tur" butondan değil, yazılı komuttan geliyor.
const EYLEMLER = ["yayinla", "iptal", "metin_yenile", "ertele", "durum", "tur"];
// Sayı parametresi alan eylemler: "slayt_ai:3", "slayt_sil:7" ...
const PARAMETRELI_EYLEM =
  /^(slayt_ai|slayt_foto|slayt_metin|slayt_kaynak|slayt_sil):([1-9]|10)$/;

// Menü gezinme komutları. Bunlar GitHub'a GİTMİYOR — Actions'ı uyandırmak
// 30+ saniye sürüyor ve menü açmak anında olmalı. Worker mesajın
// butonlarını doğrudan düzenliyor.
const MENU_GEZINME = /^(slayt_menu:(\d{1,2})|geri:(\d{1,2})|slayt:([1-9]|10):(\d{1,2}))$/;

function eylemMi(veri) {
  if (typeof veri !== "string" || veri.length > 64) return false;
  return EYLEMLER.includes(veri) || PARAMETRELI_EYLEM.test(veri);
}

// ---------------------------------------------------------------------
// Menüler
//
// Bu üç fonksiyon telegram_bot.py'deki karşılıklarının AYNISI olmalı.
// Menü gezinmesi Worker'da yapıldığı için buton düzeni iki yerde
// tanımlı — birini değiştirirsen diğerini de değiştir.
// Slayt sayısı callback_data'ya gömülü ("slayt_menu:10"): Worker'ın
// turda kaç slayt olduğunu başka türlü bilme yolu yok.
// ---------------------------------------------------------------------

function anaMenu(adet) {
  return {
    inline_keyboard: [
      [{ text: "✅ Yayınla", callback_data: "yayinla" }],
      [{ text: "🔄 Tüm metinleri yeniden üret", callback_data: "metin_yenile" }],
      [{ text: `🎨 Slayt düzenle (${adet} slayt)`, callback_data: `slayt_menu:${adet}` }],
      [{ text: "⏰ 1 saat ertele", callback_data: "ertele" }],
      [{ text: "❌ Bu turu atla", callback_data: "iptal" }],
    ],
  };
}

function slaytSecimMenusu(adet) {
  const satir1 = [];
  const satir2 = [];
  for (let i = 1; i <= Math.min(adet, 5); i++) {
    satir1.push({ text: String(i), callback_data: `slayt:${i}:${adet}` });
  }
  for (let i = 6; i <= adet; i++) {
    satir2.push({ text: String(i), callback_data: `slayt:${i}:${adet}` });
  }
  const tuslar = [satir1];
  if (satir2.length) tuslar.push(satir2);
  tuslar.push([{ text: "← Geri", callback_data: `geri:${adet}` }]);
  return { inline_keyboard: tuslar };
}

function slaytIslemMenusu(sira, adet) {
  return {
    inline_keyboard: [
      [{ text: `🔀 ${sira}. slayt: başka fotoğraf (bedava)`, callback_data: `slayt_foto:${sira}` }],
      [{ text: `🎨 ${sira}. slayt: AI ile üret (~$0.04)`, callback_data: `slayt_ai:${sira}` }],
      [{ text: `✏️ ${sira}. slaytın metnini yenile`, callback_data: `slayt_metin:${sira}` }],
      [{ text: `📄 ${sira}. slaytın kaynak metnini göster`, callback_data: `slayt_kaynak:${sira}` }],
      [{ text: `🗑 ${sira}. slaytı çıkar`, callback_data: `slayt_sil:${sira}` }],
      [{ text: "← Geri", callback_data: `slayt_menu:${adet}` }],
    ],
  };
}

/** Mesajın butonlarını değiştirir (metne dokunmaz). */
async function menuyuDegistir(env, sohbetId, mesajId, menu) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/editMessageReplyMarkup`;
  await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      chat_id: sohbetId,
      message_id: mesajId,
      reply_markup: menu,
    }),
  });
}

// Komut adlarının insan diline çevrisi — "işleniyor" satırında görünüyor.
const KOMUT_ADI = {
  yayinla: "Yayınlanıyor",
  iptal: "Tur atlanıyor",
  metin_yenile: "Metinler yeniden üretiliyor",
  ertele: "Erteleniyor",
  slayt_ai: "AI görsel üretiliyor",
  slayt_foto: "Başka fotoğraf aranıyor",
  slayt_metin: "Metin yeniden üretiliyor",
  slayt_kaynak: "Kaynak metni getiriliyor",
  slayt_sil: "Slayt çıkarılıyor",
};

/**
 * Butonları kaldırıp mesajın başına "işleniyor" satırı koyar.
 *
 * NEDEN: GitHub Actions'ın uyanıp işi bitirmesi 40-90 saniye sürüyor.
 * O sürede hiçbir şey değişmezse iş alındı mı belli olmuyor ve insan
 * ikinci kez basıyor — "yayınla"da bu çift post demek.
 *
 * Butonları kaldırmak çift basmayı kökten engelliyor; sonucu yazan
 * `onay_isle.py` başarısız olursa menüyü geri koyuyor.
 */
async function islemeAlindiGoster(env, sohbetId, mesajId, mesajMetni, komut) {
  const ad = KOMUT_ADI[komut.split(":")[0]] || "İşleniyor";
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/editMessageText`;
  await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      chat_id: sohbetId,
      message_id: mesajId,
      text: `⏳ ${ad}…\n\n${mesajMetni || ""}`.slice(0, 4096),
      reply_markup: { inline_keyboard: [] },
      disable_web_page_preview: true,
    }),
  });
}

/** Düz mesaj gönderir (yazılı komutlara anında cevap için). */
async function mesajGonder(env, sohbetId, metin) {
  if (!sohbetId) return;
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
  await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      chat_id: sohbetId,
      text: metin.slice(0, 4096),
      disable_web_page_preview: true,
    }),
  });
}

/** Butonun üstündeki "yükleniyor" halkasını durdurur. */
async function butonuDurdur(env, callbackId, metin) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/answerCallbackQuery`;
  await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      callback_query_id: callbackId,
      text: metin || "",
      show_alert: false,
    }),
  });
}

async function githubaIlet(env, komut, mesajId, basanKisi) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`;
  const cevap = await fetch(url, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GITHUB_PAT}`,
      accept: "application/vnd.github+json",
      "content-type": "application/json",
      // GitHub API User-Agent zorunlu kılıyor, yoksa 403 dönüyor
      "user-agent": "haber-bot-worker",
    },
    body: JSON.stringify({
      event_type: "telegram_onay",
      client_payload: { komut, mesaj_id: mesajId, basan: basanKisi },
    }),
  });
  // 204 = kabul edildi. GitHub dispatch'te gövde döndürmüyor.
  return cevap.status === 204;
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("yalnızca POST", { status: 405 });
    }

    // 1) Telegram'dan geldiğini doğrula
    const gelenGizli = request.headers.get("x-telegram-bot-api-secret-token");
    if (!env.WEBHOOK_SECRET || gelenGizli !== env.WEBHOOK_SECRET) {
      return new Response("yetkisiz", { status: 401 });
    }

    let guncelleme;
    try {
      guncelleme = await request.json();
    } catch {
      return new Response("bozuk gövde", { status: 400 });
    }

    // --- Yazılı komutlar: /durum, /tur, /yardim ---
    //
    // Buton menüsü yalnızca AÇIK bir onay mesajı varken işe yarıyor.
    // Tur kapandıysa ya da hiç kurulmadıysa elde hiçbir tutamak
    // kalmıyordu; bu komutlar o boşluğu dolduruyor.
    const msj = guncelleme.message;
    if (msj && typeof msj.text === "string") {
        const komutMetni = msj.text.trim().split(/[\s@]/)[0].toLowerCase();
        const sohbet = msj.chat ? msj.chat.id : null;

        if (komutMetni === "/yardim" || komutMetni === "/start") {
            // Yardım metni Worker'da duruyor: GitHub'ı uyandırmak 40+
            // saniye sürüyor, sabit bir metin için buna değmez.
            await mesajGonder(env, sohbet,
                "🤖 Daily Brief botu\n\n" +
                "/durum — onay bekleyen tur var mı, havuzda kaç haber var\n" +
                "/tur — yeni tur hazırla (birkaç dakika sürer)\n" +
                "/yardim — bu mesaj\n\n" +
                "Onay mesajındaki butonlarla yayınlayabilir, slaytları " +
                "değiştirebilir veya turu atlayabilirsin.");
            return new Response("ok");
        }

        if (komutMetni === "/durum" || komutMetni === "/tur") {
            const komut = komutMetni.slice(1);
            const iletildi = await githubaIlet(env, komut, null,
                msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? (komut === "tur"
                        ? "⏳ Yeni tur hazırlanıyor, birkaç dakika sürebilir…"
                        : "⏳ Durum sorgulanıyor…")
                    : "⚠️ Komut iletilemedi, tekrar dene.");
            return new Response("ok");
        }

        return new Response("ok");
    }

    const cb = guncelleme.callback_query;
    // Butona basılmayan güncellemeler (grup mesajları vb.) bizi ilgilendirmiyor.
    // 200 dönüyoruz ki Telegram tekrar tekrar denemesin.
    if (!cb) return new Response("ok");

    const komut = cb.data;
    const sohbetId = cb.message ? cb.message.chat.id : null;
    const mesajId = cb.message ? cb.message.message_id : null;

    // --- Menü gezinme: Worker anında hallediyor, GitHub'a gitmiyor ---
    const gezinme = MENU_GEZINME.exec(komut);
    if (gezinme) {
      let menu;
      if (komut.startsWith("slayt_menu:")) {
        menu = slaytSecimMenusu(Number(gezinme[2]));
      } else if (komut.startsWith("geri:")) {
        menu = anaMenu(Number(gezinme[3]));
      } else {
        // "slayt:3:10" -> 3. slayt seçildi, turda 10 slayt var
        menu = slaytIslemMenusu(Number(gezinme[4]), Number(gezinme[5]));
      }
      await menuyuDegistir(env, sohbetId, mesajId, menu);
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // --- Gerçek eylem: GitHub Actions'a iletiliyor ---
    if (!eylemMi(komut)) {
      await butonuDurdur(env, cb.id, "Tanınmayan komut");
      return new Response("ok");
    }

    const basan = cb.from
      ? `${cb.from.first_name || ""} ${cb.from.username ? "@" + cb.from.username : ""}`.trim()
      : "";

    const iletildi = await githubaIlet(env, komut, mesajId, basan);

    if (iletildi) {
      // Önce görsel geri bildirim, sonra buton halkasını durdur.
      // Sıra önemli: kullanıcı butona bastıktan sonra ilk gördüğü şey
      // mesajın değişmesi olmalı.
      await islemeAlindiGoster(
        env, sohbetId, mesajId,
        cb.message ? cb.message.text : "", komut
      );
    }

    await butonuDurdur(
      env,
      cb.id,
      iletildi ? "Alındı, işleniyor…" : "İletilemedi, tekrar dene"
    );

    return new Response("ok");
  },
};
