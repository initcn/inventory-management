from datetime import date
from flask import Blueprint, flash, redirect, render_template, request, url_for
from services import ValidationError
from services.inventory_service import list_batch_inventory
from services.transfer_service import (
    VALID_TRANSFER_STATUSES,
    cancel_transfer,
    create_transfer,
    dispatch_transfer,
    list_transfers,
    receive_transfer,
)
from services.warehouse_service import list_warehouses

transfers_bp = Blueprint("transfers_bp", __name__)


@transfers_bp.route("/transfers", methods=["GET"])
def index():
    status_filter = request.args.get("status", default="", type=str).strip()
    transfers = list_transfers(status_filter=status_filter or None)
    warehouses = list_warehouses(active_only=True)
    eligible_holdings = list_batch_inventory(expiry_filter="ELIGIBLE")

    return render_template(
        "transfers.html",
        transfers=transfers,
        warehouses=warehouses,
        eligible_holdings=eligible_holdings,
        statuses=VALID_TRANSFER_STATUSES,
        status_filter=status_filter,
        today_iso=date.today().isoformat(),
        active_page="transfers",
    )


@transfers_bp.route("/transfers/create", methods=["POST"])
def create():
    try:
        auto_dispatch = request.form.get("initial_action", "dispatch") == "dispatch"
        res = create_transfer(
            source_warehouse_id=request.form.get("source_warehouse_id", ""),
            dest_warehouse_id=request.form.get("dest_warehouse_id", ""),
            batch_id=request.form.get("batch_id", ""),
            quantity=request.form.get("quantity", ""),
            transfer_date=request.form.get("transfer_date", ""),
            notes=request.form.get("notes", ""),
            auto_dispatch=auto_dispatch,
        )
        flash(
            f"Stock Transfer '{res['transfer_number']}' created with status '{res['status']}'.",
            "success",
        )
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("transfers_bp.index"))


@transfers_bp.route("/transfers/<int:transfer_id>/dispatch", methods=["POST"])
def dispatch(transfer_id: int):
    try:
        res = dispatch_transfer(transfer_id)
        flash(
            f"Transfer '{res['transfer_number']}' dispatched. Source stock deducted and now in transit.",
            "success",
        )
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("transfers_bp.index"))


@transfers_bp.route("/transfers/<int:transfer_id>/receive", methods=["POST"])
def receive(transfer_id: int):
    try:
        recv_qty = request.form.get("receive_quantity")
        res = receive_transfer(transfer_id, receive_quantity=recv_qty)
        flash(
            f"Transfer '{res['transfer_number']}' received at destination warehouse (Status: '{res['status']}').",
            "success",
        )
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("transfers_bp.index"))


@transfers_bp.route("/transfers/<int:transfer_id>/cancel", methods=["POST"])
def cancel(transfer_id: int):
    try:
        res = cancel_transfer(transfer_id)
        flash(
            f"Transfer '{res['transfer_number']}' cancelled.",
            "info",
        )
    except ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("transfers_bp.index"))
