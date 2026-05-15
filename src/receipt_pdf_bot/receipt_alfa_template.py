"""Template for Alfa-Bank SBP receipt based on original PDF coordinates."""

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

# Попробуем загрузить Tahoma, если есть, иначе DejaVuSans
ASSET_DIR = Path(__file__).parent / "assets"
FONT_DIR = ASSET_DIR / "fonts"
FONT_REGULAR = "AlfaRegular"
FONT_BOLD = "AlfaBold"
FONT_FALLBACK = "AlfaFallback"

_FONT_CANDIDATES = [
    (FONT_REGULAR, [FONT_DIR / "Tahoma.ttf", FONT_DIR / "DejaVuSans.ttf", FONT_DIR / "TinkoffSans-Regular.ttf"]),
    (FONT_BOLD,   [FONT_DIR / "Tahoma-Bold.ttf", FONT_DIR / "DejaVuSans-Bold.ttf", FONT_DIR / "TinkoffSans-Medium.ttf"]),
    (FONT_FALLBACK, [FONT_DIR / "DejaVuSans.ttf", FONT_DIR / "TinkoffSans-Regular.ttf"]),
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
    """Все поля для чека Альфа-Банка."""
    datetime_text: str = "19.11.2025 20:21:45 мск"   # дата и время перевода
    amount: str = "26 200 RUR"
    recipient_phone: str = "79273364000"
    fee: str = "0 RUR"
    recipient_bank: str = "Т-Банк"
    sender_account: str = "40817810505905043078"
    operation_number: str = "C421911251260019"
    sbp_id: str = "A5323172126061020000020011640104"
    recipient_name: str = "Роман Павлович Б"
    transfer_message: str = "Перевод денежных средств"

# Размеры страницы (взяты из вашего PDF, при необходимости подкорректируйте)
PAGE_WIDTH = 600.0
PAGE_HEIGHT = 840.0

# Координаты из extract_coords.py (все значения в pt, Y от нижнего края)
# Левая колонка (названия)
LEFT_X = 35.45
RIGHT_X = 304.75   # X для правой колонки

# Y‑координаты для левой колонки (названия и значения)
LEFT_LABELS_Y = {
    "Сумма перевода": 693.70,
    "Комиссия": 650.80,
    "Дата и время перевода": 607.91,
    "Номер операции": 565.02,
    "Получатель": 522.12,
}
LEFT_VALUES_Y = {
    "amount": 676.29,
    "fee": 633.39,
    "datetime_text": 590.50,
    "operation_number": 547.61,
    "recipient_name": 504.71,
}

# Y‑координаты для правой колонки (названия и значения)
RIGHT_LABELS_Y = {
    "Номер телефона получателя": 693.70,
    "Банк получателя": 650.80,
    "Счёт списания": 607.91,
    "Идентификатор операции в СБП": 565.02,
    "Сообщение получателю": 522.12,
}
RIGHT_VALUES_Y = {
    "recipient_phone": 676.29,
    "recipient_bank": 633.39,
    "sender_account": 590.50,
    "sbp_id": 547.61,
    "transfer_message": 504.71,
}

# Заголовок и дата формирования (верхний правый угол)
TITLE_Y = 736.78
HEADER_Y = 806.44   # "Сформирована"
HEADER_DATE_Y = 790.15

# Нижние штампы (относительное расположение, оставляем как в исходном шаблоне)
STAMP1_Y_OFFSET = 60
STAMP2_Y_OFFSET = 20

def _draw_text(c, x, y, text, font, size, color=HexColor("#000000")):
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawString(x, y, text)

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    _ensure_fonts()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setTitle(f"alfa_receipt_{datetime.now().strftime('%d.%m.%Y')}.pdf")

    # Верхняя строка: "Сформирована" и текущая дата (можно использовать системную)
    _draw_text(c, LEFT_X, HEADER_Y, "Сформирована", FONT_REGULAR, 11)
    _draw_text(c, LEFT_X, HEADER_DATE_Y, datetime.now().strftime("%d.%m.%Y %H:%M мск"), FONT_REGULAR, 11)

    # Заголовок
    _draw_text(c, LEFT_X, TITLE_Y, "Квитанция о переводе по СБП", FONT_BOLD, 21)

    # Левая колонка: названия
    for label, y in LEFT_LABELS_Y.items():
        _draw_text(c, LEFT_X, y, label, FONT_REGULAR, 11)
    # Левая колонка: значения
    _draw_text(c, LEFT_X, LEFT_VALUES_Y["amount"], data.amount, FONT_BOLD, 12)
    _draw_text(c, LEFT_X, LEFT_VALUES_Y["fee"], data.fee, FONT_BOLD, 12)
    _draw_text(c, LEFT_X, LEFT_VALUES_Y["datetime_text"], data.datetime_text, FONT_BOLD, 12)
    _draw_text(c, LEFT_X, LEFT_VALUES_Y["operation_number"], data.operation_number, FONT_BOLD, 12)
    _draw_text(c, LEFT_X, LEFT_VALUES_Y["recipient_name"], data.recipient_name, FONT_BOLD, 12)

    # Правая колонка: названия
    for label, y in RIGHT_LABELS_Y.items():
        _draw_text(c, RIGHT_X, y, label, FONT_REGULAR, 11)
    # Правая колонка: значения
    _draw_text(c, RIGHT_X, RIGHT_VALUES_Y["recipient_phone"], data.recipient_phone, FONT_BOLD, 12)
    _draw_text(c, RIGHT_X, RIGHT_VALUES_Y["recipient_bank"], data.recipient_bank, FONT_BOLD, 12)
    _draw_text(c, RIGHT_X, RIGHT_VALUES_Y["sender_account"], data.sender_account, FONT_BOLD, 12)
    _draw_text(c, RIGHT_X, RIGHT_VALUES_Y["sbp_id"], data.sbp_id, FONT_BOLD, 12)
    _draw_text(c, RIGHT_X, RIGHT_VALUES_Y["transfer_message"], data.transfer_message, FONT_BOLD, 12)

    # Штампы (если вы добавите изображения, они будут использованы автоматически)
    # Для простоты оставим только текст, как в оригинале (его можно заменить на картинки)
    alfa_asset_dir = ASSET_DIR / "alfa"
    stamp1_path = alfa_asset_dir / "stamp.png"
    stamp2_path = alfa_asset_dir / "stamp2.png"
    y_stamp = min(LEFT_VALUES_Y.values()) - 40  # ниже последнего значения

    if stamp1_path.exists():
        c.drawImage(str(stamp1_path), LEFT_X, y_stamp - 50, width=200, height=80, preserveAspectRatio=True, mask='auto')
    else:
        lines1 = [
            "АО «АЛЬФА-БАНК»",
            "БИК 044525593 ИНН 7728168971",
            "к/сч 30101810200000000593",
            "",
            "ПЕРЕВОД ВЫПОЛНЕН"
        ]
        for i, line in enumerate(lines1):
            _draw_text(c, LEFT_X, y_stamp - i*12, line, FONT_REGULAR, 8)
        y_stamp -= 80

    if stamp2_path.exists():
        c.drawImage(str(stamp2_path), LEFT_X, y_stamp - 50, width=250, height=60, preserveAspectRatio=True, mask='auto')
    else:
        lines2 = [
            "alfabank.ru",
            "АО «АЛЬФА-БАНК»",
            "ул. Каланчёвская, 27, Москва, 107078",
            "+7 495 620 91 91 / +7 495 974 25 15",
            "mail@alfabank.ru"
        ]
        for i, line in enumerate(lines2):
            _draw_text(c, LEFT_X, y_stamp - i*12, line, FONT_REGULAR, 8)

    c.showPage()
    c.save()
    return buf.getvalue()
