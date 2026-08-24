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
const EYLEMLER = ["yayinla", "iptal", "metin_yenile", "ertele", "durum", "tur",
                  "ayar", "tamamla", "arsiv", "oneri_gec", "tura_birak", "cope_at",
                  "plan_iptal", "havuz_guncelle", "havuzdan_ekle", "android_muzikli",
                  // Yönetim & Acil durum kontrolleri
                  "yonetim", "yonetim_panel", "devam_et", "saglik_testi",
                  "kota_raporu", "tur_temizle",
                  // Tur başlık önizlemesi (iki aşamalı tur akışı)
                  "tur_onayla", "tur_yeniden"];
// Sayı parametresi alan eylemler: "slayt_ai:3", "slayt_sil:7", "slayt_elle:3", "slayt_yukari:3" ...
const PARAMETRELI_EYLEM =
  /^(slayt_ai|slayt_foto|slayt_metin|slayt_kaynak|slayt_elle|slayt_sil|slayt_yukari|slayt_asagi|slayt_basa|sansur_kaldir|sansur_uygula|metin_uzat|metin_kisalt|cope_at_tekil):([1-9]|10)$/;

// Botu duraklatma (1s, 6s, 12s, 24s)
const DURAKLAT = /^duraklat:(1|6|12|24)$/;

// Görsel önizleme düğmeleri: "gorsel_kabul:{slayt}:{turMesajId}".
// ⚠️ Tur id'si komutta — önizleme AYRI bir mesajda duruyor ve
// cb.message.message_id turu göstermiyor.
const GORSEL_ONAY = /^(gorsel_kabul|gorsel_yeni):([1-9]|10):\d{1,12}$/;

// Zamanlanmış yayın: "yayinla_sonra:60" -> 60 dakika sonra yayınla.
// ⚠️ DEĞERLER 30'UN KATLARI ve serbest sayı DEĞİL. Zamanı gelen turu
// son dakika kontrolü yayınlıyor, o cron 30 dakikada bir çalışıyor;
// "15 dk" kabul etseydik gerçekte 15-45 dakika arası yayınlanır ve
// düğme yalan söylerdi.
const YAYINLA_SONRA = /^yayinla_sonra:(30|60|120|180|240)$/;

// Turdaki bir haberi başkasıyla değiştirme.
//   "haber_degistir:3"      -> 3. slayt için 2 alternatif iste
//   "haber_sec:3:16380"     -> 3. slayta 16380 numaralı haberi koy
// id yalnızca rakam; slayt numarası 1-10 (Instagram carousel sınırı).
const HABER_DEGISTIR = /^haber_degistir:([1-9]|10)$/;
// ⚠️ Tur mesaj id'si komutun İÇİNDE ("haber_sec:5:16380:474"). Bu düğme
// ayrı bir mesajda duruyor; cb.message.message_id turu göstermiyor.
// haber_sec:{eskiHaberId}:{yeniHaberId}:{turMesajId}
// ⚠️ İlk alan SLAYT NUMARASI DEĞİL haber id'si — numara tur
// yeniden sıralanınca kayıyor ve yanlış slaydı hedefliyor.
const HABER_SEC = /^haber_sec:\d{1,8}:\d{1,8}:\d{1,12}$/;
const HABER_VAZGEC = /^haber_vazgec:\d{1,12}$/;

// Yayın doğrulama düğmeleri. Tur mesaj id'si komutun İÇİNDE — bu
// düğmeler yayın sonucu / hata mesajında duruyor ve o mesajların
// message_id'si turunkinden farklı.
//   yayin_kontrol:{turMesajId}   -> Instagram'a sorup durumu bildirir
//   yeniden_yayinla:{turMesajId} -> önce kontrol, yayınlanmamışsa yayınlar
const YAYIN_KONTROL = /^yayin_kontrol:\d{1,12}$/;
const YENIDEN_YAYINLA = /^yeniden_yayinla:\d{1,12}$/;

// Tekil post ÖNERİSİ: "hazirla:1482" — haber id'si komuta gömülü.
// İki aşamalı akışın ikinci adımı: kontrol job'ı yalnızca başlıkları
// puanlayıp öneriyor, tam metin ve görsel ancak bu butona basılınca
// üretiliyor. id sınırlı biçimde doğrulanıyor (yalnızca rakam).
const HAZIRLA = /^hazirla:\d{1,8}(,\d{1,8}){0,7}$/;

