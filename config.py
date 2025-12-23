import os
import sys
from dotenv import load_dotenv

load_dotenv()

def get_env_variable(name: str):
    value = os.getenv(name)
    if not value:
        sys.stderr.write(f"Ошибка конфигурации: Не найдена переменная '{name}'\n")
        sys.exit(1)
    return value

BOT_TOKEN = get_env_variable("BOT_TOKEN")
YANDEX_TOKEN = get_env_variable("YANDEX_TOKEN")
EXCEL_FILE = "subscriptions.xlsx"

# Папка на Яндекс.Диске (начинается со слеша, без слеша в конце)
YANDEX_DIR = "/Боты/Бот журнала"

# Полный путь к файлу в облаке
REMOTE_PATH = f"{YANDEX_DIR}/{EXCEL_FILE}"

admin_ids_str = os.getenv("ADMIN_IDS")

ADMIN_IDS = []
if admin_ids_str:
    try:
        # Разбиваем строку, удаляем пробелы и пустые элементы
        ADMIN_IDS = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip()]
    except ValueError:
        # Если там мусор, просто выводим предупреждение, но НЕ падаем
        sys.stderr.write("⚠️ ВНИМАНИЕ: Ошибка в ADMIN_IDS. Список админов будет пуст.\n")
else:
    # Если переменной нет
    print("ℹ️ ADMIN_IDS не указаны. Бот запущен без администраторов.")