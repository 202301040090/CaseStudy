from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def create_app(config_object=None):
    """Application factory."""
    app = Flask(__name__)

    # Load config
    if config_object:
        app.config.from_object(config_object)
    else:
        from config import Config
        app.config.from_object(Config)

    # Init extensions
    db.init_app(app)

    # Register blueprints
    from app.products import products_bp
    from app.alerts import alerts_bp

    app.register_blueprint(products_bp)
    app.register_blueprint(alerts_bp)

    return app
