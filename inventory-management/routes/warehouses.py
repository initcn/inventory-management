from flask import Blueprint, flash, redirect, render_template, request, url_for
from services import ValidationError
from services.warehouse_service import (
    create_warehouse,
    get_warehouse,
    get_warehouse_stock,
    list_warehouses,
    update_warehouse,
)

warehouses_bp = Blueprint("warehouses_bp", __name__)


@warehouses_bp.route("/warehouses", methods=["GET"])
def index():
    warehouses = list_warehouses(active_only=False)
    edit_id = request.args.get("edit_id", type=int)
    inspect_id = request.args.get("inspect_id", type=int)

    edit_warehouse = get_warehouse(edit_id) if edit_id else None
    inspected_warehouse = get_warehouse(inspect_id) if inspect_id else None
    warehouse_stock = (
        get_warehouse_stock(inspect_id) if inspected_warehouse else []
    )

    return render_template(
        "warehouses.html",
        warehouses=warehouses,
        edit_warehouse=edit_warehouse,
        inspected_warehouse=inspected_warehouse,
        warehouse_stock=warehouse_stock,
        active_page="warehouses",
    )


@warehouses_bp.route("/warehouses/create", methods=["POST"])
def create():
    try:
        create_warehouse(
            warehouse_code=request.form.get("warehouse_code", ""),
            name=request.form.get("name", ""),
            location=request.form.get("location", ""),
            address=request.form.get("address", ""),
            is_active=request.form.get("is_active") == "1",
        )
        flash("Warehouse created successfully.", "success")
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("warehouses_bp.index"))


@warehouses_bp.route("/warehouses/<int:warehouse_id>/edit", methods=["POST"])
def edit(warehouse_id: int):
    try:
        update_warehouse(
            warehouse_id=warehouse_id,
            warehouse_code=request.form.get("warehouse_code", ""),
            name=request.form.get("name", ""),
            location=request.form.get("location", ""),
            address=request.form.get("address", ""),
            is_active=request.form.get("is_active") == "1",
        )
        flash("Warehouse updated successfully.", "success")
        return redirect(url_for("warehouses_bp.index"))
    except ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("warehouses_bp.index", edit_id=warehouse_id))
