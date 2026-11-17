# System Architecture & Component Design
## Inventory & Multi-Warehouse Management System

### 1. Layered Software Architecture
The application is structured into four strictly separated layers plus an isolated external integration adapter:

1. **Presentation Layer (`templates/*.html`, `static/css/style.css`, `static/js/app.js`)**:
   - Server-rendered Jinja2 templates styled with Bootstrap 5.
   - Displays dashboard KPIs, status badges, FIFO valuation tables, and flash notifications.
2. **Controller / Route Layer (`app.py`, `routes/*.py`)**:
   - Modular Flask Blueprints (`products_bp`, `warehouses_bp`, `suppliers_bp`, `inventory_bp`, `purchases_bp`, `transfers_bp`, `returns_bp`).
   - Parses HTTP form inputs, invokes service functions, catches `ValidationError`, and flashes user-friendly messages. Contains zero SQL queries.
3. **Business Service Layer (`services/*.py`)**:
   - Stateless domain services (`product_service`, `warehouse_service`, `supplier_service`, `inventory_service`, `reorder_service`, `transfer_service`, `fifo_service`, `return_service`).
   - Enforces all business invariants (SKU uniqueness, expiry validation, duplicate-PO prevention, in-transit transfer conservation, strict FIFO ordering by `receipt_date ASC, id ASC`, negative stock prevention) inside atomic transactions.
4. **Data Access & Integration Layer (`database.py`, `schema.sql`, `integrations/supplier_adapter.py`)**:
   - `database.py` manages SQLite connections (`sqlite3.Row`), enforces `PRAGMA foreign_keys = ON`, and provides the `transaction()` context manager.
   - `integrations/supplier_adapter.py` encapsulates the **Simulated External Supplier System** behind `SupplierIntegrationAdapter`.

---

### 2. Component Diagram (StarUML Specification)

```text
+-----------------------------------------------------------------------+
|                       <<subsystem>> Presentation                      |
|  [Jinja2 Templates (11 Views)]       [Bootstrap 5 CSS & Vanilla JS]   |
+-----------------------------------+-----------------------------------+
                                    | HTTP GET / POST
                                    v
+-----------------------------------------------------------------------+
|                    <<subsystem>> Flask Route Blueprints               |
|  [products_bp] [warehouses_bp] [suppliers_bp] [inventory_bp]          |
|  [purchases_bp] [transfers_bp] [returns_bp]                           |
+-----------------------------------+-----------------------------------+
                                    | Calls Service API
                                    v
+-----------------------------------------------------------------------+
|                     <<subsystem>> Business Services                   |
|  [product_service]   [warehouse_service]   [supplier_service]         |
|  [inventory_service] [reorder_service]     [transfer_service]         |
|  [fifo_service]      [return_service]                                 |
+-------------------+-----------------------------------+---------------+
                    | Parameterized SQL / ACID          | Adapter Call
                    v                                   v
+---------------------------------------+   +---------------------------+
|     <<component>> Database Layer      |   | <<component>> Integration |
|   [database.py (Connection & Tx)]     |   |   [supplier_adapter.py]   |
+-------------------+-------------------+   +-------------+-------------+
                    | sqlite3 DB-API                      | Simulated RPC
                    v                                     v
+---------------------------------------+   +---------------------------+
|      <<database>> SQLite Storage      |   | <<external>> Simulated    |
|     [inventory.db (16 Tables)]        |   |    Vendor Catalog API     |
+---------------------------------------+   +---------------------------+
```

#### StarUML Step-by-Step Instructions for Component Diagram (`06_ComponentDiagram`):
1. In StarUML, select **Model $\rightarrow$ Add Diagram $\rightarrow$ Component Diagram**.
2. Create **7 Components**:
   - `UI Templates & Static Assets` (`templates/*.html`, `static/*`)
   - `Flask Application & Route Blueprints` (`app.py`, `routes/*.py`)
   - `Business Services Layer` (`services/*.py`)
   - `Database Access Layer` (`database.py`)
   - `SQLite Database` (`inventory.db` / `schema.sql`)
   - `Supplier Integration Adapter` (`integrations/supplier_adapter.py`)
   - `Simulated External Supplier System` (`SIMULATED_VENDOR_CATALOG`)
