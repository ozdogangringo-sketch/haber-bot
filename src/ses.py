"""
ses.py — ElevenLabs seslendirmesi ve seslendirmeli dikey video ("🎙️ Sesli Yayınla").

postedm'den taşındı (2026-09-26, edm/postedm/src/ses.py). Kullanıcı kararları
orada dinlenerek verildi ve burada aynen geçerli:

  * Ses "Sıla Özalp" (ElevenLabs kütüphanesi, haber sunucusu), "biraz daha hızlı ve
    heyecanlı" ayarla. Tek kaynak config.yaml › seslendirme; ses kütüphaneden
    kalkarsa yedek sese düşülür.
  * Yalnızca KAPAK okunur. Tur (10 ayrı haber) için "basliklar" kipi de var:
    her haberin başlığı kendi slaytında okunur (config.yaml › seslendirme.tur_kipi).
  * Son slaytta kısa kapanış çağrısı ("…istemiyorsanız takipte kalın"); "beğenin" yok.
  * Seslendirme isteğe bağlı: düz "✅ Yayınla" eskisi gibi seslendirmesiz. "🎙️ Sesli
    Yayınla" → fon müzikli / fon müziksiz. Worker kanal listesine ses_muzikli /
    ses_muziksiz ekler; onay_isle.yayinla onu okur.
  * Metin önce src/okunus.py'den geçer ("Hz." hezt değil Hazreti, "1/5000" beş binde bir).

Okunan metin slayttakiyle AYNIDIR: içerik filtresinden geçmiş başlık ve özet
(slaytlar._slayt_metni). Filtrenin yumuşattığı bir kelime seste ham okunmamalı.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import imageio_ffmpeg
import requests
from dotenv import load_dotenv

from . import okunus

load_dotenv()
log = logging.getLogger(__name__)

KOK = Path(__file__).resolve().parent.parent
CIKTI = KOK / "data" / "output"
FON_MUZIGI = KOK / "assets" / "audio" / "haber_fon.mp3"
YEDEK_SES_ID = "J17lijyP1BHYcM7ld0Rg"  # Adam — config.yaml'da ses yoksa

ANLATIM_ONCESI_SN = 0.4   # slayt açıldıktan sonra sesin başlaması
ANLATIM_SONRASI_SN = 0.8  # ses bittikten sonra geçişe kadar nefes
CAGRI_ARASI_SN = 0.6
GECIS_SN = 0.5


def _ayar(ayarlar: Optional[Dict[str, Any]], yol: str, varsayilan: Any = None) -> Any:
    deger: Any = (ayarlar or {}).get("seslendirme") or {}
    for parca in yol.split("."):
        if not isinstance(deger, dict) or parca not in deger:
            return varsayilan
        deger = deger[parca]
    return deger


def ses_suresi_ogren(ses_yolu: Optional[Path | str]) -> float:
    if not ses_yolu or not Path(ses_yolu).exists():
        return 0.0
    try:
        cikti = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(ses_yolu)],
                               capture_output=True, text=True).stderr
        saat, dakika, saniye = cikti.split("Duration: ")[1].split(",")[0].split(":")
        return int(saat) * 3600 + int(dakika) * 60 + float(saniye)
    except Exception as e:
        log.warning("Ses süresi okunamadı (%s): %s", ses_yolu, e)
        return 0.0


def metin_seslendir(metin: str, ayarlar: Optional[Dict[str, Any]] = None,
                    cikti_yolu: Optional[Path] = None) -> Optional[Path]:
    """Metni ElevenLabs ile seslendirir; anahtar yoksa ya da kota bittiyse None."""
    anahtar = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not anahtar:
        log.warning("ELEVENLABS_API_KEY yok, seslendirme atlanıyor.")
        return None
    # Okunuş, sonra tek harfin tırnağı ("A Milli Takım": düz "A" çok hızlı okunuyordu — ölçüldü)
    temiz = okunus.tek_harfleri_belirginlestir(okunus.okunusa_cevir(metin or ""))
    if not temiz:
        return None
    sesler = [s for s in dict.fromkeys([_ayar(ayarlar, "ses_id"), _ayar(ayarlar, "yedek_ses_id"), YEDEK_SES_ID]) if s]
    cikti_yolu = Path(cikti_yolu or CIKTI / f"ses_{os.getpid()}_{int(time.time() * 1000)}.mp3")
    cikti_yolu.parent.mkdir(parents=True, exist_ok=True)
    basliklar = {"xi-api-key": anahtar, "Content-Type": "application/json"}
    govde = {"text": temiz, "model_id": _ayar(ayarlar, "model", "eleven_multilingual_v2"),
             "voice_settings": dict(_ayar(ayarlar, "ayarlar", {}) or {}), "language_code": "tr"}
    for ses_id in sesler:
        for deneme in range(1, 4):
            try:
                r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{ses_id}",
                                  headers=basliklar, json=govde, timeout=45)
                if r.status_code == 200 and len(r.content) > 500:
                    cikti_yolu.write_bytes(r.content)
                    return cikti_yolu
                log.warning("ElevenLabs hatası (deneme %d/3) [%s]: %s", deneme, r.status_code, r.text[:120])
                if r.status_code in (401, 402):
                    return None  # yetki/kota: başka ses denemek de aynı hatayı alır
                if r.status_code in (400, 404) and "voice" in r.text.lower():
                    break  # ses kütüphaneden kalkmış: yedek sese geç
            except Exception as e:
                log.warning("ElevenLabs isteği başarısız (deneme %d/3): %s", deneme, e)
            if deneme < 3:
                time.sleep(1.5 * deneme)
    return None


def _slayt_metni(haber: Any, alan: str, ayarlar: Optional[Dict[str, Any]]) -> str:
    """Slayta basılan metnin AYNISI (içerik filtresinden geçmiş)."""
    from . import slaytlar
    try:
        return (slaytlar._slayt_metni(haber, alan, ayarlar or {}) or "").strip()
    except Exception:
        return ""


def slayt_metinleri(haberler: List[Any], ayarlar: Optional[Dict[str, Any]], slayt_sayisi: int) -> List[Optional[str]]:
    """Her slaytta okunacak metin (None = sessiz). Başlık ve özet dışında hiçbir şey okunmaz.

    Tek haber (son dakika, tekil): kapakta başlık + özet, detay sayfaları sessiz.
    Tur (birden çok haber): her slayt YALNIZCA kendi haberinin başlığını okur —
    kullanıcı kararı 2026-09-26 ("elle tetiklediğimde sadece başlıkları okunsun");
    `tur_kipi: kapak` eski davranışa (yalnız ilk slayt, başlık + özet) döner.
    Ekonomi turunun ilk slaytları ısı haritası ve tablo: haber metni okunmaz.
    """
    metinler: List[Optional[str]] = [None] * max(0, slayt_sayisi)
    if not haberler or not metinler:
        return metinler
    ilk = dict(haberler[0]) if hasattr(haberler[0], "keys") else {}
    if ilk.get("tur") == "ekonomi":
        return metinler

    def cumle(*parcalar: str) -> Optional[str]:
        temiz = []
        for p in parcalar:
            p = (p or "").strip()
            if not p:
                continue
            if p[-1] not in ".?!…":
                p += "."
            if not any(p.lower().rstrip(".") in t.lower() for t in temiz):
                temiz.append(p)
        return " ".join(temiz) or None

    if len(haberler) > 1 and _ayar(ayarlar, "tur_kipi", "basliklar") == "basliklar":
        for i in range(min(len(haberler), slayt_sayisi)):
            metinler[i] = cumle(_slayt_metni(haberler[i], "ig_baslik", ayarlar))
        return metinler
    metinler[0] = cumle(_slayt_metni(haberler[0], "ig_baslik", ayarlar), _slayt_metni(haberler[0], "slayt_ozet", ayarlar))
    return metinler


def kapanis_cagrisi(ayarlar: Optional[Dict[str, Any]]) -> Optional[str]:
    return (_ayar(ayarlar, "kapanis_cagrisi") or "").strip() or None


def _anlatim_izi(parcalar: List[tuple], toplam_sure: float, cikti: Path) -> Optional[Path]:
    """(ses, başlangıç sn) parçalarını video boyunda tek bir ize yerleştirir."""
    girdiler: List[str] = []
    zincir: List[str] = []
    for i, (yol, bas) in enumerate(parcalar):
        girdiler += ["-i", str(yol)]
        zincir.append(f"[{i}:a]adelay=delays={int(bas * 1000)}:all=1[a{i}]")
    etiket = "".join(f"[a{i}]" for i in range(len(parcalar)))
    zincir.append(f"{etiket}amix=inputs={len(parcalar)}:normalize=0,apad=whole_dur={toplam_sure:.2f}[out]")
    try:
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", *girdiler, "-filter_complex", ";".join(zincir),
                        "-map", "[out]", "-t", f"{toplam_sure:.2f}", "-ar", "44100", "-ac", "2", str(cikti)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return cikti
    except Exception as e:
        log.warning("Anlatım izi kurulamadı: %s", e)
        return None


def seslendirilmis_mi(yol: Optional[Path | str]) -> bool:
    """Sesi son hâlini almış video: youtube_icin_sesli_video_hazirla ona müzik EKLEMEZ.

    O fonksiyon adında "_yt" olmayan her videonun sesini fon müziğiyle DEĞİŞTİRİYOR;
    seslendirmeli video olduğu gibi verilse anlatım silinirdi.
    """
    return bool(yol) and Path(yol).stem.endswith("_sesli")


def sesli_video_hazirla(video_yolu: Path, konusma: Optional[Path], muzik: bool,
                        ayarlar: Optional[Dict[str, Any]] = None) -> Path:
    """Anlatım (varsa) + fon müziği (istenirse) → "<ad>_sesli.mp4", ses seviyesi normalleşmiş."""
    cikti = video_yolu.with_name(f"{video_yolu.stem}_sesli.mp4")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    seviye = f"loudnorm=I={_ayar(ayarlar, 'hedef_lufs', -14)}:TP=-1.5:LRA=11"
    muzikli = muzik and FON_MUZIGI.exists()
    if konusma and muzikli:
        komut = [ffmpeg, "-y", "-i", str(video_yolu), "-i", str(konusma), "-stream_loop", "-1", "-i", str(FON_MUZIGI),
                 "-filter_complex", f"[1:a]volume=1.0[v];[2:a]volume=0.14[m];[v][m]amix=inputs=2:duration=first:"
                 f"dropout_transition=2,{seviye}[aout]", "-map", "0:v", "-map", "[aout]"]
    elif konusma:
        komut = [ffmpeg, "-y", "-i", str(video_yolu), "-i", str(konusma), "-map", "0:v", "-map", "1:a", "-af", seviye]
    elif muzikli:  # seslendirme düştü ama müzik istendi: eskisi gibi fon müzikli
        komut = [ffmpeg, "-y", "-i", str(video_yolu), "-stream_loop", "-1", "-i", str(FON_MUZIGI),
                 "-map", "0:v", "-map", "1:a", "-filter:a", "volume=0.20"]
    else:  # müziksiz ve ses yok: sessiz video "_sesli" adıyla; yükleyici müzik eklemesin
        komut = [ffmpeg, "-y", "-i", str(video_yolu), "-c", "copy"]
    komut += ([] if komut[-1] == "copy" else ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest"])
    komut += ["-movflags", "+faststart", str(cikti)]
    subprocess.run(komut, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return cikti


def _onbellekli_seslendir(metin: str, ayarlar: Optional[Dict[str, Any]]) -> Optional[Path]:
    """Kapanış çağrısı her videoda aynı: ses + ayar + metin aynıysa yeniden üretilmez."""
    anahtar = hashlib.md5(repr((_ayar(ayarlar, "ses_id"), _ayar(ayarlar, "ayarlar"), metin)).encode()).hexdigest()[:16]
    yol = CIKTI / "ses_onbellek" / f"{anahtar}.mp3"
    if yol.exists() and yol.stat().st_size > 500:
        return yol
    return metin_seslendir(metin, ayarlar, cikti_yolu=yol)


def anlatimli_video_uret(dikey_gorseller: List[Path | str], haberler: List[Any],
                         ayarlar: Optional[Dict[str, Any]] = None, muzik: bool = True,
                         sonuc: Optional[Dict[str, Any]] = None) -> Optional[Path]:
    """Onaylanan 9:16 karelerden seslendirmeli video; dönüş her zaman "_sesli" adlı.

    Okunan slayt, sesi bitene kadar ekranda kalır; diğerleri video.slayt_surelerini_hesapla
    kadar. Kapanış çağrısı son slaytın SONUNA yaslanır (tek slaytta kapak sesinin ardına).
    Seslendirme düşerse video seslendirmesiz çıkar ve sonuc["anlatim"] False olur.
    """
    from . import video

    n = len(dikey_gorseller)
    if not n:
        return None
    metinler = slayt_metinleri(haberler, ayarlar, n)
    sesler: List[Optional[Path]] = []
    for metin in metinler:
        try:
            sesler.append(metin_seslendir(metin, ayarlar) if metin else None)
        except Exception as e:
            log.warning("Seslendirme üretilemedi: %s", e)
            sesler.append(None)
    cagri = None
    if any(sesler) and kapanis_cagrisi(ayarlar):
        cagri = _onbellekli_seslendir(kapanis_cagrisi(ayarlar), ayarlar)
    if sonuc is not None:
        sonuc["anlatim"] = any(sesler)

    sureler = list(video.slayt_surelerini_hesapla(n, haberler=haberler))
    sure_ses = [ses_suresi_ogren(s) if s else 0.0 for s in sesler]
    for i, d in enumerate(sure_ses):
        if d:
            sureler[i] = round(max(sureler[i], ANLATIM_ONCESI_SN + d + ANLATIM_SONRASI_SN + GECIS_SN), 2)
    parcalar = [(s, sum(sureler[:i]) + ANLATIM_ONCESI_SN) for i, s in enumerate(sesler) if s]
    if cagri:
        d_cagri = ses_suresi_ogren(cagri)
        son_bas = sum(sureler[:-1])
        asgari = son_bas + (ANLATIM_ONCESI_SN + sure_ses[-1] + CAGRI_ARASI_SN if sesler[-1] else CAGRI_ARASI_SN)
        # Bu projede son slayt geçiş payı yemez: video sonu = sürelerin toplamı
        sureler[-1] = round(max(sureler[-1], asgari - son_bas + d_cagri + ANLATIM_SONRASI_SN), 2)
        parcalar.append((cagri, max(asgari, sum(sureler) - d_cagri - ANLATIM_SONRASI_SN)))

    sessiz = Path(video.slaytlardan_reels_uret(dikey_gorseller, fps=30, gecis_suresi=GECIS_SN,
                                              slayt_sureleri=sureler, haberler=haberler))
    anlatim = _anlatim_izi(parcalar, sum(sureler), sessiz.with_name(f"{sessiz.stem}_anlatim.wav")) if parcalar else None
    if sonuc is not None:
        sonuc["anlatim"] = bool(anlatim)
    try:
        cikti = sesli_video_hazirla(sessiz, anlatim, muzik, ayarlar)
    except Exception as e:
        log.warning("Ses miksi başarısız, sessiz videoyla devam: %s", e)
        return sessiz
    for ara in (sessiz, anlatim):
        if ara:
            Path(ara).unlink(missing_ok=True)
    return cikti
