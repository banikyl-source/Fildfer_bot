"""Template for Alfa-Bank SBP receipt – exact coordinates and sizes."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from datetime import datetime

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ASSET_DIR = Path(__file__).parent / "assets"
FONT_DIR = ASSET_DIR / "fonts"
ALFA_ASSET_DIR = ASSET_DIR / "alfa"

FONT_NAME = "AlfaTahoma"
_fonts_registered = False

def _ensure_fonts():
    global _fonts_registered
    if _fonts_registered:
        return
    font_path = FONT_DIR / "Tahoma.ttf"
    if not font_path.exists():
        font_path = FONT_DIR / "DejaVuSans.ttf"
    if font_path.exists():
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(font_path)))
    else:
        raise RuntimeError("No font found for Alfa receipt")
    _fonts_registered = True

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

PAGE_WIDTH = 600.0
PAGE_HEIGHT = 840.0

# === ТЕКСТОВЫЕ КООРДИНАТЫ (Y от нижнего края) ===
LEFT_X = 35.45
RIGHT_X = 304.75

HEADER_LABEL_X = 484.40
HEADER_LABEL_Y = PAGE_HEIGHT - 37.975   # 802.025
HEADER_DATE_X = 453.998
HEADER_DATE_Y = PAGE_HEIGHT - 54.467    # 785.533

TITLE_Y = 736.78

LEFT_LABELS = [
    ("Сумма перевода", 693.70),
    ("Комиссия", 650.80),
    ("Дата и время перевода", 607.91),
    ("Номер операции", 565.02),
    ("Получатель", 522.12),
]
LEFT_VALUES = [
    ("amount", 676.29),
    ("fee", 633.39),
    ("datetime_text", 590.50),
    ("operation_number", 547.61),
    ("recipient_name", 504.71),
]

RIGHT_LABELS = [
    ("Номер телефона получателя", 693.70),
    ("Банк получателя", 650.80),
    ("Счёт списания", 607.91),
    ("Идентификатор операции в СБП", 565.02),
    ("Сообщение получателю", 522.12),
]
RIGHT_VALUES = [
    ("recipient_phone", 676.29),
    ("recipient_bank", 633.39),
    ("sender_account", 590.50),
    ("sbp_id", 547.61),
    ("transfer_message", 504.71),
]

# === ИЗОБРАЖЕНИЯ (координаты нижнего левого угла) ===
LOGO_X = 35.45
LOGO_Y = 769.55
LOGO_WIDTH = 30.0
LOGO_HEIGHT = 46.0

STAMP1_X = 35.45
STAMP1_Y = 373.68
STAMP1_WIDTH = 201.0
STAMP1_HEIGHT = 85.09

STAMP2_X = 262.85
STAMP2_Y = 68.55
STAMP2_WIDTH = 297.0
STAMP2_HEIGHT = 35.0

# Цвета
COLOR_GRAY = HexColor("#7e7e83")
COLOR_LIGHT_GRAY = HexColor("#808080")
COLOR_BLACK = HexColor("#000000")

def _draw_text(c, x, y, text, size, color):
    c.setFillColor(color)
    c.setFont(FONT_NAME, size)
    c.drawString(x, y, text)

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    _ensure_fonts()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    current_date = datetime.now().strftime("%d.%m.%Y %H:%M мск")
    c.setTitle(f"alfa_receipt_{datetime.now().strftime('%d.%m.%Y')}.pdf")

    # Логотип
    logo_path = ALFA_ASSET_DIR / "logo.png"
    if logo_path.exists():
        c.drawImage(str(logo_path), LOGO_X, LOGO_Y, width=LOGO_WIDTH, height=LOGO_HEIGHT, preserveAspectRatio=True, mask='auto')

    # Штамп 1
    stamp1_path = ALFA_ASSET_DIR / "stamp.png"
    if stamp1_path.exists():
        c.drawImage(str(stamp1_path), STAMP1_X, STAMP1_Y, width=STAMP1_WIDTH, height=STAMP1_HEIGHT, preserveAspectRatio=True, mask='auto')

    # Штамп 2
    stamp2_path = ALFA_ASSET_DIR / "stamp2.png"
    if stamp2_path.exists():
        c.drawImage(str(stamp2_path), STAMP2_X, STAMP2_Y, width=STAMP2_WIDTH, height=STAMP2_HEIGHT, preserveAspectRatio=True, mask='auto')

    # Тексты
    _draw_text(c, HEADER_LABEL_X, HEADER_LABEL_Y, "Сформирована", 11, COLOR_GRAY)
    _draw_text(c, HEADER_DATE_X, HEADER_DATE_Y, current_date, 11, COLOR_GRAY)
    _draw_text(c, LEFT_X, TITLE_Y, "Квитанция о переводе по СБП", 21, COLOR_BLACK)

    for label, y in LEFT_LABELS:
        _draw_text(c, LEFT_X, y, label, 11, COLOR_LIGHT_GRAY)
    for field, y in LEFT_VALUES:
        _draw_text(c, LEFT_X, y, getattr(data, field), 12, COLOR_BLACK)

    for label, y in RIGHT_LABELS:
        _draw_text(c, RIGHT_X, y, label, 11, COLOR_LIGHT_GRAY)
    for field, y in RIGHT_VALUES:
        _draw_text(c, RIGHT_X, y, getattr(data, field), 12, COLOR_BLACK)

    c.showPage()
    c.save()
    return buf.getvalue()
