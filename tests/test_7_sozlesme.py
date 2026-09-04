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
    # `tur_icin_sec` aday kapısına bağlandı; kural oradan geliyor.
    denetle("aday.Baglam.kur(aday.TUR" in secim_kaynak
            or "yayinlanmis_konular(con, ayarlar)" in secim_kaynak,
            "tur_icin_sec() geçmiş tekrar denetimi yapıyor",
            "aday.Baglam ya da yayinlanmis_konular")


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
        # ⚠️ `tests/` BİLEREK TARANMIYOR (4 Eyl 2026). Bir testin bir
        # config anahtarını anması o ayarı CANLI yapmaz. Testler
        # `scripts/` altındayken tam bu oldu:
        # `haber_gorseli_asgari_genislik/yukseklik` ayarlarını yalnızca
        # `test_gorsel_cesitliligi` okuyordu, üretim kodu hiç bakmıyordu
        # ve bu denetim yıllarca TEMİZ geçti. Testler `tests/`e taşınınca
        # ölü ayarlar ortaya çıktı ve kaldırıldı.
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


def test_planlanmis_yayin_zaman_asimlarindan_muaf() -> None:
    """
    Planlanmış yayın (yayınla > "2 saat sonra") turu yayın anına kadar
    `onay_bekliyor` durumunda bekletiyor. Bu projede turu bekletmeyi
    zaman aşımına bağlayan İKİ ayrı mekanizma var ve ikisi de bu turu
    yayın anı gelmeden öldürebilir:

      * `son_dakika.suresi_gecmisi_iptal_et` — 60 dakikada iptal eder,
        yani "1 saat sonra" planı bile kendini iptal ederdi;
      * `hatirlat.py` — 6 saat sonra havuza döndürür ve o ana kadar
        her saat gereksiz hatırlatma atar.

    ⚠️ Bu denetim tam olarak bu projenin tekrar eden hata sınıfı için
    var: kural doğru yazılıyor ama AYNI İŞİ YAPAN diğer kod yolunda
    unutuluyor (bkz. CLAUDE.md 1j, 1p, 1f).
    """
    for dosya, fonksiyon in (("scripts/son_dakika.py", "60 dakikalık iptal"),
                             ("scripts/hatirlat.py", "6 saatlik kapatma")):
        kaynak = (KOK / dosya).read_text(encoding="utf-8")
        # Turu seçen SELECT'te muafiyet şartı olmalı
        denetle("planlanan_yayin IS NULL" in kaynak,
                f"planlı yayın {fonksiyon} kuralından muaf ({dosya})",
                "planlanan_yayin IS NULL şartı yok — planlanan tur "
                "yayın anı gelmeden havuza döner")

    # Kullanıcıya söylenen PENCERE, kontrolün gerçek aralığından kısa
    # olmamalı — kısa olursa düğme tutamayacağı bir söz verir.
    oi = (KOK / "scripts/onay_isle.py").read_text(encoding="utf-8")
    pencere = re.search(r'timedelta\(minutes=(\d+)\)\):%H:%M\} arasında', oi)
    denetle(bool(pencere), "yayın planı mesajı bir PENCERE söylüyor",
            "tek bir saat söyleniyor — cron atlanınca yalan olur")
    if pencere:
        # son-dakika.yml'deki en büyük gündüz aralığı
        yml = (KOK / ".github/workflows/son-dakika.yml").read_text(encoding="utf-8")
        gunduz = [c for c in re.findall(r'cron:\s*"([^"]+)"', yml)
                  if not re.match(r'^\S+\s+(20|23|2)[,\s]', c)]
        denetle(int(pencere.group(1)) >= 90,
                "söylenen pencere kontrol aralığından kısa değil",
                f"pencere {pencere.group(1)} dk ama cron 90 dakikada bir: {gunduz}")


def test_mukerrer_instagrama_da_bakiyor() -> None:
    """
    Mükerrer denetimi yalnızca veritabanına güvenemez.

    20 Ağu 2026'da ölçüldü: "Merkez Bankası rezervleri" TR 17:47'de,
    "TUFAN Kamikaze İDA" TR 17:19'da Instagram'da yayınlandı ama
    veritabanında ikisinin de hiçbir kaydı 'yayinlandi' değildi ve
    ikisi de akşam turuna yeniden girdi. Aynı turdaki Endonezya haberi
    DB'de doğru kayıtlıydı ve kural onu YAKALADI — yani kural sağlamdı,
    beslendiği veri eksikti.
    """
    kaynak = (KOK / "src/secim.py").read_text(encoding="utf-8")
    denetle("_instagram_gecmisi" in kaynak,
            "mükerrer denetimi Instagram geçmişini de okuyor",
            "yalnızca veritabanına bakıyor — DB bozulursa mükerrer geçer")

    ig = (KOK / "src/instagram.py").read_text(encoding="utf-8")
    denetle("def son_yayinlanan_basliklar" in ig,
            "instagram.son_yayinlanan_basliklar() var")

    # ⚠️ Her post KENDİ içinde değerlendirilmeli. İlk yazımda
    # "numarasız caption'ın ilk satırı manşettir" kuralı global listeye
    # bakıyordu ve ilk posttan sonra tekil postların manşetleri hiç
    # okunmadı — düzeltilen kusur tam olarak buydu.
    denetle("post_basliklari" in ig,
            "caption ayrıştırması post bazında yapılıyor",
            "global listeye bakılıyor: tekil post manşetleri okunmaz")


def test_ertelemede_menu_kaliyor() -> None:
    """
    "1 saat ertele" turu KAPATMIYOR, sadece bekletiyor. Menü kalkarsa
    tur kilitleniyor: ne yayınlanabiliyor ne atlanabiliyor.

    20 Ağu 2026: kullanıcı 20:58'de erteledi, menü silindi, 21:58'de
    gelen hatırlatma "yukarıdaki mesajdan yayınlayabilirsin" dedi ama
    o mesajda hiçbir düğme yoktu.
    """
    kaynak = (KOK / "scripts/onay_isle.py").read_text(encoding="utf-8")
    govde = kaynak.split("def ertele(")[1].split("\ndef ")[0]
    # ⚠️ Docstring'e değil GERÇEK ÇAĞRIYA bak: bu fonksiyonun
    # açıklamasında "sonucu_yaz KULLANMA" uyarısı yazılı ve düz metin
    # araması onu ihlal sanıyordu.
    denetle("telegram_bot.sonucu_yaz(" not in govde,
            "ertele() butonları kaldıran sonucu_yaz'ı ÇAĞIRMIYOR",
            "sonucu_yaz butonları siliyor — ertelenen tur kilitlenir")
    denetle("menuyu_geri_koy" in govde,
            "ertele() menüyü geri koyuyor")


def test_ayri_mesajdaki_dugme_tur_id_tasiyor() -> None:
    """
    Onay mesajından BAŞKA bir mesajda duran her düğme, hedef turun
    id'sini kendi içinde taşımalı.

    Worker düğmeye basıldığında `cb.message.message_id` gönderiyor —
    yani düğmenin BULUNDUĞU mesajın id'sini. Ayrı bir mesajdaki düğme
    için bu değer turu göstermez.

    ⚠️ İKİ KEZ YAŞANDI:
      * `kaldir` (yayın sonucu mesajı) — çözülmüş, id gömülü.
      * `haber_sec` (alternatif mesajı) — 20 Ağu 2026, düğmeye basıldı
        ve job "mesaj_id=487 için haber bulunamadı" ile düştü; tur
        474'tü. Aynı tuzak, yeni kod yolu.
    """
    # ⚠️ BU TUZAK DÖRT KEZ TEKRARLADI: kaldir, haber_sec, gorsel_kabul,
    # gorsel_yeni. Ayrı mesajda duran HER düğme tur id'sini taşımalı.
    tb = (KOK / "src/telegram_bot.py").read_text(encoding="utf-8")
    oi = (KOK / "scripts/onay_isle.py").read_text(encoding="utf-8")
    # (dosya, fonksiyon, komut, callback_data'da bulunması gereken değişken)
    for kaynak, menu, komut, degisken in (
            (tb, "alternatif_menusu", "haber_sec", "tur_mesaj_id"),
            (tb, "alternatif_menusu", "haber_vazgec", "tur_mesaj_id"),
            (tb, "sonucu_yaz", "kaldir", "message_id"),
            (oi, "slayt_islemi", "gorsel_kabul", "mesaj_id"),
            (oi, "slayt_islemi", "gorsel_yeni", "mesaj_id")):
        govde = kaynak.split(f"def {menu}(")[1].split("\ndef ")[0]
        satirlar = [s for s in govde.splitlines() if f"{komut}:" in s]
        denetle(bool(satirlar) and any(degisken in s for s in satirlar),
                f"{menu}(): '{komut}' düğmesi tur mesaj id'sini taşıyor",
                f"callback_data'da {degisken} yok — Worker'ın gönderdiği "
                "mesaj id'si o düğmenin bulunduğu mesaja ait, turu "
                "göstermez")


def test_havuza_donen_haber_metnini_koruyor() -> None:
    """
    Onaylanmayan tur havuza dönerken METNİ OLAN haber 'metin_hazir'
    olmalı, 'yeni' değil.

    'yeni' yapılırsa sonraki tur o haberi Gemini'ye TEKRAR gönderiyor
    ve zaten üretilmiş metin için ikinci kez kota harcanıyor. Ücretsiz
    kota model başına günde 20 istek — bu israf doğrudan turu düşürüyor.

    ⚠️ Kural İKİ YERDE yaşıyor ve biri unutulmuştu: `son_dakika`
    baştan doğru yapıyordu, `hatirlat.py` 20 Ağu 2026'da 10 haberlik
    bir turu 'yeni' yazarak havuza döndürdü.
    """
    for dosya in ("scripts/hatirlat.py", "scripts/son_dakika.py"):
        kaynak = (KOK / dosya).read_text(encoding="utf-8")
        denetle("ig_baslik IS NOT NULL THEN 'metin_hazir'" in kaynak,
                f"havuza dönen haber metnini koruyor ({dosya})",
                "durum düz 'yeni' yapılıyor — üretilmiş metin çöpe "
                "gidiyor ve Gemini kotası ikinci kez harcanıyor")


def test_turkce_ek_toleransi() -> None:
    """
    Mükerrer denetimi düz küme kesişimi kullanamaz — Türkçe sondan
    eklemeli bir dil.

    20 Ağu 2026: aynı PFDK kararının iki haberi tek tura girdi.
      "…çok sayıda kulübe para CEZASI verdi"
      "…Mahmut Uslu'ya 2 milyon 500 bin lira ve kulüplere CEZA"
    Düz kesişimde ortak kelime yalnızca "pfdk" (1) sayıldı, eşik 2.
    """
    from src import secim as _s
    for a, b in (("ceza", "cezası"), ("deprem", "depremde"),
                 ("endonezya", "endonezyada"), ("yangın", "yangını")):
        denetle(_s._ayni_kok(a, b), f"ek toleransı: {a} ~ {b}")
    # Yanlış eşleşme yapmamalı
    for a, b in (("ankara", "antalya"), ("istanbul", "izmir"),
                 ("kara", "deniz")):
        denetle(not _s._ayni_kok(a, b), f"ek toleransı: {a} ≠ {b}",
                "alakasız kelimeler eşleşiyor — tur boşalır")

    # Kural aday kapısında GERÇEKTEN kullanılıyor mu (düz kesişim kalmasın)
    kaynak = (KOK / "src/aday.py").read_text(encoding="utf-8")
    denetle("secim.ortak_kelime(" in kaynak,
            "aday kapısı ek-toleranslı karşılaştırma kullanıyor",
            "düz `&` kesişimi kalmış — Türkçe ekler kaçar")


def test_kategori_uc_yerde_tanimli() -> None:
    """
    Kategori listesi ÜÇ yerde yaşıyor ve üçü de aynı olmalı:
      * `generate_text.KATEGORILER` — modelin seçebileceği değerler,
      * `config → gorsel.serit_renkleri` — slaytın şerit/gradyan rengi,
      * `config → secim.kategori_katsayilari` — ön elemedeki ağırlık.

    ⚠️ Biri eksik kalırsa hata YOK, sessiz hasar var: renk bulunamayan
    kategori "turkiye" rengine düşüyor, katsayısı olmayan kategori
    varsayılan ağırlıkla yarışıyor.
    """
    from src.generate_text import KATEGORILER
    g = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    renkler = set((g.get("gorsel") or {}).get("serit_renkleri", {}))
    katsayilar = set((g.get("secim") or {}).get("kategori_katsayilari", {}))
    kats = set(KATEGORILER)

    denetle(kats <= renkler, "her kategorinin şerit rengi var",
            f"renksiz: {sorted(kats - renkler)} — slayt sessizce "
            "turkiye rengine düşer")
    denetle(kats <= katsayilar, "her kategorinin ön eleme katsayısı var",
            f"katsayısız: {sorted(kats - katsayilar)}")

    # Model şemayı ihlal ederse diye ikinci savunma
    dbk = (KOK / "src/db.py").read_text(encoding="utf-8")
    denetle("_gecerli_kategori" in dbk,
            "kaydetmeden önce kategori beyaz listeden geçiyor",
            "model listede olmayan bir değer üretirse doğrudan yazılır")

    gt = (KOK / "src/generate_text.py").read_text(encoding="utf-8")
    denetle('"kategori": {"type": "string", "enum": KATEGORILER}' in gt,
            "cevap şeması kategoriyi enum ile sınırlıyor")


def test_gecici_hatalar_400te_de_yakalaniyor() -> None:
    """
    Üç dış servis de geçici hatalarını HTTP 400 ile veriyor ve HTTP
    koduna bakmak yetmiyor:
      * Instagram  — 2207003 / 2207052 ("medya indirilemedi")
      * Telegram   — WEBPAGE_CURL_FAILED
      * imgbb      — code 111 "Internal upload error"
      * Threads    — 4279009 "Media Not Found"

    Hepsinde aynı kanıt var: saniyeler sonra aynı istek çalışıyor.
    400'ü kalıcı sayan kod bu isteği HİÇ tekrar denemiyor ve tur/post
    düşüyor. 21 Ağu 2026'da imgbb yüzünden iki tekil post üretilemedi.
    """
    for dosya, isaret in (
            ("src/upload_image.py", "GECICI_MESAJLAR"),
            ("src/telegram_bot.py", "GECICI_MESAJLAR"),
            ("src/instagram.py", "GECICI_ALT_KODLAR"),
            ("src/threads.py", "GECICI_ALT_KODLAR")):
        kaynak = (KOK / dosya).read_text(encoding="utf-8")
        denetle(isaret in kaynak,
                f"{dosya}: 400 ile gelen geçici hatalar tanınıyor",
                "yalnızca HTTP koduna bakılıyor — geçici hata kalıcı "
                "sayılıp hiç tekrar denenmiyor")

    # Threads publish'i yalnızca "Media Not Found"da tekrarlamalı;
    # diğer hatalarda mükerrer gönderi riski var.
    th = (KOK / "src/threads.py").read_text(encoding="utf-8")
    denetle("_medya_yok_mu" in th,
            "Threads publish 'Media Not Found'da taze container ile "
            "tekrar deniyor")


def test_git_degisiklik_yok_yanlis_alarm_vermiyor() -> None:
    """
    "Commit edilecek bir şey yok" durumu HATA DEĞİL.

    Git bunu birden çok cümleyle anlatıyor; koda tek kalıp yazmak
    yanlış alarm veriyordu. 21 Ağu 2026: veritabanı değişmemişti ama
    takip edilmeyen bir bayrak dosyası vardı, git "nothing ADDED to
    commit" dedi, kod "nothing to commit" arıyordu ve job kırmızı oldu.
    """
    from src.db_senkron import _degisiklik_yok
    for cikti in ("nothing to commit, working tree clean",
                  "nothing added to commit but untracked files present",
                  "no changes added to commit"):
        denetle(_degisiklik_yok(cikti), f"'değişiklik yok' tanınıyor: "
                                        f"{cikti[:34]}")
    denetle(not _degisiklik_yok("error: could not write index"),
            "gerçek git hatası 'değişiklik yok' sanılmıyor",
            "gerçek hata yutulursa veri kaybı sessizce geçer")


def test_kosullu_tanimlanan_bayraklar() -> None:
    """
    Bir bayrak koşullu blokta tanımlanıp bloğun DIŞINDA okunuyorsa,
    koşul çalışmadığında `NameError` verir.

    21 Ağu 2026: `th_yarim` (Threads zinciri yarım mı) yalnızca
    `if threadse_de_at and kullanilabilir_mi()` bloğunun içinde
    tanımlanmıştı ve yayın sonucunu yazan satırda okunuyordu. Threads
    kapalı olsaydı BAŞARILI bir yayın kırmızı job'a dönecekti.

    ⚠️ Bütünlük testi bunu göremiyor — kod sözdizimi açısından geçerli,
    hata ancak o dal çalışmadığında ortaya çıkıyor.
    """
    import ast
    kaynak = (KOK / "scripts/onay_isle.py").read_text(encoding="utf-8")
    agac = ast.parse(kaynak)

    for islev in ast.walk(agac):
        if not isinstance(islev, ast.FunctionDef) or islev.name != "yayinla":
            continue
        # Fonksiyon gövdesinin ÜST seviyesinde atanan isimler
        ust_seviye = set()
        for dugum in islev.body:
            if isinstance(dugum, ast.Assign):
                for h in dugum.targets:
                    if isinstance(h, ast.Name):
                        ust_seviye.add(h.id)
        for bayrak in ("th_notu", "th_yarim", "th_gonderi_id"):
            denetle(bayrak in ust_seviye,
                    f"yayinla(): '{bayrak}' koşulsuz tanımlı",
                    "yalnızca if/try içinde atanıyor — o dal "
                    "çalışmazsa NameError")
        return
    denetle(False, "yayinla() fonksiyonu bulundu")


def test_worker_calisiyor() -> None:
    """
    `worker/index.js` üst seviyesi HATASIZ yüklenmeli.

    ⚠️ `node --check` YETMİYOR — o yalnızca sözdizimine bakıyor.
    21 Ağu 2026: bir düzenlemede satır sonları gerçek newline yerine
    literal "\n" olarak yazıldı, `const HABER_SEC = ...` satırı bir
    `//` yorumunun İÇİNDE kaldı ve Worker canlıda
    `ReferenceError: HABER_SEC is not defined` ile 500 döndü.
    Telegram'daki HİÇBİR düğme çalışmadı; sözdizimi ise kusursuzdu.

    Bu test Worker'ı gerçekten yükleyip `eylemMi`'yi çağırıyor.
    """
    import shutil
    import subprocess
    if not shutil.which("node"):
        return                                  # node yoksa atla
    # ⚠️ `export default` SONRASINI KESME — dosyanın %57'si denetimsiz
    # kalıyordu (4 Eyl 2026). `export default` 528. satırda, dosya 1234
    # satır; bütün istek işleyicileri, /yardim metni ve düğme panelleri
    # o bloğun İÇİNDE. Kesince test yalnızca üst yarıyı ayrıştırıyordu.
    #
    # ÖLÇÜLDÜ — gerçek bir hata (JS'te geçersiz, yan yana iki dizgi)
    # 657. satıra kondu ve ÜÇ yöntem denendi:
    #   node --check                          → TEMİZ (kaçırdı)
    #   new Function + kesilmiş kaynak        → TEMİZ (kaçırdı)
    #   new Function + `export default` ataması → HATA (yakaladı)
    # Wrangler/esbuild derlemesi de patlıyordu, yani hata gerçekti.
    #
    # ⚠️ `node --check` BU DOSYADA GÜVENİLMEZ. Tek başına yeterli
    # sanılmasın diye buraya yazıldı; CLAUDE.md'deki eski uyarı
    # ("node --check Worker'ı doğrulamaz") ölçümle daha da güçlendi.
    betik = (
        "const fs=require('fs');"
        "let k=fs.readFileSync(process.argv[1],'utf8');"
        "k=k.replace(/export default/,'const _wd =');"
        "new Function(k+';return eylemMi(\"hazirla:1\");')();"
        "console.log('ok');"
    )
    sonuc = subprocess.run(
        ["node", "-e", betik, str(KOK / "worker/index.js")],
        capture_output=True, text=True, timeout=30)
    denetle(sonuc.returncode == 0 and "ok" in sonuc.stdout,
            "worker/index.js hatasız yükleniyor",
            (sonuc.stderr or "")[:200])

    # Kaçış hatasının doğrudan izi: yorum satırında literal \n
    kod = (KOK / "worker/index.js").read_text(encoding="utf-8")
    bozuk = [s for s in kod.splitlines()
             if s.strip().startswith("//") and "\\n" in s]
    denetle(not bozuk, "Worker'da kaçış hatası kalmamış",
            f"{len(bozuk)} yorum satırında literal \\n var — sonraki "
            "kod satırı yoruma gömülmüş olabilir")


