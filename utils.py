"""
utils.py – Shared helper utilities.
"""

from decimal import Decimal, InvalidOperation


def parse_decimal(value, field_name: str):
    """
    Safely converts a value to Decimal rounded to 2dp.
    Returns (decimal_value, None) on success or (None, error_message) on failure.
    """
    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"))
        if d < 0:
            return None, f"{field_name} must be >= 0"
        return d, None
    except (InvalidOperation, TypeError):
        return None, f"{field_name} must be a valid number"


def parse_non_negative_int(value, field_name: str):
    """
    Safely converts a value to a non-negative integer.
    Returns (int_value, None) on success or (None, error_message) on failure.
    """
    try:
        i = int(value)
        if i < 0:
            return None, f"{field_name} must be >= 0"
        return i, None
    except (TypeError, ValueError):
        return None, f"{field_name} must be a non-negative integer"
