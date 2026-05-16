import logging
import os
import json
from datetime import datetime
from typing import Any, Dict, List, Set, Optional

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
from receipt_pdf_bot.receipt_17_card_template import (
    Receipt17CardData,
    render_receipt_17_card_pdf,
)
from receipt_pdf_bot.receipt_alfa_template import (
    AlfaReceiptData,
    render_alfa_receipt_pdf,
)

logger = logging.getLogger(__name__)
router = Router()

# ---------- НАСТРОЙКИ ----------
ADMIN_ID = 7531804130  # замените на свой Telegram ID
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise SystemExit("BOT_TOKEN is not set.")

KEYS_FILE = "keys.txt"
ALLOWED_USERS_FILE = "allowed_users.json"
USED_KEYS_FILE = "used_keys.json"

# ---------- FSM ----------
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
    transfer_message = State()

class AdminActions(StatesGroup):
    waiting_for_new_key = State()
    waiting_for_delete_key = State()

TEMPLATE_CLASSIC = "classic"
TEMPLATE_17_PHONE = "tbank_phone"
TEMPLATE_17_CARD = "tbank_card"
TEMPLATE_ALFA = "alfa"

# ---------- ПОРЯДОК ПОЛЕЙ ДЛЯ КАЖДОГО ШАБЛОНА ----------
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
    FillReceipt.transfer_message.state: "transfer_message",
}

# СберБанк
_FIELD_ORDER_CLASSIC = (
    FillReceipt.datetime_text,
    FillReceipt.operation,
    FillReceipt.amount,
    FillReceipt.fee,
    FillReceipt.sender_name,
    FillReceipt.recipient_card,
    FillReceipt.recipient_name,
    FillReceipt.sender_account,
    FillReceipt.document_number,
    FillReceipt.auth_code,
    FillReceipt.receipt_number,
)

# Т-банк (по телефону)
_FIELD_ORDER_TBANK_PHONE = (
    FillReceipt.datetime_text,
    FillReceipt.operation,
    FillReceipt.amount,
    FillReceipt.fee,
    FillReceipt.sender_name,
    FillReceipt.recipient_card,
    FillReceipt.recipient_name,
    FillReceipt.recipient_bank,
    FillReceipt.sender_account,
    FillReceipt.document_number,
    FillReceipt.auth_code,
    FillReceipt.receipt_number,
)

# Т-банк (по карте) – только нужные поля, без счёта списания, номера операции и кода
_FIELD_ORDER_TBANK_CARD = (
    FillReceipt.datetime_text,
    FillReceipt.operation,
    FillReceipt.amount,
    FillReceipt.fee,
    FillReceipt.sender_name,
    FillReceipt.recipient_card,
    FillReceipt.recipient_name,
    FillReceipt.recipient_bank,
    FillReceipt.receipt_number,
)

# Альфа-Банк
_FIELD_ORDER_ALFA = (
    FillReceipt.datetime_text,
    FillReceipt.amount,
    FillReceipt.fee,
    FillReceipt.recipient_card,
    FillReceipt.recipient_bank,
    FillReceipt.sender_account,
    FillReceipt.document_number,
    FillReceipt.auth_code,
    FillReceipt.recipient_name,
    FillReceipt.transfer_message,
)

# Подсказки для Альфа-Банка
_ALFA_PROMPTS = {
    FillReceipt.datetime_text.state: "📅 Введите дату и время перевода (пример: 19.11.2025 20:21:45 мск):",
    FillReceipt.amount.state: "💰 Введите сумму перевода (пример: 26 200 RUR):",
    FillReceipt.fee.state: "💸 Введите комиссию (пример: 0 RUR):",
    FillReceipt.recipient_card.state: "📞 Введите номер телефона получателя (10 цифр без +):",
    FillReceipt.recipient_bank.state: "🏦 Введите банк получателя (пример: Т-Банк):",
    FillReceipt.sender_account.state: "💳 Введите счёт списания (пример: 40817810505905043078):",
    FillReceipt.document_number.state: "🔢 Введите номер операции (пример: C421911251260019):",
    FillReceipt.auth_code.state: "🆔 Введите идентификатор операции в СБП (длинный):",
    FillReceipt.recipient_name.state: "👤 Введите ФИО получателя:",
    FillReceipt.transfer_message.state: "✉️ Введите сообщение получателю (пример: Перевод денежных средств):",
}

