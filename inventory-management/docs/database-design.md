# Relational Database Design & Schema Documentation
## Inventory & Multi-Warehouse Management System

### 1. Normalization & Core Design Principles
The SQLite database (`schema.sql`) is normalized to **Third Normal Form (3NF)** across **16 relational tables** with `PRAGMA foreign_keys = ON` enforced on every connection in `database.py`.

#### Representing Multi-Warehouse Batch Inventory Without Redundancy
A central requirement of the project is that a single batch (received from a supplier with a specific `batch_number`, `mfg_date`, `expiry_date`, `receipt_date`, and `unit_cost`) can have its units distributed across multiple warehouses via inter-warehouse transfers without duplicating or corrupting its original batch identity or cost:
1. **`batches` Table (Intrinsic Batch Identity)**: Stores one row per `(product_id, batch_number)` pair (`UNIQUE (product_id, batch_number)`). Holds `mfg_date`, `expiry_date`, `unit_cost`, `receipt_date`, and `initial_quantity`.
2. **`inventory` Table (Warehouse-Specific Holdings)**: Stores one row per `(warehouse_id, batch_id)` pair (`UNIQUE (warehouse_id, batch_id)`) with `CHECK (quantity >= 0)`.
3. **Result**: When 80 units of `BATCH-ORS-601` (`batch_id = 11`, cost `₹18.00`, expiry `2027-09-12`) are transferred from `WH-DEL-01` to `WH-FBD-03`, `inventory` simply decrements `(WH-DEL-01, batch_id=11)` by 80 on dispatch and increments `(WH-FBD-03, batch_id=11)` by 80 on receipt. Both warehouses reference the exact same `batches.id = 11` record.

#### Justification for Including `stock_issues` and `stock_issue_items`
In addition to the 14 baseline tables listed in Section 5 of the project specification, the schema includes `stock_issues` (Table 12) and `stock_issue_items` (Table 13). Because a single FIFO stock issue (e.g., issuing 60 boxes of `SURG-GLV-M`) can consume quantities across multiple batches with different unit costs (50 units from `BATCH-GLV-A` @ ₹100 + 10 units from `BATCH-GLV-B` @ ₹120 = ₹6,200), persisting the issue header and per-batch consumption lines provides an auditable, normalized record of every FIFO valuation calculation alongside `stock_transactions`.

---

### 2. Table-by-Table Specification & Relationships

