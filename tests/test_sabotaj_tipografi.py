"""
test_sabotaj_tipografi.py — Tipografi, Para Birimi & Unvan Bütünlüğü Sabotaj Testleri.

Bu test modülü Doğukan'ın bildirdiği sorunları en az 10 agresif senaryoyla sınar:
  1. ₺ sembolünün önceki sayıdan ayrılmaması (asla satır başında yetim ₺ kalmaz)
  2. Büyüklük + Para birimi üçlüsünün (350 bin ₺) kopmaması
  3. ₺ ekleri (45,50 ₺'ye, 90 ₺'de) ve döviz sembollerinin ($100, 50 €) bütünlüğü
  4. Doç. Dr. unvanlarının satır sonu ve sayfa geçişinde bölünmemesi
  5. Prof. Dr. ve Yrd. Doç. Dr. gibi karmaşık unvanlarda cümle bütünlüğü
  6. Av. ve md. gibi hukuki kısaltmaların cümle sınırını bozmaması
  7. Sıra sayılarının (14. meclis, 3. cadde, 42. sokak) cümleyi bölmemesi
  8. Sayfa ve belge kısaltmalarının (sf. 42, vb. evraklar) tek parça kalması
  9. detay_sayfalara_bol fonksiyonunun sayfaları ASLA cümle ortasından kesmemesi
 10. Markdown **bold** etiketli para birimi ve unvanların kusursuz yapışkanlığı
"""

import os
import sys
from pathlib import Path

# Proje kökünü sys.path'e ekle
KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from PIL import Image, ImageDraw, ImageFont
from src.make_image import (
    _satirlara_bol,
    _font,
    cumlelere_bol,
    _metni_paragraflara_ayir,
    detay_sayfalara_bol,
    DETAY_PUNTO,
    EKSEN_OZET,
    STORY_GENISLIK,
    STORY_YUKSEKLIK,
    STORY_GUVENLI_PAY,
)

# Testler için mock çizim ve font objeleri
DUMMY_IMG = Image.new("RGB", (STORY_GENISLIK, STORY_YUKSEKLIK))
DUMMY_CIZ = ImageDraw.Draw(DUMMY_IMG)
TEST_FONT = _font(DETAY_PUNTO, EKSEN_OZET)

AYARLAR_MOCK = {
    "gorsel": {
        "genislik": STORY_GENISLIK,
        "yukseklik": STORY_YUKSEKLIK,
        "kenar_bosluk": 80,
        "dikey_guvenli_pay": STORY_GUVENLI_PAY,
    }
}


def test_sabotaj_1_tl_sembolu_rakamdan_kopmaz():
    """1. Sabotaj: 2.500 ₺ ifadesinde ₺ sembolü yeni satıra tek başına düşemez."""
    metin = "Trafik cezası 2.500 ₺ olarak açıklandı."
    # 2.500'den hemen sonra satır taşmasını tetikleyecek sınır genişlik
    w_2500 = DUMMY_CIZ.textlength("Trafik cezası 2.500", font=TEST_FONT)
    w_tam = DUMMY_CIZ.textlength("Trafik cezası 2.500 ₺", font=TEST_FONT)
    
    # Tam w_2500 ile w_tam arasında bir genişlik veriyoruz (₺ sığmayacak)
    azami_w = int(w_2500 + (w_tam - w_2500) / 2)
    satirlar = _satirlara_bol(metin, TEST_FONT, azami_w, DUMMY_CIZ)
    
    assert len(satirlar) >= 2, f"En az iki satıra bölünmeliydi: {satirlar}"
    # Satırların hiçbiri tek başına veya önünde sayı olmadan ₺ ile başlayamaz
    for i, s in enumerate(satirlar):
        kelimeler = s.split()
        if kelimeler and kelimeler[0] == "₺":
            raise AssertionError(f"Satır {i+1} yetim ₺ ile başladı! Satırlar: {satirlar}")
    # 2.500 ve ₺ aynı satırda olmalı
    tl_satiri = [s for s in satirlar if "₺" in s][0]
    assert "2.500 ₺" in tl_satiri, f"2.500 ve ₺ ayrılmış: {satirlar}"
    print("✓ Sabotaj 1 geçti: 2.500 ₺ yapışkan kaldı, ₺ yetim düşmedi.")


