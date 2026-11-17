from datetime import date
from flask import Blueprint, flash, redirect, render_template, request, url_for
from services import ValidationError
from services.product_service import list_products
from services.reorder_service import (
    VALID_PO_STATUSES,
    auto_generate_purchase_orders,
    check_reorder_levels,
    generate_purchase_order,
    get_purchase_order_details,
    list_goods_receipts,
    list_purchase_orders,
    receive_goods,
    update_purchase_order_status,
)
from services.supplier_service import list_suppliers
from services.warehouse_service import list_warehouses

purchases_bp = Blueprint("purchases_bp", __name__)


@purchases_bp.route("/purchases", methods=["GET"])
def index():
    status_filter = request.args.get("status", default="", type=str).strip()
    inspect_id = request.args.get("inspect_id", type=int)

    reorder_alerts = check_reorder_levels()
    purchase_orders = list_purchase_orders(status_filter=status_filter or None)
    po_details = get_purchase_order_details(inspect_id) if inspect_id else None
    products = list_products()
    suppliers = list_suppliers(active_only=True)
    warehouses = list_warehouses(active_only=True)

    return render_template(
        "purchases.html",
        reorder_alerts=reorder_alerts,
        purchase_orders=purchase_orders,
        po_details=po_details,
        products=products,
        suppliers=suppliers,
        warehouses=warehouses,
        statuses=VALID_PO_STATUSES,
        status_filter=status_filter,
        today_iso=date.today().isoformat(),
        active_page="purchases",
    )


@purchases_bp.route("/purchases/auto-generate", methods=["POST"])
def auto_generate():
    try:
        res = auto_generate_purchase_orders(
            target_warehouse_id=request.form.get("target_warehouse_id")
        )
        messages = []
        if res["created_pos"]:
            messages.append(
                f"Generated {len(res['created_pos'])} draft PO(s): {', '.join(res['created_pos'])}."
            )
        if res["skipped_open_po"]:
            messages.append(
                f"Skipped duplicate generation for products with open POs: {', '.join(res['skipped_open_po'])}."
            )
        if res["skipped_no_supplier"]:
            messages.append(
                f"Skipped products without an active preferred supplier: {', '.join(res['skipped_no_supplier'])}."
            )
        if not messages:
            messages.append("All products are above reorder levels. No purchase orders needed.")
        flash(" ".join(messages), "success" if res["created_pos"] else "info")
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("purchases_bp.index"))


@purchases_bp.route("/purchases/create", methods=["POST"])
def create():
    try:
        item_payload = [
            {
                "product_id": request.form.get("product_id", ""),
                "ordered_quantity": request.form.get("ordered_quantity", ""),
                "expected_unit_cost": request.form.get("expected_unit_cost", "0"),
            }
        ]
        res = generate_purchase_order(
            supplier_id=request.form.get("supplier_id", ""),
            target_warehouse_id=request.form.get("target_warehouse_id", ""),
            items=item_payload,
            order_date=request.form.get("order_date", ""),
            status=request.form.get("status", "Draft"),
            is_auto_generated=False,
            notes=request.form.get("notes", ""),
        )
        flash(
            f"Purchase Order '{res['po_number']}' ({res['status']}) created successfully.",
            "success",
        )
        return redirect(url_for("purchases_bp.index", inspect_id=res["po_id"]))
    except ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("purchases_bp.index"))


@purchases_bp.route("/purchases/<int:po_id>/status", methods=["POST"])
def change_status(po_id: int):
    new_status = request.form.get("status", "")
    try:
        update_purchase_order_status(po_id=po_id, new_status=new_status)
        flash(f"Purchase order status updated to '{new_status}'.", "success")
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("purchases_bp.index", inspect_id=po_id))


@purchases_bp.route("/receipts", methods=["GET"])
def receipts():
    selected_po_id = request.args.get("po_id", type=int)
    all_pos = list_purchase_orders()
    receivable_pos = [
        po
        for po in all_pos
        if po["status"] in ("Draft", "Pending", "Partially Received")
        and po["total_pending"] > 0
    ]

    if not selected_po_id and receivable_pos:
        selected_po_id = int(receivable_pos[0]["id"])

    selected_po = (
        get_purchase_order_details(selected_po_id) if selected_po_id else None
    )
    grn_history = list_goods_receipts()
    warehouses = list_warehouses(active_only=True)

    return render_template(
        "receipts.html",
        receivable_pos=receivable_pos,
        selected_po=selected_po,
        grn_history=grn_history,
        warehouses=warehouses,
        today_iso=date.today().isoformat(),
        active_page="receipts",
    )


@purchases_bp.route("/receipts/create", methods=["POST"])
def create_receipt():
    po_id = request.form.get("po_id", type=int)
    try:
        receipt_line = {
            "po_item_id": request.form.get("po_item_id", ""),
            "received_quantity": request.form.get("received_quantity", ""),
            "unit_cost": request.form.get("unit_cost", ""),
            "batch_number": request.form.get("batch_number", ""),
            "mfg_date": request.form.get("mfg_date", ""),
            "expiry_date": request.form.get("expiry_date", ""),
        }
        res = receive_goods(
            po_id=po_id or 0,
            receipt_items=[receipt_line],
            warehouse_id=request.form.get("warehouse_id"),
            receipt_date=request.form.get("receipt_date", ""),
            notes=request.form.get("notes", ""),
        )
        flash(
            f"Goods Receipt '{res['grn_number']}' recorded for {res['po_number']}. "
            f"Purchase Order status is now '{res['po_status']}'.",
            "success",
        )
        return redirect(url_for("purchases_bp.receipts", po_id=res["po_id"]))
    except ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("purchases_bp.receipts", po_id=po_id))
