from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Главное меню (появляется при старте)
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📖 О журнале"),
            KeyboardButton(text="✍️ Оформить подписку")
        ]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие..."
)

# Меню подтверждения
confirm_kb = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="✅ Всё верно"),
            KeyboardButton(text="🔄 Заполнить заново")
        ],
        [
            KeyboardButton(text="❌ Отмена")
        ]
    ],
    resize_keyboard=True
)