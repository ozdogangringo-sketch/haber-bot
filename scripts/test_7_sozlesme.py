"""
SÖZLEŞME TESTLERİ — "bu koşulda şu olmalı" denetimleri.

NİYE VAR:
    `test_0_butunluk.py` kodun ÇAĞRILABİLİR olduğunu denetliyor:
    fonksiyon var mı, imza uyuyor mu. Ama kodun DOĞRU DAVRANDIĞINI
    denetlemiyor. Bu oturumda çıkan hataların çoğu tam o boşluktaydı:

      * mükerrer engeli üç yerde gerekiyordu, ikisine konmuştu
        (aynı olay bir saat arayla iki kez yayınlandı)
      * `instagram.deneme_sayisi` config'de vardı, kod okumuyordu
      * `TAZELIK_SAAT` sabit koda gömülüydü, config'deki değer ölüydü
      * prompt'un bir kopyası güncellendi, ikincisi unutuldu
      * buton listesi Python'da değişti, Worker'da değişmedi

    Hepsinin ortak deseni: AYNI KURAL BİRDEN FAZLA YERDE YAŞIYOR VE
    BİRİ UNUTULUYOR. Bu testler o unutmayı yakalamak için var.

NE YAPMIYOR:
    Ağa çıkmıyor, gerçek veritabanına DOKUNMUYOR (geçici kopya
    kullanıyor), para harcamıyor. Her değişiklikten sonra
    çalıştırılabilir.

ÇALIŞTIRMA:
    python scripts/test_7_sozlesme.py
"""

import ast
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(KOK / "scripts"))

import yaml                                          # noqa: E402

from src import secim                                # noqa: E402

SONUCLAR: list[tuple[bool, str, str]] = []


def denetle(kosul: bool, ad: str, ayrinti: str = "") -> None:
    SONUCLAR.append((bool(kosul), ad, ayrinti))


# ─────────────────────────────────────────────────────────────
#  1. MÜKERRER ENGELİ — HER AKIŞTA UYGULANMALI
# ─────────────────────────────────────────────────────────────
#
# ⚠️ 20 Ağu 2026: "Rusya'nın Kiev ve Jitomir'e füzeli saldırısı" sabah
# turunda yayınlandı, bir saat sonra "Rus ordusu Kiev'i füzelerle
# vurdu" TEKİL post olarak çıktı. Kural doğruydu ama `aday_bul`'da
# uygulanmıyordu. Bu test o boşluğu yakalar.

def gecici_db() -> sqlite3.Connection:
    """Bellekte test veritabanı — gerçek veriye dokunmaz."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE haberler (
            id INTEGER PRIMARY KEY, kaynak TEXT, kategori TEXT,
            agirlik INTEGER, baslik_orj TEXT, link TEXT, ozet_orj TEXT,
            yayin_tarihi TEXT, cekilme_zamani TEXT, ig_baslik TEXT,
            onem_puani INTEGER, durum TEXT, son_dakika INTEGER,
            gonderim_zamani TEXT, oneri_gonderildi INTEGER DEFAULT 0,
            makale_metni TEXT, tur TEXT
        );
    """)
    return con


def test_mukerrer_engeli() -> None:
    con = gecici_db()
    simdi = datetime.now(timezone.utc)
    # Dün yayınlanmış haber
    con.execute(
        "INSERT INTO haberler (id, kaynak, kategori, agirlik, baslik_orj, "
        "ig_baslik, durum, gonderim_zamani, yayin_tarihi, onem_puani) "
        "VALUES (1,'TRT','turkiye',10,?,?,'yayinlandi',?,?,9)",
        ("Rusya'nın Kiev ve Jitomir'e füzeli saldırısında en az 10 kişi hayatını kaybetti",
         "Rusya'nın Kiev ve Jitomir'e füzeli saldırısında en az 10 kişi hayatını kaybetti",
         (simdi - timedelta(hours=3)).isoformat(),
         (simdi - timedelta(hours=4)).isoformat()))
    con.commit()

    ayarlar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    gecmis = secim.yayinlanmis_konular(con, ayarlar)
    denetle(len(gecmis) == 1, "yayinlanmis_konular yayınlanmış haberi buluyor",
            f"bulunan: {len(gecmis)}")

    # Aynı olayın başka kaynaktan gelen hali elenmeli
    benzer = "Rus ordusu Kiev'i füzelerle vurdu: En az 8 kişi hayatını kaybetti"
    k, i = secim.konu_imzasi(benzer)
    esik = ayarlar["secim"]["gecmis_ortak_kelime_esigi"]
    carpisma = any(len(k & ok) >= esik and (i & oi) for ok, oi in gecmis)
    denetle(carpisma, "aynı olayın farklı kaynaktan hali TEKRAR sayılıyor",
            f"eşik={esik}")

    # Alakasız haber elenmemeli (yanlış pozitif denetimi)
    alakasiz = "İstanbul'da barajların doluluk oranı yüzde 50'nin altına düştü"
    k2, i2 = secim.konu_imzasi(alakasiz)
    yanlis = any(len(k2 & ok) >= esik and (i2 & oi) for ok, oi in gecmis)
    denetle(not yanlis, "alakasız haber YANLIŞLIKLA elenmiyor")
    con.close()


