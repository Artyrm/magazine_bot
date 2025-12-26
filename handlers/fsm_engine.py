import yaml
import logging
import os
import traceback
import asyncio
from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from datetime import datetime

from config import ADMIN_GROUP_ID
from services.sheets import add_subscription, CloudUploadError, find_last_subscription
from services.thread_manager import get_last_msg_id, set_last_msg_id

router = Router()
logger = logging.getLogger(__name__)
router.message.filter(F.chat.type == "private")

try:
    with open("fsm_config.yaml", encoding="utf-8") as f:
        FSM_CONFIG = yaml.safe_load(f)
except Exception as e:
    logger.critical(f"Ошибка чтения fsm_config.yaml: {e}")
    FSM_CONFIG = {"initial_state": "error", "states": {}}

class EngineState(StatesGroup):
    active = State()          
    confirm_forward = State() 
    in_dialogue = State()     

def get_node(node_name):
    return FSM_CONFIG.get("states", {}).get(node_name)

def create_kb(buttons_list):
    if not buttons_list: return types.ReplyKeyboardRemove()
    kb = [[types.KeyboardButton(text=b) for b in row] for row in buttons_list]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

async def report_error(message: types.Message, error_text: str):
    logger.error(error_text)
    await message.answer("⚠️ Ошибка. Попробуйте /start.")
    if ADMIN_GROUP_ID:
        try: await message.bot.send_message(ADMIN_GROUP_ID, f"🚨 <b>ERROR LOG</b>\n<pre>{error_text}</pre>", parse_mode="HTML")
        except: pass

async def execute_action(action_name, message, state: FSMContext):
    if not action_name: return None
    data = await state.get_data()
    text = message.text

    if action_name == "check_paper_history" or action_name == "check_digital_history":
        is_paper = (action_name == "check_paper_history")
        sub_type = "Бумажная версия" if is_paper else "Электронная версия"
        await state.update_data(sub_type=sub_type)
        user_id = message.from_user.id
        try:
            history = await asyncio.to_thread(find_last_subscription, user_id)
        except Exception as e:
            return "not_found"
        if history and history.get("name"):
            await state.update_data(saved_name=history['name'], saved_phone=history['phone'], saved_address=history.get('address', ''))
            return sub_type
        else:
            return "not_found"

    elif action_name == "autofill_paper":
        await state.update_data(
            name=data.get("saved_name"),
            phone=data.get("saved_phone"),
            delivery_info=f"По почте (+доставка). Адрес: {data.get('saved_address', '')}"
        )
    elif action_name == "autofill_digital":
        await state.update_data(
            name=data.get("saved_name"),
            phone=data.get("saved_phone"),
            delivery_info="Прислать в этот чат"
        )
    
    elif action_name == "save_name":
        await state.update_data(name=text)
    elif action_name == "save_delivery_method":
        await state.update_data(delivery_info=text)
    elif action_name == "save_address_append":
        current_info = data.get("delivery_info", "По почте (+доставка)")
        await state.update_data(delivery_info=f"{current_info}. Адрес: {text}")
    elif action_name == "save_digital_delivery":
        await state.update_data(delivery_info=text)
    elif action_name == "save_phone":
        await state.update_data(phone=text)
    elif action_name == "save_issues":
        await state.update_data(issues=text)

    # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
    elif action_name == "clear_data":
        # Получаем текущие данные
        current_data = await state.get_data()
        # Собираем данные, которые нужно СОХРАНИТЬ (цены)
        data_to_keep = {
            key: value for key, value in current_data.items() if key.startswith('price_')
        }
        # Очищаем все и тут же восстанавливаем цены
        await state.clear()
        await state.set_data(data_to_keep)
    # -------------------------

    elif action_name == "prepare_payment_and_calc":
        await state.update_data(consent="Да")
        config_prices = FSM_CONFIG.get("config", {}).get("prices")
        if not config_prices:
            await state.update_data(price_text="Ошибка цен")
            return

        sub_type = data.get("sub_type", "")
        issues = data.get("issues", "")
        delivery_info = data.get("delivery_info", "").lower()
        needs_delivery = "+доставка" in delivery_info
        
        try:
            if "электронные" in sub_type.lower():
                price_str = f"{config_prices['digital']}₽"
            else:
                if "комплект" in issues.lower():
                    base, dele = config_prices["paper_full"], config_prices["delivery_full"] if needs_delivery else 0
                else:
                    base, dele = config_prices["paper_single"], config_prices["delivery_single"] if needs_delivery else 0
                total = base + dele
                desc = f"({base}₽ + {dele}₽ дост.)" if needs_delivery else "(без доставки)"
                price_str = f"{total}₽ {desc}"
            await state.update_data(price_text=price_str)
        except:
            await state.update_data(price_text="Ошибка цен")

    elif action_name == "submit_subscription":
        wait_msg = await message.answer("⏳ Сохраняем...")
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M"), message.from_user.id, f"@{message.from_user.username or 'unknown'}",
            data.get("sub_type"), data.get("name"), data.get("delivery_info"), 
            data.get("phone"), data.get("issues"), data.get("consent")
        ]
        try:
            await add_subscription(row)
            await wait_msg.delete()
        except Exception as e:
            await wait_msg.edit_text(f"⚠️ Ошибка: {e}")
    
    return None