// Tekil post önerisinde ÇOKLU SEÇİM.
// "sec:1482" bir başlığı işaretler/işareti kaldırır — bu GitHub'a
// GİTMİYOR, Worker mesajın butonlarını doğrudan düzenliyor. Actions'ı
// her seçim için uyandırmak 3 haber = 3 ayrı job (~5 dk) demekti.
// "hazirla_secilenler" işaretli olanların hepsini tek dispatch ile
// gönderiyor; id'ler buton metinlerinden okunuyor.
const SEC = /^sec:\d{1,8}$/;
const SECILENLERI_HAZIRLA = "hazirla_secilenler";

// Menü gezinme komutları. Bunlar GitHub'a GİTMİYOR — Actions'ı uyandırmak
// 30+ saniye sürüyor ve menü açmak anında olmalı. Worker mesajın
// butonlarını doğrudan düzenliyor.
const MENU_GEZINME =
  /^(slayt_menu:(\d{1,2})|geri:(\d{1,2})|slayt:([1-9]|10):(\d{1,2})|yayin_menu:(\d{1,2})|yayin_geri:(\d{1,2}))$/;

// Yayından kaldırma. Tur id'si komuta GÖMÜLÜ ("kaldir:144") çünkü bu
// düğme yayın sonucu mesajında duruyor ve o mesajın kendi message_id'si
// turunkinden farklı — cb.message.message_id kullanılırsa yanlış turu
// hedefler.
const KALDIR = /^kaldir:(\d{1,12})$/;

// Ayar düğmeleri: "ayar:genel.gece_otomatik_yayin". Yol beyaz listeye
// karşı GitHub tarafında da doğrulanıyor; buradaki desen yalnızca
// biçim kontrolü.
// Ayar alt menüsü Worker'da açılıyor (anında). Seçenekler düğmenin
// içinde taşınıyor ("ayarmenu:genel.gece_otomatik_yayin:true-false"),
// böylece seçenek listesi yalnızca src/ayar.py'de duruyor — menüyü
// üçüncü bir yerde tekrarlamıyoruz.
const AYAR_MENU = /^ayarmenu:([a-z_]+\.[a-z_]+):([a-z0-9\-]{1,40})$/;
const AYAR_SEC  = /^ayarsec:[a-z_]+\.[a-z_]+:[a-z0-9]{1,10}$/;

// Hata bildirimindeki eylem düğmeleri (src/hata_bildir.py üretiyor).
// "tur_tekrar" ve "tur_metinsiz" GitHub'da tur kurdurur; "ayrinti"
// GitHub'a HİÇ gitmez — Worker ham hata metnini repodan okuyup anında
// cevaplıyor, Actions dakikası harcamıyoruz.
const HATA_EYLEM = /^hata:(tur_tekrar|tur_metinsiz|sondakika_tekrar)$/;
// Son dakika kontrolü kendi workflow'unda çalışıyor; tur eylemlerinden
// AYRI bir event'e gitmeli, yoksa "son dakika hatası" düğmesi akşam
// turunu tetikliyor (20 Ağu 2026'da tam olarak bu oldu).
const SONDAKIKA_EYLEM = "hata:sondakika_tekrar";
const HATA_AYRINTI = "hata:ayrinti";

function eylemMi(veri) {
  if (typeof veri !== "string" || veri.length > 64) return false;
  return EYLEMLER.includes(veri) || PARAMETRELI_EYLEM.test(veri)
    || YAYINLA_SONRA.test(veri)
    || HABER_DEGISTIR.test(veri) || HABER_SEC.test(veri)
    || HABER_VAZGEC.test(veri)
    || YAYIN_KONTROL.test(veri) || YENIDEN_YAYINLA.test(veri)
    || GORSEL_ONAY.test(veri)
    || KALDIR.test(veri) || AYAR_SEC.test(veri) || HATA_EYLEM.test(veri)
    || HAZIRLA.test(veri) || veri === SECILENLERI_HAZIRLA
    || DURAKLAT.test(veri);
}

