"""Template for T-Bank card transfer receipt – очередной сдвиг Итого.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from datetime import datetime
import logging

from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_REGULAR = "Receipt17Sans"
FONT_BOLD = "Receipt17Sans-Bold"
FONT_RUBLE = "Receipt17Ruble"
FONT_RUBLE_BOLD = "Receipt17Ruble-Bold"
FONT_FALLBACK = "Receipt17Fallback"

ASSET_DIR = Path(__file__).parent / "assets"
FONT_DIR = ASSET_DIR / "fonts"
RECEIPT17_ASSET_DIR = ASSET_DIR / "receipt17"
LOGO_PATH = RECEIPT17_ASSET_DIR / "logo.png"
STAMP_PATH = RECEIPT17_ASSET_DIR / "stamp.png"

_FONT_CANDIDATES = {
    FONT_REGULAR: [FONT_DIR / "TinkoffSans-Regular.ttf", Path("~/AppData/Local/Microsoft/Windows/Fonts/Roboto-Regular.ttf").expanduser(), Path("C:/Windows/Fonts/arial.ttf")],
    FONT_BOLD: [FONT_DIR / "TinkoffSans-Medium.ttf", Path("~/AppData/Local/Microsoft/Windows/Fonts/Roboto-Bold.ttf").expanduser(), Path("C:/Windows/Fonts/arialbd.ttf")],
    FONT_RUBLE: [FONT_DIR / "ALSRubl.ttf", FONT_DIR / "TinkoffSans-Regular.ttf", Path("C:/Windows/Fonts/arial.ttf")],
    FONT_RUBLE_BOLD: [FONT_DIR / "ALSRubl.ttf", FONT_DIR / "TinkoffSans-Medium.ttf", Path("C:/Windows/Fonts/arialbd.ttf")],
    FONT_FALLBACK: [FONT_DIR / "DejaVuSans.ttf", Path("C:/Windows/Fonts/segoeui.ttf")],
}

_fonts_registered = False

def _ensure_fonts_registered() -> None:
    global _fonts_registered
    if _fonts_registered:
        return
    for logical_name, candidates in _FONT_CANDIDATES.items():
        for path in candidates:
            if not path.exists():
                continue
            try:
                pdfmetrics.registerFont(TTFont(logical_name, str(path)))
                break
            except Exception:
                continue
    _fonts_registered = True

def _get_font(logical_name: str) -> str:
    if logical_name in pdfmetrics._fonts:
        return logical_name
    if logical_name in (FONT_BOLD, FONT_RUBLE_BOLD):
        return "Helvetica-Bold"
    return "Helvetica"

def _draw_text(c: canvas.Canvas, x: float, y: float, text: str, font_name: str, size: float) -> None:
    c.setFont(_get_font(font_name), size)
    c.drawString(x, y, text)

@dataclass(slots=True)
class Receipt17CardData:
    datetime_text: str = "13.02.2026  19:00:35"
    total: str = "10 000 ₽"
    transfer_type: str = "По номеру карты"
    status: str = "Успешно"
    amount: str = "10 000 ₽"
    fee: str = "Без комиссии"
    sender_name: str = "Михаил Видинеев"
    recipient_card: str = "220220******7357"
    recipient_name: str = "Ильяс А."
    recipient_bank: str = "Сбербанк"
    receipt_number: str = "№ 1-127-176-643-532"
    support_label: str = "Служба поддержки"
    support_email: str = "fb@tbank.ru"
    note_text: str = "По вопросам зачисления обращайтесь к получателю"

PAGE_WIDTH = 270.0
PAGE_HEIGHT = 471.0

# Координаты (после всех сдвигов)
LOGO_LEFT = 121.0
LOGO_TOP = 28.0
LOGO_WIDTH = 28.0
LOGO_HEIGHT = 28.0

DATE_LEFT = 22.592
DATE_TOP = 86.38

# Итого: было 23.48 + 4.48 = 27.96
TOTAL_LABEL_LEFT = 27.96
TOTAL_LABEL_TOP = 106.45

TOTAL_AMOUNT_RIGHT_X = 249.0
TOTAL_AMOUNT_TOP = 95.842

TOP_LINE_LEFT = 18.0
TOP_LINE_TOP = 120.5
TOP_LINE_WIDTH = 232.0

FIELDS = [
    ("Перевод", 20.783, 136.298, "transfer_type", 186.833, 136.298),
    ("Статус", 20.432, 156.217, "status", 216.777, 156.298),
    ("Комиссия", 20.783, 197.298, "fee", 198.883, 197.298),
    ("Отправитель", 20.432, 217.217, "sender_name", 183.665, 217.298),
    ("Карта получателя", 20.783, 237.298, "recipient_card", 181.447, 237.082),
    ("Получатель", 20.783, 257.298, "recipient_name", 219.063, 257.298),
    ("Банк получателя", 20.783, 277.298, "recipient_bank", 214.152, 276.569),
]

SUM_LABEL_LEFT = 20.432
SUM_LABEL_TOP = 176.217
SUM_VALUE_RIGHT_X = 249.0
SUM_VALUE_TOP = 176.217
SUM_VALUE_SIZE = 9.0

BOTTOM_LINE_LEFT = 19.0
BOTTOM_LINE_TOP = 389.5
BOTTOM_LINE_WIDTH = 232.0

RECEIPT_LEFT = 20.783
RECEIPT_TOP = 406.150
RECEIPT_SIZE = 9.0

NOTE_LEFT = 20.783
NOTE_TOP = 422.529
NOTE_SIZE = 9.0

SUPPORT_LABEL_LEFT = 20.432
SUPPORT_LABEL_TOP = 439.529
SUPPORT_EMAIL_LEFT = 92.640
SUPPORT_EMAIL_TOP = 437.180
SUPPORT_SIZE = 9.0

STAMP_LEFT = 66.0
STAMP_TOP = 304.0
STAMP_WIDTH = 175.0
STAMP_HEIGHT = 63.23

COLOR_TEXT = HexColor("#333333")
COLOR_MUTED = HexColor("#909090")
COLOR_ACCENT = HexColor("#ffdd2d")
COLOR_LINK = HexColor("#1771d6")
COLOR_STAMP = HexColor("#126cba")

def _draw_accent_line(c: canvas.Canvas, x: float, y: float, width: float) -> None:
    c.setStrokeColor(COLOR_ACCENT)
    c.setLineWidth(1.0)
    c.line(x, y, x + width, y)

def _draw_logo(c: canvas.Canvas) -> None:
    if LOGO_PATH.exists():
        y = PAGE_HEIGHT - LOGO_TOP - LOGO_HEIGHT
        c.drawImage(str(LOGO_PATH), LOGO_LEFT, y, width=LOGO_WIDTH, height=LOGO_HEIGHT, preserveAspectRatio=True, mask='auto')
        return
    c.saveState()
    c.setFillColor(COLOR_ACCENT)
    path = c.beginPath()
    path.moveTo(121.0, PAGE_HEIGHT - 28.0)
    path.lineTo(149.0, PAGE_HEIGHT - 28.0)
    path.lineTo(149.0, PAGE_HEIGHT - 48.0)
    path.curveTo(149.0, PAGE_HEIGHT - 52.0, 143.0, PAGE_HEIGHT - 55.0, 135.0, PAGE_HEIGHT - 59.0)
    path.curveTo(127.0, PAGE_HEIGHT - 55.0, 121.0, PAGE_HEIGHT - 52.0, 121.0, PAGE_HEIGHT - 48.0)
    path.close()
    c.drawPath(path, stroke=0, fill=1)
    c.setFillColor(HexColor("#111111"))
    c.setFont(_get_font(FONT_BOLD), 17.0)
    c.drawCentredString(135.0, PAGE_HEIGHT - 47.7, "D")
    c.restoreState()

def _draw_demo_stamp(c: canvas.Canvas) -> None:
    if STAMP_PATH.exists():
        y = PAGE_HEIGHT - STAMP_TOP - STAMP_HEIGHT
        c.drawImage(str(STAMP_PATH), STAMP_LEFT, y, width=STAMP_WIDTH, height=STAMP_HEIGHT, preserveAspectRatio=True, mask='auto')
        return
    c.saveState()
    c.setFillColor(COLOR_STAMP)
    c.setFont(_get_font(FONT_BOLD), 12)
    y_text = PAGE_HEIGHT - STAMP_TOP - 15
    c.drawString(STAMP_LEFT, y_text, "ДЕМО-БАНК")
    c.restoreState()

def _draw_money_right(c: canvas.Canvas, y: float, value: str, size: float, right_x: float, bold: bool = False) -> None:
    amount = value.strip().removesuffix("₽").rstrip()
    ruble = "₽"
    font_name = FONT_BOLD if bold else FONT_REGULAR
    font = _get_font(font_name)
    ruble_width = c.stringWidth(ruble, font, size)
    amount_width = c.stringWidth(amount, font, size)
    start_x = right_x - amount_width - ruble_width
    c.setFillColor(COLOR_TEXT)
    c.setFont(font, size)
    c.drawString(start_x, y, amount)
    c.drawString(start_x + amount_width, y, ruble)

def render_receipt_17_card_pdf(data: Receipt17CardData) -> bytes:
    _ensure_fonts_registered()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setTitle(f"receipt_card_{datetime.now().strftime('%d.%m.%Y')}.pdf")

    def y(top: float) -> float:
        return PAGE_HEIGHT - top

    _draw_logo(c)

    c.setFillColor(COLOR_MUTED)
    _draw_text(c, DATE_LEFT, y(DATE_TOP), data.datetime_text, FONT_REGULAR, 8.0)

    c.setFillColor(COLOR_TEXT)
    _draw_text(c, TOTAL_LABEL_LEFT, y(TOTAL_LABEL_TOP), "Итого", FONT_BOLD, 16.0)
    _draw_money_right(c, y(TOTAL_AMOUNT_TOP), data.total, 16.0, TOTAL_AMOUNT_RIGHT_X, bold=True)

    _draw_accent_line(c, TOP_LINE_LEFT, y(TOP_LINE_TOP), TOP_LINE_WIDTH)

    for label, lx, lt, field, vx, vt in FIELDS:
        c.setFillColor(COLOR_TEXT)
        _draw_text(c, lx, y(lt), label, FONT_REGULAR, 9.0)
        _draw_text(c, vx, y(vt), getattr(data, field), FONT_REGULAR, 9.0)

    c.setFillColor(COLOR_TEXT)
    _draw_text(c, SUM_LABEL_LEFT, y(SUM_LABEL_TOP), "Сумма", FONT_REGULAR, 9.0)
    _draw_money_right(c, y(SUM_VALUE_TOP), data.amount, SUM_VALUE_SIZE, SUM_VALUE_RIGHT_X, bold=False)

    _draw_accent_line(c, BOTTOM_LINE_LEFT, y(BOTTOM_LINE_TOP), BOTTOM_LINE_WIDTH)

    c.setFillColor(COLOR_TEXT)
    _draw_text(c, RECEIPT_LEFT, y(RECEIPT_TOP), f"Квитанция  {data.receipt_number}", FONT_REGULAR, RECEIPT_SIZE)

    c.setFillColor(COLOR_MUTED)
    _draw_text(c, NOTE_LEFT, y(NOTE_TOP), data.note_text, FONT_REGULAR, NOTE_SIZE)

    c.setFillColor(COLOR_TEXT)
    _draw_text(c, SUPPORT_LABEL_LEFT, y(SUPPORT_LABEL_TOP), data.support_label + " ", FONT_REGULAR, SUPPORT_SIZE)
    c.setFillColor(COLOR_LINK)
    _draw_text(c, SUPPORT_EMAIL_LEFT, y(SUPPORT_EMAIL_TOP), data.support_email, FONT_REGULAR, SUPPORT_SIZE)

    _draw_demo_stamp(c)

    c.setStrokeColor(HexColor("#c2c2c2"))
    c.setLineWidth(0.25)
    c.line(1.0, 1.0, PAGE_WIDTH - 1.0, 1.0)

    c.showPage()
    c.save()
    return buf.getvalue()

if __name__ == "__main__":
    test_data = Receipt17CardData(
        datetime_text="16.05.2026 16:46:31",
        total="10 ₽",
        amount="10 ₽",
        recipient_card="220220*******7357",
        recipient_name="Ильяс А.",
        recipient_bank="Сбербанк",
        receipt_number="№ 1-132-150-477-390"
    )
    Path("receipt-17-card-demo.pdf").write_bytes(render_receipt_17_card_pdf(test_data))
