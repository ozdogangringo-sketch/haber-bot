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
    secilen = [h for _, h in puanli[:kac]]
    log.info("ön eleme: %d havuzdan %d aday", len(havuz), len(secilen))
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


def tur_icin_sec(con, ayarlar: dict) -> list:
    """
    Yayınlanacak haberleri seçer.

    Metni hazır olan havuzdan skora göre sıralayıp en iyi N tanesini
    döner. Onaylanmayıp havuza dönen haberler burada yeniden yarışıyor —
    "onay verilmezse haber elenmez" kararı böyle işliyor.
    """
    g = ayarlar["gorsel"]
    sinir_saat = ayarlar["genel"]["yayin_yasi_siniri_saat"]

    adaylar = [
        h for h in con.execute(
            "SELECT * FROM haberler WHERE durum = 'metin_hazir' "
            "AND ig_baslik IS NOT NULL"
        )
        if _yas_saat(h) <= sinir_saat
    ]

    adaylar.sort(key=lambda h: skor(h, ayarlar), reverse=True)
    secilen = adaylar[: g["slayt_sayisi"]]

    log.info("tur seçimi: %d adaydan %d haber", len(adaylar), len(secilen))
    return secilen
