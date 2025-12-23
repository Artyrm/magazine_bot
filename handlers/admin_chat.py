import re
from aiogram import Router, F, Bot, types # <--- ДОБАВИЛ types СЮДА
from aiogram.types import Message
from aiogram.filters import Command
from config import ADMIN_GROUP_ID

router = Router()

# Фильтр: работаем только в группе координаторов
if ADMIN_GROUP_ID:
    router.message.filter(F.chat.id == ADMIN_GROUP_ID)

# --- 1. ОТВЕТ НА СООБЩЕНИЕ (REPLY) ---

@router.message(F.reply_to_message)
async def process_coordinator_reply(message: Message, bot: Bot):
    # Игнорируем ответы не боту
    if not message.reply_to_message.from_user.is_bot:
        return 

    # Ищем ID в тексте
    original_text = message.reply_to_message.text or message.reply_to_message.caption
    match = re.search(r"ID:\s*(\d+)", original_text)
    
    if match:
        user_id = int(match.group(1))
        
        try:
            # 1. Отправляем ответ пользователю
            response_text = f"👩‍💻 <b>Ответ координатора:</b>\n\n{message.text}"
            await bot.send_message(chat_id=user_id, text=response_text, parse_mode="HTML")
            
            # 2. Ставим реакцию в группе (теперь 'types' известно)
            try:
                await message.react([types.ReactionTypeEmoji(emoji="👍")])
            except Exception:
                # Если реакции в группе запрещены или старая версия Telegram, просто молчим
                pass
            
        except Exception as e:
            await message.reply(f"❌ Не удалось доставить сообщение пользователю:\n{e}")

# --- 2. РУЧНАЯ ОТПРАВКА (/send) ---

@router.message(Command("send"))
async def cmd_send_manual(message: Message, bot: Bot):
    parts = message.text.split(maxsplit=2)
    
    if len(parts) < 3:
        await message.answer("⚠️ Формат: `/send ID ТЕКСТ`")
        return

    target_id = parts[1]
    text = parts[2]
    
    try:
        full_text = f"👩‍💻 <b>Сообщение от координатора:</b>\n\n{text}"
        await bot.send_message(chat_id=target_id, text=full_text, parse_mode="HTML")
        
        # Тоже ставим реакцию вместо текста "Отправлено"
        try:
            await message.react([types.ReactionTypeEmoji(emoji="👍")])
        except:
            await message.reply("✅ Отправлено.")
            
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")