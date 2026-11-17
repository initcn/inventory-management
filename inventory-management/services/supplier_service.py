import sqlite3
from typing import Any, Optional
from database import query_all, query_one, transaction
from integrations.supplier_adapter import (
    SupplierIntegrationAdapter,
    SupplierIntegrationError,
)
from services import ValidationError


def _validate_supplier_payload(
    supplier_code: str,
    name: str,
    contact_person: str,
    email: str,
    phone: str,
    address: str,
) -> tuple[str, str, str, str, str, str]:
    """Validate and normalize supplier fields."""
    code_clean = (supplier_code or "").strip().upper()
    name_clean = (name or "").strip()
    contact_clean = (contact_person or "").strip()
    email_clean = (email or "").strip()
    phone_clean = (phone or "").strip()
    address_clean = (address or "").strip()

    if not code_clean:
        raise ValidationError("Supplier code cannot be empty.")
    if not name_clean:
        raise ValidationError("Supplier name cannot be empty.")
    if not contact_clean:
        raise ValidationError("Contact person cannot be empty.")
    if not email_clean or "@" not in email_clean:
        raise ValidationError("A valid email address is required.")
    if not phone_clean:
        raise ValidationError("Phone number cannot be empty.")
    if not address_clean:
        raise ValidationError("Supplier address cannot be empty.")

    return code_clean, name_clean, contact_clean, email_clean, phone_clean, address_clean


def list_suppliers(
    active_only: bool = False, conn: Optional[sqlite3.Connection] = None
) -> list[sqlite3.Row]:
    """Return all suppliers with counts of linked products and purchase orders."""
    where_clause = "WHERE s.is_active = 1" if active_only else ""
    sql = f"""
        SELECT s.*,
               COUNT(DISTINCT p.id) AS product_count,
               COUNT(DISTINCT po.id) AS po_count
        FROM suppliers s
        LEFT JOIN products p ON p.preferred_supplier_id = s.id
        LEFT JOIN purchase_orders po ON po.supplier_id = s.id
        {where_clause}
        GROUP BY s.id
        ORDER BY s.name ASC
    """
    return query_all(sql, conn=conn)


def get_supplier(
    supplier_id: int, conn: Optional[sqlite3.Connection] = None
) -> Optional[sqlite3.Row]:
    """Fetch a single supplier by primary key."""
    return query_one(
        "SELECT * FROM suppliers WHERE id = ?", (supplier_id,), conn=conn
    )


def create_supplier(
    supplier_code: str,
    name: str,
    contact_person: str,
    email: str,
    phone: str,
    address: str,
    is_active: bool = True,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Create a new supplier record after validating uniqueness and required fields."""
    code_c, name_c, contact_c, email_c, phone_c, addr_c = _validate_supplier_payload(
        supplier_code, name, contact_person, email, phone, address
    )
    active_flag = 1 if is_active else 0

    existing = query_one(
        "SELECT id FROM suppliers WHERE upper(supplier_code) = ?",
        (code_c,),
        conn=conn,
    )
    if existing:
        raise ValidationError(f"Supplier code '{code_c}' already exists.")

    with transaction(conn) as tx_conn:
        cursor = tx_conn.execute(
            """
            INSERT INTO suppliers (
                supplier_code, name, contact_person, email, phone, address, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (code_c, name_c, contact_c, email_c, phone_c, addr_c, active_flag),
        )
        return int(cursor.lastrowid)


def update_supplier(
    supplier_id: int,
    supplier_code: str,
    name: str,
    contact_person: str,
    email: str,
    phone: str,
    address: str,
    is_active: bool = True,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Update an existing supplier's details."""
    target = get_supplier(supplier_id, conn=conn)
    if not target:
        raise ValidationError("Supplier not found.")

    code_c, name_c, contact_c, email_c, phone_c, addr_c = _validate_supplier_payload(
        supplier_code, name, contact_person, email, phone, address
    )
    active_flag = 1 if is_active else 0

    duplicate = query_one(
        "SELECT id FROM suppliers WHERE upper(supplier_code) = ? AND id != ?",
        (code_c, supplier_id),
        conn=conn,
    )
    if duplicate:
        raise ValidationError(f"Another supplier already uses code '{code_c}'.")

    with transaction(conn) as tx_conn:
        tx_conn.execute(
            """
            UPDATE suppliers
            SET supplier_code = ?,
                name = ?,
                contact_person = ?,
                email = ?,
                phone = ?,
                address = ?,
                is_active = ?
            WHERE id = ?
            """,
            (
                code_c,
                name_c,
                contact_c,
                email_c,
                phone_c,
                addr_c,
                active_flag,
                supplier_id,
            ),
        )


def get_supplier_associations(
    supplier_id: int, conn: Optional[sqlite3.Connection] = None
) -> dict[str, Any]:
    """Return products and recent purchase orders associated with a supplier."""
    products = query_all(
        """
        SELECT id, sku, name, category, unit, reorder_level
        FROM products
        WHERE preferred_supplier_id = ?
        ORDER BY name ASC
        """,
        (supplier_id,),
        conn=conn,
    )
    purchase_orders = query_all(
        """
        SELECT po.id, po.po_number, po.order_date, po.status,
               w.name AS warehouse_name,
               COALESCE(SUM(poi.ordered_quantity), 0) AS total_ordered,
               COALESCE(SUM(poi.received_quantity), 0) AS total_received
        FROM purchase_orders po
        JOIN warehouses w ON w.id = po.target_warehouse_id
        LEFT JOIN purchase_order_items poi ON poi.po_id = po.id
        WHERE po.supplier_id = ?
        GROUP BY po.id
        ORDER BY po.id DESC
        """,
        (supplier_id,),
        conn=conn,
    )
    return {"products": products, "purchase_orders": purchase_orders}


def check_external_supplier_catalog(
    supplier_id: int | str,
    product_id: int | str,
    requested_quantity: int | str = 25,
    simulation_mode: str = "SUCCESS",
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """
    Invoke the isolated SupplierIntegrationAdapter to validate supplier catalog
    pricing, MOQ, and lead time, handling simulated timeout or service-unavailable
    exceptions gracefully.
    """
    try:
        supp_id = int(supplier_id)
        prod_id = int(product_id)
        req_qty = int(requested_quantity)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "Valid supplier, product, and integer quantity are required for catalog verification."
        ) from exc

    if req_qty <= 0:
        raise ValidationError("Requested quantity must be greater than zero.")

    supplier = get_supplier(supp_id, conn=conn)
    if not supplier:
        raise ValidationError("Selected supplier does not exist.")

    product = query_one(
        "SELECT id, sku, name FROM products WHERE id = ?", (prod_id,), conn=conn
    )
    if not product:
        raise ValidationError("Selected product does not exist.")

    adapter = SupplierIntegrationAdapter()
    try:
        return adapter.verify_supplier_product(
            supplier_code=supplier["supplier_code"],
            product_sku=product["sku"],
            requested_quantity=req_qty,
            simulation_mode=simulation_mode,
        )
    except SupplierIntegrationError as exc:
        return {
            "ok": False,
            "simulated": True,
            "status": exc.error_code,
            "supplier_code": supplier["supplier_code"],
            "product_sku": product["sku"],
            "requested_quantity": req_qty,
            "message": str(exc),
        }
