import asyncio
import logging
import os
import openpyxl
from openpyxl import Workbook
import yadisk
from yadisk.exceptions import LockedError
from config import YANDEX_TOKEN, EXCEL_FILE, YANDEX_DIR, REMOTE_PATH_SUBS

logger = logging.getLogger(__name__)

file_lock = asyncio.Lock()

# Инициализация клиента
try:
    y = yadisk.YaDisk(token=YANDEX_TOKEN)
except Exception as e:
    logger.critical(f"Ошибка инициализации Yadisk: {e}")
    y = None

class CloudUploadError(Exception):
    """Кастомная ошибка для уведомления админов"""
    pass

def _ensure_remote_dir_exists(client: yadisk.YaDisk, path: str):
    parts = path.strip("/").split("/")
    current_path = ""
    for part in parts:
        current_path += f"/{part}"
        try:
            if not client.exists(current_path):
                client.mkdir(current_path)
        except Exception:
            pass

def _set_column_widths(ws):
    """Настраивает красивую ширину колонок"""
    # Словарь: {Буква: Ширина}
    widths = {
        'A': 18, # Дата (2025-12-25 15:00)
        'B': 15, # User ID
        'C': 20, # Username
        'D': 20, # Тип подписки
        'E': 35, # ФИО (пошире)
        'F': 50, # Адрес / Способ (самое широкое)
        'G': 18, # Телефон
        'H': 25, # Выбранные номера
        'I': 12  # Согласие (узкое)
    }
    
    for col_letter, width in widths.items():
        try:
            ws.column_dimensions[col_letter].width = width
        except Exception:
            pass

def _update_headers_if_needed(ws, new_headers: list):
    try:
        # Проверяем заголовки
        current_headers = [cell.value for cell in ws[1]]
        
        # Если это новый файл или заголовки изменились
        if current_headers != new_headers:
            logger.info("📉 Обновляем заголовки и ширину колонок...")
            for col_num, header in enumerate(new_headers, 1):
                ws.cell(row=1, column=col_num, value=header)
            
            # Принудительно применяем ширину
            _set_column_widths(ws)
            
    except Exception as e:
        logger.warning(f"Ошибка обновления структуры Excel: {e}")

def _save_to_excel_sync(filename: str, remote_path: str, data: list, headers: list):
    # --- 1. ЛОКАЛЬНАЯ ЗАПИСЬ ---
    if not os.path.exists(filename):
        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        # Сразу ставим ширину для нового файла
        _set_column_widths(ws)
        wb.save(filename)
    
    try:
        wb = openpyxl.load_workbook(filename)
        ws = wb.active
        
        # Проверяем структуру (и чиним ширину, если сбилась)
        _update_headers_if_needed(ws, headers)
        
        # Добавляем данные
        ws.append(data)
        wb.save(filename)
        logger.info(f"💾 Запись сохранена локально.")
    except PermissionError:
        logger.error(f"❌ Файл {filename} заблокирован Excel!")
        raise IOError(f"Файл {filename} открыт другой программой.")

    # --- 2. ЗАГРУЗКА В ОБЛАКО ---
    if not y:
        return

    try:
        if not y.check_token():
            raise CloudUploadError("Токен Яндекс.Диска невалиден")

        _ensure_remote_dir_exists(y, YANDEX_DIR)
        
        try:
            y.upload(filename, remote_path, overwrite=True)
            logger.info("☁️ Успешная загрузка в облако.")
        
        except LockedError:
            logger.warning("⚠️ Файл на Диске заблокирован (423). Пытаемся удалить и перезалить...")
            try:
                y.remove(remote_path)
                import time
                time.sleep(1) 
                y.upload(filename, remote_path, overwrite=True)
                logger.info("☁️ Перезаливка удалась.")
            except Exception as delete_err:
                raise CloudUploadError(f"Ресурс заблокирован и не удаляется: {delete_err}")

    except Exception as e:
        logger.error(f"❌ Ошибка облака: {e}")
        if isinstance(e, CloudUploadError):
            raise e
        raise CloudUploadError(f"Сбой загрузки: {e}")

async def add_subscription(user_data: list):
    headers = [
        "Дата", "User ID", "Username", 
        "Тип подписки", "ФИО", 
        "Способ получения / Доставка", 
        "Телефон", "Выбранные номера", 
        "Согласие ПД"
    ]
    async with file_lock:
        await asyncio.to_thread(_save_to_excel_sync, EXCEL_FILE, REMOTE_PATH_SUBS, user_data, headers)