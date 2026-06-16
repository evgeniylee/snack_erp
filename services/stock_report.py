from sqlalchemy import func

from db.database import SessionLocal
from db.models import InventoryMovement


def get_all_stock():

    db = SessionLocal()

    try:
        rows = db.query(
            InventoryMovement.item,
            InventoryMovement.type,
            func.sum(InventoryMovement.quantity)
        ).group_by(
            InventoryMovement.item,
            InventoryMovement.type
        ).all()

        balances = {}

        for item, movement_type, qty in rows:

            qty = float(qty or 0)

            if item not in balances:
                balances[item] = 0

            # приход
            if movement_type in ["📥 Приход", "production"]:
                balances[item] += qty

            # расход
            elif movement_type in ["📤 Расход", "shipment", "⚠️ Брак"]:
                balances[item] -= qty

        return balances

    finally:
        db.close()


def get_stock_status(balance):

    if balance < 0:
        return "NEGATIVE"

    if balance < 10:
        return "LOW"

    return "OK"