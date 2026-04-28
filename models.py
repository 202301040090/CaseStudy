"""
models.py – SQLAlchemy ORM models for StockFlow.

Mirrors the schema defined in migrations/001_schema.sql.
"""

from datetime import datetime
from decimal import Decimal
from app import db


class Company(db.Model):
    __tablename__ = "companies"

    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(255), nullable=False)
    plan_tier  = db.Column(db.String(50), nullable=False, default="starter")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    warehouses = db.relationship("Warehouse", back_populates="company", lazy="dynamic")
    orders     = db.relationship("Order",     back_populates="company", lazy="dynamic")
    suppliers  = db.relationship("Supplier",  back_populates="company", lazy="dynamic")

    def __repr__(self):
        return f"<Company id={self.id} name={self.name!r}>"


class Warehouse(db.Model):
    __tablename__ = "warehouses"

    id         = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    name       = db.Column(db.String(255), nullable=False)
    location   = db.Column(db.Text)
    is_active  = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    company    = db.relationship("Company",   back_populates="warehouses")
    inventory  = db.relationship("Inventory", back_populates="warehouse", lazy="dynamic")

    def __repr__(self):
        return f"<Warehouse id={self.id} name={self.name!r}>"


class Supplier(db.Model):
    __tablename__ = "suppliers"

    id              = db.Column(db.Integer, primary_key=True)
    company_id      = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    name            = db.Column(db.String(255), nullable=False)
    contact_email   = db.Column(db.String(255))
    contact_phone   = db.Column(db.String(50))
    lead_time_days  = db.Column(db.Integer)
    created_at      = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    company  = db.relationship("Company",  back_populates="suppliers")
    products = db.relationship("Product",  back_populates="supplier", lazy="dynamic")

    def __repr__(self):
        return f"<Supplier id={self.id} name={self.name!r}>"


class Product(db.Model):
    __tablename__ = "products"

    id                  = db.Column(db.Integer, primary_key=True)
    sku                 = db.Column(db.String(100), nullable=False, unique=True, index=True)
    name                = db.Column(db.String(255), nullable=False)
    description         = db.Column(db.Text)
    price               = db.Column(db.Numeric(10, 2), nullable=False)
    product_type        = db.Column(db.String(50), nullable=False, default="standard")  # standard | bundle
    low_stock_threshold = db.Column(db.Integer, nullable=False, default=20)
    supplier_id         = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    is_active           = db.Column(db.Boolean, nullable=False, default=True)
    created_at          = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    supplier    = db.relationship("Supplier",    back_populates="products")
    inventory   = db.relationship("Inventory",   back_populates="product",  lazy="dynamic")
    bundle_items = db.relationship(
        "BundleItem", foreign_keys="BundleItem.bundle_id",
        back_populates="bundle", lazy="dynamic"
    )

    def __repr__(self):
        return f"<Product id={self.id} sku={self.sku!r}>"


class BundleItem(db.Model):
    """Links a bundle product to its component products."""
    __tablename__ = "bundle_items"
    __table_args__ = (db.UniqueConstraint("bundle_id", "component_id"),)

    id           = db.Column(db.Integer, primary_key=True)
    bundle_id    = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    component_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    quantity     = db.Column(db.Integer, nullable=False, default=1)

    bundle    = db.relationship("Product", foreign_keys=[bundle_id],    back_populates="bundle_items")
    component = db.relationship("Product", foreign_keys=[component_id])

    def __repr__(self):
        return f"<BundleItem bundle={self.bundle_id} component={self.component_id} qty={self.quantity}>"


class Inventory(db.Model):
    __tablename__ = "inventory"
    __table_args__ = (db.UniqueConstraint("product_id", "warehouse_id"),)

    id           = db.Column(db.Integer, primary_key=True)
    product_id   = db.Column(db.Integer, db.ForeignKey("products.id",   ondelete="CASCADE"), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity     = db.Column(db.Integer, nullable=False, default=0)
    updated_at   = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    product   = db.relationship("Product",   back_populates="inventory")
    warehouse = db.relationship("Warehouse", back_populates="inventory")
    movements = db.relationship("InventoryMovement", back_populates="inventory", lazy="dynamic")

    def __repr__(self):
        return f"<Inventory product={self.product_id} warehouse={self.warehouse_id} qty={self.quantity}>"


class InventoryMovement(db.Model):
    """Audit trail for every stock change."""
    __tablename__ = "inventory_movements"

    id           = db.Column(db.Integer, primary_key=True)
    inventory_id = db.Column(db.Integer, db.ForeignKey("inventory.id", ondelete="CASCADE"), nullable=False)
    change_qty   = db.Column(db.Integer, nullable=False)          # positive = in, negative = out
    reason       = db.Column(db.String(100))                      # sale | purchase | adjustment | transfer
    reference_id = db.Column(db.Integer)                          # order_id, po_id, etc.
    created_by   = db.Column(db.Integer)                          # user_id (FK omitted for brevity)
    created_at   = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)

    inventory = db.relationship("Inventory", back_populates="movements")

    def __repr__(self):
        return f"<InventoryMovement inv={self.inventory_id} change={self.change_qty} reason={self.reason!r}>"


class Order(db.Model):
    __tablename__ = "orders"

    id         = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    status     = db.Column(db.String(50), nullable=False, default="pending")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)

    company = db.relationship("Company", back_populates="orders")
    items   = db.relationship("OrderItem", back_populates="order", lazy="dynamic")

    def __repr__(self):
        return f"<Order id={self.id} company={self.company_id} status={self.status!r}>"


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id           = db.Column(db.Integer, primary_key=True)
    order_id     = db.Column(db.Integer, db.ForeignKey("orders.id",    ondelete="CASCADE"), nullable=False, index=True)
    product_id   = db.Column(db.Integer, db.ForeignKey("products.id"),  nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"), nullable=False)
    quantity     = db.Column(db.Integer, nullable=False)
    unit_price   = db.Column(db.Numeric(10, 2), nullable=False)

    order     = db.relationship("Order",     back_populates="items")
    product   = db.relationship("Product")
    warehouse = db.relationship("Warehouse")

    def __repr__(self):
        return f"<OrderItem order={self.order_id} product={self.product_id} qty={self.quantity}>"
