"""Template for Alfa-Bank – использует встроенный шрифт NMPEME+Tahoma,
не встраивает новый, вставляет сумму по скорректированным координатам.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import io
import fitz

ASSET_DIR = Path(__file__).parent / "assets"
ALFA_ASSET_DIR = ASSET_DIR / "alfa"
BLANK_TEMPLATE = ALFA_ASSET_DIR / "blank_alfa.pdf"

# Новые координаты после правки (от левого верхнего угла)
SUM_X = 35.462
SUM_Y = 167.204
FONT_SIZE = 12
# Имя шрифта, уже встроенного в оригинальный PDF (подмножество)
FONT_NAME = "NMPEME+Tahoma"

@dataclass
class AlfaReceiptData:
    amount: str = "1 400 RUB"

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    if not BLANK_TEMPLATE.exists():
        raise FileNotFoundError(f"Template not found: {BLANK_TEMPLATE}")

    doc = fitz.open(BLANK_TEMPLATE)
    page = doc[0]

    # Вставляем сумму, используя имя существующего шрифта (не встраиваем новый)
    page.insert_text(
        (SUM_X, SUM_Y + 10),      # +10 для корректировки базовой линии
        data.amount,
        fontsize=FONT_SIZE,
        fontname=FONT_NAME,
        color=(0, 0, 0),
        render_mode=0,
    )

    # --- ОПТИМИЗАЦИЯ РАЗМЕРА (сохраняем ~60 КБ) ---
    # Удаляем лишние метаданные и служебные данные
    doc.scrub(metadata=True, xml_metadata=True)
    # Создаём поднаборы шрифтов (обрезаем неиспользуемые символы)
    doc.subset_fonts()
    # Сохраняем с максимальным сжатием
    out = io.BytesIO()
    doc.save(out, garbage=4, deflate=True, clean=True)
    doc.close()
    return out.getvalue()

if __name__ == "__main__":
    test_data = AlfaReceiptData(amount="5 000 RUB")
    with open("alfa_final.pdf", "wb") as f:
        f.write(render_alfa_receipt_pdf(test_data))
    print("✅ Чек создан с правильным шрифтом и координатами")
