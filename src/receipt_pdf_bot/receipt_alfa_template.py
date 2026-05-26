"""Template for Alfa-Bank SBP receipt – overlay on blank PDF template.
Координаты измерены в редакторе. Шрифт Tahoma 12pt.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader, PdfWriter

ASSET_DIR = Path(__file__).parent / "assets"
FONT_DIR = ASSET_DIR / "fonts"
ALFA_ASSET_DIR = ASSET_DIR / "alfa"
BLANK_TEMPLATE = ALFA_ASSET_DIR / "blank_alfa.pdf"

# Регистрация шрифта Tahoma
FONT_NAME = "Tahoma"
font_path = FONT_DIR / "Tahoma.ttf"
if font_path.exists():
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(font_path)))
else:
    # fallback на Helvetica, если Tahoma не найден
    FONT_NAME = "Helvetica"

@dataclass
class AlfaReceiptData:
    datetime_text: str = "19.11.2025 20:21:45 мск"
    amount: str = "26 200 RUR"
    recipient_phone: str = "79273364000"
    fee: str = "0 RUR"
    recipient_bank: str = "Т-Банк"
    sender_account: str = "40817810505905043078"
    operation_number: str = "C421911251260019"
    sbp_id: str = "A5323172126061020000020011640104"
    recipient_name: str = "Роман Павлович Б"
    transfer_message: str = "Перевод денежных средств"

# Координаты (x, y) от ВЕРХНЕГО левого угла страницы (как в редакторе)
COORDS_FROM_TOP = {
    "datetime_text": (453.998, 54.467),
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

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    if not BLANK_TEMPLATE.exists():
        raise FileNotFoundError(f"Blank template not found: {BLANK_TEMPLATE}")

    # Читаем пустой шаблон
    reader = PdfReader(BLANK_TEMPLATE)
    page = reader.pages[0]
    page_width = float(page.mediabox.width)
    page_height = float(page.mediabox.height)

    # Создаём слой с текстом через ReportLab
    packet = BytesIO()
    c = canvas.Canvas(packet, pagesize=(page_width, page_height))
    c.setFont(FONT_NAME, 12)   # размер шрифта 12

    for field_name, (x_top, y_top) in COORDS_FROM_TOP.items():
        value = getattr(data, field_name, "")
        if not value:
            continue
        # Преобразуем Y: от верхнего края к нижнему
        y_bottom = page_height - y_top
        c.drawString(x_top, y_bottom, str(value))

    c.save()

    # Накладываем слой на страницу шаблона
    overlay = PdfReader(packet)
    page.merge_page(overlay.pages[0])

    # Сохраняем результат
    writer = PdfWriter()
    writer.add_page(page)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()

if __name__ == "__main__":
    # Тестовый запуск: сгенерирует файл alfa_test.pdf
    test_data = AlfaReceiptData(
        datetime_text="14.05.2026 23:09 мск",
        amount="26 200 RUR",
        recipient_phone="79273364000",
        fee="0 RUR",
        recipient_bank="Т-Банк",
        sender_account="40817810505905043078",
        operation_number="C421911251260019",
        sbp_id="A5323172126061020000020011640104",
        recipient_name="Роман Павлович Б",
        transfer_message="Перевод денежных средств"
    )
    Path("alfa_test.pdf").write_bytes(render_alfa_receipt_pdf(test_data))
