import asyncio
import hashlib
import hmac
import logging
import os
import threading
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from db.database import SessionLocal
from db.models import InventoryMovement, TechCard, ProductPrice, RawMaterialPrice
from keyboards import (
    main_menu,
    warehouse_menu,
    items_menu,
    production_menu,
    shipment_place_menu,
    shipment_product_menu,
    confirm_menu,
    product_admin_menu,
    tech_raw_menu,
    report_period_menu,
    users_menu,
)
from services.stock_report import (
    get_all_stock,
    get_stock_status
)
from services.inventory import get_balance
from services.report import get_daily_report, get_report
from services.google_sheets import (
    log_audit,
    log_to_sheet,
    log_shipment,
    sync_daily_report,
    sync_raw_report,
)
from services.auth import (
    add_technologist,
    get_admins,
    get_technologists,
    is_admin,
    remove_technologist,
)
from services.alerts import check_deviation_alerts, check_negative_stock
from config.products import PRODUCTS
from config.brands import (
    get_brand,
    get_pcs_in_box
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_BASE_URL = os.getenv(
    "WEBHOOK_BASE_URL",
    "https://snack-erp-bot.onrender.com",
).rstrip("/")
WEBHOOK_PATH = "/telegram"
WEBHOOK_SECRET = (
    hashlib.sha256(BOT_TOKEN.encode()).hexdigest()
    if BOT_TOKEN
    else ""
)

user_state = {}

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

web = Flask(__name__)
bot_application = None
bot_event_loop = None
bot_ready = threading.Event()
runtime_metrics = {
    "webhook_updates_received": 0,
    "last_update_at": None,
    "last_update_id": None,
    "start_commands_received": 0,
    "last_start_at": None,
    "handler_errors": 0,
    "last_handler_error": None,
}


@web.route("/")
def home():
    return "ERP BOT OK"


@web.route("/status")
def status():
    data = {
        "ok": True,
        "telegram_mode": "webhook",
        "bot_ready": bot_ready.is_set(),
        **runtime_metrics,
    }

    if bot_ready.is_set() and bot_application and bot_event_loop:
        data["bot_username"] = bot_application.bot.username

        future = asyncio.run_coroutine_threadsafe(
            bot_application.bot.get_webhook_info(),
            bot_event_loop,
        )
        try:
            webhook_info = future.result(timeout=5)
            data["webhook"] = {
                "url": webhook_info.url,
                "pending_update_count": webhook_info.pending_update_count,
                "last_error_message": webhook_info.last_error_message,
            }
        except Exception as exc:
            logger.exception("Failed to retrieve Telegram webhook info")
            data["webhook_check_error"] = type(exc).__name__

    return jsonify(data)


@web.post(WEBHOOK_PATH)
def telegram_webhook():
    if not hmac.compare_digest(
        request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""),
        WEBHOOK_SECRET,
    ):
        return "Forbidden", 403

    if not bot_ready.is_set() or not bot_application or not bot_event_loop:
        return "Bot is starting", 503

    update = Update.de_json(request.get_json(force=True), bot_application.bot)
    runtime_metrics["webhook_updates_received"] += 1
    runtime_metrics["last_update_at"] = datetime.now(timezone.utc).isoformat()
    runtime_metrics["last_update_id"] = update.update_id

    future = asyncio.run_coroutine_threadsafe(
        bot_application.update_queue.put(update),
        bot_event_loop,
    )

    try:
        future.result(timeout=5)
    except Exception:
        logger.exception("Failed to enqueue Telegram update")
        return "Temporary failure", 503

    return "OK"


def run_web():
    web.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        use_reloader=False,
    )


# =========================
# данные пользователя для аудита
# =========================
def get_audit_user(update):
    user = update.message.from_user
    return user.full_name or user.username or str(user.id)


def format_old_value(value):
    return "не было" if value is None else value


# =========================
# получить цену готовой продукции из БД
# =========================
def get_product_price(product, place):
    db = SessionLocal()
    try:
        row = db.query(ProductPrice).filter(
            ProductPrice.product == product,
            ProductPrice.place == place
        ).first()

        if not row:
            return None

        return row.price

    finally:
        db.close()