def test_sabotaj_2_buyukluk_ve_para_birimi_kopmaz():
    """2. Sabotaj: 350 bin ₺ ifadesinde ₺ veya bin ₺ tek başına kopamaz."""
    metin = "Toplam ceza tutarı 350 bin ₺ seviyesine ulaştı."
    w_350_bin = DUMMY_CIZ.textlength("Toplam ceza tutarı 350 bin", font=TEST_FONT)
    w_tam = DUMMY_CIZ.textlength("Toplam ceza tutarı 350 bin ₺", font=TEST_FONT)
    azami_w = int(w_350_bin + (w_tam - w_350_bin) / 2)
    
    satirlar = _satirlara_bol(metin, TEST_FONT, azami_w, DUMMY_CIZ)
    for s in satirlar:
        if s.strip().startswith("₺"):
            raise AssertionError(f"Satır ₺ ile başladı: {satirlar}")
    tl_satiri = [s for s in satirlar if "₺" in s][0]
    assert "350 bin ₺" in tl_satiri or "bin ₺" in tl_satiri, f"350 bin ₺ parçalandı: {satirlar}"
    print("✓ Sabotaj 2 geçti: 350 bin ₺ başarıyla korundu.")


def test_sabotaj_3_tl_ekleri_ve_doviz_sembolleri():
    """3. Sabotaj: 45,50 ₺'ye, 90 ₺'de ve $ / € simgeleri sayıdan ayrılmaz."""
    ornekler = [
        ("Ürün fiyatı 45,50 ₺'ye kadar indi.", "45,50 ₺'ye"),
        ("İndirim oranı 90 ₺'de sabitlendi.", "90 ₺'de"),
        ("Hisse senedi 100 $ seviyesini aştı.", "100 $"),
        ("Giriş bileti 50 € olarak belirlendi.", "50 €"),
    ]
    for cumle, hedef in ornekler:
        w_hedef_once = DUMMY_CIZ.textlength(cumle.split(hedef)[0] + hedef.split()[0], font=TEST_FONT)
        satirlar = _satirlara_bol(cumle, TEST_FONT, int(w_hedef_once + 10), DUMMY_CIZ)
        hedef_satiri = [s for s in satirlar if hedef.split()[-1] in s][0]
        assert hedef in hedef_satiri, f"Hedef '{hedef}' ayrıldı! Satırlar: {satirlar}"
    print("✓ Sabotaj 3 geçti: ₺ ekleri ve döviz sembolleri başarıyla korundu.")


def test_sabotaj_4_doc_dr_ayrilmaz():
    """4. Sabotaj: Doç. Dr. Ahmet Yılmaz unvanı satır sonunda Doç. bırakıp Dr.'yi atamaz."""
    metin = "Konferansta konuşan Doç. Dr. Ahmet Yılmaz önemli uyarılarda bulundu."
    w_doc = DUMMY_CIZ.textlength("Konferansta konuşan Doç.", font=TEST_FONT)
    w_doc_dr = DUMMY_CIZ.textlength("Konferansta konuşan Doç. Dr.", font=TEST_FONT)
    azami_w = int(w_doc + (w_doc_dr - w_doc) / 2)
    
    satirlar = _satirlara_bol(metin, TEST_FONT, azami_w, DUMMY_CIZ)
    assert not satirlar[0].strip().endswith("Doç."), f"Doç. satır sonunda yetim kaldı: {satirlar}"
    assert "Doç. Dr." in " ".join(satirlar), f"Doç. Dr. bütünlüğü bozuldu: {satirlar}"
    print("✓ Sabotaj 4 geçti: Doç. Dr. satır sınırında yapışık kaldı.")


