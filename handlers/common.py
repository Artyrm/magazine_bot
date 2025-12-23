# handlers/common.py
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from config import ADMIN_IDS

router = Router()

@router.message(Command("id"))
async def cmd_get_id(message: Message):
    """Команда, чтобы узнать свой ID"""
    user_id = message.from_user.id
    
    # Проверим, админ ли это
    status = "Вы администратор 🛠" if user_id in ADMIN_IDS else "Вы обычный пользователь"
    
    await message.answer(f"Ваш Telegram ID: `{user_id}`\n{status}", parse_mode="Markdown")

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer("Доступные команды:\n/start - Подписаться\n/id - Узнать свой ID")