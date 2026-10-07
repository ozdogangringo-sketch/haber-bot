// tests/worker_kopru.test.mjs — OzBorn Studio uygulama köprüsü (7 Eki 2026)
//
// Çalıştırma:  node --test tests/worker_kopru.test.mjs
//
// Worker'ı gerçekten çağırır; Telegram ve GitHub fetch'leri sahte, D1 yerine
// Node'un kendi SQLite'ı (gerçek SQL — sahte bir sözlük değil). Denetlenen:
//   · bot özeti yalnızca doğru imzayla kabul ediliyor, aynı özet tekrar yazılmıyor
//   · eşleştirme Telegram'da "Onayla" ile tamamlanıyor, belirteç BİR KEZ veriliyor
//   · uygulamadan gelen komut, Telegram düğmesiyle AYNI biçimde GitHub'a gidiyor
//   · Telegram'daki onay mesajı "📱 …" diye işaretleniyor (çift yayın kapısı kapanıyor)
//   · hatalı komut/kanal reddediliyor, bağlantısı kaldırılan cihaz giremiyor

import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { copyFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath, pathToFileURL } from "node:url";

const kok = join(dirname(fileURLToPath(import.meta.url)), "..");
const gecici = join(mkdtempSync(join(tmpdir(), "haber-worker-kopru-")), "index.mjs");
copyFileSync(join(kok, "worker/index.js"), gecici);
const worker = (await import(pathToFileURL(gecici).href)).default;

const GIZLI = "test-gizli";
const JETON = "123456:test-bot-jetonu";
const SOHBET = "-1001234567890";
const IMZA = createHmac("sha256", JETON).update("ozborn-kopru-v1").digest("hex");

// ---------------------------------------------------------------- sahte D1
class Ifade {
  constructor(db, sql, degerler = []) { this.db = db; this.sql = sql; this.degerler = degerler; }
  bind(...d) { return new Ifade(this.db, this.sql, d); }
  async first() { return this.db.prepare(this.sql).get(...this.degerler) ?? null; }
  async all() { return { results: this.db.prepare(this.sql).all(...this.degerler) }; }
  async run() { const r = this.db.prepare(this.sql).run(...this.degerler); return { meta: { changes: Number(r.changes) } }; }
}
function sahteD1() {
  const db = new DatabaseSync(":memory:");
  return {
    db,
    prepare: (sql) => new Ifade(db, sql),
    async batch(ifadeler) {
      db.exec("BEGIN");
      try {
        const sonuc = [];
        for (const i of ifadeler) sonuc.push(await i.run());
        db.exec("COMMIT");
        return sonuc;
      } catch (e) { db.exec("ROLLBACK"); throw e; }
    },
  };
}
function sahteKV() {
  const m = new Map();
  return { m, async get(k) { return m.get(k) ?? null; }, async put(k, v) { m.set(k, v); },
           async delete(k) { m.delete(k); }, async list() { return { keys: [...m.keys()].map((name) => ({ name })) }; } };
}

let ENV, dispatchler, telegramlar;
beforeEach(() => {
  ENV = { WEBHOOK_SECRET: GIZLI, TELEGRAM_BOT_TOKEN: JETON, GITHUB_PAT: "pat",
          GITHUB_REPO: "ozdogangringo-sketch/haber-bot", PLANLAR: sahteKV(), KOPRU: sahteD1() };
  dispatchler = [];
  telegramlar = [];
  globalThis.fetch = async (url, secenek = {}) => {
    const govde = secenek.body ? JSON.parse(secenek.body) : {};
    if (String(url).endsWith("/dispatches")) {
      dispatchler.push(govde);
      return new Response(null, { status: 204 });
    }
    const yontem = String(url).split("/").pop();
    telegramlar.push({ yontem, govde });
    return new Response(JSON.stringify({ ok: true, result: { message_id: 9001 } }), { status: 200 });
  };
});

// ---------------------------------------------------------------- yardımcılar
const istek = (yol, { yontem = "GET", govde, belirtec } = {}) => worker.fetch(new Request(`https://worker.test${yol}`, {
  method: yontem,
  headers: { "content-type": "application/json", ...(belirtec ? { authorization: `Bearer ${belirtec}` } : {}) },
  body: govde === undefined ? undefined : (typeof govde === "string" ? govde : JSON.stringify(govde)),
}), ENV);

