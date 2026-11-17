import os
import tempfile
import unittest
from database import create_connection, init_db
from services import ValidationError
from services.inventory_service import list_batch_inventory, receive_batch_stock
from services.product_service import create_product
from services.transfer_service import create_transfer, receive_transfer
from services.warehouse_service import create_warehouse


class TestTransfersPhase5(unittest.TestCase):
    """Unit tests for Phase 5: Inter-Warehouse Stock Transfers."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        init_db(self.db_path)
        self.conn = create_connection(self.db_path)

        self.wh_source = create_warehouse(
            warehouse_code="WH-SRC-01",
            name="Source Hub Noida",
            location="Noida, UP",
            conn=self.conn,
        )
        self.wh_dest = create_warehouse(
            warehouse_code="WH-DST-02",
            name="Destination Hub Faridabad",
            location="Faridabad, Haryana",
            conn=self.conn,
        )
        self.prod_id = create_product(
            sku="MED-ORS-20",
            name="ORS Electrolyte Sachet",
            description="WHO formula",
            category="Hydration",
            unit="Sachets",
            reorder_level=50,
            conn=self.conn,
        )
        batch_res = receive_batch_stock(
            product_id=self.prod_id,
            warehouse_id=self.wh_source,
            batch_number="BATCH-ORS-100",
            quantity=100,
            unit_cost=18.50,
            receipt_date="2026-10-15",
            mfg_date="2026-09-01",
            expiry_date="2027-09-01",
            conn=self.conn,
        )
        self.batch_id = batch_res["batch_id"]

    def tearDown(self):
        self.conn.close()
        os.close(self.db_fd)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_successful_two_step_stock_transfer_preserves_batch_identity(self):
        trf = create_transfer(
            source_warehouse_id=self.wh_source,
            dest_warehouse_id=self.wh_dest,
            batch_id=self.batch_id,
            quantity=40,
            transfer_date="2026-11-15",
            auto_dispatch=True,
            conn=self.conn,
        )
        self.assertEqual(trf["status"], "Dispatched")

        src_holdings = list_batch_inventory(
            warehouse_id=self.wh_source, product_id=self.prod_id, conn=self.conn
        )
        dst_holdings_before = list_batch_inventory(
            warehouse_id=self.wh_dest, product_id=self.prod_id, conn=self.conn
        )
        self.assertEqual(src_holdings[0]["remaining_quantity"], 60)
        self.assertEqual(len(dst_holdings_before), 0)

        recv = receive_transfer(trf["transfer_id"], conn=self.conn)
        self.assertEqual(recv["status"], "Received")

        dst_holdings_after = list_batch_inventory(
            warehouse_id=self.wh_dest, product_id=self.prod_id, conn=self.conn
        )
        self.assertEqual(len(dst_holdings_after), 1)
        self.assertEqual(dst_holdings_after[0]["remaining_quantity"], 40)
        self.assertEqual(dst_holdings_after[0]["batch_id"], self.batch_id)
        self.assertEqual(dst_holdings_after[0]["batch_number"], "BATCH-ORS-100")
        self.assertEqual(dst_holdings_after[0]["unit_cost"], 18.50)
        self.assertEqual(dst_holdings_after[0]["expiry_date"], "2027-09-01")

    def test_transfer_with_insufficient_stock_rejected(self):
        with self.assertRaises(ValidationError):
            create_transfer(
                source_warehouse_id=self.wh_source,
                dest_warehouse_id=self.wh_dest,
                batch_id=self.batch_id,
                quantity=150,
                conn=self.conn,
            )

    def test_transfer_to_same_warehouse_rejected(self):
        with self.assertRaises(ValidationError):
            create_transfer(
                source_warehouse_id=self.wh_source,
                dest_warehouse_id=self.wh_source,
                batch_id=self.batch_id,
                quantity=10,
                conn=self.conn,
            )


if __name__ == "__main__":
    unittest.main()
