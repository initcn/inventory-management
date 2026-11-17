import os
import tempfile
import unittest
from datetime import date, timedelta
from database import create_connection, init_db
from seed import seed_demo_data
from services import ValidationError
from services.inventory_service import list_batch_inventory, receive_batch_stock
from services.product_service import create_product, list_products
from services.reorder_service import (
    auto_generate_purchase_orders,
    check_reorder_levels,
    get_purchase_order_details,
    receive_goods,
    update_purchase_order_status,
)
from services.supplier_service import create_supplier
from services.warehouse_service import create_warehouse


class TestPurchasesAndSeed(unittest.TestCase):
    """Unit tests for Reorder detection, PO generation, Partial Goods Receipt, and Idempotent Seed."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        init_db(self.db_path)
        self.conn = create_connection(self.db_path)

        self.supplier_id = create_supplier(
            supplier_code="SUP-BIO-01",
            name="BioCare Formulations",
            contact_person="Vikram Mehta",
            email="vikram@biocare.in",
            phone="+91-9818001122",
            address="Industrial Area Phase 1, Chandigarh",
            conn=self.conn,
        )
        self.warehouse_id = create_warehouse(
            warehouse_code="WH-GGN-01",
            name="Gurugram Distribution Center",
            location="Gurugram, Haryana",
            conn=self.conn,
        )
        self.product_id = create_product(
            sku="MED-AZI-500",
            name="Azithromycin 500mg Tablets",
            description="Pack of 5 tablets",
            category="Antibiotics",
            unit="Packs",
            reorder_level=40,
            preferred_supplier_id=self.supplier_id,
            conn=self.conn,
        )

    def tearDown(self):
        self.conn.close()
        os.close(self.db_fd)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_reorder_detection_ignores_expired_stock_and_prevents_duplicate_pos(self):
        past_date = (date.today() - timedelta(days=10)).isoformat()
        mfg_date = (date.today() - timedelta(days=200)).isoformat()
        receive_batch_stock(
            product_id=self.product_id,
            warehouse_id=self.warehouse_id,
            batch_number="BATCH-AZI-OLD",
            quantity=50,
            unit_cost=85.0,
            receipt_date=mfg_date,
            mfg_date=mfg_date,
            expiry_date=past_date,
            conn=self.conn,
        )

        alerts = check_reorder_levels(conn=self.conn)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["available_stock"], 0)
        self.assertTrue(alerts[0]["can_auto_generate"])

        gen_1 = auto_generate_purchase_orders(
            target_warehouse_id=self.warehouse_id, conn=self.conn
        )
        self.assertEqual(len(gen_1["created_pos"]), 1)
        self.assertEqual(len(gen_1["skipped_open_po"]), 0)

        gen_2 = auto_generate_purchase_orders(
            target_warehouse_id=self.warehouse_id, conn=self.conn
        )
        self.assertEqual(len(gen_2["created_pos"]), 0)
        self.assertEqual(len(gen_2["skipped_open_po"]), 1)

    def test_partial_and_multiple_goods_receipts_against_single_po(self):
        gen = auto_generate_purchase_orders(
            target_warehouse_id=self.warehouse_id, conn=self.conn
        )
        self.assertEqual(len(gen["created_pos"]), 1)

        po_row = self.conn.execute(
            "SELECT id FROM purchase_orders WHERE po_number = ?",
            (gen["created_pos"][0],),
        ).fetchone()
        po_id = int(po_row["id"])

        update_purchase_order_status(po_id, "Pending", conn=self.conn)
        details = get_purchase_order_details(po_id, conn=self.conn)
        po_item = details["items"][0]
        ordered_qty = int(po_item["ordered_quantity"])
        self.assertEqual(ordered_qty, 80)

        r1 = receive_goods(
            po_id=po_id,
            receipt_items=[
                {
                    "po_item_id": po_item["id"],
                    "received_quantity": 30,
                    "unit_cost": 90.0,
                    "batch_number": "BATCH-AZI-P1",
                    "mfg_date": "2026-10-01",
                    "expiry_date": "2027-10-01",
                }
            ],
            receipt_date="2026-11-10",
            conn=self.conn,
        )
        self.assertEqual(r1["po_status"], "Partially Received")

        with self.assertRaises(ValidationError):
            receive_goods(
                po_id=po_id,
                receipt_items=[
                    {
                        "po_item_id": po_item["id"],
                        "received_quantity": 60,
                        "unit_cost": 92.0,
                        "batch_number": "BATCH-AZI-OVER",
                    }
                ],
                conn=self.conn,
            )

        r2 = receive_goods(
            po_id=po_id,
            receipt_items=[
                {
                    "po_item_id": po_item["id"],
                    "received_quantity": 50,
                    "unit_cost": 92.0,
                    "batch_number": "BATCH-AZI-P2",
                    "mfg_date": "2026-10-15",
                    "expiry_date": "2027-10-15",
                }
            ],
            receipt_date="2026-11-14",
            conn=self.conn,
        )
        self.assertEqual(r2["po_status"], "Completed")

        batches = list_batch_inventory(
            warehouse_id=self.warehouse_id, product_id=self.product_id, conn=self.conn
        )
        self.assertEqual(len(batches), 2)
        total_received_stock = sum(b["remaining_quantity"] for b in batches)
        self.assertEqual(total_received_stock, 80)

    def test_seed_demo_data_idempotency(self):
        seed_fd, seed_path = tempfile.mkstemp(suffix=".db")
        os.close(seed_fd)
        try:
            first_run = seed_demo_data(seed_path, force_reset=True)
            self.assertTrue(first_run["seeded"])

            second_run = seed_demo_data(seed_path, force_reset=False)
            self.assertFalse(second_run["seeded"])

            s_conn = create_connection(seed_path)
            try:
                prods = list_products(conn=s_conn)
                self.assertEqual(len(prods), 8)
            finally:
                s_conn.close()
        finally:
            if os.path.exists(seed_path):
                os.remove(seed_path)


if __name__ == "__main__":
    unittest.main()
