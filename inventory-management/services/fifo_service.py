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


def _next_issue_number(tx_conn: sqlite3.Connection) -> str:
    """Generate a sequential FIFO stock issue number (e.g., ISS-2026-0001)."""
    row = query_one("SELECT COUNT(*) AS cnt FROM stock_issues", conn=tx_conn)
    seq = (int(row["cnt"]) if row else 0) + 1
    year_str = date.today().strftime("%Y")
    candidate = f"ISS-{year_str}-{seq:04d}"
    while query_one(
        "SELECT id FROM stock_issues WHERE issue_number = ?",
        (candidate,),
        conn=tx_conn,
    ):
        seq += 1
        candidate = f"ISS-{year_str}-{seq:04d}"
    return candidate


def get_fifo_eligible_batches(
    warehouse_id: int,
    product_id: int,
    as_of_date: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[sqlite3.Row]:
    """
    Return all non-expired batch holdings with quantity > 0 for a product at a warehouse,
    strictly ordered by FIFO (batch receipt_date ASC, batch id ASC).
    """
    ref_date = as_of_date or date.today().isoformat()
    sql = """
        SELECT i.id AS inventory_id,
               i.warehouse_id,
               i.batch_id,
               i.product_id,
               i.quantity AS available_quantity,
               b.batch_number,
               b.receipt_date,
               b.mfg_date,
               b.expiry_date,
               b.unit_cost,
               p.sku,
               p.name AS product_name,
               p.unit,
               w.warehouse_code,
               w.name AS warehouse_name
        FROM inventory i
        JOIN batches b ON b.id = i.batch_id
        JOIN products p ON p.id = i.product_id
        JOIN warehouses w ON w.id = i.warehouse_id
        WHERE i.warehouse_id = ?
          AND i.product_id = ?
          AND i.quantity > 0
          AND (b.expiry_date IS NULL OR date(b.expiry_date) >= date(?))
        ORDER BY date(b.receipt_date) ASC, b.id ASC
    """
    return query_all(sql, (warehouse_id, product_id, ref_date), conn=conn)


def issue_stock_fifo(
    warehouse_id: int | str,
    product_id: int | str,
    issue_quantity: int | str,
    issue_date: Optional[str] = None,
    recipient_reference: str = "",
    notes: str = "",
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """
    Issue product stock from a warehouse using strict First-In, First-Out (FIFO)
    valuation based on batch receipt_date (and batch ID tie-breaker).
    Excludes expired batches, consumes across multiple batches when required,
    calculates total FIFO cost, updates inventory, and logs STOCK_ISSUE transactions.
    """
    try:
        wh_id = int(warehouse_id)
        prod_id = int(product_id)
        requested_qty = int(issue_quantity)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "Valid warehouse, product, and integer issue quantity are required."
        ) from exc

    if requested_qty <= 0:
        raise ValidationError("Issue quantity must be greater than zero.")

    iss_date = parse_iso_date(
        issue_date or date.today().isoformat(), "Issue date", required=True
    )

    warehouse = query_one("SELECT * FROM warehouses WHERE id = ?", (wh_id,), conn=conn)
    if not warehouse or warehouse["is_active"] == 0:
        raise ValidationError("Selected warehouse does not exist or is inactive.")

    product = query_one("SELECT * FROM products WHERE id = ?", (prod_id,), conn=conn)
    if not product:
        raise ValidationError("Selected product does not exist.")

    with transaction(conn) as tx_conn:
        eligible_batches = get_fifo_eligible_batches(
            warehouse_id=wh_id,
            product_id=prod_id,
            as_of_date=iss_date,
            conn=tx_conn,
        )
        total_eligible = sum(int(b["available_quantity"]) for b in eligible_batches)

        if total_eligible < requested_qty:
            expired_row = query_one(
                """
                SELECT COALESCE(SUM(i.quantity), 0) AS expired_qty
                FROM inventory i
                JOIN batches b ON b.id = i.batch_id
                WHERE i.warehouse_id = ?
                  AND i.product_id = ?
                  AND i.quantity > 0
                  AND b.expiry_date IS NOT NULL
                  AND date(b.expiry_date) < date(?)
                """,
                (wh_id, prod_id, iss_date),
                conn=tx_conn,
            )
            expired_qty = int(expired_row["expired_qty"] or 0) if expired_row else 0
            expiry_note = (
                f" ({expired_qty} additional units are expired and excluded from normal issue.)"
                if expired_qty > 0
                else ""
            )
            raise ValidationError(
                f"Insufficient eligible stock for '{product['sku']}' at {warehouse['warehouse_code']}: "
                f"requested {requested_qty}, but only {total_eligible} non-expired units are available.{expiry_note}"
            )

        remaining_to_consume = requested_qty
        consumed_breakdown: list[dict[str, Any]] = []
        total_issue_cost = 0.0

        for batch in eligible_batches:
            if remaining_to_consume <= 0:
                break

            batch_avail = int(batch["available_quantity"])
            take_qty = min(batch_avail, remaining_to_consume)
            unit_cost = float(batch["unit_cost"])
            line_cost = round(take_qty * unit_cost, 2)

            new_remaining = upsert_inventory_holding(
                tx_conn=tx_conn,
                warehouse_id=wh_id,
                batch_id=int(batch["batch_id"]),
                product_id=prod_id,
                quantity_delta=-take_qty,
            )

            consumed_breakdown.append(
                {
                    "batch_id": int(batch["batch_id"]),
                    "batch_number": batch["batch_number"],
                    "receipt_date": batch["receipt_date"],
                    "expiry_date": batch["expiry_date"],
                    "quantity_consumed": take_qty,
                    "unit_cost": unit_cost,
                    "line_cost": line_cost,
                    "remaining_in_batch": new_remaining,
                }
            )
            total_issue_cost = round(total_issue_cost + line_cost, 2)
            remaining_to_consume -= take_qty

        issue_number = _next_issue_number(tx_conn)
        issue_cursor = tx_conn.execute(
            """
            INSERT INTO stock_issues (
                issue_number, warehouse_id, issue_date,
                recipient_reference, total_quantity, total_cost, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                issue_number,
                wh_id,
                iss_date,
                (recipient_reference or "").strip(),
                requested_qty,
                total_issue_cost,
                (notes or "").strip(),
            ),
        )
        issue_id = int(issue_cursor.lastrowid)

        for item in consumed_breakdown:
            tx_conn.execute(
                """
                INSERT INTO stock_issue_items (
                    issue_id, product_id, batch_id, quantity, unit_cost, line_cost
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    issue_id,
                    prod_id,
                    item["batch_id"],
                    item["quantity_consumed"],
                    item["unit_cost"],
                    item["line_cost"],
                ),
            )

            record_stock_transaction(
                tx_conn=tx_conn,
                product_id=prod_id,
                batch_id=item["batch_id"],
                warehouse_id=wh_id,
                transaction_type="STOCK_ISSUE",
                quantity=-item["quantity_consumed"],
                unit_cost=item["unit_cost"],
                reference_type="FIFO_ISSUE",
                reference_id=issue_number,
                notes=notes or f"FIFO issue ({recipient_reference or 'Standard Dispatch'})",
            )

        return {
            "issue_id": issue_id,
            "issue_number": issue_number,
            "warehouse_id": wh_id,
            "product_id": prod_id,
            "total_quantity": requested_qty,
            "total_cost": total_issue_cost,
            "breakdown": consumed_breakdown,
        }


def get_fifo_valuation_overview(
    warehouse_id: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """
    Return the current FIFO queue of eligible batches and total inventory valuation.
    """
    where_clauses = [
        "i.quantity > 0",
        "(b.expiry_date IS NULL OR date(b.expiry_date) >= date('now'))",
    ]
    params: list[Any] = []
    if warehouse_id:
        where_clauses.append("i.warehouse_id = ?")
        params.append(warehouse_id)

    where_sql = " AND ".join(where_clauses)
    layers = query_all(
        f"""
        SELECT i.warehouse_id,
               w.warehouse_code,
               w.name AS warehouse_name,
               p.id AS product_id,
               p.sku,
               p.name AS product_name,
               p.unit,
               b.id AS batch_id,
               b.batch_number,
               b.receipt_date,
               b.expiry_date,
               i.quantity AS remaining_quantity,
               b.unit_cost,
               (i.quantity * b.unit_cost) AS layer_value,
               ROW_NUMBER() OVER (
                   PARTITION BY i.warehouse_id, i.product_id
                   ORDER BY date(b.receipt_date) ASC, b.id ASC
               ) AS fifo_rank
        FROM inventory i
        JOIN warehouses w ON w.id = i.warehouse_id
        JOIN products p ON p.id = i.product_id
        JOIN batches b ON b.id = i.batch_id
        WHERE {where_sql}
        ORDER BY w.warehouse_code ASC, p.sku ASC, date(b.receipt_date) ASC, b.id ASC
        """,
        params,
        conn=conn,
    )

    total_eligible_value = round(
        sum(float(row["layer_value"]) for row in layers), 2
    )
    return {"layers": layers, "total_eligible_value": total_eligible_value}


def list_stock_issues(
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict[str, Any]]:
    """Return all recorded FIFO stock issues with their per-batch consumption breakdown."""
    headers = query_all(
        """
        SELECT si.*,
               w.warehouse_code,
               w.name AS warehouse_name
        FROM stock_issues si
        JOIN warehouses w ON w.id = si.warehouse_id
        ORDER BY si.id DESC
        """,
        conn=conn,
    )

    results: list[dict[str, Any]] = []
    for h in headers:
        lines = query_all(
            """
            SELECT sii.*,
                   p.sku,
                   p.name AS product_name,
                   p.unit,
                   b.batch_number,
                   b.receipt_date,
                   b.expiry_date
            FROM stock_issue_items sii
            JOIN products p ON p.id = sii.product_id
            JOIN batches b ON b.id = sii.batch_id
            WHERE sii.issue_id = ?
            ORDER BY sii.id ASC
            """,
            (h["id"],),
            conn=conn,
        )
        results.append({"header": h, "lines": lines})
    return results
