// Python'un urettigi her callback_data Worker tarafindan KARSILANIYOR mu?
const fs = require('fs');
let k = fs.readFileSync(process.argv[2], 'utf8').replace(/export default[\s\S]*$/, '');
const w = new Function(k +
  ';return {eylemMi, MENU_GEZINME, SEC, KANAL_TOGGLE, SECILENLERI_HAZIRLA, HATA_AYRINTI, SESLI_YAYIN};')();
const karsilanir = (v) =>
  w.eylemMi(v) || w.MENU_GEZINME.test(v) || w.SEC.test(v) || w.KANAL_TOGGLE.test(v)
  || w.SESLI_YAYIN.test(v)  // yayinla/yayinla_sonra'ya çevrilip iletilir
  || v === "duraklat_menu" || v === w.SECILENLERI_HAZIRLA || v === w.HATA_AYRINTI
  || v.startsWith("slayt_elle:") || v.startsWith("makro_yardim:")
  || v === "isleniyor";
const out = {};
for (const a of JSON.parse(process.argv[3])) out[a] = karsilanir(a);
console.log(JSON.stringify(out));
