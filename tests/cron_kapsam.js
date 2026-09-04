const fs = require('fs');
let k = fs.readFileSync('worker/index.js', 'utf8').replace(/export default/, 'const W =');
const W = new Function(k + ';return W;')();

function sahteKV(kayitlar) {
  const veri = new Map(Object.entries(kayitlar));
  return {
    list: async ({ prefix }) => ({ keys: [...veri.keys()].filter(x => x.startsWith(prefix)).map(name => ({ name })) }),
    get: async (n) => veri.get(n) ?? null,
    delete: async (n) => { veri.delete(n); },
    put: async (n, v) => { veri.set(n, v); },
    _kalan: () => [...veri.keys()],
  };
}

async function dene(ad, kayitlar) {
  const cagrilar = [];
  global.fetch = async (u, o) => { cagrilar.push(JSON.parse(o.body).event_type); return { ok: true }; };
  const kv = sahteKV(kayitlar);
  const env = { GITHUB_PAT: "x", GITHUB_REPO: "a/b", PLANLAR: kv };
  await W.scheduled({ cron: "*/10 * * * *" }, env, {});
  console.log(`  ${ad.padEnd(34)} dispatch=${cagrilar.length ? cagrilar.join(",") : "YOK"}   KV'de kalan=${kv._kalan().length}`);
}

(async () => {
  const gecmis = new Date(Date.now() - 5 * 60000).toISOString();
  const gelecek = new Date(Date.now() + 90 * 60000).toISOString();
  await dene("KV boş", {});
  await dene("plan 90 dk sonra", { "plan:700": gelecek });
  await dene("plan 5 dk önce (zamanı geldi)", { "plan:700": gecmis });
  await dene("biri geçmiş biri gelecek", { "plan:700": gecmis, "plan:701": gelecek });
  // KV patlarsa
  const bozuk = { list: async () => { throw new Error("KV down"); } };
  const cagrilar = [];
  global.fetch = async () => { cagrilar.push(1); return { ok: true }; };
  await W.scheduled({ cron: "*/10 * * * *" }, { GITHUB_PAT: "x", GITHUB_REPO: "a/b", PLANLAR: bozuk }, {});
  console.log(`  ${"KV patladı".padEnd(34)} dispatch=${cagrilar.length ? "VAR ⛔" : "YOK ✓ (sessiz)"}`);
  // Diger cron'lar bozulmadi mi
  const c2 = [];
  global.fetch = async (u, o) => { c2.push(JSON.parse(o.body).event_type); return { ok: true }; };
  await W.scheduled({ cron: "12 5-20 * * *" }, { GITHUB_PAT: "x", GITHUB_REPO: "a/b" }, {});
  console.log(`  ${"eski saatlik cron".padEnd(34)} dispatch=${c2.join(",") || "YOK ⛔"}`);
})();
