"""Template for T-Bank card transfer receipt – coordinates adjusted by -10.368 pt vertically.
Штамп присутствует. Все top пересчитаны по новым замерам.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from datetime import datetime

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# ========== ШРИФТЫ ==========
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

_FONT_CANDIDATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (FONT_REGULAR, (str(FONT_DIR / "TinkoffSans-Regular.ttf"), "~/AppData/Local/Microsoft/Windows/Fonts/Roboto-Regular.ttf", "C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/roboto/Roboto-Regular.ttf")),
    (FONT_BOLD, (str(FONT_DIR / "TinkoffSans-Medium.ttf"), "~/AppData/Local/Microsoft/Windows/Fonts/Roboto-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/roboto/Roboto-Bold.ttf")),
    (FONT_RUBLE, (str(FONT_DIR / "ALSRubl.ttf"), str(FONT_DIR / "TinkoffSans-Regular.ttf"), "C:/Windows/Fonts/arial.ttf")),
    (FONT_RUBLE_BOLD, (str(FONT_DIR / "ALSRubl.ttf"), str(FONT_DIR / "TinkoffSans-Medium.ttf"), "C:/Windows/Fonts/arialbd.ttf")),
    (FONT_FALLBACK, (str(FONT_DIR / "DejaVuSans.ttf"), "C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")),
)

_fonts_registered = False

def _ensure_fonts_registered() -> None:
    global _fonts_registered
    if _fonts_registered:
        return
    for name, candidates in _FONT_CANDIDATES:
        for path in candidates:
            candidate = Path(path).expanduser()
            if candidate.exists():
                pdfmetrics.registerFont(TTFont(name, str(candidate)))
                break
        else:
            raise RuntimeError(f"Font {name} not found.")
    _fonts_registered = True

def _font_supports_text(font_name: str, text: str) -> bool:
    font = pdfmetrics.getFont(font_name)
    char_to_glyph = getattr(font.face, "charToGlyph", {})
    return all(ord(char) in char_to_glyph for char in text)

def _font_for_char(preferred_font: str, char: str) -> str:
    if _font_supports_text(preferred_font, char):
        return preferred_font
    return FONT_FALLBACK

def _mixed_text_width(c: canvas.Canvas, text: str, font_name: str, size: float) -> float:
    return sum(c.stringWidth(char, _font_for_char(font_name, char), size) for char in text)

def _draw_text(c: canvas.Canvas, x: float, y: float, text: str, font_name: str, size: float) -> None:
    cursor_x = x
    for char in text:
        char_font = _font_for_char(font_name, char)
        c.setFont(char_font, size)
        c.drawString(cursor_x, y, char)
        cursor_x += c.stringWidth(char, char_font, size)

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

# ========== РАЗМЕРЫ СТРАНИЦЫ ==========
PAGE_WIDTH = 270.0
PAGE_HEIGHT = 471.0

# ========== КООРДИНАТЫ (Слева, Сверху от верхнего края) – скорректированы на -10.368 ==========
LOGO_LEFT = 121.0
LOGO_TOP = 28.0                # не меняется (не текст)
LOGO_WIDTH = 28.0
LOGO_HEIGHT = 28.0

DATE_LEFT = 20.648
DATE_TOP = 81.100 - 10.368      # 70.732

TOTAL_LABEL_LEFT = 21.240       # новое значение из примера
TOTAL_LABEL_TOP = 96.082 - 10.368  # 85.714

TOTAL_AMOUNT_RIGHT_X = 249.0    # правый край (не меняем)
TOTAL_AMOUNT_TOP = 95.842 - 10.368   # 85.474

TOP_LINE_LEFT = 18.0
TOP_LINE_TOP = 120.5 - 10.368        # 110.132
TOP_LINE_WIDTH = 232.0

FIELDS = [  # (label, label_left, label_top, field, value_left, value_top)
    ("Перевод", 20.783, 136.298 - 10.368, "transfer_type", 186.833, 136.298 - 10.368),
    ("Статус", 20.432, 156.217 - 10.368, "status", 216.777, 156.298 - 10.368),
    ("Комиссия", 20.783, 197.298 - 10.368, "fee", 198.883, 197.298 - 10.368),
    ("Отправитель", 20.432, 217.217 - 10.368, "sender_name", 183.665, 217.298 - 10.368),
    ("Карта получателя", 20.783, 237.298 - 10.368, "recipient_card", 181.447, 237.082 - 10.368),
    ("Получатель", 20.783, 257.298 - 10.368, "recipient_name", 219.063, 257.298 - 10.368),
    ("Банк получателя", 20.783, 277.298 - 10.368, "recipient_bank", 214.152, 276.569 - 10.368),
]

SUM_LABEL_LEFT = 20.432
SUM_LABEL_TOP = 176.217 - 10.368       # 165.849
SUM_VALUE_RIGHT_X = 249.0
SUM_VALUE_TOP = 176.217 - 10.368       # 165.849
SUM_VALUE_SIZE = 9.0

# Сумма (число и рубль отдельно уже не нужны, используем _draw_money_right)

BOTTOM_LINE_LEFT = 19.0
BOTTOM_LINE_TOP = 389.5 - 10.368       # 379.132
BOTTOM_LINE_WIDTH = 232.0

RECEIPT_LEFT = 20.783
RECEIPT_TOP = 406.150 - 10.368         # 395.782
RECEIPT_SIZE = 9.0

NOTE_LEFT = 20.783
NOTE_TOP = 422.529 - 10.368            # 412.161
NOTE_SIZE = 9.0

SUPPORT_LABEL_LEFT = 20.432
SUPPORT_LABEL_TOP = 439.529 - 10.368   # 429.161
SUPPORT_EMAIL_LEFT = 92.640
SUPPORT_EMAIL_TOP = 437.180 - 10.368   # 426.812
SUPPORT_SIZE = 9.0

STAMP_LEFT = 66.0
STAMP_TOP = 304.0 - 10.368             # 293.632
STAMP_WIDTH = 175.0
STAMP_HEIGHT = 63.23

# Цвета
COLOR_TEXT = HexColor("#333333")
COLOR_MUTED = HexColor("#909090")
COLOR_ACCENT = HexColor("#ffdd2d")
COLOR_LINK = HexColor("#1771d6")
COLOR_STAMP = HexColor("#126cba")

# ========== ФУНКЦИИ РИСОВАНИЯ ==========
def _draw_accent_line(c: canvas.Canvas, x: float, y: float, width: float) -> None:
    c.setStrokeColor(COLOR_ACCENT)
    c.setLineWidth(1.0)
    c.line(x, y, x + width, y)

def _draw_logo(c: canvas.Canvas) -> None:
    if LOGO_PATH.exists():
        y = PAGE_HEIGHT - LOGO_TOP - LOGO_HEIGHT
        c.drawImage(str(LOGO_PATH), LOGO_LEFT, y, width=LOGO_WIDTH, height=LOGO_HEIGHT, preserveAspectRatio=True, mask='auto')
        return
    # fallback
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
    c.setFont(FONT_BOLD, 17.0)
    c.drawCentredString(135.0, PAGE_HEIGHT - 47.7, "D")
    c.restoreState()

def _draw_demo_stamp(c: canvas.Canvas) -> None:
    if STAMP_PATH.exists():
        y = PAGE_HEIGHT - STAMP_TOP - STAMP_HEIGHT
        c.drawImage(str(STAMP_PATH), STAMP_LEFT, y, width=STAMP_WIDTH, height=STAMP_HEIGHT, preserveAspectRatio=True, mask='auto')
        return
    c.saveState()
    c.setFillColor(COLOR_STAMP)
    c.setFont(FONT_BOLD, 12)
    y_text = PAGE_HEIGHT - STAMP_TOP - 15
    _draw_text(c, STAMP_LEFT, y_text, "ДЕМО-БАНК", FONT_BOLD, 12)
    c.restoreState()

def _draw_money_right(c: canvas.Canvas, y: float, value: str, size: float, right_x: float, bold: bool = False) -> None:
    amount = value.strip().removesuffix("₽").rstrip()
    ruble = "i"
    amount_font = FONT_BOLD if bold else FONT_REGULAR
    ruble_font = FONT_RUBLE_BOLD if bold else FONT_RUBLE
    ruble_width = c.stringWidth(ruble, ruble_font, size)
    amount_width = _mixed_text_width(c, amount, amount_font, size)
    start_x = right_x - amount_width - ruble_width
    c.setFillColor(COLOR_TEXT)
    _draw_text(c, start_x, y, amount, amount_font, size)
    if bold:
        c.saveState()
        c.setFillColor(COLOR_TEXT)
        c.setStrokeColor(COLOR_TEXT)
        c.setLineWidth(size / 30.0)
        text_obj = c.beginText(start_x + amount_width, y)
        text_obj.setFont(ruble_font, size)
        text_obj.setTextRenderMode(2)
        text_obj.textOut(ruble)
        c.drawText(text_obj)
        c.restoreState()
    else:
        c.setFont(ruble_font, size)
        c.drawString(start_x + amount_width, y, ruble)

def render_receipt_17_card_pdf(data: Receipt17CardData) -> bytes:
    _ensure_fonts_registered()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setTitle(f"receipt_card_{datetime.now().strftime('%d.%m.%Y')}.pdf")
    c.setAuthor("receipt-pdf-bot")

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
        value = getattr(data, field)
        _draw_text(c, vx, y(vt), value, FONT_REGULAR, 9.0)

    # Сумма
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
