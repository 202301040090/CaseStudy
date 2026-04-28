"""
tests/test_alerts.py

Unit + integration tests for GET /api/companies/<id>/alerts/low-stock (Part 3).

Run with:  pytest tests/test_alerts.py -v
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from app import create_app, db
from app.models import Company, Warehouse, Product, Supplier, Inventory, Order, OrderItem
from app.auth import generate_token
from config import TestConfig


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        _seed_alert_data()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_headers_c1(app):
    with app.app_context():
        token = generate_token(user_id=1, company_id=10)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def auth_headers_c2(app):
    with app.app_context():
        token = generate_token(user_id=2, company_id=20)
    return {"Authorization": f"Bearer {token}"}


def _seed_alert_data():
    """
    Creates two companies with controlled inventory and order data.

    Company 10 – Acme:
      Warehouse 100 (active), Warehouse 101 (inactive)
      Products:
        P200 Widget A  – LOW stock (5 < threshold 20), has recent sales  → ALERT
        P201 Gadget B  – LOW stock (3 < threshold 10), has recent sales  → ALERT
        P202 Widget C  – low stock (8 < threshold 25), NO recent sales   → no alert
        P203 Widget D  – OK stock (50 > threshold 20), has recent sales  → no alert
        P204 Widget E  – LOW stock, but in INACTIVE warehouse             → no alert
        P205 Bundle X  – LOW stock (2 < threshold 5), no supplier        → ALERT (null supplier)

    Company 20 – Beta: isolated; should never appear in company 10's alerts
    """
    now = datetime.utcnow()
    recent   = now - timedelta(days=10)
    too_old  = now - timedelta(days=45)

    # Companies
    c1 = Company(id=10, name="Acme",    plan_tier="pro")
    c2 = Company(id=20, name="Beta Co", plan_tier="starter")
    db.session.add_all([c1, c2])

    # Suppliers
    s1 = Supplier(id=50, company_id=10, name="Supplier Corp", contact_email="orders@supplier.com")
    db.session.add(s1)

    # Warehouses
    w100 = Warehouse(id=100, company_id=10, name="Main WH",     is_active=True)
    w101 = Warehouse(id=101, company_id=10, name="Closed WH",   is_active=False)
    w200 = Warehouse(id=200, company_id=20, name="Beta HQ",     is_active=True)
    db.session.add_all([w100, w101, w200])

    # Products
    p200 = Product(id=200, sku="WID-A",  name="Widget A",  price=100, low_stock_threshold=20, supplier_id=50)
    p201 = Product(id=201, sku="GAD-B",  name="Gadget B",  price=200, low_stock_threshold=10, supplier_id=50)
    p202 = Product(id=202, sku="WID-C",  name="Widget C",  price=80,  low_stock_threshold=25, supplier_id=None)
    p203 = Product(id=203, sku="WID-D",  name="Widget D",  price=75,  low_stock_threshold=20, supplier_id=50)
    p204 = Product(id=204, sku="WID-E",  name="Widget E",  price=60,  low_stock_threshold=20, supplier_id=50)
    p205 = Product(id=205, sku="BND-X",  name="Bundle X",  price=250, low_stock_threshold=5,  supplier_id=None, product_type="bundle")
    p_beta = Product(id=300, sku="BETA-1", name="Beta Prod", price=50, low_stock_threshold=10, supplier_id=None)
    db.session.add_all([p200, p201, p202, p203, p204, p205, p_beta])

    # Inventory
    inv_data = [
        (200, 100, 5),    # Widget A  – LOW
        (201, 100, 3),    # Gadget B  – LOW
        (202, 100, 8),    # Widget C  – LOW but no recent sales
        (203, 100, 50),   # Widget D  – OK
        (204, 101, 2),    # Widget E  – LOW but inactive warehouse
        (205, 100, 2),    # Bundle X  – LOW, no supplier
        (300, 200, 1),    # Beta prod – different company
    ]
    for (pid, wid, qty) in inv_data:
        db.session.add(Inventory(product_id=pid, warehouse_id=wid, quantity=qty))

    # Orders & order_items for company 10 (recent)
    o1 = Order(id=1000, company_id=10, status="delivered", created_at=recent)
    o2 = Order(id=1001, company_id=10, status="cancelled", created_at=recent)  # cancelled – excluded
    o3 = Order(id=1002, company_id=10, status="delivered", created_at=too_old)  # too old – excluded
    db.session.add_all([o1, o2, o3])

    # Recent delivered order – Widget A, Gadget B, Bundle X sold (recent sales activity)
    db.session.add_all([
        OrderItem(order_id=1000, product_id=200, warehouse_id=100, quantity=10, unit_price=100),
        OrderItem(order_id=1000, product_id=201, warehouse_id=100, quantity=5,  unit_price=200),
        OrderItem(order_id=1000, product_id=203, warehouse_id=100, quantity=20, unit_price=75),
        OrderItem(order_id=1000, product_id=205, warehouse_id=100, quantity=3,  unit_price=250),
    ])

    # Cancelled order – Widget C (should be excluded)
    db.session.add(OrderItem(order_id=1001, product_id=202, warehouse_id=100, quantity=50, unit_price=80))

    # Old order – Widget C (should be excluded too)
    db.session.add(OrderItem(order_id=1002, product_id=202, warehouse_id=100, quantity=30, unit_price=80))

    db.session.commit()


# ── Tests: Happy path ─────────────────────────────────────────────────────────

class TestLowStockAlertsSuccess:

    def test_returns_200(self, client, auth_headers_c1):
        resp = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c1)
        assert resp.status_code == 200

    def test_response_has_required_keys(self, client, auth_headers_c1):
        data = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c1).get_json()
        assert "alerts" in data
        assert "total_alerts" in data
        assert data["total_alerts"] == len(data["alerts"])

    def test_alert_object_shape(self, client, auth_headers_c1):
        data = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c1).get_json()
        alert = data["alerts"][0]
        required_keys = [
            "product_id", "product_name", "sku",
            "warehouse_id", "warehouse_name",
            "current_stock", "threshold",
            "days_until_stockout", "supplier"
        ]
        for key in required_keys:
            assert key in alert, f"Missing key: {key}"

    def test_widget_a_is_in_alerts(self, client, auth_headers_c1):
        data = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c1).get_json()
        skus = [a["sku"] for a in data["alerts"]]
        assert "WID-A" in skus

    def test_gadget_b_is_in_alerts(self, client, auth_headers_c1):
        data = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c1).get_json()
        skus = [a["sku"] for a in data["alerts"]]
        assert "GAD-B" in skus

    def test_bundle_x_no_supplier_returns_null_supplier(self, client, auth_headers_c1):
        data = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c1).get_json()
        bundle_alerts = [a for a in data["alerts"] if a["sku"] == "BND-X"]
        assert len(bundle_alerts) == 1
        assert bundle_alerts[0]["supplier"] is None

    def test_supplier_info_present_when_exists(self, client, auth_headers_c1):
        data = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c1).get_json()
        widget_a = next(a for a in data["alerts"] if a["sku"] == "WID-A")
        assert widget_a["supplier"] is not None
        assert widget_a["supplier"]["name"] == "Supplier Corp"
        assert widget_a["supplier"]["contact_email"] == "orders@supplier.com"

    def test_current_stock_below_threshold_for_all_alerts(self, client, auth_headers_c1):
        data = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c1).get_json()
        for alert in data["alerts"]:
            assert alert["current_stock"] < alert["threshold"], (
                f"{alert['sku']}: stock={alert['current_stock']} threshold={alert['threshold']}"
            )

    def test_days_until_stockout_is_non_negative_int_or_null(self, client, auth_headers_c1):
        data = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c1).get_json()
        for alert in data["alerts"]:
            d = alert["days_until_stockout"]
            assert d is None or (isinstance(d, int) and d >= 0)


# ── Tests: Exclusion rules ────────────────────────────────────────────────────

class TestLowStockAlertsExclusions:

    def test_widget_c_excluded_no_recent_sales(self, client, auth_headers_c1):
        """Widget C is below threshold but has no recent non-cancelled sales."""
        data = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c1).get_json()
        skus = [a["sku"] for a in data["alerts"]]
        assert "WID-C" not in skus

    def test_widget_d_excluded_stock_ok(self, client, auth_headers_c1):
        """Widget D has recent sales but stock is above threshold."""
        data = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c1).get_json()
        skus = [a["sku"] for a in data["alerts"]]
        assert "WID-D" not in skus

    def test_widget_e_excluded_inactive_warehouse(self, client, auth_headers_c1):
        """Widget E is low stock but lives in an inactive warehouse."""
        data = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c1).get_json()
        skus = [a["sku"] for a in data["alerts"]]
        assert "WID-E" not in skus

    def test_beta_products_not_in_acme_alerts(self, client, auth_headers_c1):
        """Company 20's products must never appear in company 10's alerts."""
        data = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c1).get_json()
        skus = [a["sku"] for a in data["alerts"]]
        assert "BETA-1" not in skus


# ── Tests: Auth & authorisation ───────────────────────────────────────────────

class TestLowStockAlertsAuth:

    def test_no_token_returns_401(self, client):
        resp = client.get("/api/companies/10/alerts/low-stock")
        assert resp.status_code == 401

    def test_wrong_company_returns_403(self, client, auth_headers_c2):
        """User from company 20 cannot access company 10's alerts."""
        resp = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c2)
        assert resp.status_code == 403

    def test_own_company_returns_200(self, client, auth_headers_c2):
        """User from company 20 can access company 20's own alerts."""
        resp = client.get("/api/companies/20/alerts/low-stock", headers=auth_headers_c2)
        assert resp.status_code == 200


# ── Tests: Edge cases ─────────────────────────────────────────────────────────

class TestLowStockAlertsEdgeCases:

    def test_company_with_no_alerts_returns_empty_list(self, client, auth_headers_c2):
        """Company 20 has 1 product above threshold → empty alerts, not 404."""
        data = client.get("/api/companies/20/alerts/low-stock", headers=auth_headers_c2).get_json()
        assert data["alerts"] == []
        assert data["total_alerts"] == 0

    def test_total_alerts_matches_list_length(self, client, auth_headers_c1):
        data = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c1).get_json()
        assert data["total_alerts"] == len(data["alerts"])

    def test_db_error_returns_500(self, client, auth_headers_c1):
        with patch("app.alerts.db") as mock_db:
            mock_db.session.execute.side_effect = Exception("DB down")
            resp = client.get("/api/companies/10/alerts/low-stock", headers=auth_headers_c1)
        assert resp.status_code == 500
        assert resp.get_json()["error"] == "Internal server error"
