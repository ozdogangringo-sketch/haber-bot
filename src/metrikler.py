"""
metrikler.py — Sosyal Medya Algoritma Geri Besleme ve Performans Takip Motoru.

Bu modül:
  1. Instagram Graph API üzerinden yayınlanan gönderilerin gerçek etkileşim
     metriklerini (erişim, kaydetme, paylaşım, yorum, beğeni) çeker ve SQLite'a işler.
  2. En yüksek etkileşim (kaydetme & paylaşım) alan haber başlıklarını ve kancalarını tespit eder.
  3. Gemini metin üretim motoruna (generate_text.py) gerçek verilere dayalı
     "few-shot learning" kanca bağlamı besleyerek kanca kalitesini sürekli optimize eder.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("metrikler")

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Soğuk başlangıç (cold start) ve test durumlarında modelin referans alacağı
# kanıtlanmış yüksek etkileşimli kanca ve manşet şablonları.
VARSAYILAN_ORNEK_KANCALAR = [
    {
        "baslik": "İkinci el araç satışında yeni dönem: Güvenli ödeme sistemi zorunlu oldu",
        "kanca": "PARAYI ALMADAN DEVRİ VERMEK YASAKLANDI",
        "vurgu_sayi": "₺0",
        "vurgu_etiket": "nakit elden ödeme",
        "tur": "somut_yaptirim",
    },
    {
        "baslik": "Bakanlık denetimleri sıklaştırdı: Fahiş fiyat uygulayan marketlere ağır ceza",
        "kanca": "ŞUBE BAŞINA 1,2 MİLYON ₺ CEZA",
        "vurgu_sayi": "1.250",
        "vurgu_etiket": "kapatılan market şubesi",
        "tur": "stat_punch",
    },
    {
        "baslik": "Avrupa Birliği vize kurallarını güncelledi: Randevu süreleri uzatıldı",
        "kanca": "REDDEDİLENLER 6 AY BAŞVURAMAYACAK",
        "vurgu_sayi": "180 gün",
        "vurgu_etiket": "asgari bekleme süresi",
        "tur": "kisisel_etki",
    },
]


def instagram_metrikleri_guncelle(con, ayarlar: Optional[Dict[str, Any]] = None, gun: int = 14) -> dict[str, int]:
    """
    Son `gun` gün içinde yayınlanmış Instagram postlarının Graph API üzerinden
    erişim, kaydetme, paylaşım ve beğeni metriklerini çeker ve DB'yi günceller.
    """
    token = os.getenv("IG_ACCESS_TOKEN", "").strip()
    if not token:
        log.info("IG_ACCESS_TOKEN tanımlı değil, metrik güncelleme atlandı.")
        return {"guncellenen": 0, "hata": 0, "sebep": "token_yok"}

    sinir = (datetime.now(timezone.utc) - timedelta(days=gun)).isoformat()
    satirlar = con.execute("""
        SELECT id, ig_post_id, ig_baslik, kanca
        FROM haberler
        WHERE durum = 'yayinlandi'
          AND ig_post_id IS NOT NULL
          AND gonderim_zamani >= ?
        ORDER BY gonderim_zamani DESC
    """, (sinir,)).fetchall()

    if not satirlar:
        log.info("Son %s günde incelenecek Instagram postu bulunamadı.", gun)
        return {"guncellenen": 0, "hata": 0}

    guncellenen = 0
    hatalar = 0
    simdi_iso = datetime.now(timezone.utc).isoformat()

    for row in satirlar:
        h_id = row["id"]
        media_id = str(row["ig_post_id"]).strip()
        if not media_id or media_id.lower() == "none":
            continue

        try:
            # 1. Beğeni ve yorum sayıları
            r_temel = requests.get(
                f"{GRAPH_API_BASE}/{media_id}",
                params={"fields": "like_count,comments_count,media_type", "access_token": token},
                timeout=12,
            )
            if r_temel.status_code != 200:
                log.warning("IG temel veri hatası (ID %s, status %s): %s", media_id, r_temel.status_code, r_temel.text[:120])
                hatalar += 1
                continue

            veri_temel = r_temel.json()
            begeni = int(veri_temel.get("like_count") or 0)
            yorum = int(veri_temel.get("comments_count") or 0)

            # 2. Insights: reach (erişim), saved (kaydetme), shares (paylaşım)
            erisim = 0
            kaydetme = 0
            paylasim = 0

            r_ins = requests.get(
                f"{GRAPH_API_BASE}/{media_id}/insights",
                params={"metric": "reach,saved,shares", "access_token": token},
                timeout=12,
            )
            if r_ins.status_code == 200:
                veri_ins = r_ins.json().get("data", [])
                for metrik in veri_ins:
                    m_ad = metrik.get("name")
                    degerler = metrik.get("values", [])
                    m_val = degerler[0].get("value", 0) if degerler else 0
                    if m_ad == "reach":
                        erisim = int(m_val or 0)
                    elif m_ad == "saved":
                        kaydetme = int(m_val or 0)
                    elif m_ad == "shares":
                        paylasim = int(m_val or 0)
            else:
                # Carousel veya yeni gönderilerde bazı metrikler henüz toplanmamış olabilir
                log.debug("IG insights uyarısı (ID %s): %s", media_id, r_ins.text[:100])

            con.execute("""
                UPDATE haberler
                SET erisim = ?, kaydetme = ?, paylasim = ?, yorum = ?, begeni = ?, metrik_zamani = ?
                WHERE id = ?
            """, (erisim, kaydetme, paylasim, yorum, begeni, simdi_iso, h_id))
            guncellenen += 1

        except Exception as e:
            log.warning("Post metrikleri güncellenirken hata (ID %s): %s", media_id, e)
            hatalar += 1

    con.commit()
    log.info("Instagram metrikleri güncellendi: %s başarılı, %s hata.", guncellenen, hatalar)
    return {"guncellenen": guncellenen, "hata": hatalar}


def en_iyi_kancalari_getir(con, limit: int = 5, kategori: Optional[str] = None) -> list[dict[str, Any]]:
    """
    En yüksek etkileşim alan gönderileri ağırlıklı algoritmik skorla sıralar:
    Skor = (paylaşım * 4) + (kaydetme * 3) + (yorum * 2) + beğeni + (erişim / 100)
    """
    if con is None:
        return VARSAYILAN_ORNEK_KANCALAR[:limit]

    try:
        sql = """
            SELECT id, ig_baslik, kanca, vurgu_sayi, vurgu_etiket, kategori,
                   erisim, kaydetme, paylasim, yorum, begeni,
                   (COALESCE(paylasim, 0) * 4 + COALESCE(kaydetme, 0) * 3 +
                    COALESCE(yorum, 0) * 2 + COALESCE(begeni, 0) + (COALESCE(erisim, 0) / 100.0)) AS skor
            FROM haberler
            WHERE durum = 'yayinlandi'
              AND kanca IS NOT NULL AND TRIM(kanca) != ''
              AND (COALESCE(paylasim, 0) > 0 OR COALESCE(kaydetme, 0) > 0 OR COALESCE(begeni, 0) > 0)
        """
        params = []
        if kategori:
            sql += " AND kategori = ?"
            params.append(kategori)

        sql += " ORDER BY skor DESC LIMIT ?"
        params.append(limit)

        satirlar = con.execute(sql, tuple(params)).fetchall()
        if satirlar and len(satirlar) >= 1:
            return [dict(s) for s in satirlar]
    except Exception as e:
        log.warning("En iyi kancalar çekilirken DB hatası: %s", e)

    # Yeterli metrik verisi yoksa varsayılan yüksek etkileşimli şablonları dön
    return VARSAYILAN_ORNEK_KANCALAR[:limit]


def kanca_ogrenme_konteksti(con=None, limit: int = 3, kategori: Optional[str] = None) -> str:
    """
    Gemini istemine (generate_text.py) beslenmek üzere, daha önce en çok kaydetme
    ve paylaşım almış kanca formatlarını içeren dinamik few-shot prompt bloğu üretir.
    """
    ornekler = en_iyi_kancalari_getir(con, limit=limit, kategori=kategori)
    if not ornekler:
        return ""

    satirlar = [
        "★ HESAPTA EN ÇOK PAYLAŞIM VE KAYDETME ALAN GERÇEK KANCA VE VURGU KALIPLARI (BUNLARI MODEL AL):",
    ]
    for o in ornekler:
        b = (o.get("ig_baslik") or o.get("baslik") or "").strip()
        k = (o.get("kanca") or "").strip()
        vs = (o.get("vurgu_sayi") or "").strip()
        ve = (o.get("vurgu_etiket") or "").strip()
        vurgu_metni = f" [Vurgu: {vs} / {ve}]" if vs and ve else ""
        satirlar.append(f'  • Başlık: "{b}" -> Kanca: "{k}"{vurgu_metni}')

    satirlar.append(
        "  -> Bürokratik dolgu veya kuru ilçe/yer adları yerine 'somut kişisel etki', 'şok rakam' ve 'beklenmedik kırılma' kalıplarını uygula."
    )
    return "\n".join(satirlar)


def rapor_satirlari_getir(con, gun: int = 7) -> list[str]:
    """
    gunluk_rapor.py için son haftanın en çok paylaşılan ve kaydedilen içerik özetini döner.
    """
    if con is None:
        return []

    sinir = (datetime.now(timezone.utc) - timedelta(days=gun)).isoformat()
    try:
        satirlar = con.execute("""
            SELECT ig_baslik, kanca, erisim, kaydetme, paylasim, begeni
            FROM haberler
            WHERE durum = 'yayinlandi'
              AND gonderim_zamani >= ?
              AND (COALESCE(paylasim, 0) > 0 OR COALESCE(kaydetme, 0) > 0)
            ORDER BY (COALESCE(paylasim, 0) * 3 + COALESCE(kaydetme, 0) * 2) DESC
            LIMIT 3
        """, (sinir,)).fetchall()

        if not satirlar:
            return []

        cikti = ["📈 <b>Haftanın En Çok Etkileşim Alan İçerikleri:</b>"]
        for s in satirlar:
            b = s["ig_baslik"] or "İsimsiz Haber"
            if len(b) > 55:
                b = b[:52] + "…"
            cikti.append(
                f"  • {b}\n"
                f"    ↳ ↗️ {s['paylasim'] or 0} paylaşım · 🔖 {s['kaydetme'] or 0} kaydetme · 👁️ {s['erisim'] or 0} erişim"
            )
        return cikti
    except Exception as e:
        log.warning("Metrik rapor satırları alınamadı: %s", e)
        return []