// Ayar alt menüsü: seçenekler düğmeden okunuyor, geçerli değer
// bilinmediği için işaret KONULMUYOR — onu GitHub tarafı, paneli
// tazelerken gösteriyor.
function ayarAltMenu(yol, kodlar) {
  const goster = (k) => (k === "true" ? "AÇIK" : k === "false" ? "KAPALI" : k);
  const satir = kodlar.split("-").map((k) => ({
    text: goster(k),
    callback_data: `ayarsec:${yol}:${k}`,
  }));
  return { inline_keyboard: [satir, [{ text: "← Ayarlara dön", callback_data: "ayar" }]] };
}

// Kanal seçimi toggle komutu ("kanal:ig", "kanal:story", "kanal:threads", "kanal:facebook", "kanal:twitter")
const KANAL_TOGGLE = /^kanal:(ig|story|threads|facebook|twitter)$/;

function seciliKanallariCikar(klavye) {
  if (!klavye || !klavye.length) return null;
  const kanalButonlari = klavye.flat().filter((b) => String(b.callback_data || "").startsWith("kanal:"));
  if (kanalButonlari.length === 0) return null;
  return kanalButonlari
    .filter((b) => String(b.text || "").startsWith("✅"))
    .map((b) => b.callback_data.slice(6)); // "kanal:ig" -> "ig"
}

function kanalButonlariSatiri(kanallar) {
  const varMi = (k) => {
    if (Array.isArray(kanallar)) return kanallar.includes(k);
    if (kanallar && typeof kanallar === "object") return Boolean(kanallar[k]);
    return true;
  };
  return [
    { text: `${varMi('ig') ? '✅' : '⬜'} IG`, callback_data: "kanal:ig" },
    { text: `${varMi('story') ? '✅' : '⬜'} Story`, callback_data: "kanal:story" },
    { text: `${varMi('threads') ? '✅' : '⬜'} Threads`, callback_data: "kanal:threads" },
    { text: `${varMi('facebook') ? '✅' : '⬜'} FB`, callback_data: "kanal:facebook" },
    { text: `${varMi('twitter') ? '✅' : '⬜'} X`, callback_data: "kanal:twitter" },
  ];
}

// ---------------------------------------------------------------------
// Menüler
//
// Bu fonksiyonlar telegram_bot.py'deki karşılıklarının AYNISI olmalı.
// Menü gezinmesi Worker'da yapıldığı için buton düzeni iki yerde
// tanımlı — birini değiştirirsen diğerini de değiştir.
// Slayt sayısı callback_data'ya gömülü ("slayt_menu:10"): Worker'ın
// turda kaç slayt olduğunu başka türlü bilme yolu yok.
// ---------------------------------------------------------------------

function anaMenu(adet, kanallar) {
  return {
    inline_keyboard: [
      kanalButonlariSatiri(kanallar),
      [{ text: "✅ Yayınla", callback_data: `yayin_menu:${adet}` }],
      [{ text: "🔄 Tüm metinleri yeniden üret", callback_data: "metin_yenile" }],
      [{ text: `🎨 Slayt düzenle (${adet} slayt)`, callback_data: `slayt_menu:${adet}` }],
      [{ text: "⏰ 1 saat ertele", callback_data: "ertele" }],
      // ⚠️ Menü İKİ YERDE tanımlı (telegram_bot.py ve burada);
      // birini değiştirirken diğerini de değiştir.
      [{ text: "📋 Tekil atma, 10'lu tura bırak", callback_data: "tura_birak" }],
      [{ text: "❌ Bu turu atla (Havuza döner)", callback_data: "iptal" },
       { text: "🗑️ Çöpe At (Havuza dönmesin)", callback_data: "cope_at" }],
    ],
  };
}

