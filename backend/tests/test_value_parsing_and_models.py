"""Tests for lightweight parsing and model behavior."""

from app.models import RoutePlanningOptions
from app.value_parsing import parse_float_or_default

DEFAULT_INTEGER = 0


def test_coerce_float_handles_valid_and_invalid_values() -> None:
    """coerce_float should parse numbers and fallback to default for invalid inputs."""
    assert parse_float_or_default("1.5") == 1.5
    assert parse_float_or_default(2) == 2.0
    assert parse_float_or_default("bad", default=3.0) == 3.0
    assert parse_float_or_default(None, default=4.0) == 4.0


def test_route_option_defaults_use_shortest_method() -> None:
    """Default options should use the shortest-path method."""
    options = RoutePlanningOptions()

    assert options.route_optimization_method == "shortest"
    assert options.preference_weights.scenic_weight == DEFAULT_INTEGER
