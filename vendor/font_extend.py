#!/usr/bin/env python3
"""Расширение subset-шрифта PDF глифами из Tahoma (полный кириллический алфавит)."""

from __future__ import annotations

import os
import re
import zlib
from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from patch_alfa_amount import (
    STREAM_RE,
    TJ_AT_POS_RE,
    _classify_field,
    _fix_xref_offsets,
    _parse_cmap_bfchar,
    chars_needing_font_extension,
    decode_cid_hex,
    recompress_to_size,
    AmountPatchError,
)

_MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_TAHOMA = Path(r"C:\Windows\Fonts\tahoma.ttf")

# Полный набор для чеков: кириллица, цифры, знаки, NBSP, базовая латиница.
FULL_RECEIPT_CHARSET = (
    "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789+-().: "
    "\xa0"
)
FULL_CYRILLIC = (
    "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
)
# Минимальная латиница для sbp_ref в pdf 58 (subset без A/G/M).
SBP_LATIN_EXTRA = "AGM"


def full_template_charset(unicode_to_cid: dict[str, str]) -> set[str]:
    """Полная кириллица + латиница из исходного subset + AGM для СБП-ref."""
    chars = set(FULL_CYRILLIC) | set(SBP_LATIN_EXTRA)
    for ch in FULL_RECEIPT_CHARSET:
        if ch in unicode_to_cid and ("A" <= ch <= "Z" or "a" <= ch <= "z"):
            chars.add(ch)
    return chars
# pdf 58: слоты, которые можно перезаписать (не в статике страницы).
PDF58_RELOCATABLE = "BYАВГТжхы?"
PDF58_SACRIFICE = "BY?"
# Не удаляем fpgm/prep/cvt — без них subset рендерится «сплющенным» на 11–12 pt.
# Для pdf58_squash (бот + полная кириллица) hinting снимается отдельно — см. HINT_TABLES.
HINT_TABLES = ("fpgm", "prep", "cvt ", "gasp")
_FONT_STRIP_TABLES = (
    "GPOS",
    "GSUB",
    "hdmx",
    "VDMX",
    "LTSH",
    "kern",
    "vhea",
    "vmtx",
)


class FontExtendError(AmountPatchError):
    pass


def _tahoma_search_paths() -> list[Path]:
    """Кандидаты для системного Tahoma (Windows, WSL, Linux, vendor/fonts)."""
    candidates: list[Path] = []

    for env_name in ("TAHOMA_TTF", "PDF_CHECKER_TAHOMA"):
        env_path = os.getenv(env_name, "").strip()
        if env_path:
            candidates.append(Path(env_path).expanduser())

    candidates.extend(
        (
            _MODULE_DIR / "fonts" / "tahoma.ttf",
            _MODULE_DIR.parent / "fonts" / "tahoma.ttf",
        )
    )

    windir = os.getenv("WINDIR", r"C:\Windows")
    candidates.extend(
        (
            Path(windir) / "Fonts" / "tahoma.ttf",
            Path(r"C:\Windows\Fonts\tahoma.ttf"),
            Path.home() / "AppData/Local/Microsoft/Windows/Fonts/tahoma.ttf",
            Path("/mnt/c/Windows/Fonts/tahoma.ttf"),
        )
    )

    candidates.extend(
        (
            Path("/usr/share/fonts/truetype/msttcorefonts/tahoma.ttf"),
            Path("/usr/share/fonts/truetype/microsoft-fonts/tahoma.ttf"),
            Path("/usr/share/fonts/TTF/tahoma.ttf"),
            Path("/usr/local/share/fonts/tahoma.ttf"),
        )
    )

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        key = path.as_posix().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def resolve_tahoma_path(explicit: Path | None = None) -> Path:
    """Возвращает первый доступный tahoma.ttf или бросает FontExtendError."""
    if explicit is not None:
        path = Path(explicit).expanduser()
        if path.is_file():
            return path.resolve()
        raise FontExtendError(f"Tahoma не найден: {path}")

    for path in _tahoma_search_paths():
        if path.is_file():
            return path.resolve()

    checked = "\n".join(f"  • {p}" for p in _tahoma_search_paths())
    fonts_dir = _MODULE_DIR / "fonts"
    raise FontExtendError(
        "Tahoma не найден. Скопируйте tahoma.ttf из C:\\Windows\\Fonts "
        f"в {fonts_dir} или задайте TAHOMA_TTF в .env.\n"
        f"Проверенные пути:\n{checked}"
    )


@dataclass(frozen=True)
class FontExtendResult:
    extended: bool
    added_chars: tuple[str, ...]
    cmap: dict[str, str]


def _require_pypdf():
    try:
        import pypdf  # noqa: F401
    except ImportError as exc:
        raise FontExtendError("Нужен pypdf: pip install pypdf") from exc


def _extract_font_parts(pdf_path: Path) -> dict:
    import pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    font = reader.pages[0]["/Resources"]["/Font"]["/F1"]
    desc = font["/DescendantFonts"][0].get_object()
    fd = desc["/FontDescriptor"]
    ff_dec = fd["/FontFile2"].get_data()
    tu_obj = font["/ToUnicode"]
    tu_raw = (
        tu_obj.get_data()
        if hasattr(tu_obj, "get_data")
        else tu_obj.get_object().get_data()
    )
    try:
        tu_dec = zlib.decompress(tu_raw)
        tu_compressed = True
    except zlib.error:
        tu_dec = tu_raw
        tu_compressed = False

    w_list = list(desc.get("/W") or [])
    return {
        "font_dec": ff_dec,
        "tu_dec": tu_dec,
        "tu_compressed": tu_compressed,
        "w_list": w_list,
        "unicode_to_cid": _parse_cmap_bfchar(tu_dec),
    }


@dataclass(frozen=True)
class _StreamSpan:
    header_start: int
    content_start: int
    content_end: int
    raw: bytes


def _find_stream_span(data: bytes, target_dec: bytes) -> _StreamSpan | None:
    for m in STREAM_RE.finditer(data):
        raw = m.group(2)
        try:
            dec = zlib.decompress(raw)
        except zlib.error:
            dec = raw
        if dec == target_dec:
            return _StreamSpan(m.start(), m.start(2), m.end(2), raw)
    return None


def _find_cmap_stream_bytes(data: bytes) -> bytes | None:
    marker = b"beginbfchar"
    pos = data.find(marker)
    if pos < 0:
        return None
    start = data.rfind(b"stream\r\n", 0, pos)
    if start < 0:
        start = data.rfind(b"stream\n", 0, pos)
    if start < 0:
        return None
    start = data.find(b"\n", start) + 1
    end = data.find(b"\r\nendstream", pos)
    if end < 0:
        end = data.find(b"\nendstream", pos)
    if end < 0:
        return None
    return data[start:end]