3. Connect `UI Templates` $\rightarrow$ `Flask Route Blueprints` $\rightarrow$ `Business Services Layer` using **Dependency** arrows.
4. Connect `Business Services Layer` $\rightarrow$ `Database Access Layer` $\rightarrow$ `SQLite Database`.
5. Connect `Business Services Layer` (`supplier_service`) $\rightarrow$ `Supplier Integration Adapter` $\rightarrow$ `Simulated External Supplier System`.

---

### 3. Initial vs. Refined Class Diagrams (StarUML Specifications)

#### 3.1 Initial Conceptual Class Model (`02_InitialClassDiagram`)
Before refinement, the initial conceptual analysis model contained **14 loosely structured classes** with overlapping responsibilities and redundant alert entities:
- `Product` (`sku`, `name`, `category`, `unit`, `reorderLevel`)
- `Warehouse` (`warehouseCode`, `name`, `location`, `isActive`)
- `Supplier` (`supplierCode`, `name`, `contactPerson`, `email`, `phone`, `address`)
- `BatchInventory` *(Monolithic class combining `batchNumber`, `mfgDate`, `expiryDate`, `unitCost`, `receiptDate`, `warehouseId`, and `remainingQty` in one class)*
- `LowStockAlert` *(Redundant persistent class storing `productId`, `triggeredAt`, `currentQty`)*
- `ExpiredBatchAlert` *(Redundant persistent class storing `batchId`, `expiredOn`, `alertStatus`)*
- `PurchaseOrder` (`poNumber`, `orderDate`, `status`, `orderedQty`, `receivedQty`)
- `GoodsReceipt` (`grnNumber`, `receiptDate`, `receivedQty`, `batchNumber`, `unitCost`)
- `InternalDispatchNote` *(Separate class for outbound warehouse transfer dispatch)*
- `InternalReceiptNote` *(Separate class for inbound warehouse transfer receipt)*
- `FifoStockIssue` (`issueNumber`, `issueDate`, `issuedQty`, `calculatedCost`)
- `SupplierReturn` (`returnNumber`, `returnDate`, `returnedQty`, `reason`)
- `StockLogEntry` (`timestamp`, `actionDescription`, `qtyChange`)
- `ExternalSupplierClient` (`verifyCatalog()`)

#### 3.2 Refined Class Model (`03_RefinedClassDiagram`)
Through systematic OOAD refinement (detailed in `docs/refinement-log.md`), the model was refined into a cohesive, homogeneous **16-entity domain model** + **1 External Adapter**:

