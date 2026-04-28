"""
alerts.py – Part 3: Low-Stock Alerts endpoint.

GET /api/companies/<company_id>/alerts/low-stock

Business rules implemented:
  - "Low stock" means inventory.quantity < products.low_stock_threshold
  - Only products with at least one sale in the last 30 days are included
    (configurable via LOW_STOCK_SALES_WINDOW_DAYS in config)
  - Handles multiple warehouses per company (one alert row per product+warehouse pair)
  - Includes supplier info for reordering
  - days_until_stockout = floor(current_stock / avg_daily_sales); None if no velocity

Assumptions documented:
  - "Recent sales activity" = orders.created_at within the last 30 days
  - Cancelled orders are excluded from velocity calculation
  - days_until_stockout is NULL (not 0) when there are 0 recent sales
  - Only active products in active warehouses are surfaced
  - Alerts are ordered by days_until_stockout ASC (most urgent first)
"""

import logging
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, g, current_app
from sqlalchemy import text

from app import db
from app.auth import login_required

logger = logging.getLogger(__name__)

alerts_bp = Blueprint("alerts", __name__)


# ── SQL query ─────────────────────────────────────────────────────────────────
# Uses a CTE to compute sales velocity per (product, warehouse) over the
# configurable window, then joins to inventory + product + supplier.
# A single round-trip avoids N+1 queries even for thousands of SKUs.

LOW_STOCK_QUERY = text("""
    WITH recent_sales AS (
        -- Aggregate units sold per (product, warehouse) over the sales window.
        -- HAVING > 0 filters out products with no recent activity.
        SELECT
            oi.product_id,
            oi.warehouse_id,
            SUM(oi.quantity)::FLOAT                          AS total_sold,
            SUM(oi.quantity)::FLOAT / :window_days           AS daily_velocity
        FROM order_items  oi
        JOIN orders        o  ON o.id = oi.order_id
        WHERE o.company_id  = :company_id
          AND o.created_at >= :cutoff
          AND o.status     != 'cancelled'
        GROUP BY oi.product_id, oi.warehouse_id
        HAVING SUM(oi.quantity) > 0
    )
    SELECT
        p.id                        AS product_id,
        p.name                      AS product_name,
        p.sku,
        w.id                        AS warehouse_id,
        w.name                      AS warehouse_name,
        inv.quantity                AS current_stock,
        p.low_stock_threshold       AS threshold,
        -- days_until_stockout: NULL when daily_velocity = 0 (avoids division by zero)
        CASE
            WHEN rs.daily_velocity > 0
            THEN FLOOR(inv.quantity / rs.daily_velocity)::INT
            ELSE NULL
        END                         AS days_until_stockout,
        s.id                        AS supplier_id,
        s.name                      AS supplier_name,
        s.contact_email             AS supplier_email
    FROM inventory      inv
    JOIN products        p   ON p.id  = inv.product_id
    JOIN warehouses      w   ON w.id  = inv.warehouse_id
    JOIN recent_sales    rs  ON rs.product_id   = inv.product_id
                             AND rs.warehouse_id = inv.warehouse_id
    LEFT JOIN suppliers  s   ON s.id = p.supplier_id
    WHERE w.company_id        = :company_id
      AND w.is_active         = TRUE
      AND p.is_active         = TRUE
      AND inv.quantity        < p.low_stock_threshold
    ORDER BY days_until_stockout ASC NULLS LAST
""")


@alerts_bp.route("/api/companies/<int:company_id>/alerts/low-stock", methods=["GET"])
@login_required
def low_stock_alerts(company_id: int):
    """
    Returns low-stock alerts for a company.

    Path param:
        company_id   int   – company to fetch alerts for

    Returns:
        200  { alerts: [...], total_alerts: int }
        403  { error }  – caller does not belong to this company
        500  { error }  – unexpected server error

    Alert object:
        product_id          int
        product_name        str
        sku                 str
        warehouse_id        int
        warehouse_name      str
        current_stock       int
        threshold           int
        days_until_stockout int | null
        supplier            { id, name, contact_email } | null
    """

    # ── 1. Authorisation ─────────────────────────────────────────────────────
    # Users may only query their own company's alerts.
    if g.current_user.company_id != company_id:
        return jsonify({"error": "Forbidden: you do not belong to this company"}), 403

    # ── 2. Build query parameters ─────────────────────────────────────────────
    window_days = current_app.config.get("LOW_STOCK_SALES_WINDOW_DAYS", 30)
    cutoff      = datetime.utcnow() - timedelta(days=window_days)

    params = {
        "company_id":  company_id,
        "cutoff":      cutoff,
        "window_days": window_days,
    }

    # ── 3. Execute query ──────────────────────────────────────────────────────
    try:
        rows = db.session.execute(LOW_STOCK_QUERY, params).fetchall()
    except Exception as exc:
        logger.error(
            "low_stock_alerts DB error for company=%s: %s", company_id, exc, exc_info=True
        )
        return jsonify({"error": "Internal server error"}), 500

    # ── 4. Serialise results ──────────────────────────────────────────────────
    alerts = []
    for row in rows:
        alert = {
            "product_id":          row.product_id,
            "product_name":        row.product_name,
            "sku":                 row.sku,
            "warehouse_id":        row.warehouse_id,
            "warehouse_name":      row.warehouse_name,
            "current_stock":       row.current_stock,
            "threshold":           row.threshold,
            "days_until_stockout": row.days_until_stockout,  # None = no sales data
            "supplier": {
                "id":            row.supplier_id,
                "name":          row.supplier_name,
                "contact_email": row.supplier_email,
            } if row.supplier_id else None,
        }
        alerts.append(alert)

    logger.info(
        "low_stock_alerts: company=%s returned %d alerts (window=%d days)",
        company_id, len(alerts), window_days,
    )

    # Always return 200 with an empty list when no alerts exist (not a 404)
    return jsonify({"alerts": alerts, "total_alerts": len(alerts)}), 200