const OZET = { protokol: 1, proje: { id: "dailybrief", ad: "DailyBrief", hesap: "@dailybrief.co" },
               onaylar: [{ mesaj_id: 5960, tur: "sondakika" }], _ic: { telegram_sohbet: SOHBET } };
const ozetGonder = (ozet = OZET, imza = IMZA) =>
  istek("/api/kopru/ozet", { yontem: "POST", govde: JSON.stringify(ozet), belirtec: imza });

const tikla = (data) => worker.fetch(new Request("https://worker.test/", {
  method: "POST",
  headers: { "content-type": "application/json", "x-telegram-bot-api-secret-token": GIZLI },
  body: JSON.stringify({ callback_query: { id: "cb1", data, from: { first_name: "Doğukan" },
    message: { message_id: 9001, chat: { id: Number(SOHBET) }, text: "istek" } } }),
}), ENV);

/** Özet + eşleştirme + Telegram onayı → cihaz belirteci. */
async function bagla(cihaz = "iPhone") {
  await ozetGonder();
  const b = await (await istek("/api/v1/eslestir", { yontem: "POST", govde: { cihaz } })).json();
  await tikla(`eslestir_onay:${b.istek}`);
  return (await (await istek(`/api/v1/eslestir/${b.istek}`)).json()).belirtec;
}

// ---------------------------------------------------------------- testler
test("bot özeti yalnızca doğru imzayla kabul ediliyor; aynı özet tekrar yazılmıyor", async () => {
  assert.equal((await ozetGonder(OZET, "yanlis")).status, 401);
  const ilk = await (await ozetGonder()).json();
  assert.deepEqual(ilk, { ok: true, degisti: true });
  const ikinci = await (await ozetGonder()).json();
  assert.deepEqual(ikinci, { ok: true, degisti: false }, "aynı özet ikinci kez yazılmamalı");
  const sohbet = ENV.KOPRU.db.prepare("SELECT deger FROM ic_ayar WHERE anahtar = 'telegram_sohbet'").get();
  assert.equal(sohbet.deger, SOHBET);
});

test("bilgi uç noktası herkese açık, proje adını veriyor", async () => {
  await ozetGonder();
  const b = await (await istek("/api/v1/bilgi")).json();
  assert.equal(b.protokol, 1);
  assert.equal(b.proje.ad, "DailyBrief");
  assert.equal(b.eslestirme, "telegram");
});

test("eşleştirme: bot özet göndermeden açılamıyor", async () => {
  const c = await istek("/api/v1/eslestir", { yontem: "POST", govde: { cihaz: "iPhone" } });
  assert.equal(c.status, 503);
  assert.equal(telegramlar.length, 0);
});

test("eşleştirme: Telegram'a kod ve Onayla/Reddet gidiyor, onaydan sonra belirteç BİR KEZ veriliyor", async () => {
  await ozetGonder();
  const cevap = await istek("/api/v1/eslestir", { yontem: "POST", govde: { cihaz: "iPhone <script>" } });
  assert.equal(cevap.status, 200);
  const b = await cevap.json();
  assert.match(b.istek, /^[0-9a-f]{32}$/);
  assert.match(b.kod, /^\d{3} \d{3}$/);

  const mesaj = telegramlar.find((t) => t.yontem === "sendMessage");
  assert.equal(String(mesaj.govde.chat_id), SOHBET);
  assert.ok(mesaj.govde.text.includes(b.kod), "kod Telegram mesajında olmalı");
  assert.ok(!mesaj.govde.text.includes("<script>"), "cihaz adı HTML olarak basılmamalı");
  const dugmeler = mesaj.govde.reply_markup.inline_keyboard.flat().map((d) => d.callback_data);
  assert.deepEqual(dugmeler, [`eslestir_onay:${b.istek}`, `eslestir_red:${b.istek}`]);
  assert.ok(dugmeler.every((d) => new TextEncoder().encode(d).length <= 64), "callback_data 64 bayt sınırında");

  assert.equal((await (await istek(`/api/v1/eslestir/${b.istek}`)).json()).durum, "bekliyor");
  await tikla(`eslestir_onay:${b.istek}`);
  const duzenleme = telegramlar.find((t) => t.yontem === "editMessageText");
  assert.ok(duzenleme.govde.text.includes("bağlandı"));
  assert.deepEqual(duzenleme.govde.reply_markup.inline_keyboard, [], "onaydan sonra düğmeler kalkmalı");

  const ilk = await (await istek(`/api/v1/eslestir/${b.istek}`)).json();
  assert.equal(ilk.durum, "onaylandi");
  assert.ok(ilk.belirtec && ilk.belirtec.length >= 40);
  const ikinci = await (await istek(`/api/v1/eslestir/${b.istek}`)).json();
  assert.equal(ikinci.durum, "teslim_edildi");
  assert.equal(ikinci.belirtec, undefined, "belirteç ikinci kez verilmemeli");

  const kayit = ENV.KOPRU.db.prepare("SELECT belirtec_ozeti FROM cihazlar").get();
  assert.notEqual(kayit.belirtec_ozeti, ilk.belirtec, "belirtecin kendisi saklanmamalı, yalnızca özeti");
});

