"""Бинарная замена суммы в оригинальном PDF (с обычными пробелами)."""

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
    # Паттерн: цифры, разделённые пробелами (обычными), затем RUR
    # Также допускаем неразрывные пробелы на всякий случай
    pattern = re.compile(rb'\d+(?:[ \xa0]\d+)*[ \xa0]RUR[ \xa0]?')
    match = pattern.search(pdf_bytes)
    if not match:
        # Пробуем искать просто "1 400 RUR"
        fallback = b'1 400 RUR'
        pos = pdf_bytes.find(fallback)
        if pos != -1:
            match = re.search(re.escape(fallback), pdf_bytes)
    if not match:
        # Выведем первые 500 байт для диагностики
        print("Не удалось найти сумму. Первые 500 байт PDF:")
        print(pdf_bytes[:500])
        raise ValueError("Не удалось найти сумму в PDF")
    
    old_sum = match.group()
    print(f"Найдена старая сумма: {old_sum!r}")  # для отладки
    
    # Нормализуем новую сумму: заменяем пробелы на такие же, как в старой
    # Определяем, какой пробел используется в оригинале
    space_char = b'\xa0' if b'\xa0' in old_sum else b' '
    new_sum_bytes = new_sum.replace(' ', ' ').encode('latin-1')
    # Заменяем пробелы в новой сумме на оригинальные
    if space_char != b' ':
        new_sum_bytes = new_sum_bytes.replace(b' ', space_char)
    # Добавляем завершающий пробел/неразрывный пробел, если он был в оригинале
    if old_sum[-1:] in (b' ', b'\xa0'):
        new_sum_bytes += old_sum[-1:]
    # Выравниваем длину (добавляем или отрезаем пробелы в конце)
    diff = len(old_sum) - len(new_sum_bytes)
    if diff > 0:
        new_sum_bytes += space_char * diff
    elif diff < 0:
        new_sum_bytes = new_sum_bytes[:diff]
    
    # Заменяем
    new_pdf = pdf_bytes[:match.start()] + new_sum_bytes + pdf_bytes[match.end():]
    return new_pdf

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
