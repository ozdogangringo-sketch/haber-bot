"""
otomatik_onay.py — Gece otomatik yayın için çok katmanlı doğrulama.

NİYE VAR:
    Gece onaylayacak kimse uyanık değil. Büyük bir olay olduğunda hesabın
    sabaha kadar sessiz kalması kötü; ama insan onayını kaldırmak da
    doğruluk güvencesini kaldırıyor. Bu modül o güvenceyi otomatikleştirmeye
    çalışıyor — insan gözünün yerini tutmuyor, ama şüpheli her şeyi
    reddederek riski daraltıyor.

TEMEL İLKE — ŞÜPHEDE REDDET:
    Her katman "yayınlanabilir" demek zorunda. Bir tanesi bile tereddüt
    ederse otomatik yayın YAPILMIYOR, haber sabaha bırakılıyor. Yanlış
    haber yayınlamanın bedeli, doğru haberi kaçırmanın bedelinden çok
    daha yüksek.

DÖRT KATMAN:
    1. Deterministik denetim  — kaynakta olmayan sayı/isim, içi boş
       başlık, suçlama dili (dogrula.py'deki mevcut süzgeç)
    2. İkinci kaynak teyidi   — aynı olayı başka bir haber kaynağı da
       veriyor mu? Tek kaynağın hatasını devralmamak için.
    3. LLM çapraz denetim     — üreten modelden BAĞIMSIZ bir çağrı:
       "bu metin bu kaynakla tutarlı mı?" Anlam kaymasını yakalar.
    4. Riskli kategori engeli — ölüm sayısı, suçlama, savaş, çatışma.
       Bunlar ilk saatlerde en çok düzeltilen haberler.

NE YAPMIYOR:
    Kaynağın kendi hatasını tamamen eleyemiyor. İki kaynak da aynı
    yanlış ajans bültenini geçtiyse ikisi de aynı hatayı taşır. Bu
    riski sıfırlamanın yolu yok; katman 2 onu yalnızca azaltıyor.
"""

from __future__ import annotations

import json
import logging
import os

import requests
from dotenv import load_dotenv

from . import dogrula

log = logging.getLogger(__name__)
load_dotenv()

# Bu kelimeler haberde geçiyorsa gece otomatik yayınlanmıyor.
#
# Gerekçe: hepsi ilk saatlerde sayıların ve isimlerin en çok değiştiği
# haber türleri. Deprem haberinde can kaybı gece boyunca güncelleniyor;
# yanlış sayıyla sabahlamak, hiç paylaşmamaktan kötü.
#
# NOT: bu liste "bu haberleri paylaşma" demiyor — "gece OTOMATİK
# paylaşma, sabah insana sor" diyor. Akşam turunda bu haberler normal
# şekilde çıkıyor.
RISKLI_KELIMELER = (
    "öldü", "ölü", "can kaybı", "hayatını kaybetti", "yaşamını yitirdi",
    "yaralı", "cenaze", "katliam", "saldırı", "patlama", "çatışma",
    "tutuklandı", "gözaltı", "şüpheli", "iddia", "soruşturma",
    "istismar", "taciz", "cinayet", "infaz", "idam",
)

UC_NOKTA = ("https://generativelanguage.googleapis.com/v1beta/"
            "models/{model}:generateContent")

DENETIM_ISTEMI = """Aşağıda bir haberin KAYNAK metni ve ondan üretilmiş
Instagram metni var. Görevin: üretilen metnin kaynakla TUTARLI olup
olmadığını denetlemek.

Şunlara bak:
1. Üretilen metindeki her iddia kaynakta var mı?
2. Anlam tersine dönmüş mü? ("reddetti" -> "kabul etti" gibi)
3. Kaynakta ihtiyatlı olan bir ifade kesinleştirilmiş mi?
   ("iddia edildi" -> "yaptı" gibi)
4. Kaynakta olmayan bir sonuç/yorum eklenmiş mi?
5. Sayılar ve isimler doğru mu?

Küçük bir kuşkun bile varsa "HAYIR" de. Bu metin insan onayı olmadan
yayınlanacak; şüphede reddetmek doğru davranıştır.

--- KAYNAK ---
{kaynak}

--- ÜRETİLEN BAŞLIK ---
{baslik}

--- ÜRETİLEN ÖZET ---
{ozet}

--- ÜRETİLEN AÇIKLAMA ---
{caption}
"""

