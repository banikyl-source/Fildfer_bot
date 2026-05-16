"""Template for Alfa-Bank SBP receipt with Tahoma (regular only)."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from datetime import datetime

from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ASSET_DIR = Path(__file__).parent / "assets"
FONT_DIR = ASSET_DIR / "fonts"
ALFA_ASSET_DIR = ASSET_DIR / "alfa"

FONT_REGULAR = "AlfaRegular"
FONT_FALLBACK = "AlfaFallback"

# Используем только обычный Tahoma для всего текста
_FONT_CANDIDATES = [
    (FONT_REGULAR, [
        FONT_DIR / "Tahoma.ttf",
        FONT_DIR / "DejaVuSans.ttf",
        FONT_DIR / "TinkoffSans-Regular.ttf"
    ]),
    (FONT_FALLBACK, [
        FONT_DIR / "Tahoma.ttf",
        FONT_DIR / "DejaVuSans.ttf"
    ]),
]

_fonts_registered = False

def _ensure_fonts():
    global _fonts_registered
    if _fonts_registered:
        return
    for name, paths in _FONT_CANDIDATES:
        for p in paths:
            if p and p.exists():
                pdfmetrics.registerFont(TTFont(name, str(p)))
                break
        else:
            raise RuntimeError(f"Font {name} not found")
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
LEFT_X = 35.45
RIGHT_X = 304.75

LOGO_X = 262.85
LOGO_Y = PAGE_HEIGHT - 771.45
LOGO_WIDTH = 35.0
LOGO_HEIGHT = 35.0

HEADER_LABEL_Y = 806.44
HEADER_DATE_Y = 790.15
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

LAST_Y = 504.71
STAMP1_Y = LAST_Y - 50
STAMP2_Y = STAMP1_Y - 90

COLOR_GRAY = HexColor("#7e7e83")
COLOR_LIGHT_GRAY = HexColor("#808080")
COLOR_BLACK = HexColor("#000000")

def _draw_text(c, x, y, text, font, size, color):
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawString(x, y, text)

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    _ensure_fonts()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    current_date = datetime.now().strftime("%d.%m.%Y %H:%M мск")
    c.setTitle(f"alfa_receipt_{datetime.now().strftime('%d.%m.%Y')}.pdf")

    logo_path = ALFA_ASSET_DIR / "logo.png"
    if logo_path.exists():
        c.drawImage(str(logo_path), LOGO_X, LOGO_Y, width=LOGO_WIDTH, height=LOGO_HEIGHT, preserveAspectRatio=True, mask='auto')

    _draw_text(c, LEFT_X, HEADER_LABEL_Y, "Сформирована", FONT_REGULAR, 11, COLOR_GRAY)
    _draw_text(c, LEFT_X, HEADER_DATE_Y, current_date, FONT_REGULAR, 11, COLOR_GRAY)
    _draw_text(c, LEFT_X, TITLE_Y, "Квитанция о переводе по СБП", FONT_REGULAR, 21, COLOR_BLACK)  # используем обычный шрифт

    for label, y in LEFT_LABELS:
        _draw_text(c, LEFT_X, y, label, FONT_REGULAR, 11, COLOR_LIGHT_GRAY)
    for field, y in LEFT_VALUES:
        value = getattr(data, field)
        _draw_text(c, LEFT_X, y, value, FONT_REGULAR, 12, COLOR_BLACK)

    for label, y in RIGHT_LABELS:
        _draw_text(c, RIGHT_X, y, label, FONT_REGULAR, 11, COLOR_LIGHT_GRAY)
    for field, y in RIGHT_VALUES:
        value = getattr(data, field)
        _draw_text(c, RIGHT_X, y, value, FONT_REGULAR, 12, COLOR_BLACK)

    # Штампы
    stamp1_path = ALFA_ASSET_DIR / "stamp.png"
    stamp2_path = ALFA_ASSET_DIR / "stamp2.png"

    if stamp1_path.exists():
        c.drawImage(str(stamp1_path), LEFT_X, STAMP1_Y - 40, width=250, height=80, preserveAspectRatio=True, mask='auto')
    else:
        y = STAMP1_Y
        lines1 = ["АО «АЛЬФА-БАНК»", "БИК 044525593 ИНН 7728168971", "к/сч 30101810200000000593", "", "ПЕРЕВОД ВЫПОЛНЕН"]
        for line in lines1:
            if line:
                _draw_text(c, LEFT_X, y, line, FONT_REGULAR, 8, COLOR_BLACK)
            y -= 12

    if stamp2_path.exists():
        c.drawImage(str(stamp2_path), LEFT_X, STAMP2_Y - 30, width=250, height=70, preserveAspectRatio=True, mask='auto')
    else:
        y = STAMP2_Y
        lines2 = ["alfabank.ru", "АО «АЛЬФА-БАНК»", "ул. Каланчёвская, 27, Москва, 107078", "+7 495 620 91 91", "mail@alfabank.ru"]
        for line in lines2:
            if line:
                _draw_text(c, LEFT_X, y, line, FONT_REGULAR, 8, COLOR_BLACK)
            y -= 12

    c.showPage()
    c.save()
    return buf.getvalue()
