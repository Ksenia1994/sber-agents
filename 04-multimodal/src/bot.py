import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from handlers import router
from config import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    # Проверяем наличие обязательных переменных окружения
    if not config.TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не установлен в .env файле!")
        print("\n❌ Ошибка: TELEGRAM_TOKEN не установлен!")
        print("\n📝 Инструкция:")
        print("1. Откройте файл .env в корне проекта")
        print("2. Добавьте токен от @BotFather:")
        print("   TELEGRAM_TOKEN=ваш_токен_здесь")
        print("\n💡 Как получить токен:")
        print("   - Найдите @BotFather в Telegram")
        print("   - Отправьте /newbot и следуйте инструкциям")
        sys.exit(1)
    
    if not config.OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY не установлен в .env файле!")
        print("\n❌ Ошибка: OPENAI_API_KEY не установлен!")
        print("\n📝 Инструкция:")
        print("1. Откройте файл .env в корне проекта")
        print("2. Добавьте API ключ от OpenRouter:")
        print("   OPENAI_API_KEY=ваш_ключ_здесь")
        print("\n💡 Как получить ключ:")
        print("   - Зарегистрируйтесь на https://openrouter.ai/")
        print("   - Перейдите в раздел API Keys")
        print("   - Создайте новый ключ")
        sys.exit(1)
    
    if not config.MODEL_TEXT:
        logger.warning("MODEL_TEXT не установлен, будет использовано значение по умолчанию")
    
    if not config.MODEL_IMAGE:
        logger.warning("MODEL_IMAGE не установлен, обработка изображений может не работать")
    
    bot = Bot(token=config.TELEGRAM_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    
    logger.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

