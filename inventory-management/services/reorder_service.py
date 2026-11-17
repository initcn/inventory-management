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


VALID_PO_STATUSES = (
    "Draft",
    "Pending",
    "Partially Received",
    "Completed",
    "Cancelled",
)


def _next_document_number(
    tx_conn: sqlite3.Connection, table: str, column: str, prefix: str
) -> str:
    """Generate a sequential human-readable document number (e.g., PO-2026-0001)."""
    row = query_one(f"SELECT COUNT(*) AS cnt FROM {table}", conn=tx_conn)
    seq = (int(row["cnt"]) if row else 0) + 1
    year_str = date.today().strftime("%Y")
    candidate = f"{prefix}-{year_str}-{seq:04d}"
    while query_one(
        f"SELECT id FROM {table} WHERE {column} = ?", (candidate,), conn=tx_conn
    ):
        seq += 1
        candidate = f"{prefix}-{year_str}-{seq:04d}"
    return candidate


def check_reorder_levels(
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict[str, Any]]:
    """
    Evaluate all products against their reorder level.
    Only non-expired stock in active warehouses counts as available stock.
    Also checks whether an open PO ('Draft', 'Pending', 'Partially Received')
    already covers each product to prevent duplicate PO generation.
    """
    rows = query_all(
        """
        SELECT p.id AS product_id,
               p.sku,
               p.name AS product_name,
               p.category,
               p.unit,
               p.reorder_level,
               p.preferred_supplier_id,
               s.name AS supplier_name,
               s.supplier_code,
               s.is_active AS supplier_active,
               COALESCE(SUM(
                   CASE
                       WHEN w.is_active = 1
                        AND (b.expiry_date IS NULL OR date(b.expiry_date) >= date('now'))
                       THEN i.quantity
                       ELSE 0
                   END
               ), 0) AS available_stock,
               (
                   SELECT COALESCE(SUM(poi.ordered_quantity - poi.received_quantity), 0)
                   FROM purchase_order_items poi
                   JOIN purchase_orders po ON po.id = poi.po_id
                   WHERE poi.product_id = p.id
                     AND po.status IN ('Draft', 'Pending', 'Partially Received')
                     AND poi.received_quantity < poi.ordered_quantity
               ) AS open_po_pending_qty,
               (
                   SELECT po.po_number
                   FROM purchase_order_items poi
                   JOIN purchase_orders po ON po.id = poi.po_id
                   WHERE poi.product_id = p.id
                     AND po.status IN ('Draft', 'Pending', 'Partially Received')
                     AND poi.received_quantity < poi.ordered_quantity
                   ORDER BY po.id DESC
                   LIMIT 1
               ) AS active_po_number
        FROM products p
        LEFT JOIN suppliers s ON s.id = p.preferred_supplier_id
        LEFT JOIN inventory i ON i.product_id = p.id
        LEFT JOIN batches b ON b.id = i.batch_id
        LEFT JOIN warehouses w ON w.id = i.warehouse_id
        GROUP BY p.id
        HAVING available_stock <= p.reorder_level
        ORDER BY available_stock ASC, p.sku ASC
        """,
        conn=conn,
    )

    results: list[dict[str, Any]] = []
    for row in rows:
        avail = int(row["available_stock"])
        reorder = int(row["reorder_level"])
        open_po_qty = int(row["open_po_pending_qty"])
        recommended_qty = max((reorder * 2) - avail, reorder, 10)

        results.append(
            {
                "product_id": int(row["product_id"]),
                "sku": row["sku"],
                "product_name": row["product_name"],
                "category": row["category"],
                "unit": row["unit"],
                "reorder_level": reorder,
                "available_stock": avail,
                "preferred_supplier_id": row["preferred_supplier_id"],
                "supplier_name": row["supplier_name"],
                "supplier_code": row["supplier_code"],
                "supplier_active": row["supplier_active"],
                "open_po_pending_qty": open_po_qty,
                "active_po_number": row["active_po_number"],
                "recommended_order_qty": recommended_qty,
                "can_auto_generate": (
                    open_po_qty == 0
                    and row["preferred_supplier_id"] is not None
                    and row["supplier_active"] == 1
                ),
            }
        )
    return results


