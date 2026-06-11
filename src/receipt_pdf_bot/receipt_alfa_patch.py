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
BOT_TEMPLATES = _BOT_ROOT / "templates"
DESKTOP = Path.home() / "Desktop"
DEFAULT_ALFA_TEMPLATE = BOT_TEMPLATES / "PROHOD_FIXED1.pdf"
DEFAULT_ALFA_CARD_TEMPLATE = BOT_TEMPLATES / "PROHOD_CARD_FIXED1.pdf"
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
) -> dict[str, Any]:
    """Собирает словарь для replace_fields_in_pdf из ответов пользователя."""
    mapping = BOT_FIELD_TO_PATCH_CARD if card else BOT_FIELD_TO_PATCH
    if defaults is None:
        defaults = load_alfa_card_defaults() if card else load_alfa_defaults()
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


def render_alfa_botpass_pdf(bot_values: dict[str, Any]) -> bytes:
    """Патчит bot-pass шаблон СБП и возвращает байты PDF."""
    return _render_alfa_pdf(bot_values, card=False)


def render_alfa_card_pdf(bot_values: dict[str, Any]) -> bytes:
    """Патчит шаблон чека карта→карта и возвращает байты PDF."""
    return _render_alfa_pdf(bot_values, card=True)


def _render_alfa_pdf(bot_values: dict[str, Any], *, card: bool) -> bytes:
    _ensure_checker_import()
    from patch_alfa_amount import (
        AmountPatchError,
        load_unicode_to_cid,
        missing_receipt_digits,
        repair_card_template_digits,
        replace_fields_in_pdf,
        resolve_card_bot_pass_template,
        validate_card_bot_safe_patch,
    )

    template = find_alfa_card_template() if card else find_alfa_template()
    patch_values = build_patch_values(bot_values, card=card)
    prepared_template: Path | None = None

    if card:
        template = resolve_card_bot_pass_template(template)
        if missing_receipt_digits(load_unicode_to_cid(template)):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_tpl:
                prepared_template = Path(tmp_tpl.name)
            template = repair_card_template_digits(template, prepared_template)
        validate_card_bot_safe_patch(template, patch_values)

    template_size = template.stat().st_size

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        out_path = Path(tmp.name)

    try:
        replace_fields_in_pdf(
            template,
            patch_values,
            out_path,
            verify=False,
            extend_font=False,
            template="card" if card else None,
        )
        if card:
            from font_extend import fit_pdf_to_target

            out_data = bytearray(out_path.read_bytes())
            fit_pdf_to_target(out_data, template_size)
            out_path.write_bytes(out_data)
            out_size = out_path.stat().st_size
            if out_size != template_size and abs(out_size - template_size) > 2:
                raise AmountPatchError(
                    f"Размер PDF изменился ({template_size} → {out_size} байт). "
                    "Бот не распознает чек — проверьте шаблон (нужен PDF Document.pdf, не fullfont)."
                )
        return out_path.read_bytes()
    except AmountPatchError as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        if out_path.is_file():
            out_path.unlink(missing_ok=True)
        if prepared_template is not None and prepared_template.is_file():
            prepared_template.unlink(missing_ok=True)