def _find_tounicode_object_span(data: bytes) -> tuple[int, int, int] | None:
    m = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", data)
    if not m:
        return None
    obj_num = int(m.group(1))
    obj_re = re.compile(
        rf"{obj_num} 0 obj\s*<<.*?>>\s*stream\r?\n".encode() + rb".*?"
        + rb"\r?\nendstream\r?\nendobj",
        re.S,
    )
    om = obj_re.search(data)
    if not om:
        return None
    inner = om.group(0)
    sm = re.search(rb"stream\r?\n", inner)
    em = re.search(rb"\r?\nendstream", inner)
    if not sm or not em:
        return None
    content_start = om.start() + sm.end()
    content_end = om.start() + em.start()
    return om.start(), content_start, content_end


def _tounicode_uses_flate(data: bytes, header_start: int) -> bool:
    head = data[header_start : header_start + 400]
    return bool(re.search(rb"/Filter\s*/FlateDecode", head))


def _update_length_before_stream(data: bytearray, content_start: int, new_len: int) -> None:
    window = data[max(0, content_start - 400) : content_start]
    matches = list(re.finditer(rb"/Length\s+(\d+)", window))
    if not matches:
        raise FontExtendError("/Length не найден перед ToUnicode stream")
    m = matches[-1]
    base = max(0, content_start - 400)
    s, e = base + m.start(1), base + m.end(1)
    old = data[s:e].decode()
    repl = str(new_len).encode()
    if len(repl) != len(old):
        raise FontExtendError(f"Ширина /Length изменилась: {old!r} -> {new_len}")
    data[s:e] = repl


def repair_tounicode_in_bytes(data: bytearray) -> bool:
    """Restore /ToUnicode CMap when stream body was corrupted during font extend."""
    cmap_plain = _find_cmap_stream_bytes(bytes(data))
    if not cmap_plain:
        return False
    cmap_plain = _dedupe_cmap_bfchar(cmap_plain)
    span = _find_tounicode_object_span(bytes(data))
    if not span:
        return False

    header_start, content_start, content_end = span
    use_flate = _tounicode_uses_flate(bytes(data), header_start)
    new_content = zlib.compress(cmap_plain, 9) if use_flate else cmap_plain

    len_window_start = max(0, content_start - 400)
    len_matches = list(re.finditer(rb"/Length\s+(\d+)", data[len_window_start:content_start]))
    if not len_matches:
        raise FontExtendError("/Length не найден перед ToUnicode stream")
    len_m = len_matches[-1]
    len_token_start = len_window_start + len_m.start()
    len_token_end = len_window_start + len_m.end()
    new_len_token = f"/Length {len(new_content)}".encode("ascii")
    len_delta = len(new_len_token) - (len_token_end - len_token_start)

    pivot = min(len_token_start, content_start)
    if len_delta:
        data[len_token_start:len_token_end] = new_len_token
        _fix_xref_offsets(data, pivot, len_delta)
        content_start += len_delta
        content_end += len_delta

    old_size = content_end - content_start
    content_delta = len(new_content) - old_size
    data[content_start:content_end] = new_content
    if content_delta:
        _fix_xref_offsets(data, content_start, content_delta)
    return True


def _load_unicode_to_cid_from_bytes(data: bytes) -> dict[str, str]:
    import pypdf
    from io import BytesIO

    reader = pypdf.PdfReader(BytesIO(data))
    tu_raw = reader.pages[0]["/Resources"]["/Font"]["/F1"]["/ToUnicode"].get_data()
    if not tu_raw:
        raise FontExtendError("ToUnicode stream пуст")
    mapping = _parse_cmap_bfchar(tu_raw)
    if not mapping:
        raise FontExtendError("ToUnicode CMap пуст или не распознан")
    return mapping


def _stream_is_flate(span: _StreamSpan | None) -> bool:
    """True if stream bytes in the PDF file are zlib/Flate compressed."""
    if span is None:
        return False
    try:
        zlib.decompress(span.raw)
        return True
    except zlib.error:
        return False


def _compress_like_pdf(payload: bytes) -> bytes:
    best = zlib.compress(payload, 9)
    for level in range(10):
        candidate = zlib.compress(payload, level)
        if len(candidate) < len(best):
            best = candidate
    return best


def _format_w_array(w_list: list) -> bytes:
    parts: list[str] = []
    i = 0
    while i < len(w_list):
        cid = w_list[i]
        width = w_list[i + 1][0]
        parts.append(f" {cid}[{width}]")
        i += 2
    body = "".join(parts)
    if body.startswith(" "):
        body = body[1:]
    return f"/W [{body}]".encode("ascii")


def _parse_w_span(data: bytes) -> tuple[int, int]:
    m = re.search(rb"/W\s*\[", data)
    if not m:
        raise FontExtendError("/W массив не найден в PDF")
    start = m.start()
    depth = 0
    pos = m.end() - 1
    while pos < len(data):
        ch = data[pos : pos + 1]
        if ch == b"[":
            depth += 1
        elif ch == b"]":
            depth -= 1
            if depth == 0:
                return start, pos + 1
        pos += 1
    raise FontExtendError("Закрывающая ] для /W не найдена")


def _extend_cmap_bytes(cmap_dec: bytes, additions: list[tuple[int, int]]) -> bytes:
    if not additions:
        return cmap_dec
    text = cmap_dec.decode("latin-1")
    count_m = re.search(r"(\d+)\s+beginbfchar", text)
    if not count_m:
        raise FontExtendError("beginbfchar не найден в ToUnicode")
    old_count = int(count_m.group(1))
    insert = "".join(f"<{cid:04X}> <{cp:04X}>\n" for cid, cp in additions)
    text = re.sub(
        rf"{old_count}\s+beginbfchar",
        f"{old_count + len(additions)} beginbfchar",
        text,
        count=1,
    )
    text = re.sub(
        r"(\r?\n)endbfchar",
        lambda m: f"{m.group(1)}{insert}endbfchar",
        text,
        count=1,
    )
    return text.encode("latin-1")


def _dedupe_cmap_bfchar(cmap_dec: bytes) -> bytes:
    """Убирает повторяющиеся CID в bfchar (оставляет первое вхождение слота)."""
    text = cmap_dec.decode("latin-1")
    count_m = re.search(r"(\d+)\s+beginbfchar", text)
    if not count_m:
        return cmap_dec
    seen_cids: set[str] = set()
    entries: list[str] = []
    for m in re.finditer(r"<([0-9A-Fa-f]{4})>\s*<([0-9A-Fa-f]{4})>", text):
        cid = m.group(1).upper()
        if cid in seen_cids:
            continue
        seen_cids.add(cid)
        entries.append(f"<{cid}> <{m.group(2).upper()}>\n")
    if len(entries) == int(count_m.group(1)):
        return cmap_dec
    body = "".join(entries)
    text = re.sub(
        rf"{count_m.group(1)}\s+beginbfchar\r?\n.*?endbfchar",
        f"{len(entries)} beginbfchar\n{body}endbfchar",
        text,
        count=1,
        flags=re.S,
    )
    return text.encode("latin-1")


