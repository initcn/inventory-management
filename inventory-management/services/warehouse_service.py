import sqlite3
from typing import Optional
from database import query_all, query_one, transaction
from services import ValidationError


def _validate_warehouse_payload(
    warehouse_code: str, name: str, location: str, address: str
) -> tuple[str, str, str, str]:
    """Validate and normalize warehouse fields."""
    code_clean = (warehouse_code or "").strip().upper()
    name_clean = (name or "").strip()
    loc_clean = (location or "").strip()
    addr_clean = (address or "").strip()

    if not code_clean:
        raise ValidationError("Warehouse code cannot be empty.")
    if not name_clean:
        raise ValidationError("Warehouse name cannot be empty.")
    if not loc_clean:
        raise ValidationError("Warehouse location cannot be empty.")

    return code_clean, name_clean, loc_clean, addr_clean


def list_warehouses(
    active_only: bool = False, conn: Optional[sqlite3.Connection] = None
) -> list[sqlite3.Row]:
    """Return all warehouses with total physical units, distinct SKUs, and stock value."""
    where_clause = "WHERE w.is_active = 1" if active_only else ""
    sql = f"""
        SELECT w.*,
               COALESCE(SUM(i.quantity), 0) AS total_units,
               COUNT(DISTINCT CASE WHEN i.quantity > 0 THEN i.product_id END) AS distinct_products,
               COALESCE(SUM(i.quantity * b.unit_cost), 0.0) AS total_stock_value
        FROM warehouses w
        LEFT JOIN inventory i ON i.warehouse_id = w.id
        LEFT JOIN batches b ON b.id = i.batch_id
        {where_clause}
        GROUP BY w.id
        ORDER BY w.warehouse_code ASC
    """
    return query_all(sql, conn=conn)


def get_warehouse(
    warehouse_id: int, conn: Optional[sqlite3.Connection] = None
) -> Optional[sqlite3.Row]:
    """Fetch a single warehouse by primary key."""
    return query_one(
        "SELECT * FROM warehouses WHERE id = ?", (warehouse_id,), conn=conn
    )


def create_warehouse(
    warehouse_code: str,
    name: str,
    location: str,
    address: str = "",
    is_active: bool = True,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Create a new warehouse after validating code uniqueness and required fields."""
    code_c, name_c, loc_c, addr_c = _validate_warehouse_payload(
        warehouse_code, name, location, address
    )
    active_flag = 1 if is_active else 0

    existing = query_one(
        "SELECT id FROM warehouses WHERE upper(warehouse_code) = ?",
        (code_c,),
        conn=conn,
    )
    if existing:
        raise ValidationError(f"Warehouse code '{code_c}' already exists.")

    with transaction(conn) as tx_conn:
        cursor = tx_conn.execute(
            """
            INSERT INTO warehouses (warehouse_code, name, location, address, is_active)
            VALUES (?, ?, ?, ?, ?)
            """,
            (code_c, name_c, loc_c, addr_c, active_flag),
        )
        return int(cursor.lastrowid)


def update_warehouse(
    warehouse_id: int,
    warehouse_code: str,
    name: str,
    location: str,
    address: str = "",
    is_active: bool = True,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Update an existing warehouse's details and active status."""
    target = get_warehouse(warehouse_id, conn=conn)
    if not target:
        raise ValidationError("Warehouse not found.")

    code_c, name_c, loc_c, addr_c = _validate_warehouse_payload(
        warehouse_code, name, location, address
    )
    active_flag = 1 if is_active else 0

    duplicate = query_one(
        "SELECT id FROM warehouses WHERE upper(warehouse_code) = ? AND id != ?",
        (code_c, warehouse_id),
        conn=conn,
    )
    if duplicate:
        raise ValidationError(
            f"Another warehouse already uses code '{code_c}'."
        )

    with transaction(conn) as tx_conn:
        tx_conn.execute(
            """
            UPDATE warehouses
            SET warehouse_code = ?,
                name = ?,
                location = ?,
                address = ?,
                is_active = ?
            WHERE id = ?
            """,
            (code_c, name_c, loc_c, addr_c, active_flag, warehouse_id),
        )


def get_warehouse_stock(
    warehouse_id: int, conn: Optional[sqlite3.Connection] = None
) -> list[sqlite3.Row]:
    """
    Return all batch stock rows currently held at a specific warehouse,
    including expiry status flags and batch valuation.
    """
    sql = """
        SELECT i.id AS inventory_id,
               i.quantity,
               p.id AS product_id,
               p.sku,
               p.name AS product_name,
               p.category,
               p.unit,
               b.id AS batch_id,
               b.batch_number,
               b.mfg_date,
               b.expiry_date,
               b.receipt_date,
               b.unit_cost,
               (i.quantity * b.unit_cost) AS batch_value,
               CASE
                   WHEN b.expiry_date IS NOT NULL AND date(b.expiry_date) < date('now')
                   THEN 'EXPIRED'
                   WHEN b.expiry_date IS NOT NULL AND date(b.expiry_date) <= date('now', '+30 days')
                   THEN 'NEAR_EXPIRY'
                   ELSE 'OK'
               END AS expiry_status
        FROM inventory i
        JOIN products p ON p.id = i.product_id
        JOIN batches b ON b.id = i.batch_id
        WHERE i.warehouse_id = ? AND i.quantity > 0
        ORDER BY p.sku ASC, date(b.receipt_date) ASC, b.id ASC
    """
    return query_all(sql, (warehouse_id,), conn=conn)
