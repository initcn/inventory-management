# Software Requirements Specification (SRS)
## Inventory & Multi-Warehouse Management System

### 1. Project Overview & Scope
The **Inventory & Multi-Warehouse Management System** is an enterprise-grade, highly reliable web application built using **Python 3, Flask, SQLite (`sqlite3`), HTML5/CSS3/Bootstrap 5, Jinja2, and `unittest`**. It models and implements batch-wise stock management across multiple warehouses, expiry monitoring, automatic purchase order generation with duplicate prevention, partial and multi-shipment goods receipts, two-stage inter-warehouse stock transfers, strict First-In, First-Out (FIFO) stock valuation, supplier returns, and an immutable stock transaction history ledger.

---

### 2. Actors & Use Case Model (StarUML Use Case Specification)

#### 2.1 Identified Actors
| Actor Name | Stereotype / Type | Role Description |
| :--- | :--- | :--- |
| **Inventory Manager** | Primary Actor | Manages product catalog and warehouse locations, monitors batch expiry and stock KPIs, executes FIFO stock issues, and audits the stock transaction ledger. |
| **Warehouse Operator** | Primary Actor | Records physical goods receipts (full or partial GRNs), dispatches and receives inter-warehouse stock transfers, and processes supplier returns. |
| **Purchase Manager** | Primary Actor | Manages supplier records, runs reorder-level detection, reviews/confirms/cancels purchase orders, and invokes external supplier catalog verification. |
| **Supplier System (Simulated)** | Secondary External Actor | External vendor system represented by `integrations/supplier_adapter.py` that responds to catalog price, MOQ, lead-time, and availability checks. |

#### 2.2 Use Case Inventory & Actor Mapping
| Use Case ID | Use Case Name | Primary Actor(s) | Included / Extended Use Cases & Preconditions |
| :--- | :--- | :--- | :--- |
| **UC-01** | Manage Products (Add/Edit/View/Safe Delete) | Inventory Manager | Validates unique SKU, `reorder_level >= 0`, and zero historical dependencies before deletion. |
| **UC-02** | Manage Warehouses & Inspect Warehouse Stock | Inventory Manager | Enforces unique `warehouse_code` and displays per-warehouse batch holdings. |
| **UC-03** | Manage Suppliers & View Associations | Purchase Manager | Links suppliers to catalog products and purchase orders. |
| **UC-04** | Register Batch Stock & Monitor Expiry | Inventory Manager, Warehouse Operator | `<<include>>` Record Stock Transaction (`GOODS_RECEIPT`). Flags `EXPIRED` and `NEAR_EXPIRY` batches. |
| **UC-05** | Detect Reorder Levels & Auto-Generate POs | Purchase Manager | Evaluates non-expired stock in active warehouses; skips products already covered by an open PO. |
| **UC-06** | Review, Confirm, or Cancel Purchase Order | Purchase Manager | Transitions PO from `Draft` to `Pending` or `Cancelled` (if `received_quantity == 0`). |
| **UC-07** | Record Partial or Full Goods Receipt (GRN) | Warehouse Operator | `<<include>>` Create/Update Batch & Warehouse Holding; `<<include>>` Record Stock Transaction (`GOODS_RECEIPT`). |
| **UC-08** | Dispatch Inter-Warehouse Stock Transfer | Warehouse Operator | `<<include>>` Record Stock Transaction (`TRANSFER_DISPATCH`). Deducts source stock immediately. |
| **UC-09** | Receive Inter-Warehouse Stock Transfer | Warehouse Operator | `<<include>>` Record Stock Transaction (`TRANSFER_RECEIPT`). Credits destination under same `batch_id`. |
| **UC-10** | Issue Stock & Compute FIFO Valuation | Inventory Manager | `<<include>>` Record Stock Transaction (`STOCK_ISSUE`). Consumes oldest non-expired batches by `receipt_date ASC, batch_id ASC`. |
| **UC-11** | Process Supplier Return | Warehouse Operator | `<<include>>` Record Stock Transaction (`SUPPLIER_RETURN`). Validates `return_qty <= remaining_quantity`. |
| **UC-12** | Verify Supplier Catalog (External Integration) | Purchase Manager, Supplier System | Communicates with `SupplierIntegrationAdapter` (`SUCCESS`, `FAILURE`, `TIMEOUT`, `UNAVAILABLE`). |
| **UC-13** | Audit Stock Transaction History | Inventory Manager | Filters immutable ledger by product, warehouse, and transaction type. |