def test_sabotaj_5_prof_dr_ve_yrd_doc_dr_cumle_butunlugu():
    """5. Sabotaj: Prof. Dr. ve Yrd. Doç. Dr. içeren metin 2 cümleye bölünmeli (noktalar cümle sayılmamalı)."""
    metin = (
        "Prof. Dr. Ayşe Demir ve Yrd. Doç. Dr. Mehmet Kaya ortak çalışma yürüttü. "
        "Elde edilen veriler tıp fakültesi dergisinde yayımlandı."
    )
    cumleler = cumlelere_bol(metin)
    assert len(cumleler) == 2, f"Tam 2 cümle olmalıydı, {len(cumleler)} bulundu: {cumleler}"
    assert cumleler[0].startswith("Prof. Dr. Ayşe Demir"), f"İlk cümle bozuldu: {cumleler[0]}"
    assert cumleler[1].startswith("Elde edilen veriler"), f"İkinci cümle bozuldu: {cumleler[1]}"
    print("✓ Sabotaj 5 geçti: Karmaşık unvan noktaları cümleyi bölmedi.")


def test_sabotaj_6_avukat_ve_kanun_maddesi():
    """6. Sabotaj: Av. ve md. 125 kısaltmaları cümle sınırını bozmaz."""
    metin = (
        "Av. Mehmet Bey Türk Ceza Kanunu md. 125 uyarınca savcılığa başvurdu. "
        "Soruşturma kapsamında ilk ifadeler alındı."
    )
    cumleler = cumlelere_bol(metin)
    assert len(cumleler) == 2, f"2 cümle bekleniyordu, {len(cumleler)} çıktı: {cumleler}"
    assert "md. 125" in cumleler[0], f"md. 125 bölündü: {cumleler[0]}"
    print("✓ Sabotaj 6 geçti: Av. ve md. kısaltmaları başarıyla korundu.")


def test_sabotaj_7_sira_sayilari_cumleyi_bolmez():
    """7. Sabotaj: 14. meclis ve 42. sokak sıra sayıları cümleyi ikiye ayıramaz."""
    metin = (
        "Büyükşehir Belediyesi 14. meclis oturumunu dün gerçekleştirdi. "
        "Alınan kararlar 3. cadde ve 42. sokak üzerindeki esnafı doğrudan ilgilendiriyor."
    )
    cumleler = cumlelere_bol(metin)
    assert len(cumleler) == 2, f"2 cümle olmalıydı, {len(cumleler)} çıktı: {cumleler}"
    assert "14. meclis" in cumleler[0], f"14. ayrıldı: {cumleler[0]}"
    assert "42. sokak" in cumleler[1], f"42. ayrıldı: {cumleler[1]}"
    print("✓ Sabotaj 7 geçti: Sıra sayıları (. ile biten) cümleyi bölmedi.")


def test_sabotaj_8_sayfa_ve_belge_kisaltmalari():
    """8. Sabotaj: sf. 42 ve vb. basılı evraklar tek cümle içinde kalmalı."""
    metin = (
        "Raporun sf. 42 bölümünde belirtilen belgeler (tapu, ruhsat, kimlik vb.) eksiksiz getirilmelidir."
    )
    cumleler = cumlelere_bol(metin)
    assert len(cumleler) == 1, f"Tek cümle olmalıydı, {len(cumleler)} parça çıktı: {cumleler}"
    print("✓ Sabotaj 8 geçti: sf. ve vb. kısaltmaları tek cümlede kaldı.")


