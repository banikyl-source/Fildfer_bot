"""Template for T-Bank card transfer receipt – exact coordinates from Master PDF Editor."""

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
    (
        FONT_REGULAR,
        (
            str(FONT_DIR / "TinkoffSans-Regular-full.ttf"),
            str(FONT_DIR / "TinkoffSans-Regular.otf"),
            str(FONT_DIR / "TinkoffSans-Regular-reportlab.ttf"),
            str(FONT_DIR / "TinkoffSans-Regular.ttf"),
            "~/AppData/Local/Microsoft/Windows/Fonts/Roboto-Regular.ttf",
            "~/AppData/Local/Microsoft/Windows/Fonts/NotoSans-Regular.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Regular.ttf",
            "/usr/share/fonts/truetype/roboto/Roboto-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ),
    ),
    (
        FONT_BOLD,
        (
            str(FONT_DIR / "TinkoffSans-Medium-full.ttf"),
            str(FONT_DIR / "TinkoffSans-Medium.otf"),
            str(FONT_DIR / "TinkoffSans-Medium-reportlab.ttf"),
            str(FONT_DIR / "TinkoffSans-Medium.ttf"),
            "~/AppData/Local/Microsoft/Windows/Fonts/Roboto-Bold.ttf",
            "~/AppData/Local/Microsoft/Windows/Fonts/NotoSans-Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Bold.ttf",
            "/usr/share/fonts/truetype/roboto/Roboto-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
    ),
    (
        FONT_RUBLE,
        (
            str(FONT_DIR / "ALSRubl-reportlab.ttf"),
            str(FONT_DIR / "ALSRubl.ttf"),
            str(FONT_DIR / "TinkoffSans-Regular.ttf"),
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ),
    ),
    (
        FONT_RUBLE_BOLD,
        (
            str(FONT_DIR / "ALSRubl-reportlab.ttf"),
            str(FONT_DIR / "ALSRubl.ttf"),
            str(FONT_DIR / "TinkoffSans-Medium.ttf"),
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
    ),
    (
        FONT_FALLBACK,
        (
            str(FONT_DIR / "DejaVuSans.ttf"),
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ),
    ),
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

def _font_for_text(preferred_font: str, text: str) -> str:
    if _font_supports_text(preferred_font, text):
        return preferred_font
    return FONT_FALLBACK

def _font_for_char(preferred_font: str, char: str) -> str:
    if _font_supports_text(preferred_font, char):
        return preferred_font
    return FONT_FALLBACK

def _mixed_text_width(c: canvas.Canvas, text: str, font_name: str, size: float) -> float:
    return sum(c.stringWidth(char, _font_for_char(font_name, char), size) for char in text)

def _draw_text(
    c: canvas.Canvas,
    x: float,
    y: float,
    text: str,
    font_name: str,
    size: float,
) -> None:
    cursor_x = x
    for char in text:
        char_font = _font_for_char(font_name, char)
        c.setFont(char_font, size)
        c.drawString(cursor_x, y, char)
        cursor_x += c.stringWidth(char, char_font, size)

def _draw_right_text(
    c: canvas.Canvas,
    x: float,
    y: float,
    text: str,
    font_name: str,
    size: float,
) -> None:
    _draw_text(c, x - _mixed_text_width(c, text, font_name, size), y, text, font_name, size)

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

# ========== РАЗМЕРЫ СТРАНИЦЫ (из оригинала) ==========
PAGE_WIDTH = 270.0
PAGE_HEIGHT = 471.0

# ========== КООРДИНАТЫ (Y = PAGE_HEIGHT - top) ==========
# Логотип (нижний левый угол)
LOGO_X = 121.0
LOGO_Y = PAGE_HEIGHT - 28.0 - 28.0
LOGO_W = 28.0
LOGO_H = 28.0

# Штамп
STAMP_X = 66.0
STAMP_Y = PAGE_HEIGHT - 304.0 - 63.23
STAMP_W = 175.0
STAMP_H = 63.23

# Жёлтые линии
TOP_LINE_X = 19.0
TOP_LINE_Y = PAGE_HEIGHT - 120.5 - 2.0
TOP_LINE_W = 232.0

BOTTOM_LINE_X = 19.0
BOTTOM_LINE_Y = PAGE_HEIGHT - 389.5 - 2.0
BOTTOM_LINE_W = 232.0

# Дата
DATE_X = 20.648
DATE_Y = PAGE_HEIGHT - 81.1
DATE_FONT = FONT_REGULAR
DATE_SIZE = 8.0

# Итого (левое слово)
TOTAL_LABEL_X = 20.120
TOTAL_LABEL_Y = PAGE_HEIGHT - 96.082
TOTAL_LABEL_FONT = FONT_BOLD
TOTAL_LABEL_SIZE = 16.0

# Сумма итога (правая часть)
TOTAL_AMOUNT_X = 218.260   # правый край, от которого выравнивается текст
TOTAL_AMOUNT_Y = PAGE_HEIGHT - 95.842
TOTAL_AMOUNT_FONT = FONT_BOLD
TOTAL_AMOUNT_SIZE = 16.0

# Символ рубля итога
RUBLE_X = 239.913
RUBLE_Y = PAGE_HEIGHT - 95.143
RUBLE_FONT = FONT_RUBLE_BOLD
RUBLE_SIZE = 16.0

# Основные поля (левая колонка – название, правая – значение)
FIELDS = [
    ("Перевод", 20.783, 136.298, "transfer_type", 186.833, 136.298),
    ("Статус", 20.432, 156.217, "status", 216.777, 156.298),
    ("Сумма", 20.432, 176.217, "amount", 233.489, 176.217),
    ("Комиссия", 20.783, 197.298, "fee", 198.883, 197.298),
    ("Отправитель", 20.432, 217.217, "sender_name", 183.665, 217.298),
    ("Карта получателя", 20.783, 237.298, "recipient_card", 181.447, 237.082),
    ("Получатель", 20.783, 257.298, "recipient_name", 219.063, 257.298),
    ("Банк получателя", 20.783, 277.298, "recipient_bank", 214.152, 276.569),
]

# Отдельно число и рубль для строки "Сумма"
AMOUNT_NUMBER_X = 233.489
AMOUNT_NUMBER_Y = PAGE_HEIGHT - 176.217
AMOUNT_NUMBER_FONT = FONT_BOLD
AMOUNT_NUMBER_SIZE = 9.0

RUBLE_SIGN_X = 245.036
RUBLE_SIGN_Y = PAGE_HEIGHT - 175.920
RUBLE_SIGN_FONT = FONT_RUBLE_BOLD
RUBLE_SIGN_SIZE = 9.0

# Нижние тексты
RECEIPT_X = 20.783
RECEIPT_Y = PAGE_HEIGHT - 406.150
NOTE_X = 20.783
NOTE_Y = PAGE_HEIGHT - 422.529
SUPPORT_LABEL_X = 20.432
SUPPORT_LABEL_Y = PAGE_HEIGHT - 439.529
SUPPORT_EMAIL_X = 92.640
SUPPORT_EMAIL_Y = PAGE_HEIGHT - 437.180

# Цвета
COLOR_TEXT = HexColor("#333333")
COLOR_MUTED = HexColor("#909090")
COLOR_ACCENT = HexColor("#ffdd2d")
COLOR_LINK = HexColor("#1771d6")
COLOR_STAMP = HexColor("#126cba")
COLOR_DISCLAIMER = HexColor("#a04040")
COLOR_WATERMARK = Color(0.85, 0.2, 0.2, alpha=0.09)

WATERMARK_SIZE = 44.0
WATERMARK_SPACING = 118.0

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def _draw_accent_line(c: canvas.Canvas, x: float, y: float, width: float) -> None:
    c.setStrokeColor(COLOR_ACCENT)
    c.setLineWidth(1.0)
    c.line(x, y, x + width, y)

def _draw_demo_icon(c: canvas.Canvas) -> None:
    if LOGO_PATH.exists():
        c.drawImage(str(LOGO_PATH), LOGO_X, LOGO_Y, width=LOGO_W, height=LOGO_H, preserveAspectRatio=True, mask='auto')
        return
    c.saveState()
    c.setFillColor(COLOR_ACCENT)
    path = c.beginPath()
    path.moveTo(121.0, 491.0)
    path.lineTo(149.0, 491.0)
    path.lineTo(149.0, 471.0)
    path.curveTo(149.0, 467.0, 143.0, 464.0, 135.0, 460.0)
    path.curveTo(127.0, 464.0, 121.0, 467.0, 121.0, 471.0)
    path.close()
    c.drawPath(path, stroke=0, fill=1)
    c.setFillColor(HexColor("#111111"))
    c.setFont(_font_for_text(FONT_BOLD, "D"), 17.0)
    c.drawCentredString(135.0, 470.3, "D")
    c.restoreState()

def _draw_demo_stamp(c: canvas.Canvas) -> None:
    if STAMP_PATH.exists():
        c.drawImage(str(STAMP_PATH), STAMP_X, STAMP_Y, width=STAMP_W, height=STAMP_H, preserveAspectRatio=True, mask='auto')
        return
    c.saveState()
    x = STAMP_X
    y = STAMP_Y + STAMP_H - 12
    c.setFillColor(COLOR_STAMP)
    _draw_text(c, x, y, "ДЕМО-БАНК", FONT_BOLD, 12)
    y -= 12
    _draw_text(c, x, y, "БИК 000000000 ИНН 0000000000", FONT_REGULAR, 8)
    c.restoreState()

def _draw_money_right(c: canvas.Canvas, y: float, value: str, size: float, bold: bool = False, right_x: float = None) -> None:
    if right_x is None:
        right_x = PAGE_WIDTH - 10
    amount = value.strip().removesuffix("₽").rstrip()
    ruble = "i"
    amount_font = FONT_BOLD if bold else FONT_REGULAR
    ruble_font = FONT_RUBLE_BOLD if bold else FONT_RUBLE
    ruble_width = c.stringWidth(ruble, ruble_font, size)
    amount_text = amount + " "
    amount_width = _mixed_text_width(c, amount_text, amount_font, size)
    start_x = right_x - amount_width - ruble_width
    c.setFillColor(COLOR_TEXT)
    _draw_text(c, start_x, y, amount_text, amount_font, size)
    if bold:
        _draw_bold_ruble(c, start_x + amount_width, y, ruble, ruble_font, size)
    else:
        c.setFont(ruble_font, size)
        c.drawString(start_x + amount_width, y, ruble)

def _draw_bold_ruble(c: canvas.Canvas, x: float, y: float, text: str, font_name: str, size: float) -> None:
    c.saveState()
    c.setFillColor(COLOR_TEXT)
    c.setStrokeColor(COLOR_TEXT)
    c.setLineWidth(size / 30.0)
    text_obj = c.beginText(x, y)
    text_obj.setFont(font_name, size)
    text_obj.setTextRenderMode(2)
    text_obj.textOut(text)
    c.drawText(text_obj)
    c.restoreState()

def _draw_watermark(c: canvas.Canvas) -> None:
    c.saveState()
    c.translate(PAGE_WIDTH / 2, PAGE_HEIGHT / 2)
    c.rotate(35)
    c.setFillColor(COLOR_WATERMARK)
    text = ""
    c.setFont(_font_for_text(FONT_BOLD, text), WATERMARK_SIZE)
    text_width = c.stringWidth(text, FONT_BOLD, WATERMARK_SIZE)
    half = int(PAGE_HEIGHT / WATERMARK_SPACING) + 1
    for i in range(-half, half + 1):
        c.drawString(-text_width / 2, i * WATERMARK_SPACING, text)
    c.restoreState()

def _draw_disclaimer(c: canvas.Canvas) -> None:
    c.setFillColor(COLOR_DISCLAIMER)
    text = ""
    c.setFont(_font_for_text(FONT_BOLD, text), 7.0)
    c.drawCentredString(PAGE_WIDTH / 2, 8.0, text)

def render_receipt_17_card_pdf(data: Receipt17CardData) -> bytes:
    _ensure_fonts_registered()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setTitle(f"receipt_card_{datetime.now().strftime('%d.%m.%Y')}.pdf")
    c.setAuthor("receipt-pdf-bot (card transfer template)")
    c.setSubject("Демонстрационная квитанция, не имеет юридической силы")

    _draw_watermark(c)
    _draw_demo_icon(c)
    _draw_demo_stamp(c)

    # Дата
    c.setFillColor(COLOR_MUTED)
    _draw_text(c, DATE_X, DATE_Y, data.datetime_text.strip() or "—", DATE_FONT, DATE_SIZE)

    # Итого (левое слово)
    c.setFillColor(COLOR_TEXT)
    _draw_text(c, TOTAL_LABEL_X, TOTAL_LABEL_Y, "Итого", TOTAL_LABEL_FONT, TOTAL_LABEL_SIZE)

    # Сумма итога (правый край)
    _draw_money_right(c, TOTAL_AMOUNT_Y, data.total, TOTAL_AMOUNT_SIZE, bold=True, right_x=TOTAL_AMOUNT_X)

    # Верхняя жёлтая линия
    _draw_accent_line(c, TOP_LINE_X, TOP_LINE_Y, TOP_LINE_W)

    # Основные поля (левый столбец – названия, правый – значения)
    for label, lx, top_l, field, rx, top_r in FIELDS:
        y_l = PAGE_HEIGHT - top_l
        y_r = PAGE_HEIGHT - top_r
        c.setFillColor(COLOR_TEXT)
        _draw_text(c, lx, y_l, label, FONT_REGULAR, 9.0)
        value = getattr(data, field)
        _draw_text(c, rx, y_r, value, FONT_REGULAR, 9.0)

    # Дополнительно: число и рубль для строки "Сумма" (так как data.amount содержит "10 000 ₽", но мы выводим отдельно)
    _draw_text(c, AMOUNT_NUMBER_X, AMOUNT_NUMBER_Y, "10 000", AMOUNT_NUMBER_FONT, AMOUNT_NUMBER_SIZE)
    _draw_text(c, RUBLE_SIGN_X, RUBLE_SIGN_Y, "i", RUBLE_SIGN_FONT, RUBLE_SIGN_SIZE)

    # Нижняя жёлтая линия
    _draw_accent_line(c, BOTTOM_LINE_X, BOTTOM_LINE_Y, BOTTOM_LINE_W)

    # Нижние тексты
    c.setFillColor(COLOR_TEXT)
    _draw_text(c, RECEIPT_X, RECEIPT_Y, f"Квитанция  {data.receipt_number}", FONT_REGULAR, 9.0)
    c.setFillColor(COLOR_MUTED)
    _draw_text(c, NOTE_X, NOTE_Y, data.note_text, FONT_REGULAR, 9.0)
    support_label = data.support_label + " "
    c.setFillColor(COLOR_TEXT)
    _draw_text(c, SUPPORT_LABEL_X, SUPPORT_LABEL_Y, support_label, FONT_REGULAR, 9.0)
    c.setFillColor(COLOR_LINK)
    _draw_text(c, SUPPORT_EMAIL_X, SUPPORT_EMAIL_Y, data.support_email, FONT_REGULAR, 9.0)

    c.setStrokeColor(HexColor("#c2c2c2"))
    c.setLineWidth(0.25)
    c.line(1.0, 1.0, PAGE_WIDTH - 1.0, 1.0)
    _draw_disclaimer(c)

    c.showPage()
    c.save()
    return buf.getvalue()

if __name__ == "__main__":
    Path("receipt-17-card-demo.pdf").write_bytes(render_receipt_17_card_pdf(Receipt17CardData()))
