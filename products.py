"""
products.py – Part 1 (Fixed): Create Product endpoint.

Original bugs fixed:
  1. No input validation          → validate all required fields + types; 400 on failure
  2. No error handling            → try/except with rollback; 500 with safe message
  3. SKU uniqueness not enforced  → explicit check before insert; 409 Conflict
  4. Float price rounding errors  → use Python Decimal, stored as NUMERIC(10,2)
  5. No authentication            → @login_required decorator; warehouse ownership check
  6. Two separate commits         → db.session.flush() + single commit covers both rows
"""

import logging
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify, g

from app import db
from app.auth import login_required
from app.models import Product, Inventory, Warehouse

logger = logging.getLogger(__name__)

products_bp = Blueprint("products", __name__)


@products_bp.route("/api/products", methods=["POST"])
@login_required
def create_product():
    """
    POST /api/products

    Request body (JSON):
        name             str   required
        sku              str   required  – must be unique across the platform
        price            num   required  – stored as NUMERIC(10,2)
        warehouse_id     int   required  – must belong to the caller's company
        initial_quantity int   required  – non-negative integer

    Optional:
        description         str
        product_type        str  ('standard' | 'bundle'), default 'standard'
        low_stock_threshold int  default 20
        supplier_id         int

    Returns:
        201  { message, product_id }
        400  { error }   – missing / invalid fields
        401  { error }   – not authenticated
        403  { error }   – warehouse belongs to another company
        404  { error }   – warehouse not found
        409  { error }   – SKU already exists
        500  { error }   – unexpected server error
    """

    # ── 1. Parse JSON body ────────────────────────────────────────────────────
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    # ── 2. Required field presence check ─────────────────────────────────────
    required_fields = ["name", "sku", "price", "warehouse_id", "initial_quantity"]
    missing = [f for f in required_fields if f not in data or data[f] is None]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    # ── 3. Type validation ────────────────────────────────────────────────────
    # Price: use Decimal to avoid floating-point rounding (e.g. 9.99 != 9.990000001)
    try:
        price = Decimal(str(data["price"])).quantize(Decimal("0.01"))
        if price < 0:
            raise ValueError("price must be >= 0")
    except (InvalidOperation, ValueError) as exc:
        return jsonify({"error": f"Invalid price: {exc}"}), 400

    # initial_quantity: non-negative integer
    try:
        initial_quantity = int(data["initial_quantity"])
        if initial_quantity < 0:
            raise ValueError("initial_quantity must be >= 0")
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"Invalid initial_quantity: {exc}"}), 400

    # warehouse_id: integer
    try:
        warehouse_id = int(data["warehouse_id"])
    except (TypeError, ValueError):
        return jsonify({"error": "warehouse_id must be an integer"}), 400

    # Optional low_stock_threshold
    low_stock_threshold = 20
    if "low_stock_threshold" in data:
        try:
            low_stock_threshold = int(data["low_stock_threshold"])
            if low_stock_threshold < 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "low_stock_threshold must be a non-negative integer"}), 400

    # Normalise SKU: strip whitespace, uppercase
    sku = str(data["sku"]).strip().upper()
    if not sku:
        return jsonify({"error": "sku cannot be blank"}), 400

    name = str(data["name"]).strip()
    if not name:
        return jsonify({"error": "name cannot be blank"}), 400

    # ── 4. SKU uniqueness check ───────────────────────────────────────────────
    # Checked in application layer for a clear 409 response.
    # The DB UNIQUE constraint is the final safety net.
    if Product.query.filter_by(sku=sku).first():
        return jsonify({"error": f'SKU "{sku}" already exists on the platform'}), 409

    # ── 5. Warehouse ownership check ─────────────────────────────────────────
    # Ensures callers can only create products in their own company's warehouses.
    warehouse = Warehouse.query.filter_by(
        id=warehouse_id,
        company_id=g.current_user.company_id,
    ).first()

    if not warehouse:
        # Deliberately ambiguous: don't reveal whether the warehouse exists at all
        return jsonify({"error": "Warehouse not found or access denied"}), 404

    if not warehouse.is_active:
        return jsonify({"error": "Cannot add products to an inactive warehouse"}), 400

    # ── 6. Single atomic transaction ─────────────────────────────────────────
    # flush() writes the Product row and populates product.id WITHOUT committing.
    # Both the Product and Inventory are committed together, so a crash between
    # the two original commits can never leave an orphaned Product row.
    try:
        product = Product(
            name=name,
            sku=sku,
            price=price,                    # Decimal → NUMERIC(10,2) in DB
            description=data.get("description"),
            product_type=data.get("product_type", "standard"),
            low_stock_threshold=low_stock_threshold,
            supplier_id=data.get("supplier_id"),
        )
        db.session.add(product)
        db.session.flush()                  # assigns product.id

        inventory = Inventory(
            product_id=product.id,
            warehouse_id=warehouse_id,
            quantity=initial_quantity,
        )
        db.session.add(inventory)
        db.session.commit()                 # single commit – atomic

        logger.info(
            "Product created: id=%s sku=%s warehouse=%s by user=%s",
            product.id, sku, warehouse_id, g.current_user.id,
        )
        return jsonify({"message": "Product created", "product_id": product.id}), 201

    except Exception as exc:
        db.session.rollback()
        logger.error("create_product failed: %s", exc, exc_info=True)
        # Never surface raw DB errors to the client
        return jsonify({"error": "Internal server error"}), 500
