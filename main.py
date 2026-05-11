import sys
from pathlib import Path

# Добавляем папку src в путь поиска модулей
sys.path.insert(0, str(Path(__file__).parent / "src"))

from receipt_pdf_bot.bot import main

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
