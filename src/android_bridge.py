"""
android_bridge.py — Android Otomasyon İstasyonu Köprü Modülü

Hazırlanan veya onaylanan haber slaytlarını, başlıklarını ve caption metnini
Android telefonun yerel olarak tüketebileceği standart JSON paketine dönüştürür
ve Android otomasyon cihazına servis eder.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

KOK = Path(__file__).resolve().parent.parent
CIKTI_KLASORU = KOK / "data" / "output"
PAKET_YOLU = CIKTI_KLASORU / "son_tur_android.json"


def paketi_hazirla(
    mesaj_id: int | str,
    haberler: list[dict],
    gorsel_yollari: list[str | Path],
    caption_metni: str,
    ayarlar: dict | None = None,
    muzik_kategorisi: str = "Gündem & Haber",
) -> Path:
    """
    Android cihazın Instagram üzerinden müzikli carousel paylaşması için
    tüm verileri (slayt yolları, URL'ler, caption ve müzik tercihi) paketler.
    """
    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)

    slayt_listesi = []
    for idx, yol in enumerate(gorsel_yollari, start=1):
        p = Path(yol)
        slayt_listesi.append({
            "sira": idx,
            "yerel_yol": str(p.resolve()),
            "dosya_adi": p.name,
            "mevcut": p.exists(),
        })

    paket = {
        "tur_id": str(mesaj_id),
        "hazirlanma_tarihi": datetime.now(timezone.utc).isoformat(),
        "slayt_sayisi": len(gorsel_yollari),
        "muzik_kategorisi": muzik_kategorisi,
        "caption": caption_metni,
        "haberler": [
            {
                "id": h.get("id"),
                "baslik": h.get("ig_baslik") or h.get("baslik_orj", ""),
                "kategori": h.get("kategori", ""),
                "kaynak": h.get("kaynak", ""),
                "gorsel_url": h.get("gorsel_url", ""),
            }
            for h in haberler
        ],
        "slaytlar": slayt_listesi,
        "durum": "yayin_bekliyor",
    }

    PAKET_YOLU.write_text(json.dumps(paket, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Android otomasyon paketi oluşturuldu: %s (%s slayt)", PAKET_YOLU, len(gorsel_yollari))
    return PAKET_YOLU


def son_paketi_oku() -> dict | None:
    """Android cihazın çekeceği en son hazır paketi okur."""
    if not PAKET_YOLU.exists():
        return None
    try:
        return json.loads(PAKET_YOLU.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Android paketi okunamadı: %s", e)
        return None


def durumu_guncelle(durum: str, post_id: str = "") -> bool:
    """Android cihaz yayını tamamladığında durumu günceller."""
    veri = son_paketi_oku()
    if not veri:
        return False

    veri["durum"] = durum
    veri["tamamlanma_tarihi"] = datetime.now(timezone.utc).isoformat()
    if post_id:
        veri["instagram_post_id"] = post_id

    PAKET_YOLU.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
    return True
