from datetime import date
from flask import Blueprint, flash, redirect, render_template, request, url_for
from services import ValidationError
from services.inventory_service import list_batch_inventory
from services.return_service import list_supplier_returns, process_supplier_return
from services.supplier_service import list_suppliers
from services.warehouse_service import list_warehouses

returns_bp = Blueprint("returns_bp", __name__)


@returns_bp.route("/returns", methods=["GET"])
def index():
    returns_list = list_supplier_returns()
    holdings = list_batch_inventory()
    suppliers = list_suppliers(active_only=False)
    warehouses = list_warehouses(active_only=False)

    return render_template(
        "returns.html",
        returns_list=returns_list,
        holdings=holdings,
        suppliers=suppliers,
        warehouses=warehouses,
        today_iso=date.today().isoformat(),
        active_page="returns",
    )


@returns_bp.route("/returns/create", methods=["POST"])
def create():
    try:
        res = process_supplier_return(
            supplier_id=request.form.get("supplier_id", ""),
            warehouse_id=request.form.get("warehouse_id", ""),
            batch_id=request.form.get("batch_id", ""),
            return_quantity=request.form.get("return_quantity", ""),
            reason=request.form.get("reason", ""),
            return_date=request.form.get("return_date", ""),
        )
        flash(
            f"Supplier Return '{res['return_number']}' processed for {res['quantity_returned']} units "
            f"(Value: ₹{res['return_value']:.2f}). Remaining batch stock: {res['remaining_batch_quantity']}.",
            "success",
        )
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("returns_bp.index"))