# =========================
# отправка алертов
# =========================
async def send_alerts(context, messages):
    for admin_id in get_admins():
        for msg in messages:
            await context.bot.send_message(chat_id=admin_id, text=msg)


def format_report_message(report, title):
    message = (
        f"{title}\n"
        f"{report['start_date']} - {report['end_date']}\n\n"
        f"Произведено: {report['produced']} шт\n"
        f"Отгружено: {report['shipped']} шт\n\n"
        f"Выручка: {report['revenue']:.0f} сум\n"
        f"Себестоимость факт: {report['cost']:.0f} сум\n"
        f"Себестоимость норма: {report['norm_cost']:.0f} сум\n"
        f"Потери по сырью: {report['raw_loss_money']:.0f} сум\n"
        f"Прибыль факт: {report['profit']:.0f} сум\n"
        f"Маржа: {report['margin']:.1f}%\n\n"
        f"Сырье:\n"
    )

    for item, qty in report["raw_usage"].items():
        price = report["raw_prices"].get(item, 0)
        item_cost = report["fact_cost_by_item"].get(item, 0)

        message += (
            f"- {item}: {qty:.2f} кг × {price:.0f} = "
            f"{item_cost:.0f} сум\n"
        )

    message += "\n🚨 Контроль потерь:\n"

    for item, data in report["deviations"].items():
        message += (
            f"- {item}: {data['status']}\n"
            f"  факт {data['fact']:.2f} кг | "
            f"норма {data['norm']:.2f} кг | "
            f"Δ {data['diff']:.2f} кг | "
            f"{data['percent']:.1f}%\n"
            f"  потери: {data['diff_money']:.0f} сум\n"
        )

    return message


# =========================
# старт
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    runtime_metrics["start_commands_received"] += 1
    runtime_metrics["last_start_at"] = datetime.now(timezone.utc).isoformat()

    user_id = update.message.from_user.id
    user_state.pop(user_id, None)

    try:
        reply_markup = main_menu(user_id)
    except Exception:
        logger.exception("Database role lookup failed during /start")
        reply_markup = main_menu()

    await update.message.reply_text(
        "Выберите действие:",
        reply_markup=reply_markup,
    )


