"""
okunus.py — Seslendirme metnini Türkçe okunuşa çevirir.

postedm'den taşındı (2026-09-26); iki projede aynı dosya — birinde düzeltilen
bir okuma hatası ötekine de taşınmalı.

NİYE VAR: ElevenLabs yazıyı gördüğü gibi okur. Örnek okumada "1/5000" "bir
bölü beş bin", "0.50" "sıfır nokta elli" olacaktı; başka bir üründe "Hz."
"hezt" diye okundu (doğrusu "Hazreti"). "Av." "av" diye, "3. kat" "üç nokta
kat" diye okunabilir.

KISALTMALAR VE TEK HARFLER OLDUĞU GİBİ KALIR (ölçüldü, 2026-09-26): ElevenLabs
"KDV'li", "SGK'ya", "TBMM'de", "B blok", "D-100"ü doğru okuyor. Harf harf yazmak
bozuyordu: "be blok" → "beblokta", "de yüz" → "da yüz", "ka de veli" → "kadeveliği";
küçük "a" ise yutuluyordu ("Uluslar a Ligi" → "Uluslar Ligi"). Yalnızca açılımı
bilinen kurumlar (İBB, TKGM…) açılır ve okunabilen büyük harfli kelimeler
("YENİ İMAR PLANI") küçültülür.

İNGİLİZCE KISALTMA VE TERİMLER TÜRKÇE FONETİKLE YAZILIR (2026-09-28):
ElevenLabs'a "language_code: tr" verildiği için İngilizce unvan ve terimler
Türkçe harf harf okunuyordu: "CEO" → "ce-o" / "ceosu", "AI" → "a-ı", "Wi-Fi" → "vi-fi",
"online" → "on-li-ne". Bunlar haber spikeri standartlarında fonetik karşılıklarına
çevrilir ("si-i-o'su", "ey-ay", "vay-fay", "onlayn"). Ek uyumu (_ek_uyumu) ile
çekim ekleri yeni köke otomatik uyarlanır ("CEO'ya" → "si-i-o'ya").

Slayttaki metne DOKUNULMAZ; yalnızca sese giden kopya çevrilir.

İLKE — emin olunmayan hiçbir şey çevrilmez: kötü bir okunuş yayını çirkinleştirir,
yanlış bir ANLAM ise sıfır tolerans kuralını bozar. Bu yüzden etiketsiz "142/85"
kesir sayılıp "seksen beşte yüz kırk iki" okunmaz ("yüz kırk iki bölü seksen beş"),
ünlü taşıyan ve okunabilen büyük harfli kelimeler kısaltma sanılıp harf harf
okunmaz ("YOK", "HARÇ", "ŞERH" birer kelimedir).

Sıra önemlidir: noktalı kısaltmalar (Dr., md.) sayılardan, tarih ve saat
ondalıktan, birimler sayıların yazıya dönüşünden ÖNCE çözülür.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Callable, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Sayılar
# ---------------------------------------------------------------------------
_BIRLER = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_ONLAR = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
_BUYUKLER = ["", "bin", "milyon", "milyar", "trilyon"]
_UNLULER = "aıoueiöüâîû"
_KALIN = "aıouâû"
_SERT = "fstkçşhp"
_AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
_KUCUK = "a-zçğıöşüâîû"
_HARF = "A-Za-zÇĞİÖŞÜçğıöşüÂÎÛâîû"


def sayi_yazi(n: int) -> str:
    """Tam sayının Türkçe okunuşu: 1000 → "bin" ("bir bin" değil), 3194 → "üç bin yüz doksan dört"."""
    if n < 0:
        return "eksi " + sayi_yazi(-n)
    if n == 0:
        return "sıfır"
    if n >= 1000 ** len(_BUYUKLER):
        raise ValueError(f"okunamayacak kadar büyük: {n}")
    parcalar: List[str] = []
    grup = 0
    while n:
        n, uc = divmod(n, 1000)
        if uc:
            yuz, on, bir = uc // 100, uc // 10 % 10, uc % 10
            s = []
            if yuz:
                s.append("yüz" if yuz == 1 else f"{_BIRLER[yuz]} yüz")
            if on:
                s.append(_ONLAR[on])
            if bir and not (grup == 1 and uc == 1):
                s.append(_BIRLER[bir])
            if grup:
                s.append(_BUYUKLER[grup])
            parcalar.append(" ".join(s))
        grup += 1
    return " ".join(reversed(parcalar))


def _son_unlu(s: str) -> str:
    return next((c for c in reversed(s.lower()) if c in _UNLULER), "e")


def _dortlu(unlu: str) -> str:
    return {"a": "ı", "ı": "ı", "â": "ı", "o": "u", "u": "u", "û": "u",
            "e": "i", "i": "i", "î": "i", "ö": "ü", "ü": "ü"}[unlu]


def _bulunma_eki(s: str) -> str:
    """-de / -da / -te / -ta: "beş bin" → "de" (beş binde bir), "dört" → "te" (dörtte üç)."""
    return ("t" if s[-1] in _SERT else "d") + ("a" if _son_unlu(s) in _KALIN else "e")


def sira_yazi(n: int) -> str:
    """Sıra sayısı: 8 → "sekizinci", 4 → "dördüncü", 2 → "ikinci"."""
    s = sayi_yazi(n)
    if s.endswith("dört"):
        s = s[:-1] + "d"
    u = _dortlu(_son_unlu(s))
    return s + ("nc" + u if s[-1] in _UNLULER else u + "nc" + u)


def _guvenli(fn: Callable[["re.Match[str]"], str]) -> Callable[["re.Match[str]"], str]:
    """Trilyonun üstündeki sayı çevrilmez, olduğu gibi kalır (uydurulmaz, çökmez)."""
    def sar(m: "re.Match[str]") -> str:
        try:
            return fn(m)
        except ValueError:
            return m[0]
    return sar


def _tam_oku(rakamlar: str) -> str:
    # Baştaki sıfırlar okunur: telefon "0536", ondalık "0,05"
    if len(rakamlar) > 1 and rakamlar.startswith("0"):
        return "sıfır " + _tam_oku(rakamlar[1:])
    return sayi_yazi(int(rakamlar))


def _sayi_oku(belirtec: str) -> str:
    """ "18.000" → on sekiz bin, "0,50" / "0.50" → sıfır virgül elli, "10.000,5" → on bin virgül beş."""
    if "," in belirtec:
        tam, kesir = belirtec.rsplit(",", 1)
        tam = tam.replace(".", "")
    elif "." in belirtec:
        gruplar = belirtec.split(".")
        if len(gruplar) > 1 and gruplar[0][0] != "0" and len(gruplar[0]) <= 3 and all(len(g) == 3 for g in gruplar[1:]):
            return _tam_oku("".join(gruplar))  # Türkçe binlik ayraç
        if len(gruplar) > 2:
            return " nokta ".join(_tam_oku(g) for g in gruplar)
        tam, kesir = gruplar
    else:
        return _tam_oku(belirtec)
    sifirlar = len(kesir) - len(kesir.lstrip("0"))
    kalan = kesir.lstrip("0")
    ondalik = ["sıfır"] * sifirlar + ([sayi_yazi(int(kalan))] if kalan else [])
    return f"{_tam_oku(tam or '0')} virgül {' '.join(ondalik) or 'sıfır'}"


def _ek_uyumu(kok: str, ek: str) -> str:
    """Kökü değişen ekin ünlülerini ve baştaki d/t'sini yeni köke uydurur ("TL'lik" → "liralık")."""
    onceki = _son_unlu(kok)
    son = kok[-1].lower() if kok else "a"
    cikti = []
    for i, c in enumerate(ek):
        if i == 0 and c in "dt":
            c = "t" if son in _SERT else "d"
        if c in "ıiuü":
            c = _dortlu(onceki)
            onceki = c
        elif c in "ae":
            c = "a" if onceki in _KALIN else "e"
            onceki = c
        elif c in _UNLULER:
            onceki = c
        cikti.append(c)
    return "".join(cikti)


