from datetime import date, timedelta
from sqlalchemy import func

from config.brands import get_brand

from db.database import SessionLocal
from db.models import InventoryMovement, TechCard, RawMaterialPrice


def get_raw_price_map(db):
    rows = db.query(RawMaterialPrice).all()

    return {
        row.raw_item: float(row.price_per_kg or 0)
        for row in rows
    }


def get_period_dates(period):
    today = date.today()

    if period == "day":
        return today, today

    if period == "week":
        return today - timedelta(days=6), today

    if period == "month":
        return today - timedelta(days=29), today

    raise ValueError("Unknown report period")


def get_report(period):
    start_date, end_date = get_period_dates(period)

    db = SessionLocal()

    try:
        # =========================
        # произведено сегодня
        # =========================
        produced_rows = db.query(
            InventoryMovement.item,
            func.sum(InventoryMovement.quantity)
        ).filter(
            func.date(InventoryMovement.created_at).between(
                start_date,
                end_date
            ),
            InventoryMovement.type == "production"
        ).group_by(
            InventoryMovement.item
        ).all()

        produced_by_product = {
            item: float(qty or 0)
            for item, qty in produced_rows
        }

        produced_total = sum(produced_by_product.values())

        # =========================
        # отгружено сегодня
        # =========================
        shipped_qty = db.query(
            func.sum(InventoryMovement.quantity)
        ).filter(
            func.date(InventoryMovement.created_at).between(
                start_date,
                end_date
            ),
            InventoryMovement.type == "shipment"
        ).scalar() or 0

        shipped_qty = float(shipped_qty)

        # =========================
        # выручка сегодня
        # =========================
        revenue = db.query(
            func.sum(InventoryMovement.revenue)
        ).filter(
            func.date(InventoryMovement.created_at).between(
                start_date,
                end_date
            ),
            InventoryMovement.type == "shipment"
        ).scalar() or 0

        revenue = float(revenue)

        # =========================
        # фактический расход сырья сегодня
        # =========================
        raw_fact_rows = db.query(
            InventoryMovement.item,
            func.sum(InventoryMovement.quantity)
        ).filter(
            func.date(InventoryMovement.created_at).between(
                start_date,
                end_date
            ),
            InventoryMovement.type == "📤 Расход"
        ).group_by(
            InventoryMovement.item
        ).all()

        raw_fact = {
            item: float(qty or 0)
            for item, qty in raw_fact_rows
        }

        # =========================
        # нормативный расход по техкарте
        # =========================
        raw_norm = {}

        for product, produced_qty in produced_by_product.items():

            brand = get_brand(product)

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

                norm_kg = (
                    produced_qty *
                    grams_per_unit /
                    1000
                )

                raw_norm[raw_item] = (
                    raw_norm.get(raw_item, 0)
                    + norm_kg
                )

        # =========================
        # цены сырья
        # =========================
        raw_prices = get_raw_price_map(db)

        # =========================
        # себестоимость
        # =========================
        fact_cost_by_item = {}
        norm_cost_by_item = {}

        for item, qty in raw_fact.items():
            price = raw_prices.get(item, 0)
            fact_cost_by_item[item] = qty * price

        for item, qty in raw_norm.items():
            price = raw_prices.get(item, 0)
            norm_cost_by_item[item] = qty * price

        fact_cost = sum(
            fact_cost_by_item.values()
        )

        norm_cost = sum(
            norm_cost_by_item.values()
        )

        raw_loss_money = (
            fact_cost - norm_cost
        )

        profit = revenue - fact_cost

        if revenue > 0:
            margin = (
                profit / revenue * 100
            )
        else:
            margin = 0

        # =========================
        # отклонения
        # =========================
        deviations = {}

        all_raw_items = (
            set(raw_fact.keys()) |
            set(raw_norm.keys())
        )

        for item in all_raw_items:

            fact = raw_fact.get(item, 0)
            norm = raw_norm.get(item, 0)

            diff = fact - norm

            if norm > 0:
                percent = (
                    diff / norm * 100
                )
            else:
                percent = 0

            if abs(percent) <= 5:
                status = "OK"
            elif percent > 5:
                status = "ПЕРЕРАСХОД"
            else:
                status = "ЭКОНОМИЯ"

            price = raw_prices.get(item, 0)

            diff_money = diff * price

            deviations[item] = {
                "fact": fact,
                "norm": norm,
                "diff": diff,
                "percent": percent,
                "status": status,
                "price": price,
                "diff_money": diff_money,
                "fact_cost": fact_cost_by_item.get(item, 0),
                "norm_cost": norm_cost_by_item.get(item, 0),
            }

        return {
            "period": period,
            "start_date": start_date,
            "end_date": end_date,

            "produced": produced_total,
            "produced_by_product": produced_by_product,

            "shipped": shipped_qty,
            "revenue": revenue,

            "cost": fact_cost,
            "norm_cost": norm_cost,
            "raw_loss_money": raw_loss_money,

            "profit": profit,
            "margin": margin,

            "raw_usage": raw_fact,
            "raw_norm": raw_norm,

            "raw_prices": raw_prices,

            "fact_cost_by_item": fact_cost_by_item,
            "norm_cost_by_item": norm_cost_by_item,

            "deviations": deviations
        }

    finally:
        db.close()


def get_daily_report():
    return get_report("day")
