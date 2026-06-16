from telegram import ReplyKeyboardMarkup
from services.auth import is_admin, is_technologist
from config.products import PRODUCTS


# =========================
# Главное меню
# =========================
def main_menu(user_id=None):
    if user_id and is_admin(user_id):
        keyboard = [
            ["📥 Приход", "📤 Расход"],
            ["🏭 Склад", "🚚 Отгрузка"],
            ["⚠️ Брак", "📊 Отчет"],
            ["⚙️ Продукт", "👤 Пользователи"],
        ]
    elif user_id and is_technologist(user_id):
        keyboard = [
            ["📥 Приход", "📤 Расход"],
            ["🏭 Склад", "🚚 Отгрузка"],
            ["⚠️ Брак"],
        ]
    else:
        keyboard = [
            ["📥 Приход", "📤 Расход"],
            ["🏭 Склад", "🚚 Отгрузка"],
            ["⚠️ Брак"],
        ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


# =========================
# Управление пользователями
# =========================
def users_menu():
    keyboard = [
        ["➕ Добавить технолога"],
        ["📋 Список технологов"],
        ["❌ Удалить технолога"],
        ["⬅️ Назад"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


# =========================
# Период отчета
# =========================
def report_period_menu():
    keyboard = [
        ["📅 Сегодня"],
        ["📆 Неделя"],
        ["📈 Месяц"],
        ["⬅️ Назад"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


# =========================
# Меню склада
# =========================
def warehouse_menu():
    keyboard = [
        ["📦 Остатки"],
        ["🏭 Производство"],
        ["⬅️ Назад"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


# =========================
# Сырье / материалы
# =========================
def items_menu():
    keyboard = [
        ["Крупа", "Сахар"],
        ["Сухое молоко", "Масло"],
        ["Ванилин", "Эссенция ваниль"],
        ["Эссенция сгущенка"],
        ["Игрушки", "Коробка", "Плёнка"],
        ["⬅️ Назад"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


# =========================
# Готовая продукция
# =========================
def production_menu():

    keyboard = [
        ["ToyCorn Девочка", "ToyCorn Мальчик"],
        ["Kukuruzik Девочка", "Kukuruzik Мальчик"],
        ["⬅️ Назад"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


# =========================
# Направление отгрузки
# =========================
def shipment_place_menu():
    keyboard = [
        ["Хавас", "Склад Маруф"],
        ["⬅️ Назад"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


# =========================
# Продукция для отгрузки
# =========================
def shipment_product_menu():

    keyboard = [
        ["ToyCorn Девочка", "ToyCorn Мальчик"],
        ["Kukuruzik Девочка", "Kukuruzik Мальчик"],
        ["⬅️ Назад"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )

# =========================
# Подтверждение
# =========================
def confirm_menu():
    keyboard = [
        ["✅ Подтвердить", "❌ Отмена"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


# =========================
# Админка продукта
# =========================
def product_admin_menu():
    keyboard = [
        ["📋 Техкарта", "💰 Цены"],
        ["🧾 Цены сырья"],
        ["⬅️ Назад"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


# =========================
# Сырье для техкарты и цен сырья
# =========================
def tech_raw_menu():
    keyboard = [
        ["Крупа", "Сахар"],
        ["Сухое молоко", "Масло"],
        ["Ванилин", "Эссенция ваниль"],
        ["Эссенция сгущенка"],
        ["Игрушки", "Коробка", "Плёнка"],
        ["⬅️ Назад"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )
