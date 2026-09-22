"""
test_dengeli_detay.py — Detay slaytlarında dengeli sayfa dağıtımı ve yetim blok koruması testleri.

Açgözlü (greedy) sayfalama mantığının sebep olduğu:
1. Önceki sayfayı tıkış tıkış doldurup alt bilgi çizgisine dayama,
2. Son sayfaya sadece 1-2 satırlık alıntıyı tek başına atıp %85 boş bırakma (yetim blok)
hatalarını kalıcı olarak engelleyen optimizasyon testleridir.
"""

import sys
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src import make_image

AYARLAR_TEST = {
    "genel": {},
    "gorsel": {
        "genislik": 1080,
        "yukseklik": 1920,
        "kenar_bosluk": 80,
        "dikey_guvenli_pay": 330,
        "kanal_ikon_boyu": 34,
        "perde_rengi": [22, 18, 46],
    },
}


def test_haber_241168_dengeli_dagilim():
    """Haber #241168 (Gazze) gerçek metniyle 3 sayfaya dengeli bölünmeli ve alıntı tek kalmamalı."""
    detay_metni = (
        "İsrail ordusu, Gazze şeridinin doğusunda işgal altında tuttuğu **Sarı Hat** bölgesinde bir iş "
        "makinesinin patlayıcı üstünden geçtiğini öne sürerek Gazze genelinde yeni saldırılar başlattı.\n\n"
        "Resmi açıklamada, D9 tipi bir buldozerin infilak eden patlayıcının üzerinden geçtiği ve kimsenin "
        "yaralanmadığı bildirildi. İsrail makamları, durumun Hamas tarafından bir ateşkes ihlali olduğunu iddia etti.\n\n"
        "İsrail'de yayımlanan Yedioth Ahronoth gazetesinde yer alan haberde ise askeri yetkililerin patlayıcının "
        "ateşkes öncesinde mi yoksa sonrasında mı yerleştirildiğini henüz belirleyemediği aktarıldı. "
        "Hamas tarafı ise suçlamalara ilişkin henüz bir açıklama yapmadı.\n\n"
        "İsrail ordusunun Filistinlilerin bulunmasına izin verilen alanları sınırlayan Sarı Hat sınırını batıya "
        "doğru genişlettiği belirtiliyor. Bölgede siviller ve yerleşim yerleri saldırıların hedefi olmaya devam ediyor.\n\n"
        "Ateşkesin sağlandığı 10 Ekim 2025'ten bu yana gerçekleşen İsrail saldırılarında 1.394 Filistinli yaşamını "
        "yitirdi, 4.839 kişi yaralandı. Ekim 2023'ten itibaren toplam can kaybı yaklaşık 74 bine ulaştı."
    )
    vurgu = ("1.394", "ateşkes sonrası can kaybı")
    alinti = ("Hamas'ın ateşkes anlaşmasını açıkça ihlal ettiğini", "İsrail Ordusu")
    neden_onemli = "Ateşkes sürecine rağmen Gazze'deki askeri hareketlilik ve sınır ihlali iddiaları bölgedeki kırılgan dengeleri ve insani krizi derinleştiriyor."

    sayfalar = make_image.detay_sayfalara_bol(
        detay=detay_metni,
        ayarlar=AYARLAR_TEST,
        vurgu=vurgu,
        alinti=alinti,
        neden_onemli=neden_onemli,
    )

    assert len(sayfalar) == 3, f"Tam 3 sayfa olmalı, {len(sayfalar)} sayfa üretildi"

    # Sayfa blok sayıları: [3, 2, 3] olmalı (eskiden [3, 3, 2] veya [3, 4, 1] idi)
    blok_sayilari = [len(s) for s in sayfalar]
    assert blok_sayilari == [3, 2, 3], f"Beklenen blok dağılımı [3, 2, 3], gerçekleşen: {blok_sayilari}"

    # Boyutları denetle
    aralik = make_image.PARAGRAF_ARASI
    boylar = [sum(b["yukseklik"] for b in s) + aralik * (len(s) - 1) for s in sayfalar]

    # Hiçbir sayfa 1066px güvenli alanı aşamaz
    for i, boy in enumerate(boylar, start=1):
        assert boy <= 1066, f"Sayfa {i} boyu ({boy}px) 1066px sınırını aştı!"

    # Sayfalar arası fark 150px'den az olmalı (mükemmel optik denge)
    fark = max(boylar) - min(boylar)
    assert fark <= 150, f"Sayfalar arası boy farkı ({fark}px) çok fazla! Boylar: {boylar}"

    # 3. Sayfada alıntı tek başına (yetim) kalmamalı, Neden Önemli ve gelişme paragrafıyla kapanmalı
    son_sayfa_tipleri = [b["tip"] for b in sayfalar[2]]
    assert "alinti" in son_sayfa_tipleri, "3. sayfada alıntı bulunmalı"
    assert len(son_sayfa_tipleri) >= 2, "3. sayfada alıntı tek başına kalamaz"


def test_alinti_yetim_blok_korumasi():
    """Alıntı toplam blok sayısı >= 3 iken ASLA son sayfada tek başına kalamaz."""
    detay = (
        "Avrupa Merkez Bankası faiz kararını açıkladı. Politika faizi 25 baz puan düşürüldü. "
        "Piyasa analistleri kararın enflasyon hedefleriyle uyumlu olduğunu vurguladı. "
        "Ekonomistler faiz indirim döngüsünün devam etmesini bekliyor. "
        "Yıl sonu büyüme tahminleri ise yukarı yönlü revize edildi."
    )
    alinti = ("Enflasyonla mücadelede kararlıyız ancak büyüme dengesini de gözetiyoruz.", "Christine Lagarde")

    sayfalar = make_image.detay_sayfalara_bol(
        detay=detay,
        ayarlar=AYARLAR_TEST,
        alinti=alinti,
    )

    for i, sayfa in enumerate(sayfalar, start=1):
        if len(sayfa) == 1:
            assert sayfa[0]["tip"] != "alinti", f"Sayfa {i}'de alıntı tek başına yetim kalmış!"


def test_vurgu_sayisi_asla_tek_basina_kalmaz():
    """Vurgu sayısı sayfası mutlaka en az bir metin paragrafı da içermelidir."""
    detay = "Merkez Bankası rezervleri tarihi zirveye ulaştı. Swap hariç net rezervler artıya geçti."
    vurgu = ("156,4 Milyar $", "Brüt Rezerv")

    sayfalar = make_image.detay_sayfalara_bol(
        detay=detay,
        ayarlar=AYARLAR_TEST,
        vurgu=vurgu,
    )

    assert len(sayfalar) >= 1
    ilk_sayfa = sayfalar[0]
    assert len(ilk_sayfa) >= 2, "İlk sayfada vurgu sayısının yanında mutlaka metin olmalı"
    assert ilk_sayfa[0]["tip"] == "sayi"
    assert ilk_sayfa[1]["tip"] == "metin"


def test_kisa_haber_tek_sayfada_kalir():
    """Kısa haber gereksiz yere 2 sayfaya bölünmemelidir."""
    kisa_detay = "Sanayi ve Teknoloji Bakanlığı yeni teşvik paketini açıkladı. Pakette yerli üretime tam destek var."
    sayfalar = make_image.detay_sayfalara_bol(
        detay=kisa_detay,
        ayarlar=AYARLAR_TEST,
    )
    assert len(sayfalar) == 1, f"Kısa haber 1 sayfaya sığmalıydı, {len(sayfalar)} sayfa üretildi"
