import sqlite3
from datetime import date
from typing import Any, Optional
from database import query_all, query_one, transaction
from services import ValidationError
from services.inventory_service import (
    parse_iso_date,
    record_stock_transaction,
    upsert_inventory_holding,
)


def _next_return_number(tx_conn: sqlite3.Connection) -> str:
    """Generate a sequential supplier return document number (e.g., RET-2026-0001)."""
    row = query_one("SELECT COUNT(*) AS cnt FROM supplier_returns", conn=tx_conn)
    seq = (int(row["cnt"]) if row else 0) + 1
    year_str = date.today().strftime("%Y")
    candidate = f"RET-{year_str}-{seq:04d}"
    while query_one(
        "SELECT id FROM supplier_returns WHERE return_number = ?",
        (candidate,),
        conn=tx_conn,
    ):
        seq += 1
        candidate = f"RET-{year_str}-{seq:04d}"
    return candidate


def process_supplier_return(
    supplier_id: int | str,
    warehouse_id: int | str,
    batch_id: int | str,
    return_quantity: int | str,
    reason: str,
    return_date: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """
    Process a stock return to a supplier for a specific batch at a warehouse.
    Validates that return_quantity does not exceed remaining batch stock at that warehouse,
    deducts inventory without deleting historical records, and logs a SUPPLIER_RETURN transaction.
    """
    try:
        supp_id = int(supplier_id)
        wh_id = int(warehouse_id)
        b_id = int(batch_id)
        qty_int = int(return_quantity)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "Valid supplier, warehouse, batch, and integer return quantity are required."
        ) from exc

    if qty_int <= 0:
        raise ValidationError("Return quantity must be greater than zero.")

    reason_clean = (reason or "").strip()
    if not reason_clean:
        raise ValidationError("A return reason is required.")

    ret_date = parse_iso_date(
        return_date or date.today().isoformat(), "Return date", required=True
    )

    supplier = query_one("SELECT * FROM suppliers WHERE id = ?", (supp_id,), conn=conn)
    if not supplier:
        raise ValidationError("Selected supplier does not exist.")

    warehouse = query_one("SELECT * FROM warehouses WHERE id = ?", (wh_id,), conn=conn)
    if not warehouse:
        raise ValidationError("Selected warehouse does not exist.")

    holding = query_one(
        """
        SELECT i.quantity AS remaining_quantity,
               b.id AS batch_id,
               b.batch_number,
               b.product_id,
               b.supplier_id AS batch_supplier_id,
               b.unit_cost,
               p.sku,
               p.name AS product_name
        FROM inventory i
        JOIN batches b ON b.id = i.batch_id
        JOIN products p ON p.id = i.product_id
        WHERE i.warehouse_id = ? AND i.batch_id = ?
        """,
        (wh_id, b_id),
        conn=conn,
    )
    if not holding or int(holding["remaining_quantity"]) <= 0:
        raise ValidationError(
            "Selected batch has no remaining stock at the specified warehouse."
        )

    if qty_int > int(holding["remaining_quantity"]):
        raise ValidationError(
            f"Return quantity ({qty_int}) cannot exceed remaining stock "
            f"({holding['remaining_quantity']}) for batch '{holding['batch_number']}'."
        )

    with transaction(conn) as tx_conn:
        ret_number = _next_return_number(tx_conn)
        cursor = tx_conn.execute(
            """
            INSERT INTO supplier_returns (
                return_number, supplier_id, warehouse_id, return_date, reason, status
            )
            VALUES (?, ?, ?, ?, ?, 'Completed')
            """,
            (ret_number, supp_id, wh_id, ret_date, reason_clean),
        )
        return_id = int(cursor.lastrowid)

        prod_id = int(holding["product_id"])
        unit_cost = float(holding["unit_cost"])

        tx_conn.execute(
            """
            INSERT INTO supplier_return_items (
                return_id, product_id, batch_id, quantity, unit_cost
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (return_id, prod_id, b_id, qty_int, unit_cost),
        )

        new_remaining = upsert_inventory_holding(
            tx_conn=tx_conn,
            warehouse_id=wh_id,
            batch_id=b_id,
            product_id=prod_id,
            quantity_delta=-qty_int,
        )

        record_stock_transaction(
            tx_conn=tx_conn,
            product_id=prod_id,
            batch_id=b_id,
            warehouse_id=wh_id,
            transaction_type="SUPPLIER_RETURN",
            quantity=-qty_int,
            unit_cost=unit_cost,
            reference_type="SUPPLIER_RETURN",
            reference_id=ret_number,
            notes=f"Returned to {supplier['supplier_code']}: {reason_clean}",
        )

        return {
            "return_id": return_id,
            "return_number": ret_number,
            "quantity_returned": qty_int,
            "return_value": round(qty_int * unit_cost, 2),
            "remaining_batch_quantity": new_remaining,
        }


def list_supplier_returns(
    conn: Optional[sqlite3.Connection] = None,
) -> list[sqlite3.Row]:
    """Return all recorded supplier returns with batch, product, supplier, and cost details."""
    sql = """
        SELECT sr.id,
               sr.return_number,
               sr.return_date,
               sr.reason,
               sr.status,
               s.supplier_code,
               s.name AS supplier_name,
               w.warehouse_code,
               w.name AS warehouse_name,
               p.sku,
               p.name AS product_name,
               p.unit,
               b.batch_number,
               b.expiry_date,
               sri.quantity,
               sri.unit_cost,
               (sri.quantity * sri.unit_cost) AS return_value
        FROM supplier_return_items sri
        JOIN supplier_returns sr ON sr.id = sri.return_id
        JOIN suppliers s ON s.id = sr.supplier_id
        JOIN warehouses w ON w.id = sr.warehouse_id
        JOIN products p ON p.id = sri.product_id
        JOIN batches b ON b.id = sri.batch_id
        ORDER BY sr.id DESC
    """
    return query_all(sql, conn=conn)