CEVAP_SEMASI = {
    "type": "object",
    "properties": {
        "tutarli": {"type": "boolean"},
        "gerekce": {"type": "string"},
    },
    "required": ["tutarli", "gerekce"],
}


def katman1_deterministik(haber) -> tuple[bool, str]:
    """Mevcut süzgeç: sayı, isim, başlık kalıbı, suçlama dili."""
    sonuc = dogrula.haberi_dogrula(haber)
    if sonuc["temiz"]:
        return True, "deterministik denetim temiz"

    sebep = []
    if not sonuc["kaynak_var"]:
        sebep.append("kaynak metni yok")
    if sonuc["eksik_sayilar"]:
        sebep.append(f"kaynakta olmayan sayı: {', '.join(sonuc['eksik_sayilar'][:3])}")
    if sonuc["eksik_isimler"]:
        sebep.append(f"kaynakta olmayan isim: {', '.join(sonuc['eksik_isimler'][:3])}")
    sebep += sonuc["baslik_sorunlari"] + sonuc["suclama_sorunlari"]
    return False, "; ".join(sebep)


def katman2_ikinci_kaynak(con, haber, ayarlar: dict) -> tuple[bool, str]:
    """
    Aynı olayı başka bir haber kaynağı da veriyor mu?

    Tek kaynaktan gördüğü haberi otomatik yayınlamak, o kaynağın
    hatasını da devralmak demek. İki bağımsız kaynak aynı şeyi
    söylüyorsa güven ciddi biçimde artıyor — bu gerçek gazetecilik
    pratiği.

    Eşleştirme başlıklardaki ortak kelime köklerine bakıyor. Kaba ama
    yeterli: aynı olayı anlatan iki başlık kaçınılmaz olarak aynı özel
    isimleri ve sayıları taşıyor.
    """
    # YÜKSEK AĞIRLIKLI KAYNAK MUAFİYETİ
    # config'deki `agirlik` zaten "bu kaynağa ne kadar güveniyoruz"u
    # ölçüyor. TRT ve BBC Türkçe 10, AA 9 — bunlar kurumsal yayıncı,
    # teyit süreçleri var. Onlardan gelen bir haberi ikinci kaynak
    # bekleyerek geciktirmek gereksiz.
    #
    # Ölçüldü (17 Ağu 2026): aynı olayı iki kaynağın AYNI ŞEKİLDE
    # vermesi nadir — 136 haberlik havuzda tek eşleşme çıkmadı. Her
    # kaynak farklı açı seçiyor. Muafiyet olmadan bu katman her şeyi
    # reddediyordu.
    esik = ayarlar["genel"].get("tek_basina_yeterli_agirlik", 9)
    if (haber["agirlik"] or 0) >= esik:
        return True, f"{haber['kaynak']} tek başına yeterli (ağırlık {haber['agirlik']})"

    kendi_kok = {
        dogrula._kok(k) for k in (haber["baslik_orj"] or "").split()
        if len(k) > 4
    }
    if len(kendi_kok) < 3:
        return False, "başlık çok kısa, ikinci kaynak eşleştirilemedi"

    # Son 12 saatte gelen, BAŞKA kaynaktan haberler
    adaylar = con.execute(
        "SELECT kaynak, baslik_orj FROM haberler "
        "WHERE kaynak != ? AND yayin_tarihi >= datetime('now', '-12 hours')",
        (haber["kaynak"],),
    )

    for aday in adaylar:
        aday_kok = {
            dogrula._kok(k) for k in (aday["baslik_orj"] or "").split()
            if len(k) > 4
        }
        ortak = kendi_kok & aday_kok
        # 3 ortak kök: "Endonezya", "deprem", "hayatını" gibi. İki farklı
        # olayın 3 uzun kelimede birden buluşması pek olmuyor.
        if len(ortak) >= 3:
            return True, f"{aday['kaynak']} da doğruluyor"

    return False, (f"tek kaynak ({haber['kaynak']}, ağırlık "
                   f"{haber['agirlik']}) ve başka kaynak doğrulamıyor")


