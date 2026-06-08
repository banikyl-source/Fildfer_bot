Шаблон для чеков Альфа-Банка в Telegram-боте:

  PROHOD_FIXED1.pdf   (основной, лежит в этой папке для BotHost/GitHub)

Запасные варианты: lauchj.pdf, test_patch.pdf

Переопределить путь в .env на BotHost (если нужно):

  ALFA_TEMPLATE_PDF=/путь/к/PROHOD_FIXED1.pdf

PDF_CHECKER_ROOT на BotHost не нужен — модули patch_alfa_amount.py
и font_extend.py лежат в vendor/ рядом с main.py.
