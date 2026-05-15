"""Template for Alfa-Bank SBP receipt based on original PDF."""

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

FONT_REGULAR = "Receipt17Sans"
FONT_BOLD = "Receipt17Sans-Bold"
FONT_FALLBACK = "Receipt17Fallback"

ASSET_DIR = Path(__file__).parent / "assets"
FONT_DIR = ASSET_DIR / "fonts"
ALFA_ASSET_DIR = ASSET_DIR / "alfa"   # сюда положим логотип alfa.png
LOGO_PATH = ALFA_ASSET_DIR / "alfa.png"

# Регистрация шрифтов (та же, что в основном шаблоне)
_fonts_registered = False
_FONT_CANDIDATES = (  # упрощённо – только TinkoffSans и DejaVu
    (FONT_REGULAR, (str(FONT_DIR / "TinkoffSans-Regular.ttf"), str(FONT_DIR / "DejaVuSans.ttf"))),
    (FONT_BOLD, (str(FONT_DIR / "TinkoffSans-Medium.ttf"), str(FONT_DIR / "DejaVuSans-Bold.ttf"))),
    (FONT_FALLBACK, (str(FONT_DIR / "DejaVuSans.ttf"),)),
)

def _ensure_fonts():
    global _fonts_registered
    if _fonts_registered:
        return
    for name, candidates in _FONT_CANDIDATES:
        for path in candidates:
            p = Path(path).expanduser()
            if p.exists():
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
    operation_number: str = "C421911251260019"          # Номер операции
    sbp_id: str = "A5323172126061020000020011640104"   # Идентификатор СБП
    recipient_name: str = "Роман Павлович Б"
    transfer_message: str = "Перевод денежных средств"

PAGE_WIDTH = 400.0   # ширина чека (можно подогнать)
PAGE_HEIGHT = 280.0
LEFT_MARGIN = 20.0
RIGHT_MARGIN = PAGE_WIDTH - 20.0

def _draw_text(c, x, y, text, font, size):
    c.setFont(font, size)
    c.drawString(x, y, text)

def _draw_right_text(c, x, y, text, font, size):
    w = c.stringWidth(text, font, size)
    c.drawString(x - w, y, text)

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    _ensure_fonts()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setTitle(f"alfa_receipt_{datetime.now().strftime('%d.%m.%Y')}.pdf")

    # Логотип (если есть)
    if LOGO_PATH.exists():
        c.drawImage(str(LOGO_PATH), LEFT_MARGIN, PAGE_HEIGHT - 30, width=60, height=20, preserveAspectRatio=True, mask='auto')

    # Заголовок
    _draw_text(c, LEFT_MARGIN, PAGE_HEIGHT - 45, "Квитанция о переводе по СБП", FONT_BOLD, 12)

    y = PAGE_HEIGHT - 75
    fields = [
        ("Сумма перевода", data.amount),
        ("Номер телефона получателя", data.recipient_phone),
        ("Комиссия", data.fee),
        ("Банк получателя", data.recipient_bank),
        ("Дата и время перевода", data.datetime_text),
        ("Счёт списания", data.sender_account),
        ("Номер операции", data.operation_number),
        ("Идентификатор операции в СБП", data.sbp_id),
        ("Получатель", data.recipient_name),
        ("Сообщение получателю", data.transfer_message),
    ]
    for label, value in fields:
        _draw_text(c, LEFT_MARGIN, y, label + ":", FONT_REGULAR, 9)
        _draw_right_text(c, RIGHT_MARGIN, y, value, FONT_REGULAR, 9)
        y -= 18

    # Реквизиты Альфа-Банка
    y -= 10
    _draw_text(c, LEFT_MARGIN, y, "АО «АЛЬФА-БАНК» БИК 044525593 ИНН 7728168971 к/сч 30101810200000000593", FONT_REGULAR, 7)
    y -= 12
    _draw_text(c, LEFT_MARGIN, y, "ПЕРЕВОД ВЫПОЛНЕН", FONT_BOLD, 8)

    c.showPage()
    c.save()
    return buf.getvalue()