async def render_state(node_name, message, state: FSMContext):
    node = get_node(node_name)
    if not node:
        await report_error(message, f"Node '{node_name}' not found in YAML")
        return

    data = await state.get_data()
    text = node.get("text", "")
    
    try:
        text = text.format(**data)
    except KeyError as e:
        logger.warning(f"Ошибка форматирования текста: не найдена переменная {e}")
        pass
    
    kb = create_kb(node.get("keyboard", []))
    image_file = node.get("image")
    
    if image_file:
        if os.path.exists(image_file):
            try:
                photo = FSInputFile(image_file)
                await message.answer_photo(photo=photo, caption=text, reply_markup=kb, parse_mode="HTML")
                await state.update_data(current_node=node_name)
                return
            except: pass
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    await state.update_data(current_node=node_name)

async def forward_to_admins(message: types.Message, state: FSMContext, is_reply=False, text_override=None):
    user = message.from_user
    username = f"@{user.username}" if user.username else ""
    data = await state.get_data()
    current_node = data.get("current_node", "unknown")
    content_text = text_override if text_override else (message.text or '[Медиафайл]')
    reply_to_id = get_last_msg_id(user.id) or data.get("last_admin_thread_id")
    header = "🗣 <b>Сообщение</b>" if is_reply else "📩 <b>Новое обращение</b>"
    
    admin_text = (
        f"{header}\n"
        f"👤 {user.full_name} ({username})\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"📍 Этап: {current_node}\n"
        f"#id{user.id}\n"
        f"➖➖➖➖➖➖➖\n"
        f"{content_text}"
    )

    if ADMIN_GROUP_ID:
        try:
            sent_msg = await message.bot.send_message(chat_id=ADMIN_GROUP_ID, text=admin_text, parse_mode="HTML", reply_to_message_id=reply_to_id)
            set_last_msg_id(user.id, sent_msg.message_id)
            await state.update_data(last_admin_thread_id=sent_msg.message_id)
            return True
        except: return False
    return False

async def load_prices_to_state(state: FSMContext):
    prices = FSM_CONFIG.get("config", {}).get("prices", {})
    price_data = {
        'price_digital': prices.get('digital', 0),
        'price_paper_single': prices.get('paper_single', 0),
        'price_paper_full': prices.get('paper_full', 0),
        'price_delivery_single': prices.get('delivery_single', 0),
        'price_delivery_full': prices.get('delivery_full', 0)
    }
    await state.update_data(**price_data)

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await load_prices_to_state(state)
    start_node = FSM_CONFIG.get("initial_state", "main_menu")
    await render_state(start_node, message, state)
    await state.set_state(EngineState.active)

