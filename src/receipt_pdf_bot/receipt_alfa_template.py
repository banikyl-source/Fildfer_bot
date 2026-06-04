"""Template for Alfa-Bank – вставка суммы в готовый шаблон.
Шаблон уже содержит все остальные поля (дата, получатель и т.д.).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import io
import fitz

ASSET_DIR = Path(__file__).parent / "assets"
ALFA_ASSET_DIR = ASSET_DIR / "alfa"
BLANK_TEMPLATE = ALFA_ASSET_DIR / "blank_alfa.pdf"

# Координаты для вставки суммы (в pt от левого верхнего угла)
SUM_X = 78.1
SUM_Y = 317.5   # верхний край текста
FONT_SIZE = 12
FONT_NAME = "Tahoma"

@dataclass
class AlfaReceiptData:
    amount: str = "1 400 RUB"

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    if not BLANK_TEMPLATE.exists():
        raise FileNotFoundError(f"Template not found: {BLANK_TEMPLATE}")

    doc = fitz.open(BLANK_TEMPLATE)
    page = doc[0]

    # Встраиваем шрифт Tahoma, если есть файл
    font_path = ASSET_DIR / "fonts" / "Tahoma.ttf"
    if font_path.exists():
        page.insert_font(fontname=FONT_NAME, fontfile=str(font_path))

    text_y = SUM_Y + 10
    page.insert_text(
        (SUM_X, text_y),
        data.amount,
        fontsize=FONT_SIZE,
        fontname=FONT_NAME,
        color=(0, 0, 0),
        render_mode=0,
    )

    out = io.BytesIO()
    doc.save(out, garbage=4, deflate=True, clean=True)
    doc.close()
    return out.getvalue()

if __name__ == "__main__":
    test_data = AlfaReceiptData(amount="5 000 RUB")
    with open("alfa_with_sum.pdf", "wb") as f:
        f.write(render_alfa_receipt_pdf(test_data))
    print("✅ Тестовый чек создан")