#### 2.3 StarUML Step-by-Step Instructions for Use Case Diagram
1. Open **StarUML** and select **Model $\rightarrow$ Add Diagram $\rightarrow$ Use Case Diagram** (name it `01_UseCaseDiagram`).
2. From the **Toolbox (Use Case)**, drag **1 System Boundary (`Subject`)** onto the canvas and title it `Inventory & Multi-Warehouse Management System`.
3. Drag **3 Actors** to the **left** of the boundary: `Inventory Manager`, `Warehouse Operator`, and `Purchase Manager`.
4. Drag **1 Actor** to the **right** of the boundary: `Supplier System <<external>>`.
5. Drag **13 Use Cases** (`UC-01` through `UC-13`) inside the system boundary plus a shared internal use case `UC-14: Record Stock Transaction`.
6. Connect actors to their respective use cases with **Undirected Associations** (`Association`) as listed in Table 2.2.
7. Draw **`<<include>>` Dependencies** from `UC-04`, `UC-07`, `UC-08`, `UC-09`, `UC-10`, and `UC-11` pointing to `UC-14: Record Stock Transaction`.
8. Draw an **Association** from `UC-12: Verify Supplier Catalog` to the right-side actor `Supplier System <<external>>`.

---

### 3. Functional Requirements Traceability Matrix

| Req ID | Module | Requirement Summary | Implemented Service Function | Route Blueprint |
| :--- | :--- | :--- | :--- | :--- |
| **FR-01** | Module 1: Products | Add, view, edit, and safely delete products; unique SKU; non-negative reorder level; supplier link. | `product_service.create_product`, `update_product`, `delete_product`, `list_products` | `routes/products.py` |
| **FR-02** | Module 2: Warehouses | Add, view, edit warehouses; active/inactive toggle; inspect warehouse stock; block same-warehouse transfer. | `warehouse_service.create_warehouse`, `update_warehouse`, `get_warehouse_stock` | `routes/warehouses.py` |
| **FR-03** | Module 3: Suppliers | Add, view, edit suppliers; associate with products and POs; inspect associations. | `supplier_service.create_supplier`, `update_supplier`, `get_supplier_associations` | `routes/suppliers.py` |
| **FR-04** | Module 4: Batch Inventory | Track batch identity (`batch_number`, `mfg_date`, `expiry_date`, `unit_cost`, `receipt_date`) separately from warehouse holdings; detect expired/near-expiry batches; prevent negative stock. | `inventory_service.receive_batch_stock`, `upsert_inventory_holding`, `adjust_batch_stock`, `get_expiry_alerts` | `routes/inventory.py` |
| **FR-05** | Module 5: Reorder & POs | Monitor reorder levels on non-expired stock; auto-generate POs without duplicates; support partial and multiple goods receipts (`Draft`, `Pending`, `Partially Received`, `Completed`, `Cancelled`). | `reorder_service.check_reorder_levels`, `auto_generate_purchase_orders`, `generate_purchase_order`, `receive_goods` | `routes/purchases.py` |
| **FR-06** | Module 6: Stock Transfers | Two-step transfer workflow (`Draft` $\rightarrow$ `Dispatched` $\rightarrow$ `Partially Received` / `Received` / `Cancelled`); preserve batch identity, cost, and expiry date. | `transfer_service.create_transfer`, `dispatch_transfer`, `receive_transfer`, `cancel_transfer` | `routes/transfers.py` |
| **FR-07** | Module 7: FIFO Valuation | Consume oldest non-expired batches first (`receipt_date ASC, id ASC`); span multiple batches; compute exact FIFO cost in ₹. | `fifo_service.get_fifo_eligible_batches`, `issue_stock_fifo`, `get_fifo_valuation_overview` | `routes/inventory.py` (`/valuation`) |
| **FR-08** | Module 8: Supplier Returns | Validate `return_quantity <= remaining_quantity`; deduct stock; preserve historical records; log transaction. | `return_service.process_supplier_return`, `list_supplier_returns` | `routes/returns.py` |
| **FR-09** | Module 9: Transactions | Maintain immutable audit history for receipts, issues, transfer dispatches/receipts, returns, and adjustments. | `inventory_service.record_stock_transaction`, `list_stock_transactions` | `routes/inventory.py` (`/transactions`) |
| **FR-10** | Section 8: Integration | Simulated external supplier adapter demonstrating success, failure, and timeout/unavailable scenarios. | `supplier_adapter.SupplierIntegrationAdapter.verify_supplier_product` | `routes/suppliers.py` (`/suppliers/verify-integration`) |

---

### 4. Non-Functional Requirements
1. **Transactional Atomicity (ACID)**: All multi-table writes execute inside `database.transaction()` with `BEGIN ... COMMIT` and automatic `ROLLBACK` on exception.
2. **Referential Integrity**: `PRAGMA foreign_keys = ON` is enforced on every SQLite connection.
3. **SQL Injection Prevention**: 100% of SQL queries use parameterized `?` placeholders via Python's built-in `sqlite3` library.
4. **Minimal Stack & Local Portability**: Runs on standard Windows Python 3.10+ with `Flask` as the sole external pip package and Bootstrap 5 via CDN.
