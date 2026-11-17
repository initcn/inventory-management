from flask import Blueprint, flash, redirect, render_template, request, url_for
from services import ValidationError
from services.product_service import (
    create_product,
    delete_product,
    get_product,
    list_products,
    update_product,
)
from services.supplier_service import list_suppliers

products_bp = Blueprint("products_bp", __name__)


@products_bp.route("/products", methods=["GET"])
def index():
    products = list_products()
    suppliers = list_suppliers(active_only=False)
    edit_id = request.args.get("edit_id", type=int)
    edit_product = get_product(edit_id) if edit_id else None
    return render_template(
        "products.html",
        products=products,
        suppliers=suppliers,
        edit_product=edit_product,
        active_page="products",
    )


@products_bp.route("/products/create", methods=["POST"])
def create():
    try:
        create_product(
            sku=request.form.get("sku", ""),
            name=request.form.get("name", ""),
            description=request.form.get("description", ""),
            category=request.form.get("category", ""),
            unit=request.form.get("unit", "Units"),
            reorder_level=request.form.get("reorder_level", "0"),
            preferred_supplier_id=request.form.get("preferred_supplier_id"),
        )
        flash("Product created successfully.", "success")
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("products_bp.index"))


@products_bp.route("/products/<int:product_id>/edit", methods=["POST"])
def edit(product_id: int):
    try:
        update_product(
            product_id=product_id,
            sku=request.form.get("sku", ""),
            name=request.form.get("name", ""),
            description=request.form.get("description", ""),
            category=request.form.get("category", ""),
            unit=request.form.get("unit", "Units"),
            reorder_level=request.form.get("reorder_level", "0"),
            preferred_supplier_id=request.form.get("preferred_supplier_id"),
        )
        flash("Product details updated successfully.", "success")
        return redirect(url_for("products_bp.index"))
    except ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("products_bp.index", edit_id=product_id))


@products_bp.route("/products/<int:product_id>/delete", methods=["POST"])
def delete(product_id: int):
    try:
        delete_product(product_id)
        flash("Product deleted successfully.", "success")
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("products_bp.index"))
