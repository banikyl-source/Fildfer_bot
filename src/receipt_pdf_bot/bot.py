"""Telegram bot front-end for the demo receipt generator.

The bot guides the user through a step-by-step FSM dialog, collects every
field, and replies with a watermarked demo PDF. Two input modes are
supported:

  * `/new` — step-by-step questions (default, easiest)
  * `/quick` — paste all fields in one message in `key: value` format
"""

from __future__ import annotations

import logging
import os
import ssl
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BufferedInputFile, Message
from dotenv import load_dotenv

from receipt_pdf_bot.receipt import ReceiptData, render_receipt_pdf
from receipt_pdf_bot.receipt_17_03_2026_template import (
    Receipt17Data,
    render_receipt_17_pdf,
)

logger = logging.getLogger(__name__)

router = Router()


class FillReceipt(StatesGroup):
    template = State()
    datetime_text = State()
    operation = State()
    recipient_name = State()
    recipient_card = State()
    recipient_bank = State()
    sender_name = State()
    sender_account = State()
    amount = State()
    fee = State()
    document_number = State()
    auth_code = State()
    receipt_number = State()  # НОВОЕ: отдельный номер квитанции


# Порядок шагов для классического шаблона (без recipient_bank)
_FIELD_ORDER_CLASSIC = (
    FillReceipt.datetime_text,
    FillReceipt.operation,
    FillReceipt.recipient_name,
    FillReceipt.recipient_card,
    FillReceipt.sender_name,
    FillReceipt.sender_account,
    FillReceipt.amount,
    FillReceipt.fee,
    FillReceipt.document_number,
    FillReceipt.auth_code,
    FillReceipt.receipt_number,   # добавлен
)

# Полный порядок для шаблона 17 (включая recipient_bank)
_FIELD_ORDER_FULL = (
    FillReceipt.datetime_text,
    FillReceipt.operation,
    FillReceipt.recipient_name,
    FillReceipt.recipient_card,
    FillReceipt.recipient_bank,
    FillReceipt.sender_name,
    FillReceipt.sender_account,
    FillReceipt.amount,
    FillReceipt.fee,
    FillReceipt.document_number,
    FillReceipt.auth_code,
    FillReceipt.receipt_number,   # добавлен
)

# Маппинг состояний в имена полей (для всех шаблонов)
_FIELD_BY_STATE = {
    FillReceipt.datetime_text.state: "datetime_text",
    FillReceipt.operation.state: "operation",
    FillReceipt.recipient_name.state: "recipient_name",
    FillReceipt.recipient_card.state: "recipient_card",
    FillReceipt.recipient_bank.state: "recipient_bank",
    FillReceipt.sender_name.state: "sender_name",
    FillReceipt.sender_account.state: "sender_account",
    FillReceipt.amount.state: "amount",
    FillReceipt.fee.state: "fee",
    FillReceipt.document_number.state: "document_number",
    FillReceipt.auth_code.state: "auth_code",
    FillReceipt.receipt_number.state: "receipt_number",
}