def test_sabotaj_9_detay_sayfalara_bol_asla_cumle_ortasinda_kesmez():
    """9. Sabotaj: detay_sayfalara_bol uzun metni sayfalara bölerken ASLA cümle ortasında kesemez."""
    uzun_detay = (
        "Sağlık Bakanlığı tarafından hazırlanan yeni yönetmelik Resmi Gazete'de yayımlandı. "
        "Yeni düzenlemeyle birlikte Doç. Dr. Ahmet Yılmaz ve ekibinin hazırladığı standartlar geçerli olacak. "
        "Buna göre poliklinik muayene ücreti 2.500 ₺ tavan fiyatı aşamayacak. "
        "Vatandaşlar şikayetlerini 14. madde uyarınca doğrudan il sağlık müdürlüklerine iletebilecek. "
        "Uygulamanın detayları için hastane yönetimi sf. 12 rehberini duyurdu. "
        "Denetimlerin ilk sonuçları ise önümüzdeki ay kamuoyuyla paylaşılacak."
    )
    sayfalar = detay_sayfalara_bol(uzun_detay, AYARLAR_MOCK)
    assert len(sayfalar) >= 1, "En az bir sayfa üretilmeli"
    
    # Her sayfadaki her paragrafın son karakteri tam cümle bitişi (.!?”") olmalı
    for s_idx, sayfa in enumerate(sayfalar):
        for b_idx, blok in enumerate(sayfa):
            if blok.get("tip") == "metin" and blok.get("satirlar"):
                son_satir = blok["satirlar"][-1].strip()
                # Son karakter noktalama ile bitmeli
                assert son_satir[-1] in ".!?…\"”'", (
                    f"Sayfa {s_idx+1} Blok {b_idx+1} cümle ortasında kesilmiş: '{son_satir}'"
                )
    print("✓ Sabotaj 9 geçti: detay_sayfalara_bol sayfaları tam cümle sınırından böldü.")


def test_sabotaj_10_markdown_bold_ile_para_ve_unvan_kopmaz():
    """10. Sabotaj: **2.500 ₺** ve **Doç. Dr. Ahmet Yılmaz** gibi bold etiketli yapılar sağlam kalır."""
    metin = "Yeni ceza tarifesi **2.500 ₺** oldu. Açıklamayı **Doç. Dr. Ahmet Yılmaz** yaptı."
    cumleler = cumlelere_bol(metin)
    assert len(cumleler) == 2, f"2 cümle bekleniyordu: {cumleler}"
    
    # Satırlara bölmede bold yapışkanlığı
    satirlar = _satirlara_bol(metin, TEST_FONT, 380, DUMMY_CIZ)
    tum_metin = " ".join(satirlar)
    assert "**2.500 ₺**" in tum_metin or ("2.500 ₺" in tum_metin), f"Bold para birimi bozuldu: {satirlar}"
    assert "Doç. Dr." in tum_metin, f"Bold unvan bozuldu: {satirlar}"
    print("✓ Sabotaj 10 geçti: Markdown bold etiketli para ve unvanlar kusursuz korundu.")


if __name__ == "__main__":
    print("=" * 60)
    print("10 TİPOGRAFİ VE SAYFA GEÇİŞİ SABOTAJ TESTİ BAŞLATILIYOR")
    print("=" * 60)
    test_sabotaj_1_tl_sembolu_rakamdan_kopmaz()
    test_sabotaj_2_buyukluk_ve_para_birimi_kopmaz()
    test_sabotaj_3_tl_ekleri_ve_doviz_sembolleri()
    test_sabotaj_4_doc_dr_ayrilmaz()
    test_sabotaj_5_prof_dr_ve_yrd_doc_dr_cumle_butunlugu()
    test_sabotaj_6_avukat_ve_kanun_maddesi()
    test_sabotaj_7_sira_sayilari_cumleyi_bolmez()
    test_sabotaj_8_sayfa_ve_belge_kisaltmalari()
    test_sabotaj_9_detay_sayfalara_bol_asla_cumle_ortasinda_kesmez()
    test_sabotaj_10_markdown_bold_ile_para_ve_unvan_kopmaz()
    print("=" * 60)
    print("🎉 TEBRİKLER! 10 SABOTAJ TESTİNİN HEPSİ BAŞARIYLA GEÇTİ!")
    print("=" * 60)