| Class Name | Attributes (with Types) | Key Operations (Mapped to Service Layer) | Multiplicities & Associations |
| :--- | :--- | :--- | :--- |
| **`Supplier`** | `id: int`, `supplier_code: str`, `name: str`, `contact_person: str`, `email: str`, `phone: str`, `address: str`, `is_active: bool` | `+create_supplier(): int`<br>`+update_supplier(): void`<br>`+get_supplier_associations(): dict` | `1` supplies `0..*` `Product`<br>`1` receives `0..*` `PurchaseOrder`<br>`1` receives `0..*` `SupplierReturn` |
| **`Product`** | `id: int`, `sku: str`, `name: str`, `description: str`, `category: str`, `unit: str`, `reorder_level: int`, `preferred_supplier_id: int` | `+create_product(): int`<br>`+update_product(): void`<br>`+delete_product(): void`<br>`+list_product_stock_summary(): list` | `1` has `0..*` `Batch`<br>`1` held in `0..*` `InventoryHolding` |
| **`Warehouse`** | `id: int`, `warehouse_code: str`, `name: str`, `location: str`, `address: str`, `is_active: bool` | `+create_warehouse(): int`<br>`+update_warehouse(): void`<br>`+get_warehouse_stock(): list` | `1` holds `0..*` `InventoryHolding` |
| **`Batch`** | `id: int`, `batch_number: str`, `product_id: int`, `supplier_id: int`, `mfg_date: date`, `expiry_date: date`, `unit_cost: float`, `receipt_date: date`, `initial_quantity: int` | `+receive_batch_stock(): dict`<br>`+is_expired(ref_date): bool`<br>`+days_to_expiry(): int` | `1` distributed across `0..*` `InventoryHolding` |
| **`InventoryHolding`** | `id: int`, `warehouse_id: int`, `batch_id: int`, `product_id: int`, `quantity: int`, `updated_at: datetime` | `+upsert_inventory_holding(delta: int): int`<br>`+adjust_batch_stock(delta: int, reason: str): int` | Links `1` `Warehouse` and `1` `Batch` (`UNIQUE(warehouse_id, batch_id)`) |
| **`PurchaseOrder`** & **`PurchaseOrderItem`** | Header: `id`, `po_number`, `supplier_id`, `target_warehouse_id`, `order_date`, `status`, `is_auto_generated`<br>Item: `id`, `po_id`, `product_id`, `ordered_quantity`, `received_quantity`, `expected_unit_cost` | `+check_reorder_levels(): list`<br>`+auto_generate_purchase_orders(): dict`<br>`+generate_purchase_order(): dict`<br>`+update_purchase_order_status(): void` | `PurchaseOrder` `1` $\rightarrow$ `1..*` `PurchaseOrderItem` (Composition) |
| **`GoodsReceipt`** & **`GoodsReceiptItem`** | Header: `id`, `grn_number`, `po_id`, `warehouse_id`, `receipt_date`, `notes`<br>Item: `id`, `receipt_id`, `po_item_id`, `product_id`, `batch_id`, `received_quantity`, `unit_cost` | `+receive_goods(po_id, receipt_items): dict`<br>`+list_goods_receipts(): list` | `PurchaseOrder` `1` $\rightarrow$ `0..*` `GoodsReceipt`<br>`GoodsReceipt` `1` $\rightarrow$ `1..*` `GoodsReceiptItem` (Composition) |
| **`StockTransfer`** & **`TransferItem`** | Header: `id`, `transfer_number`, `source_warehouse_id`, `dest_warehouse_id`, `transfer_date`, `status`<br>Item: `id`, `transfer_id`, `product_id`, `batch_id`, `quantity`, `received_quantity` | `+create_transfer(): dict`<br>`+dispatch_transfer(): dict`<br>`+receive_transfer(): dict`<br>`+cancel_transfer(): dict` | `StockTransfer` `1` $\rightarrow$ `1..*` `TransferItem` (Composition) |
| **`StockIssue`** & **`StockIssueItem`** | Header: `id`, `issue_number`, `warehouse_id`, `issue_date`, `recipient_reference`, `total_quantity`, `total_cost`<br>Item: `id`, `issue_id`, `product_id`, `batch_id`, `quantity`, `unit_cost`, `line_cost` | `+get_fifo_eligible_batches(): list`<br>`+issue_stock_fifo(): dict`<br>`+get_fifo_valuation_overview(): dict` | `StockIssue` `1` $\rightarrow$ `1..*` `StockIssueItem` (Composition) |
| **`SupplierReturn`** & **`SupplierReturnItem`** | Header: `id`, `return_number`, `supplier_id`, `warehouse_id`, `return_date`, `reason`, `status`<br>Item: `id`, `return_id`, `product_id`, `batch_id`, `quantity`, `unit_cost` | `+process_supplier_return(): dict`<br>`+list_supplier_returns(): list` | `SupplierReturn` `1` $\rightarrow$ `1..*` `SupplierReturnItem` (Composition) |
| **`StockTransaction`** | `id: int`, `product_id: int`, `batch_id: int`, `warehouse_id: int`, `transaction_type: str`, `quantity: int`, `unit_cost: float`, `reference_type: str`, `reference_id: str`, `created_at: datetime` | `+record_stock_transaction(): int`<br>`+list_stock_transactions(): list` | Associated with `1` `Product`, `1` `Batch`, and `1` `Warehouse` |
| **`SupplierIntegrationAdapter`** | `SIMULATED_VENDOR_CATALOG: dict` | `+verify_supplier_product(supplier_code, sku, qty, mode): dict` | Dependency from `Supplier` / `PurchaseOrder` service |

---

### 4. Activity Diagrams (StarUML Specifications)