def _rebuild_cmap_bfchar(cmap_dec: bytes, unicode_to_cid: dict[str, str]) -> bytes:
    """Пересобирает bfchar из итоговой карты символ→CID (без дублей слотов)."""
    text = cmap_dec.decode("latin-1")
    count_m = re.search(r"(\d+)\s+beginbfchar", text)
    if not count_m:
        raise FontExtendError("beginbfchar не найден в ToUnicode")

    cid_to_char: dict[str, str] = {}
    for ch, cid_hex in unicode_to_cid.items():
        cid = cid_hex.upper()
        prev = cid_to_char.get(cid)
        if prev is not None and prev != ch:
            raise FontExtendError(
                f"CID {cid} одновременно для {prev!r} и {ch!r} — карта несогласована"
            )
        cid_to_char[cid] = ch

    body = "".join(
        f"<{cid}> <{ord(ch):04X}>\n"
        for cid, ch in sorted(cid_to_char.items(), key=lambda item: int(item[0], 16))
    )
    text = re.sub(
        rf"{count_m.group(1)}\s+beginbfchar\r?\n.*?endbfchar",
        f"{len(cid_to_char)} beginbfchar\n{body}endbfchar",
        text,
        count=1,
        flags=re.S,
    )
    return text.encode("latin-1")


def _flatten_glyph_outline(src: TTFont, glyph_name: str):
    """
    Контур глифа без TrueType-hinting.

    Composite-глифы (заглавная «В»/«Т» в Tahoma) разворачиваются в simple;
    иначе в subset с чужим fpgm/prep текст на 11–12 pt рендерится «сплющенным».
    """
    glyph_set = src.getGlyphSet()
    pen = TTGlyphPen(glyph_set)

    class _DecomposePen:
        """Раскрывает composite в контуры, не оставляя ссылок на латиницу."""

        __slots__ = ("_glyph_set", "_pen")

        def __init__(self, glyph_set, target_pen):
            self._glyph_set = glyph_set
            self._pen = target_pen

        def moveTo(self, pt):
            self._pen.moveTo(pt)

        def lineTo(self, pt):
            self._pen.lineTo(pt)

        def curveTo(self, *pts):
            self._pen.curveTo(*pts)

        def qCurveTo(self, *pts):
            self._pen.qCurveTo(*pts)

        def closePath(self):
            self._pen.closePath()

        def endPath(self):
            self._pen.endPath()

        def addComponent(self, component_glyph_name, transformation):
            component = TransformPen(self._pen, transformation)
            self._glyph_set[component_glyph_name].draw(component)

    glyph_set[glyph_name].draw(_DecomposePen(glyph_set, pen))
    return pen.glyph()


def _import_glyph(
    dst: TTFont,
    src: TTFont,
    src_glyph_name: str,
    name_map: dict[str, str],
) -> str:
    if src_glyph_name in name_map:
        return name_map[src_glyph_name]

    new_gid = dst["maxp"].numGlyphs
    new_name = f"glyph{new_gid:05d}"
    dst.setGlyphOrder(dst.getGlyphOrder() + [new_name])
    name_map[src_glyph_name] = new_name
    dst["glyf"][new_name] = _flatten_glyph_outline(src, src_glyph_name)

    aw, lsb = src["hmtx"][src_glyph_name]
    dst["hmtx"].metrics[new_name] = (aw, lsb)
    dst["maxp"].numGlyphs += 1
    return new_name


def _copy_glyph(dst: TTFont, src: TTFont, src_glyph_name: str) -> tuple[int, int]:
    """Копирует глиф из Tahoma в subset, включая composite-зависимости."""
    name_map = {old: old for old in dst.getGlyphOrder()}
    new_name = _import_glyph(dst, src, src_glyph_name, name_map)
    new_gid = dst.getGlyphOrder().index(new_name)
    aw, _ = dst["hmtx"][new_name]
    return new_gid, int(aw)


def _subset_width_scale(dst_font: TTFont, w_list: list) -> float:
    """
    Коэффициент перевода hmtx advance width → /W для subset-шрифта чека.
    В существующих глифах /W примерно вдвое меньше hmtx (масштаб ~0.49).
    """
    order = dst_font.getGlyphOrder()
    samples: list[float] = []
    i = 0
    while i + 1 < len(w_list):
        cid = w_list[i]
        widths = w_list[i + 1]
        if isinstance(cid, int) and isinstance(widths, list) and widths:
            pdf_w = int(widths[0])
            if 0 <= cid < len(order):
                aw, _ = dst_font["hmtx"][order[cid]]
                if aw > 0 and 0 < pdf_w < aw:
                    samples.append(pdf_w / aw)
        i += 2
    if samples:
        return sum(samples) / len(samples)
    return 589 / 1207


def _pdf_glyph_width(dst_font: TTFont, w_list: list, hmtx_width: int) -> int:
    scale = _subset_width_scale(dst_font, w_list)
    return max(1, int(round(hmtx_width * scale)))


def _strip_font_tables(font: TTFont) -> None:
    for tag in _FONT_STRIP_TABLES:
        if tag in font:
            del font[tag]


def _strip_hinting_tables(font: TTFont) -> None:
    for tag in HINT_TABLES:
        if tag in font:
            del font[tag]


def _strip_hinting_in_pdf_bytes(data: bytearray) -> bool:
    """Убирает TrueType-hinting из FontFile2 (компромисс: полная кириллица + размер pdf 58)."""
    import pypdf

    reader = pypdf.PdfReader(BytesIO(bytes(data)))
    ff_dec = (
        reader.pages[0]["/Resources"]["/Font"]["/F1"]["/DescendantFonts"][0]
        ["/FontDescriptor"]["/FontFile2"]
        .get_data()
    )
    font = TTFont(BytesIO(ff_dec))
    if not any(tag in font for tag in HINT_TABLES):
        return False
    _strip_hinting_tables(font)
    out = BytesIO()
    font.save(out, reorderTables=True)
    new_ff = out.getvalue()
    ff_span = _find_stream_span(bytes(data), ff_dec)
    if not ff_span:
        raise FontExtendError("FontFile2 stream не найден при снятии hinting")
    _patch_stream_span(data, ff_span, _compress_like_pdf(new_ff))
    return True


def _page_cids(pdf_path: Path) -> set[str]:
    """Все CID из content stream, включая значения полей чека."""
    data = pdf_path.read_bytes()
    used: set[str] = set()
    for m in STREAM_RE.finditer(data):
        try:
            dec = zlib.decompress(m.group(2))
        except zlib.error:
            continue
        for tm in TJ_AT_POS_RE.finditer(dec):
            hexs = tm.group(3).decode().upper()
            for i in range(0, len(hexs), 4):
                used.add(hexs[i : i + 4])
    return used