// ⚠️ src/telegram_bot.py -> yayin_zamani_menusu() ile BİREBİR AYNI olmalı.
// İki sütun: dar telefon ekranında düğme metinleri kırpılmasın.
function yayinZamaniMenusu(adet, kanallar) {
  return {
    inline_keyboard: [
      kanalButonlariSatiri(kanallar),
      [{ text: "▶️ Şimdi", callback_data: "yayinla" },
       { text: "30 dk", callback_data: "yayinla_sonra:30" }],
      [{ text: "1 saat", callback_data: "yayinla_sonra:60" },
       { text: "2 saat", callback_data: "yayinla_sonra:120" }],
      [{ text: "3 saat", callback_data: "yayinla_sonra:180" },
       { text: "4 saat", callback_data: "yayinla_sonra:240" }],
      [{ text: "← Geri", callback_data: `yayin_geri:${adet}` }],
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
  if (adet < 10) {
    tuslar.push([{ text: `➕ Havuzdan Haber Ekle (${adet}/10)`, callback_data: "havuzdan_ekle" }]);
  }
  tuslar.push([{ text: "← Geri", callback_data: `geri:${adet}` }]);
  return { inline_keyboard: tuslar };
}

function slaytIslemMenusu(sira, adet) {
  const tuslar = [];
  if (adet > 1) {
    if (sira > 1) {
      tuslar.push([{ text: `🔝 ${sira}. slaytı EN BAŞA al (Manşet)`, callback_data: `slayt_basa:${sira}` }]);
    }
    const siraSatiri = [];
    if (sira > 1) {
      siraSatiri.push({ text: "⬆️ 1 Yukarı Taşı", callback_data: `slayt_yukari:${sira}` });
    }
    if (sira < adet) {
      siraSatiri.push({ text: "⬇️ 1 Aşağı Taşı", callback_data: `slayt_asagi:${sira}` });
    }
    if (siraSatiri.length) {
      tuslar.push(siraSatiri);
    }
  }

  tuslar.push(
    [{ text: `🔀 ${sira}. slayt: başka fotoğraf (bedava)`, callback_data: `slayt_foto:${sira}` }],
    [{ text: `🎨 ${sira}. slayt: AI ile üret (~$0.04)`, callback_data: `slayt_ai:${sira}` }],
    [{ text: `✏️ ${sira}. slaytın metnini yenile`, callback_data: `slayt_metin:${sira}` }],
    [{ text: `✍️ ${sira}. slaytın başlığını elle yaz`, callback_data: `slayt_elle:${sira}` }],
    [{ text: `🧹 ${sira}. slayt: Sansürü Kaldır (* sil)`, callback_data: `sansur_kaldir:${sira}` },
     { text: `🛡️ ${sira}. slayt: Sansürle`, callback_data: `sansur_uygula:${sira}` }],
    [{ text: `➕ ${sira}. slayt: Metni Uzat`, callback_data: `metin_uzat:${sira}` },
     { text: `➖ ${sira}. slayt: Metni Kısalt`, callback_data: `metin_kisalt:${sira}` }],
    [{ text: `📄 ${sira}. slaytın kaynak metnini göster`, callback_data: `slayt_kaynak:${sira}` }],
    [{ text: `🔄 ${sira}. slaytın HABERİNİ değiştir`, callback_data: `haber_degistir:${sira}` }],
    [{ text: `🗑 ${sira}. slaytı çıkar`, callback_data: `slayt_sil:${sira}` },
     { text: `🗑️ Haberi Çöpe At`, callback_data: `cope_at_tekil:${sira}` }],
    [{ text: "← Geri", callback_data: `slayt_menu:${adet}` }],
  );
  return { inline_keyboard: tuslar };
}

function duraklatmaSecenekleriMenusu() {
  return {
    inline_keyboard: [
      [{ text: "⏸️ 1 Saat Duraklat", callback_data: "duraklat:1" },
       { text: "⏸️ 6 Saat Duraklat", callback_data: "duraklat:6" }],
      [{ text: "⏸️ 12 Saat Duraklat", callback_data: "duraklat:12" },
       { text: "⏸️ 24 Saat Duraklat", callback_data: "duraklat:24" }],
      [{ text: "← Yönetim Paneline Dön", callback_data: "yonetim_panel" }],
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
  slayt_elle: "Başlık düzenleniyor",
  slayt_yukari: "Slayt yukarı taşınıyor",
  slayt_asagi: "Slayt aşağı taşınıyor",
  slayt_basa: "Slayt başa alınıyor",
  havuzdan_ekle: "Havuzdan haber ekleniyor",
  slayt_kaynak: "Kaynak metni getiriliyor",
  slayt_sil: "Slayt çıkarılıyor",
  metin_duzenle: "Yeni metin uygulanıyor",
  hata: "Tur yeniden kuruluyor",
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
/** Düz mesaj gönderir (yazılı komutlara anında cevap için). */
async function mesajGonder(env, sohbetId, metin, parseMode = null) {
  if (!sohbetId) return;
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
  const body = {
    chat_id: sohbetId,
    text: metin.slice(0, 4096),
    disable_web_page_preview: true,
  };
  if (parseMode) body.parse_mode = parseMode;
  await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
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

// Ham hata metnini repodan okur. GitHub'a dispatch ATMIYOR — yalnızca
// dosya okuyor, yani Actions dakikası harcanmıyor ve cevap anında geliyor.
async function hamHataOku(env) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/contents/data/son_hata.txt`;
  const cevap = await fetch(url, {
    headers: {
      authorization: `Bearer ${env.GITHUB_PAT}`,
      accept: "application/vnd.github+json",
      "user-agent": "haber-bot-worker",
    },
  });
  if (!cevap.ok) return null;
  const veri = await cevap.json();
  try {
    return decodeURIComponent(escape(atob((veri.content || "").replace(/\n/g, ""))));
  } catch (e) {
    return null;
  }
}

async function githubaIlet(env, komut, mesajId, basanKisi, kanallar, metin) {
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
      // Tur kurma ayrı bir workflow (hazirla.yml); onay akışıyla aynı
      // event'i paylaşırsa yayinla.yml onu da işlemeye kalkıyor.
      event_type: komut === SONDAKIKA_EYLEM
        ? "son_dakika_calistir"
        : (HATA_EYLEM.test(komut) ? "tur_hazirla" : "telegram_onay"),
      client_payload: {
        komut,
        mesaj_id: mesajId,
        basan: basanKisi,
        metinsiz: komut === "hata:tur_metinsiz",
        kanallar: kanallar || "",
        metin: metin || "",
      },
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
        const sohbet = msj.chat ? msj.chat.id : null;

        // --- Yanıtlanan Mesajlar (Reply): Doğrudan başlık/metin düzenleme ---
        if (msj.reply_to_message) {
            const replyId = msj.reply_to_message.message_id;
            const replyMetin = msj.text.trim();
            const basan = msj.from ? msj.from.first_name || "" : "";

            if (!replyMetin.startsWith("/")) {
                const iletildi = await githubaIlet(env, "metin_duzenle", replyId, basan, "", replyMetin);
                await mesajGonder(env, sohbet,
                    iletildi
                        ? "✍️ Yeni metin işleniyor, başlık ve slayt güncelleniyor…"
                        : "⚠️ İstek GitHub'a iletilemedi.");
                return new Response("ok");
            }
        }

        const komutMetni = msj.text.trim().split(/[\s@]/)[0].toLowerCase();

        // /guncelle — RSS'i hemen tarar. Kullanıcı duyduğu bir haberi
        // arayıp bulamadığında kontrolün çalışmasını beklemek zorunda
        // kalıyordu (21 Ağu 2026, "Netanyahu tutuklama emri").
        if (komutMetni === "/guncelle" || komutMetni === "/havuz") {
            const iletildi = await githubaIlet(
                env, "havuz_guncelle", null,
                msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? "🔄 Kaynaklar taranıyor, sonucu birazdan yazacağım…"
                    : "⚠️ İstek GitHub'a iletilemedi.");
            return new Response("ok");
        }

        if (komutMetni === "/yardim" || komutMetni === "/start") {
            // Yardım metni Worker'da duruyor: GitHub'ı uyandırmak 40+
            // saniye sürüyor, sabit bir metin için buna değmez.
            await mesajGonder(env, sohbet,
                "🤖 Daily Brief Bot Komutları\n\n" +
                "📋 ÖZEL HABER ÜRETİMİ (Havuz Dışı):\n" +
                "• /link <url> — Herhangi bir haber linkinden tam post üretir\n" +
                "• /arastir <konu> — Konuyu webde araştırıp doğrulanmış haber yapar\n" +
                "• /ozel <metin> — Kendi bülten veya duyuru metninden post üretir\n\n" +
                "⚙️ YÖNETİM & TUR KONTROLÜ:\n" +
                "• /tur — Sabah/Akşam turunu hemen hazırla\n" +
                "• /durum — Canlı kota, havuz ve bekleyen tur durumu\n" +
                "• /yonetim — Botu duraklatma, API sağlık testleri\n" +
                "• /haber <kelime> — Havuzdaki taze haberlerde ara\n" +
                "• /guncelle — RSS kaynaklarını hemen tara\n" +
                "• /ayar — Gece otomatik yayın ve kategori eşikleri\n" +
                "• /tamamla — Yarım kalan Threads zincirini tamamla\n" +
                "• /yardim — Bu yardım menüsü\n\n" +
                "Onay mesajındaki butonlarla yayınlayabilir, slaytları " +
                "değiştirebilir veya turu atlayabilirsin.");
            return new Response("ok");
        }

        // /link <URL> — Verilen web linkinden özel haber üretir
        if (komutMetni === "/link") {
            const url = msj.text.trim().slice(komutMetni.length).trim();
            if (!url.startsWith("http")) {
                await mesajGonder(env, sohbet,
                    "⚠️ Lütfen geçerli bir haber linki yaz:\n/link https://bloomberg.com/...");
                return new Response("ok");
            }
            const iletildi = await githubaIlet(env, `link:${url}`,
                null, msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? `🌐 Link taranıyor ve özel haber hazırlanıyor…\n${url.slice(0, 70)}`
                    : "⚠️ Komut iletilemedi, tekrar dene.");
            return new Response("ok");
        }

        // /arastir <KONU> — Konuyu webde araştırıp doğrulanmış haber üretir
        if (komutMetni === "/arastir" || komutMetni === "/ara") {
            const konu = msj.text.trim().slice(komutMetni.length).trim();
            if (konu.length < 4) {
                await mesajGonder(env, sohbet,
                    "⚠️ Araştırmak istediğin konuyu yaz:\n/arastir Nvidia yeni kuantum yapay zeka çipini duyurdu");
                return new Response("ok");
            }
            const iletildi = await githubaIlet(env, `arastir:${konu.slice(0, 300)}`,
                null, msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? `🔍 "${konu.slice(0, 70)}" konusu canlı araştırılıyor ve haberleştiriliyor…`
                    : "⚠️ Komut iletilemedi, tekrar dene.");
            return new Response("ok");
        }

        // /ozel <METİN> — Kullanıcının bülten/duyuru metninden post üretir
        if (komutMetni === "/ozel" || komutMetni === "/bulten" || komutMetni === "/duyuru") {
            const metin = msj.text.trim().slice(komutMetni.length).trim();
            if (metin.length < 15) {
                await mesajGonder(env, sohbet,
                    "⚠️ Post yapmak istediğin bülten veya duyuru metnini yaz:\n/ozel Daily Briefing mobil uygulamamız App Store ve Google Play'de yayına girdi...");
                return new Response("ok");
            }
            const iletildi = await githubaIlet(env, `ozel:${metin.slice(0, 1500)}`,
                null, msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? "✍️ Özel bülten metni işleniyor, slaytlar hazırlanıyor…"
                    : "⚠️ Komut iletilemedi, tekrar dene.");
            return new Response("ok");
        }

        // /haber <konu> — havuzda arama yapıp öneri sunar.
        if (komutMetni === "/haber") {
            const konu = msj.text.trim().slice(komutMetni.length).trim();
            if (konu.length < 3) {
                await mesajGonder(env, sohbet,
                    "Aramak istediğin konuyu yaz:\n/haber galatasaray transfer");
                return new Response("ok");
            }
            const iletildi = await githubaIlet(env, `ara:${konu.slice(0, 120)}`,
                null, msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? `🔎 "${konu.slice(0, 60)}" havuzda aranıyor…`
                    : "⚠️ Komut iletilemedi, tekrar dene.");
            return new Response("ok");
        }

        if (["/durum", "/tur", "/sondakika", "/haftalik", "/pazar", "/video", "/reels", "/ayar", "/tamamla", "/arsiv", "/yonetim", "/panel"].includes(komutMetni)) {
            let komut = komutMetni.slice(1);
            if (komut === "panel") komut = "yonetim";
            if (komut === "pazar") komut = "haftalik";
            if (komut === "reels") komut = "video";
            const iletildi = await githubaIlet(env, komut, null,
                msj.from ? msj.from.first_name || "" : "");
            await mesajGonder(env, sohbet,
                iletildi
                    ? (komut === "tur"
                        ? "⏳ Yeni tur hazırlanıyor, birkaç dakika sürebilir…"
                        : komut === "sondakika"
                          ? "⚡️ Son dakika sıcak haber taraması başlatılıyor…"
                          : komut === "haftalik"
                            ? "🗓️ Haftalık Pazar özeti hazırlanıyor, son 7 günün manşetleri taranıyor…"
                            : komut === "video"
                              ? "🎬 Son turun 9:16 MP4 Reels videosu render ediliyor…"
                              : komut === "ayar"
                                ? "⏳ Ayarlar getiriliyor…"
                                : komut === "yonetim"
                                  ? "⏳ Yönetim paneli getiriliyor…"
                                  : komut === "tamamla"
                                    ? "⏳ Threads zinciri kontrol ediliyor…"
                                    : komut === "arsiv"
                                      ? "⏳ Arşiv paylaşımı başlatılıyor, uzun sürebilir…"
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

    // --- Slayt başlığını elle yazma kılavuzu ---
    if (komut.startsWith("slayt_elle:")) {
      const sira = komut.split(":")[1];
      await mesajGonder(env, sohbetId,
          `✍️ <b>${sira}. slayt</b> için yeni başlığı bu mesaja <b>YANITLAYARAK (Reply)</b> yazabilirsin.\n\n` +
          `<b>Örnek formatlar:</b>\n` +
          `• <code>${sira}: Yeni Başlık Metni</code>\n` +
          `• <code>${sira}: Yeni Başlık | Yeni Alt Açıklama</code>\n\n` +
          `<i>(Başlık onayı aşamasındaysa liste, görsel onayı aşamasındaysa slayt görseli yenilenir.)</i>`,
          "HTML"
      );
      await butonuDurdur(env, cb.id, "Yanıtını bekliyorum...");
      return new Response("ok");
    }

    // --- Duraklatma alt menüsü: Worker anında açıyor ---
    if (komut === "duraklat_menu") {
      await menuyuDegistir(env, sohbetId, mesajId, duraklatmaSecenekleriMenusu());
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // --- Ayar alt menüsü: Worker anında açıyor ---
    const ayarMenu = AYAR_MENU.exec(komut);
    if (ayarMenu) {
      await menuyuDegistir(env, sohbetId, mesajId,
                           ayarAltMenu(ayarMenu[1], ayarMenu[2]));
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // --- Öneri çoklu seçimi: Worker anında hallediyor ---
    if (SEC.test(komut)) {
      const klavye = cb.message?.reply_markup?.inline_keyboard || [];
      let secili = 0;
      const yeni = klavye.map((satir) =>
        satir.map((btn) => {
          const kopya = { ...btn };
          if (kopya.callback_data === komut) {
            // İşareti aç/kapat
            kopya.text = kopya.text.startsWith("✅")
              ? kopya.text.slice(1)
              : "✅" + kopya.text;
          }
          if (String(kopya.callback_data || "").startsWith("sec:")
              && kopya.text.startsWith("✅")) {
            secili += 1;
          }
          return kopya;
        })
      );
      // "Hazırla (N)" sayacını güncelle
      for (const satir of yeni) {
        for (const btn of satir) {
          if (btn.callback_data === SECILENLERI_HAZIRLA) {
            btn.text = `▶️ Hazırla (${secili})`;
          }
        }
      }
      await menuyuDegistir(env, sohbetId, mesajId, { inline_keyboard: yeni });
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // Seçilenleri topla ve TEK dispatch ile gönder
    if (komut === SECILENLERI_HAZIRLA) {
      const klavye = cb.message?.reply_markup?.inline_keyboard || [];
      const idler = klavye
        .flat()
        .filter((b) => String(b.callback_data || "").startsWith("sec:")
                       && String(b.text || "").startsWith("✅"))
        .map((b) => b.callback_data.slice(4));
      if (idler.length === 0) {
        await butonuDurdur(env, cb.id, "Önce en az bir haber seç");
        return new Response("ok");
      }
      // Komut GitHub'a "hazirla:12,34,56" biçiminde gidiyor.
      // callback_data 64 bayt sınırına takılmıyor çünkü id'ler
      // butonun kendisinde değil, buton METİNLERİNDEN okunuyor.
      // `basan` aşağıda tanımlanıyor ama bu blok ondan önce
      // çalışıyor; burada kendimiz hesaplıyoruz.
      const secen = cb.from
        ? `${cb.from.first_name || ""} ${cb.from.username ? "@" + cb.from.username : ""}`.trim()
        : "";
      const kararlar = `hazirla:${idler.join(",")}`;
      await islemeAlindiGoster(env, sohbetId, mesajId,
        `${idler.length} haber seçildi, sırayla üretiliyor.`, kararlar);
      await githubaIlet(env, kararlar, mesajId, secen);
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // --- Kanal seçimi toggle: Worker anında hallediyor ---
    if (KANAL_TOGGLE.test(komut)) {
      const klavye = cb.message?.reply_markup?.inline_keyboard || [];
      const yeni = klavye.map((satir) =>
        satir.map((btn) => {
          const kopya = { ...btn };
          if (kopya.callback_data === komut) {
            kopya.text = kopya.text.startsWith("✅")
              ? "⬜" + kopya.text.slice(1).trim()
              : "✅" + kopya.text.slice(1).trim();
          }
          return kopya;
        })
      );
      await menuyuDegistir(env, sohbetId, mesajId, { inline_keyboard: yeni });
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // --- Menü gezinme: Worker anında hallediyor, GitHub'a gitmiyor ---
    const gezinme = MENU_GEZINME.exec(komut);
    if (gezinme) {
      let menu;
      const seciliKanallar = seciliKanallariCikar(cb.message?.reply_markup?.inline_keyboard);
      if (komut.startsWith("slayt_menu:")) {
        menu = slaytSecimMenusu(Number(gezinme[2]));
      } else if (komut.startsWith("geri:")) {
        menu = anaMenu(Number(gezinme[3]), seciliKanallar);
      } else if (komut.startsWith("yayin_menu:")) {
        menu = yayinZamaniMenusu(Number(gezinme[6]), seciliKanallar);
      } else if (komut.startsWith("yayin_geri:")) {
        menu = anaMenu(Number(gezinme[7]), seciliKanallar);
      } else {
        // "slayt:3:10" -> 3. slayt seçildi, turda 10 slayt var
        menu = slaytIslemMenusu(Number(gezinme[4]), Number(gezinme[5]));
      }
      await menuyuDegistir(env, sohbetId, mesajId, menu);
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // --- Ham hata metni: Worker repodan okuyup anında gösteriyor ---
    if (komut === HATA_AYRINTI) {
      const ham = await hamHataOku(env);
      await mesajGonder(env, sohbetId,
        ham ? `🔍 HAM HATA METNİ\n\n${ham.slice(0, 3500)}`
            : "Kayıtlı ham hata metni bulunamadı.");
      await butonuDurdur(env, cb.id, "");
      return new Response("ok");
    }

    // --- Gerçek eylem: GitHub Actions'a iletiliyor ---
    if (!eylemMi(komut)) {
      await butonuDurdur(env, cb.id, "Tanınmayan komut");
      return new Response("ok");
    }

    const seciliKanallar = seciliKanallariCikar(cb.message?.reply_markup?.inline_keyboard);
    // Sıfır kanal seçimi koruması (Senaryo A)
    if (seciliKanallar !== null && seciliKanallar.length === 0 && (komut === "yayinla" || komut.startsWith("yayinla_sonra:"))) {
      await butonuDurdur(env, cb.id, "⚠️ En az bir yayın kanalı seçmelisin!");
      return new Response("ok");
    }

    const basan = cb.from
      ? `${cb.from.first_name || ""} ${cb.from.username ? "@" + cb.from.username : ""}`.trim()
      : "";

    // "kaldir:144" -> komut "kaldir", hedef tur 144. Mesajın kendi
    // id'si burada işe yaramıyor (bkz. KALDIR açıklaması).
    let gonderilecek = komut;
    let hedefMesajId = mesajId;
    const kaldirEslesme = KALDIR.exec(komut);
    if (kaldirEslesme) {
      gonderilecek = "kaldir";
      hedefMesajId = Number(kaldirEslesme[1]);
    }

    const kanallarStr = seciliKanallar ? seciliKanallar.join(",") : "";
    const iletildi = await githubaIlet(env, gonderilecek, hedefMesajId, basan, kanallarStr);

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
