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


VALID_TRANSFER_STATUSES = (
    "Draft",
    "Dispatched",
    "Partially Received",
    "Received",
    "Cancelled",
)


def _next_transfer_number(tx_conn: sqlite3.Connection) -> str:
    """Generate a sequential transfer document number (e.g., TRF-2026-0001)."""
    row = query_one("SELECT COUNT(*) AS cnt FROM transfers", conn=tx_conn)
    seq = (int(row["cnt"]) if row else 0) + 1
    year_str = date.today().strftime("%Y")
    candidate = f"TRF-{year_str}-{seq:04d}"
    while query_one(
        "SELECT id FROM transfers WHERE transfer_number = ?",
        (candidate,),
        conn=tx_conn,
    ):
        seq += 1
        candidate = f"TRF-{year_str}-{seq:04d}"
    return candidate


def create_transfer(
    source_warehouse_id: int | str,
    dest_warehouse_id: int | str,
    batch_id: int | str,
    quantity: int | str,
    transfer_date: Optional[str] = None,
    notes: str = "",
    auto_dispatch: bool = True,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """
    Create an inter-warehouse stock transfer for a specific batch.
    Validates source != destination, active warehouses, non-expired batch,
    and sufficient available source stock. If auto_dispatch=True, immediately
    dispatches the transfer so source stock is reserved/deducted in transit.
    """
    try:
        src_wh_id = int(source_warehouse_id)
        dst_wh_id = int(dest_warehouse_id)
        b_id = int(batch_id)
        qty_int = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "Valid source warehouse, destination warehouse, batch, and integer quantity are required."
        ) from exc

    if src_wh_id == dst_wh_id:
        raise ValidationError(
            "Source warehouse and destination warehouse cannot be identical."
        )
    if qty_int <= 0:
        raise ValidationError("Transfer quantity must be greater than zero.")

    t_date = parse_iso_date(
        transfer_date or date.today().isoformat(), "Transfer date", required=True
    )

    src_wh = query_one("SELECT * FROM warehouses WHERE id = ?", (src_wh_id,), conn=conn)
    dst_wh = query_one("SELECT * FROM warehouses WHERE id = ?", (dst_wh_id,), conn=conn)
    if not src_wh or not dst_wh:
        raise ValidationError("Source or destination warehouse does not exist.")
    if src_wh["is_active"] == 0 or dst_wh["is_active"] == 0:
        raise ValidationError(
            "Both source and destination warehouses must be active for stock transfers."
        )

    holding = query_one(
        """
        SELECT i.quantity,
               b.id AS batch_id,
               b.batch_number,
               b.product_id,
               b.expiry_date,
               b.unit_cost
        FROM inventory i
        JOIN batches b ON b.id = i.batch_id
        WHERE i.warehouse_id = ? AND i.batch_id = ?
        """,
        (src_wh_id, b_id),
        conn=conn,
    )
    if not holding or int(holding["quantity"]) <= 0:
        raise ValidationError(
            "Selected batch has no available stock at the source warehouse."
        )

    if holding["expiry_date"] and holding["expiry_date"] < t_date:
        raise ValidationError(
            f"Batch '{holding['batch_number']}' expired on {holding['expiry_date']} "
            "and cannot be transferred for normal operations."
        )

    if qty_int > int(holding["quantity"]):
        raise ValidationError(
            f"Transfer quantity ({qty_int}) exceeds available stock ({holding['quantity']}) "
            f"for batch '{holding['batch_number']}' at {src_wh['warehouse_code']}."
        )

    with transaction(conn) as tx_conn:
        trf_number = _next_transfer_number(tx_conn)
        cursor = tx_conn.execute(
            """
            INSERT INTO transfers (
                transfer_number, source_warehouse_id, dest_warehouse_id,
                transfer_date, status, notes
            )
            VALUES (?, ?, ?, ?, 'Draft', ?)
            """,
            (trf_number, src_wh_id, dst_wh_id, t_date, (notes or "").strip()),
        )
        transfer_id = int(cursor.lastrowid)

        tx_conn.execute(
            """
            INSERT INTO transfer_items (
                transfer_id, product_id, batch_id, quantity, received_quantity
            )
            VALUES (?, ?, ?, ?, 0)
            """,
            (transfer_id, int(holding["product_id"]), b_id, qty_int),
        )

        final_status = "Draft"
        if auto_dispatch:
            dispatch_transfer(transfer_id, conn=tx_conn)
            final_status = "Dispatched"

        return {
            "transfer_id": transfer_id,
            "transfer_number": trf_number,
            "status": final_status,
        }