def test_mukerrer_her_akista_var() -> None:
    """
    ⚠️ ASIL DENETİM: kural üç akışta da uygulanıyor mu?

    Kod metnine bakıyoruz — `yayinlanmis_konular` çağrısı aday seçen
    her fonksiyonda geçmeli. 1p'de tam olarak bu eksikti.
    """
    kaynak = (KOK / "scripts" / "son_dakika.py").read_text(encoding="utf-8")
    agac = ast.parse(kaynak)
    beklenen = {"aday_bul", "onerileri_gonder"}
    for dugum in ast.walk(agac):
        if not isinstance(dugum, ast.FunctionDef) or dugum.name not in beklenen:
            continue
        govde = ast.get_source_segment(kaynak, dugum) or ""
        # ⚠️ İKİ KABUL EDİLEBİLİR YOL:
        #   1. `aday.Baglam` kullanmak — kural tek kapıdan geliyor
        #   2. doğrudan `yayinlanmis_konular` çağırmak (eski yol)
        # Aday kapısı tercih edilen; eski yol henüz bağlanmamış
        # akışlar için geçerli kalıyor.
        korumali = ("yayinlanmis_konular" in govde
                    or "aday.Baglam" in govde
                    or "Baglam.kur" in govde)
        denetle(korumali,
                f"{dugum.name}() geçmiş tekrar denetimi yapıyor",
                "aday seçen her akışta gerekli (aday.Baglam ya da "
                "yayinlanmis_konular)")
        beklenen.discard(dugum.name)
    for eksik in beklenen:
        denetle(False, f"{eksik}() bulunamadı", "fonksiyon silinmiş olabilir")

    secim_kaynak = (KOK / "src" / "secim.py").read_text(encoding="utf-8")
    denetle("yayinlanmis_konular(con, ayarlar)" in secim_kaynak,
            "tur_icin_sec() geçmiş tekrar denetimi yapıyor")


# ─────────────────────────────────────────────────────────────
#  2. CONFIG ↔ KOD TUTARLILIĞI
# ─────────────────────────────────────────────────────────────
#
# ⚠️ `instagram.deneme_sayisi` config'de tanımlıydı ama kod onu HİÇ
# okumuyordu (`range(1,4)` sabitti). Ayar değiştirmek hiçbir şeyi
# değiştirmiyordu ve bu ancak elle okuyarak fark edildi.

def test_config_anahtarlari_okunuyor() -> None:
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    tum_kod = "\n".join(
        p.read_text(encoding="utf-8")
        for klasor in ("src", "scripts")
        for p in (KOK / klasor).glob("*.py")
    )

    # Yalnızca ayar bloklarını denetliyoruz; `kaynaklar` liste ve
    # `sosyal.kanallar` gibi veri alanları koda ada göre girmiyor.
    atlanacak = {"kaynaklar", "icerik_filtresi"}
    olu = []
    for blok, icerik in cfg.items():
        if blok in atlanacak or not isinstance(icerik, dict):
            continue
        for anahtar in icerik:
            if not isinstance(anahtar, str):
                continue
            if f'"{anahtar}"' not in tum_kod and f"'{anahtar}'" not in tum_kod:
                olu.append(f"{blok}.{anahtar}")
    denetle(not olu, "config'deki her ayar kod tarafından okunuyor",
            f"ölü ayar: {', '.join(olu)}" if olu else "")


