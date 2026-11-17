import sqlite3
from datetime import date, datetime
from typing import Any, Optional
from database import query_all, query_one, transaction
from services import ValidationError


VALID_TRANSACTION_TYPES = (
    "GOODS_RECEIPT",
    "STOCK_ISSUE",
    "TRANSFER_DISPATCH",
    "TRANSFER_RECEIPT",
    "TRANSFER_CANCEL",
    "SUPPLIER_RETURN",
    "ADJUSTMENT",
)


def parse_iso_date(value: Optional[str], field_label: str, required: bool = False) -> Optional[str]:
    """Validate and normalize an ISO YYYY-MM-DD date string."""
    cleaned = (value or "").strip()
    if not cleaned:
        if required:
            raise ValidationError(f"{field_label} is required.")
        return None
    try:
        parsed = datetime.strptime(cleaned, "%Y-%m-%d").date()
        return parsed.isoformat()
    except ValueError as exc:
        raise ValidationError(
            f"{field_label} must be a valid date in YYYY-MM-DD format."
        ) from exc


def record_stock_transaction(
    tx_conn: sqlite3.Connection,
    product_id: int,
    batch_id: int,
    warehouse_id: int,
    transaction_type: str,
    quantity: int,
    unit_cost: float,
    reference_type: str = "",
    reference_id: str = "",
    notes: str = "",
) -> int:
    """Insert an immutable audit record into stock_transactions within an active transaction."""
    if transaction_type not in VALID_TRANSACTION_TYPES:
        raise ValidationError(f"Unsupported transaction type '{transaction_type}'.")
    if int(quantity) == 0:
        raise ValidationError("Transaction quantity cannot be zero.")

    cursor = tx_conn.execute(
        """
        INSERT INTO stock_transactions (
            product_id, batch_id, warehouse_id, transaction_type,
            quantity, unit_cost, reference_type, reference_id, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product_id,
            batch_id,
            warehouse_id,
            transaction_type,
            int(quantity),
            float(unit_cost),
            reference_type.strip(),
            str(reference_id).strip(),
            notes.strip(),
        ),
    )
    return int(cursor.lastrowid)


def upsert_inventory_holding(
    tx_conn: sqlite3.Connection,
    warehouse_id: int,
    batch_id: int,
    product_id: int,
    quantity_delta: int,
) -> int:
    """
    Atomically adjust the inventory holding for a (warehouse_id, batch_id) pair.
    Prevents stock quantities from ever becoming negative.
    Returns the new remaining quantity at that warehouse.
    """
    existing = query_one(
        """
        SELECT id, quantity
        FROM inventory
        WHERE warehouse_id = ? AND batch_id = ?
        """,
        (warehouse_id, batch_id),
        conn=tx_conn,
    )

    if existing is None:
        if quantity_delta < 0:
            raise ValidationError(
                "Insufficient stock: cannot deduct from a batch not held at this warehouse."
            )
        tx_conn.execute(
            """
            INSERT INTO inventory (warehouse_id, batch_id, product_id, quantity, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (warehouse_id, batch_id, product_id, int(quantity_delta)),
        )
        return int(quantity_delta)

    new_qty = int(existing["quantity"]) + int(quantity_delta)
    if new_qty < 0:
        raise ValidationError(
            f"Insufficient stock: available quantity is {existing['quantity']}, "
            f"cannot deduct {abs(quantity_delta)}."
        )

    tx_conn.execute(
        """
        UPDATE inventory
        SET quantity = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (new_qty, existing["id"]),
    )
    return new_qty


def receive_batch_stock(
    product_id: int | str,
    warehouse_id: int | str,
    batch_number: str,
    quantity: int | str,
    unit_cost: float | str,
    receipt_date: Optional[str] = None,
    mfg_date: Optional[str] = None,
    expiry_date: Optional[str] = None,
    supplier_id: Optional[int | str] = None,
    reference_type: str = "DIRECT_RECEIPT",
    reference_id: str = "",
    notes: str = "",
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """
    Create or reuse a product batch, add the received quantity to the specified
    warehouse's inventory, and record a GOODS_RECEIPT stock transaction.
    """
    try:
        prod_id = int(product_id)
        wh_id = int(warehouse_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Valid product and warehouse must be selected.") from exc

    batch_code = (batch_number or "").strip().upper()
    if not batch_code:
        raise ValidationError("Batch number cannot be empty.")

    try:
        qty_int = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Quantity received must be a whole number.") from exc
    if qty_int <= 0:
        raise ValidationError("Quantity received must be greater than zero.")

    try:
        cost_float = round(float(unit_cost), 2)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Unit purchase cost must be a valid number.") from exc
    if cost_float < 0:
        raise ValidationError("Unit purchase cost cannot be negative.")

    rec_date = parse_iso_date(
        receipt_date or date.today().isoformat(), "Receipt date", required=True
    )
    mfg_iso = parse_iso_date(mfg_date, "Manufacturing date", required=False)
    exp_iso = parse_iso_date(expiry_date, "Expiry date", required=False)

    if mfg_iso and exp_iso and exp_iso < mfg_iso:
        raise ValidationError(
            "Expiry date cannot be earlier than the manufacturing date."
        )
    if mfg_iso and rec_date and mfg_iso > rec_date:
        raise ValidationError(
            "Manufacturing date cannot be later than the receipt date."
        )

    product = query_one("SELECT * FROM products WHERE id = ?", (prod_id,), conn=conn)
    if not product:
        raise ValidationError("Selected product does not exist.")

    warehouse = query_one(
        "SELECT * FROM warehouses WHERE id = ?", (wh_id,), conn=conn
    )
    if not warehouse:
        raise ValidationError("Selected warehouse does not exist.")
    if warehouse["is_active"] == 0:
        raise ValidationError(
            f"Warehouse '{warehouse['name']}' is inactive and cannot receive stock."
        )

    supp_id_int: Optional[int] = None
    if supplier_id not in (None, "", "0", 0):
        try:
            supp_id_int = int(supplier_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Invalid supplier selected.") from exc
        if not query_one("SELECT id FROM suppliers WHERE id = ?", (supp_id_int,), conn=conn):
            raise ValidationError("Selected supplier does not exist.")
    elif product["preferred_supplier_id"]:
        supp_id_int = int(product["preferred_supplier_id"])

    with transaction(conn) as tx_conn:
        existing_batch = query_one(
            """
            SELECT * FROM batches
            WHERE product_id = ? AND upper(batch_number) = ?
            """,
            (prod_id, batch_code),
            conn=tx_conn,
        )

        if existing_batch:
            if abs(float(existing_batch["unit_cost"]) - cost_float) > 0.009:
                raise ValidationError(
                    f"Batch '{batch_code}' already exists for this product with unit cost "
                    f"₹{existing_batch['unit_cost']:.2f}. Use a new batch number for a different cost."
                )
            if (existing_batch["expiry_date"] or None) != (exp_iso or None):
                raise ValidationError(
                    f"Batch '{batch_code}' already exists with expiry date "
                    f"'{existing_batch['expiry_date'] or 'None'}'."
                )
            batch_id = int(existing_batch["id"])
            tx_conn.execute(
                """
                UPDATE batches
                SET initial_quantity = initial_quantity + ?
                WHERE id = ?
                """,
                (qty_int, batch_id),
            )
        else:
            cursor = tx_conn.execute(
                """
                INSERT INTO batches (
                    batch_number, product_id, supplier_id,
                    mfg_date, expiry_date, unit_cost, receipt_date, initial_quantity
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_code,
                    prod_id,
                    supp_id_int,
                    mfg_iso,
                    exp_iso,
                    cost_float,
                    rec_date,
                    qty_int,
                ),
            )
            batch_id = int(cursor.lastrowid)

        new_wh_qty = upsert_inventory_holding(
            tx_conn=tx_conn,
            warehouse_id=wh_id,
            batch_id=batch_id,
            product_id=prod_id,
            quantity_delta=qty_int,
        )

        tx_id = record_stock_transaction(
            tx_conn=tx_conn,
            product_id=prod_id,
            batch_id=batch_id,
            warehouse_id=wh_id,
            transaction_type="GOODS_RECEIPT",
            quantity=qty_int,
            unit_cost=cost_float,
            reference_type=reference_type,
            reference_id=reference_id or batch_code,
            notes=notes or f"Batch receipt into {warehouse['warehouse_code']}",
        )

        return {
            "batch_id": batch_id,
            "batch_number": batch_code,
            "warehouse_quantity": new_wh_qty,
            "transaction_id": tx_id,
        }


def adjust_batch_stock(
    warehouse_id: int | str,
    batch_id: int | str,
    quantity_delta: int | str,
    reason: str,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """
    Record a positive or negative stock adjustment on an existing batch at a warehouse.
    Prevents negative inventory and logs an ADJUSTMENT entry in stock_transactions.
    """
    try:
        wh_id = int(warehouse_id)
        b_id = int(batch_id)
        delta_int = int(quantity_delta)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Valid warehouse, batch, and integer adjustment are required.") from exc

    if delta_int == 0:
        raise ValidationError("Adjustment quantity cannot be zero.")

    reason_clean = (reason or "").strip()
    if not reason_clean:
        raise ValidationError("An adjustment reason is required for audit traceability.")

    batch = query_one("SELECT * FROM batches WHERE id = ?", (b_id,), conn=conn)
    if not batch:
        raise ValidationError("Selected batch does not exist.")

    warehouse = query_one("SELECT * FROM warehouses WHERE id = ?", (wh_id,), conn=conn)
    if not warehouse:
        raise ValidationError("Selected warehouse does not exist.")

    with transaction(conn) as tx_conn:
        new_qty = upsert_inventory_holding(
            tx_conn=tx_conn,
            warehouse_id=wh_id,
            batch_id=b_id,
            product_id=int(batch["product_id"]),
            quantity_delta=delta_int,
        )
        record_stock_transaction(
            tx_conn=tx_conn,
            product_id=int(batch["product_id"]),
            batch_id=b_id,
            warehouse_id=wh_id,
            transaction_type="ADJUSTMENT",
            quantity=delta_int,
            unit_cost=float(batch["unit_cost"]),
            reference_type="MANUAL_ADJUSTMENT",
            reference_id=batch["batch_number"],
            notes=reason_clean,
        )
        return new_qty


def list_batch_inventory(
    warehouse_id: Optional[int] = None,
    product_id: Optional[int] = None,
    expiry_filter: Optional[str] = None,
    include_zero: bool = False,
    conn: Optional[sqlite3.Connection] = None,
) -> list[sqlite3.Row]:
    """
    Return batch-wise stock holdings across warehouses with expiry classification
    ('EXPIRED', 'NEAR_EXPIRY', 'OK', 'NON_PERISHABLE') and valuation.
    """
    conditions = []
    params: list[Any] = []

    if not include_zero:
        conditions.append("i.quantity > 0")
    if warehouse_id:
        conditions.append("i.warehouse_id = ?")
        params.append(warehouse_id)
    if product_id:
        conditions.append("i.product_id = ?")
        params.append(product_id)

    if expiry_filter == "EXPIRED":
        conditions.append(
            "b.expiry_date IS NOT NULL AND date(b.expiry_date) < date('now')"
        )
    elif expiry_filter == "NEAR_EXPIRY":
        conditions.append(
            "b.expiry_date IS NOT NULL AND date(b.expiry_date) >= date('now') "
            "AND date(b.expiry_date) <= date('now', '+30 days')"
        )
    elif expiry_filter == "ELIGIBLE":
        conditions.append(
            "(b.expiry_date IS NULL OR date(b.expiry_date) >= date('now'))"
        )

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT i.id AS inventory_id,
               i.warehouse_id,
               i.batch_id,
               i.product_id,
               i.quantity AS remaining_quantity,
               w.warehouse_code,
               w.name AS warehouse_name,
               w.is_active AS warehouse_active,
               p.sku,
               p.name AS product_name,
               p.category,
               p.unit,
               b.batch_number,
               b.mfg_date,
               b.expiry_date,
               b.receipt_date,
               b.initial_quantity,
               b.unit_cost,
               (i.quantity * b.unit_cost) AS stock_value,
               s.name AS supplier_name,
               CASE
                   WHEN b.expiry_date IS NULL THEN 'NON_PERISHABLE'
                   WHEN date(b.expiry_date) < date('now') THEN 'EXPIRED'
                   WHEN date(b.expiry_date) <= date('now', '+30 days') THEN 'NEAR_EXPIRY'
                   ELSE 'OK'
               END AS expiry_status,
               CASE
                   WHEN b.expiry_date IS NOT NULL
                   THEN CAST(julianday(date(b.expiry_date)) - julianday(date('now')) AS INTEGER)
                   ELSE NULL
               END AS days_to_expiry
        FROM inventory i
        JOIN warehouses w ON w.id = i.warehouse_id
        JOIN products p ON p.id = i.product_id
        JOIN batches b ON b.id = i.batch_id
        LEFT JOIN suppliers s ON s.id = b.supplier_id
        {where_sql}
        ORDER BY p.sku ASC, date(b.receipt_date) ASC, b.id ASC, w.warehouse_code ASC
    """
    return query_all(sql, params, conn=conn)


def list_product_stock_summary(
    conn: Optional[sqlite3.Connection] = None,
) -> list[sqlite3.Row]:
    """
    Return total stock, eligible non-expired stock, expired stock, and total valuation
    grouped by product across all warehouses.
    """
    sql = """
        SELECT p.id AS product_id,
               p.sku,
               p.name AS product_name,
               p.category,
               p.unit,
               p.reorder_level,
               COUNT(DISTINCT CASE WHEN i.quantity > 0 THEN i.batch_id END) AS active_batches,
               COUNT(DISTINCT CASE WHEN i.quantity > 0 THEN i.warehouse_id END) AS warehouses_holding,
               COALESCE(SUM(i.quantity), 0) AS total_quantity,
               COALESCE(SUM(
                   CASE
                       WHEN w.is_active = 1
                        AND (b.expiry_date IS NULL OR date(b.expiry_date) >= date('now'))
                       THEN i.quantity
                       ELSE 0
                   END
               ), 0) AS eligible_quantity,
               COALESCE(SUM(
                   CASE
                       WHEN b.expiry_date IS NOT NULL AND date(b.expiry_date) < date('now')
                       THEN i.quantity
                       ELSE 0
                   END
               ), 0) AS expired_quantity,
               COALESCE(SUM(i.quantity * b.unit_cost), 0.0) AS total_value
        FROM products p
        LEFT JOIN inventory i ON i.product_id = p.id
        LEFT JOIN batches b ON b.id = i.batch_id
        LEFT JOIN warehouses w ON w.id = i.warehouse_id
        GROUP BY p.id
        ORDER BY p.sku ASC
    """
    return query_all(sql, conn=conn)


def get_expiry_alerts(
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, list[sqlite3.Row]]:
    """Return separate lists of expired and near-expiry batch holdings."""
    expired = list_batch_inventory(expiry_filter="EXPIRED", conn=conn)
    near_expiry = list_batch_inventory(expiry_filter="NEAR_EXPIRY", conn=conn)
    return {"expired": expired, "near_expiry": near_expiry}


def list_stock_transactions(
    product_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    transaction_type: Optional[str] = None,
    limit: int = 200,
    conn: Optional[sqlite3.Connection] = None,
) -> list[sqlite3.Row]:
    """Return stock transaction history filtered by product, warehouse, or type."""
    conditions = []
    params: list[Any] = []

    if product_id:
        conditions.append("st.product_id = ?")
        params.append(product_id)
    if warehouse_id:
        conditions.append("st.warehouse_id = ?")
        params.append(warehouse_id)
    if transaction_type:
        conditions.append("st.transaction_type = ?")
        params.append(transaction_type)

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(int(limit))

    sql = f"""
        SELECT st.*,
               p.sku,
               p.name AS product_name,
               p.unit,
               b.batch_number,
               b.expiry_date,
               w.warehouse_code,
               w.name AS warehouse_name
        FROM stock_transactions st
        JOIN products p ON p.id = st.product_id
        JOIN batches b ON b.id = st.batch_id
        JOIN warehouses w ON w.id = st.warehouse_id
        {where_sql}
        ORDER BY st.id DESC
        LIMIT ?
    """
    return query_all(sql, params, conn=conn)
