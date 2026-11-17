# Inventory & Multi-Warehouse Management System
**Enterprise Multi-Warehouse Inventory & Supply Chain Management System**

A production-grade, reliable, layered web application built with **Python 3, Flask, SQLite (`sqlite3`), HTML5/CSS3/Bootstrap 5, Jinja2, and `unittest`** demonstrating Object-Oriented Analysis and Design (OOAD), transactional relational database architecture, and automated testing.

---

## 1. Key Features Implemented
1. **Product Management (`Module 1`)**: Add, view, edit, and safely delete products (`sku`, `name`, `category`, `unit`, `reorder_level`, `preferred_supplier_id`). Prevents duplicate SKUs, negative reorder levels, and deletion of products with historical records.
2. **Warehouse Management (`Module 2`)**: Manage multiple warehouses (`WH-DEL-01`, `WH-GGN-02`, `WH-FBD-03`), toggle active status, and inspect warehouse-specific batch holdings and stock valuation in `₹`.
3. **Supplier Management & External Integration (`Module 3` & `Section 8`)**: Manage supplier contacts, view associated products and purchase orders, and test the **Simulated External Supplier System Adapter** (`integrations/supplier_adapter.py`) across `SUCCESS`, `FAILURE`, `TIMEOUT`, and `UNAVAILABLE` scenarios without external API keys.
4. **Batch-Wise Inventory & Expiry Monitoring (`Module 4`)**: Separates intrinsic batch identity (`batches` table: `batch_number`, `mfg_date`, `expiry_date`, `unit_cost`, `receipt_date`) from warehouse-specific quantities (`inventory` table). Automatically flags `EXPIRED` and `NEAR_EXPIRY` (within 30 days) batches and blocks negative stock.
5. **Automatic Reorder & Partial Goods Receipts (`Module 5`)**: Evaluates non-expired stock across active warehouses against `reorder_level`, generates draft Purchase Orders with strict duplicate prevention, and supports partial and multi-shipment Goods Receipts (`GRN`) that automatically create/update batches and transition PO status (`Draft` $\rightarrow$ `Pending` $\rightarrow$ `Partially Received` $\rightarrow$ `Completed`).
6. **Two-Step Inter-Warehouse Stock Transfers (`Module 6`)**: Enforces `Draft` $\rightarrow$ `Dispatched` (in-transit deduction from source) $\rightarrow$ `Partially Received` / `Received` (credit to destination under the exact same `batch_id`, preserving original unit cost and expiry date) or `Cancelled` (safe restoration to source).
7. **FIFO Stock Issue & Valuation (`Module 7`)**: Consumes oldest eligible (non-expired) batches first ordered strictly by `receipt_date ASC, batch_id ASC`, spans multiple batches automatically, and displays the exact batch-by-batch FIFO cost breakdown in `₹`.
8. **Supplier Returns (`Module 8`)**: Validates return quantities against remaining batch stock, deducts warehouse inventory without deleting historical records, and logs a return transaction.
9. **Immutable Stock Transaction Ledger (`Module 9`)**: Records every `GOODS_RECEIPT`, `STOCK_ISSUE`, `TRANSFER_DISPATCH`, `TRANSFER_RECEIPT`, `TRANSFER_CANCEL`, `SUPPLIER_RETURN`, and `ADJUSTMENT` with product, batch, warehouse, signed quantity, unit cost, and document reference.

---

