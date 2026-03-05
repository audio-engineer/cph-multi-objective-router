"""Shared parsing helpers."""

from typing import cast


def coerce_float(value: object, *, default: float = 0.0) -> float:
    """Coerce values to float with a safe default."""
    try:
        numeric_value = cast("str | int | float", value)

        return float(numeric_value)
    except (TypeError, ValueError):
        return default
