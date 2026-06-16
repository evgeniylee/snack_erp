from db.database import SessionLocal
from db.models import InventoryMovement


def get_balance(item_name):
    db = SessionLocal()
    try:
        movements = db.query(InventoryMovement).filter(
            InventoryMovement.item == item_name
        ).all()

        balance = 0

        for m in movements:
            if m.type == "📥 Приход":
                balance += m.quantity
            elif m.type == "📤 Расход":
                balance -= m.quantity
            elif m.type == "⚠️ Брак":
                balance -= m.quantity
            elif m.type == "production":
                balance += m.quantity
            elif m.type == "shipment":
                balance -= m.quantity

        return balance

    except Exception as e:
        print("ERROR BALANCE:", e)
        return 0

    finally:
        db.close()