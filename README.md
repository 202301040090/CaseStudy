# StockFlow – B2B Inventory Management API

Engineering case study solution built with **Python / Flask + PostgreSQL**.

## Project Structure

```
stockflow/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── models.py            # SQLAlchemy ORM models
│   ├── auth.py              # JWT auth decorator
│   ├── products.py          # Part 1 – create product endpoint (fixed)
│   ├── alerts.py            # Part 3 – low-stock alerts endpoint
│   └── utils.py             # Shared helpers
├── migrations/
│   ├── 001_schema.sql       # Part 2 – full DDL (tables, indexes, constraints)
│   └── 002_seed.sql         # Sample data for testing
├── tests/
│   ├── test_products.py     # Unit + integration tests for Part 1
│   └── test_alerts.py       # Unit + integration tests for Part 3
├── requirements.txt
├── config.py
└── run.py
```

## Setup

```bash
# 1. Clone & create virtualenv
git clone <your-repo-url>
cd stockflow
python -m venv venv && source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create PostgreSQL database
createdb stockflow_db

# 4. Run migrations
psql stockflow_db < migrations/001_schema.sql
psql stockflow_db < migrations/002_seed.sql

# 5. Configure environment
cp .env.example .env   # edit DATABASE_URL and SECRET_KEY

# 6. Run the app
python run.py
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/products` | Create a product (Part 1) |
| GET | `/api/companies/<id>/alerts/low-stock` | Low-stock alerts (Part 3) |

## Running Tests

```bash
pytest tests/ -v
```
