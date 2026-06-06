"""Бинарная замена суммы в оригинальном PDF Альфа-банка (автоматический поиск)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

ASSET_DIR = Path(__file__).parent / "assets"
ALFA_ASSET_DIR = ASSET_DIR / "alfa"
ORIGINAL_PDF = ALFA_ASSET_DIR / "original.pdf"

@dataclass
class AlfaReceiptData:
    amount: str = "1 400 RUB"

def replace_pdf_sum(pdf_bytes: bytes, new_sum: str) -> bytes:
    """
    Ищет в PDF байтовую последовательность, похожую на сумму (цифры, пробелы, RUR),
    и заменяет её на новую сумму той же длины.
    """
    # Паттерн: одна или более цифр, разделённые пробелами или \xa0, затем RUR, затем пробел/\xa0
    pattern = re.compile(rb'[\d\xa0 ]+RUR[\xa0 ]')
    match = pattern.search(pdf_bytes)
    if not match:
        raise ValueError("Не удалось найти сумму в PDF")
    old_sum = match.group()
    # Определяем тип пробелов в оригинале
    if b'\xa0' in old_sum:
        new_sum_bytes = new_sum.replace(' ', '\xa0').encode('latin-1')
    else:
        new_sum_bytes = new_sum.encode('latin-1')
    # Добавляем завершающий пробел, если он был в оригинале
    if old_sum[-1:] in (b' ', b'\xa0'):
        new_sum_bytes += old_sum[-1:]
    # Если длина не совпадает, выравниваем неразрывными пробелами (в конец)
    diff = len(old_sum) - len(new_sum_bytes)
    if diff > 0:
        new_sum_bytes += b'\xa0' * diff
    elif diff < 0:
        new_sum_bytes = new_sum_bytes[:diff]
    # Заменяем
    return pdf_bytes[:match.start()] + new_sum_bytes + pdf_bytes[match.end():]

def render_alfa_receipt_pdf(data: AlfaReceiptData) -> bytes:
    if not ORIGINAL_PDF.exists():
        raise FileNotFoundError(f"Оригинальный PDF не найден: {ORIGINAL_PDF}")
    with open(ORIGINAL_PDF, "rb") as f:
        original = f.read()
    return replace_pdf_sum(original, data.amount)

if __name__ == "__main__":
    test = AlfaReceiptData(amount="1 500 RUB")
    with open("test_output.pdf", "wb") as f:
        f.write(render_alfa_receipt_pdf(test))
    print("✅ Тестовый PDF создан")
