from datetime import date
from flask import Blueprint, flash, redirect, render_template, request, url_for
from services import ValidationError
from services.fifo_service import (
    get_fifo_valuation_overview,
    issue_stock_fifo,
    list_stock_issues,
)
from services.inventory_service import (
    VALID_TRANSACTION_TYPES,
    adjust_batch_stock,
    get_expiry_alerts,
    list_batch_inventory,
    list_product_stock_summary,
    list_stock_transactions,
    receive_batch_stock,
)
from services.product_service import list_products
from services.supplier_service import list_suppliers
from services.warehouse_service import list_warehouses

inventory_bp = Blueprint("inventory_bp", __name__)


@inventory_bp.route("/inventory", methods=["GET"])
def index():
    warehouse_id = request.args.get("warehouse_id", type=int)
    product_id = request.args.get("product_id", type=int)
    expiry_filter = request.args.get("expiry_filter", default="", type=str).strip()
    show_zero = request.args.get("show_zero") == "1"

    batch_rows = list_batch_inventory(
        warehouse_id=warehouse_id,
        product_id=product_id,
        expiry_filter=expiry_filter or None,
        include_zero=show_zero,
    )
    product_summary = list_product_stock_summary()
    expiry_alerts = get_expiry_alerts()
    products = list_products()
    warehouses = list_warehouses(active_only=False)
    suppliers = list_suppliers(active_only=True)

    return render_template(
        "inventory.html",
        batch_rows=batch_rows,
        product_summary=product_summary,
        expiry_alerts=expiry_alerts,
        products=products,
        warehouses=warehouses,
        suppliers=suppliers,
        filters={
            "warehouse_id": warehouse_id,
            "product_id": product_id,
            "expiry_filter": expiry_filter,
            "show_zero": show_zero,
        },
        today_iso=date.today().isoformat(),
        active_page="inventory",
    )


@inventory_bp.route("/inventory/receive-batch", methods=["POST"])
def receive_batch():
    try:
        result = receive_batch_stock(
            product_id=request.form.get("product_id", ""),
            warehouse_id=request.form.get("warehouse_id", ""),
            batch_number=request.form.get("batch_number", ""),
            quantity=request.form.get("quantity", ""),
            unit_cost=request.form.get("unit_cost", ""),
            receipt_date=request.form.get("receipt_date", ""),
            mfg_date=request.form.get("mfg_date", ""),
            expiry_date=request.form.get("expiry_date", ""),
            supplier_id=request.form.get("supplier_id", ""),
            reference_type="INITIAL_OR_DIRECT_BATCH",
            notes=request.form.get("notes", ""),
        )
        flash(
            f"Batch '{result['batch_number']}' recorded successfully "
            f"(Current warehouse batch qty: {result['warehouse_quantity']}).",
            "success",
        )
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("inventory_bp.index"))


@inventory_bp.route("/inventory/adjust", methods=["POST"])
def adjust():
    try:
        new_qty = adjust_batch_stock(
            warehouse_id=request.form.get("warehouse_id", ""),
            batch_id=request.form.get("batch_id", ""),
            quantity_delta=request.form.get("quantity_delta", ""),
            reason=request.form.get("reason", ""),
        )
        flash(
            f"Stock adjustment recorded. Updated batch quantity at warehouse: {new_qty}.",
            "success",
        )
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("inventory_bp.index"))


@inventory_bp.route("/valuation", methods=["GET"])
def valuation():
    warehouse_id = request.args.get("warehouse_id", type=int)
    overview = get_fifo_valuation_overview(warehouse_id=warehouse_id)
    issue_history = list_stock_issues()
    products = list_products()
    warehouses = list_warehouses(active_only=True)

    return render_template(
        "valuation.html",
        fifo_layers=overview["layers"],
        total_eligible_value=overview["total_eligible_value"],
        issue_history=issue_history,
        products=products,
        warehouses=warehouses,
        selected_warehouse_id=warehouse_id,
        today_iso=date.today().isoformat(),
        active_page="valuation",
    )


@inventory_bp.route("/valuation/issue", methods=["POST"])
def issue_fifo():
    try:
        res = issue_stock_fifo(
            warehouse_id=request.form.get("warehouse_id", ""),
            product_id=request.form.get("product_id", ""),
            issue_quantity=request.form.get("issue_quantity", ""),
            issue_date=request.form.get("issue_date", ""),
            recipient_reference=request.form.get("recipient_reference", ""),
            notes=request.form.get("notes", ""),
        )
        batch_summary = ", ".join(
            f"{b['quantity_consumed']} from {b['batch_number']} @ ₹{b['unit_cost']:.2f}"
            for b in res["breakdown"]
        )
        flash(
            f"FIFO Stock Issue '{res['issue_number']}' completed: {res['total_quantity']} units issued "
            f"for Total FIFO Value ₹{res['total_cost']:.2f} ({batch_summary}).",
            "success",
        )
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("inventory_bp.valuation"))


@inventory_bp.route("/transactions", methods=["GET"])
def transactions():
    product_id = request.args.get("product_id", type=int)
    warehouse_id = request.args.get("warehouse_id", type=int)
    transaction_type = request.args.get("transaction_type", default="", type=str).strip()

    tx_rows = list_stock_transactions(
        product_id=product_id,
        warehouse_id=warehouse_id,
        transaction_type=transaction_type or None,
    )
    products = list_products()
    warehouses = list_warehouses(active_only=False)

    return render_template(
        "transactions.html",
        transactions=tx_rows,
        products=products,
        warehouses=warehouses,
        transaction_types=VALID_TRANSACTION_TYPES,
        filters={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "transaction_type": transaction_type,
        },
        active_page="transactions",
    )
