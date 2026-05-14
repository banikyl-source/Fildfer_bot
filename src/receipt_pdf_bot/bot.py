import logging
import os
import json
import ssl
from datetime import datetime
from typing import Any, Dict, List, Set, Optional
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from dotenv import load_dotenv

from receipt_pdf_bot.receipt import ReceiptData, render_receipt_pdf
from receipt_pdf_bot.receipt_17_03_2026_template import (
    Receipt17Data,
    render_receipt_17_pdf,
)

logger = logging.getLogger(__name__)
router = Router()

# ---------- НАСТРОЙКИ ----------
ADMIN_ID = 7531804130  # замените на ваш ID
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise SystemExit("BOT_TOKEN is not set.")

KEYS_FILE = "keys.txt"
ALLOWED_USERS_FILE = "allowed_users.json"
USED_KEYS_FILE = "used_keys.json"

# ---------- FSM (полностью как у вас) ----------
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
    receipt_number = State()

TEMPLATE_CLASSIC = "classic"
TEMPLATE_17 = "receipt_17"

# ---------- ПОЛЯ И ПОРЯДОК ШАГОВ ----------
_FIELD_BY_STATE = {
    FillReceipt.template.state: "template_id",
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
    FillReceipt.receipt_number,
)

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
    FillReceipt.receipt_number,
)

_NEXT_PROMPT = {
    FillReceipt.datetime_text.state: "<b>Шаг 1/11.</b> Введите дату и время операции.\nПример: <code>5 апреля 2026 20:29:42 (МСК)</code>",
    FillReceipt.operation.state: "<b>Шаг 2/11.</b> Название операции.\nПример: <code>Перевод клиенту</code>",
    FillReceipt.recipient_name.state: "<b>Шаг 3/11.</b> ФИО получателя.\nПример: <code>Даниил Андреевич З.</code>",
    FillReceipt.recipient_card.state: "<b>Шаг 4/11.</b> Карта или телефон получателя.\nПример: <code>**** 0264</code>",
    FillReceipt.recipient_bank.state: "<b>Шаг 5/11.</b> Банк получателя (только для шаблона Т-банк).\nПример: <code>Яндекс</code>",
    FillReceipt.sender_name.state: "<b>Шаг 5/11.</b> ФИО отправителя.\nПример: <code>Артём Анатольевич М.</code>",
    FillReceipt.sender_account.state: "<b>Шаг 6/11.</b> Счёт отправителя.\nПример: <code>**** 0220</code>",
    FillReceipt.amount.state: "<b>Шаг 7/11.</b> Сумма перевода.\nПример: <code>259,00 ₽</code>",
    FillReceipt.fee.state: "<b>Шаг 8/11.</b> Комиссия.\nПример: <code>0,00 ₽</code>",
    FillReceipt.document_number.state: "<b>Шаг 9/11.</b> Номер документа (идентификатор, первая строка).\nПример: <code>A6076160011783290G100300117</code>",
    FillReceipt.auth_code.state: "<b>Шаг 10/11.</b> Код авторизации (вторая строка).\nПример: <code>00117</code>",
    FillReceipt.receipt_number.state: "<b>Шаг 11/11.</b> Номер квитанции (отдельно от идентификатора).\nПример: <code>№ 1-127-176-643-532</code>",
}

_TEMPLATE_17_DEFAULTS = Receipt17Data()
_TEMPLATE_17_FIELD_HINTS = {
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

_TEMPLATE_NAMES = {
    TEMPLATE_CLASSIC: "СберБанк",
    TEMPLATE_17: "Т-банк",
}

_RECEIPT_DATA_FIELDS = set(ReceiptData.__dataclass_fields__)

# ---------- СИСТЕМА КЛЮЧЕЙ И ПОЛЬЗОВАТЕЛЕЙ ----------
def load_keys() -> Set[str]:
    if not os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, "w") as f:
            f.write("DEMO123\n")
    with open(KEYS_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())

def save_keys(keys_set: Set[str]) -> None:
    with open(KEYS_FILE, "w") as f:
        for key in keys_set:
            f.write(key + "\n")

