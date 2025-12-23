import yaml
import logging
from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime

# Импорты конфигурации и сервисов
from config import ADMIN_IDS
from services.sheets import add_subscription

router = Router()
logger = logging.getLogger(__name__)

# --- ЗАГРУЗКА КОНФИГА ---
try:
    with open("fsm_config.yaml", encoding="utf-8") as f:
        FSM_CONFIG = yaml.safe_load(f)
except Exception as e:
    logger.critical(f"Ошибка чтения fsm_config.yaml: {e}")
    FSM_CONFIG = {"initial_state": "error", "states": {}}

# --- СОСТОЯНИЯ ---
class EngineState(StatesGroup):
    active = State()          # Основной режим работы по меню
    confirm_forward = State() # Режим ожидания подтверждения отправки

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_node(node_name):
    return FSM_CONFIG["states"].get(node_name)

def create_kb(buttons_list):
    if not buttons_list:
        return types.ReplyKeyboardRemove()
    kb = [[types.KeyboardButton(text=b) for b in row] for row in buttons_list]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

async def execute_action(action_name, message, state: FSMContext):
    """Выполняет бизнес-логику"""
    if not action_name:
        return
    data = await state.get_data()

    if action_name == "save_name":
        await state.update_data(name=message.text)
    elif action_name == "save_address":
        await state.update_data(address=message.text)
    elif action_name == "save_phone":
        await state.update_data(phone=message.text)
    elif action_name == "clear_data":
        await state.set_data({})
    elif action_name == "submit_to_excel":
        wait_msg = await message.answer("⏳ Сохраняем заявку...")
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            message.from_user.id,
            f"@{message.from_user.username or 'unknown'}",
            data.get("name"),
            data.get("address"),
            data.get("phone")
        ]
        try:
            await add_subscription(row)
            await wait_msg.delete()
        except Exception as e:
            await wait_msg.edit_text(f"⚠️ Ошибка сохранения: {e}")

async def render_state(node_name, message, state: FSMContext):
    """Рисует текущий экран меню"""
    node = get_node(node_name)
    if not node:
        await message.answer(f"Ошибка: состояние '{node_name}' не найдено.")
        return

    data = await state.get_data()
    text_template = node.get("text", "")
    try:
        text = text_template.format(**data)
    except KeyError:
        text = text_template
    
    kb = create_kb(node.get("keyboard", []))
    await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(current_node=node_name)

# --- ОБРАБОТЧИКИ (HANDLERS) ---

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    start_node = FSM_CONFIG.get("initial_state", "main_menu")
    await render_state(start_node, message, state)
    await state.set_state(EngineState.active)

# 1. ОБРАБОТЧИК ОСНОВНОГО МЕНЮ И ТЕКСТА
@router.message(EngineState.active)
async def process_step(message: types.Message, state: FSMContext):
    data = await state.get_data()
    current_node_name = data.get("current_node")
    node = get_node(current_node_name)
    
    if not node:
        await message.answer("Ошибка состояния. Нажмите /start")
        return

    user_text = message.text
    transitions = node.get("transitions", [])
    
    target_node = None
    action_to_do = None

    # Поиск перехода по меню
    for trans in transitions:
        trigger = trans.get("trigger")
        if trigger == user_text or trigger == "*":
            target_node = trans.get("dest")
            action_to_do = trans.get("action")
            break
    
    if target_node:
        # Если команда найдена - переходим дальше
        await execute_action(action_to_do, message, state)
        await render_state(target_node, message, state)
    else:
        # --- ЛОГИКА "НЕПОНЯТНОГО СООБЩЕНИЯ" ---
        
        # 1. Сохраняем текст, который написал юзер
        await state.update_data(pending_message_text=message.text)
        await state.update_data(pending_message_id=message.message_id) # На случай фото/файлов

        # 2. Создаем инлайн-клавиатуру (Да/Нет)
        confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📨 Отправить координатору", callback_data="fwd_yes"),
                InlineKeyboardButton(text="❌ Нет, ошибка", callback_data="fwd_no")
            ]
        ])

        # 3. Спрашиваем
        await message.answer(
            "Я не понял эту команду. 🤔\n"
            "Хотите переслать это сообщение администратору журнала?",
            reply_markup=confirm_kb
        )
        
        # 4. Переключаем состояние (чтобы ждать нажатия кнопки, а не текста)
        await state.set_state(EngineState.confirm_forward)


# 2. ОБРАБОТЧИК НАЖАТИЯ КНОПОК "ДА/НЕТ"
@router.callback_query(EngineState.confirm_forward, F.data.in_({"fwd_yes", "fwd_no"}))
async def process_forward_decision(callback: types.CallbackQuery, state: FSMContext):
    """Обрабатываем решение пользователя"""
    
    if callback.data == "fwd_no":
        # Если нажал "Нет"
        await callback.message.edit_text("Действие отменено.")
    elif callback.data == "fwd_yes":
        # Если нажал "Да, отправить"
        data = await state.get_data()
        msg_text = data.get("pending_message_text", "[Нет текста]")
        current_node = data.get("current_node", "unknown")
        
        user = callback.from_user
        username = f"@{user.username}" if user.username else "без юзернейма"
        name = user.full_name
        
        # Формируем карточку для группы координаторов
        coord_message = (
            f"📩 <b>Вопрос от читателя</b>\n"
            f"👤 {name} ({username})\n"
            f"🆔 ID: <code>{user.id}</code>\n"  # Тег code позволит кликом копировать ID
            f"📍 Этап: {current_node}\n"
            f"➖➖➖➖➖➖➖\n"
            f"{msg_text}"
        )
        
        bot = callback.message.bot
        
        # Импортируем ID группы
        from config import ADMIN_GROUP_ID
        
        if ADMIN_GROUP_ID:
            try:
                # Отправляем В ГРУППУ
                await bot.send_message(chat_id=ADMIN_GROUP_ID, text=coord_message, parse_mode="HTML")
                await callback.message.edit_text("✅ Сообщение передано координатору.")
            except Exception as e:
                logger.error(f"Ошибка отправки в группу: {e}")
                await callback.message.edit_text("⚠️ Ошибка связи с координаторами.")
        else:
            await callback.message.edit_text("⚠️ Ошибка настройки: не задана группа координаторов.")    


    # В ЛЮБОМ СЛУЧАЕ:
    # Возвращаем пользователя обратно в меню (в то состояние, где он был)
    data = await state.get_data()
    current_node = data.get("current_node", "main_menu")
    
    # Снова показываем меню (чтобы кнопки вернулись)
    # Нам нужно отправить новое сообщение, так как callback - это редактирование старого
    # Вызываем render_state, но передаем callback.message (он подойдет как Message)
    await render_state(current_node, callback.message, state)
    
    # Возвращаем режим движка
    await state.set_state(EngineState.active)
    
    # Отвечаем телеграму, что кнопка нажата
    await callback.answer()