def _label_protected_cids(pdf_path: Path) -> set[str]:
    """CID из подписей/шапки — их слоты нельзя перезаписывать при расширении."""
    data = pdf_path.read_bytes()
    protected: set[str] = set()
    for m in STREAM_RE.finditer(data):
        try:
            dec = zlib.decompress(m.group(2))
        except zlib.error:
            continue
        for tm in TJ_AT_POS_RE.finditer(dec):
            x, y = float(tm.group(1)), float(tm.group(2))
            if _classify_field(y, x) is not None:
                continue
            hexs = tm.group(3).decode().upper()
            for i in range(0, len(hexs), 4):
                protected.add(hexs[i : i + 4])
    return protected


def _is_cyrillic_letter(ch: str) -> bool:
    o = ord(ch)
    return (0x0400 <= o <= 0x04FF) or o in (0x0401, 0x0451)


def _auto_sacrifice_chars(pdf_path: Path, unicode_to_cid: dict[str, str]) -> str:
    """
    Кириллица, которая не встречается в подписях — слот можно перезаписать.
    Подписи и общие CID не трогаем, иначе ломается вёрстка шаблона.
    """
    protected = _label_protected_cids(pdf_path)
    out: list[str] = []
    for ch, cid_hex in unicode_to_cid.items():
        if not _is_cyrillic_letter(ch):
            continue
        cid = f"{int(cid_hex, 16):04X}"
        if cid == "0000" or cid in protected:
            continue
        out.append(ch)
    return "".join(out)


def _remap_cids_in_pdf_streams(data: bytearray, remap: dict[str, str]) -> int:
    """Заменяет CID в Tj после переноса глифа в другой слот."""
    if not remap:
        return 0
    file_data = bytes(data)
    pending: list[tuple[_StreamSpan, bytes]] = []
    for m in STREAM_RE.finditer(file_data):
        raw = m.group(2)
        try:
            dec = bytearray(zlib.decompress(raw))
            flate = True
        except zlib.error:
            dec = bytearray(raw)
            flate = False
        changed = False
        for tm in TJ_AT_POS_RE.finditer(dec):
            hexs = tm.group(3).decode().upper()
            new_hex = "".join(
                remap.get(hexs[i : i + 4], hexs[i : i + 4])
                for i in range(0, len(hexs), 4)
            )
            if new_hex != hexs:
                changed = True
                dec[tm.start(3) : tm.end(3)] = new_hex.encode("ascii")
        if not changed:
            continue
        new_raw = _compress_like_pdf(bytes(dec)) if flate else bytes(dec)
        pending.append(
            (_StreamSpan(m.start(), m.start(2), m.end(2), raw), new_raw)
        )

    delta = 0
    for span, new_raw in reversed(pending):
        span = _shift_span(span, delta)
        delta += _patch_stream_span(data, span, new_raw)
    return len(pending)


def _component_glyph_slots(font: TTFont, cid_indices: set[int]) -> set[int]:
    """Глифы-компоненты composite-символов (нельзя перезаписывать in-place)."""
    order = font.getGlyphOrder()
    glyf = font["glyf"]
    protected: set[int] = set()
    for cid in cid_indices:
        if cid <= 0 or cid >= len(order):
            continue
        glyph = glyf[order[cid]]
        if not glyph.isComposite():
            continue
        for comp in glyph.components:
            try:
                protected.add(order.index(comp.glyphName))
            except ValueError:
                pass
    return protected


def _free_glyph_slots(
    unicode_to_cid: dict[str, str],
    glyph_count: int,
    *,
    font: TTFont | None = None,
) -> list[int]:
    """Свободные слоты; 0 (.notdef) и component-глифы не используем для текста."""
    used = {int(cid, 16) for cid in unicode_to_cid.values()}
    protected: set[int] = set()
    if font is not None:
        protected = _component_glyph_slots(font, used)
    return [
        i
        for i in range(1, glyph_count)
        if i not in used and i not in protected
    ]


def _append_glyph_slot(dst: TTFont, glyph, aw: int, lsb: int) -> int:
    """Добавляет слот в конец FontFile2 (для переноса глифа при reloc)."""
    new_gid = len(dst.getGlyphOrder())
    new_name = f"glyph{new_gid:05d}"
    dst.setGlyphOrder(dst.getGlyphOrder() + [new_name])
    dst["glyf"][new_name] = glyph
    dst["hmtx"].metrics[new_name] = (aw, lsb)
    dst["maxp"].numGlyphs = len(dst.getGlyphOrder())
    return new_gid


def _ensure_w_entry(w_list: list, cid: int, width: int) -> None:
    i = 0
    while i < len(w_list):
        if w_list[i] == cid:
            w_list[i + 1] = [width]
            return
        i += 2
    w_list.extend([cid, [width]])


def _overwrite_slot(dst: TTFont, src: TTFont, slot: int, glyph_name: str) -> int:
    if slot == 0:
        raise FontExtendError("Слот 0 (.notdef) нельзя использовать для текста")
    slot_name = dst.getGlyphOrder()[slot]
    dst["glyf"][slot_name] = _flatten_glyph_outline(src, glyph_name)

    aw, lsb = src["hmtx"][glyph_name]
    dst["hmtx"].metrics[slot_name] = (aw, lsb)
    return int(aw)


