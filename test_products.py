"""
tests/test_products.py

Unit + integration tests for POST /api/products (Part 1).

Run with:  pytest tests/test_products.py -v
"""

import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from app import create_app, db
from app.models import Product, Inventory, Warehouse, Company
from app.auth import generate_token
from config import TestConfig


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        _seed_test_data()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_headers(app):
    """Returns Authorization headers for company_id=1, user_id=1."""
    with app.app_context():
        token = generate_token(user_id=1, company_id=1)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _seed_test_data():
    company   = Company(id=1, name="Test Co", plan_tier="pro")
    warehouse = Warehouse(id=1, company_id=1, name="Test WH", is_active=True)
    db.session.add_all([company, warehouse])
    db.session.commit()


# ── Helper ────────────────────────────────────────────────────────────────────

def _valid_payload(**overrides):
    base = {
        "name":             "Widget Alpha",
        "sku":              "TEST-001",
        "price":            99.99,
        "warehouse_id":     1,
        "initial_quantity": 50,
    }
    base.update(overrides)
    return base


# ── Tests: Happy path ─────────────────────────────────────────────────────────

class TestCreateProductSuccess:

    def test_returns_201_with_product_id(self, client, auth_headers):
        resp = client.post("/api/products", json=_valid_payload(sku="SUCC-001"), headers=auth_headers)
        assert resp.status_code == 201
        data = resp.get_json()
        assert "product_id" in data
        assert data["message"] == "Product created"

    def test_product_row_persisted(self, client, auth_headers, app):
        client.post("/api/products", json=_valid_payload(sku="SUCC-002"), headers=auth_headers)
        with app.app_context():
            product = Product.query.filter_by(sku="SUCC-002").first()
            assert product is not None
            assert product.name == "Widget Alpha"

    def test_inventory_row_persisted(self, client, auth_headers, app):
        resp = client.post("/api/products", json=_valid_payload(sku="SUCC-003", initial_quantity=42), headers=auth_headers)
        product_id = resp.get_json()["product_id"]
        with app.app_context():
            inv = Inventory.query.filter_by(product_id=product_id, warehouse_id=1).first()
            assert inv is not None
            assert inv.quantity == 42

    def test_price_stored_as_decimal(self, client, auth_headers, app):
        resp = client.post("/api/products", json=_valid_payload(sku="DEC-001", price=9.99), headers=auth_headers)
        product_id = resp.get_json()["product_id"]
        with app.app_context():
            product = Product.query.get(product_id)
            assert product.price == Decimal("9.99")

    def test_sku_normalised_to_uppercase(self, client, auth_headers, app):
        resp = client.post("/api/products", json=_valid_payload(sku="lower-case-001"), headers=auth_headers)
        product_id = resp.get_json()["product_id"]
        with app.app_context():
            product = Product.query.get(product_id)
            assert product.sku == "LOWER-CASE-001"

    def test_optional_fields_accepted(self, client, auth_headers):
        payload = _valid_payload(
            sku="OPT-001",
            description="A test product",
            product_type="standard",
            low_stock_threshold=10,
        )
        resp = client.post("/api/products", json=payload, headers=auth_headers)
        assert resp.status_code == 201

    def test_zero_initial_quantity_allowed(self, client, auth_headers):
        resp = client.post("/api/products", json=_valid_payload(sku="ZERO-001", initial_quantity=0), headers=auth_headers)
        assert resp.status_code == 201


# ── Tests: Validation failures ────────────────────────────────────────────────

class TestCreateProductValidation:

    @pytest.mark.parametrize("missing_field", [
        "name", "sku", "price", "warehouse_id", "initial_quantity"
    ])
    def test_missing_required_field_returns_400(self, client, auth_headers, missing_field):
        payload = _valid_payload(sku=f"MISS-{missing_field[:3].upper()}")
        del payload[missing_field]
        resp = client.post("/api/products", json=payload, headers=auth_headers)
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_invalid_price_string_returns_400(self, client, auth_headers):
        resp = client.post("/api/products", json=_valid_payload(sku="BADP-001", price="not_a_number"), headers=auth_headers)
        assert resp.status_code == 400

    def test_negative_price_returns_400(self, client, auth_headers):
        resp = client.post("/api/products", json=_valid_payload(sku="NEGP-001", price=-1), headers=auth_headers)
        assert resp.status_code == 400

    def test_negative_quantity_returns_400(self, client, auth_headers):
        resp = client.post("/api/products", json=_valid_payload(sku="NEGQ-001", initial_quantity=-5), headers=auth_headers)
        assert resp.status_code == 400

    def test_non_integer_quantity_returns_400(self, client, auth_headers):
        resp = client.post("/api/products", json=_valid_payload(sku="STRQ-001", initial_quantity="lots"), headers=auth_headers)
        assert resp.status_code == 400

    def test_empty_body_returns_400(self, client, auth_headers):
        resp = client.post("/api/products", data="not json", headers=auth_headers)
        assert resp.status_code == 400

    def test_duplicate_sku_returns_409(self, client, auth_headers):
        payload = _valid_payload(sku="DUP-001")
        client.post("/api/products", json=payload, headers=auth_headers)
        resp = client.post("/api/products", json=payload, headers=auth_headers)
        assert resp.status_code == 409
        assert "already exists" in resp.get_json()["error"]


# ── Tests: Auth & authorisation ───────────────────────────────────────────────

class TestCreateProductAuth:

    def test_no_token_returns_401(self, client):
        resp = client.post("/api/products", json=_valid_payload(sku="NOAUTH-001"))
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client):
        resp = client.post(
            "/api/products",
            json=_valid_payload(sku="BADTOK-001"),
            headers={"Authorization": "Bearer this.is.invalid"}
        )
        assert resp.status_code == 401

    def test_wrong_company_warehouse_returns_404(self, client, app):
        """User from company 2 cannot use company 1's warehouse."""
        with app.app_context():
            token = generate_token(user_id=99, company_id=2)
        resp = client.post(
            "/api/products",
            json=_valid_payload(sku="CROSS-001", warehouse_id=1),  # warehouse belongs to company 1
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
        assert resp.status_code == 404


# ── Tests: Atomicity ──────────────────────────────────────────────────────────

class TestCreateProductAtomicity:

    def test_no_orphaned_product_on_inventory_failure(self, client, auth_headers, app):
        """
        Simulates a crash during inventory creation.
        The product row should NOT be persisted (rollback).
        """
        sku = "ATOM-001"

        with patch("app.products.Inventory") as mock_inv:
            mock_inv.side_effect = Exception("Simulated DB crash")
            resp = client.post("/api/products", json=_valid_payload(sku=sku), headers=auth_headers)

        assert resp.status_code == 500
        with app.app_context():
            # Rollback must have removed the product row
            assert Product.query.filter_by(sku=sku).first() is None
