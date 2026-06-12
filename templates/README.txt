Шаблоны для Telegram-бота (patch_alfa_amount, onlypdf_robot).

  PROHOD_FIXED1.pdf      — СБП (~73 КБ)
  PROHOD_CARD_FIXED1.pdf — карта на карту (PDF Document.pdf, ~56 КБ)
  PROHOD_ACCOUNT.pdf     — перевод на счёт в другой банк (PDF.pdf, ~46 КБ, цифры 0–9)

Карта→карта: PROHOD_CARD_FIXED1.pdf — эталон с bot-pass FontFile2 (MD5 06867142…).
Собрать/обновить из PDF Document.pdf:
  python patch_alfa_amount.py PDF Document.pdf --fix-card-template -o PROHOD_CARD_FIXED1.pdf
(копирует шрифт с эталона: «8» рисуется восьмёркой, не «C»; onlypdf_robot принимает чек).

Починить уже сгенерированный чек с «C» вместо «8»:
  python patch_alfa_amount.py битый_чек.pdf --fix-card-template -o чек_fixed.pdf

Перевод на счёт: PROHOD_ACCOUNT.pdf — оригинал PDF.pdf (~46 КБ, VQWVIK+Tahoma, цифры 0–9).