def _build_extended_font_compact(
    parts: dict,
    chars: set[str],
    tahoma_path: Path,
    *,
    pdf_path: Path,
    relocatable: str = "",
    sacrifice: str | None = None,
) -> tuple[bytes, bytes, list, dict[str, str], list[tuple[int, int]], dict[str, str]]:
    """Расширяет subset in-place: свободные слоты, жертвы, минимальный append."""
    tahoma_path = resolve_tahoma_path(tahoma_path)

    src_font = TTFont(tahoma_path)
    src_cmap = src_font.getBestCmap() or {}
    dst_font = TTFont(BytesIO(parts["font_dec"]))
    unicode_to_cid = dict(parts["unicode_to_cid"])
    template_chars = parts["unicode_to_cid"]
    w_list = list(parts["w_list"])

    missing = sorted(chars_needing_font_extension(chars, unicode_to_cid), key=ord)
    if not missing:
        return parts["font_dec"], parts["tu_dec"], parts["w_list"], unicode_to_cid, [], {}

    page_cids = _page_cids(pdf_path)
    cid_remap: dict[str, str] = {}
    sacrifice_slots: list[tuple[str, int]] = []
    sacrifice_text = (
        sacrifice
        if sacrifice is not None
        else _auto_sacrifice_chars(pdf_path, unicode_to_cid)
    )
    for ch in sacrifice_text:
        if ch not in template_chars:
            continue
        cid = int(unicode_to_cid[ch], 16)
        if cid == 0 or f"{cid:04X}" in page_cids:
            continue
        sacrifice_slots.append((ch, cid))

    donors: list[tuple[str, int]] = []
    for ch in relocatable:
        if ch not in template_chars:
            continue
        cid = int(unicode_to_cid[ch], 16)
        cid_hex = f"{cid:04X}"
        if cid == 0 or (ch, cid) in sacrifice_slots:
            continue
        # onlypdf_robot сверяет CID-отпечатки полей (ВТБ=00310032001E и т.д.).
        # Слоты, уже встречающиеся в content stream, нельзя переносить — только append.
        if cid_hex in page_cids:
            continue
        donors.append((ch, cid))

    additions: list[tuple[int, int]] = []
    idx = 0

    for slot in _free_glyph_slots(
        unicode_to_cid, len(dst_font.getGlyphOrder()), font=dst_font
    ):
        if idx >= len(missing):
            break
        ch = missing[idx]
        aw = _overwrite_slot(dst_font, src_font, slot, src_cmap[ord(ch)])
        unicode_to_cid[ch] = f"{slot:04X}"
        _ensure_w_entry(w_list, slot, _pdf_glyph_width(dst_font, w_list, aw))
        additions.append((slot, ord(ch)))
        idx += 1

    for donor_ch, donor_slot in sacrifice_slots:
        if idx >= len(missing):
            break
        ch = missing[idx]
        aw = _overwrite_slot(dst_font, src_font, donor_slot, src_cmap[ord(ch)])
        unicode_to_cid.pop(donor_ch, None)
        unicode_to_cid[ch] = f"{donor_slot:04X}"
        _ensure_w_entry(w_list, donor_slot, _pdf_glyph_width(dst_font, w_list, aw))
        additions.append((donor_slot, ord(ch)))
        idx += 1

    for donor_ch, donor_slot in donors:
        if idx >= len(missing):
            break
        ch = missing[idx]
        donor_name = dst_font.getGlyphOrder()[donor_slot]
        saved_glyph = deepcopy(dst_font["glyf"][donor_name])
        donor_aw, donor_lsb = dst_font["hmtx"][donor_name]
        aw = _overwrite_slot(dst_font, src_font, donor_slot, src_cmap[ord(ch)])
        unicode_to_cid.pop(donor_ch, None)
        unicode_to_cid[ch] = f"{donor_slot:04X}"
        _ensure_w_entry(w_list, donor_slot, _pdf_glyph_width(dst_font, w_list, aw))
        additions.append((donor_slot, ord(ch)))

        reloc_slot = _append_glyph_slot(dst_font, saved_glyph, donor_aw, donor_lsb)
        unicode_to_cid[donor_ch] = f"{reloc_slot:04X}"
        cid_remap[f"{donor_slot:04X}"] = f"{reloc_slot:04X}"
        additions.append((reloc_slot, ord(donor_ch)))
        _ensure_w_entry(
            w_list, reloc_slot, _pdf_glyph_width(dst_font, w_list, int(donor_aw))
        )
        idx += 1

    for ch in missing[idx:]:
        code = ord(ch)
        glyph_name = src_cmap[code]
        name_map = {n: n for n in dst_font.getGlyphOrder()}
        _import_glyph(dst_font, src_font, glyph_name, name_map)
        new_cid = dst_font.getGlyphOrder().index(name_map[glyph_name])
        aw, _ = dst_font["hmtx"][name_map[glyph_name]]
        unicode_to_cid[ch] = f"{new_cid:04X}"
        _ensure_w_entry(w_list, new_cid, _pdf_glyph_width(dst_font, w_list, int(aw)))
        additions.append((new_cid, code))

    _strip_font_tables(dst_font)
    out_font = BytesIO()
    dst_font.save(out_font, reorderTables=True)
    new_tu_dec = _rebuild_cmap_bfchar(parts["tu_dec"], unicode_to_cid)
    return (
        out_font.getvalue(),
        new_tu_dec,
        w_list,
        unicode_to_cid,
        additions,
        cid_remap,
    )


def minify_pdf_streams(data: bytearray) -> int:
    """Пересжимает Flate-потоки до минимального zlib-размера."""
    out = bytearray()
    pos = 0
    saved = 0
    for m in STREAM_RE.finditer(data):
        out.extend(data[pos : m.start()])
        header, stream_raw, footer = m.group(1), m.group(2), m.group(3)
        try:
            dec = zlib.decompress(stream_raw)
        except zlib.error:
            out.extend(m.group(0))
            pos = m.end()
            continue
        best = min(zlib.compress(dec, lvl) for lvl in range(10))
        if len(best) < len(stream_raw):
            saved += len(stream_raw) - len(best)
            stream_raw = best
        out.extend(header)
        out.extend(stream_raw)
        out.extend(footer)
        pos = m.end()
    out.extend(data[pos:])
    if saved:
        data.clear()
        data.extend(out)
    return saved


def normalize_pdf_to_target(data: bytearray, target: int) -> bool:
    """Подгоняет размер PDF к target байт (zlib-padding в компактный поток + xref)."""
    buf = bytearray(bytes(data))
    minify_pdf_streams(buf)
    if len(buf) > target:
        return False
    if len(buf) == target:
        data.clear()
        data.extend(buf)
        return True

    need = target - len(buf)
    candidates: list[tuple[_StreamSpan, bytes]] = []
    for m in STREAM_RE.finditer(bytes(buf)):
        raw = m.group(2)
        try:
            dec = zlib.decompress(raw)
        except zlib.error:
            continue
        if len(dec) > 25_000:
            continue
        span = _StreamSpan(m.start(), m.start(2), m.end(2), raw)
        candidates.append((span, dec))
    candidates.sort(key=lambda item: len(item[1]))

    base_size = len(buf)
    for span, dec in candidates:
        base_raw = len(span.raw)
        len_start, len_end = _length_token_span(bytes(buf), span.content_start)
        old_len_token = len_end - len_start

        lo, hi = max(0, need - 64), need + 2048
        while lo <= hi:
            mid = (lo + hi) // 2
            stream_target = base_raw + mid
            len_delta = len(f"/Length {stream_target}".encode()) - old_len_token
            est_size = base_size + len_delta + (stream_target - base_raw)
            if est_size != target:
                if est_size < target:
                    lo = mid + 1
                else:
                    hi = mid - 1
                continue
            padded = recompress_to_size(dec, stream_target)
            if not padded:
                hi = mid - 1
                continue
            trial = bytearray(buf)
            _patch_stream_span(trial, span, padded)
            if len(trial) == target:
                data.clear()
                data.extend(trial)
                return True
            if len(trial) < target:
                lo = mid + 1
            else:
                hi = mid - 1

        for stream_target in range(
            base_raw + max(0, need - 64), base_raw + need + 512
        ):
            len_delta = len(f"/Length {stream_target}".encode()) - old_len_token
            if base_size + len_delta + (stream_target - base_raw) != target:
                continue
            padded = recompress_to_size(dec, stream_target)
            if not padded:
                continue
            trial = bytearray(buf)
            _patch_stream_span(trial, span, padded)
            if len(trial) == target:
                data.clear()
                data.extend(trial)
                return True
    return False