# Тексты подсказок для каждого шага (для классического шаблона, для 17-го переопределяются)
_NEXT_PROMPT = {
    FillReceipt.datetime_text.state: "<b>Шаг 1/11.</b> Введите дату и время операции.\nНапример: <code>5 апреля 2026 20:29:42 (МСК)</code>",
    FillReceipt.operation.state: "<b>Шаг 2/11.</b> Название операции.\nНапример: <code>Перевод клиенту</code>",
    FillReceipt.recipient_name.state: "<b>Шаг 3/11.</b> ФИО получателя.\nНапример: <code>Даниил Андреевич З.</code>",
    FillReceipt.recipient_card.state: "<b>Шаг 4/11.</b> Карта или телефон получателя.\nНапример: <code>**** 0264</code>",
    FillReceipt.recipient_bank.state: "<b>Шаг 5/11.</b> Банк получателя (только для шаблона 2).\nНапример: <code>Яндекс</code>",
    FillReceipt.sender_name.state: "<b>Шаг 5/11.</b> ФИО отправителя.\nНапример: <code>Артём Анатольевич М.</code>",
    FillReceipt.sender_account.state: "<b>Шаг 6/11.</b> Счёт отправителя.\nНапример: <code>**** 0220</code>",
    FillReceipt.amount.state: "<b>Шаг 7/11.</b> Сумма перевода.\nНапример: <code>259,00 ₽</code>",
    FillReceipt.fee.state: "<b>Шаг 8/11.</b> Комиссия.\nНапример: <code>0,00 ₽</code>",
    FillReceipt.document_number.state: "<b>Шаг 9/11.</b> Номер документа (идентификатор операции, первая строка).\nНапример: <code>A6076160011783290G100300117</code>",
    FillReceipt.auth_code.state: "<b>Шаг 10/11.</b> Код авторизации (вторая строка).\nНапример: <code>00117</code>",
    FillReceipt.receipt_number.state: "<b>Шаг 11/11.</b> Номер квитанции (отдельно от идентификатора).\nНапример: <code>№ 1-127-176-643-532</code> (или просто <code>1-127-176-643-532</code>)",
}

# Для шаблона 17 используем те же подсказки, но с поправкой на количество шагов и значения по умолчанию
_TEMPLATE_17_DEFAULTS = Receipt17Data()
_TEMPLATE_17_FIELD_HINTS: dict[str, tuple[str, str]] = {
    "datetime_text": ("Дата и время", _TEMPLATE_17_DEFAULTS.datetime_text),
    "operation": ("Тип перевода", _TEMPLATE_17_DEFAULTS.transfer_type),
    "recipient_name": ("Получатель", _TEMPLATE_17_DEFAULTS.recipient_name),
    "recipient_card": ("Телефон получателя", _TEMPLATE_17_DEFAULTS.recipient_phone),
    "recipient_bank": ("Банк получателя", _TEMPLATE_17_DEFAULTS.recipient_bank),
    "sender_name": ("Отправитель", _TEMPLATE_17_DEFAULTS.sender_name),
    "sender_account": ("Счёт списания", _TEMPLATE_17_DEFAULTS.debit_account),
    "amount": ("Сумма", _TEMPLATE_17_DEFAULTS.amount),
    "fee": ("Комиссия", _TEMPLATE_17_DEFAULTS.fee),
    "document_number": ("Идентификатор операции (первая строка)", _TEMPLATE_17_DEFAULTS.operation_id_line_1),
    "auth_code": ("Код авторизации (вторая строка)", _TEMPLATE_17_DEFAULTS.operation_id_line_2),
    "receipt_number": ("Номер квитанции", _TEMPLATE_17_DEFAULTS.receipt_number),
}

TEMPLATE_CLASSIC = "classic"
TEMPLATE_17 = "receipt_17"

_TEMPLATE_CHOICES: dict[str, str] = {
    "1": TEMPLATE_CLASSIC,
    "classic": TEMPLATE_CLASSIC,
    "старый": TEMPLATE_CLASSIC,
    "обычный": TEMPLATE_CLASSIC,
    "2": TEMPLATE_17,
    "17": TEMPLATE_17,
    "receipt_17": TEMPLATE_17,
    "новый": TEMPLATE_17,
}

_TEMPLATE_NAMES: dict[str, str] = {
    TEMPLATE_CLASSIC: "Шаблон 1: чек по операции",
    TEMPLATE_17: "Шаблон 2: квитанция 17.03",
}

_RECEIPT_DATA_FIELDS = set(ReceiptData.__dataclass_fields__)