@router.message(StateFilter(None))
async def catch_stateless_message(message: types.Message, state: FSMContext):
    await load_prices_to_state(state)
    start_node_name = FSM_CONFIG.get("initial_state", "main_menu")
    start_node = get_node(start_node_name)
    if not start_node: await cmd_start(message, state); return
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
    if not node: await cmd_start(message, state); return

    user_text = message.text
    transitions = node.get("transitions", [])
    target_node = None
    action_to_do = None

    for trans in transitions:
        if trans.get("trigger") == user_text:
            target_node = trans.get("dest")
            action_to_do = trans.get("action")
            break
            
    if target_node:
        try:
            action_result = await execute_action(action_to_do, message, state)
            next_node_data = get_node(target_node)
            auto_transition = None
            if not next_node_data:
                await report_error(message, f"Node '{target_node}' not found")
                return
            if action_result:
                for t in next_node_data.get("transitions", []):
                    if t.get("trigger") == action_result:
                        auto_transition = t
                        break
            if auto_transition:
                final_node = auto_transition.get("dest")
                final_action = auto_transition.get("action")
                if not get_node(final_node):
                    await report_error(message, f"Final node '{final_node}' not found")
                    return
                await execute_action(final_action, message, state)
                await render_state(final_node, message, state)
            else:
                await render_state(target_node, message, state)
            if current_state == EngineState.in_dialogue: 
                await state.set_state(EngineState.active)
            return
        except Exception as e:
            err_msg = f"{e}\n\n{traceback.format_exc()}"
            await report_error(message, err_msg)
            return

    if current_state == EngineState.in_dialogue:
        success = await forward_to_admins(message, state, is_reply=True)
        if success:
            try: await message.react([types.ReactionTypeEmoji(emoji="👀")])
            except: pass
        else: await message.answer("⚠️ Ошибка связи.")
        return

    for trans in transitions:
        if trans.get("trigger") == "*":
            target_node = trans.get("dest")
            action_to_do = trans.get("action")
            break
    if target_node:
        await execute_action(action_to_do, message, state)
        await render_state(target_node, message, state)
        return

    is_navigation_button = False
    for s_name, s_data in FSM_CONFIG["states"].items():
        for t in s_data.get("transitions", []):
            if t.get("trigger") == user_text: is_navigation_button = True; break
        if is_navigation_button: break
    if is_navigation_button:
        await render_state(current_node_name, message, state)
        return

    await state.update_data(pending_message_text=message.text)
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📨 Отправить координатору", callback_data="fwd_yes"), InlineKeyboardButton(text="❌ Это ошибка", callback_data="fwd_no")]])
    await message.answer("Я не понял эту команду. 🤔\nХотите отправить это сообщение координатору?", reply_markup=confirm_kb)
    await state.set_state(EngineState.confirm_forward)

@router.callback_query(EngineState.confirm_forward, F.data.in_({"fwd_yes", "fwd_no"}))
async def process_forward_decision(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "fwd_no":
        await callback.message.edit_text("Действие отменено.")
        data = await state.get_data()
        await render_state(data.get("current_node", "main_menu"), callback.message, state)
        await state.set_state(EngineState.active)
    elif callback.data == "fwd_yes":
        data = await state.get_data()
        saved_text = data.get("pending_message_text", "")
        await state.set_state(EngineState.in_dialogue)
        success = await forward_to_admins(message=callback.message, state=state, is_reply=False, text_override=saved_text)
        if success: await callback.message.edit_text("✅ Сообщение передано. Режим диалога включен: пишите сюда, я всё передам.")
        else: await callback.message.edit_text("⚠️ Ошибка: нет группы координаторов.")
    await callback.answer()