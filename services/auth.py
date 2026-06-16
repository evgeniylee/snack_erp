# services/auth.py

from sqlalchemy.exc import SQLAlchemyError

from db.database import SessionLocal, engine
from db.models import UserRole


# 👉 впиши сюда реальные user_id из Telegram
# Эти админы автоматически попадают в таблицу user_roles.
ADMINS = {
    2071181,   # <-- твой user_id
}

ROLE_ADMIN = "admin"
ROLE_TECHNOLOGIST = "technologist"

WORKERS = {
    # если пусто — все, кто не админ, считаются worker
    # можно потом добавить конкретных
}


def ensure_user_roles_table():
    UserRole.__table__.create(bind=engine, checkfirst=True)


def ensure_default_admins(db):
    for admin_id in ADMINS:
        existing = db.query(UserRole).filter(
            UserRole.user_id == admin_id,
            UserRole.role == ROLE_ADMIN
        ).first()

        if not existing:
            db.add(UserRole(
                user_id=admin_id,
                role=ROLE_ADMIN
            ))

    db.commit()


def has_role(user_id: int, role: str) -> bool:
    ensure_user_roles_table()

    db = SessionLocal()
    try:
        ensure_default_admins(db)

        return db.query(UserRole).filter(
            UserRole.user_id == user_id,
            UserRole.role == role
        ).first() is not None

    except SQLAlchemyError:
        db.rollback()
        raise

    finally:
        db.close()


def is_admin(user_id: int) -> bool:
    return has_role(user_id, ROLE_ADMIN)


def is_technologist(user_id: int) -> bool:
    return has_role(user_id, ROLE_TECHNOLOGIST)


def is_worker(user_id: int) -> bool:
    # если список WORKERS пуст — любой не-админ считается worker
    if not WORKERS:
        return not is_admin(user_id)
    return user_id in WORKERS


def get_admins():
    ensure_user_roles_table()

    db = SessionLocal()
    try:
        ensure_default_admins(db)

        rows = db.query(UserRole).filter(
            UserRole.role == ROLE_ADMIN
        ).all()

        return [row.user_id for row in rows]

    except SQLAlchemyError:
        db.rollback()
        raise

    finally:
        db.close()


def add_technologist(user_id: int):
    ensure_user_roles_table()

    db = SessionLocal()
    try:
        ensure_default_admins(db)

        existing = db.query(UserRole).filter(
            UserRole.user_id == user_id,
            UserRole.role == ROLE_TECHNOLOGIST
        ).first()

        if existing:
            return False

        db.add(UserRole(
            user_id=user_id,
            role=ROLE_TECHNOLOGIST
        ))
        db.commit()

        return True

    except SQLAlchemyError:
        db.rollback()
        raise

    finally:
        db.close()


def remove_technologist(user_id: int):
    ensure_user_roles_table()

    db = SessionLocal()
    try:
        ensure_default_admins(db)

        rows = db.query(UserRole).filter(
            UserRole.user_id == user_id,
            UserRole.role == ROLE_TECHNOLOGIST
        ).all()

        if not rows:
            return False

        for row in rows:
            db.delete(row)

        db.commit()

        return True

    except SQLAlchemyError:
        db.rollback()
        raise

    finally:
        db.close()


def get_technologists():
    ensure_user_roles_table()

    db = SessionLocal()
    try:
        ensure_default_admins(db)

        rows = db.query(UserRole).filter(
            UserRole.role == ROLE_TECHNOLOGIST
        ).order_by(
            UserRole.user_id
        ).all()

        return [row.user_id for row in rows]

    except SQLAlchemyError:
        db.rollback()
        raise

    finally:
        db.close()
