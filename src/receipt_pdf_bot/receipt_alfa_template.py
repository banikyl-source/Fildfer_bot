"""Template for Alfa-Bank SBP receipt – direct text injection using PyMuPDF.
Никаких следов ReportLab. Шрифт Tahoma (или OCR-B). Метаданные банка.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import fitz  # PyMuPDF

ASSET_DIR = Path(__file__).parent / "assets"
FONT_DIR = ASSET_DIR / "fonts"
ALFA_ASSET_DIR = ASSET_DIR / "alfa"
BLANK_TEMPLATE = ALFA_ASSET_DIR / "blank_alfa.pdf"

# Шрифт – используем системный Tahoma (или OCR-B)
# В PyMuPDF нужно указать путь к файлу шрифта для встраивания
FONT_PATH = FONT_DIR / "Tahoma.ttf"
if not FONT_PATH.exists():
    FONT_PATH = FONT_DIR / "OCRB.otf"  # fallback
if not FONT_PATH.exists():
    FONT_PATH = None  # тогда будет использован стандартный шрифт PDF

@dataclass
class AlfaReceiptData:
    header_datetime: str = "14.05.2026 23:09 мск"
    transfer_datetime: str = "19.11.2025 20:21:45 мск"
    amount: str = "26 200 RUR"
    recipient_phone: str = "79273364000"
    fee: str = "0 RUR"
    recipient_bank: str = "Т-Банк"
    sender_account: str = "40817810505905043078"
    operation_number: str = "C421911251260019"
    sbp_id: str = "A5323172126061020000020011640104"
    recipient_name: str = "Роман Павлович Б"
    transfer_message: str = "Перевод денежных средств"

# Координаты в пунктах (pt) – те же, что и раньше, но PyMuPDF использует координаты от нижнего левого угла
# Преобразуем: Y_from_top = PAGE_HEIGHT - Y_bottom
PAGE_WIDTH = 270.0   # ширина страницы в pt
PAGE_HEIGHT = 471.0  # высота страницы в pt

# Функция преобразования: верхняя координата (из Master PDF Editor) -> Y снизу
def y_from_top(top: float) -> float:
    return PAGE_HEIGHT - top

# Координаты для полей (X, Y_bottom)
# Используем последние скорректированные значения
fields_coords = {
    "amount": (35.45, y_from_top(177.48)),
    "fee": (35.45, y_from_top(220.374)),
    "recipient_phone": (304.75, y_from_top(177.48)),
    "recipient_bank": (304.75, y_from_top(220.374)),
    "sender_account": (304.75, y_from_top(263.268)),
    "operation_number": (35.45, y_from_top(306.294)),
    "sbp_id": (304.75, y_from_top(306.162)),
    "recipient_name": (35.45, y_from_top(349.056)),
    "transfer_message": (304.75, y_from_top(349.056)),
}

header_date_coords = (452.788, y_from_top(62.629))
transfer_date_coords = (35.45, y_from_top(263.268))

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    # Открываем шаблон
    doc = fitz.open(BLANK_TEMPLATE)
    page = doc[0]

    # Устанавливаем метаданные документа (банковские)
    doc.set_metadata({
        "title": "Квитанция о переводе по СБП",
        "author": "АО «АЛЬФА-БАНК»",
        "subject": "Перевод по СБП",
        "creator": "АО «АЛЬФА-БАНК»",
        "producer": "АО «АЛЬФА-БАНК»"
    })

    # Регистрируем шрифт (если есть)
    if FONT_PATH and FONT_PATH.exists():
        fontname = "CustomFont"
        # Встраиваем шрифт в PDF
        _ = page.insert_font(fontname=fontname, fontfile=str(FONT_PATH))
    else:
        fontname = "helv"  # стандартный Helvetica

    # Функция для добавления текста
    def add_text(x, y, text, fontsize, color_rgb=(0,0,0)):
        # color_rgb: (0,0,0) – чёрный, (0.5,0.5,0.5) – серый
        # Встраиваем текст
        page.insert_text(
            (x, y),
            text,
            fontsize=fontsize,
            fontname=fontname if FONT_PATH else "helv",
            color=color_rgb,
            render_mode=0,  # обычный текст
        )

    # Основные поля (чёрные, 12pt)
    for field, (x, y) in fields_coords.items():
        value = getattr(data, field, "")
        if value:
            add_text(x, y, str(value), 12, (0,0,0))

    # Дата в шапке (серая, 11pt)
    x, y = header_date_coords
    add_text(x, y, data.header_datetime, 11, (0.5,0.5,0.5))  # серый #7e7e83 ≈ RGB(126,126,131)

    # Дата перевода (чёрная, 12pt)
    x, y = transfer_date_coords
    add_text(x, y, data.transfer_datetime, 12, (0,0,0))

    # Сохраняем в байты
    out_bytes = doc.write()
    doc.close()
    return out_bytes

if __name__ == "__main__":
    test_data = AlfaReceiptData()
    with open("alfa_test_pymupdf.pdf", "wb") as f:
        f.write(render_alfa_receipt_pdf(test_data))
    print("✅ Чек создан: alfa_test_pymupdf.pdf")
