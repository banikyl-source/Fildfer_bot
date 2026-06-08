Шаблон для чеков Альфа-Банка в Telegram-боте:

  PROHOD_FIXED1.pdf   (основной, на рабочем столе)

Запасные варианты: lauchj.pdf, test_patch.pdf

Переопределить пути в .env:

  PDF_CHECKER_ROOT=C:\путь\к\pdf-checker
  ALFA_TEMPLATE_PDF=C:\путь\к\PROHOD_FIXED1.pdf

PDF_CHECKER_ROOT — папка с patch_alfa_amount.py (нужна для сборки Альфа-чека).
Если бот лежит внутри pdf-checker, переменная не обязательна.
