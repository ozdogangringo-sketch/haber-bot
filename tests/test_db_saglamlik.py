"""
test_db_saglamlik.py — Veritabanı sağlamlık kontrolü ve bozuk dosya push koruması testleri.
"""

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from src import db_senkron


def test_saglam_veritabani_dogrulanir():
    """Geçerli bir SQLite veritabanı veritabani_saglam_mi testini geçmelidir."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        with sqlite3.connect(tmp.name) as con:
            con.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, baslik TEXT)")
            con.execute("INSERT INTO test (baslik) VALUES ('Haber')")
            con.commit()
        assert db_senkron.veritabani_saglam_mi(tmp.name) is True


def test_bos_veya_kucuk_dosya_reddedilir():
    """0 bayt veya çok küçük dosya reddedilmelidir."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        tmp.write(b"")
        tmp.flush()
        assert db_senkron.veritabani_saglam_mi(tmp.name) is False


def test_bozuk_headerli_dosya_reddedilir():
    """İlk 16 baytı sıfırlanmış veya bozulmuş (def5d1b hatası) dosya reddedilmelidir."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        # 4096 bayt sıfır + sahte veri
        tmp.write(b"\x00" * 4096 + b"fake sqlite content" * 100)
        tmp.flush()
        assert db_senkron.veritabani_saglam_mi(tmp.name) is False


def test_varolmayan_dosya_reddedilir():
    """Mevcut olmayan dosya yolu False dönmelidir."""
    assert db_senkron.veritabani_saglam_mi("data/olmayan_veritabani_xyz.db") is False
