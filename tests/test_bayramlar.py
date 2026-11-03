"""
tests/test_bayramlar.py — Milli ve Dini Bayramlar Özel Afiş Motoru Testleri
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from PIL import Image
import numpy as np

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

def test_bayram_takvimi_tespiti():
    from src import bayramlar

    # 1. Sabit Milli Bayramlar
    b29 = bayramlar.bugun_bayram_mi(datetime(2026, 10, 29))
    assert b29 is not None
    assert b29["kod"] == "29_ekim"
    assert "Cumhuriyet" in b29["ad"]

    b23 = bayramlar.bugun_bayram_mi(datetime(2026, 4, 23))
    assert b23 is not None
    assert b23["kod"] == "23_nisan"

    b19 = bayramlar.bugun_bayram_mi(datetime(2026, 5, 19))
    assert b19 is not None
    assert b19["kod"] == "19_mayis"

    b30 = bayramlar.bugun_bayram_mi(datetime(2026, 8, 30))
    assert b30 is not None
    assert b30["kod"] == "30_agustos"

    b10 = bayramlar.bugun_bayram_mi(datetime(2026, 11, 10))
    assert b10 is not None
    assert b10["kod"] == "10_kasim"

    # 2. Değişken Dini Bayramlar
    rb = bayramlar.bugun_bayram_mi(datetime(2026, 3, 20))
    assert rb is not None
    assert rb["kod"] == "ramazan_bayrami"

    kb = bayramlar.bugun_bayram_mi(datetime(2026, 5, 27))
    assert kb is not None
    assert kb["kod"] == "kurban_bayrami"

    # 3. Sıradan Gün (Bayram Yok)
    normal = bayramlar.bugun_bayram_mi(datetime(2026, 2, 17))
    assert normal is None

def test_bayram_afisleri_tam_boyut_ve_sifir_kenar_boslugu():
    from src import bayramlar

    b_info = bayramlar.bugun_bayram_mi(datetime(2026, 10, 29))
    assert b_info is not None

    oneriler = bayramlar.bayram_onerileri_uret(b_info)
    assert len(oneriler) == 3

    for o in oneriler:
        # Feed boyutu tam 1080x1350 (4:5) olmalı
        f_im = Image.open(o["feed_path"])
        assert f_im.size == (1080, 1350), f"Feed boyutu yanlış: {f_im.size}"

        # Story boyutu tam 1080x1920 (9:16) olmalı
        s_im = Image.open(o["story_path"])
        assert s_im.size == (1080, 1920), f"Story boyutu yanlış: {s_im.size}"

        # Kenar Analizi (Sol ve Sağ kenarların 0. pikseli boş veya yapay çerçeveli olmamalı)
        arr_f = np.array(f_im)
        sol_f = arr_f[:, 0].mean()
        sag_f = arr_f[:, -1].mean()
        # Sıfır (0.0) tamamen boş/hatalı çizim demektir
        assert sol_f > 5.0, f"Sol kenarda çizim yok (boşluk hatası): {sol_f}"
        assert sag_f > 5.0, f"Sağ kenarda çizim yok (boşluk hatası): {sag_f}"

        # Açıklama metninde markdown yıldızı (**) ASLA olmamalı
        assert "**" not in o["caption"], "Caption'da yasaklı markdown (**) bulundu!"

def test_komut_entegrasyonu():
    from src.komutlar import MESAJSIZ_KOMUTLAR, KOMUT_MENUSU

    assert "bayram" in MESAJSIZ_KOMUTLAR
    assert "bayram_sec" in MESAJSIZ_KOMUTLAR

    bayram_cmd = next((d for d in KOMUT_MENUSU if d["command"] == "bayram"), None)
    assert bayram_cmd is not None
    assert len(bayram_cmd["description"]) <= 38
    assert bayram_cmd["description"].startswith("✍️")
