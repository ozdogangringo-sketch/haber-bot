// tests/worker_sesli.test.mjs — "🎙️ Sesli Yayınla" Worker davranışı (2026-09-26, postedm'den)
//
// Çalıştırma:  node --test tests/worker_sesli.test.mjs
//
// Worker'ı gerçekten çağırır; Telegram ve GitHub fetch'leri sahte. Denetlenen:
//   · menü: Yayınla'nın yanında Sesli Yayınla → fon müzikli/müziksiz → zaman menüsü
//   · GitHub'a YENİ komut gitmez: "yayinla" / "yayinla_sonra:N" + kanal listesinde ses_*
//   · planlı sesli yayında KV çalar saati yine kurulur
//   · video kanalı yoksa sesli yayın başlamaz; uydurma kip reddedilir

import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { copyFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const kok = join(dirname(fileURLToPath(import.meta.url)), "..");
const gecici = join(mkdtempSync(join(tmpdir(), "haber-worker-")), "index.mjs");
copyFileSync(join(kok, "worker/index.js"), gecici);
const worker = (await import(pathToFileURL(gecici).href)).default;

const GIZLI = "test-gizli";
let ENV;
let dispatchler = [];
let telegramlar = [];

function sahteKV() {
  const m = new Map();
  return {
    m,
    async get(k) { return m.has(k) ? m.get(k) : null; },
    async put(k, v) { m.set(k, v); },
    async delete(k) { m.delete(k); },
    async list({ prefix = "" } = {}) { return { keys: [...m.keys()].filter((k) => k.startsWith(prefix)).map((name) => ({ name })) }; },
  };
}

beforeEach(() => {
  ENV = { WEBHOOK_SECRET: GIZLI, TELEGRAM_BOT_TOKEN: "bot", GITHUB_PAT: "pat",
          GITHUB_REPO: "ozdogangringo-sketch/haber-bot", PLANLAR: sahteKV() };
  dispatchler = [];
  telegramlar = [];
  globalThis.fetch = async (url, secenek = {}) => {
    const govde = secenek.body ? JSON.parse(secenek.body) : {};
    if (String(url).endsWith("/dispatches")) {
      dispatchler.push(govde);
      return new Response(null, { status: 204 });
    }
    telegramlar.push({ yontem: String(url).split("/").pop(), govde });
    return new Response(JSON.stringify({ ok: true, result: {} }), { status: 200 });
  };
});

const kanallar = (acik) => [
  ["ig", "reels", "story", "threads"].map((k) => ({ text: `${acik.includes(k) ? "✅" : "⬜"} ${k}`, callback_data: `kanal:${k}` })),
  ["facebook", "twitter", "youtube", "tiktok"].map((k) => ({ text: `${acik.includes(k) ? "✅" : "⬜"} ${k}`, callback_data: `kanal:${k}` })),
];

const tikla = (data, klavye) => worker.fetch(new Request("https://worker.test/", {
  method: "POST",
  headers: { "x-telegram-bot-api-secret-token": GIZLI, "content-type": "application/json" },
  body: JSON.stringify({ callback_query: {
    id: "cb1", data, from: { id: 1, first_name: "Test" },
    message: { message_id: 474, text: "tur", chat: { id: -100 }, reply_markup: { inline_keyboard: klavye } },
  } }),
}), ENV);

const sonKlavye = () => telegramlar.filter((t) => t.yontem === "editMessageReplyMarkup").pop()?.govde.reply_markup.inline_keyboard;
const cbler = (k) => k.flat().map((b) => b.callback_data);
const yanitlar = () => telegramlar.filter((t) => t.yontem === "answerCallbackQuery").map((t) => t.govde.text).join(" | ");

test("ana menüde Sesli Yayınla, Yayınla'nın yanında; kanal kodları taşınır", async () => {
  await tikla("yayin_geri:10:i,y", kanallar(["ig", "youtube"]));
  const satir = sonKlavye().find((s) => s.some((b) => String(b.callback_data).startsWith("yayin_menu:")));
  assert.deepEqual(satir.map((b) => b.callback_data), ["yayin_menu:10:i,y", "ses_menu:10:i,y"]);
});

test("Sesli Yayınla → fon müzikli / müziksiz → aynı zaman menüsü", async () => {
  await tikla("ses_menu:10:i,y", kanallar(["ig", "youtube"]));
  assert.deepEqual(cbler(sonKlavye()).filter((c) => !c.startsWith("kanal:")),
    ["ses_zaman:muzikli:10:i,y", "ses_zaman:muziksiz:10:i,y", "yayin_geri:10:i,y"]);

  await tikla("ses_zaman:muziksiz:10:i,y", kanallar(["ig", "youtube"]));
  const k = cbler(sonKlavye());
  for (const cb of ["yayinla_ses:muziksiz", "yayinla_ses_sonra:muziksiz:30", "yayinla_ses_sonra:muziksiz:240", "ses_menu:10:i,y"]) {
    assert.ok(k.includes(cb), cb);
  }
  for (const b of sonKlavye().flat()) assert.ok(Buffer.byteLength(b.callback_data) <= 64, b.callback_data);
  assert.equal(dispatchler.length, 0);
});

test("sesli yayın mevcut 'yayinla' komutuyla gider, kip kanal listesinde", async () => {
  await tikla("yayinla_ses:muzikli", kanallar(["ig", "reels", "youtube"]));
  await tikla("yayinla", kanallar(["ig", "youtube"]));
  assert.deepEqual(dispatchler.map((d) => [d.event_type, d.client_payload.komut, d.client_payload.kanallar]),
    [["telegram_onay", "yayinla", "ig,reels,youtube,ses_muzikli"], ["telegram_onay", "yayinla", "ig,youtube"]]);
});

test("planlı sesli yayın: 'yayinla_sonra:N' olarak gider ve KV çalar saati kurulur", async () => {
  await tikla("yayinla_ses_sonra:muziksiz:120", kanallar(["tiktok", "threads"]));
  assert.equal(dispatchler[0].client_payload.komut, "yayinla_sonra:120");
  assert.equal(dispatchler[0].client_payload.kanallar, "threads,tiktok,ses_muziksiz");
  assert.ok(ENV.PLANLAR.m.has("plan:474"), "çalar saat kurulmalı");
  const fark = Date.parse(ENV.PLANLAR.m.get("plan:474")) - Date.now();
  assert.ok(fark > 119 * 60000 && fark <= 120 * 60000 + 5000);
});

test("video kanalı yoksa sesli yayın başlamaz", async () => {
  await tikla("yayinla_ses:muzikli", kanallar(["ig", "story", "threads", "twitter"]));
  assert.equal(dispatchler.length, 0);
  assert.match(yanitlar(), /video kanalı/);
});

test("uydurma kip ve süre reddedilir", async () => {
  for (const data of ["yayinla_ses:hack", "yayinla_ses:", "yayinla_ses_sonra:muzikli:45", "yayinla_ses_sonra:x:30",
                      "yayinla_ses_sonra:muzikli:30:30", "ses_zaman:hack:10"]) {
    await tikla(data, kanallar(["youtube"]));
  }
  assert.equal(dispatchler.length, 0);
  assert.equal(ENV.PLANLAR.m.size, 0);
});

test("tiktok_video toggle TT ile birbirini dışlar ve sesli yayın kanalı sayılır", async () => {
  const klavye = [
    [{ text: "✅ IG", callback_data: "kanal:ig" }, { text: "⬜ Reels", callback_data: "kanal:reels" }],
    [{ text: "✅ TT", callback_data: "kanal:tiktok" }, { text: "⬜ TT Video", callback_data: "kanal:tiktok_video" }],
  ];
  await tikla("kanal:tiktok_video", klavye);
  const kSon = sonKlavye();
  const ttBtn = kSon.flat().find((b) => b.callback_data === "kanal:tiktok");
  const ttVBtn = kSon.flat().find((b) => b.callback_data === "kanal:tiktok_video");
  assert.equal(ttBtn.text, "⬜ TT");
  assert.equal(ttVBtn.text, "✅ TT Video");

  // tiktok_video sesli yayın için geçerli video kanalıdır
  await tikla("yayinla_ses:muzikli", [
    [{ text: "⬜ IG", callback_data: "kanal:ig" }],
    [{ text: "✅ TT Video", callback_data: "kanal:tiktok_video" }],
  ]);
  assert.equal(dispatchler.length, 1);
  assert.equal(dispatchler[0].client_payload.komut, "yayinla");
  assert.equal(dispatchler[0].client_payload.kanallar, "tiktok_video,ses_muzikli");
});