def test_gorsel_cesitliligi() -> None:
    """
    Görsellerin tekdüzeleşmesine karşı iki koruma.

    21 Ağu 2026, kullanıcı: *"görseller çok genel gibi hissettirmeye
    başladı, hep aynı şeyleri kullanıyoruz gibi"*. Ölçüm iki sebep
    buldu:

      1. Haberin KENDİ fotoğrafı boyut eşiğinden tamamen eleniyordu
         (son 14 haberin 14'ü). Eşik 1080x800'dü; haber sitelerinin
         standart OG boyutları 1280x720 ve 1200x630, ikisi de altında.
         Sonuç: her şey Pexels'e düşüyordu.
      2. Aynı Pexels fotoğrafı tekrar tekrar seçiliyordu (aynı
         fotoğrafçı 6, 5 ve 4 kez) — aynı arama hep aynı sonucu
         veriyor ve biz en yüksek puanlıyı alıyorduk.
    """
    # ⚠️ ARTIK CONFIG DEĞİL, GERÇEK KAPI SINANIYOR (4 Eyl 2026).
    # Eski hâli `gorsel.haber_gorseli_asgari_*` ayarlarını okuyordu ama
    # o ayarları ÜRETİM KODU HİÇ OKUMUYORDU — boyut denetimi
    # `gorsel_kalite.gorsel_kalite_denetle`e taşınmıştı. Yani test
    # yaşayan bir kuralı değil, ölü bir ayarı doğruluyordu; testler
    # `scripts/`ten `tests/`e taşınınca "ölü ayar" denetimi yakaladı.
    from PIL import Image
    from src import gorsel_kalite as gk

    def _desenli(gen, yuk):
        # Düz renk Laplacian 0 verir ve netlik testine takılır.
        im = Image.new("RGB", (gen, yuk)); px = im.load()
        for y in range(yuk):
            for x in range(0, gen, 3):
                px[x, y] = (40 + (x * 7) % 200, 90, 150 - (y // 3) % 120)
        return im

    # Haber sitelerinin STANDART OG boyutları geçebilmeli.
    for gen, yuk, ad in ((1280, 720, "16:9"), (1200, 630, "1.91:1"),
                         (1920, 1080, "HD"), (1200, 675, "AA tipik")):
        ok, sebep = gk.gorsel_kalite_denetle(_desenli(gen, yuk), dosya_boyutu_kb=250)
        denetle(ok, f"kalite kapısı {ad} ({gen}x{yuk}) boyutunu geçiriyor",
                f"{sebep} — haber sitelerinin standart boyutu elenirse "
                "her şey Pexels'e düşer (ölçüldü: 14/14 haber)")

    # Büyütme gerektiren küçük fotoğraflar ELENMELİ.
    for gen, yuk in ((864, 486), (640, 360)):
        ok, _ = gk.gorsel_kalite_denetle(_desenli(gen, yuk), dosya_boyutu_kb=120)
        denetle(not ok, f"kalite kapısı küçük fotoğrafı ({gen}x{yuk}) eliyor",
                "büyütme bulanıklaştırır; küçültme kalite kaybettirmez")

    fs = (KOK / "src/fetch_stock.py").read_text(encoding="utf-8")
    denetle("kullanilmis" in fs,
            "Pexels aramasında tekrar engeli var",
            "aynı arama hep aynı fotoğrafı döndürür")
    sl = (KOK / "src/slaytlar.py").read_text(encoding="utf-8")
    denetle("_kullanilmis_stok_idler" in sl,
            "kullanılmış stok id'leri veritabanından okunuyor")


def test_icerik_filtresi() -> None:
    """
    Riskli kelimeler hem caption'da hem SLAYT GÖRSELİNDE yumuşatılmalı.

    21 Ağu 2026: filtre yalnızca caption'da çalışıyordu; slayt
    görselindeki başlık ham hâliyle basılıyordu. Kullanıcı benzer
    hesapların görselin üstünde sansürlediğini gösterip aynısını istedi.

    ⚠️ KISA KÖK YANLIŞ EŞLEŞME YAPAR — ölçüldü:
        "vur" -> v*rgu, v*rgun · "öl" -> ö*çüm · "kan" -> k*nser
    Bu yüzden listedeki her kök, masum bir cümlede hiçbir kelimeyi
    yıldızlamamalı.
    """
    from src import filtre as _f
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    f = cfg.get("icerik_filtresi") or {}
    kokler = f.get("yumusatilacak", [])

    denetle(f.get("gorselde") is True,
            "içerik filtresi slayt görseline de uygulanıyor",
            "yalnızca caption'da çalışıyor")
    sl = (KOK / "src/slaytlar.py").read_text(encoding="utf-8")
    denetle(sl.count("_slayt_metni(haber") >= 4,
            "slayt/story/detay başlıkları filtreden geçiyor",
            "bazı görsel metinleri ham basılıyor")

    # Masum cümlede yanlış eşleşme OLMAMALI
    masum = ("Ölçüm sonucu kanser taraması kanunla kanıtlandı, vurgu "
             "yapıldı, ölçek büyük, kanal açıldı, kararname yayımlandı")
    denetle("*" not in _f.metni_yumusat(masum, kokler),
            "filtre kökleri masum kelimeleri yıldızlamıyor",
            f"yanlış eşleşme: {_f.metni_yumusat(masum, kokler)}")

    # Riskli cümlede eşleşme OLMALI
    riskli = "Eşini vurarak öldürdü, cinayet sonrası ceset bulundu"
    denetle("*" in _f.metni_yumusat(riskli, kokler),
            "filtre riskli kelimeleri yakalıyor")


def test_temizlik_yayinlanmisi_korur() -> None:
    """
    Eski kayıt temizliği YAYINLANMIŞ haberlere dokunmamalı.

    Mükerrer engeli geçmişe bakıyor (`secim.yayinlanmis_konular`);
    yayınlanmış kayıtları silmek 1j/1z'deki "aynı haber ikinci kez
    yayınlandı" sorununu geri getirir.

    21 Ağu 2026'da eklendi: hiç temizlik yoktu, 8 günde 3134 kayıt
    birikti ve `.git` 237 MB'a çıktı (veritabanı her job'da commit
    ediliyor, ikili dosya sıkışmıyor).
    """
    import sqlite3
    from src import db as _db
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE haberler (id INTEGER PRIMARY KEY,
                   durum TEXT, cekilme_zamani TEXT)""")
    con.executemany(
        "INSERT INTO haberler (durum, cekilme_zamani) VALUES (?, ?)",
        [("yayinlandi", "2020-01-01"),      # çok eski AMA yayınlanmış
         ("metin_hazir", "2020-01-01"),     # çok eski, silinmeli
         ("yeni", "2020-01-01"),            # çok eski, silinmeli
         ("metin_hazir", "2099-01-01")])    # taze, kalmalı
    con.commit()
    _db.eski_kayitlari_temizle(con, 7)
    kalan = {r["durum"] for r in con.execute("SELECT durum FROM haberler")}
    denetle("yayinlandi" in kalan,
            "temizlik yayınlanmış haberi KORUYOR",
            "mükerrer engeli geçmişe bakıyor, silmek tekrarı geri getirir")
    denetle(len(list(con.execute(
        "SELECT 1 FROM haberler WHERE cekilme_zamani = '2020-01-01' "
        "AND durum != 'yayinlandi'"))) == 0,
        "temizlik eski yayınlanmamış kayıtları siliyor")
    con.close()


def test_arama_yazim_toleransi() -> None:
    """
    `/haber` araması yazım hatalarını tolere etmeli ama alakasız
    haber getirmemeli.

    21 Ağu 2026: kullanıcı "netenhay" aradı, havuzda 24 Netanyahu
    haberi vardı ve arama "sonuç yok" dedi. Dizi benzerliği yalnızca
    0.59 çıkıyordu çünkü harf SIRASI karışmıştı (hay ↔ yah).
    Harf kümesi ölçütü eklendi (sıradan bağımsız, 0.86).

    ⚠️ Harf kümesi TEK BAŞINA fazla gevşek: ilk denemede "netenhay"
    42 sonuç getirdi ve ilki Netanyahu'yla ilgisizdi. İlk üç harfin
    tutması şartı eklendi.
    """
    import importlib, sys as _s
    _s.path.insert(0, str(KOK / "scripts"))
    oi = importlib.import_module("onay_isle")

    for yanlis, dogru in (("netenhay", "netanyahu"),
                          ("netenyahu", "netanyahu"),
                          ("netanhayu", "netanyahu"),
                          ("erdogann", "erdogan")):
        denetle(oi._yazim_yakin_mi(yanlis, dogru),
                f"yazım toleransı: '{yanlis}' → '{dogru}'",
                "kullanıcı yazım hatası yapınca sonuç bulunamıyor")

    for a, b in (("netenhay", "hayatini"), ("ankara", "antalya"),
                 ("gazze", "gaziantep"), ("israil", "irak")):
        denetle(not oi._yazim_yakin_mi(a, b),
                f"yazım toleransı '{a}' ≠ '{b}'",
                "alakasız haberler sonuçlara karışıyor")

    # ⚠️ SKOR FONKSİYONU BULMA YÖNTEMİYLE AYNI OLMALI.
    # 21 Ağu 2026: fuzzy 24 haber buluyordu ama bir sonraki satır
    # onları TAM EŞLEŞME skoruyla süzüyordu; hepsi 0 alıp eleniyordu
    # ve arama yine "bulunamadı" diyordu. Fuzzy çalışıyordu, sonucunu
    # bir alt satır siliyordu.
    kaynak = (KOK / "scripts/onay_isle.py").read_text(encoding="utf-8")
    govde = kaynak.split("def haber_ara(")[1].split("\ndef ")[0]
    denetle("skorla = _yazim_toleransli_skor if yazim_duzeltildi" in govde,
            "fuzzy sonuçları fuzzy skoruyla süzülüyor",
            "tam eşleşme skoruyla süzülürse fuzzy sonuçları elenir")


def test_gunluk_sinir_gercek_yayini_sayiyor() -> None:
    """
    Günlük tekil post sınırı YAYINLANMIŞ postları saymalı.

    21 Ağu 2026: sayaç haber ONAYA SUNULDUĞUNDA artıyordu. Sayaç 10
    (sınır dolu) görünürken gerçekte 6 post yayınlanmıştı —
    onaylanmayan 4 haber kotayı yemişti. Kullanıcı iki haber seçti,
    job "başarılı" döndü, hiçbir şey üretilmedi ve kimse bir şey
    söylemedi.

    ⚠️ Ayrıca sınır dolduğunda ELLE SEÇİLEN haber muaf olmalı: insan
    bakıp seçtiyse makinenin sessizce reddetmesi yanlış.
    """
    kaynak = (KOK / "scripts/son_dakika.py").read_text(encoding="utf-8")
    govde = kaynak.split("def bugunku_sayi(")[1].split("\ndef ")[0]
    denetle("durum = 'yayinlandi'" in govde,
            "günlük sınır gerçek yayınları sayıyor",
            "ayrı bir sayaç okunuyor — onaylanmayan haber kotayı yer")

    ana = kaynak.split("def main(")[1]
    denetle("if zorla_haber_id:" in ana.split("son_dakika_gunluk_azami")[1][:600],
            "elle seçilen haber günlük sınırdan muaf",
            "kullanıcının açık seçimi sessizce reddediliyor")


def test_etki_dogrulamasi() -> None:
    """
    Kullanıcı komutları DÖNÜŞ DEĞERİNE değil GERÇEK ETKİYE bakmalı.

    21 Ağu 2026'da bugünkü hataların hepsi aynı desendi: kod
    "başarılı" dedi ama iş yapılmadı ve kullanıcıya hiçbir şey
    söylenmedi.
      * `son_dakika.main` günlük sayaç yanlış olduğu için 15 saniyede
        `0` döndü, hiçbir post üretmedi;
      * fuzzy arama 24 sonuç buldu, alt satır hepsini eledi;
      * yayın komutu kuyrukta iptal edildi.

    `oneriyi_hazirla` artık veritabanına bakıyor: haber gerçekten
    `onay_bekliyor` oldu mu ve bir mesaja bağlandı mı?
    """
    kaynak = (KOK / "scripts/onay_isle.py").read_text(encoding="utf-8")
    govde = kaynak.split("def oneriyi_hazirla(")[1].split("\ndef ")[0]
    denetle("gercekten_oldu" in govde,
            "oneriyi_hazirla gerçek etkiyi doğruluyor",
            "yalnızca dönüş değerine bakıyor — sessiz başarısızlık "
            "kullanıcıya 'hazırlanıyor' olarak görünür")
    denetle("durum'] in (\"onay_bekliyor\", \"yayinlandi\")" in govde
            or 'onay_bekliyor' in govde,
            "etki kontrolü haberin durumuna bakıyor")


def test_hatirlatma_tum_turlari_isliyor() -> None:
    """
    Aynı anda birden fazla açık tur olabilir ve HEPSİ işlenmeli.

    21 Ağu 2026: sabah 09:23'te kurulan tur hiç kapanmadı çünkü
    `hatirlat.main` yalnızca `haberler[0]`ın turunu işliyordu. Akşam
    yeni tur kurulunca hatırlatma hep onu görüyor, sabahki tur
    sonsuza kadar açık kalıyordu. Kullanıcı "sırada 20 küsür
    bekliyor" uyarısını böyle aldı (10 + 10 + 1 = 21 haber).
    """
    kaynak = (KOK / "scripts/hatirlat.py").read_text(encoding="utf-8")
    denetle("_turu_isle" in kaynak,
            "hatırlatma her turu ayrı ayrı işliyor",
            "yalnızca ilk tur işleniyor, diğerleri sonsuza kadar açık kalır")
    ana = kaynak.split("def main(")[1]
    denetle("turlar.setdefault" in ana or "for mesaj_id, tur_haberleri" in ana,
            "açık turlar mesaj id'sine göre gruplanıyor")


def test_commons_tukenince_katman_degisiyor() -> None:
    """
    "Başka fotoğraf" düğmesi GERÇEKTEN farklı bir görsel vermeli.

    21 Ağu 2026: kullanıcı "resmi değiştir" dedi ve hep aynı şeyi
    gördü. Ölçüldü — "Melissa Vargas" aramasının Commons'taki bütün
    adayları aynı maçtan geliyordu (Fenerbahçe forması, dosya 1-2-3-4)
    ve modulo ile dönüldüğü için düğme aynı serinin bir sonraki
    karesini veriyordu. Üstelik haber MİLLİ TAKIM haberiydi; kulüp
    forması tutarsız duruyordu.

    Artık birkaç denemeden sonra Commons atlanıyor ve Pexels
    katmanına düşülüyor.
    """
    kaynak = (KOK / "src/fetch_photo.py").read_text(encoding="utf-8")
    denetle("AZAMI_AYNI_KISI" in kaynak,
            "Commons'ta aynı kişi için deneme sınırı var",
            "modulo ile dönülüyor — 'başka dene' aynı seriyi veriyor")
    denetle("atlanacak % len(adaylar)" not in kaynak,
            "Commons adayları modulo ile döngüye sokulmuyor",
            "liste başa dönüyor, katman hiç değişmiyor")


def test_gorsel_kunyesi_zorunlu() -> None:
    """
    Yayınlanan her GERÇEK FOTOĞRAF künyeli olmak zorunda.

    ⚠️ NEDEN GEREKTİ (3 Eyl 2026): 28 Ağustos'ta `fetch_web_image`
    katmanı eklendi ve `arkaplan_sec` içinde atıf yerine boş string
    dönüyordu. Yayınlanan 10 web_haber postunun 10'u da ATIFSIZ ve
    "ARŞİV GÖRSELİ" ibaresi olmadan çıktı — yani fotoğrafın nereden
    geldiği hiçbir yerde kayıtlı değildi ve görsel, olayın belgesiymiş
    gibi duruyordu. Telif şikayeti gelse kaynağı bulmanın yolu yoktu.

    ⚠️ Katman aynı zamanda zincirin BİRİNCİ sırasındaydı — haberin
    kendi og:image'inin bile önünde. og:image konuya garantili bağlı
    (yayıncı o haber için koymuş), internet araması değil. Ölçüldü:
    3 gerçek haberin 3'ünde de yanlış fotoğraf geldi (İran saldırısı
    haberine Fox News'ten Trump portresi).

    Denetim AST ile yapılıyor: düz metin araması `return ... ""`
    kalıbını kaçırıyor, çünkü atıf bir değişkende de gelebilir.
    """
    kaynak = (KOK / "src/slaytlar.py").read_text(encoding="utf-8")
    agac = ast.parse(kaynak)

    fn = next((d for d in ast.walk(agac)
               if isinstance(d, ast.FunctionDef) and d.name == "arkaplan_sec"), None)
    denetle(fn is not None, "arkaplan_sec bulundu")
    if fn is None:
        return

    # `return (gorsel, "katman", atif)` biçimindeki dönüşleri sırayla topla
    donusler = []            # [(katman_adi, atif_bos_mu)]
    for dugum in ast.walk(fn):
        if not isinstance(dugum, ast.Return) or not isinstance(dugum.value, ast.Tuple):
            continue
        ogeler = dugum.value.elts
        if len(ogeler) != 3:
            continue
        katman = ogeler[1]
        if not (isinstance(katman, ast.Constant) and isinstance(katman.value, str)):
            continue
        atif = ogeler[2]
        bos = isinstance(atif, ast.Constant) and atif.value == ""
        donusler.append((katman.value, bos))

    denetle(len(donusler) >= 5,
            "arkaplan_sec katman dönüşleri okunabildi",
            f"yalnızca {len(donusler)} dönüş bulundu")

    # --- 1) Gerçek fotoğraf basan katman ATIFSIZ dönemez ---
    # `ai` ve `gradyan` üretilen görseller — atıf verecek kimse yok.
    kunyesiz_muaf = {"ai", "gradyan"}
    for katman, atif_bos in donusler:
        if katman in kunyesiz_muaf:
            continue
        denetle(not atif_bos,
                f"'{katman}' katmanı atıf döndürüyor",
                "gerçek fotoğraf basan katman boş atıf dönemez — "
                "görselin kaynağı kayıt altına alınmadan yayınlanır")

    # --- 2) İnternet araması og:image'den SONRA gelmeli ---
    sira = [k for k, _ in donusler]
    if "web_haber" in sira and "haber" in sira:
        denetle(sira.index("web_haber") > sira.index("haber"),
                "internet araması og:image katmanından SONRA çalışıyor",
                "internet araması haberin kendi fotoğrafını eziyor — "
                "og:image konuya garantili bağlı, arama değil")

    # --- 3) Doğrulanmamış fotoğraf ARŞİV ibaresi taşımalı ---
    denetle('"web_haber"' in kaynak.split("ARSIV_KATMANLARI")[1][:200]
            if "ARSIV_KATMANLARI" in kaynak else False,
            "web_haber ARSIV_KATMANLARI içinde",
            "internetten aranan fotoğrafın olayın belgesi olduğuna dair "
            "güvencemiz yok; 'ARŞİV GÖRSELİ' ibaresi basılmalı")

    # --- 4) Katman config'den kapatılabilir olmalı ---
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    g = cfg.get("gorsel") or {}
    denetle("web_gorsel_ara" in g,
            "gorsel.web_gorsel_ara config'de tanımlı")
    # ⚠️ DÜZ METİN ARAMASI BURADA YETMİYOR — kasten bozularak ölçüldü:
    # `if g.get("web_gorsel_ara")` şartı silindiğinde test TEMİZ geçti,
    # çünkü aynı dosyadaki `#` yorumunda o kelime hâlâ yazılıydı.
    # AST'de yorumlar HİÇ bulunmuyor, o yüzden gerçek okumayı yalnızca
    # AST görüyor. (Aynı tuzak `test_ertelemede_menu_kaliyor`da da
    # yaşanmıştı: docstring'deki uyarı yanlış alarm veriyordu.)
    okunuyor = any(
        isinstance(d, ast.Constant) and d.value == "web_gorsel_ara"
        for d in ast.walk(agac)
    )
    denetle(okunuyor,
            "slaytlar.py web_gorsel_ara ayarını GERÇEKTEN okuyor",
            "config'de duran ama okunmayan ayar ÖLÜ AYARDIR — "
            "kullanıcı false yapar, katman yine çalışır")


def test_gorsel_brief_dort_yerde_tanimli() -> None:
    """
    Görsel brief alanları DÖRT ayrı yerde yaşıyor; dördü de olmalı.

    ⚠️ BU PROJENİN EN SIK TEKRARLAYAN HATA SINIFI: bir alan şemaya
    eklenir, `metin_kaydet`in SQL'ine eklenmeyi unutulur ve alan
    SESSİZCE HİÇ KAYDEDİLMEZ. Hata vermez — model değeri üretir, kod
    onu atar, veritabanında NULL kalır ve kimse fark etmez.
    (`kategori` alanı üç yerde yaşıyordu ve aynı denetim yazılmıştı.)

    Dört yer:
      1. CEVAP_SEMASI.properties  — model üretsin diye
      2. CEVAP_SEMASI.required    — model ATLAMASIN diye
      3. PROMPT                   — model NE yazacağını bilsin diye
      4. db.EK_KOLONLAR + metin_kaydet SQL — değer SAKLANSIN diye

    3 Eyl 2026'da eklendi (İş 2 — görsel brief).
    """
    sys.path.insert(0, str(KOK))
    from src import generate_text as gt, db as _db

    alanlar = ("gorsel_ozne_tipi", "gorsel_baglam")
    kaydet_kaynak = (KOK / "src/db.py").read_text(encoding="utf-8")

    for alan in alanlar:
        denetle(alan in gt.CEVAP_SEMASI["properties"],
                f"{alan} CEVAP_SEMASI.properties içinde")
        denetle(alan in gt.CEVAP_SEMASI["required"],
                f"{alan} CEVAP_SEMASI.required içinde",
                "required değilse model alanı atlayabilir")
        denetle(alan in gt.PROMPT,
                f"{alan} PROMPT'ta anlatılıyor",
                "şemada olup promptta olmayan alan rastgele dolar")
        denetle(alan in _db.EK_KOLONLAR,
                f"{alan} db.EK_KOLONLAR içinde",
                "kolon yoksa migration çalışmaz")
        # ⚠️ ASIL DENETİM BU: SQL'de gerçekten yazılıyor mu?
        denetle(f"{alan}" in kaydet_kaynak.split("def metin_kaydet")[1][:4000],
                f"{alan} metin_kaydet SQL'inde yazılıyor",
                "şemada var ama kaydedilmiyorsa alan SESSİZCE kaybolur")

    # --- Beyaz liste: şemadaki enum tek başına yetmiyor ---
    denetle(hasattr(_db, "_gecerli_ozne_tipi"),
            "db._gecerli_ozne_tipi beyaz listesi var",
            "model şemayı ihlal edebiliyor; `kategori` alanında da iki "
            "katman gerekmişti")
    if hasattr(_db, "_gecerli_ozne_tipi"):
        denetle(_db._gecerli_ozne_tipi("yok") is None
                and _db._gecerli_ozne_tipi("kisi") == "kisi",
                "beyaz liste tanınmayan değeri eliyor")
        sema_enum = set(gt.CEVAP_SEMASI["properties"]["gorsel_ozne_tipi"]["enum"])
        denetle(sema_enum == set(_db.OZNE_TIPLERI),
                "şema enum'u ile beyaz liste AYNI",
                f"şema={sorted(sema_enum)} beyaz liste={sorted(_db.OZNE_TIPLERI)} "
                "— ayrışırsa geçerli bir değer sessizce elenir")

    # --- Yönlendirme yalnızca Commons'ı atlamalı ---
    sl = (KOK / "src/slaytlar.py").read_text(encoding="utf-8")
    denetle("commons_atla" in sl,
            "slaytlar.py brief'e göre yönlendirme yapıyor")
    agac = ast.parse(sl)
    fn = next((d for d in ast.walk(agac)
               if isinstance(d, ast.FunctionDef) and d.name == "arkaplan_sec"), None)
    if fn is not None:
        govde = ast.get_source_segment(sl, fn) or ""
        # og:image bloğu `commons_atla` ile KOŞULLANMAMALI — yangının
        # haberinde yayıncının koyduğu fotoğraf gerçekten o yangındır.
        og_blok = govde.split("0.5)")[1].split("--- YÖNLENDİRME")[0] if "0.5)" in govde else ""
        denetle("commons_atla" not in og_blok,
                "yönlendirme og:image katmanını ATLAMIYOR",
                "'olay' haberinde bile yayıncının kendi fotoğrafı doğrudur")


def test_foto_ile_yazi_arasinda_olu_bant_yok() -> None:
    """
    Yatay fotoğraf, başlığın başladığı yere KADAR inmeli.

    ⚠️ NEDEN GEREKTİ (3 Eyl 2026, kullanıcı): *"neden yazının çok
    üstünde yatay bir şekilde duruyor resim, ayrık duruyor çok fazla,
    burada açıklamaya kadar resim olurdu"*. Eski kod yatay fotoğrafı
    720px'de kesiyordu, başlık 1140'ta başlıyordu — arada ~420px "ne
    fotoğraf ne yazı" olan ölü bant kalıyordu.

    Dört varyant üretilip yan yana gösterildi (720/1150/1450/1920);
    1150 seçildi. Daha aşağısında zoom kadrajı bozuyor (Fed örneğinde
    madalyon iki yandan kesiliyordu).
    """
    sys.path.insert(0, str(KOK))
    from src import make_image as mi

    # --- 1) Fotoğraf başlık alanına kadar inmeli ---
    denetle(mi.FOTO_HEDEF_ALT >= 1000,
            "yatay fotoğraf başlık alanına kadar iniyor",
            f"FOTO_HEDEF_ALT={mi.FOTO_HEDEF_ALT} — 720'deki eski davranışta "
            "fotoğraf ile yazı arasında ölü bant oluşuyordu")

    # --- 2) Büyütme tavanı olmalı ---
    denetle(hasattr(mi, "FOTO_AZAMI_BUYUTME") and mi.FOTO_AZAMI_BUYUTME <= 2.5,
            "büyütme tavanı var ve makul",
            "tavansız büyütme küçük kaynak fotoğrafı bulanıklaştırır; "
            "bulanık basmaktansa fotoğraf daha kısa dursun")

    # --- 3) Geçiş YUMUŞAK olmalı (smoothstep) ---
    # Kullanıcı isteği: "alt ve üst arasında renkleri bağlayıcı, biraz
    # daha soft geçiş". Smoothstep'in iki ucunda da türev sıfırdır, yani
    # perdenin nerede başlayıp bittiği görünmez. Eski `t**1.8` eğrisinin
    # başlangıcı keskindi.
    maske = mi._perde_maskesi(100, 1000, 200, 800)
    d = [maske.getpixel((50, y)) for y in range(1000)]
    denetle(d[0] == 0 and d[-1] == 255, "perde 0'dan 255'e gidiyor")
    # Uçlarda değişim yavaş, ortada hızlı olmalı
    bas_egim = d[230] - d[210]
    orta_egim = d[510] - d[490]
    denetle(orta_egim > bas_egim * 2,
            "geçiş eğrisi yumuşak (uçlarda yavaş, ortada hızlı)",
            f"başlangıç eğimi={bas_egim} orta eğim={orta_egim} — "
            "keskin başlayan perde fotoğrafın altında çizgi bırakır")
    denetle(abs(d[500] - 127) <= 4,
            "geçiş tam ortada yarı yolda (simetrik)",
            f"orta nokta {d[500]}/255")

    # --- 4) Piksel piksel döngü OLMAMALI ---
    # Eski kod slayt başına 1080x1920 = 2 milyon putpixel çağırıyordu
    # (ölçüldü: 0.78 sn/slayt). Degrade yalnızca Y'ye bağlı.
    #
    # ⚠️ DÜZ METİN ARAMASI OLMAZ — bu oturumda ÜÇÜNCÜ kez yakalandı:
    # fonksiyonun docstring'i "eski kod putpixel çağırıyordu" diye
    # AÇIKLADIĞI için düz arama yanlış alarm verdi. AST'de docstring
    # bir Constant düğümü, çağrı ise Attribute — ikisi karışmaz.
    kaynak = (KOK / "src/make_image.py").read_text(encoding="utf-8")
    fn = next((d for d in ast.walk(ast.parse(kaynak))
               if isinstance(d, ast.FunctionDef) and d.name == "_perde_maskesi"), None)
    denetle(fn is not None, "_perde_maskesi fonksiyonu var")
    if fn is not None:
        cagrilar = {d.attr for d in ast.walk(fn) if isinstance(d, ast.Attribute)}
        denetle("putpixel" not in cagrilar,
                "perde maskesi putpixel döngüsü kullanmıyor",
                "2 milyon Python çağrısı slayt başına ~0.8 sn yiyor")


def test_fotograf_alt_kenari_keskin_degil() -> None:
    """
    Fotoğrafın bittiği yerde KESKİN ÇİZGİ olmamalı.

    ⚠️ NEDEN GEREKTİ (3 Eyl 2026, kullanıcı): *"bazı fotolarda fotoğrafın
    hemen altındaki alan çok keskin bir şekilde bitiyor"*. Büyütme tavanı
    yüzünden küçük kaynaklı fotoğraf erken bitiyor (ör. 450px'lik kaynak
    855'te durur), altında bulanık ambiyans başlıyor ve arada net bir
    çizgi kalıyordu. Perde o noktada henüz şeffaf olduğu için gizlemiyordu.

    Çözüm: göl yansıması — fotoğrafın alt şeridi dikey çevrilip altına
    konuyor, aşağı indikçe soluyor ve bulanıklaşıyor.

    ⚠️ BU TEST KOD METNİNE DEĞİL DAVRANIŞA BAKIYOR. Fonksiyon adı
    değişse, yansıma başka bir yolla yapılsa bile geçerli kalır —
    denetlenen şey "alt kenarda ani sıçrama var mı".
    """
    sys.path.insert(0, str(KOK))
    from PIL import Image
    from src import make_image as mi

    # Büyütme tavanına takılacak KÜÇÜK kaynak: 450 * 1.9 = 855'te biter.
    # Desenli olsun ki yansıma ile düz zemin ayırt edilebilsin.
    kaynak = Image.new("RGB", (760, 450))
    px = kaynak.load()
    for y in range(450):
        for x in range(0, 760, 2):
            px[x, y] = (40 + (x * 7) % 200, 90, 150 - (y // 3) % 120)
    ark = mi.fotograftan_arkaplan(kaynak, 1080, 1920)

    foto_alt = int(450 * mi.FOTO_AZAMI_BUYUTME)         # 855
    def satir_ort(y):
        return sum(sum(ark.getpixel((x, y))) for x in range(0, 1080, 20)) / 54

    # Fotoğrafın son satırı ile hemen altındaki satır arasında
    # ani parlaklık sıçraması olmamalı.
    ust = satir_ort(foto_alt - 3)
    alt = satir_ort(foto_alt + 3)
    sicrama = abs(ust - alt)
    denetle(sicrama < 60,
            "fotoğrafın alt kenarında ani sıçrama yok",
            f"kenarın iki yanı arasında {sicrama:.0f} birimlik fark — "
            "fotoğraf düz bir çizgiyle kesiliyor demektir")

    # Altındaki alan DÜZ RENK olmamalı — yansıma içerik taşımalı.
    bant = [satir_ort(y) for y in range(foto_alt + 10, foto_alt + 160, 10)]
    denetle(max(bant) - min(bant) > 3,
            "fotoğrafın altındaki alan düz renk değil (yansıma var)",
            "yansıma yoksa kenar çizgi gibi durur")

    # Yansıma SONSUZA kadar gitmemeli — metin alanı temiz kalmalı.
    denetle(satir_ort(1700) < satir_ort(foto_alt + 20),
            "yansıma aşağı doğru soluyor",
            "sabit opaklıkta ayna görüntüsü yapay durur ve metni bozar")


def test_kardes_gorsel_havuzu() -> None:
    """
    Aynı olayın DİĞER kaynaklarındaki fotoğraflar da aday olmalı.

    ⚠️ NEDEN GEREKTİ (3 Eyl 2026): her kaynaktan yalnızca TEK aday
    alınıyordu. Ölçüldü — yayınladığımız haber başına ortalama 3.9 ek
    kayıt aynı olayı işliyor ve dağılım şöyle: rutin haberde 0 ek
    kaynak, BÜYÜK OLAYDA 6-12. Yani en çok erişim alan postlarda en çok
    aday boşta duruyordu.

    Ek adayların gerçekten daha iyi olduğu ölçüldü:
      Voleybol : seçilen 1200x675  -> havuzda 5877x3306 vardı (24x piksel)
      Silivri  : seçilen 1200x708  -> havuzda 1280x720

    ⚠️ ÖNCE EŞLEŞTİR, SONRA SIRALA. İlk yazımda sorgu
    `ORDER BY agirlik DESC LIMIT 400` idi — yani önce en yüksek
    ağırlıklı 400 satır alınıp içinde eşleşme aranıyordu ve aynı olayın
    haberleri o dilimin DIŞINDA kalabiliyordu. Bu test tam olarak o
    hatayı yakalar: eşleşen kardeş DÜŞÜK AĞIRLIKLI.
    """
    sys.path.insert(0, str(KOK))
    from src import slaytlar as slayt_mod

    con = gecici_db()
    con.executescript("""
        INSERT INTO haberler (id, kaynak, agirlik, baslik_orj, link, cekilme_zamani)
        VALUES
          -- hedef haber
          (1, 'Borsa Gündem', 5, 'Silivri açıklarında iki Türk gemisi çarpıştı',
           'http://a/1', datetime('now')),
          -- AYNI OLAY, DÜŞÜK ağırlıklı kaynak (ön-limitleme hatasını yakalar)
          (2, 'Küçük Ajans', 1, 'Silivri açıklarında Türk bayraklı 2 gemi çarpıştı',
           'http://b/2', datetime('now')),
          -- AYNI OLAY, yüksek ağırlıklı
          (3, 'Anadolu Ajansı', 10, 'Silivri açıklarında iki gemi çarpıştı, arama sürüyor',
           'http://c/3', datetime('now')),
          -- ⚠️ BAŞKA BİR OLAY ama 3 ORTAK KELİME taşıyor
          -- (açıklarında + gemisi + çarpıştı). Ortak ÖZEL İSİM yok:
          -- hedefte {silivri, türk}, burada {marmara}. Yalnızca kelime
          -- sayan bir denetim bunu kardeş sanar — 1j'deki yanlış pozitif.
          (4, 'TRT Haber', 10, 'Marmara açıklarında yolcu gemisi kayalıklara çarpıştı',
           'http://d/4', datetime('now')),
          -- AYNI OLAY ama ÇOK ESKİ (2 günlük pencere dışında)
          (5, 'AA Dünya', 10, 'Silivri açıklarında iki Türk gemisi çarpıştı',
           'http://e/5', datetime('now', '-5 day'));
    """)
    hedef = con.execute("SELECT * FROM haberler WHERE id = 1").fetchone()
    linkler = slayt_mod.kardes_linkler(con, hedef, azami=5)

    denetle("http://b/2" in linkler,
            "düşük ağırlıklı kardeş de bulunuyor",
            "sorgu ağırlığa göre ÖN-LİMİTLEME yapıyorsa eşleşen kardeşler "
            "o dilimin dışında kalır — Silivri'de 1920x1080 bu yüzden "
            "bulunamamıştı")
    denetle("http://c/3" in linkler, "yüksek ağırlıklı kardeş bulunuyor")
    denetle("http://d/4" not in linkler,
            "alakasız haber kardeş sayılmıyor",
            "ortak özel isim şartı olmadan yanlış pozitif verir (bkz. 1j)")
    denetle("http://e/5" not in linkler,
            "2 günden eski kayıt kardeş sayılmıyor",
            "eski haberin fotoğrafı o olayın güncel karesi değil")
    denetle("http://a/1" not in linkler, "haberin kendisi listeye girmiyor")

    # Sıralama: yüksek ağırlıklı kaynak önce denenmeli (daha büyük foto koyuyor)
    if "http://c/3" in linkler and "http://b/2" in linkler:
        denetle(linkler.index("http://c/3") < linkler.index("http://b/2"),
                "kardeşler ağırlığa göre sıralı deneniyor")

    # Üst sınır olmalı — her aday 0.7-3.8 sn maliyetli
    denetle(slayt_mod.KARDES_AZAMI <= 5,
            "kardeş taraması sınırlı",
            f"KARDES_AZAMI={slayt_mod.KARDES_AZAMI} — sınırsız tarama turu yavaşlatır")
    denetle(len(slayt_mod.kardes_linkler(con, hedef)) <= slayt_mod.KARDES_AZAMI,
            "varsayılan çağrı sınıra uyuyor")

    # `con` zinciri: DB olmadan eski davranış sürmeli, patlamamalı
    denetle(slayt_mod.kardes_linkler(None, hedef) == [],
            "con verilmezse kardeş taraması yapılmıyor (eski davranış)")

    # con dört fonksiyonda da taşınmalı
    import inspect
    for ad in ("arkaplan_sec", "slayt_uret", "tur_uret", "son_dakika_uret"):
        fn = getattr(slayt_mod, ad, None)
        denetle(fn is not None and "con" in inspect.signature(fn).parameters,
                f"{ad} con parametresi taşıyor",
                "zincirin bir halkası con'u düşürürse kardeş havuzu "
                "sessizce devre dışı kalır")


def test_onaylanan_gorsel_videoya_giriyor() -> None:
    """
    Videoda ONAYLANAN görseller kullanılmalı, eski/yeniden üretilen değil.

    ⚠️ NEDEN GEREKTİ (3 Eyl 2026, kullanıcı): *"başka fotolarla yeniden
    üret dedim ve onu paylaştığımda oluşturduğu videoları eski
    görüntülerle oluşturdu"*.

    Kök sebep: `reels_dikey_gorselleri_uret` önce YEREL DOSYAYA bakıyor,
    yoksa slaytı SIFIRDAN üretiyordu — üstelik `gorsel_deneme` okumadan,
    yani "başka fotoğraf" seçimi yok sayılarak. Yayın job'ı ayrı runner'da
    çalışıyor ve `data/output` .gitignore'da olduğu için yerel dosya
    HİÇBİR ZAMAN yoktu; bu yol her seferinde devreye giriyordu.

    Onaylanan imgbb URL'leri ise parametre olarak GELİYOR ama 2. sıradaydı
    ve hiç ulaşılmıyordu.

    ⚠️ Bu, CLAUDE.md'deki "Onaylanan metin ≠ yayınlanan metin" hatasının
    görsel kardeşi: gözden geçirdiğin şey yayına çıkan şey değil.

    Test DAVRANIŞA bakıyor: onaylanan görsel KIRMIZI, yereldeki eski
    dosya MAVİ. Çıkan karenin rengi hangisi?
    """
    sys.path.insert(0, str(KOK))
    import pathlib as _pathlib
    import tempfile
    from PIL import Image
    from src import video

    with tempfile.TemporaryDirectory() as gecici:
        gecici = _pathlib.Path(gecici)
        # Onaylanan görsel — KIRMIZI
        onaylanan = gecici / "onaylanan.jpg"
        Image.new("RGB", (1080, 1920), (220, 30, 30)).save(onaylanan)

        # Yereldeki ESKİ dosya — MAVİ (eski fotoğrafı temsil ediyor)
        h_id = 999777
        video.CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)
        eski_yerel = video.CIKTI_KLASORU / f"story-{h_id}.jpg"
        eski_detay = video.CIKTI_KLASORU / f"story-{h_id}-detay-1.jpg"
        Image.new("RGB", (1080, 1920), (30, 30, 220)).save(eski_yerel)
        Image.new("RGB", (1080, 1920), (30, 30, 220)).save(eski_detay)

        try:
            kareler = video.reels_dikey_gorselleri_uret(
                [str(onaylanan)],
                cikti_dizini=gecici / "kareler",
                haberler=[{"id": h_id, "gorsel_deneme": 2}],
                ayarlar={},
            )
            denetle(len(kareler) >= 1, "video karesi üretildi")
            if kareler:
                r, g_, b = Image.open(kareler[0]).convert("RGB").getpixel((540, 960))
                denetle(r > 150 and b < 100,
                        "video ONAYLANAN görseli kullanıyor",
                        f"kare rengi ({r},{g_},{b}) — mavi ise yereldeki ESKİ "
                        "dosya kullanılmış demektir; kullanıcının onayladığı "
                        "görsel yayına çıkmıyor")
        finally:
            for f in (eski_yerel, eski_detay):
                f.unlink(missing_ok=True)

    # --- SEÇİM TEK KAPIDAN UYGULANMALI ---
    #
    # ⚠️ Slaytı yeniden üreten 20'den fazla çağrı yeri var (URL onarımı,
    # video karesi, metin yenileme, arşiv paylaşımı...). Her birine
    # `atlanacak=` eklemek bir gün unutulur — bu projedeki kusurların
    # çoğu zaten "kural doğru ama bir yerde uygulanmamış" hatası.
    # Bu yüzden seçim `_secimi_uygula` içinde, üretim fonksiyonunun
    # KENDİSİNDE okunuyor.
    from src import slaytlar as slayt_mod2
    denetle(hasattr(slayt_mod2, "_secimi_uygula"),
            "fotoğraf seçimi tek kapıdan uygulanıyor")
    if hasattr(slayt_mod2, "_secimi_uygula"):
        h_secim = {"id": 1, "gorsel_deneme": 2}
        denetle(slayt_mod2._secimi_uygula(h_secim, None, False) == (2, True),
                "çağrı belirtmezse seçim KAYITTAN okunuyor",
                "okunmazsa yeniden üretim orijinal fotoğrafa döner")
        denetle(slayt_mod2._secimi_uygula(h_secim, 5, False) == (5, True),
                "çağıran açıkça belirtirse o kazanır",
                "'başka fotoğraf' düğmesi sayacı artırıp geçiriyor")
        denetle(slayt_mod2._secimi_uygula({"id": 1}, None, False) == (0, False),
                "kolon yoksa/bozuksa güvenli varsayılan",
                "eski kayıtlar bu kolonu taşımıyor")
        import inspect
        for ad in ("slayt_uret", "son_dakika_uret"):
            par = inspect.signature(getattr(slayt_mod2, ad)).parameters["atlanacak"]
            denetle(par.default is None,
                    f"{ad}.atlanacak varsayılanı None (= kayıttan oku)",
                    "varsayılan 0 olursa 'belirtilmedi' ile 'orijinali istiyorum' "
                    "ayırt edilemez ve seçim sessizce yok sayılır")

    # Yeniden üretim yoluna düşülürse `gorsel_deneme` OKUNMALI —
    # yoksa "başka fotoğraf" seçimi yok sayılıp orijinal fotoğraf gelir.
    kaynak = (KOK / "src/video.py").read_text(encoding="utf-8")
    fn = next((d for d in ast.walk(ast.parse(kaynak))
               if isinstance(d, ast.FunctionDef)
               and d.name == "reels_dikey_gorselleri_uret"), None)
    denetle(fn is not None, "reels_dikey_gorselleri_uret bulundu")
    if fn is not None:
        sabitler = {d.value for d in ast.walk(fn)
                    if isinstance(d, ast.Constant) and isinstance(d.value, str)}
        denetle("gorsel_deneme" in sabitler,
                "yeniden üretim gorsel_deneme'yi okuyor",
                "okunmazsa kullanıcının 'başka fotoğraf' seçimi yok sayılır")


def test_vision_denetimi() -> None:
    """
    Görselin İÇİNE bakan denetim doğru katmanlarda ve doğru politikayla.

    ⚠️ NEDEN GEREKTİ (3 Eyl 2026): projedeki bütün doğruluk denetimleri
    METNE bakıyordu (`dogrula.py`). Görsel tarafında ölçülen her şey
    TEKNİKTİ — piksel, netlik, dosya boyutu. "ABD İran'a saldırdı"
    haberine gelen Fox News/Trump portresi 1200x675, keskin ve temizdi;
    teknik testin her sorusuna "evet" dedi.

    ⚠️ METİN TABANLI KAPI ELENDİ: 6 haberin 6'sı geçti (arama kendi
    sonucunu onaylıyordu). Ancak görselin içine bakan bir denetim çözer.

    Canlı ölçüldü, 3/3 doğru:
      Vlahovic + "Beşiktaş forması"  -> "ACF Fiorentina eşofmanı" -> RED
      Vargas + "milli takım forması" -> "Fenerbahçe forması"      -> RED
      Hakan Fidan, bağlam yok                                    -> KABUL
    """
    sys.path.insert(0, str(KOK))
    from src import slaytlar as sm, gorsel_denetim as gd

    # --- 1) Hangi katmanlar denetleniyor ---
    denetle(set(sm.VISION_DENETLENEN) >= {"commons", "web_haber"},
            "belirli kişi/kurum iddiası taşıyan katmanlar denetleniyor")
    denetle("haber" not in sm.VISION_DENETLENEN,
            "og:image Vision denetiminden MUAF",
            "yayıncı o fotoğrafı o haber için koymuş; konuya bağlılığı "
            "yapı gereği garanti, 5 sn harcamaya değmez")
    denetle("pexels" not in sm.VISION_DENETLENEN,
            "Pexels Vision denetiminden MUAF",
            "temsili olduğunu zaten söylüyor ve ARŞİV ibaresi basılıyor")

    # --- 2) Deneme sayısı sınırlı ---
    denetle(sm.VISION_AZAMI_DENEME <= 2,
            "Vision yeniden denemesi sınırlı",
            f"={sm.VISION_AZAMI_DENEME} — Commons adayları çoğu zaman aynı "
            "çekimden geliyor, her deneme ~7 sn yiyor")

    # --- 3) DENETİM YAPILAMAZSA KABUL (ön şart değil, ek güvence) ---
    # Kota dolduğunda/ağ patladığında post görselsiz kalmamalı.
    class _Sahte(dict):
        pass
    sahte = _Sahte({"ig_baslik": "x", "gorsel_konu": "y", "gorsel_baglam": ""})
    eski_fn = gd.gorseli_denetle
    try:
        gd.gorseli_denetle = lambda *a, **k: None          # "soramadık"
        uygun, _ = sm._vision_onayi(None, sahte, {"gorsel": {"vision_denetim": True}})
        denetle(uygun,
                "denetim yapılamazsa fotoğraf KABUL ediliyor",
                "soramadık diye postu görselsiz bırakmak, denetimden "
                "geçmemiş fotoğraf basmaktan kötü")

        gd.gorseli_denetle = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("patladı"))
        uygun, _ = sm._vision_onayi(None, sahte, {"gorsel": {"vision_denetim": True}})
        denetle(uygun, "denetim PATLARSA da fotoğraf kabul ediliyor")

        # --- 4) Net RED kararına uyulmalı ---
        gd.gorseli_denetle = lambda *a, **k: {
            "fotografta_ne_var": "Fiorentina eşofmanı",
            "konuyu_gosteriyor_mu": True, "baglam_uyuyor_mu": False,
            "sebep": "forma uyuşmuyor"}
        uygun, sebep = sm._vision_onayi(None, sahte, {"gorsel": {"vision_denetim": True}})
        denetle(not uygun and "bağlam" in sebep,
                "bağlam uymuyorsa fotoğraf reddediliyor",
                "Vlahovic/Vargas vakalarının çözümü bu")

        gd.gorseli_denetle = lambda *a, **k: {
            "fotografta_ne_var": "kale manzarası",
            "konuyu_gosteriyor_mu": False, "baglam_uyuyor_mu": True,
            "sebep": "alakasız"}
        uygun, _ = sm._vision_onayi(None, sahte, {"gorsel": {"vision_denetim": True}})
        denetle(not uygun, "konuyu göstermiyorsa fotoğraf reddediliyor")

        # --- 5) Config'den kapatılabilmeli ---
        gd.gorseli_denetle = lambda *a, **k: {
            "fotografta_ne_var": "", "konuyu_gosteriyor_mu": False,
            "baglam_uyuyor_mu": False, "sebep": ""}
        uygun, _ = sm._vision_onayi(None, sahte, {"gorsel": {"vision_denetim": False}})
        denetle(uygun, "vision_denetim=false iken denetim çalışmıyor",
                "config'de duran ama okunmayan ayar ÖLÜ AYARDIR")
    finally:
        gd.gorseli_denetle = eski_fn

    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    denetle("vision_denetim" in (cfg.get("gorsel") or {}),
            "gorsel.vision_denetim config'de tanımlı")


def test_db_yazan_workflow_commit_ediyor() -> None:
    """
    Veritabanına yazan her workflow onu COMMIT de etmeli.

    ⚠️ NEDEN GEREKTİ (4 Eyl 2026): `gunluk-rapor.yml` `permissions:
    contents: read` taşıyordu ve `db_kaydet` adımı YOKTU. Ama
    `gunluk_rapor.py` her çalıştığında `db.eski_kayitlari_temizle`
    çağırıyor. Silme runner'ın yerel kopyasında GERÇEKTEN oluyordu,
    log'a "N eski kayıt silindi" yazıyordu — sonra commit edilmediği
    için iş bitince buharlaşıyordu.

    Ölçüldü: config `kayit_saklama_gun: 3` diyor ama veritabanında
    **19 GÜNLÜK** kayıt ve 9107 satır birikmişti. Temizlik açıldığında
    9107 → 2517 satır, 11.5 MB → 3.7 MB (yayınlanmış 277 kaydın hepsi
    korunuyor).

    ⚠️ Bu, CLAUDE.md'deki "SESSİZ BAŞARISIZLIK" desenin ders kitabı
    örneği: kod `0` döndü, log başarı yazdı, iş yapılmadı.
    """
    wf = KOK / ".github/workflows"

    # Veritabanına YAZAN workflow'lar — commit adımı ŞART
    yazanlar = {
        "gunluk-rapor.yml": "eski kayıtları siliyor",
        "hazirla.yml": "tur kuruyor",
        "hatirlat.yml": "tur durumunu değiştiriyor",
        "son-dakika.yml": "öneri/aday işaretliyor",
        "yayinla.yml": "yayın sonucunu yazıyor",
        "piyasa-bulteni.yml": "bülten kaydı yazıyor",
        "haftalik-ozet.yml": "özet kaydı yazıyor",
    }
    for ad, neden in yazanlar.items():
        yol = wf / ad
        if not yol.exists():
            continue
        icerik = yol.read_text(encoding="utf-8")
        # Yorum satırlarını at — uyarı metinleri yanlış alarm veriyor
        kod = "\n".join(l for l in icerik.splitlines()
                         if not l.strip().startswith("#"))
        denetle("db_kaydet" in kod,
                f"{ad} veritabanını commit ediyor",
                f"{neden} ama commit adımı yok — yapılan iş job bitince "
                "buharlaşır ve kimse fark etmez")
        denetle("contents: write" in kod,
                f"{ad} yazma iznine sahip",
                "contents: read ile db_kaydet sessizce başarısız olur")


def test_olu_modul_yok() -> None:
    """
    `src/` altındaki her modül en az bir yerden import edilmeli.

    ⚠️ NEDEN GEREKTİ (4 Eyl 2026): `src/handlers/` bir refactor
    denemesinden kalmıştı — `slayt_yonetimi.py` ve `tur_yonetimi.py`
    içinde **hiç fonksiyon yoktu**, `yayin_yonetimi.py` 158 satırdı ama
    hiçbir yerden import edilmiyordu. Buna rağmen `GEMINI.md` onu
    **tamamlanmış bir mimari** olarak anlatıyordu.

    ⚠️ **ASIL ZARAR KOD DEĞİL, YANLIŞ HARİTA.** Bir hata ararken
    (video eski görsel kullanıyordu) o ölü kopya görülüp "kod
    ikilemesi var" diye YANLIŞ TEŞHİS kondu. Ölü kod yalnızca yer
    kaplamıyor, okuyanı yanlış yöne gönderiyor.

    Aynı taramada `src/x_paylas.py` de (141 satır) ölü bulundu —
    `twitter.py` yerini almıştı.

    ⚠️ TARAMA `n.module`'A DA BAKMALI. Bu denetimin ilk yazımında
    yalnızca `a.name` inceleniyordu ve `from src.komutlar import
    KOMUT_MENUSU` biçimi KAÇIYORDU: `a.name` = "KOMUT_MENUSU", modül
    adı `n.module` içinde. Sonuç: `komutlar` ve `zaman` yanlışlıkla
    "ölü" raporlandı (gerçekte 2 ve 7 yerden kullanılıyorlar).
    **Az kalsın yaşayan iki modül silinecekti.**
    """
    kok_src = KOK / "src"
    moduller = {p.stem for p in kok_src.glob("*.py")} - {"__init__"}
    kullanim = {m: 0 for m in moduller}

    for dosya in (list(kok_src.glob("*.py"))
                  + list((KOK / "scripts").glob("*.py"))
                  + list((KOK / "tests").glob("*.py"))):
        try:
            agac = ast.parse(dosya.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for d in ast.walk(agac):
            adaylar = []
            if isinstance(d, ast.ImportFrom):
                # ⚠️ İKİSİNE DE BAK — yukarıdaki uyarıya bakınız.
                if d.module:
                    adaylar.append(d.module.split(".")[-1])
                adaylar += [a.name.split(".")[-1] for a in d.names]
            elif isinstance(d, ast.Import):
                adaylar += [a.name.split(".")[-1] for a in d.names]
            for ad in adaylar:
                if ad in kullanim and dosya.stem != ad:
                    kullanim[ad] += 1

    olu = sorted(m for m, c in kullanim.items() if c == 0)
    denetle(not olu,
            "src/ altında ölü modül yok",
            f"hiçbir yerden import edilmeyen: {olu} — ölü kod okuyanı "
            "yanlış yöne gönderir (bkz. handlers/ vakası)")

    # Taramanın kendisi çalışıyor mu? Bilinen canlı modüller görülmeli.
    for canli in ("db", "komutlar", "zaman"):
        if canli in kullanim:
            denetle(kullanim[canli] > 0,
                    f"tarama '{canli}' modülünü canlı görüyor",
                    "tarama bozuksa YAŞAYAN modülü ölü sanıp sildirir")


def test_yazilan_durum_dosyasi_okunuyor() -> None:
    """
    `data/` altına YAZILAN her durum dosyası bir yerde OKUNMALI.

    ⚠️ NEDEN GEREKTİ (4 Eyl 2026): `data/hata_kayitlari.jsonl`
    23 Ağustos'tan beri yazılıyordu ama **hiçbir kod okumuyordu**.
    `hata_bildir.KATALOG` ile eşleştirilmiş teşhis (ne oldu / neden)
    orada birikiyor, kimse bakmıyordu. **Yazılıp okunmayan kayıt, hiç
    tutulmamış kayıttan kötüdür** — yer kaplar ve "kaydediliyor" diye
    yanlış güven verir. Günlük rapora son 24 saatin özeti eklendi.

    Aynı taramada `data/tiktok_pkce_verifier.txt` bulundu: tek seferlik
    OAuth akışının geçici artığı, hiçbir kod okumuyor ve **git'te
    duruyordu**. Silindi, `.gitignore`'a kondu.
    """
    kaynaklar = ""
    for klasor in ("src", "scripts"):
        for dosya in (KOK / klasor).glob("*.py"):
            kaynaklar += dosya.read_text(encoding="utf-8")

    # Yazan modülden BAŞKA bir yerde de geçmeli
    from src import hata_bildir
    denetle(hasattr(hata_bildir, "HATA_LOG_YOLU"),
            "hata günlüğü yolu tanımlı")

    rapor = (KOK / "scripts/gunluk_rapor.py").read_text(encoding="utf-8")
    denetle("HATA_LOG_YOLU" in rapor,
            "teşhisli hata günlüğü günlük raporda OKUNUYOR",
            "yazılıp okunmayan kayıt, hiç tutulmamış kayıttan kötüdür")

    # ⚠️ Okuma kodu GERÇEKTEN çalışıyor mu? Sadece adı geçmesi yetmez —
    # ilk yazımda `json` import edilmemişti ve geniş bir
    # `except Exception` NameError'ı SESSİZCE YUTUYORDU: rapor tertemiz
    # görünüyor, bölüm hiç basılmıyordu. Ancak taze bir kayıt eklenip
    # elle sınanınca fark edildi.
    agac = ast.parse(rapor)
    ithal = {a.name for d in ast.walk(agac) if isinstance(d, ast.Import)
             for a in d.names}
    denetle("json" in ithal,
            "gunluk_rapor json'u import ediyor",
            "jsonl okunuyor ama json import edilmemişse NameError geniş "
            "except tarafından yutulur ve bölüm sessizce hiç basılmaz")

    # Geçici OAuth artıkları depoda durmamalı
    gitignore = (KOK / ".gitignore").read_text(encoding="utf-8")
    denetle("verifier" in gitignore,
            "OAuth geçici artıkları .gitignore'da",
            "PKCE doğrulayıcısı depoda durmamalı")


def test_cagrilan_script_var_mi() -> None:
    """
    Workflow ve Worker'ın çağırdığı her script GERÇEKTEN var olmalı.

    ⚠️ NEDEN GEREKTİ (4 Eyl 2026): `scripts/ekonomi_turu.py` commit
    `2aaa220`'de bilerek silinmişti ("eski 11:15 ekonomi turu
    kaldırıldı"), ama üç yerde izi kalmıştı:
      * `yayinla.yml` hâlâ `python scripts/ekonomi_turu.py` çağırıyor
      * Worker hâlâ `ekonomi` / `ekonomi_hazirla` komutunu gönderiyor
      * Telegram'da hâlâ "📊 Ekonomi Turu Başlat" düğmesi duruyor

    Yani o düğmeye basan kullanıcı "⏳ başlatılıyor" görüyor, job
    **No such file** ile kırmızıya düşüyor ve hata bildirimi geliyor.
    Düğme her seferinde başarısız.

    ⚠️ Bir özelliği kaldırırken ÜÇ YERİ birden temizle: script,
    workflow dalı, Worker düğmesi/dispatch listesi. (1h/1k dersinin
    workflow karşılığı: kaynağı kapatmak ondan gelen KAYITLARI
    düzeltmiyordu; burada da script'i silmek onu ÇAĞIRANLARI
    düzeltmiyor.)
    """
    import re as _re
    kok = KOK
    metinler = {}
    for yol in (kok / ".github" / "workflows").glob("*.yml"):
        metinler[str(yol.relative_to(kok))] = yol.read_text(encoding="utf-8")
    worker_yolu = kok / "worker" / "index.js"
    if worker_yolu.exists():
        metinler["worker/index.js"] = worker_yolu.read_text(encoding="utf-8")

    for nerede, icerik in sorted(metinler.items()):
        # Yorum satırlarını at — uyarı metinleri yanlış alarm veriyor
        kod = "\n".join(l for l in icerik.splitlines()
                         if not l.strip().startswith("#"))
        for script in sorted(set(_re.findall(r"(scripts/[a-z0-9_]+\.py)", kod))):
            denetle((kok / script).exists(),
                    f"{nerede} → {script} mevcut",
                    "çağrılan script yoksa job 'No such file' ile kırmızıya "
                    "düşer; kullanıcı düğmeye basar, hiçbir şey olmaz")


def test_kanal_jetonlari_denetleniyor() -> None:
    """
    Açık her yayın kanalının jeton sağlığı günlük raporda görünmeli.

    ⚠️ NEDEN GEREKTİ (4 Eyl 2026): YouTube refresh jetonu öldü
    (`invalid_grant: Token has been expired or revoked`) ve post
    YouTube'a gitmedi. Yayın job'ı bunu **yalnızca WARNING** olarak
    loglayıp devam etti — bu DOĞRU davranış (bir kanal patlayınca post
    yine çıkmalı) ama arıza görünmez oldu. Kullanıcı eksik postu
    gözüyle görünce sordu.

    ⚠️ **`saglik_testi` fonksiyonları ZATEN VARDI**, yalnızca hiç
    çağrılmıyordu: rapor Instagram ve Threads'e bakıyor, video
    kanallarına bakmıyordu. Yani kod yazılmış, bağlanmamıştı.

    ⚠️ KÖK SEBEP AYRI: Google, OAuth ekranı **"Testing"** modundaki
    uygulamaların refresh jetonunu **7 GÜNDE** iptal ediyor. Ölçüldü:
    kurulum 28 Ağu, ilk yayın 28 Ağu 17:10, son başarılı 4 Eyl 06:44,
    ilk başarısız 4 Eyl 08:44 — tam 7 gün. Kalıcı çözüm jetonu
    yenilemek DEĞİL, OAuth ekranını "In production"a almak.
    """
    rapor = (KOK / "scripts/gunluk_rapor.py").read_text(encoding="utf-8")
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    kanallar = set((cfg.get("sosyal") or {}).get("kanallar") or [])

    # --- TikTok TASLAK ile YAYIN ayırt edilmeli ---
    #
    # ⚠️ `tiktok.video_yukle` önce doğrudan yayını deniyor; `video.publish`
    # izni yoksa TASLAK kutusuna düşüyor ve dönüşte `mod: "inbox_draft"`
    # diyor. Mesajlar bunu YOK SAYIP her durumda "yüklendi" yazıyordu —
    # oysa taslak modunda video TikTok uygulamasında BEKLİYOR ve elle
    # yayınlanması gerekiyor. Ölçüldü (4 Eyl 2026): yayınlanmış TÜM
    # kayıtların publish_id'si `v_inbox_file~` ile başlıyor, yani
    # doğrudan yayın HİÇ çalışmamış — kullanıcı 68 postun tamamında
    # "yüklendi" gördü ama hiçbiri yayınlanmadı.
    #
    # Bu, "Yarım zinciri başarı sayma" dersinin (Threads) TikTok
    # karşılığı: yapılmamış işi başarı diye raporlamak, hatayı hiç
    # görmemekten kötü.
    oi = (KOK / "scripts/onay_isle.py").read_text(encoding="utf-8")
    denetle(oi.count('tt_res.get("mod")') >= 2,
            "TikTok taslak/yayın ayrımı HER İKİ akışta da yapılıyor",
            "asıl yayın ve telafi akışı ayrı kod yolları — birine "
            "eklenip diğerine unutulursa kullanıcı yine yanlış bilgi alır")

    denetle("saglik_testi" in rapor,
            "günlük rapor kanal sağlık testlerini çağırıyor",
            "jeton ölünce kimse fark etmiyor; yayın job'ı yalnızca "
            "WARNING loglayıp devam ediyor")

    # Sağlık testi OLAN her açık kanal raporda anılmalı
    for kanal in sorted(kanallar):
        modul_yolu = KOK / "src" / f"{kanal}.py"
        if kanal == "x":
            modul_yolu = KOK / "src" / "twitter.py"
        if not modul_yolu.exists():
            continue
        kaynak = modul_yolu.read_text(encoding="utf-8")
        if "def saglik_testi" not in kaynak and "def api_saglik_testi" not in kaynak:
            continue          # sağlık testi yoksa denetlenemez
        ad = "twitter" if kanal == "x" else kanal
        denetle(ad in rapor,
                f"'{ad}' kanalı günlük raporda denetleniyor",
                "sağlık testi yazılmış ama rapora bağlanmamış — kod var, "
                "bağlantı yok")


def test_video_etiketleri_habere_ozel() -> None:
    """
    Video kanalları carousel caption'ını OLDUĞU GİBİ kullanmamalı.

    ⚠️ NEDEN GEREKTİ (4 Eyl 2026): kullanıcı Reels'te fark etti —
    video platformları açıklamadaki YALNIZCA İLK 5 etiketi sayıyor,
    sonrakiler düz metin olarak basılıyor. `caption.SABIT_HASHTAGLER`
    tam 5 etiket taşıyor ve `_hashtaglari_birlestir` onları BAŞA
    koyuyor — o sıralama carousel için DOĞRU (30 etiket sığıyor,
    kırpma sondan olsun diye) ama videoda haberin kendi etiketlerini
    tamamen kapının önünde bırakıyordu.

    ÖLÇÜLDÜ (4 gerçek yayın): dördünde de sayılan 5 etiket aynıydı —
    gündem · haber · türkiye · sondakika · gününhaberleri. 'derbi',
    'gemikazasi', 'organnakli' hiç sayılmadı. Üstelik ABD'deki bir tıp
    haberine '#türkiye' basılıyordu: etkisiz değil, YANLIŞ.

    ⚠️ AST ŞART, düz metin araması DEĞİL — bu dosyada ve
    `onay_isle.py`'de 'aciklamayi_kur' kelimesi yorumlarda da geçiyor
    ve düz arama denetimi sahte geçiriyor (projede üç kez yaşandı).
    """
    import ast as _ast
    from src import caption as _caption

    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))

    # --- 1) DAVRANIŞ: tam 5 etiket, jenerik olan yalnızca 1 tane ---
    haber = {"ig_hashtag": "fenerbahce, besiktas, derbi, superlig, kadikoy"}
    for kanal in ("reels", "youtube", "tiktok"):
        e = _caption.etiketleri_sec([haber], kanal=kanal, ayarlar=cfg)
        denetle(len(e) == _caption.HASHTAG_ADEDI,
                f"video etiketi sayısı 5 ({kanal})",
                f"platform ilk 5'i sayıyor; {len(e)} etiket üretildi")

        anahtar = [_caption._etiket_anahtari(x) for x in e]
        denetle(len(anahtar) == len(set(anahtar)),
                f"video etiketlerinde tekrar yok ({kanal})",
                "aynı etiket iki kez basılıyor")

        # ⚠️ TEKRAR DENETİMİ AYRI VERİ İSTİYOR. Yukarıdaki haberin
        # etiketleri zaten benzersiz, yani kural orada hiç SINANMIYOR
        # (negatif test verisi tuzağı — CLAUDE.md'de kayıtlı). Gerçek
        # vaka: haberin etiketi 'kesfet' (ş'siz), etkileşim etiketi
        # 'keşfet' (ş'li). `casefold()` ikisini farklı sayıyor ve
        # '#kesfet #keşfet' yan yana basılıyordu.
        # ⚠️ TEST KENDİ ÖLÇÜTÜNÜ KULLANMALI. İlk yazımda tekrar denetimi
        # `_caption._etiket_anahtari` ile yapılıyordu — yani ölçtüğü
        # kuralı uygulayan fonksiyonun ta kendisiyle. O fonksiyon
        # bozulunca test de aynı körlükle bakıp TEMİZ geçiyordu
        # (kasten bozularak görüldü: 306/306). Aşağıdaki normalizasyon
        # `unicodedata` ile bağımsız kuruluyor.
        def _bagimsiz_anahtar(s: str) -> str:
            import unicodedata
            s = s.replace("ı", "i").replace("I", "i").replace("İ", "i")
            s = unicodedata.normalize("NFD", s.casefold())
            return "".join(c for c in s if not unicodedata.combining(c))

        capraz = _caption.etiketleri_sec(
            [{"ig_hashtag": "kesfet, shorts, deprem, izmir, afad, ege"}],
            kanal=kanal, ayarlar=cfg)
        c_anahtar = [_bagimsiz_anahtar(x) for x in capraz]
        denetle(len(c_anahtar) == len(set(c_anahtar)),
                f"Türkçe karakter varyantı tekrar saymıyor ({kanal})",
                f"'kesfet'/'keşfet' ayrı sayılıp yan yana basıldı: {capraz}")

        sabit = {_caption._etiket_anahtari(x)
                 for x in _caption.SABIT_HASHTAGLER}
        jenerik = [x for x in anahtar if x in sabit]
        denetle(not jenerik,
                f"habere özel etiketler jeneriğe yenilmiyor ({kanal})",
                f"haberin 5 etiketi varken jenerik etiket girdi: {jenerik}")

    # --- 2) DAVRANIŞ: etkileşim etiketi platforma göre değişiyor ---
    yt = _caption.etiketleri_sec([haber], kanal="youtube", ayarlar=cfg)
    rl = _caption.etiketleri_sec([haber], kanal="reels", ayarlar=cfg)
    denetle(yt[-1] != rl[-1],
            "etkileşim etiketi platforma göre değişiyor",
            "'#Shorts' YouTube'da format sinyali, Instagram'da anlamsız; "
            "tek etiket üç platformda aynı işi görmüyor")

    # --- 3) DAVRANIŞ: havuz darsa 5'e tamamlanıyor ---
    az = _caption.etiketleri_sec([{"ig_hashtag": "deprem"}],
                                   kanal="reels", ayarlar=cfg)
    denetle(len(az) == _caption.HASHTAG_ADEDI,
            "etiket havuzu darsa jenerikle tamamlanıyor",
            "5 jenerik etiket, 2 etiketten iyidir; eksik bırakmak tercih "
            "edilmedi")

    # --- 4) DAVRANIŞ: gövde ve ATIF korunuyor ---
    ham = ("Manşet burada\n\nFoto: Jane Doe (CC BY-SA 4.0)"
           "\n\n#gündem #haber #türkiye #sondakika #gününhaberleri")
    cikti = _caption.aciklamayi_kur(ham, [haber], kanal="reels", ayarlar=cfg)
    denetle("CC BY-SA 4.0" in cikti,
            "video açıklamasında atıf korunuyor",
            "Commons atıfları CC BY gereği HUKUKEN zorunlu, kırpılamaz")
    denetle(cikti.count("#") == _caption.HASHTAG_ADEDI,
            "eski hashtag kuyruğu atılıyor",
            "eski kuyruk kalırsa etiket sayısı 5'i aşar ve sorun sürer")

    # --- 4b) TELEGRAM'A DÜŞEN METİN de aynı kuralda ---
    #
    # ⚠️ NEDEN GEREKTİ: kural önce YALNIZCA videoya uygulandı, çünkü
    # postun bot tarafından yayınlandığı varsayılmıştı. Kullanıcı
    # *"telegrama düşen açıklama metnini ben paylaşırken manuel
    # düzenliyorum"* deyince görüldü ki asıl metin BU — onay mesajı
    # 11-12 etiketle gidiyordu ve her postta ilk beş jenerik etiket elle
    # siliniyordu. Bu denetim UÇTAN UCA: gerçek caption üretiliyor.
    import re as _re2
    from src import filtre as _filtre
    sahte = {
        "id": 1, "ig_baslik": "Test başlığı", "ig_caption": "Gövde metni.",
        "ig_hashtag": "alfa, beta, gama, delta, epsilon, zeta",
        "kaynak": "TRT Haber", "onem_puani": 7, "son_dakika": 1,
        "gorsel_kaynagi": "pexels", "gorsel_atif": "", "detay_metni": "",
        "vurgu_sayi": "", "vurgu_etiket": "", "alinti": "", "alinti_sahibi": "",
        "sana_etkisi": "", "etkilesim_sorusu": "", "ulke_kodu": "",
    }
    sonuclar = [{"id": 1, "katman": "pexels", "atif": ""}]
    metin_sd = _filtre.markdown_temizle(
        _caption.son_dakika_caption(sahte, sonuclar, cfg))
    t_sd = _re2.findall(r"#(\w+)", metin_sd)
    denetle(len(t_sd) == _caption.HASHTAG_ADEDI,
            "Telegram'a düşen tekil metinde tam 5 etiket",
            f"{len(t_sd)} etiket üretildi: {t_sd}")
    sabit_kume = {_caption._etiket_anahtari(x)
                  for x in _caption.SABIT_HASHTAGLER}
    denetle(sum(1 for x in t_sd
                if _caption._etiket_anahtari(x) in sabit_kume) == 0,
            "Telegram metninde jenerik etiket habere özeli ezmiyor",
            f"jenerik etiket girdi: {t_sd}")

    # --- 4c) ÇOK HABERLİ TURDA SIRAYLA ---
    #
    # ⚠️ `_hashtaglari_birlestir` etiketleri HABER HABER sıralıyor;
    # düz dilim dördünü de İLK haberden alıyordu ve 10 haberlik tur
    # yalnızca ilk haberin etiketleriyle çıkıyordu.
    coklu = [
        {"ig_hashtag": "birinci, birinciek, birinciek2"},
        {"ig_hashtag": "ikinci, ikinciek"},
        {"ig_hashtag": "ucuncu, ucuncuek"},
        {"ig_hashtag": "dorduncu, dorduncuek"},
    ]
    e_coklu = _caption.etiketleri_sec(coklu, kanal="instagram", ayarlar=cfg)
    denetle(set(e_coklu[:4]) == {"birinci", "ikinci", "ucuncu", "dorduncu"},
            "çok haberli turda her haberden birer etiket",
            f"dördü de ilk haberden geliyor olabilir: {e_coklu}")

    # --- 5) BAĞLANTI (AST): üç kanal da caption'dan geçiyor mu ---
    agac = _ast.parse((KOK / "scripts/onay_isle.py").read_text(encoding="utf-8"))
    ham_metin = {"youtube": 0, "reels": 0, "tiktok": 0}
    gecen = {"youtube": 0, "reels": 0, "tiktok": 0}

    def _caption_cagrisi(d) -> bool:
        """`caption.aciklamayi_kur(...)` / `etiketleri_sec(...)` mı?"""
        return (isinstance(d, _ast.Call)
                and isinstance(d.func, _ast.Attribute)
                and d.func.attr in ("aciklamayi_kur", "etiketleri_sec"))

    for n in _ast.walk(agac):
        if not (isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)):
            continue
        adi = n.func.attr
        if adi == "shorts_yukle":
            kanal = "youtube"
            hedef = [k.value for k in n.keywords if k.arg == "aciklama"]
        elif adi == "reels_yayinla":
            kanal = "reels"
            hedef = [n.args[1]] if len(n.args) > 1 else []
        elif adi == "video_yukle" and isinstance(n.func.value, _ast.Name) \
                and n.func.value.id == "tiktok":
            kanal = "tiktok"
            hedef = [k.value for k in n.keywords if k.arg == "etiketler"]
        else:
            continue

        if not hedef:
            ham_metin[kanal] += 1
            continue
        d = hedef[0]
        # Doğrudan çağrı ya da caption çıktısını tutan değişken
        if _caption_cagrisi(d):
            gecen[kanal] += 1
        elif isinstance(d, _ast.Name) and d.id.startswith(
                ("aciklama_", "etiket_")):
            gecen[kanal] += 1
        else:
            ham_metin[kanal] += 1

    for kanal in ("youtube", "reels", "tiktok"):
        denetle(gecen[kanal] > 0 and ham_metin[kanal] == 0,
                f"{kanal} açıklaması caption.video_* üzerinden geçiyor",
                f"{ham_metin[kanal]} çağrı ham carousel metnini kullanıyor — "
                "'aynı kural bir kod yolunda uygulanmamış' hatası (1j/1p/1f)")

    # --- 6) TikTok başlığı manşeti KIRPMIYOR ---
    from src import tiktok as _tiktok
    # ⚠️ "manşet bozulmadı mı" DİYE BAKMAK YETMİYOR. 140 karakterlik
    # manşet, sondan kırpan bozuk bir sürümde de sağlam kalıyor —
    # kesilen şey ETİKETİN ORTASI oluyor ('#besikt' gibi) ve test sahte
    # geçiyor. İlk yazımda tam bu oldu, kasten bozulunca 303/303 dedi.
    # Doğru ölçüt: çıktıdaki her etiket TAM ve listedeki etiketlerden
    # biri olmalı.
    verilen = ["fenerbahce", "besiktas", "derbi"]
    uzun = "Ç" * 140
    s = _tiktok.baslik_kur(uzun, verilen)
    bulunan = re.findall(r"#(\S+)", s)
    denetle(uzun in s
            and len(s) <= _tiktok.TIKTOK_AZAMI_BASLIK
            and all(e in verilen for e in bulunan),
            "TikTok başlığı manşeti değil etiketi kırpıyor",
            f"okuyucu için değerli olan manşet; sınır aşılınca etiket "
            f"TAMAMEN düşmeli, yarım kalmamalı. Çıkan: {bulunan}")


def test_metin_uretimi_icerik_sinyaline_bakiyor() -> None:
    """
    Günlük akış hangi habere metin üreteceğine İÇERİK SİNYALİNE bakarak
    karar vermeli — yalnızca kaynak ağırlığına ve tazeliğe değil.

    ⚠️ NEDEN GEREKTİ (4 Eyl 2026): `son_dakika.taze_adaylar` düpedüz
    `ORDER BY agirlik DESC, yayin_tarihi DESC` diyordu. ÖLÇÜLDÜ:
    tazelik penceresine giren 60 haberin **54'ünün ağırlığı 10**, yani
    ağırlık neredeyse hep berabere bitiyor ve sıralamayı fiilen SAF
    TAZELİK belirliyordu.

    Somut sonuç: *"Yaz bitti, işbaşı sendromunu nasıl atlatabilirsiniz"*
    (içerik puanı 0) Gemini metni alırken *"Girne'deki gemide can kaybı
    12'ye yükseldi"* (içerik puanı 20) **45. sırada** bekliyordu.

    ⚠️ İKİ AYRI SIRALAMA KURALI VARDI. `secim.on_eleme` içerik
    sinyalini yıllardır kullanıyor ama o, cron'u KAPALI `hazirla.py`den
    günde ~1 kez çağrılıyor; günde ~20 kez çalışan `taze_adaylar` ise
    hiç kullanmıyordu. Formül artık `secim.on_skor`'da, tek yerde.
    Projenin en sık tekrarlayan hatası: kural doğru, bir kod yolunda
    uygulanmamış (1j · 1p · 1f).
    """
    import ast as _ast
    from src import secim as _secim
    import scripts.son_dakika as _sd

    simdi = datetime.now(timezone.utc)

    def _ekle(con, hid, baslik, agirlik, yas_saat):
        con.execute(
            "INSERT INTO haberler (id, kaynak, kategori, agirlik, baslik_orj,"
            " link, ozet_orj, yayin_tarihi, durum) VALUES (?,?,?,?,?,?,?,?,?)",
            (hid, "K", "turkiye", agirlik, baslik, f"http://x/{hid}", "",
             (simdi - timedelta(hours=yas_saat)).isoformat(), "yeni"))

    con = gecici_db()
    # DAHA TAZE ama içi boş (açıklama kalıbı, içerik puanı düşük)
    _ekle(con, 1, "Bakan konuyu değerlendirdi ve mesaj yayımladı", 10, 0.5)
    # DAHA ESKİ ama olay haberi (rakam + olay fiili)
    _ekle(con, 2, "Gemide can kaybı 12'ye yükseldi, 3 kişi tutuklandı", 10, 3.0)
    con.commit()

    ayarlar = {"genel": {"son_dakika_tazelik_saat": 8}}
    secilen = _sd.taze_adaylar(con, ayarlar, 1)
    denetle(bool(secilen) and secilen[0]["id"] == 2,
            "metin üretimi içerik sinyaline bakıyor",
            "3 saatlik olay haberi, 0.5 saatlik açıklama haberine yenildi — "
            "sıralama yine saf tazelik demektir")

    # ⚠️ ÖNCE PUANLA SONRA SINIRLA. SQL'de LIMIT kalırsa düşük ağırlıklı
    # ama yüksek içerik sinyalli haber dilimin DIŞINDA kalır ve hiç
    # puanlanmaz — kardeş görsel havuzunda birebir bu yaşandı.
    # ⚠️ VERİ TUZAĞI — ilk yazımda dolgular ağırlık 10, olay haberi
    # ağırlık 5 idi ve test HAKLI OLARAK kırmızı verdi: ağırlık ×10
    # çarpanıyla giriyor, yani 50 puanlık farkı en fazla 20 puanlık
    # içerik sinyali kapatamaz. Test, tasarımın hiç vaat etmediği bir
    # şeyi ölçüyordu. Doğru kurgu: AYNI ağırlık, olay haberi DAHA ESKİ.
    # Eski SQL (`ORDER BY agirlik, yayin_tarihi DESC LIMIT 3`) onu hiç
    # çekmezdi; yeni kod puanlayıp öne alıyor.
    con2 = gecici_db()
    for i in range(30):                      # taze ama içi boş dolgu
        _ekle(con2, 100 + i,
              "Bakan konuyu değerlendirdi ve mesaj yayımladı", 10, 0.5)
    _ekle(con2, 999, "Fabrikada yangın çıktı, dört kişi tutuklandı", 10, 3.0)
    con2.commit()
    s2 = _sd.taze_adaylar(con2, ayarlar, 3)
    denetle(any(h["id"] == 999 for h in s2),
            "eski ama önemli haber dilimin dışında kalmıyor",
            "SQL'de puanlamadan önce LIMIT var demektir; haber hiç "
            "değerlendirilmeden eleniyor (ÖNCE EŞLEŞTİR SONRA SIRALA)")

    # --- Kural TEK YERDE mi (AST) ---
    kaynak = (KOK / "scripts/son_dakika.py").read_text(encoding="utf-8")
    agac = _ast.parse(kaynak)
    fonk = next((n for n in _ast.walk(agac)
                 if isinstance(n, _ast.FunctionDef) and n.name == "taze_adaylar"),
                None)
    denetle(fonk is not None, "taze_adaylar bulundu", "fonksiyon yok")
    if fonk is not None:
        on_skor_var = any(
            isinstance(d, _ast.Attribute) and d.attr == "on_skor"
            for d in _ast.walk(fonk))
        denetle(on_skor_var,
                "taze_adaylar secim.on_skor kullanıyor",
                "formül yerel olarak yeniden yazılırsa iki sıralama kuralı "
                "doğar ve biri gün gelir unutulur")

    secim_agac = _ast.parse((KOK / "src/secim.py").read_text(encoding="utf-8"))
    oe = next((n for n in _ast.walk(secim_agac)
               if isinstance(n, _ast.FunctionDef) and n.name == "on_eleme"), None)
    if oe is not None:
        denetle(any(isinstance(d, _ast.Name) and d.id == "on_skor"
                    for d in _ast.walk(oe)),
                "on_eleme de aynı kapıdan geçiyor",
                "iki akış farklı formül kullanırsa 'aynı kural iki yerde' "
                "hatası geri gelir")

    # --- Formül B: yaş cezası saatte 1 puan (kullanıcı kararı) ---
    a = {"agirlik": 10, "baslik_orj": "test",
         "yayin_tarihi": (simdi - timedelta(hours=0)).isoformat()}
    b = {"agirlik": 10, "baslik_orj": "test",
         "yayin_tarihi": (simdi - timedelta(hours=10)).isoformat()}
    fark = _secim.on_skor(a) - _secim.on_skor(b)
    denetle(9.0 <= fark <= 11.0,
            "yaş cezası saatte ~1 puan",
            f"10 saatlik fark {fark:.1f} puan getirdi; kullanıcı kararı "
            "saatte 1 puandı (B varyantı) — 3 olsaydı gelişen haberler düşer")


def test_her_dugme_workerda_karsilaniyor() -> None:
    """
    Python'un ürettiği HER `callback_data` Worker tarafından karşılanmalı.

    ⚠️ NEDEN GEREKTİ (4 Eyl 2026): `/durum` askıda kalan her tur için
    DÖRT düğme basıyor. İkisi (`kurtar:{id}`, `yayin_kontrol:{id}`)
    çalışıyordu ama **`yayinla:{id}` ve `iptal:{id}` Worker'ın beyaz
    listesinde YOKTU** — basılınca Telegram "Tanınmayan komut" deyip
    susuyordu. Yani tur takıldığında açılan KURTARMA panelinde,
    kurtaracak iki düğmenin ikisi de ölüydü. Ayrıca Worker'ın kendi
    menüsündeki "🚨 Son Dakika Tara" (`sondakika`) düğmesi de listede
    değildi: Worker kendi bastığı düğmeyi reddediyordu.

    ⚠️ BU TESTİ DÜZ METİNLE YAZMA. `eylemMi` bir REGEX listesi
    (`GORSEL_ONAY`, `KURTAR`, `MENU_GEZINME`…); `worker/index.js`
    içinde "gorsel_yeni" diye aramak onları göremez ve üç ayrı yanlış
    envanter üretir — bu oturumda tam olarak bu yaşandı. Test Worker'ı
    **gerçekten yükleyip** `eylemMi`'yi çağırıyor.

    ⚠️ "Worker reddediyor" TEK BAŞINA kusur değil: menü gezinme
    komutları (`slayt_menu:`, `kanal:`, `sec:`…) bilerek GitHub'a
    gitmiyor, Worker onları yerel karşılıyor. Bu yüzden ölçüt
    `eylemMi` DEĞİL, "herhangi bir yerde karşılanıyor mu".
    """
    import json as _json
    import re as _re
    import shutil
    import subprocess
    if not shutil.which("node"):
        return                                   # node yoksa atla

    ham = set()
    for dosya in ("src/telegram_bot.py", "scripts/onay_isle.py"):
        metin = (KOK / dosya).read_text(encoding="utf-8")
        ham |= set(_re.findall(r'callback_data"\s*:\s*f?"([^"]+)"', metin))

    # ⚠️ WORKER'IN KENDİ DÜĞMELERİ DE DENETLENMELİ. `/menu` panelini
    # Worker basıyor; `sondakika` düğmesi yalnızca Python'da da tanımlı
    # olduğu için ŞANS ESERİ yakalandı. Worker'a özel bir düğme
    # eklenirse (örn. `makro_yardim:`) bu tarama olmadan görünmez kalır.
    js_metin = (KOK / "worker/index.js").read_text(encoding="utf-8")
    ham |= set(_re.findall(r'callback_data:\s*"([^"$]+)"', js_metin))

    def _ornekle(s: str) -> str:
        s = (s.replace("{mesaj_id}", "777").replace("{mid}", "777")
              .replace("{sira}", "3").replace("{adet}", "10"))
        return _re.sub(r"\{[^}]+\}", "1", s)

    adaylar = sorted({_ornekle(x) for x in ham})
    denetle(len(adaylar) > 50,
            "düğme biçimleri okunabildi",
            f"yalnızca {len(adaylar)} biçim bulundu — ayrıştırma bozuk olabilir")

    sonuc = subprocess.run(
        ["node", str(KOK / "tests/dugme_kapsam.js"),
         str(KOK / "worker/index.js"), _json.dumps(adaylar)],
        capture_output=True, text=True, timeout=30)
    if sonuc.returncode != 0:
        denetle(False, "worker düğme kapsamı ölçülebildi",
                (sonuc.stderr or "")[:200])
        return

    kapsam = _json.loads(sonuc.stdout)
    olu = sorted(a for a in adaylar if not kapsam[a])
    denetle(not olu,
            "Python'un ürettiği her düğme Worker'da karşılanıyor",
            f"basılınca 'Tanınmayan komut' alacak düğmeler: {olu}")

    # ⚠️ ARACIN KENDİSİ ÇALIŞIYOR MU — uydurma bir düğme kabul
    # edilmemeli, yoksa yukarıdaki denetim her şeye "temiz" der.
    dogrulama = subprocess.run(
        ["node", str(KOK / "tests/dugme_kapsam.js"), str(KOK / "worker/index.js"),
         _json.dumps(["asdfqwer_yok", "yayinla:abc", "../../etc/passwd"])],
        capture_output=True, text=True, timeout=30)
    if dogrulama.returncode == 0:
        d = _json.loads(dogrulama.stdout)
        denetle(not any(d.values()),
                "kapsam ölçer uydurma düğmeyi reddediyor",
                f"ölçer her şeye 'karşılanıyor' diyor: {d}")


def test_worker_komutlari_python_tarafinda_var() -> None:
    """
    TERS YÖN: Worker'ın kabul ettiği her komutun bir işleyicisi olmalı.

    ⚠️ `test_her_dugme_workerda_karsilaniyor` Python→Worker yönünü
    kapatıyor (düğme var, Worker tanımıyor). Bu test TERSİNİ ölçüyor:
    Worker komutu GitHub'a iletiyor, job çalışıyor, hiçbir dal uymuyor.
    Eskiden bunun sonucu **tam sessizlikti** — `main()` fonksiyonun
    sonuna varıp `None` dönüyor, `SystemExit(None)` çıkış kodunu **0**
    yapıyor, job YEŞİL görünüyordu.

    ⚠️ İki yön AYRI kusur sınıfı ve ikisi de gerçekten yaşandı:
    Python→Worker'da kurtarma panelinin iki düğmesi ölüydü;
    Worker→Python'da `android_muzikli` beyaz listede kalmıştı (Android
    kümesi 4 Eyl'de silinmişti, girdi kalmıştı).
    """
    import ast as _ast
    import re as _re

    js = (KOK / "worker/index.js").read_text(encoding="utf-8")
    blok = js.split("const EYLEMLER = [", 1)[1].split("];", 1)[0]
    blok = "\n".join(l for l in blok.splitlines()
                     if not l.strip().startswith("//"))
    eylemler = _re.findall(r'"([a-z0-9_]+)"', blok)
    denetle(len(eylemler) > 20, "worker EYLEMLER listesi okunabildi",
            f"yalnızca {len(eylemler)} komut bulundu — ayrıştırma bozuk")

    agac = _ast.parse((KOK / "scripts/onay_isle.py").read_text(encoding="utf-8"))
    tam, onek = set(), set()
    for n in _ast.walk(agac):
        if (isinstance(n, _ast.Compare) and isinstance(n.left, _ast.Name)
                and n.left.id == "komut"):
            for op, c in zip(n.ops, n.comparators):
                if not isinstance(op, (_ast.Eq, _ast.In)):
                    continue
                if isinstance(c, _ast.Constant) and isinstance(c.value, str):
                    tam.add(c.value)
                elif isinstance(c, (_ast.Tuple, _ast.List, _ast.Set)):
                    for e in c.elts:
                        if isinstance(e, _ast.Constant) and isinstance(e.value, str):
                            tam.add(e.value)
        if (isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
                and n.func.attr == "startswith"
                and isinstance(n.func.value, _ast.Name)
                and n.func.value.id == "komut"):
            for a in n.args:
                if isinstance(a, _ast.Constant):
                    onek.add(a.value)
                elif isinstance(a, _ast.Tuple):
                    for e in a.elts:
                        if isinstance(e, _ast.Constant):
                            onek.add(e.value)

    # ⚠️ onay_isle TEK işleyici değil: `yayinla.yml` bazı komutları kendi
    # dalında karşılıyor (`arsiv` → gecmisi_paylas.py). Bunu modellemezsem
    # çalışan komutu "ölü" diye raporlarım — bu oturumda tam olarak oldu.
    yml = (KOK / ".github/workflows/yayinla.yml").read_text(encoding="utf-8")
    workflow = set(_re.findall(r'\$KOMUT"\s*=\s*"([a-z0-9_]+)"', yml))

    def _islenir(k: str) -> bool:
        return (k in tam or k in onek
                or any(k.startswith(o) for o in onek) or k in workflow)

    olu = sorted(k for k in eylemler if not _islenir(k))
    denetle(not olu,
            "Worker'ın kabul ettiği her komutun işleyicisi var",
            f"beyaz listede olup hiçbir yerde işlenmeyen: {olu}")

    # --- Aracın kendisi çalışıyor mu: bilinen komutları görüyor mu? ---
    denetle(all(_islenir(k) for k in ("yayinla", "durum", "ayar")),
            "işleyici taraması bilinen komutları görüyor",
            "tarama bozuk — her komutu 'ölü' sayabilir")

    # --- SESSİZ DÜŞÜŞ YOK: try bloğu return ile bitmeli ---
    #
    # ⚠️ Yapısal denetim, metin araması değil. `main()`in try bloğunun
    # son ifadesi `return` değilse eşleşmeyen komut fonksiyonun sonuna
    # düşüyor ve `None` dönüyor demektir — çıkış kodu 0, job yeşil,
    # kullanıcıya hiçbir şey söylenmiyor.
    ana = next((n for n in _ast.walk(agac)
                if isinstance(n, _ast.FunctionDef) and n.name == "main"), None)
    denetle(ana is not None, "onay_isle.main bulundu", "fonksiyon yok")
    if ana is not None:
        try_blok = next((n for n in ana.body if isinstance(n, _ast.Try)), None)
        denetle(try_blok is not None and isinstance(try_blok.body[-1], _ast.Return),
                "eşleşmeyen komut sessizce düşmüyor",
                "main()in try bloğu return ile bitmiyor; tanınmayan komut "
                "None döndürüp çıkış kodunu 0 yapıyor (SESSİZ BAŞARISIZLIK)")


def test_komut_menusu_tutarli() -> None:
    """
    Slash menüsü · Worker'ın tanıdığı komutlar · `/yardim` metni — üçü
    de aynı komut kümesini anlatmalı.

    ⚠️ NEDEN GEREKTİ (4 Eyl 2026): üçü de ayrışmıştı. Worker **33 asıl
    slash komutu** tanıyordu, `KOMUT_MENUSU` yalnızca **21**'ini
    gösteriyordu — `/haber`, `/tamamla`, `/arsiv`, `/video`, `/fed`,
    `/makro`, `/menu`, `/haftalik`, `/ayar`, `/tur` çalışıyor ama
    hiçbir yerde YAZMIYORDU. `/yardim` metni de menüyle tutmuyordu:
    yardımda `/haber` vardı menüde yoktu, menüde `hisse`/`kripto`/
    `faiz`/`bulten` vardı yardımda yoktu.

    ⚠️ Menüde OLUP Worker'ın tanımadığı komut daha kötü: kullanıcı
    resmi menüden seçiyor ve hiçbir şey olmuyor.
    """
    import re as _re
    from src.komutlar import KOMUT_MENUSU

    js = (KOK / "worker/index.js").read_text(encoding="utf-8")
    taninan = set()
    for satir in js.splitlines():
        if ".includes(komutMetni)" in satir:
            taninan |= set(_re.findall(r'"/([a-z_]+)"', satir))
    taninan |= set(_re.findall(r'komutMetni === "/([a-z_]+)"', js))

    menu = [d["command"] for d in KOMUT_MENUSU]
    denetle(len(taninan) > 20, "worker slash listesi okunabildi",
            f"yalnızca {len(taninan)} komut — ayrıştırma bozuk")

    eksik = sorted(k for k in menu if k not in taninan)
    denetle(not eksik,
            "menüdeki her komutu Worker tanıyor",
            f"resmi menüden seçilip hiçbir şey olmayacak komutlar: {eksik}")

    denetle(len(menu) == len(set(menu)),
            "menüde tekrar eden komut yok",
            "aynı komut iki kez listelenmiş")

    # --- Gruplama: her açıklama bir grup simgesiyle başlamalı ---
    #
    # ⚠️ Telegram'da gerçek "grup" YOK; menü düz bir liste. Gruplama
    # SIRA + açıklamanın başındaki simge ile yapılıyor. Simge düşerse
    # liste 31 satırlık okunamaz bir yığına dönüyor.
    simgeler = {"✍️", "📰", "📈", "🎛", "❓"}
    simgesiz = [d["command"] for d in KOMUT_MENUSU
                if not any(d["description"].startswith(s) for s in simgeler)]
    denetle(not simgesiz,
            "menüdeki her komut bir gruba ait",
            f"grup simgesi taşımayan komutlar: {simgesiz}")

    # ⚠️ AÇIKLAMA TELEFONDA KESİLİYOR. Ölçüldü (4 Eyl 2026, gerçek
    # ekran görüntüsü): ~40 karakterden sonrası "…" ile gidiyor ve
    # sondaki kullanım ipucu HİÇ görünmüyordu — "/dosya ✍️ Konunun
    # A'dan Z'ye kronolojik do…" gibi. 31 açıklamanın 13'ü sınırı
    # aşıyordu. Çözüm: parametre ipucu BAŞA alındı (`<konu>`) ve
    # hepsi 38 karakterin altına indirildi.
    uzunlar = [(d["command"], len(d["description"])) for d in KOMUT_MENUSU
               if len(d["description"]) > 38]
    denetle(not uzunlar,
            "menü açıklamaları telefonda kesilmiyor",
            f"38 karakteri aşan (sonu görünmeyecek): {uzunlar}")

    # --- /yardim metni menüyle aynı komutları anlatmalı ---
    yardim = js[js.index("Daily Brief Bot"):]
    yardim = yardim[:yardim.index('return new Response("ok");')]
    yardimdakiler = set(_re.findall(r"/([a-z_]+)", yardim))
    anlatilmayan = sorted(k for k in menu if k not in yardimdakiler)
    denetle(not anlatilmayan,
            "/yardim menüdeki her komutu anlatıyor",
            f"menüde olup yardımda geçmeyen: {anlatilmayan}")

    # --- Menü GERÇEKTEN Telegram'a gönderiliyor mu ---
    #
    # ⚠️ 4 Eyl 2026: `KOMUT_MENUSU` özenle tutuluyordu ama
    # `telegram_bot.komut_menusu_kaydet()` fonksiyonunu **hiçbir kod
    # çağırmıyordu**. Telegram'daki menü bir zamanlar elle gönderilmiş
    # ve donmuştu; listeye komut eklemek hiçbir şeyi değiştirmiyordu.
    # "Yazılıp okunmayan kayıt" deseninin menü hâli — dosya duruyor,
    # bakımı yapılıyor, kimse okumuyor.
    import ast as _ast
    cagiran = []
    for klasor in ("src", "scripts"):
        for yol in sorted((KOK / klasor).rglob("*.py")):
            try:
                agac = _ast.parse(yol.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for n in _ast.walk(agac):
                if (isinstance(n, _ast.Call)
                        and isinstance(n.func, _ast.Attribute)
                        and n.func.attr == "komut_menusu_kaydet"):
                    cagiran.append(yol.name)
    # ⚠️ GRUP KAPSAMI AYRICA YAZILMALI. Telegram komut listesini
    # "scope"lara göre çözüyor; `default` teorik olarak hepsini kapsıyor
    # ama istemciler grup sohbetinde `all_group_chats`i ayrıca sorguluyor.
    # 4 Eyl 2026: default'ta 31 komut yazılıydı, `getMyCommands`
    # doğruluyordu, kullanıcı grupta "/" yazınca ESKİ menüyü görüyordu.
    tb = (KOK / "src/telegram_bot.py").read_text(encoding="utf-8")
    denetle("all_group_chats" in tb,
            "komut menüsü grup kapsamına da yazılıyor",
            "yalnızca varsayılan kapsama yazılırsa grup menüsü bayat kalır")

    denetle(bool(cagiran),
            "komut menüsü Telegram'a gönderiliyor",
            "komut_menusu_kaydet() hiçbir yerden çağrılmıyor — menü ölü "
            "konfigürasyon, listeyi değiştirmek Telegram'da hiçbir şeyi "
            "değiştirmiyor")


def test_kardes_havuzu_cagrilarda_da_acik() -> None:
    """
    `con` yalnızca İMZADA değil, ÇAĞRIDA da olmalı.

    ⚠️ NEDEN GEREKTİ (4 Eyl 2026): sözleşme testi `slayt_uret` ·
    `tur_uret` · `son_dakika_uret` · `arkaplan_sec` imzalarında `con`
    var mı diye bakıyordu ve TEMİZ geçiyordu. Ama `con=None`
    varsayılanı taşıyan bir imza, çağıranın onu GEÇTİĞİNİ göstermez:
    ölçüldü, `onay_isle`'deki **10 `slayt_uret` çağrısının hiçbiri**
    `con` geçmiyordu. Yani kardeş görsel havuzu — 3 Eyl'de kurulup
    "voleybolda 24 kat piksel kazancı" diye ölçülen mekanizma — tekil
    slayt üretiminde HİÇ ÇALIŞMIYORDU. Sessizce: `con is None` olunca
    havuz atlanıyor, hata verilmiyor.

    Belirtisi kullanıcıdan geldi: Galatasaray maçında og:image düşük
    çözünürlüklüydü ve havuzda aynı maçın başka kaynaktan fotoğrafı
    dururken kullanılmadı.

    ⚠️ İMZA DENETİMİ İLE ÇAĞRI DENETİMİ AYRI ŞEYLERDİR. Biri "kapı
    var mı", diğeri "kapıdan geçiliyor mu" diye soruyor.
    """
    import ast as _ast

    agac = _ast.parse((KOK / "scripts/onay_isle.py").read_text(encoding="utf-8"))
    con_alan = {n.name for n in _ast.walk(agac)
                if isinstance(n, _ast.FunctionDef)
                and any(a.arg == "con" for a in n.args.args)}
    denetle(len(con_alan) > 5, "con alan fonksiyonlar bulundu",
            f"yalnızca {len(con_alan)} bulundu — tarama bozuk olabilir")

    eksik = []
    for fn in [n for n in _ast.walk(agac) if isinstance(n, _ast.FunctionDef)]:
        if fn.name not in con_alan:
            continue
        for n in _ast.walk(fn):
            if not (isinstance(n, _ast.Call)
                    and isinstance(n.func, _ast.Attribute)):
                continue
            if n.func.attr not in ("slayt_uret", "tur_uret", "son_dakika_uret"):
                continue
            # `con` ya anahtar kelimeyle ya da 3. konumsal argüman olarak
            konumsal_con = len(n.args) >= 3
            if not any(k.arg == "con" for k in n.keywords) and not konumsal_con:
                eksik.append(f"{fn.name}:{n.end_lineno} {n.func.attr}")

    denetle(not eksik,
            "slayt üreten çağrılar con taşıyor (kardeş havuzu açık)",
            f"con geçmeyen çağrılar — kardeş havuzu SESSİZCE kapalı: {eksik}")


def test_gorsel_aday_secimi() -> None:
    """
    "Başka fotoğraf" üç aday sunmalı ve seçim güvenli olmalı.

    ⚠️ NEDEN GEREKTİ (4 Eyl 2026, kullanıcı isteği): eskiden TEK
    görsel üretilip "kullan / başka dene" soruluyordu. Beğenilmezse
    job baştan uyanıyordu — Actions'ı uyandırmak 40-90 sn ve üç kez
    basmak üç ayrı job demekti. Üçünü tek job'da üretmek hem hızlı
    hem de KARŞILAŞTIRMA imkânı veriyor; tek tek gösterilince
    "bu mu daha iyiydi" diye geri dönülemiyordu.

    ⚠️ Aday numarası KULLANICIDAN geliyor — aralık denetimi şart.
    Liste bayatlamış (tur yenilenmiş) olabilir; o durumda sessizce
    yanlış görsel uygulamak yerine açıkça söylemek gerekiyor.
    """
    import json as _json
    import logging as _logging
    import sqlite3 as _sqlite3

    sys.path.insert(0, str(KOK))
    import scripts.onay_isle as _oi
    from src import telegram_bot as _tb

    # --- Kolon ve ayar tanımlı mı ---
    from src import db as _db
    denetle("gorsel_adaylari" in _db.EK_KOLONLAR,
            "gorsel_adaylari kolonu tanımlı",
            "aday listesi saklanamaz, seçim çalışmaz")
    cfg = yaml.safe_load((KOK / "config.yaml").read_text(encoding="utf-8"))
    adet = (cfg.get("gorsel") or {}).get("gorsel_aday_adedi")
    denetle(isinstance(adet, int) and adet >= 1,
            "gorsel_aday_adedi ayarı var",
            f"okunan değer: {adet!r}")

    # --- DAVRANIŞ: seçim uygulanıyor, aralık dışı reddediliyor ---
    eski_gonder, eski_kabul, eski_menu, eski_tur = (
        _tb.mesaj_gonder, _oi.gorseli_kabul_et,
        _oi.menuyu_geri_koy, _oi.turu_getir)
    _logging.disable(_logging.CRITICAL)
    try:
        mesajlar, kabuller = [], []
        _tb.mesaj_gonder = lambda t, *a, **k: mesajlar.append(t)
        _oi.telegram_bot = _tb
        _oi.menuyu_geri_koy = lambda *a, **k: None
        _oi.turu_getir = lambda con, mid: None
        _oi.gorseli_kabul_et = lambda con, ay, hs, s, mid: (
            kabuller.append(s), 0)[1]

        con = _sqlite3.connect(":memory:")
        con.row_factory = _sqlite3.Row
        con.execute("""CREATE TABLE haberler (id INTEGER PRIMARY KEY,
            gorsel_adaylari TEXT, gorsel_url_aday TEXT, story_url_aday TEXT,
            gorsel_kaynagi_aday TEXT, gorsel_atif_aday TEXT,
            gorsel_yolu_aday TEXT, gorsel_deneme INTEGER)""")
        adaylar = [{"url": f"http://x/{i}", "story_url": f"http://s/{i}",
                    "katman": "pexels", "atif": f"atif{i}",
                    "yol": f"/tmp/{i}.jpg", "deneme": i - 1} for i in (1, 2, 3)]
        con.execute("INSERT INTO haberler (id, gorsel_adaylari) VALUES (1, ?)",
                    (_json.dumps(adaylar),))
        con.commit()
        hs = list(con.execute("SELECT * FROM haberler"))

        _oi.gorsel_adayini_sec(con, {}, hs, 2, 1, 999)
        secilen = con.execute(
            "SELECT gorsel_url_aday FROM haberler WHERE id=1").fetchone()[0]
        denetle(secilen == "http://x/2" and kabuller,
                "seçilen aday uygulanıyor",
                f"yazılan url: {secilen}, kabul çağrıldı mı: {bool(kabuller)}")

        for gecersiz in (0, 9):
            mesajlar.clear(); kabuller.clear()
            _oi.gorsel_adayini_sec(con, {}, hs, gecersiz, 1, 999)
            denetle(not kabuller and mesajlar,
                    f"aralık dışı aday reddediliyor ({gecersiz})",
                    "geçersiz numara sessizce kabul edildi")

        # Bayat liste: tur yenilenmiş, aday listesi silinmiş
        con.execute("UPDATE haberler SET gorsel_adaylari = NULL WHERE id=1")
        con.commit()
        hs2 = list(con.execute("SELECT * FROM haberler"))
        mesajlar.clear(); kabuller.clear()
        _oi.gorsel_adayini_sec(con, {}, hs2, 1, 1, 999)
        denetle(not kabuller and mesajlar,
                "aday listesi yoksa açıkça söyleniyor",
                "sessizce geçildi — kullanıcı düğmeye basıp cevap alamaz")
        con.close()
    finally:
        _logging.disable(_logging.NOTSET)
        _tb.mesaj_gonder = eski_gonder
        _oi.gorseli_kabul_et = eski_kabul
        _oi.menuyu_geri_koy = eski_menu
        _oi.turu_getir = eski_tur


def main() -> int:
    # ⚠️ SÖZLEŞME TESTİ AĞA ÇIKMAZ. `secim.yayinlanmis_konular` artık
    # Instagram geçmişini de okuyor (mükerrer denetimi için); testte o
    # çağrı yapılırsa test ağa bağımlı hale gelir, yavaşlar ve jeton
    # yoksa patlar. Önbelleği boş doldurup API yolunu kapatıyoruz.
    sys.path.insert(0, str(KOK))
    from src import secim as _secim
    _secim._IG_GECMIS_ONBELLEK = []

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
        test_planlanmis_yayin_zaman_asimlarindan_muaf,
        test_mukerrer_instagrama_da_bakiyor,
        test_ertelemede_menu_kaliyor,
        test_ayri_mesajdaki_dugme_tur_id_tasiyor,
        test_havuza_donen_haber_metnini_koruyor,
        test_turkce_ek_toleransi,
        test_kategori_uc_yerde_tanimli,
        test_gecici_hatalar_400te_de_yakalaniyor,
        test_git_degisiklik_yok_yanlis_alarm_vermiyor,
        test_kosullu_tanimlanan_bayraklar,
        test_worker_calisiyor,
        test_gorsel_cesitliligi,
        test_icerik_filtresi,
        test_temizlik_yayinlanmisi_korur,
        test_arama_yazim_toleransi,
        test_gunluk_sinir_gercek_yayini_sayiyor,
        test_etki_dogrulamasi,
        test_hatirlatma_tum_turlari_isliyor,
        test_commons_tukenince_katman_degisiyor,
        test_gorsel_kunyesi_zorunlu,
        test_gorsel_brief_dort_yerde_tanimli,
        test_foto_ile_yazi_arasinda_olu_bant_yok,
        test_fotograf_alt_kenari_keskin_degil,
        test_kardes_gorsel_havuzu,
        test_onaylanan_gorsel_videoya_giriyor,
        test_vision_denetimi,
        test_db_yazan_workflow_commit_ediyor,
        test_olu_modul_yok,
        test_yazilan_durum_dosyasi_okunuyor,
        test_cagrilan_script_var_mi,
        test_kanal_jetonlari_denetleniyor,
        test_video_etiketleri_habere_ozel,
        test_metin_uretimi_icerik_sinyaline_bakiyor,
        test_her_dugme_workerda_karsilaniyor,
        test_worker_komutlari_python_tarafinda_var,
        test_komut_menusu_tutarli,
        test_kardes_havuzu_cagrilarda_da_acik,
        test_gorsel_aday_secimi,
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
