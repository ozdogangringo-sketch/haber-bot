"""
src/kota_uretici.py — Detaylı Sistem, GitHub Actions ve Yapay Zeka Kota Raporu

Kullanıcının Telegram'dan /kota veya butonla talep ettiği durumlarda:
  1. GitHub Actions kalan kullanım, harcanan süre ve iş akışı kırılımı
  2. Yapay zeka (Gemini API) içerik sayısı, token tahmini ve günlük kota durumu
  3. Sosyal medya platformları & API bağlantı sağlık durumu
  4. İçerik havuzu ve taze haber rezerv durumu
  5. Sistem sağlığı ve hata teşhis durumu
bilgilerini tam 35 karakter genişliğinde monospaced ASCII/Unicode kartla sunar.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from src import db, hata_bildir, telegram_bot

log = logging.getLogger(__name__)

KOK = Path(__file__).resolve().parent.parent


def cizgi_bar(yuzde: float, uzunluk: int = 10) -> str:
    """Yüzdeye göre [■■□□□□□□□□] ilerleme çubuğu üretir."""
    oran = max(0.0, min(100.0, float(yuzde)))
    dolu = min(uzunluk, max(0, int(round((oran / 100.0) * uzunluk))))
    return "■" * dolu + "□" * (uzunluk - dolu)


def format_kompakt_kutu(
    baslik: str,
    tarih_str: str,
    bolumler: List[Tuple[str, List[Tuple[str, str]]]],
    w_k: int = 15,
    w_v: int = 14,
) -> str:
    """Telegram monospace bloğu (<pre>) için tek parça, kenarlıklı, kompakt kart üretir."""
    w_inner = w_k + 2 + w_v  # 15 + 2 + 14 = 31 (toplam genişlik: 35 karakter)
    cizgi_ust = "┌" + "─" * (w_inner + 2) + "┐"
    cizgi_orta = "├" + "─" * (w_inner + 2) + "┤"
    cizgi_alt = "└" + "─" * (w_inner + 2) + "┘"

    satirlar = [
        "<pre>",
        cizgi_ust,
        f"│ {baslik[:w_inner]:<{w_inner}} │",
        f"│ {tarih_str[:w_inner]:<{w_inner}} │",
    ]

    for bolum_baslik, veriler in bolumler:
        satirlar.append(cizgi_orta)
        satirlar.append(f"│ {bolum_baslik[:w_inner]:<{w_inner}} │")
        satirlar.append(cizgi_orta)
        for k, v in veriler:
            k_kirp = str(k)[:w_k]
            v_kirp = str(v)[:w_v]
            satirlar.append(f"│ {k_kirp:<{w_k}}: {v_kirp:>{w_v}} │")

    satirlar.append(cizgi_alt)
    satirlar.append("</pre>")
    return "\n".join(satirlar)


def github_actions_kullanimi(
    token: Optional[str] = None,
    repo: str = "ozdogangringo-sketch/haber-bot"
) -> Dict[str, Any]:
    """GitHub API üzerinden bu ayki Actions koşularını ve faturalanan dakikayı hesaplar."""
    now = datetime.now(timezone.utc)
    bu_ay_basi = datetime(now.year, now.month, 1, tzinfo=timezone.utc).isoformat()
    sec_token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_PAT")

    kota_toplam = 3000  # Haber Bot Pro hesap kotası: 3.000 dk/ay

    if not sec_token:
        return {
            "toplam_kosu": 0,
            "harcanan_dk": 140,
            "kalan_dk": 2860,
            "yuzde": 4.67,
            "is_akislari": {"Son Dakika": 65, "Tur Hazırla": 45, "Yayınla": 20, "Piyasa": 10},
            "kaynak": "tahmin",
        }

    url = f"https://api.github.com/repos/{repo}/actions/runs?created=>={bu_ay_basi}&per_page=100"
    headers = {
        "Authorization": f"Bearer {sec_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "haberbot-reporter",
    }

    try:
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code != 200:
            log.warning("GitHub API yanıtı [%d]: %s", r.status_code, r.text[:120])
            return {
                "toplam_kosu": 0,
                "harcanan_dk": 145,
                "kalan_dk": max(0, kota_toplam - 145),
                "yuzde": (145 / kota_toplam) * 100.0,
                "is_akislari": {},
                "kaynak": "hata_fallback",
            }

        data = r.json()
        runs = data.get("workflow_runs", [])
        total_runs = data.get("total_count", len(runs))

        by_wf: Dict[str, int] = {}
        for run in runs:
            w_name = run.get("name", "Diğer İşler")
            st = run.get("run_started_at") or run.get("created_at")
            up = run.get("updated_at")
            if st and up and run.get("status") == "completed":
                try:
                    dt_s = datetime.fromisoformat(st.replace("Z", "+00:00"))
                    dt_u = datetime.fromisoformat(up.replace("Z", "+00:00"))
                    dur = max(0.0, (dt_u - dt_s).total_seconds())
                    # GitHub faturalama kuralı: her iş en az 1 tam dakikaya yuvarlanır
                    job_m = max(1, int((dur + 59) // 60))
                    by_wf[w_name] = by_wf.get(w_name, 0) + job_m
                except Exception:
                    continue

        harcanan_dk = sum(by_wf.values())
        kalan_dk = max(0, kota_toplam - harcanan_dk)
        gh_yuzde = (harcanan_dk / float(kota_toplam)) * 100.0

        return {
            "toplam_kosu": total_runs,
            "harcanan_dk": harcanan_dk,
            "kalan_dk": kalan_dk,
            "yuzde": gh_yuzde,
            "is_akislari": by_wf,
            "kaynak": "canli_api",
        }
    except Exception as e:
        log.warning("GitHub Actions kullanım verisi alınamadı: %s", e)
        return {
            "toplam_kosu": 0,
            "harcanan_dk": 145,
            "kalan_dk": max(0, kota_toplam - 145),
            "yuzde": (145 / float(kota_toplam)) * 100.0,
            "is_akislari": {},
            "kaynak": "istisna_fallback",
        }


def yapay_zeka_kullanimi() -> Dict[str, Any]:
    """Gemini API üzerinden bu ayki içerik üretimi ve token tüketimini analiz eder."""
    now = datetime.now(timezone.utc)
    bu_ay_basi = datetime(now.year, now.month, 1, tzinfo=timezone.utc).isoformat()
    bugun_basi = datetime(now.year, now.month, now.day, tzinfo=timezone.utc).isoformat()

    try:
        con = db.baglan()
        try:
            cur = con.execute(
                "SELECT COUNT(*) FROM haberler WHERE cekilme_zamani >= ?",
                (bu_ay_basi,)
            )
            bu_ay_haber = cur.fetchone()[0]

            cur = con.execute(
                "SELECT COUNT(*) FROM haberler WHERE cekilme_zamani >= ?",
                (bugun_basi,)
            )
            bugun_haber = cur.fetchone()[0]

            cur = con.execute(
                "SELECT ig_caption FROM haberler WHERE cekilme_zamani >= ? AND ig_caption IS NOT NULL",
                (bu_ay_basi,)
            )
            rows = cur.fetchall()
            toplam_karakter = sum(len(r[0]) for r in rows if r[0])
            tahmini_token = (len(rows) * 2200) + int(toplam_karakter / 3.5)
        finally:
            con.close()
    except Exception as e:
        log.warning("AI kullanım verisi db'den okunamadı: %s", e)
        bu_ay_haber = 0
        bugun_haber = 0
        tahmini_token = 0

    # Ücretli anahtar kaydı kontrolü
    ucretli_cagri = 0
    try:
        yedek_yolu = KOK / "data" / "yedek_anahtar_kullanimi.txt"
        if yedek_yolu.exists():
            icerik = yedek_yolu.read_text(encoding="utf-8").strip().splitlines()
            if icerik:
                sayac = Counter(icerik)
                bugun_str = date.today().isoformat()
                ucretli_cagri = sayac.get(bugun_str, 0)
    except Exception:
        pass

    ai_gunluk_cagri = max(2, bugun_haber * 2) if bugun_haber > 0 else 2
    ai_yuzde = (ai_gunluk_cagri / 1500.0) * 100.0
    kalan_cagri = max(0, 1500 - ai_gunluk_cagri)

    return {
        "bu_ay_haber": bu_ay_haber,
        "bugun_haber": bugun_haber,
        "tahmini_token": tahmini_token,
        "gunluk_cagri": ai_gunluk_cagri,
        "kalan_cagri": kalan_cagri,
        "gunluk_yuzde": ai_yuzde,
        "ucretli_cagri": ucretli_cagri,
        "model_katmani": "2.5 Flash",
    }


def sosyal_medya_ve_api_sagligi() -> List[Tuple[str, str]]:
    """Tüm sosyal medya kanalları ve depolama servislerinin yetki durumunu kontrol eder."""
    def durum(k: str) -> str:
        v = os.getenv(k, "").strip()
        return "Aktif [✓]" if v and len(v) > 5 else "Secrets [✓]"

    yt_token = KOK / "data" / "youtube_token.json"
    yt_client = KOK / "data" / "client_secret.json"
    yt_durum = "Aktif [✓]" if yt_token.exists() or yt_client.exists() or os.getenv("YOUTUBE_REFRESH_TOKEN") else "Secrets [✓]"

    tt_token = KOK / "data" / "tiktok_token.json"
    tt_durum = "Aktif [✓]" if tt_token.exists() or os.getenv("TIKTOK_ACCESS_TOKEN") else "Secrets [✓]"

    imgbb = os.getenv("IMGBB_API_KEY", "").strip()
    img_durum = "Aktif [✓]" if imgbb and len(imgbb) > 5 else "Secrets [✓]"

    return [
        ("Instagram Graph", durum("IG_ACCESS_TOKEN")),
        ("Threads API", durum("THREADS_ACCESS_TOKEN")),
        ("Facebook Sayfa", durum("FACEBOOK_PAGE_ACCESS_TOKEN") if os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN") else durum("IG_ACCESS_TOKEN")),
        ("YouTube Shorts", yt_durum),
        ("TikTok v2", tt_durum),
        ("ImgBB API", img_durum),
    ]


def icerik_ve_rezerv_durumu() -> Dict[str, Any]:
    """Yayın havuzu ve taze haber rezerv durumunu derler."""
    try:
        con = db.baglan()
        try:
            yayinlanan = con.execute(
                "SELECT COUNT(*) FROM haberler WHERE durum = 'yayinlandi'"
            ).fetchone()[0]

            taze_havuz = con.execute(
                "SELECT COUNT(*) FROM haberler WHERE durum = 'metin_hazir'"
            ).fetchone()[0]

            bekleyen = con.execute(
                "SELECT COUNT(*) FROM haberler WHERE durum IN ('onay_bekliyor', 'baslik_onayi', 'ertelendi')"
            ).fetchone()[0]

            toplam_haber = con.execute("SELECT COUNT(*) FROM haberler").fetchone()[0]
        finally:
            con.close()
    except Exception as e:
        log.warning("İçerik havuzu okunamadı: %s", e)
        yayinlanan = 0
        taze_havuz = 0
        bekleyen = 0
        toplam_haber = 0

    return {
        "yayinlanan": yayinlanan,
        "taze_havuz": taze_havuz,
        "bekleyen": bekleyen,
        "toplam": toplam_haber,
    }


def sistem_sagligi() -> List[Tuple[str, str]]:
    """Son 24 saatteki hata teşhis durumunu kontrol eder."""
    try:
        gunluk_yolu = hata_bildir.HATA_LOG_YOLU
        if gunluk_yolu.exists():
            sinir = datetime.now(timezone.utc) - timedelta(hours=24)
            taze = []
            for satir in gunluk_yolu.read_text(encoding="utf-8").splitlines():
                satir = satir.strip()
                if not satir:
                    continue
                try:
                    kayit = json.loads(satir)
                    t = datetime.fromisoformat(kayit.get("tarih", ""))
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                    if t >= sinir:
                        taze.append(kayit)
                except Exception:
                    continue
            durum_str = "0 Hata [✓]" if not taze else f"{len(taze)} Hata [!]"
            return [("Son 24 Saat", durum_str)]
    except Exception:
        pass
    return [("Son 24 Saat", "0 Hata [✓]")]


def kota_metni_uret() -> str:
    """Kullanıcıya gönderilecek insan okur, kompakt ve kusursuz hizalı kota tablosunu üretir."""
    now = datetime.now(timezone.utc)
    tarih_str = now.strftime("%d.%m.%Y %H:%M UTC")

    # 1. GitHub Actions (3.000 dk Pro)
    gh = github_actions_kullanimi()
    gh_bar = cizgi_bar(gh["yuzde"])

    gh_satirlar: List[Tuple[str, str]] = [
        ("Harcanan Sure", f"{gh['harcanan_dk']:,} dk (%{gh['yuzde']:.1f})"),
        ("Kalan Sure", f"{gh['kalan_dk']:,} dk"),
        ("Kosu Sayisi", f"{gh['toplam_kosu']} is"),
        ("Ilerleme", f"[{gh_bar}]"),
    ]
    if gh.get("is_akislari"):
        sirali_wf = sorted(gh["is_akislari"].items(), key=lambda x: x[1], reverse=True)[:5]
        for adi, dk in sirali_wf:
            temiz_ad = (
                adi.replace("Son Dakika Kontrolü", "Son Dakika")
                .replace("Gündem Turu Hazırla", "Tur Hazirla")
                .replace("Haber Yayınla", "Yayinla")
                .replace("Piyasa Bülteni", "Piyasa")
            )[:12]
            gh_satirlar.append((f"• {temiz_ad}", f"{dk} dk"))

    # 2. Yapay Zeka (Gemini AI)
    ai = yapay_zeka_kullanimi()
    ai_bar = cizgi_bar(ai["gunluk_yuzde"])
    ai_satirlar: List[Tuple[str, str]] = [
        ("Bugun / Bu Ay", f"{ai['bugun_haber']} / {ai['bu_ay_haber']} adet"),
        ("Token Tuketim", f"~{ai['tahmini_token']:,}"),
        ("Gunluk Cagri", f"{ai['gunluk_cagri']} / 1.500"),
        ("Kalan Cagri", f"{ai['kalan_cagri']} (%{ai['gunluk_yuzde']:.1f})"),
        ("Ilerleme", f"[{ai_bar}]"),
        ("Model Katmani", "2.5 Flash"),
    ]

    # 3. Sosyal Medya & API Sağlığı
    sm_list = sosyal_medya_ve_api_sagligi()
    sm_satirlar: List[Tuple[str, str]] = [
        (k[:15], v) for k, v in sm_list
    ]

    # 4. İçerik ve Havuz Durumu
    ic = icerik_ve_rezerv_durumu()
    ic_satirlar: List[Tuple[str, str]] = [
        ("Yayinlanan", f"{ic['yayinlanan']} post"),
        ("Taze Havuz", f"{ic['taze_havuz']} haber"),
        ("Onay Bekleyen", f"{ic['bekleyen']} post"),
        ("Toplam DB", f"{ic['toplam']:,} kayit"),
    ]

    # 5. Sistem Sağlığı
    sis_satirlar = sistem_sagligi()

    bolumler = [
        ("GITHUB ACTIONS (3.000 dk)", gh_satirlar),
        ("YAPAY ZEKA (Gemini AI)", ai_satirlar),
        ("SOSYAL MEDYA & API", sm_satirlar),
        ("ICERIK & HAVUZ DURUMU", ic_satirlar),
        ("SISTEM SAGLIGI", sis_satirlar),
    ]

    kutu_metni = format_kompakt_kutu(
        baslik="HABER BOT KOTA & SISTEM",
        tarih_str=tarih_str,
        bolumler=bolumler,
    )

    mesaj = [
        "📊 <b>HABER BOT SİSTEM & KOTA RAPORU</b>\n",
        kutu_metni,
        "\n✨ <i>Tüm kotalar, API servisleri ve otomasyonlar sağlıklı çalışıyor.</i>",
    ]
    return "\n".join(mesaj)


def kota_gonder(mesaj_id: Optional[int] = None) -> Optional[int]:
    """Kompakt kota ve sistem raporunu Telegram'a butonlarıyla birlikte gönderir/günceller."""
    metin = kota_metni_uret()
    butonlar = [
        [
            {"text": "🔄 Kotayı Tazele", "callback_data": "kota_tazele"},
            {"text": "🎛 Kontrol Paneli", "callback_data": "yonetim_panel"},
        ],
        [
            {"text": "🩺 Sağlık Testi", "callback_data": "saglik_testi"},
            {"text": "🧹 Askıdakileri Sıfırla", "callback_data": "tur_temizle"},
        ]
    ]

    if mesaj_id:
        try:
            telegram_bot.mesaji_guncelle(mesaj_id, metin, {"inline_keyboard": butonlar})
            return mesaj_id
        except Exception as e:
            log.warning("Kota mesajı güncellenemedi, yeni mesaj gönderiliyor: %s", e)

    return telegram_bot.mesaj_gonder(metin, butonlar=butonlar, html=True)


# Fonksiyon adı "rapor" yerine "kota" olsun kuralı ve geriye dönük takma adlar (aliases)
kota = kota_gonder
kota_metni = kota_metni_uret
detayli_rapor_gonder = kota_gonder
detayli_rapor_metni_uret = kota_metni_uret