test("eşleştirme: reddedilen istek belirteç vermiyor; saatte en fazla 5 istek", async () => {
  await ozetGonder();
  const b = await (await istek("/api/v1/eslestir", { yontem: "POST", govde: { cihaz: "x" } })).json();
  await tikla(`eslestir_red:${b.istek}`);
  const d = await (await istek(`/api/v1/eslestir/${b.istek}`)).json();
  assert.equal(d.durum, "reddedildi");
  assert.equal(d.belirtec, undefined);
  for (let i = 0; i < 4; i++) {
    assert.equal((await istek("/api/v1/eslestir", { yontem: "POST", govde: {} })).status, 200);
  }
  assert.equal((await istek("/api/v1/eslestir", { yontem: "POST", govde: {} })).status, 429);
});

test("durum: belirteçsiz giriş yok; özetin iç alanı uygulamaya verilmiyor", async () => {
  assert.equal((await istek("/api/v1/durum")).status, 401);
  const belirtec = await bagla();
  const d = await (await istek("/api/v1/durum", { belirtec })).json();
  assert.equal(d.ozet.proje.ad, "DailyBrief");
  assert.equal(d.ozet._ic, undefined, "Telegram sohbet kimliği uygulamaya sızmamalı");
  assert.ok(d.alinma && d.son_temas && d.sunucu_zamani);
});

test("komut: Telegram düğmesiyle AYNI biçimde GitHub'a gidiyor ve onay mesajı işaretleniyor", async () => {
  const belirtec = await bagla("iPhone");
  telegramlar = [];
  const c = await istek("/api/v1/komut", { yontem: "POST", belirtec,
    govde: { komut: "yayinla", mesaj_id: 5960, kanallar: ["ig", "story"], ses: null } });
  assert.equal(c.status, 200);
  assert.equal(dispatchler.length, 1);
  assert.equal(dispatchler[0].event_type, "telegram_onay");
  assert.deepEqual(
    { komut: dispatchler[0].client_payload.komut, mesaj_id: dispatchler[0].client_payload.mesaj_id,
      kanallar: dispatchler[0].client_payload.kanallar, basan: dispatchler[0].client_payload.basan },
    { komut: "yayinla", mesaj_id: 5960, kanallar: "ig,story", basan: "📱 iPhone" });

  const isaret = telegramlar.find((t) => t.yontem === "editMessageReplyMarkup");
  assert.ok(isaret, "Telegram'daki onay mesajı işaretlenmeli");
  assert.equal(isaret.govde.message_id, 5960);
  const metin = isaret.govde.reply_markup.inline_keyboard.flat().map((d) => d.text).join(" ");
  assert.ok(metin.includes("📱"), "işaret uygulamadan geldiğini söylemeli");
  assert.ok(!isaret.govde.reply_markup.inline_keyboard.flat().some((d) => d.callback_data.startsWith("yayin")),
    "işaretli mesajda yayın düğmesi kalmamalı (çift yayın)");
});

