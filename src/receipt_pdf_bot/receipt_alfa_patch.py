"""Сборка PDF-чека Альфа-Банка через patch_alfa_amount (bot-pass шаблон)."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

_MODULE_DIR = Path(__file__).resolve().parent
_BOT_ROOT = _MODULE_DIR.parents[1]  # Fildfer_bot3-main
_VENDOR_DIR = _BOT_ROOT / "vendor"
DEFAULTS_FILE = _MODULE_DIR / "alfa_defaults.json"
CARD_DEFAULTS_FILE = _MODULE_DIR / "alfa_card_defaults.json"
ACCOUNT_DEFAULTS_FILE = _MODULE_DIR / "alfa_account_defaults.json"
BOT_TEMPLATES = _BOT_ROOT / "templates"
DESKTOP = Path.home() / "Desktop"
DEFAULT_ALFA_TEMPLATE = BOT_TEMPLATES / "PROHOD_FIXED1.pdf"
DEFAULT_ALFA_CARD_TEMPLATE = BOT_TEMPLATES / "PROHOD_CARD_FIXED1.pdf"
DEFAULT_ALFA_ACCOUNT_TEMPLATE = BOT_TEMPLATES / "PROHOD_ACCOUNT.pdf"
_PATCH_MODULE = "patch_alfa_amount.py"


@lru_cache(maxsize=1)
def _find_pdf_checker_root() -> Path:
    """Каталог с patch_alfa_amount.py и font_extend.py (vendor/ или pdf-checker)."""
    env = os.getenv("PDF_CHECKER_ROOT", "").strip()
    if env:
        path = Path(env).expanduser().resolve()
        if (path / _PATCH_MODULE).is_file():
            return path
        raise FileNotFoundError(
            f"PDF_CHECKER_ROOT={path} — файл {_PATCH_MODULE} не найден"
        )

    seen: set[Path] = set()
    candidates: list[Path] = [
        _VENDOR_DIR,
    ]

    for parent in _MODULE_DIR.parents:
        candidates.append(parent)

    candidates.extend(
        (
            _BOT_ROOT,
            _BOT_ROOT.parent,
            _BOT_ROOT.parent / "pdf-checker",
            DESKTOP / "pdf-checker",
        )
    )

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / _PATCH_MODULE).is_file():
            return resolved

    raise FileNotFoundError(
        f"Не найден {_PATCH_MODULE}. Для BotHost положите файлы в {_VENDOR_DIR} "
        "или задайте PDF_CHECKER_ROOT в .env."
    )


def get_pdf_checker_root() -> Path:
    return _find_pdf_checker_root()

# Поля бота (FSM) → ключи patch_alfa_amount
BOT_FIELD_TO_PATCH: dict[str, str] = {
    "amount": "amount",
    "fee": "commission",
    "header_datetime": "datetime_header",
    "transfer_datetime": "datetime_full",
    "recipient_name": "recipient_name",
    "recipient_card": "phone",
    "recipient_bank": "recipient_bank",
    "sender_account": "account",
    "document_number": "operation_id",
    "auth_code": "sbp_ref",
    "transfer_message": "purpose",
}

MONEY_BOT_FIELDS = frozenset({"amount", "fee"})

# Поля бота (FSM) → patch_alfa_amount для чека карта→карта
BOT_FIELD_TO_PATCH_CARD: dict[str, str] = {
    "amount": "amount",
    "fee": "commission",
    "header_datetime": "datetime_header",
    "transfer_datetime": "datetime_full",
    "sender_account": "sender_card",
    "recipient_card": "recipient_card",
    "auth_code": "auth_code",
    "document_number": "terminal_code",
    "receipt_number": "operation_ref",
}

# Поля бота → patch_alfa_amount для «перевод на счёт в другой банк»
BOT_FIELD_TO_PATCH_ACCOUNT: dict[str, str] = {
    "amount": "amount",
    "fee": "commission",
    "transfer_datetime": "datetime_full",
    "document_number": "operation_id",
    "receipt_number": "payment_order",
    "sender_name": "payer_name",
    "sender_account": "sender_account",
    "recipient_name": "recipient_name",
    "recipient_card": "recipient_account",
    "recipient_bank": "recipient_bank",
    "transfer_message": "purpose",
}


def _ensure_checker_import() -> None:
    root = str(_find_pdf_checker_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import patch_alfa_amount  # noqa: F401
    except ModuleNotFoundError as exc:
        raise FileNotFoundError(
            f"Не удалось импортировать patch_alfa_amount из {root}"
        ) from exc


def load_alfa_defaults() -> dict[str, Any]:
    if DEFAULTS_FILE.is_file():
        return json.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
    return {}


def load_alfa_card_defaults() -> dict[str, Any]:
    if CARD_DEFAULTS_FILE.is_file():
        return json.loads(CARD_DEFAULTS_FILE.read_text(encoding="utf-8"))
    return {}


def load_alfa_account_defaults() -> dict[str, Any]:
    if ACCOUNT_DEFAULTS_FILE.is_file():
        return json.loads(ACCOUNT_DEFAULTS_FILE.read_text(encoding="utf-8"))
    return {}


def _parse_money(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return 0
    text = (
        text.replace("\xa0", " ")
        .replace("RUB", "")
        .replace("RUR", "")
        .replace("руб", "")
        .replace("₽", "")
    )
    text = text.replace(",", ".")
    if "." in text:
        text = text.split(".", 1)[0]
    digits = re.sub(r"\D", "", text)
    if not digits:
        raise ValueError(f"Не удалось разобрать сумму: {value!r}")
    return int(digits)


def build_patch_values(
    bot_values: dict[str, Any],
    defaults: dict[str, Any] | None = None,
    *,
    card: bool = False,
    account: bool = False,
) -> dict[str, Any]:
    """Собирает словарь для replace_fields_in_pdf из ответов пользователя."""
    if account:
        mapping = BOT_FIELD_TO_PATCH_ACCOUNT
        if defaults is None:
            defaults = load_alfa_account_defaults()
    elif card:
        mapping = BOT_FIELD_TO_PATCH_CARD
        if defaults is None:
            defaults = load_alfa_card_defaults()
    else:
        mapping = BOT_FIELD_TO_PATCH
        if defaults is None:
            defaults = load_alfa_defaults()
    base = dict(defaults)
    for bot_key, patch_key in mapping.items():
        raw = bot_values.get(bot_key)
        if raw is None or str(raw).strip() == "":
            continue
        if bot_key == "fee" and card:
            base[patch_key] = str(raw).strip()
        elif bot_key in MONEY_BOT_FIELDS:
            base[patch_key] = _parse_money(raw)
        else:
            base[patch_key] = str(raw).strip()
    return base


def find_alfa_template() -> Path:
    """Ищет bot-pass шаблон (по умолчанию templates/PROHOD_FIXED1.pdf в репозитории)."""
    env = os.getenv("ALFA_TEMPLATE_PDF", "").strip()
    if env:
        path = Path(env)
        if path.is_file():
            return path
        raise FileNotFoundError(f"ALFA_TEMPLATE_PDF не найден: {path}")

    preferred = (
        BOT_TEMPLATES / "PROHOD_FIXED1.pdf",
        DEFAULT_ALFA_TEMPLATE,
        DESKTOP / "PROHOD_FIXED1.pdf",
        DESKTOP / "PROHOD_FIXED.pdf",
    )
    for candidate in preferred:
        if candidate.is_file():
            return candidate

    local_names = ("PROHOD_FIXED1.pdf", "lauchj.pdf", "test_patch.pdf", "pdf58_bot_pass.pdf")
    for folder in (BOT_TEMPLATES, _find_pdf_checker_root(), DESKTOP):
        for name in local_names:
            candidate = folder / name
            if candidate.is_file():
                return candidate

    _ensure_checker_import()
    from patch_alfa_amount import AmountPatchError, _bot_pass_template_candidates, _validate_bot_pass_template

    for candidate in _bot_pass_template_candidates():
        try:
            _validate_bot_pass_template(candidate)
            return candidate
        except AmountPatchError:
            continue

    raise FileNotFoundError(
        f"Не найден шаблон PROHOD_FIXED1.pdf.\n"
        f"Положите файл в {BOT_TEMPLATES} (для GitHub/BotHost) "
        "или задайте ALFA_TEMPLATE_PDF в .env"
    )


def find_alfa_card_template() -> Path:
    """Ищет bot-pass шаблон чека карта→карта (оригинальный subset, не fullfont)."""
    env = os.getenv("ALFA_CARD_TEMPLATE_PDF", "").strip()
    if env:
        path = Path(env)
        if path.is_file():
            return path
        raise FileNotFoundError(f"ALFA_CARD_TEMPLATE_PDF не найден: {path}")

    from patch_alfa_amount import AmountPatchError, resolve_card_bot_pass_template

    preferred = (
        DEFAULT_ALFA_CARD_TEMPLATE,
        DESKTOP / "PROHOD_CARD_FIXED1.pdf",
        DESKTOP / "PDF Document.pdf",
    )
    for candidate in preferred:
        if candidate.is_file():
            try:
                return resolve_card_bot_pass_template(candidate)
            except AmountPatchError:
                continue

    raise FileNotFoundError(
        f"Не найден bot-pass шаблон карта→карта (PDF Document.pdf / PROHOD_CARD_FIXED1.pdf).\n"
        f"Положите копию {DESKTOP / 'PDF Document.pdf'} в {BOT_TEMPLATES} "
        "как PROHOD_CARD_FIXED1.pdf.\n"
        "Не используйте alfa_card_fullfont.pdf — бот не распознаёт расширенный шрифт."
    )


def find_alfa_account_template() -> Path:
    """Ищет шаблон «перевод на счёт в другой банк» (PDF.pdf / PROHOD_ACCOUNT.pdf)."""
    env = os.getenv("ALFA_ACCOUNT_TEMPLATE_PDF", "").strip()
    if env:
        path = Path(env)
        if path.is_file():
            return path
        raise FileNotFoundError(f"ALFA_ACCOUNT_TEMPLATE_PDF не найден: {path}")

    from patch_alfa_amount import AmountPatchError, resolve_account_bot_pass_template

    preferred = (
        DEFAULT_ALFA_ACCOUNT_TEMPLATE,
        DESKTOP / "PROHOD_ACCOUNT.pdf",
        Path(r"d:\Загрузки\PDF.pdf"),
    )
    for candidate in preferred:
        if candidate.is_file():
            try:
                return resolve_account_bot_pass_template(candidate)
            except AmountPatchError:
                continue

    raise FileNotFoundError(
        f"Не найден шаблон «перевод на счёт» (PDF.pdf / PROHOD_ACCOUNT.pdf).\n"
        f"Положите оригинал в {BOT_TEMPLATES} как PROHOD_ACCOUNT.pdf."
    )


def render_alfa_botpass_pdf(bot_values: dict[str, Any]) -> bytes:
    """Патчит bot-pass шаблон СБП и возвращает байты PDF."""
    return _render_alfa_pdf(bot_values, card=False)


def render_alfa_card_pdf(bot_values: dict[str, Any]) -> bytes:
    """Патчит шаблон чека карта→карта и возвращает байты PDF."""
    return _render_alfa_pdf(bot_values, card=True)


def render_alfa_account_pdf(bot_values: dict[str, Any]) -> bytes:
    """Патчит шаблон «перевод на счёт» и возвращает байты PDF."""
    return _render_alfa_pdf(bot_values, account=True)


def _render_alfa_pdf(
    bot_values: dict[str, Any],
    *,
    card: bool = False,
    account: bool = False,
) -> bytes:
    _ensure_checker_import()
    from patch_alfa_amount import (
        ACCOUNT_BOT_SAFE_FONT_FILE2_EXACT,
        ACCOUNT_BOT_SAFE_GLYPH_COUNT,
        AmountPatchError,
        CARD_BOT_SAFE_CONTENT_STREAM,
        CARD_BOT_SAFE_FILE_SIZE,
        CARD_BOT_SAFE_FONT_FILE2_EXACT,
        CARD_BOT_SAFE_GLYPH_COUNT,
        CARD_PATCH_MAX_SIZE_DELTA,
        card_font_file2_md5,
        card_font_file2_size,
        card_font_glyph_count,
        ensure_card_template_for_values,
        replace_fields_in_pdf,
        resolve_account_bot_pass_template,
        resolve_card_bot_pass_template,
        validate_account_bot_safe_patch,
        validate_card_bot_safe_patch,
    )

    if account:
        template = find_alfa_account_template()
        patch_values = build_patch_values(bot_values, account=True)
        template = resolve_account_bot_pass_template(template)
        validate_account_bot_safe_patch(template, patch_values)
        receipt_template = "account"
    elif card:
        template = find_alfa_card_template()
        patch_values = build_patch_values(bot_values, card=True)
        template = resolve_card_bot_pass_template(template)
        template = ensure_card_template_for_values(template, patch_values)
        validate_card_bot_safe_patch(template, patch_values)
        receipt_template = "card"
    else:
        template = find_alfa_template()
        patch_values = build_patch_values(bot_values)
        receipt_template = None

    template_size = template.stat().st_size
    template_ff2_md5 = card_font_file2_md5(template) if card else None

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        out_path = Path(tmp.name)

    try:
        replace_fields_in_pdf(
            template,
            patch_values,
            out_path,
            verify=False,
            extend_font=False,
            template=receipt_template,
        )
        if card or account:
            from font_extend import fit_pdf_to_target, stabilize_card_content_stream

            out_data = bytearray(out_path.read_bytes())
            if card:
                stabilize_card_content_stream(
                    out_data, target_compressed=CARD_BOT_SAFE_CONTENT_STREAM
                )
            fit_pdf_to_target(out_data, template_size)
            out_path.write_bytes(out_data)
            out_size = out_path.stat().st_size
            expected_size = (
                CARD_BOT_SAFE_FILE_SIZE if card else template_size
            )
            if card and out_size != expected_size and abs(out_size - expected_size) > CARD_PATCH_MAX_SIZE_DELTA:
                raise AmountPatchError(
                    f"Размер PDF изменился ({expected_size} → {out_size} байт). "
                    "Бот не распознает чек — пересоберите PROHOD_CARD_FIXED1 "
                    "(--fix-card-template из PDF Document.pdf)."
                )
            if account and out_size != template_size and abs(out_size - template_size) > 2:
                raise AmountPatchError(
                    f"Размер PDF изменился ({template_size} → {out_size} байт). "
                    "Бот не распознает чек — проверьте шаблон."
                )
            out_ff2 = card_font_file2_size(out_path)
            out_glyphs = card_font_glyph_count(out_path)
            if card:
                expected_ff2 = CARD_BOT_SAFE_FONT_FILE2_EXACT
                expected_glyphs = CARD_BOT_SAFE_GLYPH_COUNT
                kind = "карта→карта"
            else:
                expected_ff2 = ACCOUNT_BOT_SAFE_FONT_FILE2_EXACT
                expected_glyphs = ACCOUNT_BOT_SAFE_GLYPH_COUNT
                kind = "перевод на счёт"
            if out_ff2 != expected_ff2 or out_glyphs != expected_glyphs:
                raise AmountPatchError(
                    f"FontFile2 изменился ({out_ff2} байт, {out_glyphs} глифов). "
                    f"Нужно {expected_ff2} байт и {expected_glyphs} глифов ({kind}) — "
                    "бот пишет «чек не распознан»."
                )
            if template_ff2_md5 and card_font_file2_md5(out_path) != template_ff2_md5:
                raise AmountPatchError(
                    "Отпечаток FontFile2 не совпадает с шаблоном — "
                    "бот пишет «чек не распознан». "
                    "Пересоберите PROHOD_CARD_FIXED1.pdf (--fix-card-template)."
                )
        return out_path.read_bytes()
    except AmountPatchError as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        if out_path.is_file():
            out_path.unlink(missing_ok=True)