def _build_extended_font(
    parts: dict,
    chars: set[str],
    tahoma_path: Path,
) -> tuple[bytes, bytes, list, dict[str, str], list[tuple[int, int]]]:
    tahoma_path = resolve_tahoma_path(tahoma_path)

    src_font = TTFont(tahoma_path)
    src_cmap = src_font.getBestCmap() or {}

    dst_font = TTFont(BytesIO(parts["font_dec"]))
    unicode_to_cid = dict(parts["unicode_to_cid"])
    w_list = list(parts["w_list"])
    additions: list[tuple[int, int]] = []

    for ch in sorted(chars, key=ord):
        if ch in unicode_to_cid:
            continue
        code = ord(ch)
        if code not in src_cmap:
            raise FontExtendError(
                f"Символ {ch!r} (U+{code:04X}) отсутствует в Tahoma"
            )
        glyph_name = src_cmap[code]
        new_gid, hmtx_width = _copy_glyph(dst_font, src_font, glyph_name)
        new_cid = new_gid
        unicode_to_cid[ch] = f"{new_cid:04X}"
        pdf_width = _pdf_glyph_width(dst_font, w_list, hmtx_width)
        w_list.extend([new_cid, [pdf_width]])
        additions.append((new_cid, code))

    if not additions:
        return (
            parts["font_dec"],
            parts["tu_dec"],
            parts["w_list"],
            unicode_to_cid,
            [],
        )

    out_font = BytesIO()
    dst_font.save(out_font, reorderTables=True)
    new_font_dec = out_font.getvalue()
    new_tu_dec = _rebuild_cmap_bfchar(parts["tu_dec"], unicode_to_cid)
    return new_font_dec, new_tu_dec, w_list, unicode_to_cid, additions


def _length_token_span(data: bytes, content_start: int) -> tuple[int, int]:
    window_start = max(0, content_start - 400)
    window = data[window_start:content_start]
    matches = list(re.finditer(rb"/Length\s+\d+", window))
    if not matches:
        raise FontExtendError("/Length не найден перед stream")
    m = matches[-1]
    return window_start + m.start(), window_start + m.end()


def _shift_span(span: _StreamSpan, delta: int) -> _StreamSpan:
    if delta == 0:
        return span
    return _StreamSpan(
        header_start=span.header_start + delta,
        content_start=span.content_start + delta,
        content_end=span.content_end + delta,
        raw=span.raw,
    )


def _patch_stream_span(data: bytearray, span: _StreamSpan, new_content: bytes) -> int:
    """Обновляет /Length и содержимое stream, корректируя xref при смене размера."""
    len_start, len_end = _length_token_span(bytes(data), span.content_start)
    new_len_token = f"/Length {len(new_content)}".encode("ascii")
    old_len_token = bytes(data[len_start:len_end])
    len_delta = len(new_len_token) - len(old_len_token)
    content_start = span.content_start
    content_end = span.content_end

    if len_delta:
        data[len_start:len_end] = new_len_token
        _fix_xref_offsets(data, len_start, len_delta)
        content_start += len_delta
        content_end += len_delta

    old_size = content_end - content_start
    content_delta = len(new_content) - old_size
    data[content_start:content_end] = new_content
    if content_delta:
        _fix_xref_offsets(data, content_start, content_delta)
    return len_delta + content_delta


def _patch_span(data: bytearray, start: int, end: int, new_bytes: bytes) -> None:
    delta = len(new_bytes) - (end - start)
    data[start:end] = new_bytes
    if delta:
        _fix_xref_offsets(data, start, delta)


def extend_font_in_pdf_bytes(
    data: bytearray,
    pdf_path: Path,
    *,
    chars: set[str] | None = None,
    full_charset: bool = False,
    tahoma_path: Path | None = None,
) -> FontExtendResult:
    """
    Дополняет subset-шрифт PDF недостающими символами из Tahoma.
    Меняет data in-place (размер файла может измениться).
    """
    tahoma_path = resolve_tahoma_path(tahoma_path)
    _require_pypdf()
    parts = _extract_font_parts(pdf_path)
    unicode_to_cid = parts["unicode_to_cid"]

    target = set(chars or ())
    if full_charset:
        target |= set(FULL_RECEIPT_CHARSET)
    missing = chars_needing_font_extension(target, unicode_to_cid)
    if not missing:
        return FontExtendResult(False, (), parts["unicode_to_cid"])

    new_ff_dec, new_tu_dec, new_w_list, new_map, added = _build_extended_font(
        parts, missing, tahoma_path
    )
    if not added:
        return FontExtendResult(False, (), parts["unicode_to_cid"])

    file_data = bytes(data)
    ff_span = _find_stream_span(file_data, parts["font_dec"])
    tu_span = _find_stream_span(file_data, parts["tu_dec"])
    if not ff_span or not tu_span:
        raise FontExtendError("FontFile2 или ToUnicode stream не найден в PDF")

    w_start, w_end = _parse_w_span(file_data)

    new_ff_raw = _compress_like_pdf(new_ff_dec)
    # pypdf get_data() already decompresses Flate streams — detect encoding from file bytes
    tu_flate = _stream_is_flate(tu_span)
    new_tu_raw = _compress_like_pdf(new_tu_dec) if tu_flate else new_tu_dec
    new_w_raw = _format_w_array(new_w_list)

    # патч с начала файла — после каждого шага сдвигаем последующие якоря
    delta = 0
    w_start += delta
    w_end += delta
    _patch_span(data, w_start, w_end, new_w_raw)
    delta += len(new_w_raw) - (w_end - w_start)

    ff_span = _shift_span(ff_span, delta)
    delta += _patch_stream_span(data, ff_span, new_ff_raw)

    tu_span = _shift_span(tu_span, delta)
    _patch_stream_span(data, tu_span, new_tu_raw)

    added_chars = tuple(chr(cp) for _, cp in added)
    try:
        verify_map = _load_unicode_to_cid_from_bytes(bytes(data))
    except FontExtendError:
        if not repair_tounicode_in_bytes(data):
            raise FontExtendError(
                "Не удалось восстановить /ToUnicode после расширения шрифта"
            ) from None
        verify_map = _load_unicode_to_cid_from_bytes(bytes(data))
    return FontExtendResult(True, added_chars, verify_map)


def _relocatable_for_pdf(pdf_path: Path) -> str:
    """Доп. слоты-доноры для pdf 58 (совместимость с subset UHQZMV)."""
    try:
        import pypdf

        reader = pypdf.PdfReader(str(pdf_path))
        base = str(reader.pages[0]["/Resources"]["/Font"]["/F1"]["/BaseFont"])
        if "UHQZMV" in base:
            return PDF58_RELOCATABLE
    except Exception:
        pass
    return ""


def ensure_chars_in_pdf(
    data: bytearray,
    pdf_path: Path,
    needed: set[str],
    *,
    full_cyrillic: bool = True,
) -> FontExtendResult:
    """Добавляет недостающие символы; при full_cyrillic — кириллица + латиница для СБП-ref."""
    target = set(needed)
    if full_cyrillic:
        target |= set(FULL_RECEIPT_CHARSET)
    return extend_font_compact_in_pdf_bytes(
        data, pdf_path, chars=target, relocatable=_relocatable_for_pdf(pdf_path)
    )


