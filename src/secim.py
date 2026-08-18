"""
secim.py — Turda hangi haberlerin yayınlanacağına karar verir.

ÇÖZDÜĞÜ SORUN — tavuk-yumurta:
    Seçim skoru `onem_puani`ye dayanıyor, ama o puanı Gemini üretiyor.
    Yani "hangisi önemli" sorusunu cevaplamak için önce hepsine metin
    ürettirmek gerekiyor. Havuzda 200+ haber var; hepsine metin üretmek
    hem kotayı hem 200 makale indirmeyi göze almak demek — turun süresi
    dakikalardan saate çıkar.

    Çözüm iki aşamalı:
      1. ÖN ELEME (bedava, LLM yok): tazelik + kaynak ağırlığı + kategori
         ile havuzu ~2 kat adaya indir.
      2. ASIL SEÇİM: yalnızca o adaylara metin üretilir, sonra gerçek
         skorla en iyi N tanesi alınır.

    Ön eleme neden güvenli: elediğimiz haberler ya bayat ya düşük ağırlıklı
    kaynaktan. İkisi de zaten asıl skorda dibe düşecek şeyler.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Aday havuzu, yayınlanacak sayının kaç katı olsun.
# 2.5 seçildi: elenen haber yerine yedek kalsın ama boşuna metin
# üretilmesin. 10 slayt için ~25 adaya metin üretiliyor.
ADAY_KATSAYISI = 2.5


def _yas_saat(haber) -> float:
    """Haberin yayınlanmasından bu yana geçen saat."""
    ham = haber["yayin_tarihi"]
    if not ham:
        return 999.0
    try:
        t = datetime.fromisoformat(ham)
    except ValueError:
        return 999.0
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


def _kategori_payi(ayarlar: dict) -> int:
    """Ön elemede her kategoriye ayrılan garantili aday sayısı."""
    return (ayarlar.get("secim", {}) or {}).get("on_eleme_kategori_payi", 3)


def on_eleme(con, ayarlar: dict, kac: int | None = None) -> list:
    """
    Metin üretilecek adayları seçer. LLM ÇAĞIRMAZ, bedavadır.

    Yalnızca elimizde zaten olan bilgiyi kullanıyor: yaş, kaynak ağırlığı,
    kategori. Bayatlama sınırını geçenler hiç aday olmuyor.
    """
    g = ayarlar["gorsel"]
    sinir_saat = ayarlar["genel"]["yayin_yasi_siniri_saat"]
    kac = kac or int(g["slayt_sayisi"] * ADAY_KATSAYISI)

    havuz = list(con.execute("SELECT * FROM haberler WHERE durum = 'yeni'"))

    puanli = []
    for haber in havuz:
        yas = _yas_saat(haber)
        if yas > sinir_saat:
            continue
        # Ön skor: taze ve ağırlıklı kaynak öne çıksın. onem_puani burada
        # YOK — henüz üretilmedi, asıl seçimde devreye girecek.
        puan = (haber["agirlik"] or 1) * 10 - yas
        if haber["kategori"] == "dunya":
            # Türkiye gündemi öncelikli; dünya haberi asıl skorda
            # onem_puani >= 8 ile geri dönebilir.
            puan -= 15
        puanli.append((puan, haber))

    puanli.sort(key=lambda p: p[0], reverse=True)

    # ⚠️ KATEGORİ PAYI OLMADAN ÖN ELEME TEK KAYNAĞA KİLİTLENİYOR.
    #
    # Ölçüldü (18 Ağu 2026, 1236 haberlik havuz): düz skor sıralamasıyla
    # 25 adayın 24'ü TRT Haber'den, 1'i BBC Türkçe'den geliyordu ve
    # kategori dağılımı %100 "turkiye" idi. Sebep basit — ön skor
    # `ağırlık × 10` ile başlıyor, ağırlığı 10 olan kaynak tek başına
    # 120 taze haber veriyor ve listeyi tamamen dolduruyor.
    #
    # Sonuç: eklenen bilim, spor, ekonomi, kültür, teknoloji ve yaşam
    # kaynakları metin üretimine HİÇ giremiyor, dolayısıyla asıl seçimde
    # de görünmüyordu. Çeşitlilik kaynakta değil, tam burada ölüyordu.
    #
    # Çözüm: her kategoriye garantili küçük bir pay ayrılıyor, kalan
    # kontenjan yine düz skorla dolduruluyor. Türkiye gündemi baskın
    # kalmaya devam ediyor (havuzun %75'i o), ama diğer kategoriler de
    # en azından temsil ediliyor.
    kategori_payi = _kategori_payi(ayarlar)
    secilen, alinan = [], set()
    if kategori_payi:
        kategoriler = {h["kategori"] for _, h in puanli}
        for kat in kategoriler:
            for puan, haber in puanli:
                if haber["kategori"] != kat or haber["id"] in alinan:
                    continue
                secilen.append(haber)
                alinan.add(haber["id"])
                if sum(1 for h in secilen if h["kategori"] == kat) >= kategori_payi:
                    break

    for _, haber in puanli:
        if len(secilen) >= kac:
            break
        if haber["id"] not in alinan:
            secilen.append(haber)
            alinan.add(haber["id"])

    secilen = secilen[:kac]
    log.info("ön eleme: %d havuzdan %d aday (%d kategori)",
             len(havuz), len(secilen), len({h["kategori"] for h in secilen}))
    return secilen


def skor(haber, ayarlar: dict) -> float:
    """
    Asıl seçim skoru. Metin üretildikten SONRA çalışır.

    Formül CLAUDE.md'de kararlaştırıldı:
        onem_puani * 10 + agirlik - yaş_saat
        - 15  eğer kategori == 'dunya' ve onem_puani < 8
    """
    onem = haber["onem_puani"] or 0
    deger = onem * 10 + (haber["agirlik"] or 1) - _yas_saat(haber)
    if haber["kategori"] == "dunya" and onem < 8:
        deger -= 15
    return deger


# Konu karşılaştırmasında sayılmayacak kelimeler. Bunlar her başlıkta
# geçiyor ve iki haberi yapay olarak "benzer" gösteriyor.
ETKISIZ_KELIMELER = {
    "için", "ile", "olarak", "sonra", "önce", "üzere", "kadar", "daha",
    "göre", "karşı", "yeni", "büyük", "sonrası", "ilgili", "hakkında",
    "arasında", "üzerine", "birlikte", "dedi", "açıkladı", "oldu",
    "edildi", "verdi", "aldı", "yaptı", "bulundu", "geldi", "başladı",
}


def _anahtar_kelimeler(baslik: str) -> set[str]:
    """
    Başlığın konusunu temsil eden kelimeler.

    Türkçe ek almış hâlleri ("İsrail'in", "Gazze'de") aynı köke indirmek
    için kesme işaretinden sonrası atılıyor; yoksa aynı olayın haberleri
    farklı kelime gibi görünüyor.
    """
    kelimeler = set()
    for ham in (baslik or "").lower().replace("'", " ").split():
        temiz = "".join(k for k in ham if k.isalnum())
        if len(temiz) >= 4 and temiz not in ETKISIZ_KELIMELER:
            kelimeler.add(temiz)
    return kelimeler


def cesitlendir(adaylar: list, adet: int, ayarlar: dict) -> list:
    """
    Skora göre sıralı adaylardan turu kurar; AYNI OLAYI bir kez alır.

    ⚠️ KATEGORİ VE KAYNAK KOTASI YOK (18 Ağu 2026'da kaldırıldı).
    Önce "kategori başına 3, kaynak başına 4" kuralı vardı. Amaç
    tekdüzeliği kırmaktı ama yan etkisi şuydu: gündem gerçekten tek
    konuya kilitlendiğinde (büyük bir deprem, seçim gecesi) kota o
    haberleri dışarıda bırakıp yerlerine daha önemsizlerini alıyordu.
    Gündemi biz değil olaylar belirlemeli.

    KALAN TEK KURAL — AYNI OLAY TEKRARI: başlıkları birbirine çok
    benzeyen haberlerden yalnızca en yüksek puanlısı alınıyor. Bu bir
    "çeşitlilik" tercihi değil, MÜKERRER İÇERİK engeli: aynı olayı iki
    kaynaktan üst üste koymak takipçiye yeni bir şey söylemiyor.
    """
    s = ayarlar.get("secim", {}) or {}
    ortak_esik = s.get("konu_ortak_kelime_esigi", 2)

    secilen, konular = [], []
    for haber in adaylar:
        if len(secilen) >= adet:
            break
        kelimeler = _anahtar_kelimeler(haber["ig_baslik"] or haber["baslik_orj"])
        if any(len(kelimeler & onceki) >= ortak_esik for onceki in konular):
            continue
        secilen.append(haber)
        konular.append(kelimeler)

    return secilen


def tur_icin_sec(con, ayarlar: dict) -> list:
    """
    Yayınlanacak haberleri seçer.

    Metni hazır olan havuzdan skora göre sıralayıp en iyi N tanesini
    döner. Onaylanmayıp havuza dönen haberler burada yeniden yarışıyor —
    "onay verilmezse haber elenmez" kararı böyle işliyor.
    """
    g = ayarlar["gorsel"]
    sinir_saat = ayarlar["genel"]["yayin_yasi_siniri_saat"]

    # ⚠️ ASGARİ ÖNEM PUANI — TUR ARTIK SABİT 10 SLAYT DEĞİL.
    #
    # Önce havuzdan en iyi 10 alınıyordu; havuz doluysa 10'uncu haber
    # bazen "belediye şu toplantıyı yaptı" seviyesine düşüyordu. Artık
    # eşiği geçen kaç haber varsa o kadar slayt üretiliyor: az gün 6-7,
    # yoğun gün 10. Zayıf haberle slayt doldurmak turun tamamını
    # sıradanlaştırıyor.
    asgari = (ayarlar.get("secim", {}) or {}).get("asgari_onem_puani", 0)

    adaylar = [
        h for h in con.execute(
            "SELECT * FROM haberler WHERE durum = 'metin_hazir' "
            "AND ig_baslik IS NOT NULL"
        )
        if _yas_saat(h) <= sinir_saat and (h["onem_puani"] or 0) >= asgari
    ]

    adaylar.sort(key=lambda h: skor(h, ayarlar), reverse=True)
    # Düz sıralamadan almak yerine çeşitlendiriyoruz: aynı olayın
    # haberleri birbirine yakın puan aldığı için üst üste diziliyordu.
    secilen = cesitlendir(adaylar, g["slayt_sayisi"], ayarlar)

    log.info("tur seçimi: %d adaydan %d haber", len(adaylar), len(secilen))
    return secilen