| # | Table | Primary Key | Foreign Keys | UNIQUE & CHECK Constraints | Purpose |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `suppliers` | `id` | None | `UNIQUE(supplier_code)`, `CHECK(is_active IN (0,1))` | Stores vendor contact details and status. |
| 2 | `products` | `id` | `preferred_supplier_id -> suppliers(id)` | `UNIQUE(sku)`, `CHECK(length(trim(name)) > 0)`, `CHECK(reorder_level >= 0)` | Master product catalog and reorder thresholds. |
| 3 | `warehouses` | `id` | None | `UNIQUE(warehouse_code)`, `CHECK(is_active IN (0,1))` | Physical warehouse locations. |
| 4 | `batches` | `id` | `product_id -> products(id)`, `supplier_id -> suppliers(id)` | `UNIQUE(product_id, batch_number)`, `CHECK(unit_cost >= 0)`, `CHECK(initial_quantity > 0)`, `CHECK(expiry_date >= mfg_date)` | Intrinsic batch metadata for FIFO ordering and expiry tracking. |
| 5 | `inventory` | `id` | `warehouse_id -> warehouses(id)`, `batch_id -> batches(id)`, `product_id -> products(id)` | `UNIQUE(warehouse_id, batch_id)`, `CHECK(quantity >= 0)` | Current remaining stock of each batch at each warehouse. |
| 6 | `purchase_orders` | `id` | `supplier_id -> suppliers(id)`, `target_warehouse_id -> warehouses(id)` | `UNIQUE(po_number)`, `CHECK(status IN ('Draft','Pending','Partially Received','Completed','Cancelled'))` | Purchase order headers (manual or auto-generated). |
| 7 | `purchase_order_items` | `id` | `po_id -> purchase_orders(id)`, `product_id -> products(id)` | `UNIQUE(po_id, product_id)`, `CHECK(ordered_quantity > 0)`, `CHECK(received_quantity >= 0 AND received_quantity <= ordered_quantity)` | Line items tracking ordered vs. received quantities. |
| 8 | `goods_receipts` | `id` | `po_id -> purchase_orders(id)`, `warehouse_id -> warehouses(id)` | `UNIQUE(grn_number)` | Header for each partial or full delivery against a PO. |
| 9 | `goods_receipt_items` | `id` | `receipt_id -> goods_receipts(id)`, `po_item_id -> purchase_order_items(id)`, `product_id -> products(id)`, `batch_id -> batches(id)` | `CHECK(received_quantity > 0)`, `CHECK(unit_cost >= 0)` | Individual batch lines received in a GRN. |
| 10 | `transfers` | `id` | `source_warehouse_id -> warehouses(id)`, `dest_warehouse_id -> warehouses(id)` | `UNIQUE(transfer_number)`, `CHECK(source_warehouse_id != dest_warehouse_id)`, `CHECK(status IN ('Draft','Dispatched','Partially Received','Received','Cancelled'))` | Inter-warehouse stock transfer headers. |
| 11 | `transfer_items` | `id` | `transfer_id -> transfers(id)`, `product_id -> products(id)`, `batch_id -> batches(id)` | `UNIQUE(transfer_id, batch_id)`, `CHECK(quantity > 0)`, `CHECK(received_quantity <= quantity)` | Batch-specific quantities dispatched and received. |
| 12 | `stock_issues` | `id` | `warehouse_id -> warehouses(id)` | `UNIQUE(issue_number)`, `CHECK(total_quantity > 0)`, `CHECK(total_cost >= 0)` | FIFO stock issuance headers with total valuation in ₹. |
| 13 | `stock_issue_items` | `id` | `issue_id -> stock_issues(id)`, `product_id -> products(id)`, `batch_id -> batches(id)` | `CHECK(quantity > 0)`, `CHECK(unit_cost >= 0)`, `CHECK(line_cost >= 0)` | Exact per-batch FIFO consumption breakdown. |
| 14 | `supplier_returns` | `id` | `supplier_id -> suppliers(id)`, `warehouse_id -> warehouses(id)` | `UNIQUE(return_number)`, `CHECK(length(trim(reason)) > 0)` | Vendor return headers. |
| 15 | `supplier_return_items` | `id` | `return_id -> supplier_returns(id)`, `product_id -> products(id)`, `batch_id -> batches(id)` | `CHECK(quantity > 0)`, `CHECK(unit_cost >= 0)` | Batch-level return quantities and credit values. |
| 16 | `stock_transactions` | `id` | `product_id -> products(id)`, `batch_id -> batches(id)`, `warehouse_id -> warehouses(id)` | `CHECK(quantity != 0)`, `CHECK(transaction_type IN ('GOODS_RECEIPT','STOCK_ISSUE','TRANSFER_DISPATCH','TRANSFER_RECEIPT','TRANSFER_CANCEL','SUPPLIER_RETURN','ADJUSTMENT'))` | Immutable audit ledger for all inventory movements. |

---

### 3. Database Indexes
Eight indexes in `schema.sql` optimize the primary lookup and sorting paths:
- `idx_products_sku`: Fast SKU uniqueness and catalog lookups.
- `idx_batches_product_receipt`: Optimizes FIFO batch sorting (`WHERE product_id = ? ORDER BY date(receipt_date) ASC, id ASC`).
- `idx_batches_expiry`: Optimizes expired and 30-day near-expiry batch scans.
- `idx_inventory_wh_prod` & `idx_inventory_batch`: Fast warehouse-specific stock aggregation.
- `idx_po_status` & `idx_transfers_status`: Fast filtering of active/pending purchase orders and in-transit transfers.
- `idx_transactions_lookup`: Optimizes audit ledger filtering on `/transactions`.