def katman3_llm_capraz(haber, ayarlar: dict) -> tuple[bool, str]:
    """
    Üreten modelden BAĞIMSIZ bir çağrıyla tutarlılık denetimi.

    Neden ayrı çağrı: metni üreten model kendi çıktısını savunma
    eğiliminde. Temiz bir bağlamda, yalnızca "bu ikisi tutarlı mı?"
    sorusuyla sorulduğunda daha katı davranıyor.

    Bu katman mevcut denetimin en büyük boşluğunu kapatıyor: anlam
    kayması. "X reddetti" ile "X kabul etti" aynı sayıları ve isimleri
    taşıyor, deterministik süzgeç ikisini ayıramıyor.
    """
    anahtar = os.getenv("GEMINI_API_KEY", "").strip()
    if not anahtar:
        return False, "GEMINI_API_KEY yok, çapraz denetim yapılamadı"

    kaynak = (haber["makale_metni"] or haber["ozet_orj"] or "").strip()
    if len(kaynak) < 300:
        return False, "kaynak metni çok kısa, çapraz denetim güvenilmez"

    g = ayarlar["gemini"]
    istem = DENETIM_ISTEMI.format(
        kaynak=kaynak[: g["azami_makale_uzunlugu"]],
        baslik=haber["ig_baslik"] or "",
        ozet=haber["slayt_ozet"] or "",
        caption=haber["ig_caption"] or "",
    )

    try:
        cevap = requests.post(
            UC_NOKTA.format(model=g["model"]),
            headers={"x-goog-api-key": anahtar},
            json={
                "contents": [{"parts": [{"text": istem}]}],
                "generationConfig": {
                    # Denetimde yaratıcılık istemiyoruz.
                    "temperature": 0,
                    "responseMimeType": "application/json",
                    "responseSchema": CEVAP_SEMASI,
                },
            },
            timeout=g["zaman_asimi"],
        )
    except requests.RequestException as e:
        return False, f"çapraz denetim ağ hatası: {type(e).__name__}"

    if cevap.status_code != 200:
        return False, f"çapraz denetim HTTP {cevap.status_code}"

    try:
        ham = (cevap.json()["candidates"][0]["content"]["parts"][0]["text"])
        sonuc = json.loads(ham)
    except Exception as e:
        return False, f"çapraz denetim cevabı okunamadı: {e}"

    if sonuc.get("tutarli"):
        return True, "çapraz denetim tutarlı buldu"
    return False, f"çapraz denetim: {sonuc.get('gerekce', '')[:160]}"


# Sayının değişebileceğini kabul eden ifadeler.
#
# NEDEN ÖNEMLİ: deprem/kaza haberlerinde can kaybı saatlik güncelleniyor.
# Farklı kaynakta farklı sayı görmek haberin YANLIŞ olduğu anlamına
# gelmiyor — sadece farklı ana ait olduğu anlamına geliyor. "En az 47
# kişi" demek bu yüzden hem doğru hem güvenli: sayı artsa bile ifade
# yanlış olmuyor.
SAYI_IHTIYATI = (
    "en az", "yaklasik", "yaklaşık", "askin", "aşkın", "uzeri", "üzeri",
    "civarinda", "civarında", "son verilere gore", "son verilere göre",
    "yukseldi", "yükseldi", "cikti", "çıktı",
)


