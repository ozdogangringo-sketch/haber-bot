"""
zaman.py — Türkiye Saati (TSİ / UTC+3) & Zaman Dönüşüm Motoru

Bot genelinde tüm kullanıcı mesajları, Telegram bildirimleri, raporlar
ve hata kayıtları Türkiye Saati (UTC+3) ile sunulur. Türkiye'de kalıcı yaz
saati uygulaması (UTC+3) geçerlidir.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

# Türkiye Saati: UTC+3 (Kalıcı)
TR_TZ = timezone(timedelta(hours=3))

AYLAR_TR = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"
]


def su_an_tr() -> datetime:
    """Şu anki Türkiye saatini datetime nesnesi olarak döner."""
    return datetime.now(TR_TZ)


def tr_tarih_cevir(dt_or_str: Any) -> datetime | None:
    """
    Verilen ISO string, SQLite datetime stringi veya datetime nesnesini
    güvenle timezone-aware TR datetime nesnesine dönüştürür.
    """
    if not dt_or_str:
        return None
    if isinstance(dt_or_str, datetime):
        if dt_or_str.tzinfo is None:
            dt_or_str = dt_or_str.replace(tzinfo=timezone.utc)
        return dt_or_str.astimezone(TR_TZ)

    s = str(dt_or_str).strip()
    try:
        if "T" in s or "+" in s or "Z" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TR_TZ)
    except Exception:
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(TR_TZ)
        except Exception:
            return None


def tr_format(dt_or_str: Any, format_turu: str = "tam") -> str:
    """
    Tarihi Türkiye formatına çevirir:
      * 'saat': '19:42'
      * 'tam': '26 Ağustos 19:42'
      * 'tarih_saat': '26.08.2026 19:42 (TSİ)'
      * 'canli': '19:42:05 (TSİ)'
      * 'goreceli': '14 dakika önce' veya '2 saat önce'
    """
    dt_tr = tr_tarih_cevir(dt_or_str)
    if not dt_tr:
        return str(dt_or_str or "")

    if format_turu == "saat":
        return dt_tr.strftime("%H:%M")
    elif format_turu == "tam":
        ay_adi = AYLAR_TR[dt_tr.month - 1]
        return f"{dt_tr.day} {ay_adi} {dt_tr.strftime('%H:%M')}"
    elif format_turu == "tarih_saat":
        return f"{dt_tr.strftime('%d.%m.%Y %H:%M')} (TSİ)"
    elif format_turu == "canli":
        return f"{dt_tr.strftime('%H:%M:%S')} (TSİ)"
    elif format_turu == "goreceli":
        return goreceli_zaman(dt_tr)
    return dt_tr.strftime("%H:%M")


def goreceli_zaman(dt_or_str: Any) -> str:
    """İki an arasındaki farkı Türkçe insan dilinde ifade eder ('15 dakika önce', '2 saat önce')."""
    dt_tr = tr_tarih_cevir(dt_or_str)
    if not dt_tr:
        return ""
    simdi = su_an_tr()
    fark = simdi - dt_tr
    toplam_sn = int(fark.total_seconds())

    if toplam_sn < 60:
        return "az önce"
    dakika = toplam_sn // 60
    if dakika < 60:
        return f"{dakika} dakika önce"
    saat = dakika // 60
    kalan_dk = dakika % 60
    if saat < 24:
        return f"{saat} saat {kalan_dk} dk önce" if kalan_dk > 0 else f"{saat} saat önce"
    gun = saat // 24
    return f"{gun} gün önce"
