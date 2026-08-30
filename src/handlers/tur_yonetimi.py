"""
tur_yonetimi.py — Tur Yaşam Döngüsü, Aday Seçimi ve Arama Motoru

Tur onayları, yeniden seçim, tura haber ekleme/çıkarma, havuz güncelleme,
arama ve erteleme/iptal süreçlerini yönetir.
"""

from __future__ import annotations

import html
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone

from src import (
    db,
    fetch_news,
    generate_text,
    hata_bildir,
    secim,
    slaytlar,
    telegram_bot,
    upload_image,
)

log = logging.getLogger("tur_yonetimi")
