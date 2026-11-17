"""
Safe, Idempotent Demonstration Data Seed Script (Section 15).

Populates realistic Indian currency (₹) demonstration data covering:
- 4 Suppliers
- 3 Warehouses (New Delhi, Gurugram, Faridabad)
- 8 Products across Pharmaceuticals, Biologics, Surgical, Diagnostics, and Chemicals
- 11 Stock Batches (multiple batches per product, varied receipt dates, expiry dates, and unit costs,
  including an expired batch and a near-expiry batch within 30 days)
- Products both above and below reorder levels
- 3 Purchase Orders (1 Completed with 2 partial receipts, 1 Partially Received with pending balance, 1 Pending)
- 2 Inter-Warehouse Stock Transfers (1 Completed/Received preserving batch identity, 1 Dispatched in transit)
- 1 Multi-Batch FIFO Stock Issue (60 units: 50 from Batch A @ ₹100 + 10 from Batch B @ ₹120 = ₹6,200)
- 1 Supplier Return (damaged/near-expiry stock returned with transaction audit record)
"""

import sqlite3
from datetime import date, timedelta
from typing import Any, Optional
from database import create_connection, init_db, query_one
from services.fifo_service import issue_stock_fifo
from services.inventory_service import receive_batch_stock
from services.product_service import create_product
from services.reorder_service import (
    generate_purchase_order,
    get_purchase_order_details,
    receive_goods,
    update_purchase_order_status,
)
from services.return_service import process_supplier_return
from services.supplier_service import create_supplier
from services.transfer_service import create_transfer, receive_transfer
from services.warehouse_service import create_warehouse


