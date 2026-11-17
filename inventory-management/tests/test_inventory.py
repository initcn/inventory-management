import os
import tempfile
import unittest
from datetime import date, timedelta
from database import create_connection, init_db
from services import ValidationError
from services.inventory_service import (
    adjust_batch_stock,
    get_expiry_alerts,
    list_batch_inventory,
    list_product_stock_summary,
    list_stock_transactions,
    receive_batch_stock,
)
from services.product_service import create_product
from services.warehouse_service import create_warehouse


class TestInventoryPhase3(unittest.TestCase):
    """Unit tests for Phase 3: Batch Inventory, Expiry Tracking, and Transactions."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        init_db(self.db_path)
        self.conn = create_connection(self.db_path)

        self.wh_id = create_warehouse(
            warehouse_code="WH-DEL-01",
            name="Delhi Central Warehouse",
            location="New Delhi",
            conn=self.conn,
        )
        self.prod_id = create_product(
            sku="MED-INS-100",
            name="Insulin Vial 10ml",
            description="Cold chain biologic",
            category="Biologics",
            unit="Vials",
            reorder_level=25,
            conn=self.conn,
        )

    def tearDown(self):
        self.conn.close()
        os.close(self.db_fd)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_batch_creation_and_transaction_logging(self):
        res = receive_batch_stock(
            product_id=self.prod_id,
            warehouse_id=self.wh_id,
            batch_number="BATCH-INS-01",
            quantity=60,
            unit_cost=450.0,
            receipt_date="2026-10-01",
            mfg_date="2026-09-01",
            expiry_date="2027-09-01",
            conn=self.conn,
        )
        self.assertEqual(res["warehouse_quantity"], 60)

        holdings = list_batch_inventory(
            warehouse_id=self.wh_id, product_id=self.prod_id, conn=self.conn
        )
        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0]["remaining_quantity"], 60)
        self.assertEqual(holdings[0]["stock_value"], 27000.0)

        tx_list = list_stock_transactions(product_id=self.prod_id, conn=self.conn)
        self.assertEqual(len(tx_list), 1)
        self.assertEqual(tx_list[0]["transaction_type"], "GOODS_RECEIPT")
        self.assertEqual(tx_list[0]["quantity"], 60)

    def test_expiry_before_manufacturing_date_rejected(self):
        with self.assertRaises(ValidationError):
            receive_batch_stock(
                product_id=self.prod_id,
                warehouse_id=self.wh_id,
                batch_number="BATCH-BAD-DATE",
                quantity=20,
                unit_cost=100.0,
                receipt_date="2026-10-10",
                mfg_date="2026-10-05",
                expiry_date="2026-09-15",
                conn=self.conn,
            )

    def test_expired_and_near_expiry_identification(self):
        today = date.today()
        past_date = (today - timedelta(days=5)).isoformat()
        near_date = (today + timedelta(days=12)).isoformat()
        mfg_past = (today - timedelta(days=120)).isoformat()

        receive_batch_stock(
            product_id=self.prod_id,
            warehouse_id=self.wh_id,
            batch_number="BATCH-EXP-01",
            quantity=15,
            unit_cost=400.0,
            receipt_date=mfg_past,
            mfg_date=mfg_past,
            expiry_date=past_date,
            conn=self.conn,
        )
        receive_batch_stock(
            product_id=self.prod_id,
            warehouse_id=self.wh_id,
            batch_number="BATCH-NEAR-01",
            quantity=30,
            unit_cost=420.0,
            receipt_date=mfg_past,
            mfg_date=mfg_past,
            expiry_date=near_date,
            conn=self.conn,
        )

        alerts = get_expiry_alerts(conn=self.conn)
        self.assertEqual(len(alerts["expired"]), 1)
        self.assertEqual(alerts["expired"][0]["batch_number"], "BATCH-EXP-01")
        self.assertEqual(len(alerts["near_expiry"]), 1)
        self.assertEqual(alerts["near_expiry"][0]["batch_number"], "BATCH-NEAR-01")

        summary = list_product_stock_summary(conn=self.conn)
        self.assertEqual(summary[0]["total_quantity"], 45)
        self.assertEqual(summary[0]["eligible_quantity"], 30)
        self.assertEqual(summary[0]["expired_quantity"], 15)

    def test_prevention_of_negative_stock_on_adjustment(self):
        res = receive_batch_stock(
            product_id=self.prod_id,
            warehouse_id=self.wh_id,
            batch_number="BATCH-ADJ-01",
            quantity=25,
            unit_cost=200.0,
            receipt_date="2026-11-01",
            conn=self.conn,
        )
        batch_id = res["batch_id"]

        updated_qty = adjust_batch_stock(
            warehouse_id=self.wh_id,
            batch_id=batch_id,
            quantity_delta=-10,
            reason="Damaged vial write-off",
            conn=self.conn,
        )
        self.assertEqual(updated_qty, 15)

        with self.assertRaises(ValidationError):
            adjust_batch_stock(
                warehouse_id=self.wh_id,
                batch_id=batch_id,
                quantity_delta=-20,
                reason="Invalid over-deduction",
                conn=self.conn,
            )


if __name__ == "__main__":
    unittest.main()
