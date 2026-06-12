Шаблоны для Telegram-бота (patch_alfa_amount, onlypdf_robot).

  PROHOD_FIXED1.pdf      — СБП (~73 КБ)
  PROHOD_CARD_FIXED1.pdf — карта на карту (PDF Document.pdf, ~56 КБ)
  PROHOD_ACCOUNT.pdf     — перевод на счёт в другой банк (PDF.pdf, ~46 КБ, цифры 0–9)

Карта→карта: PROHOD_CARD_FIXED1.pdf собран из PDF Document.pdf через
  python patch_alfa_amount.py PDF Document.pdf --fix-card-template -o PROHOD_CARD_FIXED1.pdf
(добавляет «8» только в ToUnicode CMap, FontFile2 не меняется — MD5 как у оригинала).
Суммы с «8» проходят бота. Не перезаписывайте глифы в subset — бот сверяет MD5 шрифта.

Перевод на счёт: PROHOD_ACCOUNT.pdf — оригинал PDF.pdf (~46 КБ, VQWVIK+Tahoma, цифры 0–9).