# =========================
# обработка сообщений
# =========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.from_user.id

    state = user_state.get(user_id, {})

    # =====================
    # УМНЫЙ НАЗАД
    # =====================
    if text == "⬅️ Назад":
        mode = state.get("mode")

        # из ввода цены сырья назад к выбору сырья
        if mode == "raw_price_enter_value":
            state["mode"] = "raw_price_select_item"
            user_state[user_id] = state

            await update.message.reply_text(
                "Выберите сырье:",
                reply_markup=tech_raw_menu()
            )
            return

        # из выбора сырья для цены назад в меню продукта
        if mode == "raw_price_select_item":
            user_state[user_id] = {"mode": "product_admin"}

            await update.message.reply_text(
                "Выберите действие:",
                reply_markup=product_admin_menu()
            )
            return

        # из ввода цены назад к выбору канала
        if mode == "price_enter_value":
            state["mode"] = "price_select_place"
            user_state[user_id] = state

            await update.message.reply_text(
                f"Продукт: {state.get('product')}\nВыберите канал:",
                reply_markup=shipment_place_menu()
            )
            return

        # из выбора канала цены назад к выбору продукта
        if mode == "price_select_place":
            state["mode"] = "price_select_product"
            user_state[user_id] = state

            await update.message.reply_text(
                "Выберите продукт:",
                reply_markup=production_menu()
            )
            return

        # из ввода граммов назад к выбору сырья
        if mode == "tech_card_enter_grams":
            state["mode"] = "tech_card_select_raw"
            user_state[user_id] = state

            await update.message.reply_text(
                f"Продукт: {state.get('product')}\nВыберите сырье:",
                reply_markup=tech_raw_menu()
            )
            return

        # из выбора сырья назад к выбору продукта
        if mode == "tech_card_select_raw":
            state["mode"] = "tech_card_select_product"
            user_state[user_id] = state

            await update.message.reply_text(
                "Выберите продукт:",
                reply_markup=production_menu()
            )
            return

        # из выбора продукта техкарты/цены назад в меню продукта
        if mode in ["tech_card_select_product", "price_select_product"]:
            user_state[user_id] = {"mode": "product_admin"}

            await update.message.reply_text(
                "Выберите действие:",
                reply_markup=product_admin_menu()
            )
            return

        # из меню продукта назад в главное меню
        if mode == "product_admin":
            user_state.pop(user_id, None)

            await update.message.reply_text(
                "Главное меню",
                reply_markup=main_menu(user_id)
            )
            return

        # из управления пользователями назад в главное меню
        if mode in [
            "users_admin",
            "role_add_technologist",
            "role_remove_technologist",
        ]:
            user_state.pop(user_id, None)

            await update.message.reply_text(
                "Главное меню",
                reply_markup=main_menu(user_id)
            )
            return

        # обычный назад
        user_state.pop(user_id, None)
        await update.message.reply_text(
            "Главное меню",
            reply_markup=main_menu(user_id)
        )
        return

    # =====================
    # ПОДТВЕРЖДЕНИЕ
    # =====================
    if text in ["✅ Подтвердить", "❌ Отмена"]:
        if not state.get("pending"):
            return

        if text == "❌ Отмена":
            user_state.pop(user_id, None)
            await update.message.reply_text(
                "Операция отменена",
                reply_markup=main_menu(user_id)
            )
            return

        quantity = state["quantity"]
        mode = state["mode"]
        item = state["item"]
        audit_user = get_audit_user(update)

        db = SessionLocal()
        try:
            alerts = []

            # 🚚 ОТГРУЗКА
            if mode == "shipment":
                place = state.get("place")

                pcs_in_box = get_pcs_in_box(item)

                qty_pcs = quantity * pcs_in_box

                price = get_product_price(item, place)

                if price is None:
                    await update.message.reply_text(
                        f"❌ Цена не задана:\n"
                        f"{item} / {place}\n\n"
                        f"Сначала задайте цену в:\n"
                        f"⚙️ Продукт → 💰 Цены"
                    )
                    return

                revenue = qty_pcs * price

                movement = InventoryMovement(
                    item=item,
                    type="shipment",
                    quantity=qty_pcs,
                    place=place,
                    revenue=revenue
                )

                db.add(movement)
                db.commit()

                log_to_sheet("shipment", item, qty_pcs, place, revenue)
                log_shipment(
                   place=place,
                   product=item,
                   qty_pcs=qty_pcs,
                   qty_boxes=quantity,
                   price_per_piece=price,
                   revenue=revenue
                )
                log_audit(
                    user=audit_user,
                    user_id=user_id,
                    action="отгрузка",
                    item=item,
                    quantity=qty_pcs,
                    comment=(
                        f"{place}; {quantity} коробок; "
                        f"{price} сум/шт; выручка {revenue}"
                    )
                )

                await update.message.reply_text(
                    f"Отгружено: {item}\n{quantity} коробок ({qty_pcs} шт)"
                )

            # 📦 ОСТАЛЬНОЕ
            else:
                movement = InventoryMovement(
                    item=item,
                    type=mode,
                    quantity=quantity
                )
    
                db.add(movement)
                db.commit()

                # =====================
                # АВТОСПИСАНИЕ СЫРЬЯ
                # =====================
                auto_writeoffs = []

                if mode == "production":

                    brand = get_brand(item)

                    tech_rows = db.query(
                        TechCard
                    ).filter(
                        TechCard.product == brand
                    ).all()

                    for tech in tech_rows:

                        raw_item = tech.raw_item

                        grams_per_unit = float(
                            tech.grams_per_unit or 0
                        )          

                        raw_qty_kg = (
                            quantity *
                            grams_per_unit /
                            1000
                        )

                        raw_movement = InventoryMovement(
                            item=raw_item,
                            type="📤 Расход",
                            quantity=raw_qty_kg
                        )

                        db.add(raw_movement)
                        auto_writeoffs.append((raw_item, raw_qty_kg))

                    db.commit()

                log_to_sheet(mode, item, quantity)
                action_map = {
                    "📥 Приход": "приход",
                    "📤 Расход": "расход",
                    "⚠️ Брак": "брак",
                    "production": "производство"
                }
                log_audit(
                    user=audit_user,
                    user_id=user_id,
                    action=action_map.get(mode, mode),
                    item=item,
                    quantity=quantity,
                    comment=""
                )

                for raw_item, raw_qty_kg in auto_writeoffs:
                    log_audit(
                        user=audit_user,
                        user_id=user_id,
                        action="автосписание сырья",
                        item=raw_item,
                        quantity=raw_qty_kg,
                        comment=(
                            f"Производство: {item}; "
                            f"количество {quantity} шт"
                        )
                    )

                await update.message.reply_text(
                    f"Сохранено: {mode} - {item} - {quantity}"
            )
            # =====================
            # АЛЕРТЫ
            # =====================
            alerts.extend(check_deviation_alerts())

            balance = get_balance(item)
            neg_alert = check_negative_stock(item, balance)

            if neg_alert:
                alerts.append(neg_alert)

            if alerts:
                await send_alerts(context, alerts)

        finally:
            db.close()

        user_state.pop(user_id, None)

        await update.message.reply_text(
            "Готово",
            reply_markup=main_menu(user_id)
        )
        return
    # =====================
    # ОСТАТКИ
    # =====================
    if text == "📦 Остатки":

        stock = get_all_stock()

        message = "📦 Остатки склада\n\n"

        for item, balance in sorted(stock.items()):

            status = get_stock_status(balance)

            if status == "NEGATIVE":
                icon = "🔴"
            elif status == "LOW":
                icon = "🟡"
            else:
                icon = "🟢"

            message += f"{icon} {item}: {balance:.2f}\n"

        await update.message.reply_text(message)

        return

    # =====================
    # =====================
    # ОТЧЕТ ТОЛЬКО АДМИН
    # =====================
    if text == "📊 Отчет":
        if not is_admin(user_id):
            await update.message.reply_text("⛔ Нет доступа")
            return

        user_state[user_id] = {
            "mode": "report_period"
        }

        await update.message.reply_text(
            "Выберите период отчета:",
            reply_markup=report_period_menu()
        )
        return

    if state.get("mode") == "report_period" and text in [
        "📅 Сегодня", "📆 Неделя", "📈 Месяц"
    ]:
        if not is_admin(user_id):
            await update.message.reply_text("⛔ Нет доступа")
            return

        period_map = {
            "📅 Сегодня": ("day", "📊 Дневной отчет"),
            "📆 Неделя": ("week", "📊 Отчет за неделю"),
            "📈 Месяц": ("month", "📊 Отчет за месяц"),
        }

        period, title = period_map[text]

        if period == "day":
            report = get_daily_report()
            sync_daily_report(report)
            sync_raw_report(report)
        else:
            report = get_report(period)

        message = format_report_message(report, title)

        await update.message.reply_text(message)
        return
    
    # =====================
    # ⚙️ ПРОДУКТ ТОЛЬКО АДМИН
    # =====================

    if text == "⚙️ Продукт":
        if not is_admin(user_id):
            await update.message.reply_text("⛔ Нет доступа")
            return

        user_state[user_id] = {
            "mode": "product_admin"
        }

        await update.message.reply_text(
            "Выберите действие:",
            reply_markup=product_admin_menu()
        )
        return

    # =====================
    # 👤 ПОЛЬЗОВАТЕЛИ ТОЛЬКО АДМИН
    # =====================
    if text == "👤 Пользователи":
        if not is_admin(user_id):
            await update.message.reply_text("⛔ Нет доступа")
            return

        user_state[user_id] = {
            "mode": "users_admin"
        }

        await update.message.reply_text(
            "Управление пользователями:",
            reply_markup=users_menu()
        )
        return

    if text == "➕ Добавить технолога":
        if not is_admin(user_id):
            await update.message.reply_text("⛔ Нет доступа")
            return

        user_state[user_id] = {
            "mode": "role_add_technologist"
        }

        await update.message.reply_text(
            "Введите Telegram ID технолога:"
        )
        return

    if text == "📋 Список технологов":
        if not is_admin(user_id):
            await update.message.reply_text("⛔ Нет доступа")
            return

        technologists = get_technologists()

        if not technologists:
            message = "Технологи не добавлены"
        else:
            message = "📋 Список технологов\n\n"
            for tech_user_id in technologists:
                message += f"- {tech_user_id}\n"

        await update.message.reply_text(
            message,
            reply_markup=users_menu()
        )
        return

    if text == "❌ Удалить технолога":
        if not is_admin(user_id):
            await update.message.reply_text("⛔ Нет доступа")
            return

        user_state[user_id] = {
            "mode": "role_remove_technologist"
        }

        await update.message.reply_text(
            "Введите Telegram ID технолога для удаления:"
        )
        return

    if state.get("mode") == "role_add_technologist":
        if not is_admin(user_id):
            await update.message.reply_text("⛔ Нет доступа")
            return

        try:
            tech_user_id = int(text)
        except ValueError:
            await update.message.reply_text("Введите Telegram ID числом!")
            return

        created = add_technologist(tech_user_id)

        if created:
            log_audit(
                user=get_audit_user(update),
                user_id=user_id,
                action="ROLE_ADDED",
                item=tech_user_id,
                quantity="",
                comment="technologist"
            )
            message = f"Технолог добавлен: {tech_user_id}"
        else:
            message = f"Технолог уже существует: {tech_user_id}"

        user_state[user_id] = {
            "mode": "users_admin"
        }

        await update.message.reply_text(
            message,
            reply_markup=users_menu()
        )
        return

    if state.get("mode") == "role_remove_technologist":
        if not is_admin(user_id):
            await update.message.reply_text("⛔ Нет доступа")
            return

        try:
            tech_user_id = int(text)
        except ValueError:
            await update.message.reply_text("Введите Telegram ID числом!")
            return

        removed = remove_technologist(tech_user_id)

        if removed:
            log_audit(
                user=get_audit_user(update),
                user_id=user_id,
                action="ROLE_REMOVED",
                item=tech_user_id,
                quantity="",
                comment="technologist"
            )
            message = f"Технолог удален: {tech_user_id}"
        else:
            message = f"Технолог не найден: {tech_user_id}"

        user_state[user_id] = {
            "mode": "users_admin"
        }

        await update.message.reply_text(
            message,
            reply_markup=users_menu()
        )
        return


    # =====================
    # 📋 ТЕХКАРТА
    # =====================
    if text == "📋 Техкарта":
        if not is_admin(user_id):
            await update.message.reply_text("⛔ Нет доступа")
            return

        user_state[user_id] = {"mode": "tech_card_select_product"}

        await update.message.reply_text(
            "Выберите продукт:",
            reply_markup=production_menu()
        )
        return

    # =====================
    # 💰 ЦЕНЫ ГОТОВОЙ ПРОДУКЦИИ
    # =====================
    if text == "💰 Цены":
        if not is_admin(user_id):
            await update.message.reply_text("⛔ Нет доступа")
            return

        user_state[user_id] = {"mode": "price_select_product"}

        await update.message.reply_text(
            "Выберите продукт:",
            reply_markup=production_menu()
        )
        return

    # =====================
    # 🧾 ЦЕНЫ СЫРЬЯ
    # =====================
    if text == "🧾 Цены сырья":
        if not is_admin(user_id):
            await update.message.reply_text("⛔ Нет доступа")
            return

        user_state[user_id] = {"mode": "raw_price_select_item"}

        await update.message.reply_text(
            "Выберите сырье:",
            reply_markup=tech_raw_menu()
        )
        return
    
    
    # =====================
    # ВЫБОР СЫРЬЯ ДЛЯ ЦЕНЫ СЫРЬЯ
    # =====================
    if state.get("mode") == "raw_price_select_item" and text in [
        "Крупа",
        "Сахар",
        "Сухое молоко",
        "Масло",
        "Ванилин",
        "Эссенция ваниль",
        "Эссенция сгущенка",
        "Игрушки",
        "Коробка",
        "Плёнка"
    ]:

        state["raw_item"] = text
        state["mode"] = "raw_price_enter_value"

        user_state[user_id] = state

        raw_item = text

        db = SessionLocal()

        try:
            existing = db.query(
                RawMaterialPrice
            ).filter(
                RawMaterialPrice.raw_item == raw_item
            ).first()

        finally:
            db.close()

        if existing:

            await update.message.reply_text(
                f"Сырье: {raw_item}\n\n"
                f"Текущая цена: {existing.price_per_kg} сум/кг\n\n"
                f"Введите новую цену:"
            )

        else:

            await update.message.reply_text(
                f"Сырье: {raw_item}\n\n"
                f"Цена не задана\n\n"
                f"Введите цену за 1 кг:"
            )

        return

    # =====================
    # ВВОД ЦЕНЫ СЫРЬЯ
    # =====================
    if state.get("mode") == "raw_price_enter_value":
        try:
            price_per_kg = float(text)

            raw_item = state["raw_item"]
            old_price = None

            db = SessionLocal()
            try:
                existing = db.query(RawMaterialPrice).filter(
                    RawMaterialPrice.raw_item == raw_item
                ).first()

                if existing:
                    old_price = existing.price_per_kg
                    existing.price_per_kg = price_per_kg
                else:
                    raw_price = RawMaterialPrice(
                        raw_item=raw_item,
                        price_per_kg=price_per_kg
                    )
                    db.add(raw_price)

                db.commit()

            finally:
                db.close()

            log_audit(
                user=get_audit_user(update),
                user_id=user_id,
                action="изменение цен",
                item=raw_item,
                quantity=price_per_kg,
                comment=(
                    f"Сырье; было {format_old_value(old_price)}; "
                    f"стало {price_per_kg}"
                )
            )

            await update.message.reply_text(
                f"Цена сырья сохранена:\n"
                f"{raw_item} = {price_per_kg} сум/кг",
                reply_markup=tech_raw_menu()
            )

            state["mode"] = "raw_price_select_item"
            user_state[user_id] = state
            return

        except ValueError:
            await update.message.reply_text("Введите число!")
            return

    # =====================
    # ВЫБОР ПРОДУКТА ДЛЯ ТЕХКАРТЫ
    # =====================
    if state.get("mode") == "tech_card_select_product" and text in PRODUCTS:

      brand = get_brand(text)

      state["product"] = brand
      state["mode"] = "tech_card_select_raw"

      user_state[user_id] = state

      await update.message.reply_text(
        f"Бренд: {brand}\nВыберите сырье:",
        reply_markup=tech_raw_menu()
      )
      return

    # =====================
    # ВЫБОР СЫРЬЯ ДЛЯ ТЕХКАРТЫ
    # =====================
    if state.get("mode") == "tech_card_select_raw" and text in [
        "Крупа", "Сахар", "Сухое молоко", "Масло",
        "Ванилин", "Эссенция ваниль", "Эссенция сгущенка",
        "Игрушки", "Коробка", "Плёнка"
    ]:
        state["raw_item"] = text
        state["mode"] = "tech_card_enter_grams"
        user_state[user_id] = state

        product = state["product"]
        raw_item = text

        db = SessionLocal()
        try:
            existing = db.query(TechCard).filter(
                TechCard.product == product,
                TechCard.raw_item == raw_item
            ).first()
        finally:
            db.close()

        if existing:
            await update.message.reply_text(
                f"Продукт: {product}\n"
                f"Сырье: {raw_item}\n\n"
                f"Текущая норма: {existing.grams_per_unit} г на 1 шт\n\n"
                f"Введите новую норму в граммах:"
            )
        else:
            await update.message.reply_text(
                f"Продукт: {product}\n"
                f"Сырье: {raw_item}\n\n"
                f"Норма не задана\n\n"
                f"Введите граммы на 1 шт:"
            )

        return

    # =====================
    # ВВОД ГРАММОВ ТЕХКАРТЫ
    # =====================
    if state.get("mode") == "tech_card_enter_grams":
        try:
            grams = float(text)

            product = state["product"]
            raw_item = state["raw_item"]
            old_grams = None

            db = SessionLocal()
            try:
                existing = db.query(TechCard).filter(
                    TechCard.product == product,
                    TechCard.raw_item == raw_item
                ).first()

                if existing:
                    old_grams = existing.grams_per_unit
                    existing.grams_per_unit = grams
                else:
                    tech = TechCard(
                        product=product,
                        raw_item=raw_item,
                        grams_per_unit=grams
                    )
                    db.add(tech)

                db.commit()

            finally:
                db.close()

            log_audit(
                user=get_audit_user(update),
                user_id=user_id,
                action="изменение техкарты",
                item=f"{product} / {raw_item}",
                quantity=grams,
                comment=(
                    f"Было {format_old_value(old_grams)}; "
                    f"стало {grams} г на 1 шт"
                )
            )

            await update.message.reply_text(
                f"Сохранено в техкарту:\n"
                f"{product} / {raw_item} = {grams} г на 1 шт",
                reply_markup=tech_raw_menu()
            )

            state["mode"] = "tech_card_select_raw"
            user_state[user_id] = state
            return

        except ValueError:
            await update.message.reply_text("Введите число в граммах!")
            return

    # =====================
    # ВЫБОР ПРОДУКТА ДЛЯ ЦЕНЫ ГОТОВОЙ ПРОДУКЦИИ
    # =====================
    if state.get("mode") == "price_select_product" and text in PRODUCTS:
        state["product"] = text
        state["mode"] = "price_select_place"
        user_state[user_id] = state

        await update.message.reply_text(
            f"Продукт: {text}\nВыберите канал:",
            reply_markup=shipment_place_menu()
        )
        return

    # =====================
    # ВЫБОР КАНАЛА ДЛЯ ЦЕНЫ ГОТОВОЙ ПРОДУКЦИИ
    # =====================
    if state.get("mode") == "price_select_place" and text in ["Хавас", "Склад Маруф"]:
        state["place"] = text
        state["mode"] = "price_enter_value"
        user_state[user_id] = state

        product = state["product"]
        place = text

        db = SessionLocal()
        try:
            existing = db.query(ProductPrice).filter(
                ProductPrice.product == product,
                ProductPrice.place == place
            ).first()
        finally:
            db.close()

        if existing:
            await update.message.reply_text(
                f"Продукт: {product}\n"
                f"Канал: {place}\n\n"
                f"Текущая цена: {existing.price} сум за 1 шт\n\n"
                f"Введите новую цену:"
            )
        else:
            await update.message.reply_text(
                f"Продукт: {product}\n"
                f"Канал: {place}\n\n"
                f"Цена не задана\n\n"
                f"Введите цену за 1 шт:"
            )

        return

    # =====================
    # ВВОД ЦЕНЫ ГОТОВОЙ ПРОДУКЦИИ
    # =====================
    if state.get("mode") == "price_enter_value":
        try:
            price = float(text)

            product = state["product"]
            place = state["place"]
            old_price = None

            db = SessionLocal()
            try:
                existing = db.query(ProductPrice).filter(
                    ProductPrice.product == product,
                    ProductPrice.place == place
                ).first()

                if existing:
                    old_price = existing.price
                    existing.price = price
                else:
                    product_price = ProductPrice(
                        product=product,
                        place=place,
                        price=price
                    )
                    db.add(product_price)

                db.commit()

            finally:
                db.close()

            log_audit(
                user=get_audit_user(update),
                user_id=user_id,
                action="изменение цен",
                item=f"{product} / {place}",
                quantity=price,
                comment=(
                    f"Готовая продукция; было {format_old_value(old_price)}; "
                    f"стало {price}"
                )
            )

            await update.message.reply_text(
                f"Цена сохранена:\n"
                f"{product} / {place} = {price} сум за 1 шт",
                reply_markup=shipment_place_menu()
            )

            state["mode"] = "price_select_place"
            user_state[user_id] = state
            return

        except ValueError:
            await update.message.reply_text("Введите число!")
            return

    # =====================
    # РЕЖИМЫ
    # =====================
    if text in ["📥 Приход", "📤 Расход", "⚠️ Брак"]:
        user_state[user_id] = {"mode": text}

        await update.message.reply_text(
            "Выберите товар:",
            reply_markup=items_menu()
        )
        return

    if text == "🏭 Склад":
        await update.message.reply_text(
            "Меню склада:",
            reply_markup=warehouse_menu()
        )
        return

    if text == "🏭 Производство":

        user_state[user_id] = {
            "mode": "production"
        }

        await update.message.reply_text(
            "Выберите продукцию:",
            reply_markup=production_menu()
        )
        return

    if text == "🚚 Отгрузка":
        user_state[user_id] = {
            "mode": "shipment"
        }

        await update.message.reply_text(
            "Куда отгружаем?",
            reply_markup=shipment_place_menu()
        )
        return



    # =====================
    # НАПРАВЛЕНИЕ ОТГРУЗКИ
    # =====================
    if text in ["Хавас", "Склад Маруф"]:
        if state.get("mode") != "shipment":
            return

        state["place"] = text
        user_state[user_id] = state

        await update.message.reply_text(
            "Выберите продукцию:",
            reply_markup=shipment_product_menu()
        )
        return

    # =====================
    # СЫРЬЕ
    # =====================
    if text in [
        "Крупа", "Сахар", "Сухое молоко", "Масло",
        "Ванилин", "Эссенция ваниль", "Эссенция сгущенка",
        "Игрушки", "Коробка", "Плёнка"
    ]:
        if "mode" not in state:
            return

        state["item"] = text
        user_state[user_id] = state

        balance = get_balance(text)

        await update.message.reply_text(
            f"{text}\nТекущий остаток: {balance}\nВведите количество:"
        )
        return

    # =====================
    # ПРОДУКЦИЯ
    # =====================
    if text in PRODUCTS:
        if "mode" not in state:
            return

        state["item"] = text
        user_state[user_id] = state

        balance = get_balance(text)

        if state["mode"] == "shipment":
            await update.message.reply_text(
                f"{text}\nТекущий остаток: {balance} шт\nВведите количество КОРОБОК:"
            )
        else:
            await update.message.reply_text(
                f"{text}\nТекущий остаток: {balance} шт\nВведите количество:"
            )
        return

    # =====================
    # ВВОД → ПОДТВЕРЖДЕНИЕ
    # =====================
    if "item" in state and "mode" in state:
        try:
            quantity = float(text)

            state["quantity"] = quantity
            state["pending"] = True
            user_state[user_id] = state

            await update.message.reply_text(
                f"{state['item']} — {quantity}\n"
                f"Тип: {state['mode']}\n\n"
                f"Подтвердить?",
                reply_markup=confirm_menu()
            )

        except ValueError:
            await update.message.reply_text("Введите число!")

        return