def load_used_keys() -> List[Dict]:
    if os.path.exists(USED_KEYS_FILE):
        with open(USED_KEYS_FILE, "r") as f:
            return json.load(f)
    return []

def save_used_keys(used_list: List[Dict]) -> None:
    with open(USED_KEYS_FILE, "w") as f:
        json.dump(used_list, f, indent=2, ensure_ascii=False)

def add_used_key(key: str, user_id: int, username: str) -> None:
    used = load_used_keys()
    used.append({
        "key": key,
        "user_id": user_id,
        "username": username,
        "timestamp": datetime.now().isoformat()
    })
    save_used_keys(used)

def consume_key(key: str, user_id: int, username: str) -> bool:
    global VALID_KEYS
    if key in VALID_KEYS:
        VALID_KEYS.remove(key)
        save_keys(VALID_KEYS)
        add_used_key(key, user_id, username)
        return True
    return False

def delete_key_by_admin(key: str) -> bool:
    global VALID_KEYS
    if key in VALID_KEYS:
        VALID_KEYS.remove(key)
        save_keys(VALID_KEYS)
        return True
    return False

def load_allowed_users() -> Set[str]:
    if os.path.exists(ALLOWED_USERS_FILE):
        with open(ALLOWED_USERS_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_allowed_users(users: Set[str]) -> None:
    with open(ALLOWED_USERS_FILE, "w") as f:
        json.dump(list(users), f)

def is_allowed(user_id: int) -> bool:
    return str(user_id) in allowed_users

def allow_user(user_id: int) -> None:
    allowed_users.add(str(user_id))
    save_allowed_users(allowed_users)

def reset_all_users() -> None:
    allowed_users.clear()
    save_allowed_users(allowed_users)

VALID_KEYS = load_keys()
allowed_users = load_allowed_users()

# ---------- КЛАВИАТУРЫ (НОВЫЕ) ----------
def get_main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    # Чеки и Админ панель в одной строке
    row = [KeyboardButton(text="💰 Чеки")]
    if is_admin:
        row.append(KeyboardButton(text="⚙️ Админ панель"))
    return ReplyKeyboardMarkup(keyboard=[row], resize_keyboard=True)

def get_banks_keyboard() -> ReplyKeyboardMarkup:
    # Т-банк и СберБанк в одной строке, кнопка "Назад" отдельно
    buttons = [
        [KeyboardButton(text="Т-банк 🏦"), KeyboardButton(text="СберБанк 🏦")],
        [KeyboardButton(text="◀️ Назад в меню")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🔄 Сбросить всех пользователей")],
        [KeyboardButton(text="➕ Добавить ключ"), KeyboardButton(text="🗑 Удалить ключ")],
        [KeyboardButton(text="📋 Список активных ключей"), KeyboardButton(text="📜 История использованных")],
        [KeyboardButton(text="◀️ Назад в меню")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отменить заполнение")]],
        resize_keyboard=True
    )

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def _normalize_value(text: str) -> str:
    text = text.strip()
    return "" if text in {"-", "—", "_"} else text

def _field_order_for_template(template_id: str):
    return _FIELD_ORDER_FULL if template_id == TEMPLATE_17 else _FIELD_ORDER_CLASSIC

def _next_state_for_template(current_state: str, template_id: str) -> Optional[State]:
    states = _field_order_for_template(template_id)
    for i, s in enumerate(states):
        if s.state == current_state:
            return states[i + 1] if i + 1 < len(states) else None
    return None

def _prompt_for_state(state: State, template_id: str) -> str:
    if template_id != TEMPLATE_17:
        return _NEXT_PROMPT[state.state]
    field_name = _FIELD_BY_STATE[state.state]
    label, default = _TEMPLATE_17_FIELD_HINTS[field_name]
    states = _field_order_for_template(template_id)
    step = next(i for i, s in enumerate(states, 1) if s.state == state.state)
    return (
        f"<b>Шаг {step}/{len(states)}.</b> {label}.\n"
        f"По умолчанию: <code>{default}</code>\n"
        "Отправьте новое значение или <code>-</code>, чтобы оставить как в образце."
    )

def _resolve_template_id(raw: Optional[str]) -> str:
    if not raw:
        return TEMPLATE_CLASSIC
    # сопоставляем названия кнопок
    if "Т-банк" in raw:
        return TEMPLATE_17
    if "СберБанк" in raw:
        return TEMPLATE_CLASSIC
    return TEMPLATE_CLASSIC

def _render_template_pdf(values: Dict[str, Any], template_id: str) -> tuple[bytes, str]:
    if template_id == TEMPLATE_17:
        defaults = Receipt17Data()
        amount = values.get("amount") or defaults.amount
        doc_num = values.get("document_number") or defaults.operation_id_line_1
        auth = values.get("auth_code") or defaults.operation_id_line_2
        receipt_num = values.get("receipt_number") or defaults.receipt_number
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
            operation_id_line_1=doc_num,
            operation_id_line_2=auth,
            receipt_number=receipt_num,
        )
        return render_receipt_17_pdf(receipt), "receipt-tbank.pdf"
    # classic
    receipt_values = {k: v for k, v in values.items() if k in _RECEIPT_DATA_FIELDS and v}
    return render_receipt_pdf(ReceiptData(**receipt_values)), "receipt-sberbank.pdf"

# ---------- ОСНОВНЫЕ ХЕНДЛЕРЫ ----------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    if is_allowed(user_id):
        is_admin = (user_id == ADMIN_ID)
        await message.answer(
            "👋 Добро пожаловать!\nВыберите действие:",
            reply_markup=get_main_keyboard(is_admin)
        )
    else:
        await message.answer(
            "🔐 Доступ ограничен. Введите лицензионный ключ.\nЕсли у вас нет ключа, обратитесь к администратору."
        )

# Обработка текста для авторизации по ключу
@router.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text.strip()
    username = message.from_user.username or "no_username"

    # Если не авторизован – проверяем ключ
    if not is_allowed(user_id):
        if text in VALID_KEYS:
            if consume_key(text, user_id, username):
                allow_user(user_id)
                await message.answer("✅ Ключ принят! Добро пожаловать.")
                is_admin = (user_id == ADMIN_ID)
                await message.answer("Главное меню:", reply_markup=get_main_keyboard(is_admin))
            else:
                await message.answer("❌ Ошибка активации ключа.")
        else:
            await message.answer("❌ Неверный или уже использованный ключ.")
        return

    # Авторизован – обрабатываем кнопки
    if text == "💰 Чеки":
        await state.clear()
        await message.answer("Выберите банк:", reply_markup=get_banks_keyboard())
        return

    if text == "⚙️ Админ панель" and user_id == ADMIN_ID:
        await state.clear()
        await message.answer("Админ-панель:", reply_markup=get_admin_keyboard())
        return

    if text == "◀️ Назад в меню":
        await state.clear()
        is_admin = (user_id == ADMIN_ID)
        await message.answer("Главное меню:", reply_markup=get_main_keyboard(is_admin))
        return

    if text in ("Т-банк 🏦", "СберБанк 🏦"):
        # Определяем шаблон
        if "Т-банк" in text:
            template_id = TEMPLATE_17
        else:
            template_id = TEMPLATE_CLASSIC
        await state.clear()
        await state.update_data(template_id=template_id, values={})
        first_state = _field_order_for_template(template_id)[0]
        await state.set_state(first_state)
        await message.answer(
            f"Выбран: <b>{_TEMPLATE_NAMES[template_id]}</b>\n\n{_prompt_for_state(first_state, template_id)}",
            parse_mode="HTML",
            reply_markup=get_cancel_keyboard()
        )
        return

    if text == "❌ Отменить заполнение":
        await state.clear()
        is_admin = (user_id == ADMIN_ID)
        await message.answer("Заполнение отменено.", reply_markup=get_main_keyboard(is_admin))
        return

    # Обработка шагов FSM (если есть активное состояние)
    current_state = await state.get_state()
    if current_state and current_state in _FIELD_BY_STATE:
        data = await state.get_data()
        field_name = _FIELD_BY_STATE[current_state]
        values = data.get("values", {})
        values[field_name] = _normalize_value(text)
        await state.update_data(values=values)
        template_id = data.get("template_id", TEMPLATE_CLASSIC)
        next_state = _next_state_for_template(current_state, template_id)
        if next_state is None:
            # финализация
            pdf_bytes, filename = _render_template_pdf(values, template_id)
            await message.answer_document(
                BufferedInputFile(pdf_bytes, filename=filename),
                caption=f"✅ Готово: <b>{_TEMPLATE_NAMES[template_id]}</b>\nДемонстрационный документ."
            )
            await state.clear()
            is_admin = (user_id == ADMIN_ID)
            await message.answer("Что дальше?", reply_markup=get_main_keyboard(is_admin))
        else:
            await state.set_state(next_state)
            await message.answer(
                _prompt_for_state(next_state, template_id),
                parse_mode="HTML",
                reply_markup=get_cancel_keyboard()
            )
        return

    # Если ничего не подошло
    await message.answer("Используйте кнопки меню.")

# ---------- АДМИНСКИЕ ФУНКЦИИ ----------
@router.message(F.text == "🔄 Сбросить всех пользователей")
async def reset_all_users_button(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    reset_all_users()
    await message.answer("✅ Список пользователей сброшен.", reply_markup=get_admin_keyboard())

@router.message(F.text == "➕ Добавить ключ")
async def add_key_prompt(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Введите новый ключ (одной строкой):")
    # Тут нужно дождаться ответа (используем простой подход с состоянием)
    # Для простоты используем следующий шаг, сохраняя состояние
    await router.wait_for("message", check=lambda m: m.chat.id == message.chat.id, on_received=add_new_key)

async def add_new_key(message: Message):
    key = message.text.strip()
    if not key:
        await message.answer("❌ Пустой ключ.")
    elif key in VALID_KEYS:
        await message.answer("❌ Такой ключ уже существует.")
    else:
        VALID_KEYS.add(key)
        save_keys(VALID_KEYS)
        await message.answer(f"✅ Ключ `{key}` добавлен.", parse_mode="Markdown")
    await message.answer("Админ-панель:", reply_markup=get_admin_keyboard())

@router.message(F.text == "🗑 Удалить ключ")
async def delete_key_prompt(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Введите ключ, который хотите удалить:")
    await router.wait_for("message", check=lambda m: m.chat.id == message.chat.id, on_received=delete_key_step)

async def delete_key_step(message: Message):
    key = message.text.strip()
    if delete_key_by_admin(key):
        await message.answer(f"✅ Ключ `{key}` удалён из активных.", parse_mode="Markdown")
    else:
        await message.answer(f"❌ Ключ `{key}` не найден.", parse_mode="Markdown")
    await message.answer("Админ-панель:", reply_markup=get_admin_keyboard())

@router.message(F.text == "📋 Список активных ключей")
async def active_keys_list(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    if not VALID_KEYS:
        await message.answer("📭 Активных ключей нет.")
    else:
        await message.answer("📋 Активные ключи:\n" + "\n".join(VALID_KEYS))

@router.message(F.text == "📜 История использованных")
async def used_keys_history(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    used = load_used_keys()
    if not used:
        await message.answer("📭 История пуста.")
        return
    text = "📜 Последние 20 использованных ключей:\n"
    for item in used[-20:]:
        text += f"🔑 {item['key']} — @{item['username']} ({item['user_id']}) — {item['timestamp']}\n"
    await message.answer(text[:4000])

# ---------- ЗАПУСК ----------
async def main() -> None:
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN is not set.")
    logging.basicConfig(level=logging.INFO)
    # Настройка прокси (опционально)
    proxy = os.getenv("TELEGRAM_PROXY", "").strip() or None
    session = AiohttpSession(proxy=proxy) if proxy else None
    bot = Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
