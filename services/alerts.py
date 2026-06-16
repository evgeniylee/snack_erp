from datetime import date
from sqlalchemy import func

from db.database import SessionLocal
from db.models import InventoryMovement, TechCard


def check_negative_stock(item, balance):
    if balance < 0:
        return f"🚨 Минусовой остаток: {item} = {balance}"

    return None


def check_deviation_alerts():
    today = date.today()
    db = SessionLocal()

    try:
        # =========================
        # произведено сегодня
        # =========================
        produced_rows = db.query(
            InventoryMovement.item,
            func.sum(InventoryMovement.quantity)
        ).filter(
            func.date(InventoryMovement.created_at) == today,
            InventoryMovement.type == "production"
        ).group_by(
            InventoryMovement.item
        ).all()

        produced_by_product = {
            item: float(qty or 0)
            for item, qty in produced_rows
        }

        # если сегодня производства нет — алерты по потерям не считаем
        if not produced_by_product:
            return []

        # =========================
        # фактический расход сырья сегодня
        # =========================
        raw_fact_rows = db.query(
            InventoryMovement.item,
            func.sum(InventoryMovement.quantity)
        ).filter(
            func.date(InventoryMovement.created_at) == today,
            InventoryMovement.type == "📤 Расход"
        ).group_by(
            InventoryMovement.item
        ).all()

        raw_fact = {
            item: float(qty or 0)
            for item, qty in raw_fact_rows
        }

        # =========================
        # нормативный расход по техкарте из БД
        # =========================
        raw_norm = {}

        for product, produced_qty in produced_by_product.items():
            tech_rows = db.query(TechCard).filter(
                TechCard.product == product
            ).all()

            for tech in tech_rows:
                raw_item = tech.raw_item
                grams_per_unit = float(tech.grams_per_unit or 0)

                norm_kg = produced_qty * grams_per_unit / 1000

                raw_norm[raw_item] = raw_norm.get(raw_item, 0) + norm_kg

        # =========================
        # алерты по отклонениям
        # =========================
        alerts = []

        all_raw_items = set(raw_fact.keys()) | set(raw_norm.keys())

        for item in all_raw_items:
            fact = raw_fact.get(item, 0)
            norm = raw_norm.get(item, 0)

            if norm <= 0:
                continue

            diff = fact - norm
            percent = diff / norm * 100

            if percent > 5:
                alerts.append(
                    f"🚨 Перерасход сырья: {item}\n"
                    f"Факт: {fact:.2f}\n"
                    f"Норма: {norm:.2f}\n"
                    f"Отклонение: {diff:.2f} кг ({percent:.1f}%)"
                )

        return alerts

    finally:
        db.close()