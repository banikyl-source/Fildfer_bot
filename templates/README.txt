Шаблоны для чеков Альфа-Банка в Telegram-боте:

  PROHOD_FIXED1.pdf      — СБП (по номеру телефона)
  PROHOD_CARD_FIXED1.pdf — карта на карту (копия PDF Document.pdf, ~56 КБ)

Исходник карта→карта: PDF Document.pdf на рабочем столе.
Для бота нужен оригинальный subset (~48 символов в CMap), НЕ alfa_card_fullfont.pdf.
Fullfont (alfa_card_fullfont.pdf) — только для локальных тестов, бот пишет «чек не распознан».

Переопределить в .env на BotHost (если нужно):

  ALFA_TEMPLATE_PDF=/путь/к/PROHOD_FIXED1.pdf
  ALFA_CARD_TEMPLATE_PDF=/путь/к/PROHOD_CARD_FIXED1.pdf

PDF_CHECKER_ROOT на BotHost не нужен — модули patch_alfa_amount.py
и font_extend.py лежат в vendor/ рядом с main.py.
