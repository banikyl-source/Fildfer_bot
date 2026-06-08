"""PDF rendering for demo receipts.

The output is intentionally branded as a demo: every page carries a large
diagonal "ОБРАЗЕЦ" watermark and a footer disclaimer that the document has
no legal force. There is no bank logo or bank name in the output — the
template is a generic transfer-receipt layout.

Layout (page size, margins, font sizes, colors, spacing) follows the
proportions of the user-supplied template. Uses Roboto (a humanist sans
with full Cyrillic and ₽ support) at sizes matched to the original.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from reportlab.lib.utils import ImageReader

from reportlab.lib.colors import Color, HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_REGULAR = "ReceiptSans"
FONT_BOLD = "ReceiptSans-Bold"

_FONT_CANDIDATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        FONT_REGULAR,
        (
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
            raise RuntimeError(
                f"Font {name} not found. Install fonts-liberation (apt) "
                "or place a TTF at one of the expected locations."
            )
    _fonts_registered = True


# Colors sampled from the user-supplied template render.
COLOR_LABEL = HexColor("#8a8f96")
COLOR_VALUE = HexColor("#000000")
COLOR_HEADER = HexColor("#5a5e66")
COLOR_DATE = HexColor("#7d8189")
COLOR_DIVIDER = HexColor("#b9bcc1")
COLOR_BOX_BORDER = HexColor("#5b8def")
COLOR_BOX_TEXT = HexColor("#3a6fd8")
COLOR_DISCLAIMER = HexColor("#a04040")
COLOR_WATERMARK = Color(0.85, 0.2, 0.2, alpha=0.16)


@dataclass(slots=True)
class ReceiptData:
    """Fields rendered on the demo receipt."""

    datetime_text: str = ""
    operation: str = "Перевод клиенту"
    recipient_name: str = ""
    recipient_card: str = ""
    sender_name: str = ""
    sender_account: str = ""
    amount: str = ""
    fee: str = "0,00 ₽"
    document_number: str = ""
    auth_code: str = ""
    extra_lines: list[str] = field(
        default_factory=lambda: [
            "Если вы отправили деньги не тому человеку,",
            "обратитесь к получателю перевода.",
            "Деньги может вернуть только получатель",
        ]
    )
    status_line_1: str = "ПАО Сбербанк"
    status_line_2: str = "Операция выполнена"


# Page geometry — points (1 pt = 1/72 inch). The base template matches the
# supplied PDF page box (300 x 699 pt); longer extra-info blocks grow downward.
PAGE_WIDTH = 300.0
BASE_PAGE_HEIGHT = 699.0
BASE_EXTRA_LINE_COUNT = 3
MARGIN_X = 19.0

# Header
HEADER_TITLE_TOP = 66.26
HEADER_TITLE_SIZE = 12.0
HEADER_DATE_TOP = 83.26
HEADER_DATE_SIZE = 12.0
TOP_SEPARATOR_TOP = 97.26

# Field block (label + value)
LABEL_SIZE = 10.0
VALUE_SIZE = 12.0
LABEL_TO_VALUE = 17.38
VALUE_TO_NEXT_LABEL = 16.62
VALUE_TO_NEXT_GROUP_LABEL = 40.62

# Extra-info section
EXTRA_LABEL_SIZE = 10.0
EXTRA_VALUE_SIZE = 12.0
EXTRA_SEPARATOR_TOP = 485.46
EXTRA_LABEL_TOP = 503.88
EXTRA_LABEL_TO_FIRST_LINE = 16.0
EXTRA_LINE_HEIGHT = 13.8

# Status box
STATUS_BOX_X = 50.0
STATUS_BOX_BOTTOM = 54.0
STATUS_BOX_WIDTH = 201.18
STATUS_BOX_HEIGHT = 57.0
STATUS_BOX_RADIUS = 0.0
STATUS_BOX_BORDER_WIDTH = 3.0
STATUS_LINE1_SIZE = 10.0
STATUS_LINE2_SIZE = 15.0

# Disclaimer
DISCLAIMER_SIZE = 8.0
DISCLAIMER_SUB_SIZE = 7.0
DISCLAIMER_SUB_GAP = 9.0
DISCLAIMER_Y = 33.0

WATERMARK_SIZE = 58.0
WATERMARK_SPACING = 135.0

ASSET_DIR = Path(__file__).parent / "assets"
LOGO_PATH = ASSET_DIR / "logo.png"


def _draw_logo(c: canvas.Canvas, page_height: float) -> None:
    if not LOGO_PATH.exists():
        return

    logo = ImageReader(str(LOGO_PATH))
    c.drawImage(
        logo,
        1,
        page_height - 85,
        width=300,
        height=103,
        preserveAspectRatio=True,
        mask="auto",
    )


def _compute_page_height(extra_line_count: int) -> float:
    extra_lines = max(extra_line_count, BASE_EXTRA_LINE_COUNT)
    return BASE_PAGE_HEIGHT + (extra_lines - BASE_EXTRA_LINE_COUNT) * EXTRA_LINE_HEIGHT


def _y(page_height: float, top_offset: float) -> float:
    return page_height - top_offset


def _draw_separator(c: canvas.Canvas, y: float) -> None:
    c.setFillColor(COLOR_DIVIDER)
    c.setFont(FONT_REGULAR, 12.0)
    c.drawCentredString(PAGE_WIDTH / 2, y, "- " * 37)


def _draw_field(c: canvas.Canvas, y: float, label: str, value: str) -> float:
    """Draws a label/value pair. Returns y position below the value."""
    display_value = value.strip() if value and value.strip() else "—"

    c.setFillColor(COLOR_LABEL)
    c.setFont(FONT_REGULAR, LABEL_SIZE)
    c.drawString(MARGIN_X, y, label)

    y -= LABEL_TO_VALUE
    c.setFillColor(COLOR_VALUE)
    c.setFont(FONT_REGULAR, VALUE_SIZE)
    c.drawString(MARGIN_X, y, display_value)
    return y


def _draw_watermark(c: canvas.Canvas, page_height: float) -> None:
    c.saveState()
    c.translate(PAGE_WIDTH / 2, page_height / 2)
    c.rotate(35)
    c.setFillColor(COLOR_WATERMARK)
    c.setFont(FONT_BOLD, WATERMARK_SIZE)
    text = ""
    text_width = c.stringWidth(text, FONT_BOLD, WATERMARK_SIZE)
    half = int(page_height / WATERMARK_SPACING) + 1
    for i in range(-half, half + 1):
        c.drawString(-text_width / 2, i * WATERMARK_SPACING, text)
    c.restoreState()


def _draw_header(c: canvas.Canvas, data: ReceiptData, page_height: float) -> float:
    c.setFillColor(COLOR_HEADER)
    c.setFont(FONT_REGULAR, HEADER_TITLE_SIZE)
    c.drawCentredString(
        PAGE_WIDTH / 2,
        _y(page_height, HEADER_TITLE_TOP),
        "Чек по операции",
    )

    c.setFillColor(COLOR_DATE)
    c.setFont(FONT_REGULAR, HEADER_DATE_SIZE)
    c.drawCentredString(
        PAGE_WIDTH / 2,
        _y(page_height, HEADER_DATE_TOP),
        (data.datetime_text.strip() or "—"),
    )
    _draw_separator(c, _y(page_height, TOP_SEPARATOR_TOP))
    return _y(page_height, 122.88)


def _draw_status_box(c: canvas.Canvas, data: ReceiptData) -> None:
    box_top = STATUS_BOX_BOTTOM + STATUS_BOX_HEIGHT
    c.setStrokeColor(COLOR_BOX_BORDER)
    c.setLineWidth(STATUS_BOX_BORDER_WIDTH)
    c.roundRect(
        STATUS_BOX_X,
        STATUS_BOX_BOTTOM,
        STATUS_BOX_WIDTH,
        STATUS_BOX_HEIGHT,
        radius=STATUS_BOX_RADIUS,
        stroke=1,
        fill=0,
    )
    c.setFillColor(COLOR_BOX_TEXT)
    c.setFont(FONT_REGULAR, STATUS_LINE1_SIZE)
    c.drawCentredString(PAGE_WIDTH / 2, box_top - 20, data.status_line_1)
    c.setFont(FONT_REGULAR, STATUS_LINE2_SIZE)
    c.drawCentredString(PAGE_WIDTH / 2, box_top - 40, data.status_line_2)


def _draw_disclaimer(c: canvas.Canvas) -> None:
    c.setFillColor(COLOR_DISCLAIMER)
    c.setFont(FONT_BOLD, DISCLAIMER_SIZE)
    c.drawCentredString(
        PAGE_WIDTH / 2,
        DISCLAIMER_Y,
        "",
    )
    c.setFillColor(COLOR_LABEL)
    c.setFont(FONT_REGULAR, DISCLAIMER_SUB_SIZE)
    c.drawCentredString(
        PAGE_WIDTH / 2,
        DISCLAIMER_Y - DISCLAIMER_SUB_GAP,
        "",
    )


def render_receipt_pdf(data: ReceiptData) -> bytes:
    """Renders a single-page demo receipt PDF and returns its bytes."""
    _ensure_fonts_registered()

    page_height = _compute_page_height(len(data.extra_lines))

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_WIDTH, page_height))
    c.setTitle("Чек по операции (ОБРАЗЕЦ)")
    c.setAuthor("receipt-pdf-bot (demo generator)")
    c.setSubject("Демонстрационный чек, не имеет юридической силы")

    _draw_logo(c, page_height)
    _draw_watermark(c, page_height)

    y = _draw_header(c, data, page_height)

    y = _draw_field(c, y, "Операция", data.operation)
    y -= VALUE_TO_NEXT_LABEL
    y = _draw_field(c, y, "ФИО получателя", data.recipient_name)
    y -= VALUE_TO_NEXT_LABEL
    y = _draw_field(c, y, "Номер карты получателя", data.recipient_card)
    y -= VALUE_TO_NEXT_GROUP_LABEL
    y = _draw_field(c, y, "ФИО отправителя", data.sender_name)
    y -= VALUE_TO_NEXT_LABEL
    y = _draw_field(c, y, "Счёт отправителя", data.sender_account)
    y -= VALUE_TO_NEXT_LABEL
    y = _draw_field(c, y, "Сумма перевода", data.amount)
    y -= VALUE_TO_NEXT_LABEL
    y = _draw_field(c, y, "Комиссия", data.fee)
    y -= VALUE_TO_NEXT_GROUP_LABEL
    y = _draw_field(c, y, "Номер документа", data.document_number)
    y -= VALUE_TO_NEXT_LABEL
    y = _draw_field(c, y, "Код авторизации", data.auth_code)

    _draw_separator(c, _y(page_height, EXTRA_SEPARATOR_TOP))
    y = _y(page_height, EXTRA_LABEL_TOP)

    c.setFillColor(COLOR_LABEL)
    c.setFont(FONT_REGULAR, EXTRA_LABEL_SIZE)
    c.drawString(MARGIN_X, y, "Дополнительная информация")
    y -= EXTRA_LINE_HEIGHT
    c.setFillColor(COLOR_VALUE)
    c.setFont(FONT_REGULAR, EXTRA_VALUE_SIZE)
    for line in data.extra_lines:
        c.drawString(MARGIN_X, y, line)
        y -= EXTRA_LINE_HEIGHT

    _draw_status_box(c, data)
    _draw_disclaimer(c)

    c.showPage()
    c.save()
    return buf.getvalue()
