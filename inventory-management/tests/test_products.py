import os
import tempfile
import unittest
from database import create_connection, init_db
from integrations.supplier_adapter import (
    SupplierIntegrationAdapter,
    SupplierIntegrationError,
)
from services import ValidationError
from services.product_service import (
    create_product,
    delete_product,
    list_products,
)
from services.supplier_service import (
    check_external_supplier_catalog,
    create_supplier,
)
from services.warehouse_service import create_warehouse, list_warehouses


class TestMasterDataAndIntegration(unittest.TestCase):
    """Unit tests for Products, Warehouses, Suppliers, and Simulated Supplier Integration."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        init_db(self.db_path)
        self.conn = create_connection(self.db_path)

    def tearDown(self):
        self.conn.close()
        os.close(self.db_fd)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_supplier_and_product_creation(self):
        supplier_id = create_supplier(
            supplier_code="SUP-APEX-01",
            name="Apex Pharma Distributors",
            contact_person="Rajesh Sharma",
            email="orders@apexpharma.in",
            phone="+91-9810011223",
            address="Okhla Phase III, New Delhi",
            conn=self.conn,
        )
        product_id = create_product(
            sku="MED-AMOX-250",
            name="Amoxicillin 250mg Capsules",
            description="Strip of 10 capsules",
            category="Antibiotics",
            unit="Strips",
            reorder_level=35,
            preferred_supplier_id=supplier_id,
            conn=self.conn,
        )
        self.assertGreater(product_id, 0)
        products = list_products(conn=self.conn)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["sku"], "MED-AMOX-250")
        self.assertEqual(products[0]["supplier_name"], "Apex Pharma Distributors")

    def test_duplicate_sku_rejected(self):
        create_product(
            sku="ELEC-SENS-01",
            name="Industrial Temperature Sensor",
            description="PT100 Probe",
            category="Sensors",
            unit="Pieces",
            reorder_level=10,
            conn=self.conn,
        )
        with self.assertRaises(ValidationError):
            create_product(
                sku="elec-sens-01",
                name="Duplicate Sensor",
                description="",
                category="Sensors",
                unit="Pieces",
                reorder_level=5,
                conn=self.conn,
            )

    def test_negative_reorder_level_rejected(self):
        with self.assertRaises(ValidationError):
            create_product(
                sku="BAD-REORDER-01",
                name="Invalid Threshold Item",
                description="",
                category="General",
                unit="Units",
                reorder_level=-5,
                conn=self.conn,
            )

    def test_warehouse_creation_and_duplicate_code_rejection(self):
        wh_id = create_warehouse(
            warehouse_code="WH-FBD-01",
            name="Faridabad Regional Depot",
            location="Faridabad, Haryana",
            address="Sector 24 Industrial Area",
            conn=self.conn,
        )
        self.assertGreater(wh_id, 0)
        warehouses = list_warehouses(conn=self.conn)
        self.assertEqual(len(warehouses), 1)

        with self.assertRaises(ValidationError):
            create_warehouse(
                warehouse_code="wh-fbd-01",
                name="Duplicate Depot",
                location="Faridabad",
                conn=self.conn,
            )

    def test_prevent_product_deletion_when_batch_exists(self):
        prod_id = create_product(
            sku="CHEM-ETH-500",
            name="Lab Ethanol 500ml",
            description="Analytical reagent",
            category="Chemicals",
            unit="Bottles",
            reorder_level=15,
            conn=self.conn,
        )
        self.conn.execute(
            """
            INSERT INTO batches (
                batch_number, product_id, unit_cost, receipt_date, initial_quantity
            )
            VALUES ('BATCH-ETH-01', ?, 180.0, '2026-11-01', 40)
            """,
            (prod_id,),
        )
        self.conn.commit()

        with self.assertRaises(ValidationError):
            delete_product(prod_id, conn=self.conn)

    def test_simulated_supplier_integration_success_failure_and_timeout(self):
        sup_id = create_supplier(
            supplier_code="SUP-APEX-01",
            name="Apex Pharma Distributors",
            contact_person="Rajesh Sharma",
            email="orders@apexpharma.in",
            phone="+91-9810011223",
            address="Okhla Phase III, New Delhi",
            conn=self.conn,
        )
        prod_id = create_product(
            sku="MED-PARA-500",
            name="Paracetamol 500mg",
            description="Blister pack",
            category="Pharmaceuticals",
            unit="Packs",
            reorder_level=40,
            preferred_supplier_id=sup_id,
            conn=self.conn,
        )

        # 1. Success response
        ok_res = check_external_supplier_catalog(
            supplier_id=sup_id,
            product_id=prod_id,
            requested_quantity=50,
            simulation_mode="SUCCESS",
            conn=self.conn,
        )
        self.assertTrue(ok_res["ok"])
        self.assertTrue(ok_res["simulated"])
        self.assertEqual(ok_res["status"], "VERIFIED")
        self.assertEqual(ok_res["unit_price"], 45.00)

        # 2. MOQ violation response
        moq_res = check_external_supplier_catalog(
            supplier_id=sup_id,
            product_id=prod_id,
            requested_quantity=5,  # Below MOQ 20
            simulation_mode="SUCCESS",
            conn=self.conn,
        )
        self.assertFalse(moq_res["ok"])
        self.assertEqual(moq_res["status"], "MOQ_VIOLATION")

        # 3. Simulated business failure response
        fail_res = check_external_supplier_catalog(
            supplier_id=sup_id,
            product_id=prod_id,
            requested_quantity=50,
            simulation_mode="FAILURE",
            conn=self.conn,
        )
        self.assertFalse(fail_res["ok"])
        self.assertEqual(fail_res["status"], "REJECTED_BY_SUPPLIER")

        # 4. Simulated gateway timeout handled cleanly by service layer
        timeout_res = check_external_supplier_catalog(
            supplier_id=sup_id,
            product_id=prod_id,
            requested_quantity=50,
            simulation_mode="TIMEOUT",
            conn=self.conn,
        )
        self.assertFalse(timeout_res["ok"])
        self.assertEqual(timeout_res["status"], "GATEWAY_TIMEOUT")

        # Direct adapter exception test
        adapter = SupplierIntegrationAdapter()
        with self.assertRaises(SupplierIntegrationError):
            adapter.verify_supplier_product(
                "SUP-APEX-01", "MED-PARA-500", 50, simulation_mode="UNAVAILABLE"
            )


if __name__ == "__main__":
    unittest.main()