def test_sabit_kodlanmis_esik_yok() -> None:
    """
    ⚠️ `TAZELIK_SAAT = 3` sabit koda gömülüydü ve config'deki değer
    ölüydü; tekil post 5 saat boyunca hiç çıkmadı, sebebi ancak
    ölçerek bulundu.
    """
    kaynak = (KOK / "scripts" / "son_dakika.py").read_text(encoding="utf-8")
    # Eşik/tazelik sabitleri fonksiyon üzerinden okunmalı
    denetle("_tazelik_saat(" in kaynak,
            "tazelik değeri config'den okunuyor (sabit değil)")
    denetle(re.search(r"^TAZELIK_SAAT\s*=\s*\d+", kaynak, re.M) is None,
            "sabit TAZELIK_SAAT tanımı kaldırılmış")


# ─────────────────────────────────────────────────────────────
#  3. AYNI İŞİ YAPAN İKİNCİ KOD YOLU
# ─────────────────────────────────────────────────────────────
#
# ⚠️ En sık tekrarlayan desen. Örnekler: prompt'un iki kopyası,
# Worker ile Python'daki buton listeleri, YAML'daki ham git komutu.

def test_prompt_kopyalari_tutarli() -> None:
    kaynak = (KOK / "src" / "generate_text.py").read_text(encoding="utf-8")
    # Puan bandı hem tam metin hem toplu puanlama promptunda olmalı
    denetle(kaynak.count("9 VERMEKTEN ÇEKİNME") >= 2,
            "puan bandı İKİ prompta da uygulanmış",
            "tam metin + toplu puanlama")
    denetle(kaynak.count("AÇIKLAMA HABERİ İLE OLAY HABERİNİ AYIR") >= 2,
            "açıklama/olay ayrımı İKİ prompta da uygulanmış")


def test_worker_python_buton_uyumu() -> None:
    """
    ⚠️ Buton düzeni iki yerde tanımlı: `telegram_bot.py` ve
    `worker/index.js`. Birini değiştirip diğerini unutmak
    "tanınmayan komut" hatası veriyor.
    """
    worker = (KOK / "worker" / "index.js").read_text(encoding="utf-8")
    tg = (KOK / "src" / "telegram_bot.py").read_text(encoding="utf-8")

    # Python'un ürettiği callback_data'lar Worker tarafından tanınmalı
    uretilen = set(re.findall(r'"callback_data":\s*f?"([a-z_]+)', tg))
    for komut in sorted(uretilen):
        # Parametreli komutlar Worker'da regex ile karşılanıyor
        taniniyor = (f'"{komut}"' in worker
                     or f"{komut}:" in worker
                     or komut in worker)
        denetle(taniniyor, f"worker '{komut}' komutunu tanıyor")


def test_yaml_ham_git_komutu_yok() -> None:
    """
    ⚠️ 1d/1f: `git rebase` YAML'da çıplak kullanılınca `haber.db`
    ikili dosyasında çakışıp repoyu kilitliyordu. Python tarafı
    düzeltilmiş ama YAML'lar unutulmuştu.
    """
    for yol in (KOK / ".github" / "workflows").glob("*.yml"):
        # ⚠️ YORUM SATIRLARINI ATLA. Bu dosyalarda "çıplak git rebase
        # kullanma" UYARISI yorum olarak duruyor; onu ihlal sanmak
        # yanlış pozitif üretiyor (ilk sürümde tam olarak bu oldu).
        satirlar = [s for s in yol.read_text(encoding="utf-8").splitlines()
                    if not s.strip().startswith("#")]
        denetle("git rebase" not in "\n".join(satirlar),
                f"{yol.name}: çıplak 'git rebase' yok",
                "db_kaydet.py kullanılmalı")


# ─────────────────────────────────────────────────────────────
#  4. EŞİK MANTIĞI
# ─────────────────────────────────────────────────────────────