# ---------------------------------------------------------------------------
# Kısaltmalar ve harfler
# ---------------------------------------------------------------------------
# (kısaltma, açılım, cümle sonu olabilir mi). Unvan ve adres kısaltmaları cümle
# bitirmez: "Dr. Ahmet"teki nokta cümle sonu değildir.
_NOKTALI: List[Tuple[str, str, bool]] = [
    ("Hz.", "Hazreti", False), ("Dr.", "Doktor", False), ("Av.", "Avukat", False), ("Prof.", "Profesör", False),
    ("Doç.", "Doçent", False), ("Yrd.", "Yardımcı", False), ("Yard.", "Yardımcı", False), ("Uzm.", "Uzman", False),
    ("Müh.", "Mühendis", False), ("Mim.", "Mimar", False), ("Sn.", "Sayın", False), ("Öğr.", "Öğretim", False),
    ("Gör.", "Görevlisi", False), ("Arş.", "Araştırma", False), ("Op.", "Operatör", False),
    ("Mah.", "Mahallesi", False), ("Mh.", "Mahallesi", False), ("Cad.", "Caddesi", False), ("Cd.", "Caddesi", False),
    ("Sok.", "Sokağı", False), ("Sk.", "Sokağı", False), ("Blv.", "Bulvarı", False), ("Bul.", "Bulvarı", False),
    ("Apt.", "Apartmanı", False), ("Ap.", "Apartmanı", False), ("Sit.", "Sitesi", False),
    ("No:", "numara", False), ("No.", "numara", False), ("Tel:", "telefon", False), ("Tel.", "telefon", False),
    ("Md.", "Madde", False), ("md.", "madde", False), ("mad.", "madde", False), ("fık.", "fıkra", False),
    ("A.Ş.", "Anonim Şirketi", True), ("T.C.", "Türkiye Cumhuriyeti", False), ("Ltd.", "Limited", False),
    ("Şti.", "Şirketi", True), ("Tic.", "Ticaret", False), ("San.", "Sanayi", False), ("Müd.", "Müdürlüğü", True),
    ("Bşk.", "Başkanlığı", True), ("Gn.", "Genel", False), ("Bak.", "Bakanlığı", True),
    ("vb.", "ve benzeri", True), ("vs.", "vesaire", True), ("vd.", "ve diğerleri", True), ("bkz.", "bakınız", False),
    ("Bkz.", "Bakınız", False), ("örn.", "örneğin", False), ("Örn.", "Örneğin", False), ("yak.", "yaklaşık", False),
    ("yy.", "yüzyıl", True), ("maks.", "maksimum", True), ("max.", "maksimum", True), ("min.", "minimum", True),
    ("ort.", "ortalama", True), ("Ort.", "Ortalama", False), ("sy.", "sayılı", False),
]