def generate_purchase_order(
    supplier_id: int | str,
    target_warehouse_id: int | str,
    items: list[dict[str, Any]],
    order_date: Optional[str] = None,
    status: str = "Draft",
    is_auto_generated: bool = False,
    notes: str = "",
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """
    Create a Purchase Order header and one or more line items.
    Includes duplicate-prevention check when is_auto_generated=True.
    """
    try:
        supp_id = int(supplier_id)
        wh_id = int(target_warehouse_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Valid supplier and target warehouse are required.") from exc

    if status not in ("Draft", "Pending"):
        raise ValidationError("New purchase orders must start in 'Draft' or 'Pending' status.")

    if not items:
        raise ValidationError("A purchase order must contain at least one product line item.")

    ord_date = parse_iso_date(
        order_date or date.today().isoformat(), "Order date", required=True
    )

    supplier = query_one("SELECT * FROM suppliers WHERE id = ?", (supp_id,), conn=conn)
    if not supplier:
        raise ValidationError("Selected supplier does not exist.")
    if supplier["is_active"] == 0:
        raise ValidationError(f"Supplier '{supplier['name']}' is inactive.")

    warehouse = query_one("SELECT * FROM warehouses WHERE id = ?", (wh_id,), conn=conn)
    if not warehouse:
        raise ValidationError("Selected target warehouse does not exist.")
    if warehouse["is_active"] == 0:
        raise ValidationError(f"Warehouse '{warehouse['name']}' is inactive.")

    validated_lines: list[tuple[int, int, float]] = []
    seen_products: set[int] = set()

    for line in items:
        try:
            prod_id = int(line["product_id"])
            ord_qty = int(line["ordered_quantity"])
            exp_cost = round(float(line.get("expected_unit_cost", 0.0) or 0.0), 2)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Each PO line item requires valid product, quantity, and unit cost.") from exc

        if ord_qty <= 0:
            raise ValidationError("Ordered quantity must be greater than zero.")
        if exp_cost < 0:
            raise ValidationError("Expected unit cost cannot be negative.")
        if prod_id in seen_products:
            raise ValidationError("Duplicate product lines are not allowed in the same purchase order.")

        prod_row = query_one("SELECT id, sku FROM products WHERE id = ?", (prod_id,), conn=conn)
        if not prod_row:
            raise ValidationError(f"Product ID {prod_id} does not exist.")

        seen_products.add(prod_id)
        validated_lines.append((prod_id, ord_qty, exp_cost))

    with transaction(conn) as tx_conn:
        if is_auto_generated:
            for prod_id, _, _ in validated_lines:
                open_po = query_one(
                    """
                    SELECT po.po_number
                    FROM purchase_order_items poi
                    JOIN purchase_orders po ON po.id = poi.po_id
                    WHERE poi.product_id = ?
                      AND po.status IN ('Draft', 'Pending', 'Partially Received')
                      AND poi.received_quantity < poi.ordered_quantity
                    LIMIT 1
                    """,
                    (prod_id,),
                    conn=tx_conn,
                )
                if open_po:
                    raise ValidationError(
                        f"Active purchase order '{open_po['po_number']}' already exists for product ID {prod_id}."
                    )

        po_number = _next_document_number(tx_conn, "purchase_orders", "po_number", "PO")
        cursor = tx_conn.execute(
            """
            INSERT INTO purchase_orders (
                po_number, supplier_id, target_warehouse_id,
                order_date, status, is_auto_generated, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                po_number,
                supp_id,
                wh_id,
                ord_date,
                status,
                1 if is_auto_generated else 0,
                (notes or "").strip(),
            ),
        )
        po_id = int(cursor.lastrowid)

        for prod_id, ord_qty, exp_cost in validated_lines:
            tx_conn.execute(
                """
                INSERT INTO purchase_order_items (
                    po_id, product_id, ordered_quantity, received_quantity, expected_unit_cost
                )
                VALUES (?, ?, ?, 0, ?)
                """,
                (po_id, prod_id, ord_qty, exp_cost),
            )

        return {"po_id": po_id, "po_number": po_number, "status": status}


def auto_generate_purchase_orders(
    target_warehouse_id: Optional[int | str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """
    Detect all products at or below reorder level and automatically generate
    Draft Purchase Orders grouped by preferred supplier.
    Skips products that already have an open PO or lack an active preferred supplier.
    """
    if target_warehouse_id not in (None, "", "0", 0):
        try:
            wh_id = int(target_warehouse_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Invalid target warehouse for reorder generation.") from exc
        wh_row = query_one(
            "SELECT * FROM warehouses WHERE id = ? AND is_active = 1",
            (wh_id,),
            conn=conn,
        )
        if not wh_row:
            raise ValidationError("Selected target warehouse does not exist or is inactive.")
    else:
        wh_row = query_one(
            "SELECT * FROM warehouses WHERE is_active = 1 ORDER BY id ASC LIMIT 1",
            conn=conn,
        )
        if not wh_row:
            raise ValidationError("No active warehouse is available to receive replenishment orders.")
        wh_id = int(wh_row["id"])

    candidates = check_reorder_levels(conn=conn)
    grouped_by_supplier: dict[int, list[dict[str, Any]]] = {}
    skipped_open_po: list[str] = []
    skipped_no_supplier: list[str] = []

    for item in candidates:
        if item["open_po_pending_qty"] > 0:
            skipped_open_po.append(f"{item['sku']} ({item['active_po_number']})")
            continue
        if not item["preferred_supplier_id"] or not item["supplier_active"]:
            skipped_no_supplier.append(item["sku"])
            continue

        supp_id = int(item["preferred_supplier_id"])
        last_cost_row = query_one(
            """
            SELECT unit_cost FROM batches
            WHERE product_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (item["product_id"],),
            conn=conn,
        )
        default_cost = float(last_cost_row["unit_cost"]) if last_cost_row else 100.0

        grouped_by_supplier.setdefault(supp_id, []).append(
            {
                "product_id": item["product_id"],
                "ordered_quantity": item["recommended_order_qty"],
                "expected_unit_cost": default_cost,
            }
        )

    created_pos: list[str] = []
    for supp_id, lines in grouped_by_supplier.items():
        po_res = generate_purchase_order(
            supplier_id=supp_id,
            target_warehouse_id=wh_id,
            items=lines,
            status="Draft",
            is_auto_generated=True,
            notes="Auto-generated by Reorder-Level Monitor",
            conn=conn,
        )
        created_pos.append(po_res["po_number"])

    return {
        "created_pos": created_pos,
        "skipped_open_po": skipped_open_po,
        "skipped_no_supplier": skipped_no_supplier,
    }


def update_purchase_order_status(
    po_id: int | str,
    new_status: str,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """
    Allow users to review and confirm Draft orders ('Draft' -> 'Pending')
    or cancel orders ('Draft'/'Pending' -> 'Cancelled') when no goods have been received.
    """
    try:
        po_id_int = int(po_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid purchase order ID.") from exc

    if new_status not in ("Pending", "Cancelled"):
        raise ValidationError("Manual status updates are restricted to 'Pending' or 'Cancelled'.")

    po = query_one("SELECT * FROM purchase_orders WHERE id = ?", (po_id_int,), conn=conn)
    if not po:
        raise ValidationError("Purchase order not found.")

    totals = query_one(
        """
        SELECT COALESCE(SUM(received_quantity), 0) AS total_received
        FROM purchase_order_items
        WHERE po_id = ?
        """,
        (po_id_int,),
        conn=conn,
    )
    total_received = int(totals["total_received"]) if totals else 0

    if new_status == "Pending":
        if po["status"] != "Draft":
            raise ValidationError(
                f"Only 'Draft' purchase orders can be confirmed to 'Pending' (current: '{po['status']}')."
            )
    elif new_status == "Cancelled":
        if total_received > 0 or po["status"] in ("Partially Received", "Completed", "Cancelled"):
            raise ValidationError(
                "Cannot cancel a purchase order that is already partially/fully received or cancelled."
            )

    with transaction(conn) as tx_conn:
        tx_conn.execute(
            "UPDATE purchase_orders SET status = ? WHERE id = ?",
            (new_status, po_id_int),
        )


def receive_goods(
    po_id: int | str,
    receipt_items: list[dict[str, Any]],
    warehouse_id: Optional[int | str] = None,
    receipt_date: Optional[str] = None,
    notes: str = "",
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """
    Record a full or partial Goods Receipt (GRN) against an active Purchase Order.
    Supports multiple receipts against the same PO, creates/updates batch records,
    increments warehouse inventory, updates PO line received quantities, and transitions
    PO status to 'Partially Received' or 'Completed'.
    """
    try:
        po_id_int = int(po_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Valid purchase order ID is required.") from exc

    if not receipt_items:
        raise ValidationError("At least one receipt line item is required.")

    rec_date = parse_iso_date(
        receipt_date or date.today().isoformat(), "Receipt date", required=True
    )

    with transaction(conn) as tx_conn:
        po = query_one(
            "SELECT * FROM purchase_orders WHERE id = ?", (po_id_int,), conn=tx_conn
        )
        if not po:
            raise ValidationError("Purchase order does not exist.")
        if po["status"] in ("Cancelled", "Completed"):
            raise ValidationError(
                f"Cannot receive goods against a '{po['status']}' purchase order."
            )

        target_wh_id = (
            int(warehouse_id)
            if warehouse_id not in (None, "", "0", 0)
            else int(po["target_warehouse_id"])
        )
        warehouse = query_one(
            "SELECT * FROM warehouses WHERE id = ?", (target_wh_id,), conn=tx_conn
        )
        if not warehouse or warehouse["is_active"] == 0:
            raise ValidationError("Receiving warehouse does not exist or is inactive.")

        grn_number = _next_document_number(
            tx_conn, "goods_receipts", "grn_number", "GRN"
        )
        grn_cursor = tx_conn.execute(
            """
            INSERT INTO goods_receipts (grn_number, po_id, warehouse_id, receipt_date, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (grn_number, po_id_int, target_wh_id, rec_date, (notes or "").strip()),
        )
        receipt_id = int(grn_cursor.lastrowid)

        processed_lines = 0
        for line in receipt_items:
            try:
                po_item_id = int(line["po_item_id"])
                recv_qty = int(line["received_quantity"])
                unit_cost = round(float(line["unit_cost"]), 2)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValidationError(
                    "Each goods receipt line requires a valid PO item, integer quantity, and unit cost."
                ) from exc

            if recv_qty <= 0:
                raise ValidationError("Received quantity must be greater than zero.")
            if unit_cost < 0:
                raise ValidationError("Unit cost cannot be negative.")

            batch_number = (line.get("batch_number") or "").strip().upper()
            if not batch_number:
                raise ValidationError("Batch number is required for every received item.")

            mfg_iso = parse_iso_date(line.get("mfg_date"), "Manufacturing date", required=False)
            exp_iso = parse_iso_date(line.get("expiry_date"), "Expiry date", required=False)
            if mfg_iso and exp_iso and exp_iso < mfg_iso:
                raise ValidationError("Expiry date cannot be earlier than manufacturing date.")

            po_item = query_one(
                """
                SELECT * FROM purchase_order_items
                WHERE id = ? AND po_id = ?
                """,
                (po_item_id, po_id_int),
                conn=tx_conn,
            )
            if not po_item:
                raise ValidationError(
                    f"PO item #{po_item_id} does not belong to purchase order {po['po_number']}."
                )

            pending_qty = int(po_item["ordered_quantity"]) - int(po_item["received_quantity"])
            if recv_qty > pending_qty:
                raise ValidationError(
                    f"Cannot receive {recv_qty} units for PO item #{po_item_id}; "
                    f"only {pending_qty} units remain pending."
                )

            prod_id = int(po_item["product_id"])
            existing_batch = query_one(
                """
                SELECT * FROM batches
                WHERE product_id = ? AND upper(batch_number) = ?
                """,
                (prod_id, batch_number),
                conn=tx_conn,
            )

            if existing_batch:
                if abs(float(existing_batch["unit_cost"]) - unit_cost) > 0.009:
                    raise ValidationError(
                        f"Batch '{batch_number}' already exists with unit cost "
                        f"₹{existing_batch['unit_cost']:.2f}. Use a distinct batch number."
                    )
                if (existing_batch["expiry_date"] or None) != (exp_iso or None):
                    raise ValidationError(
                        f"Batch '{batch_number}' already exists with a different expiry date."
                    )
                batch_id = int(existing_batch["id"])
                tx_conn.execute(
                    """
                    UPDATE batches
                    SET initial_quantity = initial_quantity + ?
                    WHERE id = ?
                    """,
                    (recv_qty, batch_id),
                )
            else:
                b_cursor = tx_conn.execute(
                    """
                    INSERT INTO batches (
                        batch_number, product_id, supplier_id,
                        mfg_date, expiry_date, unit_cost, receipt_date, initial_quantity
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_number,
                        prod_id,
                        int(po["supplier_id"]),
                        mfg_iso,
                        exp_iso,
                        unit_cost,
                        rec_date,
                        recv_qty,
                    ),
                )
                batch_id = int(b_cursor.lastrowid)

            upsert_inventory_holding(
                tx_conn=tx_conn,
                warehouse_id=target_wh_id,
                batch_id=batch_id,
                product_id=prod_id,
                quantity_delta=recv_qty,
            )

            tx_conn.execute(
                """
                UPDATE purchase_order_items
                SET received_quantity = received_quantity + ?
                WHERE id = ?
                """,
                (recv_qty, po_item_id),
            )

            tx_conn.execute(
                """
                INSERT INTO goods_receipt_items (
                    receipt_id, po_item_id, product_id, batch_id, received_quantity, unit_cost
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (receipt_id, po_item_id, prod_id, batch_id, recv_qty, unit_cost),
            )

            record_stock_transaction(
                tx_conn=tx_conn,
                product_id=prod_id,
                batch_id=batch_id,
                warehouse_id=target_wh_id,
                transaction_type="GOODS_RECEIPT",
                quantity=recv_qty,
                unit_cost=unit_cost,
                reference_type="PO_GRN",
                reference_id=f"{po['po_number']}/{grn_number}",
                notes=notes or f"Goods receipt against {po['po_number']}",
            )
            processed_lines += 1

        agg = query_one(
            """
            SELECT SUM(ordered_quantity) AS total_ordered,
                   SUM(received_quantity) AS total_received
            FROM purchase_order_items
            WHERE po_id = ?
            """,
            (po_id_int,),
            conn=tx_conn,
        )
        total_ordered = int(agg["total_ordered"] or 0)
        total_received = int(agg["total_received"] or 0)

        if total_received >= total_ordered and total_ordered > 0:
            updated_po_status = "Completed"
        elif total_received > 0:
            updated_po_status = "Partially Received"
        else:
            updated_po_status = po["status"]

        tx_conn.execute(
            "UPDATE purchase_orders SET status = ? WHERE id = ?",
            (updated_po_status, po_id_int),
        )

        return {
            "receipt_id": receipt_id,
            "grn_number": grn_number,
            "po_id": po_id_int,
            "po_number": po["po_number"],
            "po_status": updated_po_status,
            "processed_lines": processed_lines,
        }


def list_purchase_orders(
    status_filter: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[sqlite3.Row]:
    """Return all purchase orders with ordered, received, and pending quantity totals."""
    where_sql = "WHERE po.status = ?" if status_filter else ""
    params = (status_filter,) if status_filter else ()
    sql = f"""
        SELECT po.*,
               s.name AS supplier_name,
               s.supplier_code,
               w.name AS warehouse_name,
               w.warehouse_code,
               COALESCE(SUM(poi.ordered_quantity), 0) AS total_ordered,
               COALESCE(SUM(poi.received_quantity), 0) AS total_received,
               COALESCE(SUM(poi.ordered_quantity - poi.received_quantity), 0) AS total_pending,
               COALESCE(SUM(poi.ordered_quantity * poi.expected_unit_cost), 0.0) AS estimated_total
        FROM purchase_orders po
        JOIN suppliers s ON s.id = po.supplier_id
        JOIN warehouses w ON w.id = po.target_warehouse_id
        LEFT JOIN purchase_order_items poi ON poi.po_id = po.id
        {where_sql}
        GROUP BY po.id
        ORDER BY po.id DESC
    """
    return query_all(sql, params, conn=conn)


def get_purchase_order_details(
    po_id: int, conn: Optional[sqlite3.Connection] = None
) -> Optional[dict[str, Any]]:
    """Fetch a single purchase order header, its line items, and its goods receipt history."""
    po = query_one(
        """
        SELECT po.*,
               s.name AS supplier_name,
               s.supplier_code,
               w.name AS warehouse_name,
               w.warehouse_code
        FROM purchase_orders po
        JOIN suppliers s ON s.id = po.supplier_id
        JOIN warehouses w ON w.id = po.target_warehouse_id
        WHERE po.id = ?
        """,
        (po_id,),
        conn=conn,
    )
    if not po:
        return None

    items = query_all(
        """
        SELECT poi.*,
               p.sku,
               p.name AS product_name,
               p.unit,
               (poi.ordered_quantity - poi.received_quantity) AS pending_quantity
        FROM purchase_order_items poi
        JOIN products p ON p.id = poi.product_id
        WHERE poi.po_id = ?
        ORDER BY poi.id ASC
        """,
        (po_id,),
        conn=conn,
    )

    receipts = query_all(
        """
        SELECT gr.id, gr.grn_number, gr.receipt_date, gr.notes,
               w.warehouse_code, w.name AS warehouse_name,
               gri.received_quantity, gri.unit_cost,
               p.sku, p.name AS product_name,
               b.batch_number, b.expiry_date
        FROM goods_receipts gr
        JOIN warehouses w ON w.id = gr.warehouse_id
        JOIN goods_receipt_items gri ON gri.receipt_id = gr.id
        JOIN products p ON p.id = gri.product_id
        JOIN batches b ON b.id = gri.batch_id
        WHERE gr.po_id = ?
        ORDER BY gr.id DESC, gri.id ASC
        """,
        (po_id,),
        conn=conn,
    )

    return {"header": po, "items": items, "receipts": receipts}


def list_goods_receipts(
    conn: Optional[sqlite3.Connection] = None,
) -> list[sqlite3.Row]:
    """Return all Goods Receipts (GRNs) with PO, supplier, warehouse, and batch details."""
    sql = """
        SELECT gr.id AS receipt_id,
               gr.grn_number,
               gr.receipt_date,
               gr.notes,
               po.id AS po_id,
               po.po_number,
               po.status AS po_status,
               s.name AS supplier_name,
               w.warehouse_code,
               w.name AS warehouse_name,
               p.sku,
               p.name AS product_name,
               p.unit,
               b.batch_number,
               b.mfg_date,
               b.expiry_date,
               gri.received_quantity,
               gri.unit_cost,
               (gri.received_quantity * gri.unit_cost) AS line_total
        FROM goods_receipt_items gri
        JOIN goods_receipts gr ON gr.id = gri.receipt_id
        JOIN purchase_orders po ON po.id = gr.po_id
        JOIN suppliers s ON s.id = po.supplier_id
        JOIN warehouses w ON w.id = gr.warehouse_id
        JOIN products p ON p.id = gri.product_id
        JOIN batches b ON b.id = gri.batch_id
        ORDER BY gr.id DESC, gri.id ASC
    """
    return query_all(sql, conn=conn)
