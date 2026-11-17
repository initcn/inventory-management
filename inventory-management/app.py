import os
from flask import Flask, flash, redirect, render_template, url_for
from config import Config
from database import close_db, init_db, query_all, query_one
from routes.inventory import inventory_bp
from routes.products import products_bp
from routes.purchases import purchases_bp
from routes.returns import returns_bp
from routes.suppliers import suppliers_bp
from routes.transfers import transfers_bp
from routes.warehouses import warehouses_bp
from seed import seed_demo_data


def get_dashboard_metrics() -> dict:
    """Query live summary KPIs for the main dashboard."""
    total_products = query_one("SELECT COUNT(*) AS cnt FROM products")["cnt"]
    total_warehouses = query_one(
        "SELECT COUNT(*) AS cnt FROM warehouses WHERE is_active = 1"
    )["cnt"]
    total_stock = query_one(
        "SELECT COALESCE(SUM(quantity), 0) AS total FROM inventory"
    )["total"]

    below_reorder_rows = query_all(
        """
        SELECT p.id, p.sku, p.name, p.reorder_level,
               COALESCE(SUM(
                   CASE
                       WHEN w.is_active = 1
                        AND (b.expiry_date IS NULL OR date(b.expiry_date) >= date('now'))
                       THEN i.quantity
                       ELSE 0
                   END
               ), 0) AS available_stock
        FROM products p
        LEFT JOIN inventory i ON i.product_id = p.id
        LEFT JOIN batches b ON b.id = i.batch_id
        LEFT JOIN warehouses w ON w.id = i.warehouse_id
        GROUP BY p.id
        HAVING available_stock <= p.reorder_level
        ORDER BY available_stock ASC
        """
    )

    expired_batches = query_one(
        """
        SELECT COUNT(DISTINCT b.id) AS cnt
        FROM batches b
        JOIN inventory i ON i.batch_id = b.id
        WHERE i.quantity > 0
          AND b.expiry_date IS NOT NULL
          AND date(b.expiry_date) < date('now')
        """
    )["cnt"]

    near_expiry_batches = query_one(
        """
        SELECT COUNT(DISTINCT b.id) AS cnt
        FROM batches b
        JOIN inventory i ON i.batch_id = b.id
        WHERE i.quantity > 0
          AND b.expiry_date IS NOT NULL
          AND date(b.expiry_date) >= date('now')
          AND date(b.expiry_date) <= date('now', '+30 days')
        """
    )["cnt"]

    pending_pos = query_one(
        """
        SELECT COUNT(*) AS cnt
        FROM purchase_orders
        WHERE status IN ('Draft', 'Pending', 'Partially Received')
        """
    )["cnt"]

    pending_transfers = query_one(
        """
        SELECT COUNT(*) AS cnt
        FROM transfers
        WHERE status IN ('Draft', 'Dispatched', 'Partially Received')
        """
    )["cnt"]

    recent_transactions = query_all(
        """
        SELECT st.id, st.transaction_type, st.quantity, st.unit_cost,
               st.reference_type, st.reference_id, st.created_at,
               p.sku, p.name AS product_name,
               b.batch_number,
               w.name AS warehouse_name
        FROM stock_transactions st
        JOIN products p ON p.id = st.product_id
        JOIN batches b ON b.id = st.batch_id
        JOIN warehouses w ON w.id = st.warehouse_id
        ORDER BY st.id DESC
        LIMIT 8
        """
    )

    return {
        "total_products": total_products,
        "total_warehouses": total_warehouses,
        "total_stock": total_stock,
        "below_reorder_count": len(below_reorder_rows),
        "below_reorder_items": below_reorder_rows,
        "expired_batches": expired_batches,
        "near_expiry_batches": near_expiry_batches,
        "pending_pos": pending_pos,
        "pending_transfers": pending_transfers,
        "recent_transactions": recent_transactions,
    }


def create_app(test_config: dict | None = None) -> Flask:
    """Create and configure the Flask application instance."""
    app = Flask(__name__)
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    init_db(app.config["DATABASE_PATH"], app.config["SCHEMA_PATH"])
    app.teardown_appcontext(close_db)

    @app.context_processor
    def inject_globals():
        return {"currency_symbol": app.config.get("CURRENCY_SYMBOL", "₹")}

    # Register all application blueprints
    app.register_blueprint(products_bp)
    app.register_blueprint(warehouses_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(purchases_bp)
    app.register_blueprint(transfers_bp)
    app.register_blueprint(returns_bp)

    # Endpoint aliases for clean url_for(...) navigation across all 11 pages
    app.add_url_rule("/products", endpoint="products", view_func=app.view_functions["products_bp.index"])
    app.add_url_rule("/warehouses", endpoint="warehouses", view_func=app.view_functions["warehouses_bp.index"])
    app.add_url_rule("/suppliers", endpoint="suppliers", view_func=app.view_functions["suppliers_bp.index"])
    app.add_url_rule("/inventory", endpoint="inventory", view_func=app.view_functions["inventory_bp.index"])
    app.add_url_rule("/valuation", endpoint="valuation", view_func=app.view_functions["inventory_bp.valuation"])
    app.add_url_rule("/transactions", endpoint="transactions", view_func=app.view_functions["inventory_bp.transactions"])
    app.add_url_rule("/purchases", endpoint="purchases", view_func=app.view_functions["purchases_bp.index"])
    app.add_url_rule("/receipts", endpoint="receipts", view_func=app.view_functions["purchases_bp.receipts"])
    app.add_url_rule("/transfers", endpoint="transfers", view_func=app.view_functions["transfers_bp.index"])
    app.add_url_rule("/returns", endpoint="returns", view_func=app.view_functions["returns_bp.index"])

    @app.route("/")
    def dashboard():
        metrics = get_dashboard_metrics()
        return render_template("dashboard.html", metrics=metrics, active_page="dashboard")

    @app.route("/seed-demo", methods=["POST"])
    def seed_demo():
        result = seed_demo_data(app.config["DATABASE_PATH"], force_reset=False)
        flash(result["message"], "success" if result["seeded"] else "info")
        return redirect(url_for("dashboard"))

    return app


if __name__ == "__main__":
    flask_app = create_app()
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="127.0.0.1", port=port, debug=True)
