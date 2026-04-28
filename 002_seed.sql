-- =============================================================================
-- StockFlow – Seed Data
-- migrations/002_seed.sql
--
-- Creates realistic sample data for local development and manual testing.
-- Run AFTER 001_schema.sql:
--   psql stockflow_db < migrations/002_seed.sql
-- =============================================================================

-- ── Companies ─────────────────────────────────────────────────────────────────
INSERT INTO companies (id, name, plan_tier) VALUES
    (1, 'Acme Corp',       'pro'),
    (2, 'Beta Supplies',   'starter')
ON CONFLICT DO NOTHING;

-- ── Warehouses ────────────────────────────────────────────────────────────────
INSERT INTO warehouses (id, company_id, name, location, is_active) VALUES
    (1, 1, 'Main Warehouse',  'Mumbai, Maharashtra',  TRUE),
    (2, 1, 'North Warehouse', 'Delhi, NCR',           TRUE),
    (3, 1, 'Inactive Store',  'Pune, Maharashtra',    FALSE),
    (4, 2, 'Beta HQ',        'Bangalore, Karnataka',  TRUE)
ON CONFLICT DO NOTHING;

-- ── Suppliers ────────────────────────────────────────────────────────────────
INSERT INTO suppliers (id, company_id, name, contact_email, contact_phone, lead_time_days) VALUES
    (1, 1, 'Supplier Corp',    'orders@suppliercorp.com',   '+91-22-12345678', 7),
    (2, 1, 'FastParts Ltd',    'reorder@fastparts.in',      '+91-11-87654321', 3),
    (3, 2, 'Beta Vendor',      'supply@betavendor.com',     NULL,              14)
ON CONFLICT DO NOTHING;

-- ── Products ─────────────────────────────────────────────────────────────────
INSERT INTO products (id, sku, name, price, product_type, low_stock_threshold, supplier_id, is_active) VALUES
    (1,  'WID-001', 'Widget A',          199.99, 'standard', 20, 1, TRUE),
    (2,  'WID-002', 'Widget B',          149.50, 'standard', 15, 1, TRUE),
    (3,  'GAD-001', 'Gadget Pro',        499.00, 'standard', 10, 2, TRUE),
    (4,  'BND-001', 'Starter Bundle',    349.00, 'bundle',   5,  1, TRUE),
    (5,  'WID-003', 'Widget C (No Sup)', 89.00,  'standard', 25, NULL, TRUE),
    (6,  'OLD-001', 'Legacy Part',       19.99,  'standard', 10, 2, FALSE)  -- inactive
ON CONFLICT DO NOTHING;

-- Bundle: Starter Bundle = 1x Widget A + 1x Widget B
INSERT INTO bundle_items (bundle_id, component_id, quantity) VALUES
    (4, 1, 1),
    (4, 2, 1)
ON CONFLICT DO NOTHING;

-- ── Inventory ─────────────────────────────────────────────────────────────────
-- Acme – Main Warehouse (id=1)
INSERT INTO inventory (product_id, warehouse_id, quantity) VALUES
    (1, 1, 5),    -- Widget A:    BELOW threshold (20) → should alert
    (2, 1, 50),   -- Widget B:    above threshold
    (3, 1, 3),    -- Gadget Pro:  BELOW threshold (10) → should alert
    (4, 1, 12),   -- Bundle:      above threshold (5)
    (5, 1, 8)     -- Widget C:    BELOW threshold (25) → alert only if sales exist
ON CONFLICT DO NOTHING;

-- Acme – North Warehouse (id=2)
INSERT INTO inventory (product_id, warehouse_id, quantity) VALUES
    (1, 2, 4),    -- Widget A also low here → second alert row
    (2, 2, 30),
    (3, 2, 20)
ON CONFLICT DO NOTHING;

-- ── Orders (last 30 days) ─────────────────────────────────────────────────────
-- These drive the velocity / "recent sales activity" filter.
INSERT INTO orders (id, company_id, status, created_at) VALUES
    (1, 1, 'delivered', NOW() - INTERVAL '5 days'),
    (2, 1, 'delivered', NOW() - INTERVAL '10 days'),
    (3, 1, 'delivered', NOW() - INTERVAL '20 days'),
    (4, 1, 'cancelled', NOW() - INTERVAL '3 days'),   -- CANCELLED: excluded from velocity
    (5, 1, 'delivered', NOW() - INTERVAL '45 days')   -- OLDER than window: excluded
ON CONFLICT DO NOTHING;

-- ── Order Items ───────────────────────────────────────────────────────────────
-- Order 1: sold Widget A (warehouse 1) and Gadget Pro (warehouse 1)
INSERT INTO order_items (order_id, product_id, warehouse_id, quantity, unit_price) VALUES
    (1, 1, 1, 10, 199.99),
    (1, 3, 1, 5,  499.00);

-- Order 2: sold Widget A again (warehouse 1) and Widget A (warehouse 2)
INSERT INTO order_items (order_id, product_id, warehouse_id, quantity, unit_price) VALUES
    (2, 1, 1, 8,  199.99),
    (2, 1, 2, 6,  199.99);

-- Order 3: sold Gadget Pro (warehouse 2)
INSERT INTO order_items (order_id, product_id, warehouse_id, quantity, unit_price) VALUES
    (3, 3, 2, 4, 499.00);

-- Order 4 (CANCELLED): sold Widget B – should be EXCLUDED from velocity
INSERT INTO order_items (order_id, product_id, warehouse_id, quantity, unit_price) VALUES
    (4, 2, 1, 100, 149.50);

-- Order 5 (TOO OLD): sold Widget C – should be EXCLUDED from velocity
INSERT INTO order_items (order_id, product_id, warehouse_id, quantity, unit_price) VALUES
    (5, 5, 1, 50, 89.00);

-- ── Expected alert results (for manual verification) ──────────────────────────
-- Widget A / Main Warehouse:   stock=5,  threshold=20, velocity=18/30=0.6 → ~8 days
-- Widget A / North Warehouse:  stock=4,  threshold=20, velocity=6/30=0.2  → ~20 days
-- Gadget Pro / Main Warehouse: stock=3,  threshold=10, velocity=5/30=0.167 → ~18 days
-- Widget C / Main Warehouse:   stock=8,  threshold=25, BUT no recent sales → EXCLUDED
-- Widget B (cancelled order):  stock=50, above threshold → NOT an alert anyway
-- =============================================================================