def test_oneri_esigi_yayin_esiginden_dusuk() -> None:
    """
    ⚠️ Toplu başlık puanlaması tam metin puanlamasından ~1.6 puan
    düşük veriyor (ölçüldü). Öneri eşiği yayın eşiğiyle aynı olursa
    hiçbir başlık geçemiyor ve öneri akışı sessizce kilitleniyor.
    """
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    g = cfg["genel"]
    yayin = g.get("son_dakika_kategori_esikleri", {})
    oneri = g.get("oneri_kategori_esikleri", {})
    denetle(bool(oneri), "öneri eşikleri tanımlı")
    for kat, deger in oneri.items():
        y = yayin.get(kat)
        if y is None:
            continue
        denetle(deger < y, f"öneri eşiği ({kat}) yayın eşiğinden düşük",
                f"öneri={deger} yayın={y}")


def test_gece_esigi_gunduzden_yuksek() -> None:
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    g = cfg["genel"]
    gece = g.get("gece_puan_esigi", 9)
    gunduz = g.get("son_dakika_puan_esigi", 8)
    denetle(gece > gunduz, "gece yayın eşiği gündüzden yüksek",
            f"gece={gece} gündüz={gunduz}")


# ─────────────────────────────────────────────────────────────
#  5. INSTAGRAM SINIRLARI
# ─────────────────────────────────────────────────────────────

def test_carousel_siniri() -> None:
    """Instagram carousel sınırı 10 — API dokümanından doğrulandı."""
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    slayt = cfg["gorsel"]["slayt_sayisi"]
    denetle(2 <= slayt <= 10, "slayt sayısı Instagram sınırında (2-10)",
            f"slayt_sayisi={slayt}")



# ─────────────────────────────────────────────────────────────
#  6. ADAY KAPISI — kuralların tek yerde toplanmış hali
# ─────────────────────────────────────────────────────────────
#
# ⚠️ Bu kurallar önce üç ayrı fonksiyona dağılmıştı ve biri hep
# unutuluyordu (1j, 1p). `src/aday.py` hepsini tek kapıya topladı;
# bu testler o kapının her kuralı gerçekten uyguladığını doğruluyor.

def _sahte_haber(**degisiklik) -> dict:
    from datetime import datetime, timedelta, timezone
    temel = {
        "id": 1, "kaynak": "TRT", "kategori": "turkiye", "agirlik": 10,
        "baslik_orj": "Ankara'da metro seferleri yarın sabaha kadar uzatıldı",
        "ig_baslik": "Ankara'da metro seferleri yarın sabaha kadar uzatıldı",
        "onem_puani": 9, "durum": "metin_hazir", "son_dakika": 0,
        "yayin_tarihi": (datetime.now(timezone.utc)
                         - timedelta(hours=1)).isoformat(),
    }
    temel.update(degisiklik)
    return temel


class _SahteSatir(dict):
    """sqlite3.Row gibi davranan sözlük — aday.py `.keys()` kullanıyor."""