# =========================
# запуск
# =========================
async def error_handler(update, context):
    error = context.error
    runtime_metrics["handler_errors"] += 1
    runtime_metrics["last_handler_error"] = (
        f"{type(error).__name__}: {error}"
    )[:500]

    logger.error(
        "Unhandled exception while processing Telegram update",
        exc_info=(
            type(error),
            error,
            error.__traceback__,
        ),
    )

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Произошла внутренняя ошибка. Попробуйте ещё раз."
            )
        except Exception:
            logger.exception("Failed to send error message to Telegram")


def build_application():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set")

    application = ApplicationBuilder().token(BOT_TOKEN).updater(None).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )
    application.add_error_handler(error_handler)

    return application


async def run_bot():
    global bot_application, bot_event_loop

    bot_application = build_application()
    bot_event_loop = asyncio.get_running_loop()

    t = threading.Thread(
        target=run_web
    )

    t.daemon = True
    t.start()

    async with bot_application:
        await bot_application.bot.set_webhook(
            url=f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}",
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=False,
        )
        await bot_application.start()
        bot_ready.set()
        logger.info(
            "Bot webhook started at %s%s",
            WEBHOOK_BASE_URL,
            WEBHOOK_PATH,
        )

        try:
            await asyncio.Event().wait()
        finally:
            bot_ready.clear()
            await bot_application.stop()


def run():
    asyncio.run(run_bot())


if __name__ == "__main__":
    run()