# Harfle okununca anlaşılmayan ya da yanlış okunan kurum/kanun kısaltmaları
_ACILIM = {
    "İBB": "İstanbul Büyükşehir Belediyesi", "TKGM": "Tapu ve Kadastro Genel Müdürlüğü",
    "TMK": "Türk Medeni Kanunu", "TBK": "Türk Borçlar Kanunu", "HMK": "Hukuk Muhakemeleri Kanunu",
    "İİK": "İcra ve İflas Kanunu", "DOP": "düzenleme ortaklık payı", "KOP": "kamu ortaklık payı",
    "TL": "lira", "USD": "dolar", "EUR": "avro", "GBP": "sterlin", "RG": "Resmî Gazete",
    "ABD": "Amerika Birleşik Devletleri",
}

# Büyük harfle yazılmış iki harfli GERÇEK kelimeler: harf harf okunmaz ("VE", "EN")
_IKI_HARFLI_KELIME = {
    "ve", "da", "de", "ki", "mi", "mı", "mu", "mü", "o", "bu", "şu", "en", "az", "ev", "el", "al", "at", "ad",
    "ay", "iş", "iç", "ön", "ok", "on", "ne", "ya", "ye", "un", "ek", "er", "eş", "il", "üç", "su", "oy", "is",
}
# Dört harfe kadar kelimede izin verilen son ünsüz ikilisi: HARÇ, ŞERH, RİSK, MÜLK, TERK
_IZINLI_SON = {"rt", "rk", "st", "sk", "nk", "nt", "lk", "lt", "ls", "rs", "rp", "rç", "nç", "lç", "lp", "ks",
               "ft", "şt", "rz", "rd", "rm", "rh", "nd", "ng", "yt", "yk", "lm", "rf", "rn", "yl", "ym", "yn"}


def _tr_kucuk(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def _okunamaz(kelime: str) -> bool:
    """Büyük harfli belirteç kısaltma mı (KDV, EDM, AVM, EPDK)? Öyleyse küçültülmez."""
    k = _tr_kucuk(kelime)
    if not any(c in _UNLULER for c in k):
        return True
    if re.search(f"[^{_UNLULER}]{{3}}", k):
        return True
    if len(k) == 2 and k not in _IKI_HARFLI_KELIME:
        return True
    if 2 < len(k) <= 4 and k[-1] not in _UNLULER and k[-2] not in _UNLULER and k[-2:] not in _IZINLI_SON:
        return True
    return False


def _buyuk_harfli(m: "re.Match[str]") -> str:
    kok, ek = m.group(1), m.group(2) or ""
    if kok in _ACILIM:
        acilim = _ACILIM[kok]
        return acilim + _ek_uyumu(acilim, ek) if ek else acilim
    if len(kok) == 1 or _okunamaz(kok):
        # Kısaltma ve tek harf: ses doğru okuyor ("KDV'li", "SGK'ya" — kesme işaretiyle ölçüldü)
        return kok + (f"'{ek}" if ek else "")
    return _tr_kucuk(kok) + ek


# ---------------------------------------------------------------------------
# Adımlar
# ---------------------------------------------------------------------------
_BIRIMLER = [  # uzun olan önce: m² "m"den, km "m"den önce
    ("km²", "kilometrekare"), ("km2", "kilometrekare"), ("m²", "metrekare"), ("m2", "metrekare"),
    ("m³", "metreküp"), ("m3", "metreküp"), ("km", "kilometre"), ("cm", "santimetre"), ("mm", "milimetre"),
    ("m", "metre"), ("ha", "hektar"), ("kg", "kilogram"), ("lt", "litre"), ("dk", "dakika"), ("sn", "saniye"),
    ("TL", "lira"), ("₺", "lira"), ("USD", "dolar"), ("$", "dolar"), ("EUR", "avro"), ("€", "avro"),
    ("GBP", "sterlin"), ("£", "sterlin"),
]
_SAYI_BICIMI = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![.\d])|\d+(?:\.\d+){2,}|\d+[.,]\d+|\d+"
_EK = rf"(?:['’]([{_KUCUK}]+))?"
_SIRA_ISIMLERI = r"(?:Kat|Madde|Maddesi|Bölge|Derece|Sınıf|Sıra|Etap|Fıkra|Bent|Ada|Parsel|Hukuk|Asliye|İcra|Noter|Tapu|Yıl|Gün|Ay)"


def _temizle(metin: str) -> str:
    metin = unicodedata.normalize("NFC", metin)
    # Markdown vurgusu ("**Mbappe'nin**", "__not__") okunmaz, duraklama da yaratmaz:
    # son temizlik * ve _'yi virgüle çeviriyordu ("Konuk ekip, Mbappe'nin, …")
    metin = re.sub(r"\*+|(?<![\w])_+|_+(?![\w])", "", metin)
    metin = re.sub(r"https?://\S+", " ", metin)
    metin = re.sub(r"\bwww\.", "", metin)

    def eposta(m: "re.Match[str]") -> str:
        return m.group(1) + " et " + " nokta ".join(m.group(2).split("."))
    metin = re.sub(r"([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)", eposta, metin)

    def alan(m: "re.Match[str]") -> str:
        parcalar = m.group(0).split(".")
        return " nokta ".join("te re" if p == "tr" else p for p in parcalar)
    metin = re.sub(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|gov|edu|info|io|tr)\b", alan, metin)

    temiz = []
    for c in metin:
        kat = unicodedata.category(c)
        if c == "\n":
            temiz.append("\n")
        elif kat[0] == "C" or (kat == "So" and c != "°") or ord(c) > 0xFFFF:
            continue  # U+200B, U+202E, emoji ve süs sembolleri okunmaz
        elif c in "“”„«»\"":
            continue
        elif c == "’":
            temiz.append("'")
        else:
            temiz.append(c)
    # Satır sonları SON TEMİZLİĞE kadar korunur: burada ". " yapılırsa sıra sayısı kuralı
    # satırı aşıyordu ("2026\n%45" → "iki bin yirmi altıncı yüzde…", sabotaj testi)
    return "".join(temiz)


