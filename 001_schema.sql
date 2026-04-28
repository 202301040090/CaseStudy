-- =============================================================================
-- StockFlow – Database Schema (Part 2)
-- migrations/001_schema.sql
--
-- Run with:  psql stockflow_db < migrations/001_schema.sql
--
-- Design decisions:
--   * All monetary values use NUMERIC(10,2) – no floating-point rounding errors.
--   * SKU is UNIQUE across the entire platform (cross-company).
--   * inventory has a UNIQUE constraint on (product_id, warehouse_id) so there
--     is exactly one stock-level row per product per warehouse.
--   * inventory_movements is the audit trail; used for velocity calc in alerts.
--   * bundle_items is a self-referential join on products for composite products.
--   * Indexes are placed on every FK used in high-frequency joins and on
--     time-range columns used in the alerts query.
-- =============================================================================

-- Enable pgcrypto for potential UUID use later (optional, harmless if missing)
-- CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── 1. companies ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS companies (
    id         SERIAL       PRIMARY KEY,
    name       VARCHAR(255) NOT NULL,
    plan_tier  VARCHAR(50)  NOT NULL DEFAULT 'starter',
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── 2. warehouses ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS warehouses (
    id         SERIAL       PRIMARY KEY,
    company_id INT          NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name       VARCHAR(255) NOT NULL,
    location   TEXT,
    is_active  BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_warehouses_company ON warehouses(company_id);

-- ── 3. suppliers ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS suppliers (
    id             SERIAL       PRIMARY KEY,
    company_id     INT          NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name           VARCHAR(255) NOT NULL,
    contact_email  VARCHAR(255),
    contact_phone  VARCHAR(50),
    lead_time_days INT,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_suppliers_company ON suppliers(company_id);

-- ── 4. products ───────────────────────────────────────────────────────────────
-- SKU is unique ACROSS the whole platform (not per company).
-- low_stock_threshold varies by product; default 20.
-- product_type: 'standard' or 'bundle' (see bundle_items below).
CREATE TABLE IF NOT EXISTS products (
    id                  SERIAL        PRIMARY KEY,
    sku                 VARCHAR(100)  NOT NULL,
    name                VARCHAR(255)  NOT NULL,
    description         TEXT,
    price               NUMERIC(10,2) NOT NULL CHECK (price >= 0),
    product_type        VARCHAR(50)   NOT NULL DEFAULT 'standard',
    low_stock_threshold INT           NOT NULL DEFAULT 20 CHECK (low_stock_threshold >= 0),
    supplier_id         INT           REFERENCES suppliers(id) ON DELETE SET NULL,
    is_active           BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT products_sku_unique UNIQUE (sku),
    CONSTRAINT products_type_check CHECK (product_type IN ('standard', 'bundle'))
);

CREATE INDEX IF NOT EXISTS idx_products_sku         ON products(sku);
CREATE INDEX IF NOT EXISTS idx_products_supplier    ON products(supplier_id);

-- ── 5. bundle_items ───────────────────────────────────────────────────────────
-- Supports composite/bundle products. A bundle product can contain N components.
-- RESTRICT on component prevents deleting a product that is used inside a bundle.
CREATE TABLE IF NOT EXISTS bundle_items (
    id           SERIAL PRIMARY KEY,
    bundle_id    INT    NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    component_id INT    NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    quantity     INT    NOT NULL DEFAULT 1 CHECK (quantity > 0),

    CONSTRAINT bundle_items_unique UNIQUE (bundle_id, component_id),
    -- A product cannot be its own component
    CONSTRAINT bundle_items_no_self_ref CHECK (bundle_id <> component_id)
);

CREATE INDEX IF NOT EXISTS idx_bundle_items_bundle    ON bundle_items(bundle_id);
CREATE INDEX IF NOT EXISTS idx_bundle_items_component ON bundle_items(component_id);

-- ── 6. inventory ──────────────────────────────────────────────────────────────
-- One row per (product, warehouse) pair – the current stock level.
-- quantity >= 0 enforced at DB level (no backorders by default).
-- updated_at is refreshed on every stock change via application logic.
CREATE TABLE IF NOT EXISTS inventory (
    id           SERIAL      PRIMARY KEY,
    product_id   INT         NOT NULL REFERENCES products(id)   ON DELETE CASCADE,
    warehouse_id INT         NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    quantity     INT         NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT inventory_product_warehouse_unique UNIQUE (product_id, warehouse_id)
);

CREATE INDEX IF NOT EXISTS idx_inventory_warehouse ON inventory(warehouse_id);
CREATE INDEX IF NOT EXISTS idx_inventory_product   ON inventory(product_id);

-- ── 7. inventory_movements ────────────────────────────────────────────────────
-- Immutable audit trail for every stock change.
-- change_qty > 0 = stock added (purchase / transfer in)
-- change_qty < 0 = stock removed (sale / transfer out / shrinkage)
-- reason: 'sale' | 'purchase' | 'adjustment' | 'transfer_in' | 'transfer_out'
-- reference_id: FK to orders.id, purchase_orders.id, etc. (polymorphic, intentionally untyped)
CREATE TABLE IF NOT EXISTS inventory_movements (
    id           SERIAL      PRIMARY KEY,
    inventory_id INT         NOT NULL REFERENCES inventory(id) ON DELETE CASCADE,
    change_qty   INT         NOT NULL,
    reason       VARCHAR(100),
    reference_id INT,
    created_by   INT,                  -- user_id; FK omitted (user table out of scope)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT movements_reason_check CHECK (
        reason IN ('sale', 'purchase', 'adjustment', 'transfer_in', 'transfer_out')
        OR reason IS NULL
    )
);

-- Composite index supports the velocity CTE: filter by inventory + date range
CREATE INDEX IF NOT EXISTS idx_movements_inv_date ON inventory_movements(inventory_id, created_at DESC);

-- ── 8. orders ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orders (
    id         SERIAL      PRIMARY KEY,
    company_id INT         NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    status     VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT orders_status_check CHECK (
        status IN ('pending', 'confirmed', 'shipped', 'delivered', 'cancelled')
    )
);

CREATE INDEX IF NOT EXISTS idx_orders_company_date ON orders(company_id, created_at DESC);

-- ── 9. order_items ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS order_items (
    id           SERIAL        PRIMARY KEY,
    order_id     INT           NOT NULL REFERENCES orders(id)     ON DELETE CASCADE,
    product_id   INT           NOT NULL REFERENCES products(id)   ON DELETE RESTRICT,
    warehouse_id INT           NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    quantity     INT           NOT NULL CHECK (quantity > 0),
    unit_price   NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0)
);

-- Composite index used by the low-stock alerts velocity CTE
CREATE INDEX IF NOT EXISTS idx_order_items_product_warehouse ON order_items(product_id, warehouse_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order             ON order_items(order_id);

-- =============================================================================
-- Clarifying questions for the product team (answers would affect this schema):
--
-- Q1. Can a product belong to multiple companies, or is every product
--     company-scoped? (Currently: SKU is global / cross-company.)
-- Q2. Should inventory.quantity ever go negative (backorders)?
-- Q3. Are warehouse-to-warehouse transfers a first-class concept?
--     (Currently modelled as two movements; a transfers table may be cleaner.)
-- Q4. Does low_stock_threshold vary per warehouse, or only per product?
--     (Currently: per product only.)
-- Q5. How is bundle stock tracked – from component levels or independently?
-- Q6. Is supplier lead_time_days per product or per supplier?
-- Q7. What is the data-retention policy for inventory_movements?
-- Q8. Are there user roles (admin vs warehouse staff) affecting row-level access?
-- =============================================================================