def dispatch_transfer(
    transfer_id: int | str, conn: Optional[sqlite3.Connection] = None
) -> dict[str, Any]:
    """
    Transition a transfer from 'Draft' to 'Dispatched'.
    Atomically deducts the dispatched quantity from the source warehouse so
    dispatched stock does not remain available at the source while in transit.
    """
    try:
        trf_id = int(transfer_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid transfer ID.") from exc

    with transaction(conn) as tx_conn:
        trf = query_one(
            "SELECT * FROM transfers WHERE id = ?", (trf_id,), conn=tx_conn
        )
        if not trf:
            raise ValidationError("Stock transfer not found.")
        if trf["status"] != "Draft":
            raise ValidationError(
                f"Only 'Draft' transfers can be dispatched (current status: '{trf['status']}')."
            )

        items = query_all(
            """
            SELECT ti.*, b.batch_number, b.unit_cost, b.expiry_date
            FROM transfer_items ti
            JOIN batches b ON b.id = ti.batch_id
            WHERE ti.transfer_id = ?
            """,
            (trf_id,),
            conn=tx_conn,
        )
        if not items:
            raise ValidationError("Transfer has no line items to dispatch.")

        for item in items:
            if item["expiry_date"] and item["expiry_date"] < date.today().isoformat():
                raise ValidationError(
                    f"Cannot dispatch expired batch '{item['batch_number']}'."
                )

            upsert_inventory_holding(
                tx_conn=tx_conn,
                warehouse_id=int(trf["source_warehouse_id"]),
                batch_id=int(item["batch_id"]),
                product_id=int(item["product_id"]),
                quantity_delta=-int(item["quantity"]),
            )

            record_stock_transaction(
                tx_conn=tx_conn,
                product_id=int(item["product_id"]),
                batch_id=int(item["batch_id"]),
                warehouse_id=int(trf["source_warehouse_id"]),
                transaction_type="TRANSFER_DISPATCH",
                quantity=-int(item["quantity"]),
                unit_cost=float(item["unit_cost"]),
                reference_type="TRANSFER",
                reference_id=trf["transfer_number"],
                notes=f"Dispatched in-transit to warehouse ID {trf['dest_warehouse_id']}",
            )

        tx_conn.execute(
            """
            UPDATE transfers
            SET status = 'Dispatched', dispatched_at = datetime('now')
            WHERE id = ?
            """,
            (trf_id,),
        )
        return {
            "transfer_id": trf_id,
            "transfer_number": trf["transfer_number"],
            "status": "Dispatched",
        }


def receive_transfer(
    transfer_id: int | str,
    receive_quantity: Optional[int | str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """
    Receive in-transit stock at the destination warehouse.
    Supports full or partial receipt while preserving the original batch_id,
    expiry_date, and unit_cost at the destination warehouse.
    """
    try:
        trf_id = int(transfer_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid transfer ID.") from exc

    with transaction(conn) as tx_conn:
        trf = query_one(
            "SELECT * FROM transfers WHERE id = ?", (trf_id,), conn=tx_conn
        )
        if not trf:
            raise ValidationError("Stock transfer not found.")
        if trf["status"] not in ("Dispatched", "Partially Received"):
            raise ValidationError(
                f"Cannot receive a transfer with status '{trf['status']}'. "
                "Transfer must be 'Dispatched' or 'Partially Received'."
            )

        items = query_all(
            """
            SELECT ti.*, b.batch_number, b.unit_cost
            FROM transfer_items ti
            JOIN batches b ON b.id = ti.batch_id
            WHERE ti.transfer_id = ?
            """,
            (trf_id,),
            conn=tx_conn,
        )
        if not items:
            raise ValidationError("Transfer has no line items.")

        for item in items:
            pending_qty = int(item["quantity"]) - int(item["received_quantity"])
            if pending_qty <= 0:
                continue

            if receive_quantity not in (None, ""):
                try:
                    qty_now = int(receive_quantity)
                except (TypeError, ValueError) as exc:
                    raise ValidationError("Receive quantity must be a valid integer.") from exc
            else:
                qty_now = pending_qty

            if qty_now <= 0:
                raise ValidationError("Received transfer quantity must be greater than zero.")
            if qty_now > pending_qty:
                raise ValidationError(
                    f"Cannot receive {qty_now} units; only {pending_qty} units are in transit."
                )

            upsert_inventory_holding(
                tx_conn=tx_conn,
                warehouse_id=int(trf["dest_warehouse_id"]),
                batch_id=int(item["batch_id"]),
                product_id=int(item["product_id"]),
                quantity_delta=qty_now,
            )

            tx_conn.execute(
                """
                UPDATE transfer_items
                SET received_quantity = received_quantity + ?
                WHERE id = ?
                """,
                (qty_now, item["id"]),
            )

            record_stock_transaction(
                tx_conn=tx_conn,
                product_id=int(item["product_id"]),
                batch_id=int(item["batch_id"]),
                warehouse_id=int(trf["dest_warehouse_id"]),
                transaction_type="TRANSFER_RECEIPT",
                quantity=qty_now,
                unit_cost=float(item["unit_cost"]),
                reference_type="TRANSFER",
                reference_id=trf["transfer_number"],
                notes=f"Received transfer from warehouse ID {trf['source_warehouse_id']}",
            )

        agg = query_one(
            """
            SELECT SUM(quantity) AS total_dispatched,
                   SUM(received_quantity) AS total_received
            FROM transfer_items
            WHERE transfer_id = ?
            """,
            (trf_id,),
            conn=tx_conn,
        )
        total_disp = int(agg["total_dispatched"] or 0)
        total_recv = int(agg["total_received"] or 0)
        new_status = "Received" if total_recv >= total_disp else "Partially Received"

        tx_conn.execute(
            """
            UPDATE transfers
            SET status = ?,
                received_at = CASE WHEN ? = 'Received' THEN datetime('now') ELSE received_at END
            WHERE id = ?
            """,
            (new_status, new_status, trf_id),
        )
        return {
            "transfer_id": trf_id,
            "transfer_number": trf["transfer_number"],
            "status": new_status,
        }


def cancel_transfer(
    transfer_id: int | str, conn: Optional[sqlite3.Connection] = None
) -> dict[str, Any]:
    """
    Cancel a 'Draft' or 'Dispatched' transfer (provided no units have been received yet).
    If the transfer was already 'Dispatched', restores the in-transit stock back to the
    source warehouse and records a TRANSFER_CANCEL transaction so stock is never lost.
    """
    try:
        trf_id = int(transfer_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid transfer ID.") from exc

    with transaction(conn) as tx_conn:
        trf = query_one(
            "SELECT * FROM transfers WHERE id = ?", (trf_id,), conn=tx_conn
        )
        if not trf:
            raise ValidationError("Stock transfer not found.")
        if trf["status"] not in ("Draft", "Dispatched"):
            raise ValidationError(
                f"Cannot cancel a transfer in '{trf['status']}' status."
            )

        items = query_all(
            """
            SELECT ti.*, b.unit_cost
            FROM transfer_items ti
            JOIN batches b ON b.id = ti.batch_id
            WHERE ti.transfer_id = ?
            """,
            (trf_id,),
            conn=tx_conn,
        )

        if trf["status"] == "Dispatched":
            for item in items:
                if int(item["received_quantity"]) > 0:
                    raise ValidationError(
                        "Cannot cancel a transfer that has already been partially received."
                    )
                upsert_inventory_holding(
                    tx_conn=tx_conn,
                    warehouse_id=int(trf["source_warehouse_id"]),
                    batch_id=int(item["batch_id"]),
                    product_id=int(item["product_id"]),
                    quantity_delta=int(item["quantity"]),
                )
                record_stock_transaction(
                    tx_conn=tx_conn,
                    product_id=int(item["product_id"]),
                    batch_id=int(item["batch_id"]),
                    warehouse_id=int(trf["source_warehouse_id"]),
                    transaction_type="TRANSFER_CANCEL",
                    quantity=int(item["quantity"]),
                    unit_cost=float(item["unit_cost"]),
                    reference_type="TRANSFER",
                    reference_id=trf["transfer_number"],
                    notes="Restored in-transit stock to source warehouse upon transfer cancellation",
                )

        tx_conn.execute(
            "UPDATE transfers SET status = 'Cancelled' WHERE id = ?",
            (trf_id,),
        )
        return {
            "transfer_id": trf_id,
            "transfer_number": trf["transfer_number"],
            "status": "Cancelled",
        }


def list_transfers(
    status_filter: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[sqlite3.Row]:
    """Return all inter-warehouse transfers with source, destination, product, and batch details."""
    where_sql = "WHERE t.status = ?" if status_filter else ""
    params = (status_filter,) if status_filter else ()
    sql = f"""
        SELECT t.id,
               t.transfer_number,
               t.source_warehouse_id,
               t.dest_warehouse_id,
               t.transfer_date,
               t.dispatched_at,
               t.received_at,
               t.status,
               t.notes,
               sw.warehouse_code AS source_code,
               sw.name AS source_name,
               dw.warehouse_code AS dest_code,
               dw.name AS dest_name,
               ti.product_id,
               ti.batch_id,
               ti.quantity,
               ti.received_quantity,
               (ti.quantity - ti.received_quantity) AS in_transit_quantity,
               p.sku,
               p.name AS product_name,
               p.unit,
               b.batch_number,
               b.expiry_date,
               b.unit_cost
        FROM transfers t
        JOIN warehouses sw ON sw.id = t.source_warehouse_id
        JOIN warehouses dw ON dw.id = t.dest_warehouse_id
        JOIN transfer_items ti ON ti.transfer_id = t.id
        JOIN products p ON p.id = ti.product_id
        JOIN batches b ON b.id = ti.batch_id
        {where_sql}
        ORDER BY t.id DESC
    """
    return query_all(sql, params, conn=conn)