def _kisaltmalar(metin: str) -> str:
    for kisa, acik, cumle_sonu in _NOKTALI:
        desen = re.compile(rf"(?<![{_HARF}]){re.escape(kisa)}(?![{_KUCUK}.])")

        def degistir(m: "re.Match[str]", acik: str = acik, cumle_sonu: bool = cumle_sonu) -> str:
            sonrasi = metin_ref[0][m.end():]
            if cumle_sonu and (not sonrasi.strip() or re.match(r"\s+[A-ZÇĞİÖŞÜ]", sonrasi)):
                return acik + "."
            return acik + (" " if sonrasi[:1].isalnum() else "")
        metin_ref = [metin]
        metin = desen.sub(degistir, metin)
    # "5510 s. Kanun" → sayılı
    metin = re.sub(r"(\d)\s+s\.(?=\s)", r"\1 sayılı", metin)
    # Emlak kısaltmaları
    metin = re.sub(r"(?i)\bh\s*max\b", "azami yükseklik", metin)
    metin = re.sub(rf"(?<![{_HARF}])E\s*[:=]\s*(?=\d)", "emsal ", metin)
    metin = re.sub(rf"(?<![{_HARF}])H\s*[:=]\s*(?=\d)", "yükseklik ", metin)
    return metin


def _ada_parsel(metin: str) -> str:
    # "Ada/Parsel: 142/85" bir kesir DEĞİLDİR
    metin = re.sub(r"(?i)ada\s*[/-]\s*parsel\s*(?:no)?\s*[:.]?\s*(\d+)\s*/\s*(\d+)", r"\1 ada \2 parsel", metin)
    return re.sub(r"(?i)(\d+)\s*/\s*(\d+)\s+ada\s*[/-]\s*parsel", r"\1 ada \2 parsel", metin)


def _tarih_saat(metin: str) -> str:
    def tarih(gun: str, ay: str, yil: str, asil: str) -> str:
        if 1 <= int(ay) <= 12 and 1 <= int(gun) <= 31:
            return f"{int(gun)} {_AYLAR[int(ay) - 1]} {yil}"
        return asil
    metin = re.sub(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b", lambda m: tarih(m[1], m[2], m[3], m[0]), metin)
    metin = re.sub(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lambda m: tarih(m[3], m[2], m[1], m[0]), metin)

    def saat(m: "re.Match[str]") -> str:
        on = m.group("on") or ""
        return f"{on}{int(m['s'])}" + ("" if m["d"] == "00" else f" {int(m['d'])}")
    metin = re.sub(r"\b(?P<on>)(?P<s>[01]?\d|2[0-3]):(?P<d>[0-5]\d)\b", saat, metin)
    metin = re.sub(r"(?i)(?P<on>saat\s+)(?P<s>[01]?\d|2[0-3])\.(?P<d>[0-5]\d)\b", saat, metin)
    # "14.00'te" gibi ek almış saat
    return re.sub(r"\b(?P<on>)(?P<s>1\d|2[0-3]|[1-9])\.(?P<d>[0-5]\d)(?=['’])", saat, metin)


_PARA = {"TL": "lira", "₺": "lira", "lira": "lira", "USD": "dolar", "$": "dolar", "dolar": "dolar",
         "EUR": "avro", "€": "avro", "avro": "avro"}


def _birimler(metin: str) -> str:
    # "18.000 TL/m²'den satıldı" → "metrekaresi on sekiz bin liradan satıldı"; ek para
    # birimine uydurulur ("metrekare başına'den" diye okunuyordu)
    para = "|".join(re.escape(p) for p in _PARA)
    metin = re.sub(rf"({_SAYI_BICIMI})\s*({para})\s*/\s*m[²2](?![0-9]){_EK}",
                   lambda m: f"metrekaresi {m[1]} {_PARA[m[2]]}" + (_ek_uyumu(_PARA[m[2]], m[3]) if m[3] else ""), metin)
    metin = re.sub(rf"\s*/\s*m[²2](?![0-9])(?:['’][{_KUCUK}]+)?", " metrekare başına", metin)
    metin = re.sub(rf"%\s*({_SAYI_BICIMI})", r"yüzde \1", metin)
    metin = re.sub(rf"({_SAYI_BICIMI})\s*%", r"yüzde \1", metin)
    for kisa, acik in _BIRIMLER:
        if not kisa[0].isalnum():  # "₺500", "$500"
            metin = re.sub(rf"{re.escape(kisa)}\s*({_SAYI_BICIMI})", rf"\1 {acik}", metin)
        harf_duyarsiz = "(?i:" + re.escape(kisa) + ")" if kisa.isalpha() and kisa != "m" else re.escape(kisa)
        desen = rf"({_SAYI_BICIMI})\s*{harf_duyarsiz}(?![{_HARF}0-9²³]){_EK}"
        metin = re.sub(desen, lambda m, a=acik: f"{m[1]} {a}" + (_ek_uyumu(a, m[2]) if m[2] else ""), metin)
    return metin


def _kesirler(metin: str) -> str:
    metin = re.sub(r"(\d+)\s*/\s*([A-ZÇĞİÖŞÜ])\b", r"\1 \2", metin)  # "No: 58/A"

    def kesir(m: "re.Match[str]") -> str:
        pay, payda = int(m[1].replace(".", "")), int(m[2].replace(".", ""))
        if pay == 1 and payda == 2:
            return "yarı"  # "ikide bir" deyim olarak "sık sık" demek
        if 0 < pay < payda:
            p = sayi_yazi(payda)
            return f"{p}{_bulunma_eki(p)} {sayi_yazi(pay)}"
        return f"{m[1]} bölü {m[2]}"  # etiketsiz çift: anlamı tahmin edilmez
    sayi = r"(\d{1,3}(?:\.\d{3})+|\d+)"
    kesir = _guvenli(kesir)
    metin = re.sub(rf"(?<![\d.,:]){sayi}\s*:\s*{sayi}(?=\s*ölçek)", kesir, metin)  # "1:5000 ölçekli"
    return re.sub(rf"(?<![\d.,]){sayi}\s*/\s*{sayi}(?![\d,]|\.\d)", kesir, metin)


_ROMEN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}


