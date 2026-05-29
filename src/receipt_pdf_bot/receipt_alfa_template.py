"""Template for Alfa-Bank SBP receipt – все координаты сдвинуты вниз на 0.121 pt для компенсации высоты шрифта.
Цвет даты в шапке #7e7e83.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from pypdf import PdfReader, PdfWriter

ASSET_DIR = Path(__file__).parent / "assets"
FONT_DIR = ASSET_DIR / "fonts"
ALFA_ASSET_DIR = ASSET_DIR / "alfa"
BLANK_TEMPLATE = ALFA_ASSET_DIR / "blank_alfa.pdf"

FONT_NAME = "Tahoma"
font_path = FONT_DIR / "Tahoma.ttf"
if font_path.exists():
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(font_path)))
else:
    FONT_NAME = "Helvetica"

COLOR_GRAY = HexColor("#7e7e83")
COLOR_BLACK = HexColor("#000000")

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

# Координаты из последней калибровки, затем все y_top увеличены на 0.121
SHIFT = 0.121

COORDS_FROM_TOP = {
    "amount": (35.45, 177.48 + SHIFT),
    "fee": (35.45, 220.374 + SHIFT),
    "recipient_phone": (304.75, 177.48 + SHIFT),
    "recipient_bank": (304.75, 220.374 + SHIFT),
    "sender_account": (304.75, 263.268 + SHIFT),
    "operation_number": (35.45, 306.294 + SHIFT),
    "sbp_id": (304.75, 306.162 + SHIFT),
    "recipient_name": (35.45, 349.056 + SHIFT),
    "transfer_message": (304.75, 349.056 + SHIFT),
}

HEADER_DATE_COORDS = (452.788, 62.629 + SHIFT)      # 62.75
TRANSFER_DATE_COORDS = (35.45, 263.268 + SHIFT)     # 263.389

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    if not BLANK_TEMPLATE.exists():
        raise FileNotFoundError(f"Blank template not found: {BLANK_TEMPLATE}")

    reader = PdfReader(BLANK_TEMPLATE)
    page = reader.pages[0]
    page_width = float(page.mediabox.width)
    page_height = float(page.mediabox.height)

    packet = BytesIO()
    c = canvas.Canvas(packet, pagesize=(page_width, page_height))

    # Основные поля
    c.setFont(FONT_NAME, 12)
    c.setFillColor(COLOR_BLACK)
    for field_name, (x_top, y_top) in COORDS_FROM_TOP.items():
        value = getattr(data, field_name, "")
        if value:
            y_bottom = page_height - y_top
            c.drawString(x_top, y_bottom, str(value))

    # Дата в шапке
    c.setFont(FONT_NAME, 11)
    c.setFillColor(COLOR_GRAY)
    x_top, y_top = HEADER_DATE_COORDS
    y_bottom = page_height - y_top
    c.drawString(x_top, y_bottom, data.header_datetime)

    # Дата перевода
    c.setFont(FONT_NAME, 12)
    c.setFillColor(COLOR_BLACK)
    x_top, y_top = TRANSFER_DATE_COORDS
    y_bottom = page_height - y_top
    c.drawString(x_top, y_bottom, data.transfer_datetime)

    c.save()

    overlay = PdfReader(packet)
    page.merge_page(overlay.pages[0])

    writer = PdfWriter()
    writer.add_page(page)
    writer.add_metadata({
        '/Title': 'Квитанция о переводе по СБП',
        '/Author': 'АО «АЛЬФА-БАНК»',
        '/Subject': 'Перевод по СБП',
        '/Creator': 'АО «АЛЬФА-БАНК»',
        '/Producer': 'АО «АЛЬФА-БАНК»',
    })
    out = BytesIO()
    writer.write(out)
    return out.getvalue()

if __name__ == "__main__":
    test_data = AlfaReceiptData()
    with open("alfa_test.pdf", "wb") as f:
        f.write(render_alfa_receipt_pdf(test_data))
    print("✅ Сгенерирован alfa_test.pdf с компенсацией смещения")
