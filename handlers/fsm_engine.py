import yaml
import logging
import os
from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from datetime import datetime

from config import ADMIN_IDS, ADMIN_GROUP_ID
from services.sheets import add_subscription, CloudUploadError
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
    return FSM_CONFIG["states"].get(node_name)

def create_kb(buttons_list):
    if not buttons_list:
        return types.ReplyKeyboardRemove()
    kb = [[types.KeyboardButton(text=b) for b in row] for row in buttons_list]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

async def execute_action(action_name, message, state: FSMContext):
    if not action_name: return
    data = await state.get_data()
    text = message.text

    if action_name == "save_sub_type":
        clean_text = text.replace("📄 ", "").replace("💻 ", "")
        await state.update_data(sub_type=clean_text)
    elif action_name == "save_name":
        await state.update_data(name=text)
    elif action_name == "save_delivery_method":
        await state.update_data(delivery_info=text)
    elif action_name == "save_address_append":
        current_info = data.get("delivery_info", "Почта")
        full_info = f"{current_info}. Адрес: {text}"
        await state.update_data(delivery_info=full_info)
    elif action_name == "save_digital_delivery":
        await state.update_data(delivery_info=text)
    elif action_name == "save_phone":
        await state.update_data(phone=text)
    elif action_name == "save_issues":
        await state.update_data(issues=text)
    elif action_name == "clear_data":
        await state.set_data({})

    # --- РАСЧЕТ ЦЕНЫ (СТРОГО ИЗ YAML) ---
    elif action_name == "prepare_payment_and_calc":
        await state.update_data(consent="Да")
        
        # 1. Достаем цены из конфига. Если их нет - это ошибка админа.
        config_prices = FSM_CONFIG.get("config", {}).get("prices")
        
        if not config_prices:
            logger.error("В fsm_config.yaml не найден блок config: prices!")
            await state.update_data(price_text="Ошибка конфигурации цен")
            return

        # 2. Логика
        sub_type = data.get("sub_type", "")
        issues = data.get("issues", "")
        price_str = "Не рассчитано"

        try:
            if "электронные" in sub_type.lower():
                val = config_prices["digital"]
                price_str = f"{val}₽"
            else:
                # Бумажные
                if "комплект" in issues.lower():
                    # Комплект
                    base = config_prices["paper_full"]
                    dele = config_prices["delivery_full"]
                    total = base + dele
                    price_str = f"{total}₽ ({base}₽ подписка + {dele}₽ доставка)"
                else:
                    # Один номер
                    base = config_prices["paper_single"]
                    dele = config_prices["delivery_single"]
                    total = base + dele
                    price_str = f"{total}₽ ({base}₽ номер + {dele}₽ доставка)"
        except KeyError as e:
            logger.error(f"В конфиге не хватает ключа цены: {e}")
            price_str = "Ошибка цен (см. лог)"

        await state.update_data(price_text=price_str)

    # --- ОТПРАВКА ---
    elif action_name == "submit_subscription":
        wait_msg = await message.answer("⏳ Сохраняем заявку...")
        
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            message.from_user.id,
            f"@{message.from_user.username or 'unknown'}",
            data.get("sub_type"),
            data.get("name"),
            data.get("delivery_info"), 
            data.get("phone"),
            data.get("issues"),
            data.get("consent")
        ]
        
        try:
            await add_subscription(row)
            await wait_msg.delete()
            # Успех
        
        except CloudUploadError as e:
            await wait_msg.delete()
            # Пользователю - мягко
            await message.answer("✅ Заявка принята! (Есть временная проблема с облаком, но мы сохранили данные локально).")
            # Админам - жестко
            if ADMIN_GROUP_ID:
                try:
                    error_text = str(e)
                    advice = "Перезагрузите бота."
                    if "Locked" in error_text or "423" in error_text:
                        advice = "Файл на Яндексе завис. Удалите его вручную через браузер."
                    elif "Token" in error_text:
                        advice = "Слетел токен Яндекса."

                    await message.bot.send_message(
                        chat_id=ADMIN_GROUP_ID,
                        text=(
                            f"⚠️ <b>СБОЙ СИНХРОНИЗАЦИИ</b>\n"
                            f"Файл сохранен только локально.\n"
                            f"❌ Ошибка: {error_text}\n"
                            f"💡 Совет: {advice}"
                        ),
                        parse_mode="HTML"
                    )
                except: pass

        except Exception as e:
            await wait_msg.edit_text(f"⚠️ Ошибка сохранения: {e}")

async def render_state(node_name, message, state: FSMContext):
    node = get_node(node_name)
    if not node: return

    data = await state.get_data()
    text_template = node.get("text", "")
    try:
        text = text_template.format(**data)
    except KeyError:
        text = text_template
    
    kb = create_kb(node.get("keyboard", []))
    image_file = node.get("image")
    
    if image_file:
        if os.path.exists(image_file):
            try:
                photo = FSInputFile(image_file)
                await message.answer_photo(photo=photo, caption=text, reply_markup=kb, parse_mode="HTML")
                await state.update_data(current_node=node_name)
                return
            except Exception as e:
                logger.error(f"Ошибка фото: {e}")
        else:
            logger.error(f"Файл {image_file} не найден")

    await message.answer(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    await state.update_data(current_node=node_name)

async def forward_to_admins(message: types.Message, state: FSMContext, is_reply=False, text_override=None):
    user = message.from_user
    username = f"@{user.username}" if user.username else ""
    data = await state.get_data()
    current_node = data.get("current_node", "unknown")
    content_text = text_override if text_override else (message.text or '[Медиафайл]')
    reply_to_id = get_last_msg_id(user.id) or data.get("last_admin_thread_id")
    header = "🗣 <b>Сообщение от пользователя</b>" if is_reply else "📩 <b>Новое обращение</b>"
    
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
        except Exception:
            return False
    return False

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    start_node = FSM_CONFIG.get("initial_state", "main_menu")
    await render_state(start_node, message, state)
    await state.set_state(EngineState.active)

@router.message(StateFilter(None))
async def catch_stateless_message(message: types.Message, state: FSMContext):
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
    if not node: await message.answer("⚠️ Ошибка состояния. Нажмите /start"); return

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
        await execute_action(action_to_do, message, state)
        await render_state(target_node, message, state)
        if current_state == EngineState.in_dialogue: await state.set_state(EngineState.active)
        return

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
    await message.answer("Я не понял эту команду. 🤔\nХотите отправить это сообщение координатору журнала?", reply_markup=confirm_kb)
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