def _siralar(metin: str) -> str:
    # Yalnızca noktalı ve ardından bir isim gelen Romen rakamı: tek "V" bir harf olabilir
    # Ardından büyük harfli bir isim gelmeli ("II. Etap"): tek harf artık olduğu gibi
    # kaldığı için "X. iki yüz…" gibi bir cümle sonu da Romen rakamı sanılıyordu
    metin = re.sub(rf"(?<![{_HARF}])(X|IX|VIII|VII|VI|V|IV|III|II|I)\.(?=[ \t]+[A-ZÇĞİÖŞÜ])",
                   lambda m: sira_yazi(_ROMEN[m[1]]), metin)
    sira = _guvenli(lambda m: sira_yazi(int(m[1])))
    metin = re.sub(r"\b(\d+)['’](?:inci|ıncı|uncu|üncü|nci|ncı|ncu|ncü)\b", sira, metin)
    # Satır atlamaz ([ \t], \s değil); "D-100." yol kodu sıra sayısı değildir
    return re.sub(rf"(?<![A-ZÇĞİÖŞÜ]-)\b(\d+)\.(?=[ \t]+(?:[{_KUCUK}]|{_SIRA_ISIMLERI}\b))", sira, metin)


def _isaretler_sayi(metin: str) -> str:
    metin = re.sub(r"(\d)\s*\+\s*(\d)", r"\1 artı \2", metin)  # 3+1 daire
    metin = re.sub(r"(\d)\s*[xX×]\s*(\d)", r"\1 çarpı \2", metin)
    metin = re.sub(r"~\s*(?=\d)", "yaklaşık ", metin)
    metin = metin.replace("±", " artı eksi ")
    return re.sub(r"(\d)\s*°", r"\1 derece", metin)


def _sayilar(metin: str) -> str:
    def cevir(m: "re.Match[str]") -> str:
        try:
            okunus = _sayi_oku(m[1])
        except ValueError:
            return m[0]  # trilyonun üstü: rakam bırakılır, uydurulmaz
        ek = m[2] or ""
        if ek and ek[0] in _UNLULER and okunus.endswith("dört"):  # boş ek her dizginin "içinde"dir
            okunus = okunus[:-1] + "d"  # "dörte" değil "dörde"
        return okunus + ek
    # "D-100", "E-5" yol kodu olduğu gibi kalır: ses doğru okuyor, "D yüz" "Kazada 100" oldu (ölçüldü)
    return re.sub(rf"(?<![{_HARF}\d])(?<![A-ZÇĞİÖŞÜ]-)({_SAYI_BICIMI}){_EK}(?![{_HARF}\d])", cevir, metin)


# ---------------------------------------------------------------------------
# İngilizce terimler, unvanlar ve kısaltmalar (Türkçe fonetik okunuş)
# ---------------------------------------------------------------------------
# Türkçe haberlerde sıkça geçen ve doğrudan Türkçe harfleriyle okunduğunda
# ("ceosu", "a-ı", "vi-fi", "on-li-ne") kulağı tırmalayan İngilizce kısaltma,
# unvan ve kelimeler. Doğrudan Türkçe fonetik okunuşa çevrilir.
_C_SUITE_MAP = {
    "CEO": "si-i-o", "CFO": "si-ef-o", "CTO": "si-ti-o", "COO": "si-o-o",
    "CMO": "si-em-o", "CIO": "si-ay-o", "CPO": "si-pi-o", "CSO": "si-es-o",
    "CRO": "si-ar-o",
}

