import os
import json
import gspread

from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime


SHEET_NAME = "Snack ERP"

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

google_creds = json.loads(
    os.getenv("GOOGLE_CREDENTIALS")
)

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    google_creds,
    scope
)

client = gspread.authorize(creds)

spreadsheet = client.open(SHEET_NAME)


# ====================================
# СОЗДАНИЕ ЛИСТОВ
# ====================================

def get_or_create_worksheet(title, rows=1000, cols=30):
    try:
        return spreadsheet.worksheet(title)

    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(
            title=title,
            rows=rows,
            cols=cols
        )


MOVEMENTS = get_or_create_worksheet("Movements")
SHIPMENTS = get_or_create_worksheet("Shipments")
DAILY = get_or_create_worksheet("Daily")
RAW = get_or_create_worksheet("Raw")
STOCK = get_or_create_worksheet("Stock")
ERRORS = get_or_create_worksheet("Errors")
AUDIT_LOG = get_or_create_worksheet("Audit Log")


# ====================================
# ЗАГОЛОВКИ
# ====================================

def ensure_headers():

    if MOVEMENTS.row_count > 0 and not MOVEMENTS.cell(1, 1).value:
        MOVEMENTS.append_row([
            "datetime",
            "type",
            "item",
            "quantity",
            "place",
            "revenue"
        ])

    if SHIPMENTS.row_count > 0 and not SHIPMENTS.cell(1, 1).value:
        SHIPMENTS.append_row([
            "datetime",
            "place",
            "product",
            "qty_pcs",
            "qty_boxes",
            "price_per_piece",
            "revenue"
        ])

    if DAILY.row_count > 0 and not DAILY.cell(1, 1).value:
        DAILY.append_row([
            "date",
            "produced_total",
            "shipped_total",
            "revenue",
            "fact_cost",
            "norm_cost",
            "raw_loss",
            "profit",
            "margin"
        ])

    if RAW.row_count > 0 and not RAW.cell(1, 1).value:
        RAW.append_row([
            "date",
            "raw_item",
            "fact_usage",
            "norm_usage",
            "diff_kg",
            "diff_percent",
            "price_per_kg",
            "loss_money"
        ])

    if STOCK.row_count > 0 and not STOCK.cell(1, 1).value:
        STOCK.append_row([
            "date",
            "item",
            "balance",
            "status"
        ])

    if ERRORS.row_count > 0 and not ERRORS.cell(1, 1).value:
        ERRORS.append_row([
            "datetime",
            "type",
            "item",
            "description"
        ])

    if AUDIT_LOG.row_count > 0 and not AUDIT_LOG.cell(1, 1).value:
        AUDIT_LOG.append_row([
            "date",
            "user",
            "user_id",
            "action",
            "item",
            "quantity",
            "comment"
        ])


ensure_headers()


# ====================================
# ОБРАТНАЯ СОВМЕСТИМОСТЬ
# ====================================

def log_to_sheet(type_, item, quantity, place=None, revenue=None):
    """
    Старый метод.
    Не ломаем существующий main.py
    """

    log_movement(
        type_=type_,
        item=item,
        quantity=quantity,
        place=place,
        revenue=revenue
    )


# ====================================
# ДВИЖЕНИЯ
# ====================================

def log_movement(type_, item, quantity, place=None, revenue=None):

    MOVEMENTS.append_row([
        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        type_,
        item,
        quantity,
        place or "",
        revenue or ""
    ])


# ====================================
# AUDIT LOG
# ====================================

def log_audit(user, user_id, action, item, quantity="", comment=""):
    try:
        AUDIT_LOG.append_row([
            datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            user or "",
            user_id or "",
            action or "",
            item or "",
            quantity,
            comment or ""
        ])
    except Exception as exc:
        print(f"Audit log error: {exc}")


# ====================================
# ОТГРУЗКИ
# ====================================

def log_shipment(
    place,
    product,
    qty_pcs,
    qty_boxes,
    price_per_piece,
    revenue
):

    SHIPMENTS.append_row([
        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        place,
        product,
        qty_pcs,
        qty_boxes,
        price_per_piece,
        revenue
    ])


# ====================================
# DAILY REPORT
# ====================================

def sync_daily_report(report):

    DAILY.append_row([
        datetime.utcnow().strftime("%Y-%m-%d"),
        report.get("produced", 0),
        report.get("shipped", 0),
        report.get("revenue", 0),
        report.get("cost", 0),
        report.get("norm_cost", 0),
        report.get("raw_loss_money", 0),
        report.get("profit", 0),
        report.get("margin", 0),
    ])


# ====================================
# RAW REPORT
# ====================================

def sync_raw_report(report):

    for item, data in report["deviations"].items():

        RAW.append_row([
            datetime.utcnow().strftime("%Y-%m-%d"),
            item,
            data["fact"],
            data["norm"],
            data["diff"],
            round(data["percent"], 2),
            data.get("price", 0),
            data.get("diff_money", 0)
        ])


# ====================================
# STOCK REPORT
# ====================================

def sync_stock_report(stock_data):

    for item, balance in stock_data.items():

        status = "OK"

        if balance <= 0:
            status = "NEGATIVE"

        elif balance < 10:
            status = "LOW"

        STOCK.append_row([
            datetime.utcnow().strftime("%Y-%m-%d"),
            item,
            balance,
            status
        ])


# ====================================
# ERRORS
# ====================================

def log_error(error_type, item, description):

    ERRORS.append_row([
        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        error_type,
        item,
        description
    ])