def test_aday_kapisi_kurallari() -> None:
    from src import aday

    con = gecici_db()
    ayarlar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    b = aday.Baglam.kur("tekil", ayarlar, con)
    # Gece kuralı testi bozmasın: eşikleri sabitliyoruz
    b.esikler = {"turkiye": 8, "spor": 7}
    b.varsayilan_esik = 8
    b.tazelik_saat = 5
    b.kategori_azami = 3
    b.kategori_sayaci = {}
    b.gecmis_konular = []

    uygun, sebep = aday.uygun_mu(_SahteSatir(_sahte_haber()), b)
    denetle(uygun, "aday kapısı: uygun haber GEÇİYOR", sebep)

    from datetime import datetime, timedelta, timezone
    bayat = _sahte_haber(yayin_tarihi=(datetime.now(timezone.utc)
                                       - timedelta(hours=30)).isoformat())
    uygun, sebep = aday.uygun_mu(_SahteSatir(bayat), b)
    denetle(not uygun and "bayat" in sebep,
            "aday kapısı: BAYAT haber eleniyor", sebep)

    dusuk = _sahte_haber(onem_puani=5)
    uygun, sebep = aday.uygun_mu(_SahteSatir(dusuk), b)
    denetle(not uygun and "puan" in sebep,
            "aday kapısı: EŞİK ALTI eleniyor", sebep)

    b.kategori_sayaci = {"turkiye": 3}
    uygun, sebep = aday.uygun_mu(_SahteSatir(_sahte_haber()), b)
    denetle(not uygun and "kategori" in sebep,
            "aday kapısı: KATEGORİ SINIRI uygulanıyor", sebep)
    b.kategori_sayaci = {}

    # Geçmişte yayınlanmış konu
    gecmis_baslik = "Ankara'da metro seferleri gece boyunca uzatıldı"
    # ⚠️ `konu_imzasi` — üretim kodu da bunu kullanıyor. Test farklı
    # bir imza kullanırsa gerçek davranışı ölçmemiş olur.
    b.gecmis_konular = [secim.konu_imzasi(gecmis_baslik)]
    uygun, sebep = aday.uygun_mu(_SahteSatir(_sahte_haber(onem_puani=8)), b)
    denetle(not uygun and "yayınlandı" in sebep,
            "aday kapısı: GEÇMİŞ TEKRARI eleniyor", sebep)

    # ⚠️ Muafiyet: büyük olay günün özetinde de yer alabilmeli
    uygun, sebep = aday.uygun_mu(_SahteSatir(_sahte_haber(onem_puani=9)), b)
    denetle(uygun, "aday kapısı: 9+ puan geçmiş denetiminden MUAF", sebep)
    b.gecmis_konular = []

    # Liste içi tekrar
    b._secilenler = []
    aday.sec([_SahteSatir(_sahte_haber())], b)
    uygun, sebep = aday.uygun_mu(
        _SahteSatir(_sahte_haber(id=2, onem_puani=8)), b)
    denetle(not uygun and "bu seçimde" in sebep,
            "aday kapısı: AYNI SEÇİMDE tekrar eleniyor", sebep)
    con.close()


def test_aday_baglamlari_farkli_esik() -> None:
    """Üç bağlam farklı eşik kullanmalı; karışırsa akış kilitlenir."""
    from src import aday

    con = gecici_db()
    ayarlar = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    tekil = aday.Baglam.kur("tekil", ayarlar, con)
    oneri = aday.Baglam.kur("oneri", ayarlar, con)

    denetle(oneri.esik("turkiye") < tekil.esik("turkiye"),
            "öneri eşiği tekil post eşiğinden DÜŞÜK",
            f"öneri={oneri.esik('turkiye')} tekil={tekil.esik('turkiye')}")
    denetle(oneri.kategori_azami == tekil.kategori_azami,
            "öneri ve tekil aynı kategori sınırını kullanıyor")

    try:
        aday.Baglam.kur("olmayan_baglam", ayarlar, con)
        denetle(False, "bilinmeyen bağlam REDDEDİLİYOR")
    except ValueError:
        denetle(True, "bilinmeyen bağlam REDDEDİLİYOR")
    con.close()


def main() -> int:
    for test in (
        test_mukerrer_engeli,
        test_mukerrer_her_akista_var,
        test_config_anahtarlari_okunuyor,
        test_sabit_kodlanmis_esik_yok,
        test_prompt_kopyalari_tutarli,
        test_worker_python_buton_uyumu,
        test_yaml_ham_git_komutu_yok,
        test_oneri_esigi_yayin_esiginden_dusuk,
        test_gece_esigi_gunduzden_yuksek,
        test_carousel_siniri,
        test_aday_kapisi_kurallari,
        test_aday_baglamlari_farkli_esik,
    ):
        try:
            test()
        except Exception as e:                        # noqa: BLE001
            denetle(False, f"{test.__name__} PATLADI", f"{type(e).__name__}: {e}")

    print("=" * 70)
    print("SÖZLEŞME TESTLERİ")
    print("=" * 70)
    gecen = [s for s in SONUCLAR if s[0]]
    kalan = [s for s in SONUCLAR if not s[0]]
    for ok, ad, ayrinti in SONUCLAR:
        if not ok:
            print(f"  ✗ {ad}")
            if ayrinti:
                print(f"      {ayrinti}")
    print()
    print(f"  {len(gecen)}/{len(SONUCLAR)} denetim geçti")
    if kalan:
        print(f"  ✗ {len(kalan)} SORUN — yukarıda listelendi")
        return 1
    print("  ✓ Bütün sözleşmeler sağlanıyor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
