import re
from aiogram import Router, F, Bot, types
from aiogram.types import Message, ReplyKeyboardRemove # <--- Добавили ReplyKeyboardRemove
from aiogram.filters import Command
from config import ADMIN_GROUP_ID

router = Router()

# Роутер работает только в группе координаторов
if ADMIN_GROUP_ID:
    router.message.filter(F.chat.id == ADMIN_GROUP_ID)

# --- НОВОЕ: СТАРТ В АДМИНКЕ (Убирает кнопки) ---
@router.message(Command("start"))
async def cmd_admin_start(message: Message):
    text = (
        "👋 <b>Привет, администрация!</b>\n\n"
        "В этом чате бот работает в <b>режиме администратора</b>.\n"
        "Пользовательские кнопки здесь отключены, чтобы не мешать работе.\n\n"
        "ℹ️ Нажмите /help для списка команд управления."
    )
    # reply_markup=ReplyKeyboardRemove() уберет "залипшие" кнопки меню с экрана
    await message.answer(text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())

# --- СПРАВКА ---
@router.message(Command("help"))
async def cmd_admin_help(message: Message):
    text = (
        "🤖 <b>Справка для координаторов</b>\n\n"
        "1. <b>Ответ пользователю:</b>\n"
        "Сделайте <b>Reply (Ответить)</b> на сообщение от бота с ID пользователя.\n\n"
        "2. <b>Написать первым:</b>\n"
        "<code>/send ID ТЕКСТ</code>\n"
        "Пример: <code>/send 12345678 Привет!</code>\n\n"
        "3. <b>Узнать ID:</b>\n"
        "Команда /id покажет ваш Telegram ID."
    )
    await message.answer(text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())

# --- ОТВЕТ (REPLY) ---
@router.message(F.reply_to_message)
async def process_coordinator_reply(message: Message, bot: Bot):
    # Игнорируем ответы людям, реагируем только на ответы боту
    if not message.reply_to_message.from_user.is_bot:
        return 

    original_text = message.reply_to_message.text or message.reply_to_message.caption
    # Ищем ID (с тегом code или без)
    match = re.search(r"ID:\s*<code>(\d+)</code>", original_text)
    if not match:
        match = re.search(r"ID:\s*(\d+)", original_text)

    if match:
        user_id = int(match.group(1))
        
        try:
            # Импортируем менеджер нитей (чтобы связывать сообщения)
            from services.thread_manager import set_last_msg_id
            
            response_text = f"👩‍💻 <b>Ответ координатора:</b>\n\n{message.text}"
            sent_msg = await bot.send_message(chat_id=user_id, text=response_text, parse_mode="HTML")
            
            # Обновляем нить переписки
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

    # Безопасное преобразование ID
    if not parts[1].isdigit():
        await message.reply("❌ ID должен быть числом.")
        return

    target_id = int(parts[1])
    text = parts[2]
    
    try:
        from services.thread_manager import set_last_msg_id
        
        full_text = f"👩‍💻 <b>Сообщение от координатора:</b>\n\n{text}"
        await bot.send_message(chat_id=target_id, text=full_text, parse_mode="HTML")
        
        # Привязываем будущий ответ юзера к этому сообщению админа
        set_last_msg_id(target_id, message.message_id)

        try: await message.react([types.ReactionTypeEmoji(emoji="👍")])
        except: await message.reply("✅")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")