_QUICK_KEYS: dict[str, str] = {
    "datetime_text": "datetime_text",
    "дата": "datetime_text",
    "datetime": "datetime_text",
    "operation": "operation",
    "операция": "operation",
    "recipient_name": "recipient_name",
    "получатель": "recipient_name",
    "фио_получателя": "recipient_name",
    "recipient_card": "recipient_card",
    "карта": "recipient_card",
    "карта_получателя": "recipient_card",
    "телефон": "recipient_card",
    "телефон_получателя": "recipient_card",
    "recipient_bank": "recipient_bank",
    "банк": "recipient_bank",
    "банк_получателя": "recipient_bank",
    "sender_name": "sender_name",
    "отправитель": "sender_name",
    "фио_отправителя": "sender_name",
    "sender_account": "sender_account",
    "счёт": "sender_account",
    "счет": "sender_account",
    "amount": "amount",
    "сумма": "amount",
    "fee": "fee",
    "комиссия": "fee",
    "document_number": "document_number",
    "номер_документа": "document_number",
    "номер": "document_number",
    "auth_code": "auth_code",
    "код": "auth_code",
    "код_авторизации": "auth_code",
    "receipt_number": "receipt_number",
    "квитанция": "receipt_number",
    "номер_квитанции": "receipt_number",
    "template": "template_id",
    "шаблон": "template_id",
}

_DEMO_BANNER = (
    "Бот выдаёт <b>демонстрационный PDF с водяным знаком ОБРАЗЕЦ</b>. "
    "Документ не является платёжным и не имеет юридической силы. "
    "Использование сгенерированных файлов для введения третьих лиц "
    "в заблуждение запрещено."
)


def _normalize_value(text: str) -> str:
    text = text.strip()
    return "" if text in {"-", "—", "_"} else text


