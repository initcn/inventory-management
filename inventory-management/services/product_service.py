import sqlite3
from typing import Optional
from database import query_all, query_one, transaction
from services import ValidationError


def _validate_product_payload(
    sku: str,
    name: str,
    description: str,
    category: str,
    unit: str,
    reorder_level: int | str,
    preferred_supplier_id: Optional[int | str],
    conn: Optional[sqlite3.Connection] = None,
) -> tuple[str, str, str, str, str, int, Optional[int]]:
    """Validate and normalize product fields."""
    sku_clean = (sku or "").strip().upper()
    name_clean = (name or "").strip()
    desc_clean = (description or "").strip()
    cat_clean = (category or "").strip()
    unit_clean = (unit or "").strip() or "Units"

    if not sku_clean:
        raise ValidationError("Product SKU cannot be empty.")
    if not name_clean:
        raise ValidationError("Product name cannot be empty.")
    if not cat_clean:
        raise ValidationError("Product category cannot be empty.")

    try:
        reorder_int = int(reorder_level)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Reorder level must be a valid integer.") from exc

    if reorder_int < 0:
        raise ValidationError("Reorder level cannot be negative.")

    supplier_id_int: Optional[int] = None
    if preferred_supplier_id not in (None, "", "0", 0):
        try:
            supplier_id_int = int(preferred_supplier_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Selected supplier is invalid.") from exc

        supplier_row = query_one(
            "SELECT id FROM suppliers WHERE id = ?",
            (supplier_id_int,),
            conn=conn,
        )
        if not supplier_row:
            raise ValidationError("Selected supplier does not exist.")

    return (
        sku_clean,
        name_clean,
        desc_clean,
        cat_clean,
        unit_clean,
        reorder_int,
        supplier_id_int,
    )


def list_products(conn: Optional[sqlite3.Connection] = None) -> list[sqlite3.Row]:
    """
    List all products with preferred supplier info, total physical stock,
    eligible (non-expired) stock across active warehouses, and dependency count.
    """
    sql = """
        SELECT p.*,
               s.name AS supplier_name,
               s.supplier_code AS supplier_code,
               COALESCE(SUM(i.quantity), 0) AS total_stock,
               COALESCE(SUM(
                   CASE
                       WHEN w.is_active = 1
                        AND (b.expiry_date IS NULL OR date(b.expiry_date) >= date('now'))
                       THEN i.quantity
                       ELSE 0
                   END
               ), 0) AS available_stock,
               (
                   (SELECT COUNT(*) FROM batches b2 WHERE b2.product_id = p.id) +
                   (SELECT COUNT(*) FROM purchase_order_items poi WHERE poi.product_id = p.id) +
                   (SELECT COUNT(*) FROM stock_transactions st WHERE st.product_id = p.id)
               ) AS dependency_count
        FROM products p
        LEFT JOIN suppliers s ON s.id = p.preferred_supplier_id
        LEFT JOIN inventory i ON i.product_id = p.id
        LEFT JOIN batches b ON b.id = i.batch_id
        LEFT JOIN warehouses w ON w.id = i.warehouse_id
        GROUP BY p.id
        ORDER BY p.sku ASC
    """
    return query_all(sql, conn=conn)


def get_product(
    product_id: int, conn: Optional[sqlite3.Connection] = None
) -> Optional[sqlite3.Row]:
    """Fetch a single product by primary key."""
    return query_one(
        "SELECT * FROM products WHERE id = ?", (product_id,), conn=conn
    )


def create_product(
    sku: str,
    name: str,
    description: str,
    category: str,
    unit: str,
    reorder_level: int | str,
    preferred_supplier_id: Optional[int | str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Create a new product after validating SKU uniqueness and constraints."""
    (
        sku_c,
        name_c,
        desc_c,
        cat_c,
        unit_c,
        reorder_i,
        supplier_id_i,
    ) = _validate_product_payload(
        sku,
        name,
        description,
        category,
        unit,
        reorder_level,
        preferred_supplier_id,
        conn=conn,
    )

    existing = query_one(
        "SELECT id FROM products WHERE upper(sku) = ?", (sku_c,), conn=conn
    )
    if existing:
        raise ValidationError(f"Product with SKU '{sku_c}' already exists.")

    with transaction(conn) as tx_conn:
        cursor = tx_conn.execute(
            """
            INSERT INTO products (
                sku, name, description, category, unit, reorder_level, preferred_supplier_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (sku_c, name_c, desc_c, cat_c, unit_c, reorder_i, supplier_id_i),
        )
        return int(cursor.lastrowid)


def update_product(
    product_id: int,
    sku: str,
    name: str,
    description: str,
    category: str,
    unit: str,
    reorder_level: int | str,
    preferred_supplier_id: Optional[int | str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Update an existing product's details."""
    target = get_product(product_id, conn=conn)
    if not target:
        raise ValidationError("Product not found.")

    (
        sku_c,
        name_c,
        desc_c,
        cat_c,
        unit_c,
        reorder_i,
        supplier_id_i,
    ) = _validate_product_payload(
        sku,
        name,
        description,
        category,
        unit,
        reorder_level,
        preferred_supplier_id,
        conn=conn,
    )

    duplicate = query_one(
        "SELECT id FROM products WHERE upper(sku) = ? AND id != ?",
        (sku_c, product_id),
        conn=conn,
    )
    if duplicate:
        raise ValidationError(f"Another product already uses SKU '{sku_c}'.")

    with transaction(conn) as tx_conn:
        tx_conn.execute(
            """
            UPDATE products
            SET sku = ?,
                name = ?,
                description = ?,
                category = ?,
                unit = ?,
                reorder_level = ?,
                preferred_supplier_id = ?
            WHERE id = ?
            """,
            (
                sku_c,
                name_c,
                desc_c,
                cat_c,
                unit_c,
                reorder_i,
                supplier_id_i,
                product_id,
            ),
        )


def delete_product(
    product_id: int, conn: Optional[sqlite3.Connection] = None
) -> None:
    """
    Delete a product ONLY when it has no dependent stock, batch, PO, transfer,
    issue, return, or transaction records.
    """
    target = get_product(product_id, conn=conn)
    if not target:
        raise ValidationError("Product not found.")

    dependency_checks = [
        ("batches", "SELECT COUNT(*) AS cnt FROM batches WHERE product_id = ?"),
        ("inventory", "SELECT COUNT(*) AS cnt FROM inventory WHERE product_id = ?"),
        (
            "purchase orders",
            "SELECT COUNT(*) AS cnt FROM purchase_order_items WHERE product_id = ?",
        ),
        (
            "transfers",
            "SELECT COUNT(*) AS cnt FROM transfer_items WHERE product_id = ?",
        ),
        (
            "stock issues",
            "SELECT COUNT(*) AS cnt FROM stock_issue_items WHERE product_id = ?",
        ),
        (
            "supplier returns",
            "SELECT COUNT(*) AS cnt FROM supplier_return_items WHERE product_id = ?",
        ),
        (
            "stock transactions",
            "SELECT COUNT(*) AS cnt FROM stock_transactions WHERE product_id = ?",
        ),
    ]

    blocking_sources = []
    for label, check_sql in dependency_checks:
        row = query_one(check_sql, (product_id,), conn=conn)
        if row and row["cnt"] > 0:
            blocking_sources.append(f"{row['cnt']} {label}")

    if blocking_sources:
        joined = ", ".join(blocking_sources)
        raise ValidationError(
            f"Cannot delete product '{target['sku']}' because it has dependent historical records ({joined})."
        )

    with transaction(conn) as tx_conn:
        tx_conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