def seed_demo_data(
    db_path: Optional[str] = None, force_reset: bool = False
) -> dict[str, Any]:
    """
    Safely initialize demonstration data without duplicating records if run repeatedly.
    If the database already has products and force_reset=False, returns immediately.
    """
    init_db(db_path)
    conn = create_connection(db_path)

    try:
        existing_count = query_one("SELECT COUNT(*) AS cnt FROM products", conn=conn)["cnt"]
        if existing_count > 0 and not force_reset:
            return {
                "seeded": False,
                "message": "Demonstration data is already present. Skipping duplicate seed.",
            }

        if force_reset:
            tables_to_clear = [
                "stock_transactions",
                "supplier_return_items",
                "supplier_returns",
                "stock_issue_items",
                "stock_issues",
                "transfer_items",
                "transfers",
                "goods_receipt_items",
                "goods_receipts",
                "purchase_order_items",
                "purchase_orders",
                "inventory",
                "batches",
                "products",
                "warehouses",
                "suppliers",
            ]
            for tbl in tables_to_clear:
                conn.execute(f"DELETE FROM {tbl}")
            conn.commit()

        today = date.today()
        d_past_260 = (today - timedelta(days=260)).isoformat()
        d_past_180 = (today - timedelta(days=180)).isoformat()
        d_past_90 = (today - timedelta(days=90)).isoformat()
        d_past_45 = (today - timedelta(days=45)).isoformat()
        d_past_30 = (today - timedelta(days=30)).isoformat()
        d_past_20 = (today - timedelta(days=20)).isoformat()
        d_past_15 = (today - timedelta(days=15)).isoformat()
        d_past_10 = (today - timedelta(days=10)).isoformat()
        d_past_5 = (today - timedelta(days=5)).isoformat()
        d_near_18 = (today + timedelta(days=18)).isoformat()
        d_future_300 = (today + timedelta(days=300)).isoformat()
        d_future_450 = (today + timedelta(days=450)).isoformat()

        # 1. Create 4 Suppliers
        sup_apex = create_supplier(
            supplier_code="SUP-APEX-01",
            name="Apex Pharma Distributors Pvt. Ltd.",
            contact_person="Rajesh Sharma",
            email="orders@apexpharma.in",
            phone="+91-9810011223",
            address="Okhla Industrial Estate Phase III, New Delhi",
            conn=conn,
        )
        sup_bio = create_supplier(
            supplier_code="SUP-BIO-02",
            name="BioCare Formulations India",
            contact_person="Dr. Meera Krishnan",
            email="supply@biocare.co.in",
            phone="+91-9818044556",
            address="Udyog Vihar Phase IV, Gurugram, Haryana",
            conn=conn,
        )
        sup_surg = create_supplier(
            supplier_code="SUP-SURG-03",
            name="National Surgical & MedTech Co.",
            contact_person="Suresh Nair",
            email="dispatch@nationalsurgical.in",
            phone="+91-9811223344",
            address="Sector 24 Industrial Area, Faridabad, Haryana",
            conn=conn,
        )
        sup_chem = create_supplier(
            supplier_code="SUP-CHEM-04",
            name="Hindustan Clinical Reagents Ltd.",
            contact_person="Anjali Deshmukh",
            email="sales@hindustanreagents.in",
            phone="+91-9871099881",
            address="Sector 62 Electronic City, Noida, UP",
            conn=conn,
        )

        # 2. Create 3 Warehouses
        wh_del = create_warehouse(
            warehouse_code="WH-DEL-01",
            name="Central Delhi Hub",
            location="New Delhi, NCR",
            address="Plot 14, Okhla Industrial Area Phase II, New Delhi",
            conn=conn,
        )
        wh_ggn = create_warehouse(
            warehouse_code="WH-GGN-02",
            name="Gurugram Cold-Chain & Med Depot",
            location="Gurugram, Haryana",
            address="Sector 37 Pace City II, Gurugram",
            conn=conn,
        )
        wh_fbd = create_warehouse(
            warehouse_code="WH-FBD-03",
            name="Faridabad Regional Distribution Center",
            location="Faridabad, Haryana",
            address="Mathura Road Industrial Belt, Sector 27A, Faridabad",
            conn=conn,
        )

        # 3. Create 8 Products
        p_gloves = create_product(
            sku="SURG-GLV-M",
            name="Sterile Nitrile Examination Gloves (Box of 100)",
            description="Powder-free medium nitrile gloves (FIFO valuation benchmark)",
            category="Surgical Supplies",
            unit="Boxes",
            reorder_level=30,
            preferred_supplier_id=sup_surg,
            conn=conn,
        )
        p_para = create_product(
            sku="MED-PARA-500",
            name="Paracetamol 500mg Blister Pack (15x10)",
            description="Standard antipyretic & analgesic",
            category="Pharmaceuticals",
            unit="Packs",
            reorder_level=40,
            preferred_supplier_id=sup_apex,
            conn=conn,
        )
        p_amox = create_product(
            sku="MED-AMOX-250",
            name="Amoxicillin 250mg Capsules (10x10)",
            description="Broad-spectrum penicillin antibiotic",
            category="Antibiotics",
            unit="Boxes",
            reorder_level=35,
            preferred_supplier_id=sup_apex,
            conn=conn,
        )
        p_ins = create_product(
            sku="MED-INS-100",
            name="Human Insulin Injection 100 IU/ml (10ml Vial)",
            description="Cold-chain storage 2°C to 8°C required",
            category="Biologics",
            unit="Vials",
            reorder_level=25,
            preferred_supplier_id=sup_bio,
            conn=conn,
        )
        p_azi = create_product(
            sku="MED-AZI-500",
            name="Azithromycin 500mg Tablets (10x3)",
            description="Macrolide antibiotic pack",
            category="Antibiotics",
            unit="Packs",
            reorder_level=40,
            preferred_supplier_id=sup_bio,
            conn=conn,
        )
        p_ors = create_product(
            sku="MED-ORS-20",
            name="WHO Oral Rehydration Salts (20.5g Sachet)",
            description="Electrolyte replenishment sachet",
            category="Hydration",
            unit="Sachets",
            reorder_level=100,
            preferred_supplier_id=sup_chem,
            conn=conn,
        )
        p_eth = create_product(
            sku="CHEM-ETH-500",
            name="Analytical Grade Ethanol 99.9% (500ml)",
            description="Laboratory disinfectant & solvent",
            category="Laboratory Chemicals",
            unit="Bottles",
            reorder_level=25,
            preferred_supplier_id=sup_chem,
            conn=conn,
        )
        p_mask = create_product(
            sku="SURG-MASK-N95",
            name="NIOSH N95 Particulate Respirator (Pack of 20)",
            description="5-layer clinical respirator mask",
            category="Personal Protective Equipment",
            unit="Packs",
            reorder_level=50,
            preferred_supplier_id=sup_surg,
            conn=conn,
        )

        # 4. Seed Multi-Batch FIFO Benchmark on SURG-GLV-M at WH-DEL-01
        # Batch A: Received 2026-01-01, Qty 50 @ ₹100.00
        # Batch B: Received 2026-01-05, Qty 70 @ ₹120.00
        # Then issue 60 units -> 50 from Batch A + 10 from Batch B = ₹6,200.00 (leaves 60 in Batch B)
        receive_batch_stock(
            product_id=p_gloves,
            warehouse_id=wh_del,
            batch_number="BATCH-GLV-A",
            quantity=50,
            unit_cost=100.00,
            receipt_date="2026-01-01",
            mfg_date="2025-12-01",
            expiry_date=d_future_450,
            supplier_id=sup_surg,
            reference_type="OPENING_BATCH",
            notes="FIFO Layer 1 @ ₹100",
            conn=conn,
        )
        receive_batch_stock(
            product_id=p_gloves,
            warehouse_id=wh_del,
            batch_number="BATCH-GLV-B",
            quantity=70,
            unit_cost=120.00,
            receipt_date="2026-01-05",
            mfg_date="2025-12-15",
            expiry_date=d_future_450,
            supplier_id=sup_surg,
            reference_type="OPENING_BATCH",
            notes="FIFO Layer 2 @ ₹120",
            conn=conn,
        )
        issue_stock_fifo(
            warehouse_id=wh_del,
            product_id=p_gloves,
            issue_quantity=60,
            issue_date="2026-02-10",
            recipient_reference="Emergency Trauma Ward #ET-101",
            notes="FIFO demonstration issue (50 @ ₹100 + 10 @ ₹120 = ₹6,200)",
            conn=conn,
        )

        # 5. Seed Purchase Order #1 (Completed via 2 Partial Goods Receipts) for MED-PARA-500
        po1 = generate_purchase_order(
            supplier_id=sup_apex,
            target_warehouse_id=wh_del,
            items=[
                {
                    "product_id": p_para,
                    "ordered_quantity": 120,
                    "expected_unit_cost": 44.00,
                }
            ],
            order_date=d_past_45,
            status="Pending",
            notes="Q4 Paracetamol replenishment order",
            conn=conn,
        )
        po1_item_id = get_purchase_order_details(po1["po_id"], conn=conn)["items"][0]["id"]

        receive_goods(
            po_id=po1["po_id"],
            receipt_items=[
                {
                    "po_item_id": po1_item_id,
                    "received_quantity": 50,
                    "unit_cost": 44.00,
                    "batch_number": "BATCH-PARA-101",
                    "mfg_date=d_past_90": d_past_90,
                    "mfg_date": d_past_90,
                    "expiry_date": d_future_300,
                }
            ],
            warehouse_id=wh_del,
            receipt_date=d_past_30,
            notes="Partial Shipment 1 of 2",
            conn=conn,
        )
        receive_goods(
            po_id=po1["po_id"],
            receipt_items=[
                {
                    "po_item_id": po1_item_id,
                    "received_quantity": 70,
                    "unit_cost": 46.00,
                    "batch_number": "BATCH-PARA-102",
                    "mfg_date": d_past_45,
                    "expiry_date": d_future_450,
                }
            ],
            warehouse_id=wh_del,
            receipt_date=d_past_20,
            notes="Final Shipment 2 of 2 (Completes PO)",
            conn=conn,
        )

        # 6. Seed Purchase Order #2 (Partially Received — 40 of 90 received, 50 still pending) for MED-AZI-500
        po2 = generate_purchase_order(
            supplier_id=sup_bio,
            target_warehouse_id=wh_ggn,
            items=[
                {
                    "product_id": p_azi,
                    "ordered_quantity": 90,
                    "expected_unit_cost": 115.00,
                }
            ],
            order_date=d_past_20,
            status="Pending",
            notes="Gurugram antibiotic stock replenishment",
            conn=conn,
        )
        po2_item_id = get_purchase_order_details(po2["po_id"], conn=conn)["items"][0]["id"]
        receive_goods(
            po_id=po2["po_id"],
            receipt_items=[
                {
                    "po_item_id": po2_item_id,
                    "received_quantity": 40,
                    "unit_cost": 115.00,
                    "batch_number": "BATCH-AZI-201",
                    "mfg_date": d_past_45,
                    "expiry_date": d_future_300,
                }
            ],
            warehouse_id=wh_ggn,
            receipt_date=d_past_10,
            notes="First partial delivery (50 packs still pending)",
            conn=conn,
        )

        # 7. Seed Purchase Order #3 (Pending — 0 received yet) for SURG-MASK-N95 (which is below reorder level)
        generate_purchase_order(
            supplier_id=sup_surg,
            target_warehouse_id=wh_fbd,
            items=[
                {
                    "product_id": p_mask,
                    "ordered_quantity": 100,
                    "expected_unit_cost": 65.00,
                }
            ],
            order_date=d_past_5,
            status="Pending",
            is_auto_generated=True,
            notes="Awaiting supplier dispatch for N95 masks",
            conn=conn,
        )

        # 8. Seed Expired and Near-Expiry Batches + Reorder-Eligible Products
        # MED-INS-100: 1 Expired batch (15 vials) + 1 Near-Expiry batch (18 vials, expiring in 18 days)
        # Eligible stock = 18 <= reorder_level (25) -> Triggers Reorder Alert!
        receive_batch_stock(
            product_id=p_ins,
            warehouse_id=wh_ggn,
            batch_number="BATCH-INS-EXP01",
            quantity=15,
            unit_cost=430.00,
            receipt_date=d_past_260,
            mfg_date=d_past_260,
            expiry_date=d_past_10,  # EXPIRED 10 days ago
            supplier_id=sup_bio,
            reference_type="LEGACY_BATCH",
            notes="Expired cold-chain batch (quarantined from FIFO issue)",
            conn=conn,
        )
        ins_near = receive_batch_stock(
            product_id=p_ins,
            warehouse_id=wh_ggn,
            batch_number="BATCH-INS-NEAR02",
            quantity=23,
            unit_cost=445.00,
            receipt_date=d_past_90,
            mfg_date=d_past_90,
            expiry_date=d_near_18,  # NEAR EXPIRY (18 days remaining)
            supplier_id=sup_bio,
            reference_type="DIRECT_RECEIPT",
            notes="Approaching expiry within 30 days",
            conn=conn,
        )

        # Process a Supplier Return of 5 vials from BATCH-INS-NEAR02 (leaves 18 vials <= reorder level 25)
        process_supplier_return(
            supplier_id=sup_bio,
            warehouse_id=wh_ggn,
            batch_id=ins_near["batch_id"],
            return_quantity=5,
            reason="5 vials returned due to cold-chain temperature logger excursion",
            return_date=d_past_5,
            conn=conn,
        )

        # MED-AMOX-250: 15 boxes at WH-DEL-01 (<= reorder level 35, no open PO -> ready for Auto-PO)
        receive_batch_stock(
            product_id=p_amox,
            warehouse_id=wh_del,
            batch_number="BATCH-AMOX-301",
            quantity=15,
            unit_cost=92.00,
            receipt_date=d_past_30,
            mfg_date=d_past_90,
            expiry_date=d_future_300,
            supplier_id=sup_apex,
            notes="Low stock batch (below reorder level 35)",
            conn=conn,
        )

        # CHEM-ETH-500: 10 bottles at WH-FBD-03 (<= reorder level 25, no open PO -> ready for Auto-PO)
        receive_batch_stock(
            product_id=p_eth,
            warehouse_id=wh_fbd,
            batch_number="BATCH-ETH-401",
            quantity=10,
            unit_cost=175.00,
            receipt_date=d_past_15,
            mfg_date=d_past_45,
            expiry_date=d_future_450,
            supplier_id=sup_chem,
            notes="Low stock reagent (below reorder level 25)",
            conn=conn,
        )

        #SURG-MASK-N95: 20 packs at WH-FBD-03 (<= reorder level 50, covered by PO #3)
        receive_batch_stock(
            product_id=p_mask,
            warehouse_id=wh_fbd,
            batch_number="BATCH-N95-501",
            quantity=20,
            unit_cost=65.00,
            receipt_date=d_past_30,
            mfg_date=d_past_90,
            expiry_date=d_future_450,
            supplier_id=sup_surg,
            notes="Current PPE buffer stock",
            conn=conn,
        )

        # MED-ORS-20: 250 sachets at WH-DEL-01 (healthy stock, used for Warehouse Transfer demo)
        ors_batch = receive_batch_stock(
            product_id=p_ors,
            warehouse_id=wh_del,
            batch_number="BATCH-ORS-601",
            quantity=250,
            unit_cost=18.00,
            receipt_date=d_past_30,
            mfg_date=d_past_90,
            expiry_date=d_future_300,
            supplier_id=sup_chem,
            notes="Bulk ORS replenishment batch",
            conn=conn,
        )

        # 9. Seed 2 Inter-Warehouse Stock Transfers:
        # Transfer #1 (Completed/Received): 80 sachets of BATCH-ORS-601 from WH-DEL-01 to WH-FBD-03
        trf1 = create_transfer(
            source_warehouse_id=wh_del,
            dest_warehouse_id=wh_fbd,
            batch_id=ors_batch["batch_id"],
            quantity=80,
            transfer_date=d_past_15,
            notes="Completed regional transfer to Faridabad depot",
            auto_dispatch=True,
            conn=conn,
        )
        receive_transfer(trf1["transfer_id"], conn=conn)

        # Transfer #2 (Dispatched / In-Transit): 30 sachets of BATCH-ORS-601 from WH-DEL-01 to WH-GGN-02
        create_transfer(
            source_warehouse_id=wh_del,
            dest_warehouse_id=wh_ggn,
            batch_id=ors_batch["batch_id"],
            quantity=30,
            transfer_date=d_past_5,
            notes="In-transit shipment awaiting Gurugram receipt confirmation",
            auto_dispatch=True,
            conn=conn,
        )

        return {
            "seeded": True,
            "message": (
                "Loaded demonstration data: 4 suppliers, 3 warehouses, 8 products, "
                "11 batches (valid, near-expiry, expired), 3 POs (completed, partial, pending), "
                "2 transfers (completed & in-transit), 1 FIFO issue (₹6,200), and 1 supplier return."
            ),
        }
    finally:
        conn.close()


if __name__ == "__main__":
    result = seed_demo_data()
    print(result["message"])
