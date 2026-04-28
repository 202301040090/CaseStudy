"""
auth.py – JWT authentication decorator for StockFlow.

Usage:
    @app.route('/api/...')
    @login_required
    def my_view():
        user = g.current_user   # namedtuple with .id and .company_id
        ...
"""

import jwt
import logging
from functools import wraps
from collections import namedtuple

from flask import request, jsonify, g, current_app

logger = logging.getLogger(__name__)

# Lightweight user context attached to Flask's g object
AuthUser = namedtuple("AuthUser", ["id", "company_id"])


def login_required(f):
    """
    Validates a Bearer JWT token from the Authorization header.
    On success, sets g.current_user = AuthUser(id, company_id).
    Returns 401 if the token is missing, invalid, or expired.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Authorization header missing or malformed"}), 401

        token = auth_header.split(" ", 1)[1]

        try:
            payload = jwt.decode(
                token,
                current_app.config["SECRET_KEY"],
                algorithms=["HS256"],
            )
            g.current_user = AuthUser(
                id=payload["user_id"],
                company_id=payload["company_id"],
            )
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError as exc:
            logger.warning("Invalid JWT: %s", exc)
            return jsonify({"error": "Invalid token"}), 401

        return f(*args, **kwargs)

    return wrapper


def generate_token(user_id: int, company_id: int) -> str:
    """
    Helper for tests / dev: generates a signed JWT.
    In production, tokens are issued by a dedicated auth service.
    """
    import datetime
    payload = {
        "user_id":    user_id,
        "company_id": company_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")
