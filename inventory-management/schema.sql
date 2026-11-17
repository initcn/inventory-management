PRAGMA foreign_keys = ON;

-- 1. Suppliers Master Table
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    contact_person TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    address TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 2. Products Master Table
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'Units',
    reorder_level INTEGER NOT NULL DEFAULT 10 CHECK (reorder_level >= 0),
    preferred_supplier_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (preferred_supplier_id) REFERENCES suppliers(id) ON DELETE RESTRICT
);

-- 3. Warehouses Master Table
CREATE TABLE IF NOT EXISTS warehouses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    warehouse_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    location TEXT NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 4. Batches Table (Intrinsic batch identity, cost, and dates)
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_number TEXT NOT NULL,
    product_id INTEGER NOT NULL,
    supplier_id INTEGER,
    mfg_date TEXT,
    expiry_date TEXT,
    unit_cost REAL NOT NULL CHECK (unit_cost >= 0),
    receipt_date TEXT NOT NULL,
    initial_quantity INTEGER NOT NULL CHECK (initial_quantity > 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (product_id, batch_number),
    CHECK (expiry_date IS NULL OR mfg_date IS NULL OR date(expiry_date) >= date(mfg_date)),
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE RESTRICT
);

-- 5. Warehouse-Specific Batch Inventory Holdings
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    warehouse_id INTEGER NOT NULL,
    batch_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (warehouse_id, batch_id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT,
    FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE RESTRICT,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
);

-- 6. Purchase Orders Header
CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_number TEXT NOT NULL UNIQUE,
    supplier_id INTEGER NOT NULL,
    target_warehouse_id INTEGER NOT NULL,
    order_date TEXT NOT NULL DEFAULT (date('now')),
    status TEXT NOT NULL DEFAULT 'Draft'
        CHECK (status IN ('Draft', 'Pending', 'Partially Received', 'Completed', 'Cancelled')),
    is_auto_generated INTEGER NOT NULL DEFAULT 0 CHECK (is_auto_generated IN (0, 1)),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE RESTRICT,
    FOREIGN KEY (target_warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT
);

-- 7. Purchase Order Line Items
CREATE TABLE IF NOT EXISTS purchase_order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    ordered_quantity INTEGER NOT NULL CHECK (ordered_quantity > 0),
    received_quantity INTEGER NOT NULL DEFAULT 0
        CHECK (received_quantity >= 0 AND received_quantity <= ordered_quantity),
    expected_unit_cost REAL NOT NULL DEFAULT 0 CHECK (expected_unit_cost >= 0),
    UNIQUE (po_id, product_id),
    FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
);

-- 8. Goods Receipts Header
CREATE TABLE IF NOT EXISTS goods_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grn_number TEXT NOT NULL UNIQUE,
    po_id INTEGER NOT NULL,
    warehouse_id INTEGER NOT NULL,
    receipt_date TEXT NOT NULL DEFAULT (date('now')),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE RESTRICT,
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT
);

-- 9. Goods Receipt Line Items
CREATE TABLE IF NOT EXISTS goods_receipt_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id INTEGER NOT NULL,
    po_item_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    batch_id INTEGER NOT NULL,
    received_quantity INTEGER NOT NULL CHECK (received_quantity > 0),
    unit_cost REAL NOT NULL CHECK (unit_cost >= 0),
    FOREIGN KEY (receipt_id) REFERENCES goods_receipts(id) ON DELETE CASCADE,
    FOREIGN KEY (po_item_id) REFERENCES purchase_order_items(id) ON DELETE RESTRICT,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
    FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE RESTRICT
);

