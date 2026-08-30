"""
slayt_yonetimi.py — Slayt, Görsel ve İçerik Düzenleme Motoru

Telegram üzerinden fotoğraf değiştirme, yapay zeka ile görsel üretme,
metin düzenleme, slayt taşıma/silme ve albüm tazeleme işlemlerini yönetir.
"""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path

from src import (
    db,
    fetch_article,
    fetch_photo,
    fetch_stock,
    make_image,
    slaytlar,
    telegram_bot,
    upload_image,
)

log = logging.getLogger("slayt_yonetimi")
