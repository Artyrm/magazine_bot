import yaml
import logging
from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime

# Импорты конфигурации и сервисов
from config import ADMIN_IDS, ADMIN_GROUP_ID
from services.sheets import add_subscription
from services.thread_manager import get_last_msg_id, set_last_msg_id

router = Router()
logger = logging.getLogger(__name__)

# 1. ЗАЩИТА: Этот роутер работает ТОЛЬКО в личке
router.message.filter(F.chat.type == "private")

# --- ЗАГРУЗКА КОНФИГА ---
try:
    with open("fsm_config.yaml", encoding="utf-8") as f:
        FSM_CONFIG = yaml.safe_load(f)
except Exception as e:
    logger.critical(f"Ошибка чтения fsm_config.yaml: {e}")
    FSM_CONFIG = {"initial_state": "error", "states": {}}

# --- СОСТОЯНИЯ ---
class EngineState(StatesGroup):
    active = State()          
    confirm_forward = State() 
    in_dialogue = State()     

# --- ФУНКЦИИ-ПОМОЩНИКИ ---

def get_node(node_name):
    return FSM_CONFIG["states"].get(node_name)

def create_kb(buttons_list):
    if not buttons_list:
        return types.ReplyKeyboardRemove()
    kb = [[types.KeyboardButton(text=b) for b in row] for row in buttons_list]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

async def execute_action(action_name, message, state: FSMContext):
    """Выполняет бизнес-логику"""
    if not action_name: return
    data = await state.get_data()

    if action_name == "save_name": await state.update_data(name=message.text)
    elif action_name == "save_address": await state.update_data(address=message.text)
    elif action_name == "save_phone": await state.update_data(phone=message.text)
    elif action_name == "clear_data": await state.set_data({})
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
    node = get_node(node_name)
    if not node: return

    data = await state.get_data()
    text = node.get("text", "").format(**data) if data else node.get("text", "")
    kb = create_kb(node.get("keyboard", []))
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(current_node=node_name)

async def forward_to_admins(message: types.Message, state: FSMContext, is_reply=False):
    """
    Стандартная функция пересылки (используется, когда юзер пишет сам).
    Берет данные из message.from_user.
    """
    user = message.from_user
    username = f"@{user.username}" if user.username else ""
    data = await state.get_data()
    current_node = data.get("current_node", "unknown")
    
    content_text = message.text or '[Медиафайл]'
    reply_to_id = get_last_msg_id(user.id) or data.get("last_admin_thread_id")

    header = "🗣 <b>Сообщение от пользователя</b>" if is_reply else "📩 <b>Новое обращение</b>"
    
    admin_text = (
        f"{header}\n"
        f"👤 {user.full_name} ({username})\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"📍 Этап: {current_node}\n"
        f"➖➖➖➖➖➖➖\n"
        f"{content_text}"
    )

    if ADMIN_GROUP_ID:
        try:
            sent_msg = await message.bot.send_message(
                chat_id=ADMIN_GROUP_ID, 
                text=admin_text, 
                parse_mode="HTML",
                reply_to_message_id=reply_to_id
            )
            set_last_msg_id(user.id, sent_msg.message_id)
            await state.update_data(last_admin_thread_id=sent_msg.message_id)
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки в группу: {e}")
            return False
    return False

# --- ОБРАБОТЧИКИ ---

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    start_node = FSM_CONFIG.get("initial_state", "main_menu")
    await render_state(start_node, message, state)
    await state.set_state(EngineState.active)

# Ловушка для потерянных состояний (после перезагрузки)
@router.message(StateFilter(None))
async def catch_stateless_message(message: types.Message, state: FSMContext):
    start_node_name = FSM_CONFIG.get("initial_state", "main_menu")
    start_node = get_node(start_node_name)
    if not start_node:
        await cmd_start(message, state)
        return

    # Проверяем, нажал ли кнопку меню
    user_text = message.text
    is_main_menu_button = any(t.get("trigger") == user_text for t in start_node.get("transitions", []))
            
    if is_main_menu_button:
        await state.set_state(EngineState.active)
        await state.update_data(current_node=start_node_name)
        await process_step(message, state)
    else:
        await cmd_start(message, state)

