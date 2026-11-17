# End-to-End Scenario Walk-Through & State Transitions
## Inventory & Multi-Warehouse Management System

This document walks through five realistic operational scenarios using concrete Indian currency (`₹`) data and shows the exact database state changes across `batches`, `inventory`, `purchase_orders`, `purchase_order_items`, `goods_receipts`, `transfers`, `stock_issues`, `supplier_returns`, and `stock_transactions`.

---

### Scenario 1: Stock Reaching Reorder Level & Duplicate-Safe Automatic PO Generation

#### Initial State
- **Product**: `MED-AMOX-250` (Amoxicillin 250mg Capsules), `reorder_level = 35 Boxes`, `preferred_supplier_id = 1` (`SUP-APEX-01`).
- **Warehouse**: `WH-DEL-01` (Central Delhi Hub, `is_active = 1`).
- **Current Holding**: `BATCH-AMOX-301` has `remaining_quantity = 15 Boxes` (Expiry: `2027-09-12`, Valid).
- **Open Purchase Orders**: None (`0` active POs for `MED-AMOX-250`).

#### Execution Steps & State Changes
1. **Step 1.1 — Reorder Detection (`check_reorder_levels()`)**:
   - System sums non-expired stock in active warehouses: `available_stock = 15`.
   - Compares `15 <= 35 (reorder_level)` $\rightarrow$ **Reorder Required**.
   - Computes recommended order quantity: `max((35 * 2) - 15, 35, 10) = 55 Boxes`.
2. **Step 1.2 — Auto-Generate PO (`auto_generate_purchase_orders(target_warehouse_id=1)`)**:
   - Inserts `purchase_orders` row: `po_number = 'PO-2026-0004'`, `supplier_id = 1`, `target_warehouse_id = 1`, `status = 'Draft'`, `is_auto_generated = 1`.
   - Inserts `purchase_order_items` row: `product_id = 3`, `ordered_quantity = 55`, `received_quantity = 0`, `expected_unit_cost = ₹92.00`.
3. **Step 1.3 — Re-running Reorder Check (Duplicate Prevention Verification)**:
   - `check_reorder_levels()` detects `open_po_pending_qty = 55` on `PO-2026-0004`.
   - `auto_generate_purchase_orders()` skips `MED-AMOX-250` (`created_pos = []`, `skipped_open_po = ['MED-AMOX-250 (PO-2026-0004)']`).
4. **Step 1.4 — Purchase Manager Confirmation**:
   - `update_purchase_order_status(po_id, 'Pending')` transitions `PO-2026-0004` from `Draft` $\rightarrow$ `Pending`.

---

### Scenario 2: Partial Goods Receipt & Multi-Shipment PO Completion

#### Initial State
- **Purchase Order**: `PO-2026-0001` for `MED-PARA-500` (Paracetamol 500mg), `ordered_quantity = 120 Packs`, `received_quantity = 0`, `status = 'Pending'`, Target Warehouse: `WH-DEL-01`.

#### Execution Steps & State Changes
1. **Step 2.1 — First Partial Delivery (50 Packs @ ₹44.00)**:
   - Warehouse Operator posts `receive_goods(po_id=1, received_quantity=50, batch_number='BATCH-PARA-101', unit_cost=44.00)`.
   - **State Changes**:
     - `batches`: Created `BATCH-PARA-101` (`initial_quantity = 50`, `unit_cost = ₹44.00`).
     - `inventory`: Upserted `(WH-DEL-01, BATCH-PARA-101)` $\rightarrow$ `quantity = 50`.
     - `goods_receipts` & `goods_receipt_items`: Created `GRN-2026-0001` for `50 Packs`.
     - `purchase_order_items`: `received_quantity` updated `0` $\rightarrow$ `50` (`pending_quantity = 70`).
     - `purchase_orders`: `status` transitions `Pending` $\rightarrow$ **`Partially Received`**.
     - `stock_transactions`: Logged `GOODS_RECEIPT` (`+50`, `ref = PO-2026-0001/GRN-2026-0001`).
2. **Step 2.2 — Second Delivery Completing the Order (70 Packs @ ₹46.00)**:
   - Warehouse Operator posts `receive_goods(po_id=1, received_quantity=70, batch_number='BATCH-PARA-102', unit_cost=46.00)`.
   - **State Changes**:
     - `batches`: Created `BATCH-PARA-102` (`initial_quantity = 70`, `unit_cost = ₹46.00`).
     - `inventory`: Upserted `(WH-DEL-01, BATCH-PARA-102)` $\rightarrow$ `quantity = 70`.
     - `goods_receipts` & `goods_receipt_items`: Created `GRN-2026-0002` for `70 Packs`.
     - `purchase_order_items`: `received_quantity` updated `50` $\rightarrow$ `120` (`pending_quantity = 0`).
     - `purchase_orders`: `status` transitions `Partially Received` $\rightarrow$ **`Completed`**.
     - `stock_transactions`: Logged `GOODS_RECEIPT` (`+70`, `ref = PO-2026-0001/GRN-2026-0002`).

---

### Scenario 3: Inter-Warehouse Stock Transfer (Preserving Batch Identity)