def extend_font_compact_in_pdf_bytes(
    data: bytearray,
    pdf_path: Path,
    *,
    chars: set[str] | None = None,
    tahoma_path: Path | None = None,
    relocatable: str | None = None,
) -> FontExtendResult:
    """
    Компактное расширение: полная кириллица, минимальный рост FontFile2.
    При target_size подгоняет итоговый PDF к этому размеру (для pdf 58).
    """
    tahoma_path = resolve_tahoma_path(tahoma_path)
    _require_pypdf()
    src = Path(pdf_path)
    parts = _extract_font_parts(src)
    target_chars = set(chars or FULL_CYRILLIC)
    missing = chars_needing_font_extension(target_chars, parts["unicode_to_cid"])
    if not missing:
        return FontExtendResult(False, (), parts["unicode_to_cid"])

    reloc = relocatable if relocatable is not None else _relocatable_for_pdf(src)
    new_ff_dec, new_tu_dec, new_w_list, new_map, added, cid_remap = (
        _build_extended_font_compact(
            parts,
            target_chars,
            tahoma_path,
            pdf_path=src,
            relocatable=reloc,
        )
    )
    if not added:
        return FontExtendResult(False, (), parts["unicode_to_cid"])

    file_data = bytes(data)
    ff_span = _find_stream_span(file_data, parts["font_dec"])
    tu_span = _find_stream_span(file_data, parts["tu_dec"])
    if not ff_span or not tu_span:
        raise FontExtendError("FontFile2 или ToUnicode stream не найден в PDF")

    w_start, w_end = _parse_w_span(file_data)
    new_ff_raw = _compress_like_pdf(new_ff_dec)
    tu_flate = _stream_is_flate(tu_span)
    new_tu_raw = _compress_like_pdf(new_tu_dec) if tu_flate else new_tu_dec
    new_w_raw = _format_w_array(new_w_list)

    delta = 0
    _patch_span(data, w_start + delta, w_end + delta, new_w_raw)
    delta += len(new_w_raw) - (w_end - w_start)
    ff_span = _shift_span(ff_span, delta)
    delta += _patch_stream_span(data, ff_span, new_ff_raw)
    tu_span = _shift_span(tu_span, delta)
    _patch_stream_span(data, tu_span, new_tu_raw)
    _remap_cids_in_pdf_streams(data, cid_remap)

    added_chars = tuple(chr(cp) for _, cp in added)
    try:
        verify_map = _load_unicode_to_cid_from_bytes(bytes(data))
    except FontExtendError:
        if not repair_tounicode_in_bytes(data):
            raise FontExtendError(
                "Не удалось восстановить /ToUnicode после расширения шрифта"
            ) from None
        verify_map = _load_unicode_to_cid_from_bytes(bytes(data))

    return FontExtendResult(True, added_chars, verify_map)


def _iter_field_hex_in_dec(dec: bytes):
    """(hex_str, start, end) для каждого Tj-поля в content stream."""
    from patch_alfa_amount import TJ_AT_POS_RE

    for tm in TJ_AT_POS_RE.finditer(dec):
        hexs = tm.group(3).decode().upper()
        if len(hexs) >= 8:
            yield hexs, tm.start(3), tm.end(3)


def _chars_in_cid_streams(data: bytes, cmap: dict[str, str]) -> set[str]:
    from patch_alfa_amount import decode_cid_hex

    chars: set[str] = set()
    for m in STREAM_RE.finditer(data):
        raw = m.group(2)
        try:
            dec = zlib.decompress(raw)
        except zlib.error:
            dec = raw
        for hexs, _, _ in _iter_field_hex_in_dec(dec):
            chars.update(decode_cid_hex(hexs, cmap))
    return chars


def reencode_cid_streams_for_cmap(
    data: bytearray,
    old_cmap: dict[str, str],
    new_cmap: dict[str, str],
) -> int:
    """Перекодирует CID hex в Tj-полях content stream (сохраняя оператор Tj)."""
    from patch_alfa_amount import decode_cid_hex, encode_cid_text

    file_data = bytes(data)
    pending: list[tuple[_StreamSpan, bytes]] = []
    for m in STREAM_RE.finditer(file_data):
        raw = m.group(2)
        try:
            dec = bytearray(zlib.decompress(raw))
            flate = True
        except zlib.error:
            dec = bytearray(raw)
            flate = False

        changed = False
        for hexs, start, end in reversed(list(_iter_field_hex_in_dec(dec))):
            text = decode_cid_hex(hexs, old_cmap)
            new_hex = encode_cid_text(text, new_cmap).decode("ascii")
            if new_hex == hexs:
                continue
            changed = True
            dec[start:end] = new_hex.encode("ascii")

        if not changed:
            continue
        new_raw = _compress_like_pdf(bytes(dec)) if flate else bytes(dec)
        pending.append((_StreamSpan(m.start(), m.start(2), m.end(2), raw), new_raw))

    delta = 0
    for span, new_raw in reversed(pending):
        span = _shift_span(span, delta)
        delta += _patch_stream_span(data, span, new_raw)
    return len(pending)


def swap_font_from_donor_pdf(
    data: bytearray,
    donor_pdf: Path,
    *,
    cmap: dict[str, str] | None = None,
) -> dict[str, str]:
    """
    Подменяет FontFile2/ToUnicode//W донором и перекодирует CID-потоки.

    Нужен для --bot-pass: патч на test_patch/lauchj (~73 КБ), затем компактный
    шрифт pdf58_fullfont (~60 КБ) с сохранением CID pdf 58 в критичных полях.
    """
    _require_pypdf()
    donor = Path(donor_pdf)
    if not donor.is_file():
        raise FontExtendError(f"Донор шрифта не найден: {donor}")

    old_cmap = dict(cmap) if cmap else _load_unicode_to_cid_from_bytes(bytes(data))
    donor_parts = _extract_font_parts(donor)
    new_cmap = donor_parts["unicode_to_cid"]

    needed = _chars_in_cid_streams(bytes(data), old_cmap)
    missing = sorted({ch for ch in needed if ch not in new_cmap}, key=ord)
    if missing:
        shown = ", ".join(repr(ch) for ch in missing[:10])
        raise FontExtendError(
            f"В доноре {donor.name} нет символов для перекодировки: {shown}"
        )

    streams_hit = reencode_cid_streams_for_cmap(data, old_cmap, new_cmap)
    if streams_hit == 0:
        raise FontExtendError("Перекодировка CID: потоки не изменены")

    current_parts = _extract_font_parts_from_bytes(bytes(data))
    file_data = bytes(data)

    ff_span = _find_stream_span(file_data, current_parts["font_dec"])
    tu_span = _find_stream_span(file_data, current_parts["tu_dec"])
    if not ff_span or not tu_span:
        raise FontExtendError("FontFile2 или ToUnicode не найден в патче")

    w_start, w_end = _parse_w_span(file_data)
    new_ff_raw = _compress_like_pdf(donor_parts["font_dec"])
    tu_flate = _stream_is_flate(tu_span)
    new_tu_raw = (
        _compress_like_pdf(donor_parts["tu_dec"])
        if tu_flate or donor_parts["tu_compressed"]
        else donor_parts["tu_dec"]
    )
    new_w_raw = _format_w_array(donor_parts["w_list"])

    delta = 0
    _patch_span(data, w_start + delta, w_end + delta, new_w_raw)
    delta += len(new_w_raw) - (w_end - w_start)
    ff_span = _shift_span(ff_span, delta)
    delta += _patch_stream_span(data, ff_span, new_ff_raw)
    tu_span = _shift_span(tu_span, delta)
    _patch_stream_span(data, tu_span, new_tu_raw)

    verify = _load_unicode_to_cid_from_bytes(bytes(data))
    return verify


