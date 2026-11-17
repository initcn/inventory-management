import os
import tempfile
import unittest
from datetime import date, timedelta
from database import create_connection, init_db
from services import ValidationError
from services.fifo_service import issue_stock_fifo
from services.inventory_service import (
    list_batch_inventory,
    list_stock_transactions,
    receive_batch_stock,
)
from services.product_service import create_product
from services.return_service import process_supplier_return
from services.supplier_service import create_supplier
from services.warehouse_service import create_warehouse


class TestFifoAndReturnsPhase5(unittest.TestCase):
    """Unit tests for Phase 5: FIFO Stock Valuation and Supplier Returns."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        init_db(self.db_path)
        self.conn = create_connection(self.db_path)

        self.supplier_id = create_supplier(
            supplier_code="SUP-FIFO-01",
            name="National Surgical Supplies",
            contact_person="Suresh Nair",
            email="suresh@nss.in",
            phone="+91-9810099887",
            address="Connaught Place, New Delhi",
            conn=self.conn,
        )
        self.wh_id = create_warehouse(
            warehouse_code="WH-MAIN-01",
            name="Main Central Warehouse",
            location="New Delhi",
            conn=self.conn,
        )
        self.prod_id = create_product(
            sku="SURG-GLV-M",
            name="Sterile Nitrile Gloves (Box of 100)",
            description="Powder-free examination gloves",
            category="Surgical",
            unit="Boxes",
            reorder_level=20,
            preferred_supplier_id=self.supplier_id,
            conn=self.conn,
        )

    def tearDown(self):
        self.conn.close()
        os.close(self.db_fd)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_fifo_consumption_across_multiple_batches_matches_specification(self):
        receive_batch_stock(
            product_id=self.prod_id,
            warehouse_id=self.wh_id,
            batch_number="BATCH-A",
            quantity=50,
            unit_cost=100.0,
            receipt_date="2026-01-01",
            expiry_date="2028-12-31",
            conn=self.conn,
        )
        receive_batch_stock(
            product_id=self.prod_id,
            warehouse_id=self.wh_id,
            batch_number="BATCH-B",
            quantity=70,
            unit_cost=120.0,
            receipt_date="2026-01-05",
            expiry_date="2028-06-30",
            conn=self.conn,
        )

        issue_res = issue_stock_fifo(
            warehouse_id=self.wh_id,
            product_id=self.prod_id,
            issue_quantity=60,
            issue_date="2026-02-01",
            recipient_reference="Ward-3A",
            conn=self.conn,
        )
        self.assertEqual(issue_res["total_quantity"], 60)
        self.assertEqual(issue_res["total_cost"], 6200.0)
        self.assertEqual(len(issue_res["breakdown"]), 2)

        first_leg, second_leg = issue_res["breakdown"]
        self.assertEqual(first_leg["batch_number"], "BATCH-A")
        self.assertEqual(first_leg["quantity_consumed"], 50)
        self.assertEqual(first_leg["line_cost"], 5000.0)
        self.assertEqual(first_leg["remaining_in_batch"], 0)

        self.assertEqual(second_leg["batch_number"], "BATCH-B")
        self.assertEqual(second_leg["quantity_consumed"], 10)
        self.assertEqual(second_leg["line_cost"], 1200.0)
        self.assertEqual(second_leg["remaining_in_batch"], 60)

    def test_expired_batch_excluded_from_fifo_issue(self):
        today = date.today()
        past_expiry = (today - timedelta(days=3)).isoformat()
        future_expiry = (today + timedelta(days=180)).isoformat()

        receive_batch_stock(
            product_id=self.prod_id,
            warehouse_id=self.wh_id,
            batch_number="BATCH-EXP-OLD",
            quantity=40,
            unit_cost=80.0,
            receipt_date="2025-05-01",
            mfg_date="2025-04-01",
            expiry_date=past_expiry,
            conn=self.conn,
        )
        receive_batch_stock(
            product_id=self.prod_id,
            warehouse_id=self.wh_id,
            batch_number="BATCH-VALID-NEW",
            quantity=30,
            unit_cost=110.0,
            receipt_date="2026-05-01",
            mfg_date="2026-04-01",
            expiry_date=future_expiry,
            conn=self.conn,
        )

        res = issue_stock_fifo(
            warehouse_id=self.wh_id,
            product_id=self.prod_id,
            issue_quantity=25,
            issue_date=today.isoformat(),
            conn=self.conn,
        )
        self.assertEqual(len(res["breakdown"]), 1)
        self.assertEqual(res["breakdown"][0]["batch_number"], "BATCH-VALID-NEW")
        self.assertEqual(res["total_cost"], 2750.0)

        with self.assertRaises(ValidationError):
            issue_stock_fifo(
                warehouse_id=self.wh_id,
                product_id=self.prod_id,
                issue_quantity=10,
                issue_date=today.isoformat(),
                conn=self.conn,
            )

    def test_supplier_return_validation_and_transaction_logging(self):
        batch = receive_batch_stock(
            product_id=self.prod_id,
            warehouse_id=self.wh_id,
            batch_number="BATCH-RET-01",
            quantity=20,
            unit_cost=105.0,
            receipt_date="2026-10-01",
            conn=self.conn,
        )
        batch_id = batch["batch_id"]

        with self.assertRaises(ValidationError):
            process_supplier_return(
                supplier_id=self.supplier_id,
                warehouse_id=self.wh_id,
                batch_id=batch_id,
                return_quantity=25,
                reason="Over-return test",
                conn=self.conn,
            )

        ret = process_supplier_return(
            supplier_id=self.supplier_id,
            warehouse_id=self.wh_id,
            batch_id=batch_id,
            return_quantity=8,
            reason="Damaged outer cartons on arrival",
            return_date="2026-11-12",
            conn=self.conn,
        )
        self.assertEqual(ret["remaining_batch_quantity"], 12)
        self.assertEqual(ret["return_value"], 840.0)

        holdings = list_batch_inventory(
            warehouse_id=self.wh_id, product_id=self.prod_id, conn=self.conn
        )
        self.assertEqual(holdings[0]["remaining_quantity"], 12)

        tx_rows = list_stock_transactions(
            product_id=self.prod_id,
            transaction_type="SUPPLIER_RETURN",
            conn=self.conn,
        )
        self.assertEqual(len(tx_rows), 1)
        self.assertEqual(tx_rows[0]["quantity"], -8)


if __name__ == "__main__":
    unittest.main()