@router.message(EngineState.active)
@router.message(EngineState.in_dialogue)
async def process_step(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    data = await state.get_data()
    current_node_name = data.get("current_node")
    node = get_node(current_node_name)
    
    if not node:
        await message.answer("⚠️ Ошибка состояния. Нажмите /start")
        return

    user_text = message.text
    transitions = node.get("transitions", [])
    target_node = None
    action_to_do = None

    # 1. Проверяем кнопки меню
    for trans in transitions:
        if trans.get("trigger") == user_text:
            target_node = trans.get("dest")
            action_to_do = trans.get("action")
            break
            
    if target_node:
        await execute_action(action_to_do, message, state)
        await render_state(target_node, message, state)
        await state.set_state(EngineState.active)
        return

    # 2. Если не кнопка
    if current_state == EngineState.in_dialogue:
        success = await forward_to_admins(message, state, is_reply=True)
        if success:
            try: await message.react([types.ReactionTypeEmoji(emoji="👀")])
            except: pass
        else:
            await message.answer("⚠️ Ошибка связи с координаторами.")
        return

    for trans in transitions:
        if trans.get("trigger") == "*":
            target_node = trans.get("dest")
            action_to_do = trans.get("action")
            break
            
    if target_node:
        await execute_action(action_to_do, message, state)
        await render_state(target_node, message, state)
    else:
        # Неизвестная команда -> Предлагаем диалог
        await state.update_data(pending_message_text=message.text)
        
        confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📨 Отправить координатору", callback_data="fwd_yes"),
                InlineKeyboardButton(text="❌ Это ошибка", callback_data="fwd_no")
            ]
        ])

        await message.answer(
            "Я не понял эту команду. 🤔\n"
            "Хотите отправить это сообщение координатору журнала?",
            reply_markup=confirm_kb
        )
        await state.set_state(EngineState.confirm_forward)

# --- ИСПРАВЛЕННАЯ ОБРАБОТКА КНОПКИ ---
@router.callback_query(EngineState.confirm_forward, F.data.in_({"fwd_yes", "fwd_no"}))
async def process_forward_decision(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "fwd_no":
        await callback.message.edit_text("Действие отменено.")
        data = await state.get_data()
        await render_state(data.get("current_node", "main_menu"), callback.message, state)
        await state.set_state(EngineState.active)
        
    elif callback.data == "fwd_yes":
        # 1. Берем данные ЮЗЕРА, а не сообщения бота
        user = callback.from_user 
        data = await state.get_data()
        saved_text = data.get("pending_message_text", "")
        current_node = data.get("current_node", "unknown")
        
        # 2. Формируем сообщение вручную (не используем forward_to_admins с кривым message)
        username = f"@{user.username}" if user.username else ""
        admin_text = (
            f"📩 <b>Новое обращение</b>\n"
            f"👤 {user.full_name} ({username})\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"📍 Этап: {current_node}\n"
            f"➖➖➖➖➖➖➖\n"
            f"{saved_text}"
        )
        
        if ADMIN_GROUP_ID:
            try:
                # Отправляем в группу
                sent_msg = await callback.message.bot.send_message(
                    chat_id=ADMIN_GROUP_ID, 
                    text=admin_text, 
                    parse_mode="HTML"
                )
                
                # Сохраняем нить для будущих ответов
                set_last_msg_id(user.id, sent_msg.message_id)
                await state.update_data(last_admin_thread_id=sent_msg.message_id)
                
                # Включаем режим диалога
                await state.set_state(EngineState.in_dialogue)
                await callback.message.edit_text("✅ Сообщение передано. Режим диалога включен: пишите сюда, я всё передам.")
            except Exception as e:
                logger.error(f"Ошибка отправки: {e}")
                await callback.message.edit_text("⚠️ Ошибка связи.")
        else:
            await callback.message.edit_text("⚠️ Ошибка: нет группы координаторов.")
            
    await callback.answer()