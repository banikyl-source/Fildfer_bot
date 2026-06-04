"""Template for Alfa-Bank – вставка суммы в готовый PDF-шаблон без увеличения веса.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import io
import fitz

ASSET_DIR = Path(__file__).parent / "assets"
ALFA_ASSET_DIR = ASSET_DIR / "alfa"
BLANK_TEMPLATE = ALFA_ASSET_DIR / "blank_alfa.pdf"

# Координаты для вставки суммы (pt, от левого верхнего угла) – откалибруйте под свой шаблон
SUM_X = 78.1
SUM_Y = 317.5
FONT_SIZE = 12
FONT_NAME = "Helvetica"  # используем стандартный шрифт, не встраиваем

@dataclass
class AlfaReceiptData:
    amount: str = "1 400 RUB"

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    if not BLANK_TEMPLATE.exists():
        raise FileNotFoundError(f"Template not found: {BLANK_TEMPLATE}")

    doc = fitz.open(BLANK_TEMPLATE)
    page = doc[0]

    # Вставляем сумму (без встраивания шрифта)
    page.insert_text(
        (SUM_X, SUM_Y + 10),   # небольшая поправка для базовой линии
        data.amount,
        fontsize=FONT_SIZE,
        fontname=FONT_NAME,
        color=(0, 0, 0),
        render_mode=0,
    )

    # --- МАКСИМАЛЬНАЯ ОПТИМИЗАЦИЯ РАЗМЕРА ---
    # 1. Удаляем все служебные метаданные
    doc.scrub(metadata=True, xml_metadata=True)
    # 2. Создаём поднаборы для всех шрифтов (обрезаем неиспользуемые символы)
    doc.subset_fonts()
    # 3. (Опционально) сжимаем изображения – закомментировано, т.к. может снизить качество логотипа
    # doc.rewrite_images(dpi_target=72, quality=75)

    # 4. Сохраняем с максимальным сжатием
    out = io.BytesIO()
    doc.save(out, garbage=4, deflate=True, clean=True)
    doc.close()
    return out.getvalue()

if __name__ == "__main__":
    test_data = AlfaReceiptData(amount="5 000 RUB")
    with open("alfa_optimized.pdf", "wb") as f:
        f.write(render_alfa_receipt_pdf(test_data))
    print("✅ Чек с оптимизацией создан")