#### 4.1 Activity Diagram 1: Purchase Order & Partial Goods Receipt (`04a_Activity_PO_Receipt`)
1. **Initial Node** $\rightarrow$ Action: `Run check_reorder_levels() across active warehouses (non-expired batches)`.
2. **Decision Node** `[available_stock <= reorder_level?]`:
   - `No` $\rightarrow$ **Activity Final**.
   - `Yes` $\rightarrow$ **Decision Node** `[Open PO ('Draft'/'Pending'/'Partially Received') exists for Product?]`:
     - `Yes` $\rightarrow$ Action: `Skip product (Prevent duplicate PO)` $\rightarrow$ **Activity Final**.
     - `No` $\rightarrow$ Action: `Create Draft PurchaseOrder + PurchaseOrderItem`.
3. Action: `Purchase Manager reviews and confirms PO (status = 'Pending')`.
4. Action: `Warehouse Operator receives shipment at target warehouse and enters received_quantity, batch_number, unit_cost, expiry_date`.
5. **Decision Node** `[received_quantity <= pending_quantity AND dates/cost valid?]`:
   - `No` $\rightarrow$ Action: `Rollback & raise ValidationError` $\rightarrow$ **Activity Final**.
   - `Yes` $\rightarrow$ Action: `Begin DB Transaction: Create/Reuse Batch, Upsert InventoryHolding (+received_quantity), Insert GoodsReceipt & GoodsReceiptItem, Increment POItem.received_quantity, Log GOODS_RECEIPT StockTransaction`.
6. **Decision Node** `[SUM(received_quantity) == SUM(ordered_quantity)?]`:
   - `No` (`0 < received < ordered`) $\rightarrow$ Action: `Set PO.status = 'Partially Received' (await next shipment)` $\rightarrow$ **Loop back to Step 4 for subsequent delivery or Exit**.
   - `Yes` $\rightarrow$ Action: `Set PO.status = 'Completed' & Commit Transaction` $\rightarrow$ **Activity Final**.

#### 4.2 Activity Diagram 2: Inter-Warehouse Stock Transfer (`04b_Activity_Warehouse_Transfer`)
1. **Initial Node** $\rightarrow$ Action: `Select source_warehouse, dest_warehouse, product, eligible batch, and transfer quantity`.
2. **Decision Node** `[source != dest AND warehouses active AND batch not expired AND qty <= source_inventory?]`:
   - `No` $\rightarrow$ Action: `Reject with ValidationError` $\rightarrow$ **Activity Final**.
   - `Yes` $\rightarrow$ Action: `Create Transfer ('Draft') and TransferItem`.
3. Action: `Dispatch Transfer: Deduct quantity from Source Warehouse InventoryHolding (-qty), Log TRANSFER_DISPATCH StockTransaction, Set status = 'Dispatched'`.
4. *(In-Transit State: Stock is removed from source and not yet available at destination).*
5. **Decision Node** `[Destination Action?]`:
   - `[Cancel before receipt]` $\rightarrow$ Action: `Restore +qty to Source Warehouse InventoryHolding, Log TRANSFER_CANCEL, Set status = 'Cancelled'` $\rightarrow$ **Activity Final**.
   - `[Receive at Destination]` $\rightarrow$ Action: `Upsert Destination Warehouse InventoryHolding (+receive_qty) using SAME batch_id, Increment TransferItem.received_quantity, Log TRANSFER_RECEIPT StockTransaction`.
6. **Decision Node** `[received_quantity == dispatched_quantity?]`:
   - `No` $\rightarrow$ Action: `Set status = 'Partially Received'` $\rightarrow$ **Activity Final**.
   - `Yes` $\rightarrow$ Action: `Set status = 'Received'` $\rightarrow$ **Activity Final**.

#### 4.3 Activity Diagram 3: FIFO Stock Issue & Valuation (`04c_Activity_FIFO_Issue`)
1. **Initial Node** $\rightarrow$ Action: `Input warehouse_id, product_id, issue_quantity, issue_date`.
2. Action: `Query InventoryHolding joined with Batch where warehouse_id = ?, product_id = ?, quantity > 0, and (expiry_date IS NULL OR expiry_date >= issue_date)`.
3. Action: `Sort eligible batches strictly by receipt_date ASC, batch_id ASC (FIFO Queue)`.
4. **Decision Node** `[SUM(eligible_batch.quantity) >= issue_quantity?]`:
   - `No` $\rightarrow$ Action: `Raise ValidationError (report excluded expired units if any)` $\rightarrow$ **Activity Final**.
   - `Yes` $\rightarrow$ Action: `Initialize remaining_to_consume = issue_quantity, total_cost = 0`.