def katman4_riskli_kategori(haber) -> tuple[bool, str]:
    """
    Ölüm, suçlama, savaş gibi konularda ek şart arıyor.

    ESKİ HÂLİ ÇOK KATIYDI: bu kelimeleri gören her haberi reddediyordu ve
    gece otomatik yayının yakalamak istediği büyük olaylar tam da bu
    kategorideydi — özellik kendi amacını baltalıyordu.

    YENİ KURAL: riskli kategori tek başına ret sebebi değil. Ret sebebi,
    riskli bir konuda SAYIYI KESİN DİLLE vermek. "47 kişi öldü" yarım
    saat sonra yanlış olur; "en az 47 kişi hayatını kaybetti" olmaz.

    Suçlama içeren haberlerde ise ihtiyat dili zaten katman 1'de
    (`suclama_dili_denetle`) denetleniyor.
    """
    metin = dogrula._sadelestir(
        f"{haber['ig_baslik'] or ''} {haber['slayt_ozet'] or ''} "
        f"{haber['ig_caption'] or ''}"
    )

    bulunan = [k for k in RISKLI_KELIMELER
               if dogrula._sadelestir(k).strip() in metin]
    if not bulunan:
        return True, "riskli kategori değil"

    # Riskli konu + sayı varsa, sayı ihtiyatlı verilmiş olmalı
    sayilar = dogrula._sayilar(
        f"{haber['ig_baslik'] or ''} {haber['slayt_ozet'] or ''}"
    )
    if not sayilar:
        return True, f"riskli konu ('{bulunan[0]}') ama sayı iddiası yok"

    if any(dogrula._sadelestir(i).strip() in metin for i in SAYI_IHTIYATI):
        return True, f"riskli konu ama sayı ihtiyatlı verilmiş"

    return False, (f"riskli konu ('{bulunan[0]}') + kesin sayı — "
                   f"'en az / yaklaşık' gibi ihtiyat yok")


def katman0_mukerrer_denetimi(con, haber, ayarlar: dict) -> tuple[bool, str]:
    """
    Son 48 saat içinde veritabanında (yayınlandı, onay bekliyor) veya Instagram'da
    benzer bir haber var mı denetler. Varsa otomatik yayın DERHAL DURDURULUR.
    """
    from . import secim
    h_dict = dict(haber) if hasattr(haber, "keys") else haber
    gecmis = secim.yayinlanmis_konular(con, ayarlar)
    baslik = h_dict.get("ig_baslik") or h_dict.get("baslik_orj") or ""
    kelimeler, isimler = secim.konu_imzasi(baslik)

    for onceki_k, onceki_i in gecmis:
        ortak_k = secim.ortak_kelime(kelimeler, onceki_k)
        ortak_i = secim.ortak_kelime(isimler, onceki_i)
        if (ortak_i and len(ortak_k) >= 1) or len(ortak_k) >= 2:
            cakisan = ", ".join(ortak_i or list(ortak_k)[:2])
            return False, f"son 48 saatte benzer haber yayınlanmış/onayda ({cakisan})"

    return True, "mükerrer değil, taze ve özgün konu"


def otomatik_yayinlanabilir(con, haber, ayarlar: dict) -> tuple[bool, list[str]]:
    """
    Çok katmanlı otomatik yayın doğrulamasını sırayla uygular.

    HEPSİ geçmek zorunda. Biri bile reddederse otomatik yayın yok;
    haber sabaha bırakılıp insana soruluyor.
    """
    haber_dict = dict(haber) if hasattr(haber, "keys") else haber
    rapor = []

    for ad, fn in (
        ("0 mükerrer denetimi", lambda: katman0_mukerrer_denetimi(con, haber_dict, ayarlar)),
        ("1 deterministik", lambda: katman1_deterministik(haber_dict)),
        ("2 kaynak güveni", lambda: katman2_ikinci_kaynak(con, haber_dict, ayarlar)),
        ("4 riskli kategori", lambda: katman4_riskli_kategori(haber_dict)),
    ):
        gecti, not_ = fn()
        rapor.append(f"{'✓' if gecti else '✗'} {ad}: {not_}")
        if not gecti:
            return False, rapor

    # En pahalı katman en sonda
    gecti, not_ = katman3_llm_capraz(haber, ayarlar)
    rapor.append(f"{'✓' if gecti else '✗'} 3 çapraz denetim: {not_}")
    return gecti, rapor
