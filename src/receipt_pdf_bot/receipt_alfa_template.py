"""Template for Alfa-Bank SBP receipt – PNG + img2pdf (без следов PDF-генерации).
Координаты пересчитываются из pt в пиксели автоматически.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import io

from PIL import Image, ImageDraw, ImageFont
import img2pdf

ASSET_DIR = Path(__file__).parent / "assets"
FONT_DIR = ASSET_DIR / "fonts"
ALFA_ASSET_DIR = ASSET_DIR / "alfa"
PNG_TEMPLATE = ALFA_ASSET_DIR / "alfa_base.png"
FONT_PATH = FONT_DIR / "Tahoma.ttf"

# Оригинальные размеры PDF в пунктах (из ваших замеров)
PDF_WIDTH_PT = 270.0
PDF_HEIGHT_PT = 471.0

# Координаты в пунктах (Слева, Сверху) – финальные, после всех калибровок
COORDS_PT = {
    "header_datetime": (452.788, 62.75),
    "transfer_datetime": (35.45, 263.40),
    "amount": (35.45, 177.612),
    "fee": (35.45, 220.506),
    "recipient_phone": (304.75, 177.612),
    "recipient_bank": (304.75, 220.506),
    "sender_account": (304.75, 263.40),
    "operation_number": (35.45, 306.294),
    "sbp_id": (304.75, 306.294),
    "recipient_name": (35.45, 349.188),
    "transfer_message": (304.75, 349.188),
}

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

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    if not PNG_TEMPLATE.exists():
        raise FileNotFoundError(f"PNG template not found: {PNG_TEMPLATE}")
    if not FONT_PATH.exists():
        raise FileNotFoundError(f"Font not found: {FONT_PATH}")

    # Открываем шаблон
    img = Image.open(PNG_TEMPLATE).convert("RGB")
    draw = ImageDraw.Draw(img)
    actual_width, actual_height = img.size

    # Коэффициенты пересчёта: из пунктов в пиксели
    scale_x = actual_width / PDF_WIDTH_PT
    scale_y = actual_height / PDF_HEIGHT_PT

    # Регистрируем шрифт
    try:
        # Размер шрифта в пикселях = размер в пунктах * scale_y
        font_regular = ImageFont.truetype(str(FONT_PATH), size=int(12 * scale_y))
        font_gray = ImageFont.truetype(str(FONT_PATH), size=int(11 * scale_y))
    except Exception as e:
        raise RuntimeError(f"Font loading error: {e}")

    # Цвета (RGB)
    BLACK = (0, 0, 0)
    GRAY = (128, 128, 128)  # близко к #7e7e83

    def draw_text(x_pt, y_pt, text, font, color):
        x_px = x_pt * scale_x
        y_px = y_pt * scale_y
        draw.text((x_px, y_px), text, font=font, fill=color)

    # Основные поля (чёрные, 12pt в исходном PDF)
    for field, (x, y) in COORDS_PT.items():
        if field in ("header_datetime", "transfer_datetime"):
            continue
        value = getattr(data, field, "")
        if value:
            draw_text(x, y, str(value), font_regular, BLACK)

    # Дата в шапке (серая, 11pt)
    x, y = COORDS_PT["header_datetime"]
    draw_text(x, y, data.header_datetime, font_gray, GRAY)

    # Дата перевода (чёрная, 12pt)
    x, y = COORDS_PT["transfer_datetime"]
    draw_text(x, y, data.transfer_datetime, font_regular, BLACK)

    # Сохраняем результат в PNG в памяти
    png_bytes = io.BytesIO()
    img.save(png_bytes, format="PNG")
    png_bytes.seek(0)

    # Конвертируем PNG в PDF без сжатия (максимальное качество)
    pdf_bytes = img2pdf.convert(png_bytes, dpi=300)   # можно убрать dpi, img2pdf сам определит
    return pdf_bytes

if __name__ == "__main__":
    test_data = AlfaReceiptData()
    with open("alfa_test_pillow.pdf", "wb") as f:
        f.write(render_alfa_receipt_pdf(test_data))
    print("✅ Чек создан через Pillow+img2pdf")