test("komut: sesli planlı yayın ses kipini taşıyor ve çalar saati kuruyor", async () => {
  const belirtec = await bagla();
  const c = await istek("/api/v1/komut", { yontem: "POST", belirtec,
    govde: { komut: "yayinla_sonra:60", mesaj_id: 5960, kanallar: ["reels", "youtube"], ses: "muzikli" } });
  assert.equal(c.status, 200);
  assert.equal(dispatchler[0].client_payload.kanallar, "reels,youtube,ses_muzikli");
  assert.ok(ENV.PLANLAR.m.has("plan:5960"), "planlı yayında KV çalar saati kurulmalı");
});

test("komut: hatalı istekler reddediliyor ve GitHub'a hiçbir şey gitmiyor", async () => {
  const belirtec = await bagla();
  const dene = (govde) => istek("/api/v1/komut", { yontem: "POST", belirtec, govde });
  const durumlar = await Promise.all([
    dene({ komut: "rm -rf", mesaj_id: 5960 }),
    dene({ komut: "slayt_menu:5", mesaj_id: 5960 }),                       // menü gezinmesi GitHub'a gitmez
    dene({ komut: "yayinla", mesaj_id: 5960, kanallar: [] }),
    dene({ komut: "yayinla", mesaj_id: 5960 }),
    dene({ komut: "yayinla", mesaj_id: 5960, kanallar: ["ig", "reels"] }),
    dene({ komut: "yayinla", mesaj_id: 5960, kanallar: ["tiktok", "tiktok_video"] }),
    dene({ komut: "yayinla", mesaj_id: 5960, kanallar: ["ig"], ses: "muzikli" }),
    dene({ komut: "yayinla", mesaj_id: 5960, kanallar: ["instagram"] }),
    dene({ komut: "yayinla", mesaj_id: "5960; drop", kanallar: ["ig"] }),
    dene({ komut: "iptal", mesaj_id: 5960, ses: "muzikli" }),
  ]);
  assert.deepEqual(durumlar.map((d) => d.status), Array(10).fill(400));
  assert.equal(dispatchler.length, 0);
});

test("komut: mesajsız komutlar (öneri hazırlama, ayar) mesaj kimliği olmadan gidiyor", async () => {
  const belirtec = await bagla();
  telegramlar = [];
  assert.equal((await istek("/api/v1/komut", { yontem: "POST", belirtec,
    govde: { komut: "hazirla:371959,372039", mesaj_id: null } })).status, 200);
  assert.equal((await istek("/api/v1/komut", { yontem: "POST", belirtec,
    govde: { komut: "ayarsec:genel.son_dakika_puan_esigi:9" } })).status, 200);
  assert.deepEqual(dispatchler.map((d) => [d.client_payload.komut, d.client_payload.mesaj_id]),
    [["hazirla:371959,372039", null], ["ayarsec:genel.son_dakika_puan_esigi:9", null]]);
  assert.equal(telegramlar.filter((t) => t.yontem === "editMessageReplyMarkup").length, 0,
    "mesajsız komutta işaretlenecek onay mesajı yok");
});

test("cihaz bağlantısı kaldırılınca o belirteçle giriş kapanıyor", async () => {
  const belirtec = await bagla();
  const liste = await (await istek("/api/v1/cihazlar", { belirtec })).json();
  assert.equal(liste.cihazlar.length, 1);
  assert.equal(liste.cihazlar[0].bu_cihaz, true);
  const sil = await (await istek(`/api/v1/cihazlar/${liste.cihazlar[0].id}`, { yontem: "DELETE", belirtec })).json();
  assert.equal(sil.ok, true);
  assert.equal((await istek("/api/v1/durum", { belirtec })).status, 401);
});

test("Telegram webhook'u köprüden etkilenmiyor: secret'sız istek yine 401", async () => {
  const c = await worker.fetch(new Request("https://worker.test/", { method: "POST", body: "{}" }), ENV);
  assert.equal(c.status, 401);
  const tarayici = await istek("/api/v1/bilgi", { yontem: "OPTIONS" });
  assert.equal(tarayici.status, 204);
  assert.equal(tarayici.headers.get("access-control-allow-origin"), "*");
});