_INGILIZCE_TABLO: List[Tuple[str, str]] = [
    # Markalar ve yapay zeka modelleri
    (rf"(?i)(?<![{_HARF}])ChatGPT(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "çet ci-pi-ti"),
    (rf"(?i)(?<![{_HARF}])OpenAI(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "open ey-ay"),
    (rf"(?i)(?<![{_HARF}])DeepSeek(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "dip siik"),
    (rf"(?i)(?<![{_HARF}])Daily\s+Brief(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "Deyli Brif"),
    (r"(?i)\bUI\s*/\s*UX\b", "yu-ay, yu-eks"),
    # C-Suite unvanlar
    (rf"(?i)(?<![{_HARF}])(CEO|CFO|CTO|COO|CMO|CIO|CPO|CSO|CRO)"
     rf"(?:['’]([{_KUCUK}]+)|(su|sü|ya|ye|nun|nün|da|de|dan|den|lar|ler|luk|lük|yu|yü|"
     rf"suna|süne|sunda|sünde|sundan|sünden|larının|lerinin))?(?![{_HARF}])", "c_suite"),
    # Teknoloji & Kısaltmalar
    (rf"(?i)(?<![{_HARF}])GenAI(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "cen ey-ay"),
    (rf"(?<![{_HARF}])(?:AI|Ai|Aİ|A\.I\.|A\.İ\.)(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "ey-ay"),
    (rf"(?<![{_HARF}])GPU(?:['’]([{_KUCUK}]+)|(lar|ler|yu|yi|da|de))?(?![{_HARF}])", "ci-pi-yu"),
    (rf"(?<![{_HARF}])CPU(?:['’]([{_KUCUK}]+)|(lar|ler|yu|yi|da|de))?(?![{_HARF}])", "si-pi-yu"),
    (rf"(?<![{_HARF}])LLM(?:['’]([{_KUCUK}]+)|(ler|lar|i|e|de|den))?(?![{_HARF}])", "el-el-em"),
    (rf"(?<![{_HARF}])AGI(?:['’]([{_KUCUK}]+)|(ye|ya|de|da))?(?![{_HARF}])", "ey-ci-ay"),
    (rf"(?<![{_HARF}])NFT(?:['’]([{_KUCUK}]+)|(ler|lar|i|e|de|den))?(?![{_HARF}])", "en-ef-ti"),
    (rf"(?<![{_HARF}])VPN(?:['’]([{_KUCUK}]+)|(ler|lar|i|e|de|den))?(?![{_HARF}])", "vi-pi-en"),
    (rf"(?i)(?<![{_HARF}])(?:wi-fi|wifi)(?:['’]([{_KUCUK}]+)|(ya|ye|a|e|da|de|dan|den|ın|in))?(?![{_HARF}])", "vay-fay"),
    (rf"(?<![{_HARF}])(?:API|Api)(?:['’]([{_KUCUK}]+)|(ler|lar|si|sı|ye|ya|de|da))?(?![{_HARF}])", "ey-pi-ay"),
    (rf"(?<![{_HARF}])UI(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "yu-ay"),
    (rf"(?<![{_HARF}])UX(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "yu-eks"),
    (rf"(?<![{_HARF}])IT(?:['’]([{_KUCUK}]+)|(de|da|ye|ya|nin|nin|sektörü|ekibi))?(?![{_HARF}])", "ay-ti"),
    (rf"(?<![{_HARF}])PR(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "pi-ar"),
    (rf"(?<![{_HARF}])HR(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "eyç-ar"),
    (rf"(?i)(?<![{_HARF}])(?:FBI|Fbi)(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "ef-bi-ay"),
    (rf"(?i)(?<![{_HARF}])(?:CIA|Cia)(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "si-ay-ey"),
    (rf"(?i)(?<![{_HARF}])B2B(?![{_HARF}])", "bi-tu-bi"),
    (rf"(?i)(?<![{_HARF}])B2C(?![{_HARF}])", "bi-tu-si"),
    (rf"(?i)(?<![{_HARF}])SpaceX(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "speys-eks"),
    (rf"(?i)(?<![{_HARF}])Microsoft(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "maykrosoft"),
    (rf"(?i)(?<![{_HARF}])Google(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "gugıl"),
    (rf"(?i)(?<![{_HARF}])WhatsApp(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "vatsap"),
    (rf"(?i)(?<![{_HARF}])Netflix(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "netfliks"),
    (rf"(?i)(?<![{_HARF}])PlayStation(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "pleysteyşın"),
    (rf"(?i)(?<![{_HARF}])Xbox(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "iks-boks"),
    (rf"(?i)(?<![{_HARF}])GitHub(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "githab"),
    (rf"(?i)(?<![{_HARF}])benchmark(?:['’]([{_KUCUK}]+)|(ler|lar|i|ı))?(?![{_HARF}])", "bençmark"),
    (rf"(?i)(?<![{_HARF}])open\s+source(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "opın sors"),
    (rf"(?i)(?<![{_HARF}])screenshot(?:['’]([{_KUCUK}]+)|(ler|lar|ı|i))?(?![{_HARF}])", "skrinşat"),
    (rf"(?i)(?<![{_HARF}])livestream(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", "layvstrim"),
    (rf"(?i)(?<![{_HARF}])trailer(?:['’]([{_KUCUK}]+)|(ı|i|ler|lar))?(?![{_HARF}])", "treyler"),
    # Yaygın İngilizce kelimeler
    (rf"(?i)(?<![{_HARF}])online(?:['’]([{_KUCUK}]+)|(da|de|dan|den|a|e|ya|ye))?(?![{_HARF}])", "onlayn"),
    (rf"(?i)(?<![{_HARF}])offline(?:['’]([{_KUCUK}]+)|(da|de|dan|den|a|e|ya|ye))?(?![{_HARF}])", "oflayn"),
    (rf"(?i)(?<![{_HARF}])(?:startup|start-up)(?:['’]([{_KUCUK}]+)|(lar|ler|ı|i|a|e|da|de|dan|den))?(?![{_HARF}])", "startap"),
    (rf"(?i)(?<![{_HARF}])(?:scaleup|scale-up)(?:['’]([{_KUCUK}]+)|(lar|ler|ı|i|a|e|da|de|dan|den))?(?![{_HARF}])", "skeylap"),
    (rf"(?i)(?<![{_HARF}])fintech(?:['’]([{_KUCUK}]+)|(ler|lar|i|ı|e|a|de|da|den|dan))?(?![{_HARF}])", "fintek"),
    (rf"(?i)(?<![{_HARF}])podcast(?:['’]([{_KUCUK}]+)|(ler|lar|i|ı|e|a|de|da|den|dan))?(?![{_HARF}])", "podkast"),
    (rf"(?i)(?<![{_HARF}])streaming(?:['’]([{_KUCUK}]+)|(ler|lar|e|a|de|da))?(?![{_HARF}])", "striming"),
    (rf"(?i)(?<![{_HARF}])briefing(?:['’]([{_KUCUK}]+)|(i|ı|e|a|de|da))?(?![{_HARF}])", "brifing"),
    (rf"(?i)(?<![{_HARF}])developer(?:['’]([{_KUCUK}]+)|(lar|ler|ı|i))?(?![{_HARF}])", "divelopır"),
    (rf"(?i)(?<![{_HARF}])software(?:['’]([{_KUCUK}]+)|(i|ı|e|a|de|da))?(?![{_HARF}])", "softver"),
    (rf"(?i)(?<![{_HARF}])hardware(?:['’]([{_KUCUK}]+)|(i|ı|e|a|de|da))?(?![{_HARF}])", "hardver"),
    (rf"(?i)(?<![{_HARF}])update(?:['’]([{_KUCUK}]+)|(i|ı|e|a|de|da|den|dan|ler|lar))?(?![{_HARF}])", "apdeyt"),
    (rf"(?i)(?<![{_HARF}])upgrade(?:['’]([{_KUCUK}]+)|(i|ı|e|a|de|da|den|dan|ler|lar))?(?![{_HARF}])", "apgreyd"),
    (rf"(?i)(?<![{_HARF}])reels(?:['’]([{_KUCUK}]+)|(i|ı|e|a|de|da|den|dan|ler|lar))?(?![{_HARF}])", "rils"),
    (rf"(?i)(?<![{_HARF}])tweet(?:['’]([{_KUCUK}]+)|(i|ı|e|a|de|da|den|dan|ler|lar))?(?![{_HARF}])", "tivit"),
    (rf"(?i)(?<![{_HARF}])retweet(?:['’]([{_KUCUK}]+)|(i|ı|e|a|de|da|den|dan|ler|lar))?(?![{_HARF}])", "ritivit"),
    (rf"(?i)(?<![{_HARF}])story(?:['’]([{_KUCUK}]+)|(si|ye|ya|de|da|den|dan|ler|lar))?(?![{_HARF}])", "stori"),
    (rf"(?i)(?<![{_HARF}])like(?:['’]([{_KUCUK}]+)|(lar|ler|a|e|da|de))?(?![{_HARF}])", "layk"),
    (rf"(?i)(?<![{_HARF}])dislike(?:['’]([{_KUCUK}]+)|(lar|ler|a|e|da|de))?(?![{_HARF}])", "dislayk"),
    (rf"(?i)(?<![{_HARF}])influencer(?:['’]([{_KUCUK}]+)|(lar|ler|ı|i|a|e|da|de|dan|den))?(?![{_HARF}])", "influensır"),
    (rf"(?i)(?<![{_HARF}])hacker(?:['’]([{_KUCUK}]+)|(lar|ler|ı|i|a|e|da|de|dan|den))?(?![{_HARF}])", "hekır"),
    (rf"(?i)(?<![{_HARF}])fake(?:['’]([{_KUCUK}]+)|(ler|lar|i|ı))?(?![{_HARF}])", "feyk"),
    (rf"(?i)(?<![{_HARF}])workshop(?:['’]([{_KUCUK}]+)|(lar|ler|ı|i|a|e|da|de|dan|den))?(?![{_HARF}])", "vörkşap"),
    (rf"(?i)(?<![{_HARF}])deadline(?:['’]([{_KUCUK}]+)|(ı|i|a|e|da|de|dan|den))?(?![{_HARF}])", "dedlayn"),
    (rf"(?i)(?<![{_HARF}])feedback(?:['’]([{_KUCUK}]+)|(ler|lar|i|ı|e|a|de|da|den|dan))?(?![{_HARF}])", "fidbek"),
    (rf"(?i)(?<![{_HARF}])networking(?:['’]([{_KUCUK}]+)|(e|a|de|da))?(?![{_HARF}])", "netvörking"),
    (rf"(?i)(?<![{_HARF}])deepfake(?:['’]([{_KUCUK}]+)|(ler|lar|i|ı))?(?![{_HARF}])", "dipfeyk"),
    (rf"(?i)(?<![{_HARF}])e-?mail(?:['’]([{_KUCUK}]+)|(i|ı|e|a|de|da|den|dan|ler|lar))?(?![{_HARF}])", "i-meyl"),
]


def _ingilizce_terimler(metin: str) -> str:
    for desen, okunus in _INGILIZCE_TABLO:
        if okunus == "c_suite":
            def cevir_c(m: "re.Match[str]") -> str:
                unvan = m.group(1).upper()
                kok = _C_SUITE_MAP[unvan]
                ek_apostrof = m.group(2)
                ek_duz = m.group(3)
                if ek_apostrof:
                    ek_uyumlu = _ek_uyumu(kok, ek_apostrof)
                    return f"{kok}'{ek_uyumlu}"
                elif ek_duz:
                    ek_uyumlu = _ek_uyumu(kok, ek_duz)
                    return f"{kok}'{ek_uyumlu}"
                return kok
            metin = re.sub(desen, cevir_c, metin)
        else:
            def cevir_genel(m: "re.Match[str]", o: str = okunus) -> str:
                ek_apostrof = m.group(1) if m.re.groups >= 1 else None
                ek_duz = m.group(2) if m.re.groups >= 2 else None
                if ek_apostrof:
                    ek_uyumlu = _ek_uyumu(o, ek_apostrof)
                    return f"{o}'{ek_uyumlu}"
                elif ek_duz:
                    ek_uyumlu = _ek_uyumu(o, ek_duz)
                    return f"{o}{ek_uyumlu}"
                return o
            metin = re.sub(desen, cevir_genel, metin)
    return metin


def _buyuk_harfler(metin: str) -> str:
    return re.sub(rf"(?<![{_HARF}])([A-ZÇĞİÖŞÜ]+)(?:['’]([{_KUCUK}]+))?(?![{_HARF}])", _buyuk_harfli, metin)


_KISALTMA_KOKLERI = frozenset(k.rstrip(".:") for k, _, _ in _NOKTALI)


def _satir_sonu(m: "re.Match[str]") -> str:
    # Satır sonu bir duraktır; noktalama yoksa nokta eklenir ki cümleler birbirine akmasın.
    # Büyük harfli belirteç ("I", "TBMM") ya da noktasız kısaltma kökünden ("Hz", "Dr")
    # sonra VİRGÜL: eklenen nokta onları "Hz."/"I." yapıp kısaltma/Romen rakamı gibi
    # okutuyordu (sabotaj testi: çıktı ikinci kez çevrilince değişiyordu).
    son = m[1]
    return son + (", " if son.isupper() or son in _KISALTMA_KOKLERI else ". ")


def _son_temizlik(metin: str) -> str:
    metin = re.sub(r"([^\s.!?:;,]+)[ \t]*\n+", _satir_sonu, metin)
    metin = re.sub(r"\s*\n+\s*", " ", metin)
    metin = metin.replace("&", " ve ").replace("=", " eşittir ").replace("~", " yaklaşık ").replace("@", " ")
    for simge, okunus in (("km²", "kilometrekare"), ("m²", "metrekare"), ("m³", "metreküp"), ("°", " derece"), ("₺", " lira")):
        # "m²'si" → "metrekaresi": ek kelimeye yapışır, ünlüsü yeni köke uyar
        metin = re.sub(rf"{re.escape(simge)}['’]([{_KUCUK}]+)",
                       lambda m, o=okunus: o.strip() + _ek_uyumu(o.strip(), m[1]), metin)
        metin = metin.replace(simge, okunus)
    metin = re.sub(rf"(?<=[{_HARF}])\s*/\s*(?=[{_HARF}])", ", ", metin)  # "tapu/imar"
    metin = re.sub(r"\s[—–-]{1,2}\s|—|–", ", ", metin)
    metin = re.sub(r"[()\[\]{}|•·→►#*_]", ", ", metin)
    metin = re.sub(r"\s+", " ", metin)
    metin = re.sub(r"\s+([,.;:!?])", r"\1", metin)
    metin = re.sub(r",(\s*,)+", ",", metin)
    metin = re.sub(r",\s*([.;:!?])", r"\1", metin)
    metin = re.sub(r"([.;:!?])\s*,", r"\1", metin)
    metin = re.sub(r"\.{4,}", "...", metin)
    return metin.strip(" ,")


ADIMLAR: List[Callable[[str], str]] = [
    _temizle, _kisaltmalar, _ada_parsel, _tarih_saat, _birimler, _kesirler, _siralar,
    _isaretler_sayi, _sayilar, _ingilizce_terimler, _buyuk_harfler, _son_temizlik,
]


def okunusa_cevir(metin: str) -> str:
    """Seslendirilecek metnin Türkçe okunuşu. Boş ya da metin olmayan girdi boş döner."""
    if not isinstance(metin, str) or not metin.strip():
        return ""
    for adim in ADIMLAR:
        metin = adim(metin)
    return metin


def tek_harfleri_belirginlestir(metin: str) -> str:
    """Sese giderken tek başına duran büyük harfi tırnağa alır: "A Milli Takım" → '"A" Milli Takım'.

    Kullanıcı "A çok hızlı söyleniyor" dedi (2026-09-26). Ölçüldü (kelime zaman damgası,
    3'er deneme): düz "A" 0,02-0,04 sn ve 6'da 4 duyuldu; tırnaklı "A" daha belirgin ve
    6'da 6 duyuldu, cümle birebir okundu. <break> etiketi REDDEDİLDİ: ses cümle başına
    uydurma kelime ekledi ("Ayrıca", "Hatta", "Tacan"); virgül "Uluslararası" okuttu.
    Harf-tire-sayı kodu da: düz "F-16" "F-36"/"fon a…", "D-100" "Kazadei 100" okundu;
    '"F"-16' ve '"D"-100' ikişer denemede doğru. okunusa_cevir'den SONRA çağrılır
    (o tırnakları temizler).
    """
    return re.sub(r"(?<![\w'’\"-])([A-ZÇĞİÖŞÜ])(?=[ \t,.;:!?]|-\d|$)", r'"\1"', metin or "")

