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
BOT_TEMPLATES = _BOT_ROOT / "templates"
DESKTOP = Path.home() / "Desktop"
DEFAULT_ALFA_TEMPLATE = BOT_TEMPLATES / "PROHOD_FIXED1.pdf"
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


def build_patch_values(bot_values: dict[str, Any], defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """Собирает словарь для replace_fields_in_pdf из ответов пользователя."""
    base = dict(defaults or load_alfa_defaults())
    for bot_key, patch_key in BOT_FIELD_TO_PATCH.items():
        raw = bot_values.get(bot_key)
        if raw is None or str(raw).strip() == "":
            continue
        if bot_key in MONEY_BOT_FIELDS:
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


def render_alfa_botpass_pdf(bot_values: dict[str, Any]) -> bytes:
    """Патчит bot-pass шаблон и возвращает байты PDF."""
    _ensure_checker_import()
    from patch_alfa_amount import AmountPatchError, replace_fields_in_pdf

    template = find_alfa_template()
    patch_values = build_patch_values(bot_values)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        out_path = Path(tmp.name)

    try:
        replace_fields_in_pdf(
            template,
            patch_values,
            out_path,
            verify=False,
            extend_font=False,
        )
        return out_path.read_bytes()
    except AmountPatchError as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        if out_path.is_file():
            out_path.unlink(missing_ok=True)
