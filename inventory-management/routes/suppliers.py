from flask import Blueprint, flash, redirect, render_template, request, url_for
from services import ValidationError
from services.product_service import list_products
from services.supplier_service import (
    check_external_supplier_catalog,
    create_supplier,
    get_supplier,
    get_supplier_associations,
    list_suppliers,
    update_supplier,
)

suppliers_bp = Blueprint("suppliers_bp", __name__)


@suppliers_bp.route("/suppliers", methods=["GET"])
def index():
    suppliers = list_suppliers(active_only=False)
    products = list_products()
    edit_id = request.args.get("edit_id", type=int)
    inspect_id = request.args.get("inspect_id", type=int)

    edit_supplier = get_supplier(edit_id) if edit_id else None
    inspected_supplier = get_supplier(inspect_id) if inspect_id else None
    associations = (
        get_supplier_associations(inspect_id)
        if inspected_supplier
        else {"products": [], "purchase_orders": []}
    )

    return render_template(
        "suppliers.html",
        suppliers=suppliers,
        products=products,
        edit_supplier=edit_supplier,
        inspected_supplier=inspected_supplier,
        associations=associations,
        integration_result=None,
        active_page="suppliers",
    )


@suppliers_bp.route("/suppliers/create", methods=["POST"])
def create():
    try:
        create_supplier(
            supplier_code=request.form.get("supplier_code", ""),
            name=request.form.get("name", ""),
            contact_person=request.form.get("contact_person", ""),
            email=request.form.get("email", ""),
            phone=request.form.get("phone", ""),
            address=request.form.get("address", ""),
            is_active=request.form.get("is_active") == "1",
        )
        flash("Supplier created successfully.", "success")
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("suppliers_bp.index"))


@suppliers_bp.route("/suppliers/<int:supplier_id>/edit", methods=["POST"])
def edit(supplier_id: int):
    try:
        update_supplier(
            supplier_id=supplier_id,
            supplier_code=request.form.get("supplier_code", ""),
            name=request.form.get("name", ""),
            contact_person=request.form.get("contact_person", ""),
            email=request.form.get("email", ""),
            phone=request.form.get("phone", ""),
            address=request.form.get("address", ""),
            is_active=request.form.get("is_active") == "1",
        )
        flash("Supplier details updated successfully.", "success")
        return redirect(url_for("suppliers_bp.index"))
    except ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("suppliers_bp.index", edit_id=supplier_id))


@suppliers_bp.route("/suppliers/verify-integration", methods=["POST"])
def verify_integration():
    suppliers = list_suppliers(active_only=False)
    products = list_products()
    integration_result = None

    try:
        integration_result = check_external_supplier_catalog(
            supplier_id=request.form.get("supplier_id", ""),
            product_id=request.form.get("product_id", ""),
            requested_quantity=request.form.get("requested_quantity", "25"),
            simulation_mode=request.form.get("simulation_mode", "SUCCESS"),
        )
        if integration_result["ok"]:
            flash(integration_result["message"], "success")
        else:
            flash(
                f"[{integration_result['status']}] {integration_result['message']}",
                "error",
            )
    except ValidationError as exc:
        flash(str(exc), "error")

    return render_template(
        "suppliers.html",
        suppliers=suppliers,
        products=products,
        edit_supplier=None,
        inspected_supplier=None,
        associations={"products": [], "purchase_orders": []},
        integration_result=integration_result,
        active_page="suppliers",
    )