5. **Loop Node** `[While remaining_to_consume > 0 for next oldest Batch in FIFO Queue]`:
   - Action: `take_qty = min(batch.available_quantity, remaining_to_consume)`
   - Action: `line_cost = take_qty * batch.unit_cost; total_cost += line_cost`
   - Action: `Deduct take_qty from InventoryHolding (warehouse_id, batch_id)`
   - Action: `Append StockIssueItem(batch_id, take_qty, unit_cost, line_cost)`
   - Action: `Record STOCK_ISSUE StockTransaction (-take_qty)`
   - Action: `remaining_to_consume -= take_qty`
6. Action: `Save StockIssue header with total_quantity and total_cost (₹); Commit Transaction` $\rightarrow$ **Activity Final**.

---

### 5. Sequence Diagrams (StarUML Specifications)

#### 5.1 Sequence Diagram 1: Automatic Reorder Generation (`05a_Seq_AutoReorder`)
- **Lifelines**: `:PurchaseManager`, `:PurchasesRoute (purchases_bp)`, `:ReorderService (reorder_service)`, `:Database (database.py)`, `:SQLiteDB`.
- **Messages**:
  1. `:PurchaseManager` $\rightarrow$ `:PurchasesRoute`: `POST /purchases/auto-generate(target_warehouse_id)`
  2. `:PurchasesRoute` $\rightarrow$ `:ReorderService`: `auto_generate_purchase_orders(target_warehouse_id)`
  3. `:ReorderService` $\rightarrow$ `:ReorderService`: `check_reorder_levels()`
  4. `:ReorderService` $\rightarrow$ `:Database`: `query_all(SELECT products HAVING available_stock <= reorder_level + open_po_pending_qty)`
  5. `:Database` $\rightarrow$ `:SQLiteDB`: `Execute parameterized SQL` $\rightarrow$ returns `low_stock_rows`
  6. **Loop** `[for each candidate where open_po_pending_qty == 0 and supplier_active == 1]`:
     - `:ReorderService` $\rightarrow$ `:ReorderService`: `generate_purchase_order(supplier_id, target_warehouse_id, items, is_auto_generated=True)`
     - `:ReorderService` $\rightarrow$ `:Database`: `transaction() BEGIN`
     - `:ReorderService` $\rightarrow$ `:SQLiteDB`: `INSERT INTO purchase_orders (...)`
     - `:ReorderService` $\rightarrow$ `:SQLiteDB`: `INSERT INTO purchase_order_items (...)`
     - `:Database` $\rightarrow$ `:SQLiteDB`: `COMMIT`
  7. `:ReorderService` $\rightarrow$ `:PurchasesRoute`: `return {created_pos, skipped_open_po, skipped_no_supplier}`
  8. `:PurchasesRoute` $\rightarrow$ `:PurchaseManager`: `302 Redirect /purchases with flash summary`

