"""Template for Alfa-Bank SBP receipt – встраивание Tahoma из файла.
Размер ~500-600 КБ, но чек визуально идеален.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import io
import fitz

ASSET_DIR = Path(__file__).parent / "assets"
FONT_DIR = ASSET_DIR / "fonts"
ALFA_ASSET_DIR = ASSET_DIR / "alfa"
BLANK_TEMPLATE = ALFA_ASSET_DIR / "blank_alfa.pdf"
FONT_PATH = FONT_DIR / "Tahoma.ttf"

if not FONT_PATH.exists():
    raise FileNotFoundError(f"Font Tahoma.ttf not found at {FONT_PATH}")

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

# Финальные координаты после калибровки
RAW_COORDS = {
    "header_datetime": (452.788, 62.75),
    "transfer_datetime": (35.45, 263.40),
    "amount": (35.45, 177.612),
    "fee": (35.45, 220.506),
    "recipient_phone": (304.75, 177.612),
    "recipient_bank": (304.75, 220.506),
    "sender_account": (304.75, 263.40),
    "operation_number": (35.45, 306.294),
    "sbp_id": (304.75, 306.294),
    "recipient_name": (35.45, 349.188),
    "transfer_message": (304.75, 349.188),
}

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    doc = fitz.open(BLANK_TEMPLATE)
    page = doc[0]
    doc.set_metadata({})

    # Встраиваем шрифт Tahoma
    page.insert_font(fontname="Tahoma", fontfile=str(FONT_PATH))
    fontname = "Tahoma"

    def add_text(x, y, text, fontsize, color=(0,0,0)):
        page.insert_text((x, y), text, fontsize=fontsize, fontname=fontname, color=color)

    for field, (x, y) in RAW_COORDS.items():
        if field in ("header_datetime", "transfer_datetime"):
            continue
        value = getattr(data, field, "")
        if value:
            add_text(x, y, str(value), 12, (0,0,0))

    x, y = RAW_COORDS["header_datetime"]
    add_text(x, y, data.header_datetime, 11, (0.5, 0.5, 0.5))

    x, y = RAW_COORDS["transfer_datetime"]
    add_text(x, y, data.transfer_datetime, 12, (0,0,0))

    out = io.BytesIO()
    doc.save(out, garbage=4, deflate=True, clean=True)
    doc.close()
    return out.getvalue()
