"""Tests for lightweight parsing and model behavior."""

from app.models import RouteComputationOptions
from app.value_parsing import coerce_float

DEFAULT_INTEGER = 0


def test_coerce_float_handles_valid_and_invalid_values() -> None:
    """coerce_float should parse numbers and fallback to default for invalid inputs."""
    assert coerce_float("1.5") == 1.5
    assert coerce_float(2) == 2.0
    assert coerce_float("bad", default=3.0) == 3.0
    assert coerce_float(None, default=4.0) == 4.0


def test_route_option_defaults_use_shortest_method() -> None:
    """Default options should use the shortest-path method."""
    options = RouteComputationOptions()

    assert options.route_selection_method == "shortest"
    assert options.objective_weights.scenic == DEFAULT_INTEGER
