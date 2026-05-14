"""Separate demo template based on receipt_17.03.2026.pdf.
Adjusted for TinkoffSans font metrics with separate tuning for date and total.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from reportlab.lib.colors import Color, HexColor
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
class Receipt17Data:
    datetime_text: str = "13.02.2026  19:00:35"
    total: str = "10 000 ₽"
    transfer_type: str = "По номеру телефона"
    status: str = "В обработке"
    amount: str = "10 000 ₽"
    fee: str = "Без комиссии"
    sender_name: str = "Константин Иванов"
    recipient_phone: str = "+7 (929) 539-13-33"
    recipient_name: str = "Галина П."
    recipient_bank: str = "Яндекс"
    debit_account: str = "408178101000****5307"
    operation_id_line_1: str = "A6076160011783290G100300117"
    operation_id_line_2: str = "00117"
    operation_type: str = "СБП"
    receipt_number: str = "№ 1-127-176-643-532"
    support_label: str = "Служба поддержки"
    support_email: str = "fb@tbank.ru"
    note_text: str = "По вопросам зачисления обращайтесь к получателю"


PAGE_WIDTH = 270.0
PAGE_HEIGHT = 519.0
MARGIN_X = 20.0
RIGHT_X = 250.0          # правый край для всех правых значений, кроме Итого

COLOR_TEXT = HexColor("#333333")
COLOR_MUTED = HexColor("#909090")
COLOR_ACCENT = HexColor("#ffdd2d")
COLOR_LINK = HexColor("#1771d6")
COLOR_STAMP = HexColor("#126cba")
COLOR_DISCLAIMER = HexColor("#a04040")
COLOR_WATERMARK = Color(0.85, 0.2, 0.2, alpha=0.09)

# ========== НАСТРАИВАЕМЫЕ КООРДИНАТЫ (ПОДБЕРИТЕ ПОД СВОЙ ШРИФТ) ==========
# Дата (кегль 8) – если дата слишком высоко, уменьшите это число
DATE_Y = 432.5            # попробуйте 432.5, если нужно ниже – уменьшайте

# Строка "Итого" (кегль 16) – если итог высоко, уменьшайте
TOTAL_Y = 412.4           # подберите так, чтобы визуально встало на место

# Правый край для суммы "10 000 i" (отдельно от остальных)
TOTAL_RIGHT_X = 249.0     # чуть левее основного RIGHT_X

# Координаты для основного блока (уже подогнаны под TinkoffSans)
Y_TRANSFER = 376.78
Y_STATUS = 356.78
Y_AMOUNT = 336.78
Y_FEE = 315.78
Y_SENDER = 295.78
Y_RECIPIENT_PHONE = 275.78
Y_RECIPIENT_NAME = 255.78
Y_RECIPIENT_BANK = 235.78
Y_DEBIT_ACCOUNT = 215.78
Y_IDENT_FIRST = 195.78
Y_IDENT_SECOND = 184.70

Y_RECEIPT_NUMBER = 58.82
Y_NOTE = 41.82
Y_SUPPORT = 24.82

LABEL_SIZE = 9.0
VALUE_SIZE = 9.0
TOTAL_SIZE = 16.0
WATERMARK_SIZE = 44.0
WATERMARK_SPACING = 118.0


def _draw_accent_line(c: canvas.Canvas, y: float) -> None:
    c.setStrokeColor(COLOR_ACCENT)
    c.setLineWidth(1.0)
    c.line(19.0, y, 249.0, y)


def _draw_demo_icon(c: canvas.Canvas) -> None:
    if LOGO_PATH.exists():
        c.drawImage(
            ImageReader(str(LOGO_PATH)),
            121.0,
            463.0,
            width=28.0,
            height=28.0,
            preserveAspectRatio=True,
            mask="auto",
        )
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
        c.drawImage(
            ImageReader(str(STAMP_PATH)),
            66.0,
            103.77,
            width=175.0,
            height=63.23,
            preserveAspectRatio=True,
            mask="auto",
        )
        return
    c.saveState()
    x = 66.0
    y = 103.77
    w = 175.0
    h = 63.23
    c.setStrokeColor(COLOR_STAMP)
    c.setFillColor(COLOR_STAMP)
    c.setLineWidth(1.0)
    c.rect(x + 32.0, y + 10.0, w - 34.0, h - 12.0, stroke=1, fill=0)
    _draw_right_text(c, x + w - 13.0, y + 47.0, "ДЕМО-БАНК", FONT_BOLD, 15.0)
    _draw_right_text(c, x + w - 13.0, y + 31.0, "БИК 000000000 ИНН 0000000000", FONT_BOLD, 10.5)
    _draw_right_text(c, x + w - 13.0, y + 17.0, "", FONT_BOLD, 10.5)
    c.setLineWidth(1.8)
    c.line(x - 7.0, y + 9.0, x + 72.0, y + 35.0)
    c.line(x - 1.0, y + 17.0, x + 57.0, y + 5.0)
    c.line(x + 14.0, y + 29.0, x + 76.0, y + 18.0)
    c.restoreState()


def _draw_right(c: canvas.Canvas, y: float, value: str, size: float = VALUE_SIZE) -> None:
    if value.strip().endswith("₽"):
        _draw_money_right(c, y, value, size, bold=False)
        return
    c.setFillColor(COLOR_TEXT)
    _draw_right_text(c, RIGHT_X, y, value.strip() or "—", FONT_REGULAR, size)


def _draw_money_right(
    c: canvas.Canvas,
    y: float,
    value: str,
    size: float,
    *,
    bold: bool,
) -> None:
    amount = value.strip().removesuffix("₽").rstrip()
    ruble = "i"
    amount_font = FONT_BOLD if bold else FONT_REGULAR
    ruble_font = FONT_RUBLE_BOLD if bold else FONT_RUBLE
    ruble_width = c.stringWidth(ruble, ruble_font, size)
    amount_text = amount + " "
    amount_width = _mixed_text_width(c, amount_text, amount_font, size)
    start_x = RIGHT_X - amount_width - ruble_width
    c.setFillColor(COLOR_TEXT)
    _draw_text(c, start_x, y, amount_text, amount_font, size)
    if bold:
        _draw_bold_ruble(c, start_x + amount_width, y, ruble, ruble_font, size)
    else:
        c.setFont(ruble_font, size)
        c.drawString(start_x + amount_width, y, ruble)


def _draw_bold_ruble(
    c: canvas.Canvas,
    x: float,
    y: float,
    text: str,
    font_name: str,
    size: float,
) -> None:
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


def _draw_pair(c: canvas.Canvas, y: float, label: str, value: str) -> None:
    c.setFillColor(COLOR_TEXT)
    _draw_text(c, MARGIN_X, y, label, FONT_REGULAR, LABEL_SIZE)
    _draw_right(c, y, value)


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


def render_receipt_17_pdf(data: Receipt17Data) -> bytes:
    _ensure_fonts_registered()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setTitle("Квитанция (ОБРАЗЕЦ)")
    c.setAuthor("receipt-pdf-bot (separate demo template)")
    c.setSubject("Демонстрационная квитанция, не имеет юридической силы")

    _draw_watermark(c)
    _draw_demo_icon(c)

    # Дата
    c.setFillColor(COLOR_MUTED)
    _draw_text(c, MARGIN_X, DATE_Y, data.datetime_text.strip() or "—", FONT_REGULAR, 8.0)

    # Итого (левое слово)
    c.setFillColor(COLOR_TEXT)
    _draw_text(c, 19.0, TOTAL_Y, "Итого", FONT_BOLD, TOTAL_SIZE)

    # Сумма Итого со своим правым краем (чтобы не смещать остальные)
    amount = data.total.strip().removesuffix("₽").rstrip()
    ruble = "i"
    ruble_width = c.stringWidth(ruble, FONT_RUBLE_BOLD, TOTAL_SIZE)
    amount_text = amount + " "
    amount_width = _mixed_text_width(c, amount_text, FONT_BOLD, TOTAL_SIZE)
    start_x = TOTAL_RIGHT_X - amount_width - ruble_width
    c.setFillColor(COLOR_TEXT)
    _draw_text(c, start_x, TOTAL_Y, amount_text, FONT_BOLD, TOTAL_SIZE)
    _draw_bold_ruble(c, start_x + amount_width, TOTAL_Y, ruble, FONT_RUBLE_BOLD, TOTAL_SIZE)

    # Жёлтая линия под итогом (привязана к TOTAL_Y)
    _draw_accent_line(c, TOTAL_Y - 20.0)   # линия примерно через 20 пунктов ниже текста, подберите при необходимости

    # Ручная отрисовка остальных строк
    c.setFillColor(COLOR_TEXT)
    _draw_text(c, MARGIN_X, Y_TRANSFER, "Перевод", FONT_REGULAR, LABEL_SIZE)
    _draw_right(c, Y_TRANSFER, data.transfer_type)

    _draw_text(c, MARGIN_X, Y_STATUS, "Статус", FONT_REGULAR, LABEL_SIZE)
    _draw_right(c, Y_STATUS, data.status)

    _draw_text(c, MARGIN_X, Y_AMOUNT, "Сумма", FONT_REGULAR, LABEL_SIZE)
    _draw_right(c, Y_AMOUNT, data.amount)

    _draw_text(c, MARGIN_X, Y_FEE, "Комиссия", FONT_REGULAR, LABEL_SIZE)
    _draw_right(c, Y_FEE, data.fee)

    _draw_text(c, MARGIN_X, Y_SENDER, "Отправитель", FONT_REGULAR, LABEL_SIZE)
    _draw_right(c, Y_SENDER, data.sender_name)

    # Белый фон для телефона получателя
    c.saveState()
    c.setFillColor(HexColor("#ffffff"))
    c.rect(20.0, 176.0, 230.0, 108.0, stroke=0, fill=1)
    c.restoreState()
    _draw_text(c, MARGIN_X, Y_RECIPIENT_PHONE, "Телефон получателя", FONT_REGULAR, LABEL_SIZE)
    _draw_right(c, Y_RECIPIENT_PHONE, data.recipient_phone)

    _draw_text(c, MARGIN_X, Y_RECIPIENT_NAME, "Получатель", FONT_REGULAR, LABEL_SIZE)
    _draw_right(c, Y_RECIPIENT_NAME, data.recipient_name)

    _draw_text(c, MARGIN_X, Y_RECIPIENT_BANK, "Банк получателя", FONT_REGULAR, LABEL_SIZE)
    _draw_right(c, Y_RECIPIENT_BANK, data.recipient_bank)

    _draw_text(c, MARGIN_X, Y_DEBIT_ACCOUNT, "Счет списания", FONT_REGULAR, LABEL_SIZE)
    _draw_right(c, Y_DEBIT_ACCOUNT, data.debit_account)

    # Идентификатор операции (первая строка)
    _draw_text(c, MARGIN_X, Y_IDENT_FIRST, "Идентификатор операции", FONT_REGULAR, LABEL_SIZE)
    _draw_right(c, Y_IDENT_FIRST, data.operation_id_line_1)

    # Вторая строка (СБП и код)
    _draw_text(c, MARGIN_X, Y_IDENT_SECOND, data.operation_type, FONT_REGULAR, LABEL_SIZE)
    _draw_right(c, Y_IDENT_SECOND, data.operation_id_line_2)

    # Короткая линия под идентификатором (оставлена как в оригинале)
    _draw_accent_line(c, 72.28)   # 80.5 - 8.22

    # Нижние элементы
    c.setFillColor(COLOR_TEXT)
    _draw_text(c, MARGIN_X, Y_RECEIPT_NUMBER, f"Квитанция  {data.receipt_number}", FONT_REGULAR, VALUE_SIZE)
    c.setFillColor(COLOR_MUTED)
    _draw_text(c, MARGIN_X, Y_NOTE, data.note_text, FONT_REGULAR, VALUE_SIZE)
    support_label = data.support_label + " "
    _draw_text(c, MARGIN_X, Y_SUPPORT, support_label, FONT_REGULAR, VALUE_SIZE)
    support_width = _mixed_text_width(c, support_label, FONT_REGULAR, VALUE_SIZE)
    c.setFillColor(COLOR_LINK)
    _draw_text(c, MARGIN_X + support_width, Y_SUPPORT, data.support_email, FONT_REGULAR, VALUE_SIZE)

    _draw_demo_stamp(c)

    c.setStrokeColor(HexColor("#c2c2c2"))
    c.setLineWidth(0.25)
    c.line(1.0, 1.0, PAGE_WIDTH - 1.0, 1.0)
    _draw_disclaimer(c)

    c.showPage()
    c.save()
    return buf.getvalue()


if __name__ == "__main__":
    Path("receipt-17-demo.pdf").write_bytes(render_receipt_17_pdf(Receipt17Data()))