#### Initial State
- **Product**: `MED-ORS-20` (ORS Sachet).
- **Batch**: `BATCH-ORS-601` (`batch_id = 11`, `unit_cost = ₹18.00`, `expiry_date = 2027-09-12`).
- **Source Warehouse (`WH-DEL-01`)**: `inventory.quantity = 250 Sachets`.
- **Destination Warehouse (`WH-FBD-03`)**: `0 Sachets` of `BATCH-ORS-601`.

#### Execution Steps & State Changes
1. **Step 3.1 — Transfer Creation & Dispatch (80 Sachets)**:
   - Operator executes `create_transfer(source=WH-DEL-01, dest=WH-FBD-03, batch_id=11, quantity=80, auto_dispatch=True)`.
   - **State Changes**:
     - `transfers`: Created `TRF-2026-0001` with `status = 'Dispatched'`.
     - `transfer_items`: `quantity = 80`, `received_quantity = 0` (`in_transit = 80`).
     - `inventory` (`WH-DEL-01`, `batch_id=11`): `250` $\rightarrow$ **`170 Sachets`** (deducted immediately).
     - `inventory` (`WH-FBD-03`, `batch_id=11`): Still `0` (not added before receipt).
     - `stock_transactions`: Logged `TRANSFER_DISPATCH` (`-80` at `WH-DEL-01`).
2. **Step 3.2 — Transfer Receipt at Destination (`receive_transfer()`)**:
   - Operator confirms receipt at `WH-FBD-03`.
   - **State Changes**:
     - `inventory` (`WH-FBD-03`, `batch_id=11`): Upserted **`+80 Sachets`** referencing the **exact same `batch_id = 11`** (`BATCH-ORS-601`, `₹18.00`, expiry `2027-09-12`).
     - `transfer_items`: `received_quantity` updated `0` $\rightarrow$ `80`.
     - `transfers`: `status` transitions `Dispatched` $\rightarrow$ **`Received`**.
     - `stock_transactions`: Logged `TRANSFER_RECEIPT` (`+80` at `WH-FBD-03`).

---

### Scenario 4: Multi-Batch FIFO Stock Issue & Valuation

#### Initial State
- **Product**: `SURG-GLV-M` (Sterile Nitrile Gloves) at `WH-DEL-01`:
  - **Batch A (`BATCH-GLV-A`)**: Received `2026-01-01`, Remaining Qty = `50 Boxes`, Unit Cost = `₹100.00`.
  - **Batch B (`BATCH-GLV-B`)**: Received `2026-01-05`, Remaining Qty = `70 Boxes`, Unit Cost = `₹120.00`.

#### Execution Steps & State Changes
1. **Step 4.1 — Request FIFO Issue of 60 Boxes (`issue_stock_fifo(warehouse_id=WH-DEL-01, product_id=1, issue_quantity=60)`)**:
   - System queries non-expired holdings ordered by `date(receipt_date) ASC, id ASC`: `[BATCH-GLV-A (50), BATCH-GLV-B (70)]`.
   - **Layer 1 Consumption (`BATCH-GLV-A`)**: Consumes all `50 Boxes` @ `₹100.00` = **`₹5,000.00`**. `inventory` for `BATCH-GLV-A` becomes `0`.
   - **Layer 2 Consumption (`BATCH-GLV-B`)**: Consumes remaining `10 Boxes` @ `₹120.00` = **`₹1,200.00`**. `inventory` for `BATCH-GLV-B` becomes `60`.
   - **Total FIFO Issue Valuation**: `₹5,000.00 + ₹1,200.00` = **`₹6,200.00`**.
   - **Database Records Created**:
     - `stock_issues`: `ISS-2026-0001` (`total_quantity = 60`, `total_cost = ₹6,200.00`).
     - `stock_issue_items`: 2 rows (`50 @ ₹100 = ₹5,000` and `10 @ ₹120 = ₹1,200`).
     - `stock_transactions`: 2 `STOCK_ISSUE` entries (`-50` on `BATCH-GLV-A`, `-10` on `BATCH-GLV-B`).

---

### Scenario 5: Supplier Return & Expiry Quarantine

#### Initial State
- **Product**: `MED-INS-100` (Human Insulin Vial) at `WH-GGN-02` supplied by `SUP-BIO-02`:
  - `BATCH-INS-EXP01`: `15 Vials` (Expired 10 days ago — quarantined from normal FIFO issue).
  - `BATCH-INS-NEAR02`: `23 Vials` @ `₹445.00` (Approaching expiry in 18 days).

#### Execution Steps & State Changes
1. **Step 5.1 — Process Return of 5 Vials (`process_supplier_return()`)**:
   - Operator returns `5 Vials` from `BATCH-INS-NEAR02` to `SUP-BIO-02` with reason `"5 vials returned due to cold-chain temperature logger excursion"`.
   - System validates `5 <= 23 (remaining_quantity)`.
   - **State Changes**:
     - `supplier_returns` & `supplier_return_items`: Created `RET-2026-0001` (`quantity = 5`, `unit_cost = ₹445.00`, `return_value = ₹2,225.00`).
     - `inventory` (`WH-GGN-02`, `BATCH-INS-NEAR02`): `23` $\rightarrow$ **`18 Vials`**.
     - `stock_transactions`: Logged `SUPPLIER_RETURN` (`-5`, `unit_cost = ₹445.00`, `ref = RET-2026-0001`).
     - Historical `batches` and `purchase_orders` records remain intact for audit traceability.
