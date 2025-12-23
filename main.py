# main.py
import sys
import asyncio
import logging

# 1. Моментальное сообщение, чтобы не смотреть в черный экран
print("⏳ Загрузка библиотек и конфигурации...", end=" ", flush=True)

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramUnauthorizedError
import yadisk

# Импорт конфигурации
from config import BOT_TOKEN, YANDEX_TOKEN, ADMIN_IDS

# Импорт обработчиков
# fsm_engine - наш новый движок с YAML
# common - технические команды типа /id (если файла нет, удалите эту строку)
from handlers import fsm_engine, common 

print("✅ Готово.")

async def main():
    # Настраиваем запись логов сразу в файл с правильной кодировкой
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        # Пишем сразу в файл, минуя консоль NSSM
        filename="bot_log_internal.log",
        filemode="a",
        encoding="utf-8" 
    )
    # Дублируем в консоль (чтобы NSSM тоже видел, если нужно), но с обработкой ошибок
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    # Если консоль Windows не умеет в эмодзи, заменяем их, а не падаем
    console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logging.getLogger('').addHandler(console)
    logger = logging.getLogger(__name__)
    
    logger.info("🚀 Старт системы...")

    # 3. Проверка Яндекс.Диска (с таймаутом, чтобы не висело вечно)
    logger.info("📡 Проверка Яндекс.Диска...")
    try:
        y = yadisk.YaDisk(token=YANDEX_TOKEN)
        # Ждем ответ от Яндекса максимум 10 секунд
        is_valid = await asyncio.wait_for(
            asyncio.to_thread(y.check_token), 
            timeout=10.0
        )
        
        if is_valid:
            logger.info("✅ Яндекс.Диск успешно подключен.")
        else:
            logger.critical("❌ Токен Яндекс.Диска недействителен (просрочен или отозван).")
            sys.exit(1)
            
    except asyncio.TimeoutError:
        logger.critical("❌ Таймаут соединения с Яндексом. Проверьте интернет или VPN.")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"❌ Ошибка подключения к Яндексу: {e}")
        sys.exit(1)

    # 4. Инициализация Телеграм-бота
    logger.info("📡 Подключение к Telegram...")
    try:
        bot = Bot(token=BOT_TOKEN)
        dp = Dispatcher()
        
        # --- РЕГИСТРАЦИЯ РОУТЕРОВ ---
        # Сначала регистрируем технические команды (/id)
        # Если вы не создавали common.py, закомментируйте строку ниже
        dp.include_router(common.router)
        
        # Затем регистрируем основной движок FSM (анкета)
        dp.include_router(fsm_engine.router)
        # ---------------------------

        # Проверка авторизации бота
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот авторизован: @{bot_info.username} (ID: {bot_info.id})")
        
        # Информация об админах
        if not ADMIN_IDS:
            logger.warning("⚠️ Список админов пуст! Команды администратора недоступны.")
            logger.warning("ℹ️ Напишите боту /id чтобы узнать свой ID и добавить его в .env")
        else:
            logger.info(f"👮 Загружено администраторов: {len(ADMIN_IDS)}")

        logger.info("🟢 Бот запущен и ждет сообщений (Polling)...")
        
        # Удаляем вебхуки (если вдруг были) и запускаем прослушку
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)

    except TelegramUnauthorizedError:
        logger.critical("❌ Ошибка авторизации Telegram. Проверьте BOT_TOKEN в файле .env")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"❌ Критическая ошибка при запуске: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    try:
        # Специфичное лечение для Windows (Fix "Event loop is closed")
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        asyncio.run(main())
        
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем (Ctrl+C).")