## 2. Project Structure
```text
inventory-management/
├── app.py                      # Flask app factory, dashboard KPIs, blueprint registration
├── config.py                   # Centralized configuration (DB path, currency ₹, expiry window)
├── database.py                 # SQLite connection manager, PRAGMA foreign_keys=ON, ACID transactions
├── schema.sql                  # Normalized 16-table SQLite relational schema & indexes
├── seed.py                     # Safe, idempotent demonstration data seed script
├── requirements.txt            # Minimal dependencies (Flask)
├── README.md                   # Setup, execution, seeding, and testing guide
├── routes/                     # HTTP controller blueprints
│   ├── products.py
│   ├── warehouses.py
│   ├── suppliers.py
│   ├── inventory.py
│   ├── purchases.py
│   ├── transfers.py
│   └── returns.py
├── services/                   # Business logic & transactional domain services
│   ├── product_service.py
│   ├── warehouse_service.py
│   ├── supplier_service.py
│   ├── inventory_service.py
│   ├── reorder_service.py
│   ├── transfer_service.py
│   ├── fifo_service.py
│   └── return_service.py
├── integrations/               # Isolated external system integration layer
│   └── supplier_adapter.py     # Simulated Supplier System Adapter (Success/Failure/Timeout)
├── templates/                  # 11 Bootstrap 5 + Jinja2 views
│   ├── base.html
│   ├── dashboard.html
│   ├── products.html
│   ├── warehouses.html
│   ├── suppliers.html
│   ├── inventory.html
│   ├── purchases.html
│   ├── receipts.html
│   ├── transfers.html
│   ├── valuation.html
│   ├── returns.html
│   └── transactions.html
├── static/
│   ├── css/style.css
│   └── js/app.js
├── tests/                      # Automated unittest suite (19 tests)
│   ├── test_products.py
│   ├── test_inventory.py
│   ├── test_purchases.py
│   ├── test_transfers.py
│   └── test_fifo.py
└── docs/                       # System Architecture & OOAD Documentation
    ├── requirements.md
    ├── architecture.md
    ├── database-design.md
    ├── refinement-log.md
    ├── scenario-walkthrough.md
    └── consistency-report.md
```

---

## 3. Installation & Execution on Windows

### Step 1: Create and Activate a Virtual Environment
Open **Command Prompt** or **PowerShell** inside the `inventory-management` folder and run:
```bat
python -m venv venv
venv\Scripts\activate
```

### Step 2: Install Dependencies
```bat
pip install -r requirements.txt
```

### Step 3: Initialize Database & Load Optional Demonstration Data
The SQLite database (`inventory.db`) is automatically created from `schema.sql` whenever `app.py` or `seed.py` runs. To populate the realistic Indian currency (`₹`) demonstration dataset (8 products, 3 warehouses, 4 suppliers, 11 batches, POs, transfers, ₹6,200 FIFO issue, and supplier return), run:
```bat
python seed.py
```
*(You can also click the **"Load Demonstration Data"** button directly on the web dashboard if the database is empty. Running `python seed.py` multiple times is safe and will not duplicate records; to force a clean reset of demo data, run `python -c "from seed import seed_demo_data; seed_demo_data(force_reset=True)"`.)*

### Step 4: Run the Application
```bat
python app.py
```
Open **`http://127.0.0.1:5000`** in your web browser.

---

## 4. Running the Automated Unit Tests
Execute the built-in `unittest` suite from the `inventory-management` root directory:
```bat
python -m unittest discover -s tests -p "test_*.py" -v
```
Expected result: **`Ran 19 tests ... OK`**.

---

## 5. System Architecture & OOAD Documentation Index
All system specifications, architecture diagrams, refinement logs, and consistency checks are located in the `docs/` folder:
- [`docs/requirements.md`](docs/requirements.md) — Functional/Non-functional requirements, Actors, and StarUML Use Case Diagram guide.
- [`docs/architecture.md`](docs/architecture.md) — 4-layer architecture, Component Diagram, Initial & Refined Class Diagrams, 3 Activity Diagrams, and 3 Sequence Diagrams for StarUML.
- [`docs/database-design.md`](docs/database-design.md) — 16-table normalized SQLite schema documentation and batch-warehouse separation rationale.
- [`docs/refinement-log.md`](docs/refinement-log.md) — OOAD Model Refinement Change Log table (`Initial design`, `Refinement`, `Reason`, `Benefit`).
- [`docs/scenario-walkthrough.md`](docs/scenario-walkthrough.md) — Step-by-step state transitions for Reorder, Partial Receipt, Warehouse Transfer, FIFO Issue (`₹6,200`), and Supplier Return.
- [`docs/consistency-report.md`](docs/consistency-report.md) — Cross-model verification and automated test matrix.
