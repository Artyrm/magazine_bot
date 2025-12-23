import yaml
import logging
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from datetime import datetime

# Подключаем наш сервис сохранения
from services.sheets import add_subscription

router = Router()
logger = logging.getLogger(__name__)

# Загружаем граф состояний
try:
    with open("fsm_config.yaml", encoding="utf-8") as f:
        FSM_CONFIG = yaml.safe_load(f)
except Exception as e:
    logger.critical(f"Ошибка чтения fsm_config.yaml: {e}")
    FSM_CONFIG = {"initial_state": "error", "states": {}}

# Единое техническое состояние для движка
class EngineState(StatesGroup):
    active = State()

# --- Ядро движка ---

def get_node(node_name):
    return FSM_CONFIG["states"].get(node_name)

def create_kb(buttons_list):
    if not buttons_list:
        return types.ReplyKeyboardRemove()
    kb = [[types.KeyboardButton(text=b) for b in row] for row in buttons_list]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

async def execute_action(action_name, message, state: FSMContext):
    """Выполняет Python-код, привязанный к действиям в YAML"""
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
        # ИСПРАВЛЕНИЕ ЗДЕСЬ: Добавлены кавычки вокруг текста
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
            # Удаляем сообщение "Загрузка..."
            await wait_msg.delete() 
        except Exception as e:
            # И здесь тоже кавычки нужны, если вдруг пропали
            await wait_msg.edit_text(f"⚠️ Ошибка сохранения: {e}")

async def render_state(node_name, message, state: FSMContext):
    """Рисует пользователю экран (текст + кнопки)"""
    node = get_node(node_name)
    if not node:
        await message.answer(f"Ошибка: состояние '{node_name}' не найдено в конфиге.")
        return

    data = await state.get_data()
    
    # Подставляем переменные {name} в текст
    text_template = node.get("text", "")
    try:
        text = text_template.format(**data)
    except KeyError:
        text = text_template
    
    kb = create_kb(node.get("keyboard", []))
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")
    
    # Сохраняем, где мы сейчас, в память
    await state.update_data(current_node=node_name)

# --- Обработчики (Handlers) ---

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    start_node = FSM_CONFIG.get("initial_state", "main_menu")
    await render_state(start_node, message, state)
    await state.set_state(EngineState.active)

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

    # Поиск перехода
    for trans in transitions:
        trigger = trans.get("trigger")
        # Совпадение текста или wildcard "*"
        if trigger == user_text or trigger == "*":
            target_node = trans.get("dest")
            action_to_do = trans.get("action")
            break
    
    if target_node:
        await execute_action(action_to_do, message, state)
        await render_state(target_node, message, state)
    else:
        # Если ни один переход не подошел (юзер написал текст, а мы ждем кнопку)
        await message.answer(
            "Извините, я не понимаю этот текст 🤷‍♂️\n\n"
            "Пожалуйста, нажмите одну из кнопок меню внизу 👇"
        )