def _allowed_user(user_id: int) -> bool:
    raw = os.getenv("ALLOWED_USER_IDS", "").strip()
    if not raw:
        return True
    allow = {int(x) for x in raw.replace(",", " ").split() if x.strip().isdigit()}
    return user_id in allow


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not _allowed_user(message.from_user.id):
        await message.answer("Бот ограничен списком пользователей.")
        return
    await message.answer(
        f"Привет! {_DEMO_BANNER}\n\n"
        "Команды:\n"
        "/new — заполнить чек по шагам\n"
        "/quick — отправить все поля одним сообщением\n"
        "/templates — список шаблонов\n"
        "/cancel — отменить текущее заполнение\n"
        "/help — справка"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        f"{_DEMO_BANNER}\n\n"
        "<b>Пошаговый режим:</b> /new — бот по очереди спросит каждое поле.\n\n"
        "<b>Быстрый режим:</b> /quick, потом одно сообщение в формате\n"
        "<code>дата: 5 апреля 2026 20:29:42 (МСК)\n"
        "шаблон: 2\n"
        "операция: Перевод клиенту\n"
        "получатель: Иван И.\n"
        "карта: **** 1234\n"
        "банк: Яндекс\n"
        "отправитель: Пётр П.\n"
        "счёт: **** 5678\n"
        "сумма: 259,00 ₽\n"
        "комиссия: 0,00 ₽\n"
        "номер: A6076160011783290G100300117\n"
        "код: 00117\n"
        "квитанция: № 1-127-176-643-532</code>\n\n"
        "Любое поле можно пропустить (просто не указывайте ключ или "
        "напишите «-»).\n\n"
        "<b>Шаблоны:</b> <code>1</code> — чек по операции, "
        "<code>2</code> — квитанция 17.03."
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено. /new — начать заново.")


def _template_prompt() -> str:
    return (
        "<b>Выберите шаблон:</b>\n"
        "<code>1</code> — чек по операции\n"
        "<code>2</code> — квитанция 17.03\n\n"
        "Отправьте цифру шаблона."
    )


@router.message(Command("templates"))
async def cmd_templates(message: Message) -> None:
    await message.answer(_template_prompt())


def _field_order_for_template(template_id: str) -> tuple[State, ...]:
    if template_id == TEMPLATE_17:
        return _FIELD_ORDER_FULL
    return _FIELD_ORDER_CLASSIC


def _next_state_for_template(current_state: str, template_id: str) -> State | None:
    states = _field_order_for_template(template_id)
    for i, state in enumerate(states):
        if state.state == current_state:
            return states[i + 1] if i + 1 < len(states) else None
    return None


def _prompt_for_state(state: State, template_id: str) -> str:
    if template_id != TEMPLATE_17:
        return _NEXT_PROMPT[state.state]
    field_name = _FIELD_BY_STATE[state.state]
    label, default = _TEMPLATE_17_FIELD_HINTS[field_name]
    states = _field_order_for_template(template_id)
    step_number = next(i for i, s in enumerate(states, start=1) if s.state == state.state)
    return (
        f"<b>Шаг {step_number}/{len(states)}.</b> {label}.\n"
        f"По умолчанию: <code>{default}</code>\n"
        "Отправьте новое значение или <code>-</code>, чтобы оставить как в образце."
    )


@router.message(Command("new"))
async def cmd_new(message: Message, state: FSMContext) -> None:
    if not _allowed_user(message.from_user.id):
        return
    await state.clear()
    await state.update_data(values={})
    await state.set_state(FillReceipt.template)
    await message.answer(_template_prompt())


async def _start_field_flow(
    message: Message,
    state: FSMContext,
    template_id: str,
) -> None:
    first_state = _field_order_for_template(template_id)[0]
    await state.update_data(template_id=template_id, values={})
    await state.set_state(first_state)
    await message.answer(
        f"Выбран: <b>{_TEMPLATE_NAMES[template_id]}</b>.\n\n"
        f"{_prompt_for_state(first_state, template_id)}"
    )


async def _handle_template_choice(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().lower()
    template_id = _TEMPLATE_CHOICES.get(text)
    if template_id is not None:
        await _start_field_flow(message, state, template_id)
        return

    # Compatibility: если после /new сразу отправили поле, считаем шаблоном классический
    first_state = _FIELD_ORDER_CLASSIC[0]
    next_state = _next_state_for_template(first_state.state, TEMPLATE_CLASSIC)
    values = {_FIELD_BY_STATE[first_state.state]: _normalize_value(message.text or "")}
    await state.update_data(template_id=TEMPLATE_CLASSIC, values=values)
    if next_state is None:
        await _finalize(message, state, values)
        return
    await state.set_state(next_state)
    await message.answer(_prompt_for_state(next_state, TEMPLATE_CLASSIC))


async def _handle_step(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None or current not in _FIELD_BY_STATE:
        return
    field_name = _FIELD_BY_STATE[current]
    data = await state.get_data()
    if data.get("quick_mode"):
        return
    values: dict[str, Any] = data.get("values", {})
    values[field_name] = _normalize_value(message.text or "")
    await state.update_data(values=values)

    template_id = data.get("template_id", TEMPLATE_CLASSIC)
    next_state = _next_state_for_template(current, template_id)
    if next_state is None:
        await _finalize(message, state, values)
        return
    await state.set_state(next_state)
    await message.answer(_prompt_for_state(next_state, template_id))


@router.message(Command("quick"))
async def cmd_quick(message: Message, state: FSMContext) -> None:
    if not _allowed_user(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "Отправьте одним сообщением поля в формате <code>ключ: значение</code> "
        "(каждое с новой строки). См. /help для примера. "
        "Любое поле можно пропустить. Шаблон можно указать так: "
        "<code>шаблон: 2</code>.\n\n"
        "Для номера квитанции используйте ключ <code>квитанция</code> или <code>номер_квитанции</code>."
    )
    await state.update_data(quick_mode=True)


async def _finalize(
    message: Message, state: FSMContext, values: dict[str, Any]
) -> None:
    state_data = await state.get_data()
    raw_template = values.pop("template_id", None) or state_data.get("template_id")
    template_id = _resolve_template_id(raw_template)
    pdf_bytes, filename = _render_template_pdf(values, template_id)
    await message.answer_document(
        BufferedInputFile(pdf_bytes, filename=filename),
        caption=(
            f"Готово: <b>{_TEMPLATE_NAMES[template_id]}</b>. "
            "Это <b>ОБРАЗЕЦ</b> — демонстрационный документ "
            "с водяным знаком. Не является платёжным документом."
        ),
    )
    await state.clear()


def _resolve_template_id(raw: str | None) -> str:
    if not raw:
        return TEMPLATE_CLASSIC
    return _TEMPLATE_CHOICES.get(raw.strip().lower(), TEMPLATE_CLASSIC)


def _render_template_pdf(values: dict[str, Any], template_id: str) -> tuple[bytes, str]:
    if template_id == TEMPLATE_17:
        defaults = Receipt17Data()
        amount = values.get("amount") or defaults.amount
        document_number = values.get("document_number") or defaults.operation_id_line_1
        auth_code = values.get("auth_code") or defaults.operation_id_line_2
        # НОВОЕ: номер квитанции берётся из отдельного поля
        receipt_number = values.get("receipt_number")
        if not receipt_number:
            # Если не задан, используем значение по умолчанию из шаблона
            receipt_number = defaults.receipt_number
        receipt = Receipt17Data(
            datetime_text=values.get("datetime_text") or defaults.datetime_text,
            total=amount,
            transfer_type=values.get("operation") or defaults.transfer_type,
            amount=amount,
            fee=values.get("fee") or defaults.fee,
            sender_name=values.get("sender_name") or defaults.sender_name,
            recipient_phone=values.get("recipient_card") or defaults.recipient_phone,
            recipient_name=values.get("recipient_name") or defaults.recipient_name,
            recipient_bank=values.get("recipient_bank") or defaults.recipient_bank,
            debit_account=values.get("sender_account") or defaults.debit_account,
            operation_id_line_1=document_number,
            operation_id_line_2=auth_code,
            receipt_number=receipt_number,
        )
        return render_receipt_17_pdf(receipt), "receipt-17-demo.pdf"

    receipt_values = {
        k: v for k, v in values.items() if k in _RECEIPT_DATA_FIELDS and v is not None
    }
    return render_receipt_pdf(ReceiptData(**receipt_values)), "receipt-demo.pdf"


def _parse_quick_message(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_line in text.splitlines():
        if ":" not in raw_line:
            continue
        key, _, value = raw_line.partition(":")
        key_norm = key.strip().lower().replace(" ", "_")
        if key_norm not in _QUICK_KEYS:
            continue
        field = _QUICK_KEYS[key_norm]
        normalized = _normalize_value(value)
        out[field] = normalized.lower() if field == "template_id" else normalized
    return out


@router.message(F.text)
async def fallback_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    current = await state.get_state()
    if current == FillReceipt.template.state:
        await _handle_template_choice(message, state)
        return
    if data.get("quick_mode"):
        parsed = _parse_quick_message(message.text or "")
        await _finalize(message, state, parsed)
        return
    if current in _FIELD_BY_STATE:
        await _handle_step(message, state)
        return
    await message.answer(
        "Не понял. Используйте /new для пошагового заполнения "
        "или /quick для быстрого ввода."
    )


async def main() -> None:
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit(
            "BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
        )
    logging.basicConfig(level=logging.INFO)
    proxy = os.getenv("TELEGRAM_PROXY", "").strip() or None
    session = AiohttpSession(proxy=proxy) if proxy else None
    if proxy:
        logger.info("Using Telegram proxy from TELEGRAM_PROXY")
    ca_file = os.getenv("TELEGRAM_CA_FILE", "").strip()
    verify_ssl = os.getenv("TELEGRAM_VERIFY_SSL", "1").strip().lower()
    if session is None and (ca_file or verify_ssl in {"0", "false", "no", "off"}):
        session = AiohttpSession()
    if session is not None and ca_file:
        session._connector_init["ssl"] = ssl.create_default_context(cafile=ca_file)
        logger.info("Using custom Telegram CA file from TELEGRAM_CA_FILE")
    elif session is not None and verify_ssl in {"0", "false", "no", "off"}:
        session._connector_init["ssl"] = False
        logger.warning("Telegram SSL verification is disabled by TELEGRAM_VERIFY_SSL")
    bot = Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    logger.info("Starting bot…")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())


__all__ = ["main", "router", "FillReceipt", "_parse_quick_message"]