def _extract_font_parts_from_bytes(data: bytes) -> dict:
    import pypdf
    from io import BytesIO

    reader = pypdf.PdfReader(BytesIO(data))
    font = reader.pages[0]["/Resources"]["/Font"]["/F1"]
    desc = font["/DescendantFonts"][0].get_object()
    fd = desc["/FontDescriptor"]
    ff_dec = fd["/FontFile2"].get_data()
    tu_obj = font["/ToUnicode"]
    tu_raw = (
        tu_obj.get_data()
        if hasattr(tu_obj, "get_data")
        else tu_obj.get_object().get_data()
    )
    try:
        tu_dec = zlib.decompress(tu_raw)
        tu_compressed = True
    except zlib.error:
        tu_dec = tu_raw
        tu_compressed = False
    w_list = list(desc.get("/W") or [])
    return {
        "font_dec": ff_dec,
        "tu_dec": tu_dec,
        "tu_compressed": tu_compressed,
        "w_list": w_list,
        "unicode_to_cid": _parse_cmap_bfchar(tu_dec),
    }


def _grow_pdf_via_cmap_comments(data: bytearray, target: int) -> bool:
    """Увеличивает PDF за счёт комментариев в /ToUnicode (для точного размера pdf 58)."""
    if len(data) >= target:
        return len(data) == target

    file_data = bytes(data)
    tu_span: _StreamSpan | None = None
    tu_dec: bytes | None = None
    tu_flate = False
    for m in STREAM_RE.finditer(file_data):
        raw = m.group(2)
        try:
            dec = zlib.decompress(raw)
            flate = True
        except zlib.error:
            dec = raw
            flate = False
        if b"beginbfchar" not in dec:
            continue
        tu_span = _StreamSpan(m.start(), m.start(2), m.end(2), raw)
        tu_dec = dec
        tu_flate = flate
        break
    if tu_span is None or tu_dec is None:
        return False

    text = tu_dec.decode("latin-1")
    insert_at = text.find("\nendcmap")
    if insert_at < 0:
        return False
    prefix, suffix = text[:insert_at], text[insert_at:]

    def _apply(comment_block: str) -> int | None:
        padded_text = prefix + comment_block + suffix
        new_raw = (
            _compress_like_pdf(padded_text.encode("latin-1"))
            if tu_flate
            else padded_text.encode("latin-1")
        )
        trial = bytearray(data)
        _patch_stream_span(trial, tu_span, new_raw)
        if len(trial) == target:
            data.clear()
            data.extend(trial)
            return target
        return len(trial)

    for lines in range(0, 256):
        block = "".join(f"\n% {i:04d}" for i in range(lines))
        size = _apply(block)
        if size == target:
            return True
        if size is not None and size > target:
            break

    for lines in range(0, 256):
        base = "".join(f"\n% {i:04d}" for i in range(lines))
        for extra in range(64):
            tail = f"\n% {'x' * extra}"
            if _apply(base + tail) == target:
                return True
    return False


def fit_pdf_to_target(data: bytearray, target: int) -> bool:
    """Сжимает потоки и при необходимости дополняет zlib-паддингом до target байт."""
    minify_pdf_streams(data)
    if len(data) == target:
        return True
    if len(data) < target:
        if normalize_pdf_to_target(data, target):
            return True
        return _grow_pdf_via_cmap_comments(data, target)
    # Чуть больше шаблона — ещё раз пересжать потоки (иногда помогает после патча шрифта).
    for _ in range(2):
        saved = minify_pdf_streams(data)
        if len(data) <= target:
            break
        if not saved:
            break
    return len(data) == target


def ensure_squash_bot_charset(
    pdf_path: Path,
    output_pdf: Path | None = None,
    *,
    target_size: int | None = None,
) -> FontExtendResult:
    """
    Полная кириллица для pdf 58 с размером оригинала (~58320 байт).
    Hinting снимается — текст чуть «сплющеннее», зато onlypdf_robot распознаёт чек.
    """
    src = Path(pdf_path)
    data = bytearray(src.read_bytes())
    original_size = len(data)
    parts = _extract_font_parts(src)
    result = extend_font_compact_in_pdf_bytes(
        data,
        src,
        chars=full_template_charset(parts["unicode_to_cid"]),
        relocatable=_relocatable_for_pdf(src),
    )
    _strip_hinting_in_pdf_bytes(data)
    dst = Path(output_pdf) if output_pdf else src.with_name(f"{src.stem}_squash{src.suffix}")
    goal = target_size if target_size is not None else original_size
    minify_pdf_streams(data)
    if not fit_pdf_to_target(data, goal):
        minify_pdf_streams(data)
    dst.write_bytes(data)
    if dst.stat().st_size != goal:
        sized = bytearray(dst.read_bytes())
        minify_pdf_streams(sized)
        if fit_pdf_to_target(sized, goal):
            dst.write_bytes(sized)
    if dst.stat().st_size != goal:
        raise FontExtendError(
            f"Шаблон {dst.name}: {dst.stat().st_size} байт, нужно {goal} "
            f"(onlypdf_robot принимает pdf 58 ≈ {goal} байт)."
        )
    return result


def ensure_full_receipt_charset(
    pdf_path: Path,
    output_pdf: Path | None = None,
    *,
    target_size: int | None = None,
) -> FontExtendResult:
    """
    Компактно расширяет шрифт до полной кириллицы, сохраняя hinting и слоты подписей.
    По возможности подгоняет размер PDF к шаблону (pdf 58 ≈ 58320 байт).
    """
    src = Path(pdf_path)
    data = bytearray(src.read_bytes())
    original_size = len(data)
    parts = _extract_font_parts(src)
    result = extend_font_compact_in_pdf_bytes(
        data,
        src,
        chars=full_template_charset(parts["unicode_to_cid"]),
        relocatable=_relocatable_for_pdf(src),
    )
    dst = Path(output_pdf) if output_pdf else src.with_name(f"{src.stem}_fullfont{src.suffix}")
    goal = target_size if target_size is not None else original_size
    if not fit_pdf_to_target(data, goal):
        minify_pdf_streams(data)
    dst.write_bytes(data)
    if len(data) != goal:
        sized = bytearray(dst.read_bytes())
        if fit_pdf_to_target(sized, goal):
            dst.write_bytes(sized)
    return result
