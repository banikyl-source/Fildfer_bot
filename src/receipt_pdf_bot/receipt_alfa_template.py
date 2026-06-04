"""Template for Alfa-Bank – использует встроенный шрифт NMPEME+Tahoma из шаблона."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import io
import fitz

ASSET_DIR = Path(__file__).parent / "assets"
ALFA_ASSET_DIR = ASSET_DIR / "alfa"
BLANK_TEMPLATE = ALFA_ASSET_DIR / "blank_alfa.pdf"

# Координаты суммы (откалибруйте при необходимости)
SUM_X = 35.462
SUM_Y = 167.204
FONT_SIZE = 12
# Точное имя шрифта из шаблона
FONT_NAME = "NMPEME+Tahoma"

@dataclass
class AlfaReceiptData:
    amount: str = "1 400 RUB"

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    if not BLANK_TEMPLATE.exists():
        raise FileNotFoundError(f"Template not found: {BLANK_TEMPLATE}")

    doc = fitz.open(BLANK_TEMPLATE)
    page = doc[0]

    # Вставляем сумму, используя существующий шрифт (без встраивания)
    page.insert_text(
        (SUM_X, SUM_Y + 10),   # небольшая поправка для базовой линии
        data.amount,
        fontsize=FONT_SIZE,
        fontname=FONT_NAME,
        color=(0, 0, 0),
    )

    # Оптимизация размера (удаляем мусор, но не удаляем шрифт)
    doc.scrub(metadata=True, xml_metadata=True)
    doc.subset_fonts()
    out = io.BytesIO()
    doc.save(out, garbage=4, deflate=True, clean=True)
    doc.close()
    return out.getvalue()

if __name__ == "__main__":
    test_data = AlfaReceiptData(amount="5 000 RUB")
    with open("alfa_final.pdf", "wb") as f:
        f.write(render_alfa_receipt_pdf(test_data))
    print("✅ Чек создан")