# Общие подсказки для СберБанка и Т-банк (по телефону)
_NEXT_PROMPT = {
    FillReceipt.datetime_text.state: "<b>Шаг 1/11.</b> Введите дату и время операции.\nПример: <code>5 апреля 2026 20:29:42 (МСК)</code>",
    FillReceipt.operation.state: "<b>Шаг 2/11.</b> Название операции.\nПример: <code>Перевод клиенту</code>",
    FillReceipt.recipient_name.state: "<b>Шаг 3/11.</b> ФИО получателя.\nПример: <code>Даниил Андреевич З.</code>",
    FillReceipt.recipient_card.state: "<b>Шаг 4/11.</b> Карта или телефон получателя.\nПример: <code>**** 0264</code>",
    FillReceipt.recipient_bank.state: "<b>Шаг 5/11.</b> Банк получателя.\nПример: <code>Яндекс</code>",
    FillReceipt.sender_name.state: "<b>Шаг 5/11.</b> ФИО отправителя.\nПример: <code>Артём Анатольевич М.</code>",
    FillReceipt.sender_account.state: "<b>Шаг 6/11.</b> Счёт отправителя.\nПример: <code>**** 0220</code>",
    FillReceipt.amount.state: "<b>Шаг 7/11.</b> Сумма перевода.\nПример: <code>259,00 ₽</code>",
    FillReceipt.fee.state: "<b>Шаг 8/11.</b> Комиссия.\nПример: <code>0,00 ₽</code>",
    FillReceipt.document_number.state: "<b>Шаг 9/11.</b> Номер документа (идентификатор, первая строка).\nПример: <code>A6076160011783290G100300117</code>",
    FillReceipt.auth_code.state: "<b>Шаг 10/11.</b> Код авторизации (вторая строка).\nПример: <code>00117</code>",
    FillReceipt.receipt_number.state: "<b>Шаг 11/11.</b> Номер квитанции (отдельно от идентификатора).\nПример: <code>№ 1-127-176-643-532</code>",
}

# Подсказки для Т-банк (по карте) – убраны лишние шаги
_CARD_PROMPTS = {
    FillReceipt.datetime_text.state: "<b>Шаг 1/9.</b> Введите дату и время операции.\nПример: <code>5 апреля 2026 20:29:42 (МСК)</code>",
    FillReceipt.operation.state: "<b>Шаг 2/9.</b> Тип перевода (по умолчанию «По номеру карты»).\nОтправьте <code>-</code>, чтобы оставить по умолчанию.",
    FillReceipt.amount.state: "<b>Шаг 3/9.</b> Сумма перевода.\nПример: <code>259,00 ₽</code>",
    FillReceipt.fee.state: "<b>Шаг 4/9.</b> Комиссия.\nПример: <code>0,00 ₽</code>",
    FillReceipt.sender_name.state: "<b>Шаг 5/9.</b> ФИО отправителя.\nПример: <code>Михаил Видинеев</code>",
    FillReceipt.recipient_card.state: "<b>Шаг 6/9.</b> Номер карты получателя (16 цифр).\nПример: <code>220220******7357</code>",
    FillReceipt.recipient_name.state: "<b>Шаг 7/9.</b> ФИО получателя.\nПример: <code>Ильяс А.</code>",
    FillReceipt.recipient_bank.state: "<b>Шаг 8/9.</b> Банк получателя.\nПример: <code>Сбербанк</code>",
    FillReceipt.receipt_number.state: "<b>Шаг 9/9.</b> Номер квитанции.\nПример: <code>№ 1-127-176-643-532</code>",
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
    TEMPLATE_17_PHONE: "Т-банк (по телефону)",
    TEMPLATE_17_CARD: "Т-банк (по карте)",
    TEMPLATE_ALFA: "Альфа Банк",
}

