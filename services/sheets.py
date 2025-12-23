import asyncio
import logging
import os
import openpyxl
from openpyxl import Workbook
import yadisk
# Импортируем новые переменные
from config import YANDEX_TOKEN, EXCEL_FILE, YANDEX_DIR, REMOTE_PATH

logger = logging.getLogger(__name__)

file_lock = asyncio.Lock()
y = yadisk.YaDisk(token=YANDEX_TOKEN)

def _ensure_remote_dir_exists(client: yadisk.YaDisk, path: str):
    """
    Создает структуру папок на Яндекс.Диске, если её нет.
    Принимает путь вида '/Боты/Бот журнала'
    """
    parts = path.strip("/").split("/")
    current_path = ""
    
    for part in parts:
        current_path += f"/{part}"
        try:
            if not client.exists(current_path):
                client.mkdir(current_path)
                logger.info(f"📁 Создана папка на Диске: {current_path}")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось проверить/создать папку {current_path}: {e}")

def _process_subscription_sync(user_data: list):
    """Синхронная функция работы с файлами"""
    
    # --- 1. Локальное сохранение (без изменений) ---
    if not os.path.exists(EXCEL_FILE):
        wb = Workbook()
        ws = wb.active
        ws.append(["Дата", "User ID", "Username", "ФИО", "Адрес", "Телефон"])
        # Наводим красоту
        ws.column_dimensions['A'].width = 20
        ws.column_dimensions['C'].width = 20
        ws.column_dimensions['D'].width = 30
        ws.save(EXCEL_FILE)

    try:
        wb = openpyxl.load_workbook(EXCEL_FILE)
        ws = wb.active
        ws.append(user_data)
        wb.save(EXCEL_FILE)
        logger.info(f"💾 Заявка сохранена локально: {user_data[2]}")
    except PermissionError:
        logger.error("❌ Ошибка: Файл Excel открыт! Не могу записать.")
        raise IOError("Файл занят")

    # --- 2. Загрузка на Яндекс.Диск в папку ---
    try:
        if y.check_token():
            # Сначала проверяем/создаем папки
            _ensure_remote_dir_exists(y, YANDEX_DIR)
            
            # Загружаем по новому пути
            y.upload(EXCEL_FILE, REMOTE_PATH, overwrite=True)
            logger.info(f"☁️ Файл загружен в: {REMOTE_PATH}")
        else:
            logger.error("❌ Токен Яндекс.Диска протух")
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки на Яндекс: {e}")

async def add_subscription(user_data: list):
    async with file_lock:
        await asyncio.to_thread(_process_subscription_sync, user_data)