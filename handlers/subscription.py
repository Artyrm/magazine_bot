import asyncio
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime

# Импортируем наши сервисы и кнопки
from services.sheets import add_subscription
from keyboards import main_kb, confirm_kb

router = Router()

# Текст "О журнале"
ABOUT_TEXT = (
    "<b>🤖 Журнал «Юный киберфизик»</b>\n\n"
    "Это издание для тех, кто строит будущее! Мы рассказываем о:\n"
    "🔹 Робототехнике и электронике\n"
    "🔹 Программировании дронов и микроконтроллеров\n"
    "🔹 Проектах платформы «Берлога» и НТО\n\n"
    "В каждом номере — разборы реальных кейсов, схемы и туториалы."
)

# Машина состояний
class SubForm(StatesGroup):
    waiting_for_name = State()
    waiting_for_address = State()
    waiting_for_phone = State()
    confirmation = State() # Новый шаг: подтверждение

# --- Логика меню ---

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear() # Сбрасываем старые состояния если были
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n"
        "Я бот журнала «Юный киберфизик». Чем могу помочь?",
        reply_markup=main_kb
    )

@router.message(F.text == "📖 О журнале")
async def process_about(message: Message):
    await message.answer(ABOUT_TEXT, parse_mode="HTML")

@router.message(F.text == "❌ Отмена")
async def process_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_kb)

# --- Анкета ---

@router.message(F.text == "✍️ Оформить подписку")
async def start_subscription(message: Message, state: FSMContext):
    await message.answer(
        "Отлично! Давайте заполним анкету.\n"
        "Введите ваше **ФИО**:", 
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown"
    )
    await state.set_state(SubForm.waiting_for_name)

@router.message(SubForm.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Теперь укажите **почтовый адрес** (с индексом):")
    await state.set_state(SubForm.waiting_for_address)

@router.message(SubForm.waiting_for_address)
async def process_address(message: Message, state: FSMContext):
    await state.update_data(address=message.text)
    await message.answer("И ваш контактный **телефон**:")
    await state.set_state(SubForm.waiting_for_phone)

@router.message(SubForm.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    # Сохраняем телефон и переходим к проверке
    await state.update_data(phone=message.text)
    user_data = await state.get_data()
    
    # Формируем текст для проверки
    summary = (
        "<b>Пожалуйста, проверьте данные:</b>\n\n"
        f"👤 <b>ФИО:</b> {user_data['name']}\n"
        f"🏠 <b>Адрес:</b> {user_data['address']}\n"
        f"📱 <b>Телефон:</b> {user_data['phone']}\n\n"
        "Отправляем заявку?"
    )
    
    await message.answer(summary, parse_mode="HTML", reply_markup=confirm_kb)
    await state.set_state(SubForm.confirmation)

# --- Финал: Подтверждение или исправление ---

@router.message(SubForm.confirmation, F.text == "🔄 Заполнить заново")
async def restart_form(message: Message, state: FSMContext):
    await message.answer("Хорошо, давайте сначала. Введите ФИО:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(SubForm.waiting_for_name)

@router.message(SubForm.confirmation, F.text == "✅ Всё верно")
async def submit_form(message: Message, state: FSMContext):
    user_data = await state.get_data()
    
    # 1. Сообщаем пользователю, что процесс пошел
    status_msg = await message.answer(
        "⏳ <b>Заявка формируется и отправляется...</b>\n"
        "Пожалуйста, подождите пару секунд.", 
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML"
    )
    
    # Подготовка данных для Excel
    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        message.from_user.id,
        f"@{message.from_user.username or 'нет_юзернейма'}",
        user_data['name'],
        user_data['address'],
        user_data['phone']
    ]
    
    try:
        # 2. Пытаемся сохранить (если файл занят, бот тут "повисит" и подождет)
        await add_subscription(row)
        
        # 3. Если всё ок — редактируем сообщение
        await status_msg.edit_text(
            "✅ <b>Заявка успешно принята!</b>\n"
            "Спасибо, что вы с нами. Мы свяжемся с вами в ближайшее время.",
            parse_mode="HTML"
        )
        # Возвращаем главное меню новым сообщением
        await message.answer("Главное меню:", reply_markup=main_kb)
        
    except IOError:
        # Если файл был занят слишком долго или произошла ошибка записи
        await status_msg.edit_text(
            "⚠️ <b>Произошла ошибка при сохранении.</b>\n"
            "Возможно, сервер перегружен. Попробуйте нажать /start и отправить снова через минуту."
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Неизвестная ошибка: {e}")
    
    # Очищаем память
    await state.clear()