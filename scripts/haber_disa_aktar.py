"""
haber_disa_aktar.py — Toplanan haberleri Excel'e aktarır.

NİYE VAR:
    Önem puanını Gemini veriyor ve kalibrasyonu ancak insan yargısıyla
    karşılaştırılarak ölçülebilir. Bu script haberleri kategori kategori
    ayrı sayfalara yazıyor; kullanıcı "senin puanın" sütununu doldurup
    geri gönderdiğinde modelin nerede sapıyor olduğu görülebiliyor.

    Sapmayı ölçmek prompt'u körlemesine değiştirmekten iyi: 19 Ağustos'ta
    puan bandı iki kez elle ayarlandı ve ikisinde de etkisi ancak
    sonradan ölçülebildi.

ÇIKTI:
    data/disa-aktarim/haberler-YYYY-AA-GG.xlsx
    Her kategori ayrı sayfa. Sayfa adları Excel kurallarına uyacak
    biçimde sadeleştiriliyor (31 karakter sınırı, yasak karakterler).

ÇALIŞTIRMA:
    python scripts/haber_disa_aktar.py                # son 1 gün
    python scripts/haber_disa_aktar.py --gun 3        # son 3 gün
    python scripts/haber_disa_aktar.py --tumu         # havuzun tamamı
"""

import argparse
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from openpyxl import Workbook                        # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.utils import get_column_letter         # noqa: E402

CIKTI_KLASOR = KOK / "data" / "disa-aktarim"

# (başlık, genişlik) — sıra Excel'deki sütun sırası
SUTUNLAR = [
    ("id", 8),
    ("Yayın tarihi", 17),
    ("Kaynak", 18),
    ("Kategori", 12),
    ("Başlık", 70),
    ("Özet", 60),
    ("Gemini puanı", 13),
    ("SENİN PUANIN", 14),          # kullanıcı dolduracak
    ("Notun", 30),                 # kullanıcı dolduracak
    ("Durum", 14),
    ("Link", 45),
]

BASLIK_DOLGU = PatternFill("solid", fgColor="1F3864")
KULLANICI_DOLGU = PatternFill("solid", fgColor="FFF2CC")   # doldurulacak sütunlar


def _sayfa_adi(kategori: str) -> str:
    """
    Excel sayfa adı kuralları: 31 karakter, `[]:*?/\\` yasak, boş olamaz.
    Türkçe karakterler sorun değil ama tutarlılık için sadeleştiriyoruz.
    """
    ad = (kategori or "kategorisiz").strip() or "kategorisiz"
    ad = re.sub(r"[\[\]:*?/\\]", "-", ad)
    return ad[:31]


def haberleri_al(con, gun: int | None) -> list:
    kosul = ""
    parametre: tuple = ()
    if gun is not None:
        kosul = "WHERE cekilme_zamani > datetime('now', ?)"
        parametre = (f"-{gun} day",)
    return list(con.execute(
        f"""SELECT id, yayin_tarihi, kaynak, kategori, baslik_orj, ozet_orj,
                   onem_puani, durum, link
            FROM haberler {kosul}
            ORDER BY kategori, onem_puani DESC, yayin_tarihi DESC""",
        parametre,
    ))


def _sayfayi_kur(sayfa, haberler: list) -> None:
    for sutun, (baslik, genislik) in enumerate(SUTUNLAR, start=1):
        hucre = sayfa.cell(row=1, column=sutun, value=baslik)
        hucre.font = Font(bold=True, color="FFFFFF")
        hucre.fill = BASLIK_DOLGU
        hucre.alignment = Alignment(horizontal="center", vertical="center")
        sayfa.column_dimensions[get_column_letter(sutun)].width = genislik

    for satir, h in enumerate(haberler, start=2):
        ozet = (h["ozet_orj"] or "").replace("\n", " ").strip()
        degerler = [
            h["id"],
            (h["yayin_tarihi"] or "")[:16].replace("T", " "),
            h["kaynak"],
            h["kategori"],
            h["baslik_orj"],
            ozet[:300],
            h["onem_puani"],
            None,                       # SENİN PUANIN — boş bırakılıyor
            None,                       # Notun
            h["durum"],
            h["link"],
        ]
        for sutun, deger in enumerate(degerler, start=1):
            hucre = sayfa.cell(row=satir, column=sutun, value=deger)
            hucre.alignment = Alignment(vertical="top", wrap_text=sutun in (5, 6, 9))
            # Kullanıcının dolduracağı sütunlar renkli
            if sutun in (8, 9):
                hucre.fill = KULLANICI_DOLGU

    sayfa.freeze_panes = "A2"           # başlık satırı sabit kalsın
    sayfa.auto_filter.ref = (
        f"A1:{get_column_letter(len(SUTUNLAR))}{max(len(haberler) + 1, 2)}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gun", type=int, default=1,
                    help="son kaç günün haberleri (varsayılan 1)")
    ap.add_argument("--tumu", action="store_true",
                    help="havuzun tamamını aktar")
    a = ap.parse_args()
    gun = None if a.tumu else a.gun

    con = sqlite3.connect(KOK / "data" / "haber.db")
    con.row_factory = sqlite3.Row
    haberler = haberleri_al(con, gun)
    con.close()

    if not haberler:
        print("aktarılacak haber bulunamadı")
        return 1

    kategoriler: dict[str, list] = {}
    for h in haberler:
        kategoriler.setdefault(h["kategori"] or "kategorisiz", []).append(h)

    kitap = Workbook()
    kitap.remove(kitap.active)          # varsayılan boş sayfayı at

    # Özet sayfası en başta — hangi kategoride kaç haber var
    ozet = kitap.create_sheet("ÖZET")
    ozet.append(["Kategori", "Haber sayısı", "Gemini ort. puan", "Puansız"])
    for hucre in ozet[1]:
        hucre.font = Font(bold=True, color="FFFFFF")
        hucre.fill = BASLIK_DOLGU
    for kat in sorted(kategoriler, key=lambda k: -len(kategoriler[k])):
        liste = kategoriler[kat]
        puanlar = [h["onem_puani"] for h in liste if h["onem_puani"] is not None]
        ozet.append([
            kat, len(liste),
            round(sum(puanlar) / len(puanlar), 2) if puanlar else None,
            sum(1 for h in liste if h["onem_puani"] is None),
        ])
    ozet.append([])
    ozet.append(["TOPLAM", len(haberler)])
    for i, genislik in enumerate((22, 14, 18, 10), start=1):
        ozet.column_dimensions[get_column_letter(i)].width = genislik

    for kat in sorted(kategoriler, key=lambda k: -len(kategoriler[k])):
        _sayfayi_kur(kitap.create_sheet(_sayfa_adi(kat)), kategoriler[kat])

    CIKTI_KLASOR.mkdir(parents=True, exist_ok=True)
    damga = datetime.now().strftime("%Y-%m-%d")
    yol = CIKTI_KLASOR / f"haberler-{damga}.xlsx"
    kitap.save(yol)

    print(f"✓ {len(haberler)} haber, {len(kategoriler)} kategori -> {yol}")
    for kat in sorted(kategoriler, key=lambda k: -len(kategoriler[k])):
        print(f"    {_sayfa_adi(kat):14} {len(kategoriler[kat]):5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