#### 5.2 Sequence Diagram 2: Partial Goods Receipt (`05b_Seq_GoodsReceipt`)
- **Lifelines**: `:WarehouseOperator`, `:PurchasesRoute`, `:ReorderService`, `:InventoryService`, `:Database`, `:SQLiteDB`.
- **Messages**:
  1. `:WarehouseOperator` $\rightarrow$ `:PurchasesRoute`: `POST /receipts/create(po_id, po_item_id, received_quantity, batch_number, unit_cost, expiry_date)`
  2. `:PurchasesRoute` $\rightarrow$ `:ReorderService`: `receive_goods(po_id, receipt_items, warehouse_id, receipt_date)`
  3. `:ReorderService` $\rightarrow$ `:Database`: `transaction() BEGIN`
  4. `:ReorderService` $\rightarrow$ `:SQLiteDB`: `SELECT * FROM purchase_orders & purchase_order_items (validate received_qty <= pending_qty)`
  5. `:ReorderService` $\rightarrow$ `:SQLiteDB`: `INSERT INTO goods_receipts (...)`
  6. `:ReorderService` $\rightarrow$ `:SQLiteDB`: `SELECT / INSERT INTO batches (batch_number, product_id, unit_cost, expiry_date, receipt_date)`
  7. `:ReorderService` $\rightarrow$ `:InventoryService`: `upsert_inventory_holding(tx_conn, warehouse_id, batch_id, product_id, +received_quantity)`
  8. `:ReorderService` $\rightarrow$ `:SQLiteDB`: `UPDATE purchase_order_items SET received_quantity = received_quantity + ?`
  9. `:ReorderService` $\rightarrow$ `:SQLiteDB`: `INSERT INTO goods_receipt_items (...)`
  10. `:ReorderService` $\rightarrow$ `:InventoryService`: `record_stock_transaction(tx_conn, ..., 'GOODS_RECEIPT', +received_quantity)`
  11. `:ReorderService` $\rightarrow$ `:SQLiteDB`: `UPDATE purchase_orders SET status = ('Partially Received' or 'Completed')`
  12. `:Database` $\rightarrow$ `:SQLiteDB`: `COMMIT`
  13. `:ReorderService` $\rightarrow$ `:PurchasesRoute` $\rightarrow$ `:WarehouseOperator`: `Redirect /receipts with GRN confirmation`

#### 5.3 Sequence Diagram 3: Inter-Warehouse Stock Transfer (`05c_Seq_WarehouseTransfer`)
- **Lifelines**: `:WarehouseOperator`, `:TransfersRoute`, `:TransferService`, `:InventoryService`, `:Database`, `:SQLiteDB`.
- **Messages**:
  - **Interaction Frame 1 (`Dispatch Phase`)**:
    1. `:WarehouseOperator` $\rightarrow$ `:TransfersRoute`: `POST /transfers/create(source_wh, dest_wh, batch_id, qty, initial_action='dispatch')`
    2. `:TransfersRoute` $\rightarrow$ `:TransferService`: `create_transfer(..., auto_dispatch=True)`
    3. `:TransferService` $\rightarrow$ `:Database`: `transaction() BEGIN`
    4. `:TransferService` $\rightarrow$ `:SQLiteDB`: `Validate source != dest, batch not expired, source qty >= transfer qty`
    5. `:TransferService` $\rightarrow$ `:SQLiteDB`: `INSERT INTO transfers ('Draft') & transfer_items`
    6. `:TransferService` $\rightarrow$ `:TransferService`: `dispatch_transfer(transfer_id)`
    7. `:TransferService` $\rightarrow$ `:InventoryService`: `upsert_inventory_holding(source_wh, batch_id, -qty)`
    8. `:TransferService` $\rightarrow$ `:InventoryService`: `record_stock_transaction('TRANSFER_DISPATCH', -qty)`
    9. `:TransferService` $\rightarrow$ `:SQLiteDB`: `UPDATE transfers SET status = 'Dispatched', dispatched_at = datetime('now')`
    10. `:Database` $\rightarrow$ `:SQLiteDB`: `COMMIT`
  - **Interaction Frame 2 (`Receipt Phase`)**:
    11. `:WarehouseOperator` $\rightarrow$ `:TransfersRoute`: `POST /transfers/<id>/receive(receive_quantity)`
    12. `:TransfersRoute` $\rightarrow$ `:TransferService`: `receive_transfer(transfer_id, receive_quantity)`
    13. `:TransferService` $\rightarrow$ `:Database`: `transaction() BEGIN`
    14. `:TransferService` $\rightarrow$ `:InventoryService`: `upsert_inventory_holding(dest_wh, batch_id, +receive_quantity)` *(preserves original `batch_id`)*
    15. `:TransferService` $\rightarrow$ `:SQLiteDB`: `UPDATE transfer_items SET received_quantity = received_quantity + ?`
    16. `:TransferService` $\rightarrow$ `:InventoryService`: `record_stock_transaction('TRANSFER_RECEIPT', +receive_quantity)`
    17. `:TransferService` $\rightarrow$ `:SQLiteDB`: `UPDATE transfers SET status = 'Received', received_at = datetime('now')`
    18. `:Database` $\rightarrow$ `:SQLiteDB`: `COMMIT`
