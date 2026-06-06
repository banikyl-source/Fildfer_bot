"""Замена суммы через PyMuPDF (без новых шрифтов)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import io
import fitz

ASSET_DIR = Path(__file__).parent / "assets"
ALFA_ASSET_DIR = ASSET_DIR / "alfa"
ORIGINAL_PDF = ALFA_ASSET_DIR / "original.pdf"

@dataclass
class AlfaReceiptData:
    amount: str = "1 400 RUB"

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    doc = fitz.open(ORIGINAL_PDF)
    page = doc[0]
    # Ищем старую сумму (как она написана в PDF)
    old = "1 400 RUB"
    # Заменяем на новую
    found = page.replace_text(old, data.amount, flags=fitz.TEXT_REPLACE_FLAGS)
    if not found:
        # Если не нашло, попробуем с неразрывными пробелами
        old_nbsp = "1\xa0400\xa0RUB"
        page.replace_text(old_nbsp, data.amount.replace(" ", "\xa0"))
    # Сохраняем с максимальной оптимизацией
    out = io.BytesIO()
    doc.save(out, garbage=4, deflate=True, clean=True)
    doc.close()
    return out.getvalue()

if __name__ == "__main__":
    test = AlfaReceiptData(amount="1 500 RUB")
    with open("test_output.pdf", "wb") as f:
        f.write(render_alfa_receipt_pdf(test))
    print("✅ Готово")
