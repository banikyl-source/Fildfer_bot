#!/usr/bin/env python3
"""
Универсальный патчер суммы в PDF-квитанциях Альфа-Банка (СБП, Oracle BI Publisher).

Меняет поля на байтовом уровне. Для CID-чеков недостающие буквы автоматически
добавляются в subset-шрифт из системного Tahoma (полный кириллический алфавит).
При замене только существующих глифов размер файла не меняется; при расширении
шрифта обновляются /Length и xref.

Поддерживаемые представления суммы:
  • бинарный UTF-16BE в теле файла: 00 34 00 A0 00 31 ...
  • hex-ASCII в content stream: <003400A0003100340030> (та же UTF-16BE, но как текст)
  • CID-глифы Tahoma (original.pdf, pdf 58.pdf): <000B000A0024...> + ToUnicode CMap

Использование:
  python patch_alfa_amount.py input.pdf 5294 -o output.pdf
  python patch_alfa_amount.py input.pdf --commission 0 --phone "+7 (999) 111-22-33"
  python patch_alfa_amount.py input.pdf --list-fields
  python patch_alfa_amount.py input.pdf --fields-json patch.json -o out.pdf

Программный API:
  from patch_alfa_amount import replace_fields_in_pdf, discover_fields
  info = replace_fields_in_pdf("receipt.pdf", {"amount": 5294, "commission": 0}, "out.pdf")
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import zlib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

# UTF-16BE маркеры «RUR» для эвристики поиска суммы
RUR_UTF16BE = "RUR".encode("utf-16-be")
RUR_HEX_ASCII = RUR_UTF16BE.hex().upper().encode("ascii")

# Минимальная / максимальная длина строки суммы (символы, включая пробелы)
MIN_AMOUNT_CHARS = 3
MAX_AMOUNT_CHARS = 14


@dataclass(frozen=True)
class AmountMatch:
    """Найденное вхождение суммы в PDF."""

    offset: int
    raw: bytes          # байты, которые нужно заменить (бинарь или hex-ASCII)
    text: str           # декодированная сумма, напр. «4\xa0140» или «4140»
    encoding: str       # «binary» | «hex_ascii» | «cid_zlib»
    score: int
    cid_map: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def unicode_to_cid(self) -> dict[str, str]:
        return dict(self.cid_map)


class AmountPatchError(Exception):
    """Ошибка поиска или замены полей чека."""


# Якоря полей чека Альфа-Банка (Y, X) в content stream
# Координаты (Y, X) значений в content stream (не подписей полей).
# Левая колонка x≈35.45 — сумма, комиссия, дата, ID, ФИО получателя.
# Правая колонка x≈304.75 — телефон, банк, счёт, СБП-ref, назначение.
FIELD_ANCHORS: dict[str, tuple[float, float]] = {
    "datetime_header": (779.15, 452.788),
    "amount": (664.288, 35.45),
    "commission": (621.394, 35.45),
    "datetime_full": (578.5, 35.45),
    "operation_id": (535.606, 35.45),
    "recipient_name": (492.712, 35.45),
    "phone": (664.288, 304.75),
    "recipient_bank": (621.394, 304.75),
    "account": (578.5, 304.75),
    "sbp_ref": (535.606, 304.75),
    "purpose": (492.712, 304.75),
}

FIELD_LABELS: dict[str, str] = {
    "datetime_header": "Дата «Сформирована» (шапка)",
    "amount": "Сумма перевода",
    "commission": "Комиссия",
    "datetime_full": "Дата и время операции",
    "operation_id": "Номер операции",
    "recipient_name": "ФИО получателя",
    "phone": "Телефон получателя",
    "recipient_bank": "Банк получателя",
    "account": "Счёт получателя",
    "sbp_ref": "Идентификатор СБП",
    "purpose": "Назначение / тип перевода",
}

MONEY_FIELDS = frozenset({"amount", "commission"})
# Поля без добивки пробелами; hex в потоке может стать короче (variable-length patch).
COMPACT_TEXT_FIELDS = frozenset({"recipient_bank", "recipient_name"})
ANCHOR_TOLERANCE = 0.06

TJ_AT_POS_RE = re.compile(
    rb"1 0 0 1 ([\d.]+) ([\d.]+) Tm\s*\r?\n(?:/F\d+\s*\r?\n)?\s*[\d.]+ Tf\s*\r?\n<([0-9A-Fa-f]+)>\s*Tj"
)


@dataclass(frozen=True)
class FieldMatch:
    """Поле чека, найденное по координатам в content stream."""

    field_id: str
    y: float
    x: float
    text: str
    raw: bytes
    encoding: str
    offset: int = 0
    cid_map: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def unicode_to_cid(self) -> dict[str, str]:
        return dict(self.cid_map)


# ---------------------------------------------------------------------------
# UTF-16BE: кодирование / декодирование
# ---------------------------------------------------------------------------

def utf16be_encode(text: str) -> bytes:
    """Строка → байты UTF-16BE (без BOM)."""
    return text.encode("utf-16-be")


def utf16be_decode(data: bytes) -> str:
    """Байты UTF-16BE → строка."""
    return data.decode("utf-16-be")


def is_amount_char(ch: str) -> bool:
    return ch.isdigit() or ch in (" ", "\xa0")


def is_amount_text(text: str) -> bool:
    """Строка похожа на денежную сумму (только цифры и пробелы)."""
    if not (MIN_AMOUNT_CHARS <= len(text) <= MAX_AMOUNT_CHARS):
        return False
    if not any(c.isdigit() for c in text):
        return False
    return all(is_amount_char(c) for c in text)


def amount_numeric_value(text: str) -> int:
    """«4 140» / «4\xa0140 RUR» / «4140» → 4140."""
    s = re.sub(r"(?i)RUR", "", text)
    return int(re.sub(r"[\s\xa0]+", "", s))


def format_amount_like(amount: int, template: str) -> str:
    """
    Форматирует сумму по шаблону исходной строки.

    Сохраняет позиции пробелов/неразрывных пробелов и общую длину.
    Если цифр меньше, чем слотов — дополняет ведущими пробелами
    (того же типа, что в шаблоне).
  """
    if amount < 0:
        raise AmountPatchError(f"Сумма не может быть отрицательной: {amount}")

    digit_slots = [i for i, c in enumerate(template) if c.isdigit()]
    if not digit_slots:
        raise AmountPatchError(f"В шаблоне нет цифровых позиций: {template!r}")

    pad_char = "\xa0" if "\xa0" in template else " "
    digits = str(amount)

    if len(digits) > len(digit_slots):
        raise AmountPatchError(
            f"Сумма {amount} ({len(digits)} цифр) не помещается в шаблон "
            f"{template!r} ({len(digit_slots)} цифровых позиций).\n"
            "In-place замена невозможна без изменения длины потока.\n"
            "Альтернатива: перегенерировать PDF из XML через BI Publisher."
        )

    digits = digits.rjust(len(digit_slots), pad_char)
    result = list(template)
    for pos, digit in zip(digit_slots, digits):
        result[pos] = digit
    return "".join(result)


def format_recipient_name(new_value: str, template: str) -> str:
    """
    ФИО получателя: «Фамилия Имя И» — только текст и один NBSP между словами.

    Без добивки до длины шаблона (короче hex в потоке, variable-length patch).
  """
    pad = "\xa0" if "\xa0" in template else " "
    parts = new_value.strip().split()
    while len(parts) < 3:
        parts.append("")
    if len(parts) > 3:
        raise AmountPatchError(
            f"ФИО получателя: ожидается «Фамилия Имя И», получено {new_value!r}"
        )
    family, first, initial = parts[0], parts[1], parts[2]
    if not family:
        raise AmountPatchError("ФИО получателя: не указана фамилия")

    segments: list[str] = [family]
    if first:
        segments.extend([pad, first])
    if initial:
        segments.extend([pad, initial])
    core = "".join(segments)

    if len(core) > len(template):
        raise AmountPatchError(
            f"ФИО {new_value!r} не помещается в поле "
            f"({len(core)} > {len(template)} символов)"
        )
    return core


def format_text_like(new_value: str, template: str) -> str:
    """
    Подгоняет произвольную строку под длину и стиль пробелов шаблона.
    Обычные пробелы во входе заменяются на NBSP, если шаблон использует \\xa0.
    """
    pad = "\xa0" if "\xa0" in template else (" " if " " in template else "\xa0")
    if pad == "\xa0":
        new_value = new_value.replace(" ", "\xa0")

    if len(new_value) == len(template):
        return new_value

    if len(new_value) > len(template):
        raise AmountPatchError(
            f"Значение {new_value!r} длиннее шаблона {template!r} "
            f"({len(new_value)} > {len(template)} символов). "
            "In-place замена невозможна."
        )

    trail = ""
    tmpl = template
    if tmpl.endswith(("\xa0", " ")) and not new_value.endswith(("\xa0", " ")):
        trail = tmpl[-1]
        tmpl = tmpl[:-1]

    if len(new_value) > len(tmpl):
        raise AmountPatchError(
            f"Значение {new_value!r} не помещается в шаблон {template!r}"
        )

    if tmpl and tmpl[0] in (" ", "\xa0"):
        core = new_value.rjust(len(tmpl), pad)
    else:
        core = new_value.ljust(len(tmpl), pad)

    return core + trail


def format_field_value(field_id: str, value: Any, template: str) -> str:
    """Форматирует значение поля под шаблон исходного текста."""
    if field_id == "recipient_name":
        return format_recipient_name(str(value), template)
    if field_id in COMPACT_TEXT_FIELDS:
        return str(value).strip()
    if field_id in MONEY_FIELDS:
        if isinstance(value, str):
            digits = re.sub(r"[\s\xa0]+", "", value.replace("RUR", "").replace("rur", ""))
            if digits.isdigit():
                value = int(digits)
        if isinstance(value, int):
            return format_amount_like(value, template)
    return format_text_like(str(value), template)


def font_charset_report(unicode_to_cid: dict[str, str]) -> str:
    """Строка с доступными символами шрифта чека."""
    letters = sorted({c for c in unicode_to_cid if c.isalpha()}, key=lambda c: (c.islower(), ord(c)))
    digits = "".join(c for c in "0123456789" if c in unicode_to_cid)
    punct = sorted({c for c in unicode_to_cid if not c.isalnum() and c not in "\xa0\uffff"}, key=ord)
    nbsp = "NBSP (\\xa0)" if "\xa0" in unicode_to_cid else ""
    parts = [f"буквы: {''.join(letters)}", f"цифры: {digits}"]
    if punct:
        parts.append(f"знаки: {''.join(punct)}")
    if nbsp:
        parts.append(nbsp)
    return "; ".join(parts)


def chars_needing_font_extension(
    needed: set[str], unicode_to_cid: dict[str, str]
) -> set[str]:
    """Символы, для которых нужно добавлять глифы в subset."""
    return {ch for ch in needed if ch not in unicode_to_cid}


def encode_cid_text(text: str, unicode_to_cid: dict[str, str]) -> bytes:
    """Кодирует строку в CID hex-ASCII."""
    cmap = unicode_to_cid
    missing = sorted({ch for ch in text if ch not in cmap})
    if missing:
        shown = ", ".join(repr(ch) for ch in missing[:12])
        extra = f" и ещё {len(missing) - 12}" if len(missing) > 12 else ""
        raise AmountPatchError(
            f"В шрифте PDF нет символов: {shown}{extra}.\n"
            f"Доступно: {font_charset_report(cmap)}\n"
            "Подсказка: python patch_alfa_amount.py файл.pdf --extend-font"
        )
    parts: list[str] = []
    for ch in text:
        parts.append(cmap[ch].upper())
    return "".join(parts).encode("ascii")


def build_replacement_bytes(match: AmountMatch, new_amount: int) -> bytes:
    """Строит байтовую замену той же длины, что и match.raw."""
    new_text = format_amount_like(new_amount, match.text)

    if match.encoding == "binary":
        new_raw = utf16be_encode(new_text)
    elif match.encoding == "hex_ascii":
        new_raw = utf16be_encode(new_text).hex().upper().encode("ascii")
    elif match.encoding == "cid_zlib":
        cmap = match.unicode_to_cid
        if not cmap:
            raise AmountPatchError("CID-карта шрифта не загружена")
        new_raw = encode_cid_text(new_text, cmap)
    else:
        raise AmountPatchError(f"Неизвестная кодировка: {match.encoding}")

    if len(new_raw) != len(match.raw):
        raise AmountPatchError(
            f"Внутренняя ошибка: длина замены {len(new_raw)} != {len(match.raw)} "
            f"({match.text!r} -> {new_text!r})"
        )
    return new_raw


# ---------------------------------------------------------------------------
# Поиск суммы в PDF
# ---------------------------------------------------------------------------

def _parse_utf16be_amount_at(data: bytes, start: int) -> tuple[str, int] | None:
    """
    Пытается прочитать UTF-16BE-цепочку цифр/пробелов с позиции start.
    Возвращает (текст, конец) или None.
    """
    if start + 1 >= len(data):
        return None
    if not (data[start] == 0x00 and 0x30 <= data[start + 1] <= 0x39):
        return None

    pos = start
    while pos + 1 < len(data):
        hi, lo = data[pos], data[pos + 1]
        if hi == 0x00 and (0x30 <= lo <= 0x39 or lo in (0x20, 0xA0)):
            pos += 2
        else:
            break

    if pos == start:
        return None

    chunk = data[start:pos]
    try:
        text = utf16be_decode(chunk)
    except UnicodeDecodeError:
        return None

    if not is_amount_text(text):
        return None
    return text, pos


def _score_amount_candidate(data: bytes, start: int, end: int, text: str) -> int:
    """Чем выше score, тем вероятнее, что это основная сумма операции."""
    score = len(text) * 10

    # Тысячный разделитель (пробел или NBSP)
    if " " in text or "\xa0" in text:
        score += 40

    # Близость к «RUR»
    window = data[end : end + 120]
    if RUR_UTF16BE in window or RUR_HEX_ASCII in window or b"RUR" in window:
        score += 200

    # Типичный диапазон сумм перевода
    try:
        val = amount_numeric_value(text)
        if 1 <= val <= 9_999_999:
            score += 30
    except ValueError:
        score -= 100

    # Штраф за «годоподобные» последовательности (2010, 2016 …)
    digits_only = re.sub(r"[\s\xa0]", "", text)
    if len(digits_only) == 4 and digits_only.startswith(("19", "20")):
        score -= 80

    # Штраф за тестовые последовательности
    if digits_only in ("0123456789", "1234567890"):
        score -= 200

    return score


def scan_binary_utf16be(data: bytes) -> list[AmountMatch]:
    """Ищет бинарные UTF-16BE суммы во всём файле."""
    matches: list[AmountMatch] = []
    seen: set[tuple[int, bytes]] = set()
    i = 0
    while i < len(data) - 3:
        parsed = _parse_utf16be_amount_at(data, i)
        if parsed is None:
            i += 1
            continue
        text, end = parsed
        raw = data[i:end]
        key = (i, raw)
        if key not in seen:
            seen.add(key)
            score = _score_amount_candidate(data, i, end, text)
            matches.append(
                AmountMatch(
                    offset=i,
                    raw=raw,
                    text=text,
                    encoding="binary",
                    score=score,
                )
            )
        i = end if end > i else i + 2
    return matches


# Каждый code unit UTF-16BE = 4 hex-символа, старший байт 0x00 для цифр/пробелов
_HEX_ASCII_RE = re.compile(
    rb"(?i)(?:00[0-9a-f]{2})"
    + b"{"
    + str(MIN_AMOUNT_CHARS).encode()
    + b","
    + str(MAX_AMOUNT_CHARS).encode()
    + b"}"
)


def scan_hex_ascii_utf16be(data: bytes) -> list[AmountMatch]:
    """
    Ищет суммы, записанные как hex-ASCII (типично внутри <...> Tj).
    Пример: 003400A0003100340030 = «4\xa0140» UTF-16BE.
    """
    matches: list[AmountMatch] = []
    seen: set[tuple[int, bytes]] = set()

    for m in _HEX_ASCII_RE.finditer(data):
        raw = m.group()
        # длина hex должна быть чётной и соответствовать UTF-16BE code units
        if len(raw) % 4 != 0:
            continue
        try:
            chunk = bytes.fromhex(raw.decode("ascii"))
            text = utf16be_decode(chunk)
        except (ValueError, UnicodeDecodeError):
            continue
        if not is_amount_text(text):
            continue
        key = (m.start(), raw)
        if key in seen:
            continue
        seen.add(key)
        score = _score_amount_candidate(data, m.start(), m.end(), text)
        matches.append(
            AmountMatch(
                offset=m.start(),
                raw=raw,
                text=text,
                encoding="hex_ascii",
                score=score,
            )
        )
    return matches


# ---------------------------------------------------------------------------
# CID-глифы Tahoma (original.pdf, pdf 58.pdf, KEYS.pdf)
# ---------------------------------------------------------------------------

STREAM_RE = re.compile(rb"(stream\r?\n)(.*?)(\r?\nendstream)", re.S)


def _parse_cmap_bfchar(cmap_data: bytes) -> dict[str, str]:
    """Парсит beginbfchar из ToUnicode → {символ: CID-hex}."""
    unicode_to_cid: dict[str, str] = {}
    seen_cids: set[str] = set()
    for m in re.finditer(rb"<([0-9A-Fa-f]{4})>\s*<([0-9A-Fa-f]{4})>", cmap_data):
        cid = m.group(1).decode().upper()
        if cid in seen_cids:
            continue
        seen_cids.add(cid)
        codepoint = int(m.group(2).decode(), 16)
        unicode_to_cid[chr(codepoint)] = cid
    return unicode_to_cid


def load_unicode_to_cid(pdf_path: Path) -> dict[str, str]:
    """Загружает карту символ→CID из /ToUnicode шрифта F1."""
    try:
        import pypdf
    except ImportError as exc:
        raise AmountPatchError("Для CID-чеков нужен пакет pypdf: pip install pypdf") from exc

    reader = pypdf.PdfReader(str(pdf_path))
    page = reader.pages[0]
    fonts = page["/Resources"]["/Font"]
    font = fonts.get("/F1") or next(iter(fonts.values()))
    to_unicode = font["/ToUnicode"]
    cmap_data = (
        to_unicode.get_data()
        if hasattr(to_unicode, "get_data")
        else to_unicode.get_object().get_data()
    )
    mapping = _parse_cmap_bfchar(cmap_data)
    if not mapping:
        raise AmountPatchError("ToUnicode CMap пуст или не распознан")
    return mapping


def decode_cid_hex(hex_str: str, unicode_to_cid: dict[str, str]) -> str:
    cid_to_char: dict[str, str] = {}
    for ch, cid in unicode_to_cid.items():
        key = cid.upper()
        if key not in cid_to_char:
            cid_to_char[key] = ch
    chars: list[str] = []
    for i in range(0, len(hex_str), 4):
        cid = hex_str[i : i + 4].upper()
        chars.append(cid_to_char.get(cid, "?"))
    return "".join(chars)


def _match_anchor(y: float, x: float, anchor_y: float, anchor_x: float) -> bool:
    return abs(y - anchor_y) <= ANCHOR_TOLERANCE and abs(x - anchor_x) <= ANCHOR_TOLERANCE


def _classify_field(y: float, x: float) -> str | None:
    for field_id, (ay, ax) in FIELD_ANCHORS.items():
        if _match_anchor(y, x, ay, ax):
            return field_id
    return None


def discover_fields_in_bytes(
    data: bytes,
    unicode_to_cid: dict[str, str],
) -> dict[str, FieldMatch]:
    """Находит поля чека в уже загруженных байтах PDF."""
    cid_map_tuple = tuple(unicode_to_cid.items())
    fields: dict[str, FieldMatch] = {}

    for m in STREAM_RE.finditer(data):
        stream_raw = m.group(2)
        try:
            dec = zlib.decompress(stream_raw)
        except zlib.error:
            continue

        for tm in TJ_AT_POS_RE.finditer(dec):
            x = float(tm.group(1))
            y = float(tm.group(2))
            hex_str = tm.group(3).decode().upper()
            if len(hex_str) < 8:
                continue

            field_id = _classify_field(y, x)
            if field_id is None:
                continue

            text = decode_cid_hex(hex_str, unicode_to_cid)
            if len(text.strip("\xa0 ")) < 1:
                continue

            fields[field_id] = FieldMatch(
                field_id=field_id,
                y=y,
                x=x,
                text=text,
                raw=hex_str.encode("ascii"),
                encoding="cid_zlib",
                offset=m.start(),
                cid_map=cid_map_tuple,
            )

    return fields


def discover_fields(pdf_path: str | Path) -> dict[str, FieldMatch]:
    """Находит все редактируемые поля чека по координатам в PDF."""
    src = Path(pdf_path)
    if not src.is_file():
        raise AmountPatchError(f"Файл не найден: {src}")

    return discover_fields_in_bytes(src.read_bytes(), load_unicode_to_cid(src))


def find_cid_amount_match(pdf_path: Path, data: bytes) -> AmountMatch:
    """Ищет сумму+RUR по якорю amount в zlib-потоке."""
    fields = discover_fields(pdf_path)
    if "amount" not in fields:
        raise AmountPatchError(
            "Сумма не найдена (ни UTF-16BE, ни CID по якорю amount).\n"
            "Проверьте, что файл — чек Альфа-Банка (BI Publisher)."
        )
    fm = fields["amount"]
    return AmountMatch(
        offset=fm.offset,
        raw=fm.raw,
        text=fm.text,
        encoding=fm.encoding,
        score=500,
        cid_map=fm.cid_map,
    )


def recompress_to_size(dec: bytes, target: int) -> bytes | None:
    """Подбирает zlib-сжатие того же размера, что и оригинальный поток."""
    for level in range(10):
        c = zlib.compress(dec, level)
        if len(c) == target:
            return c
    for pad in range(1, 512):
        suffix = b"\n%" + (b"%" * pad)
        for level in range(10):
            c = zlib.compress(dec + suffix, level)
            if len(c) == target:
                return c
    return None


def _update_stream_length(data: bytearray, before_stream: int, new_len: int) -> None:
    window = data[max(0, before_stream - 400) : before_stream]
    matches = list(re.finditer(rb"/Length\s+(\d+)", window))
    if not matches:
        raise AmountPatchError("/Length не найден перед stream")
    m = matches[-1]
    base = max(0, before_stream - 400)
    abs_start = base + m.start(1)
    abs_end = base + m.end(1)
    old = data[abs_start:abs_end].decode()
    repl = str(new_len).encode()
    if len(repl) != len(old):
        raise AmountPatchError(f"Ширина /Length изменилась: {old!r} -> {new_len}")
    data[abs_start:abs_end] = repl


def _fix_xref_offsets(data: bytearray, pivot: int, delta: int) -> None:
    if delta == 0:
        return
    trailer_at = data.rfind(b"trailer")
    startxref_at = data.rfind(b"startxref")
    if trailer_at < 0 or startxref_at < 0:
        raise AmountPatchError("trailer/startxref не найден")

    xref_at = data.rfind(b"xref\r", 0, trailer_at)
    if xref_at < 0:
        xref_at = data.rfind(b"xref\n", 0, trailer_at)
    if xref_at < 0:
        raise AmountPatchError("xref не найден")

    body = data[xref_at:trailer_at]
    new_lines: list[bytes] = []
    for line in body.splitlines(keepends=True):
        core = line.rstrip(b"\r\n")
        ending = line[len(core) :]
        parts = core.split()
        if len(parts) == 3 and parts[2] == b"n":
            off = int(parts[0])
            if off >= pivot:
                off += delta
                core = f"{off:010d} {parts[1].decode()} n".encode()
        new_lines.append(core + ending)
    data[xref_at:trailer_at] = b"".join(new_lines)

    sx = re.search(rb"startxref\r?\n(\d+)", data[startxref_at : startxref_at + 40])
    if not sx:
        raise AmountPatchError("startxref не найден")
    old_sx = int(sx.group(1))
    new_sx = old_sx + delta if old_sx >= pivot else old_sx
    abs_s = startxref_at + sx.start(1)
    abs_e = startxref_at + sx.end(1)
    repl = str(new_sx).encode()
    if len(repl) != abs_e - abs_s:
        raise AmountPatchError("Ширина startxref изменилась")
    data[abs_s:abs_e] = repl


def patch_cid_zlib_streams_multi(
    data: bytearray,
    replacements: list[tuple[bytes, bytes]],
    *,
    allow_variable_length: bool = False,
) -> str:
    """Заменяет несколько CID hex в zlib-потоке за один проход."""
    if not replacements:
        raise AmountPatchError("Нет замен для применения")

    for old_hex, new_hex in replacements:
        if len(old_hex) != len(new_hex) and not allow_variable_length:
            raise AmountPatchError(
                f"CID hex должен быть той же длины: {len(old_hex)} != {len(new_hex)}"
            )

    # длинные паттерны первыми — избегаем частичных совпадений
    replacements = sorted(replacements, key=lambda p: len(p[0]), reverse=True)

    out = bytearray()
    pos = 0
    hits = 0
    mode = "in_place"
    patch_info: tuple[int, int, int] | None = None

    for m in STREAM_RE.finditer(data):
        out.extend(data[pos : m.start()])
        header, stream_raw, footer = m.group(1), m.group(2), m.group(3)

        try:
            dec = zlib.decompress(stream_raw)
        except zlib.error:
            out.extend(m.group(0))
            pos = m.end()
            continue

        new_dec = dec
        stream_hits = 0
        for old_hex, new_hex in replacements:
            if old_hex in new_dec:
                new_dec = new_dec.replace(old_hex, new_hex, 1)
                stream_hits += 1

        if stream_hits == 0:
            out.extend(m.group(0))
            pos = m.end()
            continue

        hits += stream_hits
        new_stream = recompress_to_size(new_dec, len(stream_raw))
        if new_stream is None:
            new_stream = zlib.compress(new_dec, 9)
            mode = "length_xref"
        elif mode != "length_xref":
            mode = "in_place"

        before_stream = len(out) + len(header)
        patch_info = (before_stream, len(stream_raw), len(new_stream))
        out.extend(header)
        out.extend(new_stream)
        out.extend(footer)
        pos = m.end()

    if hits == 0:
        raise AmountPatchError("Ни одно поле не найдено в zlib-потоке")

    out.extend(data[pos:])
    result = bytearray(out)

    if patch_info and mode == "length_xref":
        before_stream, _old_len, new_len = patch_info
        delta = len(result) - len(data)
        if delta:
            _update_stream_length(result, before_stream, new_len)
            _fix_xref_offsets(result, before_stream, delta)

    data[:] = result
    return mode


def patch_cid_zlib_stream(data: bytearray, old_hex: bytes, new_hex: bytes) -> str:
    """Заменяет одно CID hex в zlib-потоке."""
    return patch_cid_zlib_streams_multi(data, [(old_hex, new_hex)])


def _raw_hex_display(raw: bytes, encoding: str) -> str:
    if encoding in ("hex_ascii", "cid_zlib"):
        return raw.decode("ascii").upper()
    return raw.hex().upper()


def find_amount_in_pdf(input_pdf: str | Path) -> AmountMatch:
    """Находит сумму в PDF без изменения файла (для диагностики)."""
    src = Path(input_pdf)
    if not src.is_file():
        raise AmountPatchError(f"Файл не найден: {src}")
    return find_best_amount_match(src.read_bytes(), src)


def find_best_amount_match(data: bytes, pdf_path: Path | None = None) -> AmountMatch:
    """Находит наиболее вероятное вхождение суммы."""
    candidates = scan_binary_utf16be(data) + scan_hex_ascii_utf16be(data)
    if candidates:
        candidates.sort(key=lambda m: (-m.score, -m.offset))
        best = candidates[0]
        if len(candidates) > 1 and candidates[1].score >= best.score - 20:
            dupes = [c for c in candidates if c.score >= best.score - 20][:5]
            lines = [
                f"  offset 0x{c.offset:X}: {c.text!r} "
                f"(score={c.score}, {c.encoding})"
                for c in dupes
            ]
            print(
                "Предупреждение: найдено несколько кандидатов, выбран лучший по score:\n"
                + "\n".join(lines),
                file=sys.stderr,
            )
        return best

    if pdf_path is None:
        raise AmountPatchError(
            "UTF-16BE сумма не найдена. Для CID-чеков укажите путь к PDF."
        )
    return find_cid_amount_match(pdf_path, data)


def _field_match_to_amount(match: FieldMatch) -> AmountMatch:
    return AmountMatch(
        offset=match.offset,
        raw=match.raw,
        text=match.text,
        encoding=match.encoding,
        score=500,
        cid_map=match.cid_map,
    )


def _display_text(text: str) -> str:
    return text.replace("\xa0", " ")


def _refresh_field_cmaps(
    fields: dict[str, FieldMatch], cmap: dict[str, str]
) -> dict[str, FieldMatch]:
    cmap_tuple = tuple(cmap.items())
    return {field_id: replace(fm, cid_map=cmap_tuple) for field_id, fm in fields.items()}


def _ensure_needed_chars(
    data: bytearray,
    pdf_path: Path,
    needed: set[str],
    *,
    extend_font: bool,
) -> tuple[dict[str, str], bool, tuple[str, ...]]:
    cmap = load_unicode_to_cid(pdf_path)
    if not extend_font:
        return cmap, False, ()
    missing = chars_needing_font_extension(needed, cmap)
    if not missing:
        return cmap, False, ()
    from font_extend import ensure_chars_in_pdf

    result = ensure_chars_in_pdf(data, pdf_path, needed, full_cyrillic=True)
    if result.extended and len(data) > MAX_PDF_BYTES:
        raise AmountPatchError(
            f"После расширения шрифта PDF стал {len(data)} байт — больше лимита "
            f"{MAX_PDF_BYTES} (~60 КБ). Соберите компактный шаблон:\n"
            "  python patch_alfa_amount.py --build-template"
        )
    return result.cmap, result.extended, result.added_chars


def show_charset_report(pdf_path: Path, *, extended: bool = False) -> None:
    """Печатает символы, доступные в шрифте PDF."""
    src = Path(pdf_path)
    if not src.is_file():
        raise AmountPatchError(f"Файл не найден: {src}")
    if extended:
        from font_extend import FULL_CYRILLIC, extend_font_compact_in_pdf_bytes

        data = bytearray(src.read_bytes())
        result = extend_font_compact_in_pdf_bytes(
            data, src, chars=set(FULL_CYRILLIC)
        )
        cmap = result.cmap
        label = f"после расширения ({len(cmap)} символов)"
        if result.extended:
            print(f"Добавлено глифов: {len(result.added_chars)}")
    else:
        cmap = load_unicode_to_cid(src)
        label = f"встроенный subset ({len(cmap)} символов)"
    print(f"Шрифт в {src.name} — {label}:\n")
    print(f"  {font_charset_report(cmap)}")
    print(
        "\nЗаглавные и строчные — разные символы.\n"
        "Пробелы в полях чека — обычно неразрывный пробел (NBSP).\n"
        "При патче недостающие буквы добавляются из Tahoma автоматически."
    )


def list_fields_report(pdf_path: Path) -> None:
    """Печатает все поля чека и их текущие значения."""
    fields = discover_fields(pdf_path)
    if not fields:
        print("Поля не найдены (возможно, не CID-чек).")
        return
    print(f"Поля в {pdf_path.name}:\n")
    for field_id in FIELD_ANCHORS:
        if field_id not in fields:
            continue
        fm = fields[field_id]
        label = FIELD_LABELS.get(field_id, field_id)
        print(f"  --{field_id.replace('_', '-')}")
        print(f"      {label}")
        print(f"      сейчас: {_display_text(fm.text)!r}")
        print(f"      длина:  {len(fm.text)} символов ({len(fm.raw)} hex)")
        print()


# ---------------------------------------------------------------------------
# Замена и проверка
# ---------------------------------------------------------------------------

def replace_fields_in_pdf(
    input_pdf: str | Path,
    field_values: dict[str, Any],
    output_pdf: str | Path | None = None,
    *,
    verify: bool = True,
    extend_font: bool = True,
    compact_font_donor: Path | None = None,
) -> dict:
    """
    Заменяет одно или несколько полей чека.

    field_values — словарь {field_id: значение}, например:
      {"amount": 5294, "commission": 0, "phone": "+7 (916) 685-44-81"}
    """
    if not field_values:
        raise AmountPatchError("Не указано ни одного поля для замены")

    src = Path(input_pdf)
    if not src.is_file():
        raise AmountPatchError(f"Файл не найден: {src}")

    discovered = discover_fields(src)
    if not discovered:
        if set(field_values.keys()) == {"amount"}:
            return _replace_utf16be_amount(
                src, field_values["amount"], output_pdf, verify=verify
            )
        raise AmountPatchError(
            "Поля чека не найдены. Используйте --list-fields для диагностики."
        )

    missing = [k for k in field_values if k not in discovered]
    if missing:
        known = ", ".join(sorted(discovered))
        raise AmountPatchError(
            f"Поле(я) не найдены в PDF: {', '.join(missing)}\n"
            f"Доступные поля: {known}\n"
            "Подсказка: python patch_alfa_amount.py файл.pdf --list-fields"
        )

    if output_pdf is None:
        suffix = "_patched"
        if "amount" in field_values:
            suffix = f"_amount_{field_values['amount']}"
        dst = src.with_name(f"{src.stem}{suffix}{src.suffix}")
    else:
        dst = Path(output_pdf)

    original = bytearray(src.read_bytes())
    original_size = len(original)

    needed_chars: set[str] = set()
    for field_id, value in field_values.items():
        fm = discovered[field_id]
        new_text = format_field_value(field_id, value, fm.text)
        needed_chars.update(new_text)

    cmap, font_extended, added_chars = _ensure_needed_chars(
        original, src, needed_chars, extend_font=extend_font
    )
    if font_extended:
        discovered = discover_fields_in_bytes(bytes(original), cmap)

    prepared: list[tuple[str, FieldMatch, str]] = []
    for field_id, value in field_values.items():
        fm = discovered[field_id]
        new_text = format_field_value(field_id, value, fm.text)
        prepared.append((field_id, fm, new_text))

    replacements: list[tuple[bytes, bytes]] = []
    changes: dict[str, dict[str, str]] = {}

    allow_variable_length = False
    for field_id, fm, new_text in prepared:
        new_raw = encode_cid_text(new_text, cmap)
        if len(new_raw) != len(fm.raw):
            if field_id not in COMPACT_TEXT_FIELDS:
                raise AmountPatchError(
                    f"Поле {field_id}: длина hex изменилась "
                    f"({len(fm.raw)} -> {len(new_raw)})"
                )
            allow_variable_length = True
        replacements.append((fm.raw, new_raw))
        changes[field_id] = {
            "old": fm.text,
            "new": new_text,
            "hex_old": fm.raw.decode("ascii"),
            "hex_new": new_raw.decode("ascii"),
        }

    patch_mode = patch_cid_zlib_streams_multi(
        original, replacements, allow_variable_length=allow_variable_length
    )

    font_swapped = False
    if compact_font_donor is not None:
        from font_extend import fit_pdf_to_target, swap_font_from_donor_pdf

        swap_font_from_donor_pdf(original, compact_font_donor, cmap=cmap)
        font_swapped = True
        patch_mode = "compact_font"

    dst.parent.mkdir(parents=True, exist_ok=True)
    from font_extend import fit_pdf_to_target, minify_pdf_streams

    if font_swapped:
        minify_pdf_streams(original)
        if len(original) > MAX_PDF_BYTES:
            fit_pdf_to_target(original, MAX_PDF_BYTES)
    else:
        fit_pdf_to_target(original, original_size)
    dst.write_bytes(original)

    if font_swapped:
        validate_bot_critical_cids(dst)
        post_cmap = load_unicode_to_cid(dst)
        if post_cmap.get("У") != "008A":
            raise AmountPatchError(
                "После подмены шрифта У→CID "
                f"{post_cmap.get('У', 'MISSING')} вместо 008A — бот не распознает чек.\n"
                "Соберите без compact_font_donor (шаблон lauchj.pdf / test_patch.pdf)."
            )

    result: dict[str, Any] = {
        "input": str(src),
        "output": str(dst),
        "fields": changes,
        "patch_mode": patch_mode,
        "font_extended": font_extended,
        "font_chars_added": list(added_chars),
        "font_swapped": font_swapped,
        "size_unchanged": len(original) == original_size,
        "qpdf_ok": None,
    }

    if verify:
        expect_size = original_size if patch_mode == "in_place" else None
        result["qpdf_ok"] = verify_pdf_integrity(dst, expected_size=expect_size)

    return result


def _replace_utf16be_amount(
    src: Path,
    new_amount: int,
    output_pdf: str | Path | None,
    *,
    verify: bool,
) -> dict:
    """Замена суммы в UTF-16BE-чеке (без CID-полей)."""
    if output_pdf is None:
        dst = src.with_name(f"{src.stem}_amount_{new_amount}{src.suffix}")
    else:
        dst = Path(output_pdf)

    original = bytearray(src.read_bytes())
    original_size = len(original)
    match = find_best_amount_match(bytes(original), None)

    replacement = build_replacement_bytes(match, new_amount)
    new_text = format_amount_like(new_amount, match.text)
    off = match.offset
    original[off : off + len(match.raw)] = replacement

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(original)

    result: dict[str, Any] = {
        "input": str(src),
        "output": str(dst),
        "fields": {
            "amount": {
                "old": match.text,
                "new": new_text,
                "hex_old": _raw_hex_display(match.raw, match.encoding),
                "hex_new": _raw_hex_display(replacement, match.encoding),
            }
        },
        "patch_mode": "raw",
        "size_unchanged": len(original) == original_size,
        "qpdf_ok": None,
        "encoding": match.encoding,
    }
    if verify:
        result["qpdf_ok"] = verify_pdf_integrity(dst, expected_size=original_size)
    return result


def replace_amount_in_pdf(
    input_pdf: str | Path,
    new_amount: int,
    output_pdf: str | Path | None = None,
    *,
    verify: bool = True,
    match: AmountMatch | None = None,
) -> dict:
    """
    Заменяет сумму в PDF и сохраняет результат.

    Args:
        input_pdf: путь к исходному PDF
        new_amount: новая сумма в рублях (целое число)
        output_pdf: путь для сохранения (по умолчанию <имя>_amount_<N>.pdf)
        verify: запускать qpdf --check и сравнение размеров
        match: явно указанное вхождение (для тестов / повторного использования)

    Returns:
        dict с полями: old_amount, new_amount, old_text, new_text,
        offset, encoding, size_unchanged, qpdf_ok
    """
    info = replace_fields_in_pdf(
        input_pdf,
        {"amount": new_amount},
        output_pdf,
        verify=verify,
    )
    amount_change = info["fields"]["amount"]
    return {
        **info,
        "old_amount": amount_numeric_value(amount_change["old"]),
        "new_amount": new_amount,
        "old_text": amount_change["old"],
        "new_text": amount_change["new"],
        "encoding": "cid_zlib",
        "raw_hex_old": amount_change["hex_old"],
        "raw_hex_new": amount_change["hex_new"],
    }


def find_qpdf_executable() -> str | None:
    """Ищет qpdf.exe в PATH и типичных путях установки на Windows."""
    found = shutil.which("qpdf")
    if found:
        return found

    if sys.platform == "win32":
        candidates: list[Path] = []
        for base in (Path(r"C:\Program Files"), Path(r"C:\Program Files (x86)")):
            if base.is_dir():
                candidates.extend(sorted(base.glob("qpdf*/bin/qpdf.exe"), reverse=True))
        local = Path.home() / "AppData/Local/Programs"
        if local.is_dir():
            candidates.extend(sorted(local.glob("qpdf*/bin/qpdf.exe"), reverse=True))
        for exe in candidates:
            if exe.is_file():
                return str(exe)
    return None


def verify_pdf_integrity(path: Path | str, expected_size: int | None = None) -> bool:
    """
    Проверяет целостность PDF через qpdf (если установлен).
    Возвращает True при успехе, False при ошибках, None если qpdf недоступен.
    """
    path = Path(path)
    ok = True

    if expected_size is not None:
        actual = path.stat().st_size
        if actual != expected_size:
            print(
                f"ПРЕДУПРЕЖДЕНИЕ: размер изменился {expected_size} -> {actual} байт. "
                "Целостность xref может быть нарушена.",
                file=sys.stderr,
            )
            ok = False
        else:
            print(f"Размер файла не изменился: {actual} байт")

    qpdf = find_qpdf_executable()
    if not qpdf:
        print(
            "ПРЕДУПРЕЖДЕНИЕ: qpdf не найден. Установите: winget install QPDF.QPDF\n"
            "  или добавьте в PATH: C:\\Program Files\\qpdf 12.3.2\\bin",
            file=sys.stderr,
        )
        return None if ok else False

    proc = subprocess.run(
        [qpdf, "--check", "--warning-exit-0", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode == 0:
        print("qpdf --check: структура PDF в порядке")
    else:
        print("ПРЕДУПРЕЖДЕНИЕ: qpdf обнаружил проблемы:", file=sys.stderr)
        if proc.stdout:
            print(proc.stdout, file=sys.stderr)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        ok = False

    return ok


def _display_amount(text: str) -> str:
    return text.replace("\xa0", " ")


# Пути по умолчанию (можно запускать без аргументов)
DEFAULT_INPUT = Path(r"C:\Users\Жопсик\Desktop\original.pdf")
# Шаблон для onlypdf_robot / pdf_receipt_checker (subset UHQZMV+Tahoma, без расширения шрифта)
DEFAULT_BOT_SAFE_INPUT = Path(r"C:\Users\Жопсик\Desktop\pdf 58.pdf")
# Полный алфавит: один раз собирается через --build-template
DEFAULT_ORIGINAL_FULLFONT = Path(r"C:\Users\Жопсик\Desktop\original_fullfont.pdf")
DEFAULT_BOT_SAFE_FULLFONT = Path(r"C:\Users\Жопсик\Desktop\pdf58_fullfont.pdf")
# Полная кириллица + onlypdf_robot (~58320 байт, шрифт без hinting — чуть «сплющеннее»)
DEFAULT_BOT_SQUASH = Path(r"C:\Users\Жопсик\Desktop\pdf58_squash.pdf")
# Шаблон, который проходит onlypdf_robot: ~73 КБ, hinting сохранён, У→CID 008A (как lauchj.pdf).
DEFAULT_BOT_PASS_TEMPLATE = Path(r"C:\Users\Жопсик\Desktop\test_patch.pdf")
# Лимит для компактного squash-шаблона (~60 КБ). Bot-pass без подмены шрифта ~73 КБ.
MAX_PDF_BYTES = 60 * 1024
MAX_PDF_BYTES_BOT_PASS = 76 * 1024
BOT_SAFE_FONT_MARKER = "UHQZMV"
FULL_CYRILLIC = (
    "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
)
# CID-отпечатки pdf 58, которые onlypdf_robot сверяет в content stream.
BOT_CRITICAL_CHARS = "ВТБBYжных"
DEFAULT_AMOUNT = 5294


def bot_critical_cid_map(pdf_path: str | Path) -> dict[str, str]:
    """CID критичных символов шаблона pdf 58 (для сверки с ботом)."""
    return {
        ch: cid
        for ch, cid in load_unicode_to_cid(pdf_path).items()
        if ch in BOT_CRITICAL_CHARS
    }


def validate_bot_critical_cids(
    pdf_path: str | Path,
    *,
    reference: Path | None = None,
) -> None:
    """Проверяет, что CID критичных символов совпадают с pdf 58."""
    ref = reference or DEFAULT_BOT_SAFE_INPUT
    if not ref.is_file():
        return
    expected = bot_critical_cid_map(ref)
    actual = bot_critical_cid_map(pdf_path)
    drift = [
        f"  • {ch!r}: pdf58={expected[ch]} шаблон={actual.get(ch, 'MISSING')}"
        for ch in sorted(expected, key=ord)
        if actual.get(ch) != expected[ch]
    ]
    if drift:
        raise AmountPatchError(
            "Шаблон сдвинул CID-отпечатки pdf 58 — бот не распознает чек:\n"
            + "\n".join(drift)
            + "\nПересоберите: python patch_alfa_amount.py --build-squash-template"
        )


def has_full_cyrillic_charset(unicode_to_cid: dict[str, str]) -> bool:
    return all(ch in unicode_to_cid for ch in FULL_CYRILLIC)


def has_full_receipt_charset(unicode_to_cid: dict[str, str]) -> bool:
    """Полная кириллица + латиница для sbp_ref (AGM и буквы из исходного subset)."""
    from font_extend import full_template_charset

    return all(ch in unicode_to_cid for ch in full_template_charset(unicode_to_cid))


def _fullfont_for_template(template: Path) -> Path | None:
    resolved = {
        DEFAULT_INPUT.resolve(): DEFAULT_ORIGINAL_FULLFONT,
        DEFAULT_BOT_SAFE_INPUT.resolve(): DEFAULT_BOT_SAFE_FULLFONT,
    }.get(template.resolve())
    if resolved and resolved.is_file():
        return resolved
    return None


def resolve_fullfont_input(explicit: Path) -> Path:
    """Предпочитает *_fullfont.pdf, если шаблон уже собран."""
    fullfont = _fullfont_for_template(explicit)
    return fullfont if fullfont else explicit


def resolve_bot_squash_input(explicit: Path) -> Path:
    """Подставляет pdf58_squash.pdf при патче pdf 58."""
    if explicit.resolve() == DEFAULT_BOT_SAFE_INPUT.resolve():
        if not DEFAULT_BOT_SQUASH.is_file():
            raise AmountPatchError(
                f"Шаблон {DEFAULT_BOT_SQUASH.name} не найден.\n"
                "Соберите один раз:\n"
                "  python patch_alfa_amount.py --build-squash-template"
            )
        return DEFAULT_BOT_SQUASH
    return explicit


def _bot_pass_template_candidates() -> list[Path]:
    """Ищет готовый bot-pass шаблон (~73 КБ, 160 глифов, hinting)."""
    desktop = DEFAULT_BOT_SAFE_INPUT.parent
    names = (
        "test_patch.pdf",
        "pdf58_bot_pass.pdf",
        "lauchj.pdf",
    )
    out: list[Path] = []
    for name in names:
        p = desktop / name
        if p.is_file() and p.resolve() not in {x.resolve() for x in out}:
            out.append(p)
    if DEFAULT_BOT_PASS_TEMPLATE.is_file():
        if DEFAULT_BOT_PASS_TEMPLATE.resolve() not in {x.resolve() for x in out}:
            out.insert(0, DEFAULT_BOT_PASS_TEMPLATE)
    return out


def _validate_bot_pass_template(path: Path) -> None:
    """Проверяет, что шаблон похож на проходящий чек (lauchj / test_patch)."""
    try:
        import pypdf
        from io import BytesIO
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        raise AmountPatchError("Для --bot-pass нужны pypdf и fonttools") from exc

    if BOT_SAFE_FONT_MARKER not in pdf_base_font_name(path):
        raise AmountPatchError(
            f"Шаблон {path.name} должен быть pdf 58 ({BOT_SAFE_FONT_MARKER}+Tahoma)."
        )
    cmap = load_unicode_to_cid(path)
    if not has_full_cyrillic_charset(cmap):
        raise AmountPatchError(
            f"Шаблон {path.name} без полной кириллицы — соберите bot-pass шаблон."
        )
    if cmap.get("У") != "008A":
        raise AmountPatchError(
            f"Шаблон {path.name}: У должен быть CID 008A (как в lauchj.pdf), "
            f"сейчас {cmap.get('У', 'MISSING')}."
        )
    ff = (
        pypdf.PdfReader(str(path))
        .pages[0]["/Resources"]["/Font"]["/F1"]["/DescendantFonts"][0]
        ["/FontDescriptor"]["/FontFile2"]
        .get_data()
    )
    font = TTFont(BytesIO(ff))
    hints = any(tag in font for tag in ("fpgm", "prep", "cvt "))
    glyphs = font["maxp"].numGlyphs
    size = path.stat().st_size
    if glyphs < 155 or not hints or size < 70_000:
        raise AmountPatchError(
            f"Шаблон {path.name} не похож на проходящий чек: "
            f"size={size}, glyphs={glyphs}, hinting={hints}.\n"
            f"Нужен test_patch.pdf (~73505 байт) или lauchj.pdf как основа."
        )
    validate_bot_critical_cids(path)


def resolve_bot_pass_input(explicit: Path) -> Path:
    """
    Шаблон для onlypdf_robot: ~73 КБ, hinting сохранён (НЕ squash 58320).

    Squash-шаблон pdf58_squash.pdf даёт «чек не распознан» — бот сверяет
    отпечаток шрифта с проходящими чеками вроде lauchj.pdf.
    """
    if explicit.resolve() != DEFAULT_BOT_SAFE_INPUT.resolve():
        _validate_bot_pass_template(explicit)
        return explicit
    for candidate in _bot_pass_template_candidates():
        try:
            _validate_bot_pass_template(candidate)
            return candidate
        except AmountPatchError:
            continue
    raise AmountPatchError(
        "Не найден bot-pass шаблон (test_patch.pdf / lauchj.pdf на рабочем столе).\n"
        "Скопируйте test_patch.pdf или соберите:\n"
        "  python patch_alfa_amount.py --build-bot-pass-template"
    )


def build_bot_pass_template(
    source: Path | None = None,
    output: Path | None = None,
) -> Path:
    """
    Копирует готовый проходящий шаблон (test_patch.pdf) в pdf58_bot_pass.pdf.

    Шаблон нельзя надёжно пересобрать из pdf 58 компактным расширением:
    onlypdf_robot принимает ~73 КБ / 160 глифов / У→008A, а не squash 58320.
    """
    dst = output or DEFAULT_BOT_SAFE_INPUT.parent / "pdf58_bot_pass.pdf"
    for candidate in _bot_pass_template_candidates():
        try:
            _validate_bot_pass_template(candidate)
            import shutil

            shutil.copy2(candidate, dst)
            _validate_bot_pass_template(dst)
            return dst
        except AmountPatchError:
            continue
    src = source or DEFAULT_BOT_SAFE_INPUT
    raise AmountPatchError(
        f"На рабочем столе нет test_patch.pdf / lauchj.pdf для копирования.\n"
        f"Положите test_patch.pdf рядом с {src.name} и повторите."
    )


def _find_legacy_squash_template() -> Path | None:
    """Ищет ранее собранный squash-шаблон на рабочем столе (чек_бот.pdf и т.п.)."""
    desktop = DEFAULT_BOT_SAFE_INPUT.parent
    target_size = DEFAULT_BOT_SAFE_INPUT.stat().st_size if DEFAULT_BOT_SAFE_INPUT.is_file() else 58320
    best: Path | None = None
    for candidate in desktop.glob("*.pdf"):
        if candidate.resolve() == DEFAULT_BOT_SQUASH.resolve():
            continue
        if candidate.stat().st_size != target_size:
            continue
        try:
            if BOT_SAFE_FONT_MARKER not in pdf_base_font_name(candidate):
                continue
            cmap = load_unicode_to_cid(candidate)
            if not has_full_cyrillic_charset(cmap):
                continue
            try:
                validate_bot_critical_cids(candidate)
            except AmountPatchError:
                continue
            import pypdf
            from io import BytesIO
            from fontTools.ttLib import TTFont

            ff = (
                pypdf.PdfReader(str(candidate))
                .pages[0]["/Resources"]["/Font"]["/F1"]["/DescendantFonts"][0]
                ["/FontDescriptor"]["/FontFile2"]
                .get_data()
            )
            font = TTFont(BytesIO(ff))
            if any(tag in font for tag in ("fpgm", "prep", "cvt ")):
                continue
            best = candidate
            break
        except Exception:
            continue
    return best


def build_squash_bot_template(
    source: Path | None = None,
    output: Path | None = None,
) -> Path:
    """
    Шаблон pdf 58: полная кириллица, размер как оригинал (~58320), hinting снят.
    Лучший компромисс для onlypdf_robot + «Ульянов» и любых ФИО.
    """
    src = source or DEFAULT_BOT_SAFE_INPUT
    dst = output or DEFAULT_BOT_SQUASH
    if not src.is_file():
        raise AmountPatchError(f"Исходный шаблон не найден: {src}")
    if BOT_SAFE_FONT_MARKER not in pdf_base_font_name(src):
        raise AmountPatchError(
            f"Шаблон должен быть pdf 58 ({BOT_SAFE_FONT_MARKER}+Tahoma), а не {src.name}"
        )
    goal = src.stat().st_size
    legacy = _find_legacy_squash_template()
    if legacy is not None:
        import shutil

        shutil.copy2(legacy, dst)
    else:
        from font_extend import ensure_squash_bot_charset

        ensure_squash_bot_charset(src, dst, target_size=goal)
    cmap = load_unicode_to_cid(dst)
    if not has_full_cyrillic_charset(cmap):
        raise AmountPatchError("Squash-шаблон собран, но кириллица неполная")
    validate_bot_critical_cids(dst)
    if dst.stat().st_size != goal:
        raise AmountPatchError(
            f"Squash-шаблон {dst.stat().st_size} байт вместо {goal}"
        )
    return dst


def validate_bot_squash_patch(
    pdf_path: str | Path, field_values: dict[str, Any]
) -> None:
    """Проверяет, что squash-шаблон покрывает все символы патча."""
    src = Path(pdf_path)
    discovered = discover_fields(src)
    cmap = load_unicode_to_cid(src)
    if not has_full_cyrillic_charset(cmap):
        raise AmountPatchError(
            f"Шаблон {src.name} без полной кириллицы.\n"
            "Соберите: python patch_alfa_amount.py --build-squash-template"
        )
    problems: list[str] = []
    for field_id, value in field_values.items():
        if field_id not in discovered:
            continue
        text = format_field_value(field_id, value, discovered[field_id].text)
        missing = sorted(
            {ch for ch in text if ch not in cmap and not ch.isspace()},
            key=ord,
        )
        if missing:
            label = FIELD_LABELS.get(field_id, field_id)
            shown = ", ".join(repr(ch) for ch in missing)
            problems.append(f"  • {label} ({field_id}): {shown}")
    if problems:
        raise AmountPatchError(
            "Режим --bot-squash: символы отсутствуют в шаблоне:\n"
            + "\n".join(problems)
        )
    if BOT_SAFE_FONT_MARKER not in pdf_base_font_name(src):
        raise AmountPatchError(
            f"Режим --bot-squash: нужен шаблон pdf 58 ({BOT_SAFE_FONT_MARKER}+Tahoma)."
        )
    validate_bot_critical_cids(src)


def resolve_bot_safe_input(explicit: Path) -> Path:
    """
  Для onlypdf_robot / pdf_receipt_checker оставляет исходный шаблон (pdf 58 ≈ 58320 байт).

  fullfont-шаблоны (~60–73 КБ) ломают распознавание: бот сверяет размер и subset шрифта.
  """
    return explicit


def build_fullfont_template(
    source: Path | None = None,
    output: Path | None = None,
) -> Path:
    """
    Один раз расширяет шаблон до полного кириллического алфавита (компактно).
    Дальнейшие патчи меняют только текст, не шрифт.
    """
    src = source or DEFAULT_INPUT
    dst = output or {
        DEFAULT_INPUT.resolve(): DEFAULT_ORIGINAL_FULLFONT,
        DEFAULT_BOT_SAFE_INPUT.resolve(): DEFAULT_BOT_SAFE_FULLFONT,
    }.get(src.resolve(), src.with_name(f"{src.stem}_fullfont{src.suffix}"))
    if not src.is_file():
        raise AmountPatchError(f"Исходный шаблон не найден: {src}")
    from font_extend import ensure_full_receipt_charset

    ensure_full_receipt_charset(src, dst, target_size=src.stat().st_size)
    if dst.stat().st_size > MAX_PDF_BYTES:
        raise AmountPatchError(
            f"Шаблон {dst.name} ({dst.stat().st_size} байт) превышает лимит "
            f"{MAX_PDF_BYTES} байт (~60 КБ)."
        )
    cmap = load_unicode_to_cid(dst)
    if not has_full_receipt_charset(cmap):
        raise AmountPatchError(
            "Шаблон собран, но в /ToUnicode не хватает букв (кириллица или латиница)"
        )
    return dst


def build_bot_safe_template(
    source: Path | None = None,
    output: Path | None = None,
) -> Path:
    """Собирает fullfont-шаблон из pdf 58 (совместимость с --bot-safe)."""
    src = source or DEFAULT_BOT_SAFE_INPUT
    dst = output or DEFAULT_BOT_SAFE_FULLFONT
    if not src.is_file():
        raise AmountPatchError(f"Исходный шаблон не найден: {src}")
    if BOT_SAFE_FONT_MARKER not in pdf_base_font_name(src):
        raise AmountPatchError(
            f"Шаблон должен быть pdf 58 ({BOT_SAFE_FONT_MARKER}+Tahoma), а не {src.name}"
        )
    return build_fullfont_template(src, dst)


def pdf_base_font_name(pdf_path: str | Path) -> str:
    """Возвращает /BaseFont шрифта F1, напр. /UHQZMV+Tahoma."""
    import pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    return str(reader.pages[0]["/Resources"]["/Font"]["/F1"]["/BaseFont"])


def bot_safe_charset_report(unicode_to_cid: dict[str, str]) -> str:
    """Кириллица, доступная в subset pdf 58 без расширения шрифта."""
    upper = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    lower = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
    avail_up = "".join(c for c in upper if c in unicode_to_cid)
    avail_lo = "".join(c for c in lower if c in unicode_to_cid)
    return f"ЗАГЛ: {avail_up or '—'}; строчные: {avail_lo or '—'}"


def validate_bot_safe_patch(
    pdf_path: str | Path, field_values: dict[str, Any]
) -> None:
    """
    Проверяет, что патч можно сделать без расширения subset-шрифта.
    Иначе бот помечает чек как «вероятная подделка».
    """
    src = Path(pdf_path)
    discovered = discover_fields(src)
    cmap = load_unicode_to_cid(src)
    needed: set[str] = set()
    field_problems: list[str] = []
    for field_id, value in field_values.items():
        if field_id not in discovered:
            continue
        text = format_field_value(field_id, value, discovered[field_id].text)
        needed.update(text)
        missing_here = sorted(
            {ch for ch in text if ch not in cmap and not ch.isspace()},
            key=ord,
        )
        if missing_here:
            label = FIELD_LABELS.get(field_id, field_id)
            shown = ", ".join(repr(ch) for ch in missing_here)
            field_problems.append(f"  • {label} ({field_id}): {shown} в {text!r}")
    if has_full_cyrillic_charset(cmap):
        return

    missing = chars_needing_font_extension(needed, cmap)
    if missing:
        shown = ", ".join(repr(ch) for ch in sorted(missing, key=ord))
        details = "\n".join(field_problems) if field_problems else ""
        raise AmountPatchError(
            f"Режим --bot-safe: в subset нет символов: {shown}.\n"
            f"{details}\n"
            f"{bot_safe_charset_report(cmap)}\n"
            "Для onlypdf_robot нельзя расширять шрифт (FontFile2 должен остаться 13409 байт).\n"
            "Варианты:\n"
            "  • замените буквы на доступные (см. --show-charset), напр. «ульянов» вместо «Ульянов»\n"
            "  • или патчьте только сумму/телефон, не меняя ФИО\n"
            "  • patch_pdf58_botsafe.json — пример для бота"
        )
    base_font = pdf_base_font_name(src)
    if BOT_SAFE_FONT_MARKER not in base_font:
        raise AmountPatchError(
            f"Режим --bot-safe: нужен шаблон pdf 58 ({BOT_SAFE_FONT_MARKER}+Tahoma), "
            f"а в файле {base_font}.\n"
            f"Патчьте {DEFAULT_BOT_SAFE_INPUT}, не original.pdf."
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _collect_field_args(args: argparse.Namespace) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if args.amount is not None:
        values["amount"] = args.amount
    for field_id in FIELD_ANCHORS:
        if field_id == "amount":
            continue
        val = getattr(args, field_id, None)
        if val is not None:
            values[field_id] = val
    return values


def main() -> int:
    if len(sys.argv) == 1:
        print(
            "patch_alfa_amount.py — правка полей PDF-чека Альфа-Банка (in-place)\n"
            "\n"
            "Синтаксис:\n"
            "  python patch_alfa_amount.py <файл.pdf> <сумма> [опции полей]\n"
            "  python patch_alfa_amount.py <файл.pdf> --list-fields\n"
            "\n"
            "Примеры:\n"
            r'  python patch_alfa_amount.py "original.pdf" 5294'
            "\n"
            '  python patch_alfa_amount.py original.pdf 5294 --commission 0\n'
            '  python patch_alfa_amount.py original.pdf --phone "+7 (916) 685-44-81"\n'
            "\n"
            "Список полей:  python patch_alfa_amount.py файл.pdf --list-fields\n"
        )
        return 0

    parser = argparse.ArgumentParser(
        description="In-place замена полей PDF-чека Альфа-Банка (сумма, комиссия, телефон и др.)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python patch_alfa_amount.py receipt.pdf 5294
  python patch_alfa_amount.py receipt.pdf 5294 --commission 0 -o out.pdf
  python patch_alfa_amount.py receipt.pdf --list-fields
  python patch_alfa_amount.py receipt.pdf --fields-json patch.json

Денежные поля (amount, commission) — целое число в рублях.
Остальные поля — строка той же длины, что в оригинале (см. --list-fields).
        """,
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Исходный PDF (по умолчанию: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "amount",
        nargs="?",
        type=int,
        default=None,
        help="Новая сумма перевода в рублях",
    )
    parser.add_argument("-o", "--output", type=Path, help="Выходной PDF")
    parser.add_argument("--no-verify", action="store_true", help="Не запускать qpdf --check")
    parser.add_argument("--dry-run", action="store_true", help="Показать замены без записи")
    parser.add_argument(
        "--list-fields",
        action="store_true",
        help="Показать все поля чека и текущие значения",
    )
    parser.add_argument(
        "--show-charset",
        action="store_true",
        help="Показать буквы/цифры, которые можно записать in-place",
    )
    parser.add_argument(
        "--extend-font",
        action="store_true",
        help="С --show-charset: показать полный набор после расширения из Tahoma",
    )
    parser.add_argument(
        "--no-extend-font",
        action="store_true",
        help="Не добавлять недостающие буквы из Tahoma (только встроенный subset)",
    )
    parser.add_argument(
        "--no-fullfont",
        action="store_true",
        help=(
            "Не подставлять original_fullfont.pdf / pdf58_fullfont.pdf "
            "(иначе чек ~60 КБ и бот может не распознать; нужен --extend-font на лету)"
        ),
    )
    parser.add_argument(
        "--bot-pass",
        action="store_true",
        help=(
            "onlypdf_robot: шаблон test_patch.pdf / lauchj.pdf (~73 КБ, hinting, "
            "У→CID 008A). Рекомендуется вместо --bot-squash."
        ),
    )
    parser.add_argument(
        "--build-bot-pass-template",
        action="store_true",
        help="Скопировать test_patch.pdf → pdf58_bot_pass.pdf на рабочий стол",
    )
    parser.add_argument(
        "--bot-squash",
        action="store_true",
        help=(
            "УСТАРЕЛО: squash ~58320 байт — бот часто пишет «чек не распознан». "
            "Используйте --bot-pass."
        ),
    )
    parser.add_argument(
        "--build-squash-template",
        action="store_true",
        help=(
            "Собрать pdf58_squash.pdf: полная кириллица, размер как pdf 58, для --bot-squash"
        ),
    )
    parser.add_argument(
        "--bot-safe",
        action="store_true",
        help=(
            "Режим для onlypdf_robot: патч pdf 58.pdf без расширения шрифта, "
            "размер ~58320 байт (см. patch_pdf58.json)"
        ),
    )
    parser.add_argument(
        "--build-template",
        action="store_true",
        help=(
            "Один раз собрать original_fullfont.pdf и pdf58_fullfont.pdf "
            "(полная кириллица, компактно, ~64 КБ вместо ~58 КБ у pdf 58)"
        ),
    )
    parser.add_argument(
        "--fields-json",
        type=Path,
        help="JSON-файл с полями: {\"amount\": 5294, \"commission\": 0, ...}",
    )

    for field_id, label in FIELD_LABELS.items():
        if field_id == "amount":
            continue
        arg = f"--{field_id.replace('_', '-')}"
        kw: dict[str, Any] = {"dest": field_id, "help": f"Новое значение: {label}"}
        if field_id in MONEY_FIELDS:
            kw["type"] = int
        else:
            kw["type"] = str
        parser.add_argument(arg, **kw)

    args = parser.parse_args()

    try:
        if args.list_fields:
            list_fields_report(args.input)
            return 0

        if args.show_charset:
            show_charset_report(args.input, extended=args.extend_font)
            return 0

        if args.build_squash_template:
            dst = build_squash_bot_template()
            cmap = load_unicode_to_cid(dst)
            print(f"Squash-шаблон: {dst}")
            print(f"  шрифт: {pdf_base_font_name(dst)}")
            print(f"  размер: {dst.stat().st_size} байт (как pdf 58)")
            from font_extend import FULL_CYRILLIC, full_template_charset

            target = full_template_charset(cmap)
            have = sum(1 for ch in target if ch in cmap)
            print(
                f"  кириллица: {sum(c in cmap for c in FULL_CYRILLIC)} / "
                f"{len(FULL_CYRILLIC)}; символов шаблона: {have} / {len(target)}"
            )
            print(
                "\nПатч (полная кириллица + бот):\n"
                f'  python patch_alfa_amount.py "{DEFAULT_BOT_SAFE_INPUT}" '
                f"--bot-pass --fields-json patch_pdf58.json -o out.pdf"
            )
            return 0

        if args.build_bot_pass_template:
            dst = build_bot_pass_template()
            print(f"Bot-pass шаблон: {dst}")
            print(f"  шрифт: {pdf_base_font_name(dst)}")
            print(f"  размер: {dst.stat().st_size} байт")
            print(
                "\nПатч для бота:\n"
                f'  python patch_alfa_amount.py "{DEFAULT_BOT_SAFE_INPUT}" '
                f"--bot-pass --fields-json patch_pdf58.json -o out.pdf"
            )
            return 0

        if args.build_template:
            built: list[Path] = []
            for src in (DEFAULT_INPUT, DEFAULT_BOT_SAFE_INPUT):
                if not src.is_file():
                    continue
                if src == DEFAULT_BOT_SAFE_INPUT:
                    built.append(build_bot_safe_template(src))
                else:
                    built.append(build_fullfont_template(src))
            if not built:
                raise AmountPatchError(
                    f"Не найден ни {DEFAULT_INPUT.name}, ни {DEFAULT_BOT_SAFE_INPUT.name}"
                )
            for dst in built:
                cmap = load_unicode_to_cid(dst)
                print(f"Шаблон готов: {dst}")
                print(f"  шрифт: {pdf_base_font_name(dst)}")
                print(f"  размер: {dst.stat().st_size} байт (лимит {MAX_PDF_BYTES})")
                from font_extend import FULL_CYRILLIC, full_template_charset

                target = full_template_charset(cmap)
                have = sum(1 for ch in target if ch in cmap)
                print(
                    f"  кириллица: {sum(c in cmap for c in FULL_CYRILLIC)} / "
                    f"{len(FULL_CYRILLIC)}; всего символов шаблона: {have} / {len(target)}"
                )
                print(f"  символов в CMap: {len(cmap)}\n")
            print(
                "Дальше собирайте чеки (любой текст, до ~60 КБ):\n"
                "  python patch_alfa_amount.py -o чек.pdf ...\n"
                "  python patch_alfa_amount.py --bot-safe -o чек.pdf ..."
            )
            return 0

        if sum(1 for f in (args.bot_pass, args.bot_squash, args.bot_safe) if f) > 1:
            raise AmountPatchError("--bot-pass, --bot-squash и --bot-safe — только один режим")

        extend_font = not (
            args.no_extend_font or args.bot_safe or args.bot_squash or args.bot_pass
        )

        if args.bot_pass:
            args.input = resolve_bot_pass_input(args.input)
        elif args.bot_squash:
            args.input = resolve_bot_squash_input(args.input)
        elif args.bot_safe:
            args.input = resolve_bot_safe_input(args.input)
        elif (
            extend_font
            and not args.no_fullfont
            and args.input.resolve()
            in (DEFAULT_INPUT.resolve(), DEFAULT_BOT_SAFE_INPUT.resolve())
        ):
            args.input = resolve_fullfont_input(args.input)

        field_values = _collect_field_args(args)
        if args.fields_json:
            if not args.fields_json.is_file():
                raise AmountPatchError(f"JSON не найден: {args.fields_json}")
            from_json = json.loads(args.fields_json.read_text(encoding="utf-8"))
            if not isinstance(from_json, dict):
                raise AmountPatchError("JSON должен быть объектом {поле: значение}")
            field_values.update(from_json)

        if args.bot_safe and not field_values:
            default_json = Path(__file__).with_name("patch_pdf58.json")
            if not default_json.is_file():
                raise AmountPatchError("patch_pdf58.json не найден рядом со скриптом")
            field_values = json.loads(default_json.read_text(encoding="utf-8"))

        if not field_values:
            raise AmountPatchError(
                "Укажите поля для замены (сумма, --commission, --phone, ...)\n"
                "или --list-fields для просмотра доступных полей."
            )

        if args.bot_pass:
            validate_bot_squash_patch(args.input, field_values)
        elif args.bot_squash:
            validate_bot_squash_patch(args.input, field_values)
        elif args.bot_safe:
            validate_bot_safe_patch(args.input, field_values)

        discovered = discover_fields(args.input)
        if not discovered and "amount" in field_values and len(field_values) == 1:
            data = args.input.read_bytes()
            match = find_best_amount_match(data, args.input)
            new_text = format_amount_like(field_values["amount"], match.text)
            replacement = build_replacement_bytes(match, field_values["amount"])
            print(f"Поле amount (UTF-16BE):")
            print(f"  было:  {_display_text(match.text)!r}")
            print(f"  станет: {_display_text(new_text)!r}")
            if args.dry_run:
                print("dry-run: файл не записан")
                return 0
            info = replace_amount_in_pdf(
                args.input,
                field_values["amount"],
                args.output,
                verify=not args.no_verify,
            )
            print(f"\nГотово: {info['output']}")
            return 0

        print("Замены:")
        preview_data = bytearray(args.input.read_bytes())
        needed_chars: set[str] = set()
        prepared_preview: list[tuple[str, FieldMatch, str]] = []
        for field_id, value in field_values.items():
            if field_id not in discovered:
                continue
            fm = discovered[field_id]
            new_text = format_field_value(field_id, value, fm.text)
            needed_chars.update(new_text)
            prepared_preview.append((field_id, fm, new_text))

        cmap, font_extended, added_chars = _ensure_needed_chars(
            preview_data, args.input, needed_chars, extend_font=extend_font
        )
        if font_extended:
            print(
                f"\nШрифт расширен: добавлено {len(added_chars)} символов из Tahoma"
            )

        for field_id, fm, new_text in prepared_preview:
            new_raw = encode_cid_text(new_text, cmap)
            label = FIELD_LABELS.get(field_id, field_id)
            print(f"\n  [{field_id}] {label}")
            print(f"    было:  {_display_text(fm.text)!r}")
            print(f"    станет: {_display_text(new_text)!r}")
            print(f"    hex: {fm.raw.decode('ascii')} -> {new_raw.decode('ascii')}")

        if args.dry_run:
            print("\ndry-run: файл не записан")
            return 0

        info = replace_fields_in_pdf(
            args.input,
            field_values,
            args.output,
            verify=not args.no_verify,
            extend_font=extend_font,
        )
        mode = info["patch_mode"]
        extra = ""
        if info.get("font_extended"):
            extra = f", шрифт +{len(info.get('font_chars_added', []))} символов"
        if info.get("font_swapped"):
            extra += ", компактный FontFile2"
        print(
            f"\nГотово: {info['output']} (режим: {mode}{extra}, "
            f"{Path(info['output']).stat().st_size} байт)"
        )
        return 0

    except AmountPatchError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