_RECEIPT_DATA_FIELDS = set(ReceiptData.__dataclass_fields__)

# ---------- СИСТЕМА КЛЮЧЕЙ ----------
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

# ---------- КЛАВИАТУРЫ ----------
def get_main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    row = [KeyboardButton(text="💰 Чеки")]
    if is_admin:
        row.append(KeyboardButton(text="⚙️ Админ панель"))
    return ReplyKeyboardMarkup(keyboard=[row], resize_keyboard=True)

def get_banks_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="Т-банк"), KeyboardButton(text="СберБанк"), KeyboardButton(text="Альфа Банк")],
        [KeyboardButton(text="◀️ Назад в меню")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_tbank_variants_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📞 По номеру телефона"), KeyboardButton(text="💳 По номеру карты")],
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
    if template_id == TEMPLATE_17_PHONE:
        return _FIELD_ORDER_TBANK_PHONE
    if template_id == TEMPLATE_17_CARD:
        return _FIELD_ORDER_TBANK_CARD
    if template_id == TEMPLATE_ALFA:
        return _FIELD_ORDER_ALFA
    return _FIELD_ORDER_CLASSIC

def _next_state_for_template(current_state: str, template_id: str) -> Optional[State]:
    states = _field_order_for_template(template_id)
    for i, s in enumerate(states):
        if s.state == current_state:
            return states[i + 1] if i + 1 < len(states) else None
    return None

def _prompt_for_state(state: State, template_id: str) -> str:
    if template_id == TEMPLATE_ALFA:
        return _ALFA_PROMPTS.get(state.state, "Введите значение:")
    if template_id == TEMPLATE_17_CARD:
        return _CARD_PROMPTS.get(state.state, "Введите значение:")
    if template_id == TEMPLATE_17_PHONE:
        if state.state == FillReceipt.recipient_card.state:
            return "📞 Введите номер телефона получателя (10 цифр без +):"
        field_name = _FIELD_BY_STATE[state.state]
        label, default = _TEMPLATE_17_FIELD_HINTS[field_name]
        states = _field_order_for_template(template_id)
        step = next(i for i, s in enumerate(states, 1) if s.state == state.state)
        return (
            f"<b>Шаг {step}/{len(states)}.</b> {label}.\n"
            f"По умолчанию: <code>{default}</code>\n"
            "Отправьте новое значение или <code>-</code>, чтобы оставить как в образце."
        )
    # СберБанк
    return _NEXT_PROMPT.get(state.state, "Введите значение:")

def _resolve_template_id(raw: Optional[str]) -> str:
    if not raw:
        return TEMPLATE_CLASSIC
    if raw == "Т-банк (по телефону)" or raw == "📞 По номеру телефона":
        return TEMPLATE_17_PHONE
    if raw == "Т-банк (по карте)" or raw == "💳 По номеру карты":
        return TEMPLATE_17_CARD
    if "Альфа" in raw:
        return TEMPLATE_ALFA
    if "Сбер" in raw:
        return TEMPLATE_CLASSIC
    return TEMPLATE_CLASSIC

def _render_template_pdf(values: Dict[str, Any], template_id: str) -> tuple[bytes, str]:
    current_date = datetime.now().strftime("%d.%m.%Y")
    if template_id == TEMPLATE_17_PHONE:
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
        return render_receipt_17_pdf(receipt), f"receipt_{current_date}.pdf"
    elif template_id == TEMPLATE_17_CARD:
        defaults = Receipt17CardData()
        amount = values.get("amount") or defaults.amount
        receipt_num = values.get("receipt_number") or defaults.receipt_number
        receipt = Receipt17CardData(
            datetime_text=values.get("datetime_text") or defaults.datetime_text,
            total=amount,
            transfer_type=values.get("operation") or defaults.transfer_type,
            status=values.get("status") or defaults.status,
            amount=amount,
            fee=values.get("fee") or defaults.fee,
            sender_name=values.get("sender_name") or defaults.sender_name,
            recipient_card=values.get("recipient_card") or defaults.recipient_card,
            recipient_name=values.get("recipient_name") or defaults.recipient_name,
            recipient_bank=values.get("recipient_bank") or defaults.recipient_bank,
            receipt_number=receipt_num,
        )
        return render_receipt_17_card_pdf(receipt), f"receipt_card_{current_date}.pdf"
    elif template_id == TEMPLATE_ALFA:
        alfa_data = AlfaReceiptData(
            datetime_text=values.get("datetime_text") or "19.11.2025 20:21:45 мск",
            amount=values.get("amount") or "26 200 RUR",
            recipient_phone=values.get("recipient_card") or "79273364000",
            fee=values.get("fee") or "0 RUR",
            recipient_bank=values.get("recipient_bank") or "Т-Банк",
            sender_account=values.get("sender_account") or "40817810505905043078",
            operation_number=values.get("document_number") or "C421911251260019",
            sbp_id=values.get("auth_code") or "A5323172126061020000020011640104",
            recipient_name=values.get("recipient_name") or "Роман Павлович Б",
            transfer_message=values.get("transfer_message") or "Перевод денежных средств",
        )
        return render_alfa_receipt_pdf(alfa_data), f"alfa_receipt_{current_date}.pdf"
    else:
        receipt_values = {k: v for k, v in values.items() if k in _RECEIPT_DATA_FIELDS and v}
        return render_receipt_pdf(ReceiptData(**receipt_values)), f"receipt_{current_date}.pdf"

# ---------- ОСНОВНЫЕ ХЕНДЛЕРЫ ----------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    if is_allowed(user_id):
        is_admin = (user_id == ADMIN_ID)
        await message.answer("👋 Добро пожаловать!", reply_markup=get_main_keyboard(is_admin))
    else:
        await message.answer(
            "🔐 Доступ ограничен. Введите лицензионный ключ.\nЕсли у вас нет ключа, обратитесь к администратору."
        )

@router.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text.strip()
    username = message.from_user.username or "no_username"

    # ---------- НЕ АВТОРИЗОВАН ----------
    if not is_allowed(user_id):
        if text in VALID_KEYS:
            if consume_key(text, user_id, username):
                allow_user(user_id)
                is_admin = (user_id == ADMIN_ID)
                await message.answer("✅ Ключ принят! Добро пожаловать.", reply_markup=get_main_keyboard(is_admin))
            else:
                await message.answer("❌ Ошибка активации ключа.")
        else:
            await message.answer("❌ Неверный или уже использованный ключ.")
        return

    # ---------- АДМИН-ДЕЙСТВИЯ (ожидание ввода) ----------
    current_admin_state = await state.get_state()
    if current_admin_state == AdminActions.waiting_for_new_key.state:
        new_key = text
        if new_key in VALID_KEYS:
            await message.answer("❌ Такой ключ уже существует.")
        else:
            VALID_KEYS.add(new_key)
            save_keys(VALID_KEYS)
            await message.answer(f"✅ Ключ `{new_key}` добавлен.", parse_mode="Markdown")
        await state.clear()
        await message.answer("·", reply_markup=get_admin_keyboard())
        return

    if current_admin_state == AdminActions.waiting_for_delete_key.state:
        key_to_del = text
        if delete_key_by_admin(key_to_del):
            await message.answer(f"✅ Ключ `{key_to_del}` удалён из активных.", parse_mode="Markdown")
        else:
            await message.answer(f"❌ Ключ `{key_to_del}` не найден.", parse_mode="Markdown")
        await state.clear()
        await message.answer("·", reply_markup=get_admin_keyboard())
        return

    # ---------- КНОПКИ МЕНЮ ----------
    if text == "💰 Чеки":
        await state.clear()
        await message.answer("·", reply_markup=get_banks_keyboard())
        return

    if text == "Т-банк":
        await state.clear()
        await message.answer("Выберите тип перевода:", reply_markup=get_tbank_variants_keyboard())
        return

    if text in ("📞 По номеру телефона", "💳 По номеру карты"):
        if "телефона" in text:
            template_id = TEMPLATE_17_PHONE
            template_name = "Т-банк (по телефону)"
        else:
            template_id = TEMPLATE_17_CARD
            template_name = "Т-банк (по карте)"
        await state.clear()
        await state.update_data(template_id=template_id, values={})
        first_state = _field_order_for_template(template_id)[0]
        await state.set_state(first_state)
        await message.answer(
            f"Выбран: <b>{template_name}</b>\n\n{_prompt_for_state(first_state, template_id)}",
            parse_mode="HTML",
            reply_markup=get_cancel_keyboard()
        )
        return

    if text == "⚙️ Админ панель" and user_id == ADMIN_ID:
        await state.clear()
        await message.answer("·", reply_markup=get_admin_keyboard())
        return

    if text == "◀️ Назад в меню":
        await state.clear()
        is_admin = (user_id == ADMIN_ID)
        await message.answer("·", reply_markup=get_main_keyboard(is_admin))
        return

    if text in ("СберБанк", "Альфа Банк"):
        if "Сбер" in text:
            template_id = TEMPLATE_CLASSIC
        else:
            template_id = TEMPLATE_ALFA
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
        await message.answer("·", reply_markup=get_main_keyboard(is_admin))
        return

    # ---------- АДМИН-КНОПКИ (без перехода в состояние) ----------
    if text == "➕ Добавить ключ" and user_id == ADMIN_ID:
        await state.set_state(AdminActions.waiting_for_new_key)
        await message.answer("Введите новый ключ (любое слово).\nОтправьте текст, и он станет ключом:")
        return

    if text == "🗑 Удалить ключ" and user_id == ADMIN_ID:
        await state.set_state(AdminActions.waiting_for_delete_key)
        await message.answer("Введите ключ, который хотите удалить из активных:")
        return

    if text == "📋 Список активных ключей" and user_id == ADMIN_ID:
        if not VALID_KEYS:
            await message.answer("📭 Активных ключей нет.")
        else:
            await message.answer("📋 Активные ключи:\n" + "\n".join(VALID_KEYS))
        return

    if text == "📜 История использованных" and user_id == ADMIN_ID:
        used = load_used_keys()
        if not used:
            await message.answer("📭 История пуста.")
            return
        hist_text = "📜 Последние 20 использованных ключей:\n"
        for item in used[-20:]:
            hist_text += f"🔑 {item['key']} — @{item['username']} ({item['user_id']}) — {item['timestamp']}\n"
        await message.answer(hist_text[:4000])
        return

    if text == "🔄 Сбросить всех пользователей" and user_id == ADMIN_ID:
        reset_all_users()
        await message.answer("✅ Список пользователей сброшен.")
        return

    # ---------- FSM ДЛЯ ЗАПОЛНЕНИЯ ЧЕКА ----------
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
            pdf_bytes, filename = _render_template_pdf(values, template_id)
            await message.answer_document(
                BufferedInputFile(pdf_bytes, filename=filename),
                caption=f"✅ Готово: <b>{_TEMPLATE_NAMES.get(template_id, 'Чек')}</b>"
            )
            await state.clear()
            is_admin = (user_id == ADMIN_ID)
            await message.answer("·", reply_markup=get_main_keyboard(is_admin))
        else:
            await state.set_state(next_state)
            await message.answer(
                _prompt_for_state(next_state, template_id),
                parse_mode="HTML",
                reply_markup=get_cancel_keyboard()
            )
        return

    # ---------- НЕИЗВЕСТНАЯ КОМАНДА ----------
    await message.answer("Используйте кнопки меню.")

# ---------- ЗАПУСК ----------
async def main() -> None:
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN is not set.")
    logging.basicConfig(level=logging.INFO)
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