-- 10. Inter-Warehouse Transfers Header
CREATE TABLE IF NOT EXISTS transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transfer_number TEXT NOT NULL UNIQUE,
    source_warehouse_id INTEGER NOT NULL,
    dest_warehouse_id INTEGER NOT NULL,
    transfer_date TEXT NOT NULL DEFAULT (date('now')),
    dispatched_at TEXT,
    received_at TEXT,
    status TEXT NOT NULL DEFAULT 'Draft'
        CHECK (status IN ('Draft', 'Dispatched', 'Partially Received', 'Received', 'Cancelled')),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (source_warehouse_id != dest_warehouse_id),
    FOREIGN KEY (source_warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT,
    FOREIGN KEY (dest_warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT
);

-- 11. Inter-Warehouse Transfer Line Items
CREATE TABLE IF NOT EXISTS transfer_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transfer_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    batch_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    received_quantity INTEGER NOT NULL DEFAULT 0
        CHECK (received_quantity >= 0 AND received_quantity <= quantity),
    UNIQUE (transfer_id, batch_id),
    FOREIGN KEY (transfer_id) REFERENCES transfers(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
    FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE RESTRICT
);

-- 12. FIFO Stock Issues Header
CREATE TABLE IF NOT EXISTS stock_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_number TEXT NOT NULL UNIQUE,
    warehouse_id INTEGER NOT NULL,
    issue_date TEXT NOT NULL DEFAULT (date('now')),
    recipient_reference TEXT NOT NULL DEFAULT '',
    total_quantity INTEGER NOT NULL CHECK (total_quantity > 0),
    total_cost REAL NOT NULL CHECK (total_cost >= 0),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT
);

-- 13. FIFO Stock Issue Batch Consumption Breakdown
CREATE TABLE IF NOT EXISTS stock_issue_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    batch_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_cost REAL NOT NULL CHECK (unit_cost >= 0),
    line_cost REAL NOT NULL CHECK (line_cost >= 0),
    FOREIGN KEY (issue_id) REFERENCES stock_issues(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
    FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE RESTRICT
);

-- 14. Supplier Returns Header
CREATE TABLE IF NOT EXISTS supplier_returns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    return_number TEXT NOT NULL UNIQUE,
    supplier_id INTEGER NOT NULL,
    warehouse_id INTEGER NOT NULL,
    return_date TEXT NOT NULL DEFAULT (date('now')),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    status TEXT NOT NULL DEFAULT 'Completed' CHECK (status IN ('Completed', 'Cancelled')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE RESTRICT,
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT
);

-- 15. Supplier Return Line Items
CREATE TABLE IF NOT EXISTS supplier_return_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    return_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    batch_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_cost REAL NOT NULL CHECK (unit_cost >= 0),
    FOREIGN KEY (return_id) REFERENCES supplier_returns(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
    FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE RESTRICT
);

-- 16. Immutable Stock Transaction History Ledger
CREATE TABLE IF NOT EXISTS stock_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    batch_id INTEGER NOT NULL,
    warehouse_id INTEGER NOT NULL,
    transaction_type TEXT NOT NULL CHECK (
        transaction_type IN (
            'GOODS_RECEIPT',
            'STOCK_ISSUE',
            'TRANSFER_DISPATCH',
            'TRANSFER_RECEIPT',
            'TRANSFER_CANCEL',
            'SUPPLIER_RETURN',
            'ADJUSTMENT'
        )
    ),
    quantity INTEGER NOT NULL CHECK (quantity != 0),
    unit_cost REAL NOT NULL DEFAULT 0 CHECK (unit_cost >= 0),
    reference_type TEXT NOT NULL DEFAULT '',
    reference_id TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
    FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE RESTRICT,
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE RESTRICT
);

-- Performance & Lookup Indexes
CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
CREATE INDEX IF NOT EXISTS idx_batches_product_receipt ON batches(product_id, receipt_date, id);
CREATE INDEX IF NOT EXISTS idx_batches_expiry ON batches(expiry_date);
CREATE INDEX IF NOT EXISTS idx_inventory_wh_prod ON inventory(warehouse_id, product_id);
CREATE INDEX IF NOT EXISTS idx_inventory_batch ON inventory(batch_id);
CREATE INDEX IF NOT EXISTS idx_po_status ON purchase_orders(status);
CREATE INDEX IF NOT EXISTS idx_transfers_status ON transfers(status);
CREATE INDEX IF NOT EXISTS idx_transactions_lookup ON stock_transactions(product_id, warehouse_id, created_at);
