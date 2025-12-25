import re
import os
import openpyxl
from aiogram import Router, F, Bot, types
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.filters import Command
from config import ADMIN_GROUP_ID, EXCEL_FILE

router = Router()

if ADMIN_GROUP_ID:
    router.message.filter(F.chat.id == ADMIN_GROUP_ID)

# --- НОВОЕ: СТАТИСТИКА ЗАЯВОК ---
@router.message(Command("stats"))
async def cmd_admin_stats(message: Message):
    if not os.path.exists(EXCEL_FILE):
        await message.reply("📂 Файл с заявками еще не создан (0 заявок).")
        return

    try:
        # Открываем файл только для чтения (data_only=True)
        wb = openpyxl.load_workbook(EXCEL_FILE, read_only=True)
        ws = wb.active
        # Считаем строки. max_row может врать, если есть пустые строки, 
        # но для наших целей (append) это обычно работает корректно.
        # Вычитаем 1 (заголовок).
        count = ws.max_row - 1
        if count < 0: count = 0
        
        await message.reply(
            f"📊 <b>Статистика подписок</b>\n\n"
            f"Всего заявок в базе: <b>{count}</b>\n"
            f"Файл: <code>{EXCEL_FILE}</code>", 
            parse_mode="HTML"
        )
        wb.close()
    except Exception as e:
        await message.reply(f"❌ Ошибка чтения файла: {e}")

# --- СПРАВКА ---
@router.message(Command("help"))
async def cmd_admin_help(message: Message):
    text = (
        "🤖 <b>Справка для координаторов</b>\n\n"
        "1. <b>Статистика:</b>\n"
        "/stats — Показать количество заявок.\n\n"
        "2. <b>Ответ пользователю:</b>\n"
        "Сделайте <b>Reply</b> на сообщение от бота.\n\n"
        "3. <b>Написать первым:</b>\n"
        "<code>/send ID ТЕКСТ</code>\n\n"
        "4. <b>Инфо:</b>\n"
        "/id — ID группы."
    )
    await message.answer(text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())

# --- ОТВЕТ (REPLY) ---
@router.message(F.reply_to_message)
async def process_coordinator_reply(message: Message, bot: Bot):
    if not message.reply_to_message.from_user.is_bot: return 

    original_text = message.reply_to_message.text or message.reply_to_message.caption
    match = re.search(r"ID:\s*<code>(\d+)</code>", original_text)
    if not match:
        match = re.search(r"ID:\s*(\d+)", original_text)

    if match:
        user_id = int(match.group(1))
        try:
            from services.thread_manager import set_last_msg_id
            response_text = f"👩‍💻 <b>Ответ координатора:</b>\n\n{message.text}"
            sent_msg = await bot.send_message(chat_id=user_id, text=response_text, parse_mode="HTML")
            set_last_msg_id(user_id, message.message_id)
            try: await message.react([types.ReactionTypeEmoji(emoji="👍")])
            except: pass
        except Exception as e:
            await message.reply(f"❌ Не удалось доставить:\n{e}")

# --- ИНИЦИАТИВА (/send) ---
@router.message(Command("send"))
async def cmd_send_manual(message: Message, bot: Bot):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("⚠️ Формат: <code>/send ID ТЕКСТ</code>", parse_mode="HTML")
        return
    if not parts[1].isdigit():
        await message.reply("❌ ID должен быть числом.")
        return

    target_id = int(parts[1])
    text = parts[2]
    try:
        from services.thread_manager import set_last_msg_id
        full_text = f"👩‍💻 <b>Сообщение от координатора:</b>\n\n{text}"
        await bot.send_message(chat_id=target_id, text=full_text, parse_mode="HTML")
        set_last_msg_id(target_id, message.message_id)
        try: await message.react([types.ReactionTypeEmoji(emoji="👍")])
        except: await message.reply("✅")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")