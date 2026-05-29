"""Template for Alfa-Bank SBP receipt – PyMuPDF direct text insertion.
Координаты amount скорректированы. Остальные поля без изменений.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import fitz

ASSET_DIR = Path(__file__).parent / "assets"
FONT_DIR = ASSET_DIR / "fonts"
ALFA_ASSET_DIR = ASSET_DIR / "alfa"
BLANK_TEMPLATE = ALFA_ASSET_DIR / "blank_alfa.pdf"

FONT_PATH = FONT_DIR / "Tahoma.ttf"
if not FONT_PATH.exists():
    FONT_PATH = None

@dataclass
class AlfaReceiptData:
    header_datetime: str = "14.05.2026 23:09 мск"
    transfer_datetime: str = "19.11.2025 20:21:45 мск"
    amount: str = "26 200 RUR"
    recipient_phone: str = "79273364000"
    fee: str = "0 RUR"
    recipient_bank: str = "Т-Банк"
    sender_account: str = "40817810505905043078"
    operation_number: str = "C421911251260019"
    sbp_id: str = "A5323172126061020000020011640104"
    recipient_name: str = "Роман Павлович Б"
    transfer_message: str = "Перевод денежных средств"

# Координаты (x, y) – как в Master PDF Editor (Слева, Сверху)
RAW_COORDS = {
    "header_datetime": (452.788, 62.75),        # исправлено ранее
    "transfer_datetime": (36.770, 254.364),
    "amount": (36.134, 177.612),               # исправлено: +0.048 по X, +9.036 по Y
    "fee": (35.942, 211.470),
    "recipient_phone": (305.326, 168.576),
    "recipient_bank": (304.750, 211.650),
    "sender_account": (304.990, 254.340),
    "operation_number": (35.834, 297.258),
    "sbp_id": (304.702, 297.258),
    "recipient_name": (36.338, 340.332),
    "transfer_message": (305.638, 340.332),
}

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    if not BLANK_TEMPLATE.exists():
        raise FileNotFoundError(f"Blank template not found: {BLANK_TEMPLATE}")

    doc = fitz.open(BLANK_TEMPLATE)
    page = doc[0]

    doc.set_metadata({
        "title": "Квитанция о переводе по СБП",
        "author": "АО «АЛЬФА-БАНК»",
        "subject": "Перевод по СБП",
        "creator": "АО «АЛЬФА-БАНК»",
        "producer": "АО «АЛЬФА-БАНК»"
    })

    fontname = "helv"
    if FONT_PATH and FONT_PATH.exists():
        try:
            page.insert_font(fontname="Tahoma", fontfile=str(FONT_PATH))
            fontname = "Tahoma"
        except Exception:
            pass

    def add_text(x, y, text, fontsize, color=(0,0,0)):
        page.insert_text((x, y), text, fontsize=fontsize, fontname=fontname, color=color)

    # Основные поля (чёрные, 12pt)
    for field, (x, y) in RAW_COORDS.items():
        if field in ("header_datetime", "transfer_datetime"):
            continue
        value = getattr(data, field, "")
        if value:
            add_text(x, y, str(value), 12, (0,0,0))

    # Дата в шапке (серая, 11pt)
    x, y = RAW_COORDS["header_datetime"]
    add_text(x, y, data.header_datetime, 11, (0.5, 0.5, 0.5))

    # Дата перевода (чёрная, 12pt)
    x, y = RAW_COORDS["transfer_datetime"]
    add_text(x, y, data.transfer_datetime, 12, (0,0,0))

    out = doc.write()
    doc.close()
    return out

if __name__ == "__main__":
    test_data = AlfaReceiptData()
    with open("alfa_corrected.pdf", "wb") as f:
        f.write(render_alfa_receipt_pdf(test_data))
    print("✅ Готово, координаты amount обновлены")
