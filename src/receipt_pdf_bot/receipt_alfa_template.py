"""Template for Alfa-Bank SBP receipt – две отдельные даты: шапка и дата перевода.
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
    header_datetime: str = "14.05.2026 23:09 мск"      # дата в шапке (серая, 11pt)
    transfer_datetime: str = "19.11.2025 20:21:45 мск" # дата под "Дата и время перевода" (чёрная, 12pt)
    amount: str = "26 200 RUR"
    recipient_phone: str = "79273364000"
    fee: str = "0 RUR"
    recipient_bank: str = "Т-Банк"
    sender_account: str = "40817810505905043078"
    operation_number: str = "C421911251260019"
    sbp_id: str = "A5323172126061020000020011640104"
    recipient_name: str = "Роман Павлович Б"
    transfer_message: str = "Перевод денежных средств"

# Координаты для основных полей (чёрные, 12pt)
COORDS_FROM_TOP = {
    "amount": (36.086, 168.576),
    "fee": (35.942, 211.470),
    "recipient_phone": (305.326, 168.576),
    "recipient_bank": (304.750, 211.650),
    "sender_account": (304.990, 254.340),
    "operation_number": (35.834, 297.258),
    "sbp_id": (304.702, 297.258),
    "recipient_name": (36.338, 340.332),
    "transfer_message": (305.638, 340.332),
}

# Координаты для двух дат
HEADER_DATE_COORDS = (453.998, 54.467)   # серая, 11pt
TRANSFER_DATE_COORDS = (36.770, 254.364) # чёрная, 12pt

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    if not BLANK_TEMPLATE.exists():
        raise FileNotFoundError(f"Blank template not found: {BLANK_TEMPLATE}")

    reader = PdfReader(BLANK_TEMPLATE)
    page = reader.pages[0]
    page_width = float(page.mediabox.width)
    page_height = float(page.mediabox.height)

    packet = BytesIO()
    c = canvas.Canvas(packet, pagesize=(page_width, page_height))

    # Основные поля (чёрные, 12pt)
    c.setFont(FONT_NAME, 12)
    c.setFillColor(COLOR_BLACK)
    for field_name, (x_top, y_top) in COORDS_FROM_TOP.items():
        value = getattr(data, field_name, "")
        if value:
            y_bottom = page_height - y_top
            c.drawString(x_top, y_bottom, str(value))

    # Дата в шапке (серая, 11pt)
    c.setFont(FONT_NAME, 11)
    c.setFillColor(COLOR_GRAY)
    x_top, y_top = HEADER_DATE_COORDS
    y_bottom = page_height - y_top
    c.drawString(x_top, y_bottom, data.header_datetime)

    # Дата перевода (чёрная, 12pt)
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
    out = BytesIO()
    writer.write(out)
    return out.getvalue()

if __name__ == "__main__":
    test_data = AlfaReceiptData()
    Path("alfa_test.pdf").write_bytes(render_alfa_receipt_pdf(test_data))
