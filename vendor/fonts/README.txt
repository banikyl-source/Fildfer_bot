Шрифт Tahoma нужен для расширения subset-шрифта в PDF-чеках Альфа-Банка.

На Windows обычно берётся из C:\Windows\Fonts\tahoma.ttf автоматически.
На BotHost / Linux положите сюда копию:

  vendor/fonts/tahoma.ttf

Или задайте в .env:

  TAHOMA_TTF=/полный/путь/к/tahoma.ttf
