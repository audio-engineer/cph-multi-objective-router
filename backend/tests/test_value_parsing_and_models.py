"""Tests for lightweight parsing and model behavior."""

from app.models import (
    AddressRouteRequest,
    CoordinateRouteRequest,
    LayerProperties,
    RouteComputationOptions,
)
from app.value_parsing import coerce_float

DEFAULT_INTEGER = 0


def test_coerce_float_handles_valid_and_invalid_values() -> None:
    """coerce_float should parse numbers and fallback to default for invalid inputs."""
    assert coerce_float("1.5") == 1.5
    assert coerce_float(2) == 2.0
    assert coerce_float("bad", default=3.0) == 3.0
    assert coerce_float(None, default=4.0) == 4.0


def test_route_computation_options_accept_legacy_aliases() -> None:
    """Route options should parse both modern and legacy field names."""
    options = RouteComputationOptions.model_validate(
        {
            "route_method": "weighted",
            "weights": {
                "scenic": 10,
                "avoid_snow": 20,
                "avoid_uphill": 30,
            },
        }
    )

    assert options.route_selection_method == "weighted"
    assert options.objective_weights.scenic == 10
    assert options.objective_weights.avoid_snow == 20
    assert options.objective_weights.avoid_uphill == 30


def test_route_request_models_accept_new_and_legacy_fields() -> None:
    """Address and coordinate request models should accept both input schemas."""
    address_request = AddressRouteRequest.model_validate(
        {
            "travel_mode": "bike",
            "from": "A Street 1",
            "to": "B Street 2",
            "options": {},
        }
    )

    assert address_request.transport_mode == "bike"
    assert address_request.origin == "A Street 1"
    assert address_request.destination == "B Street 2"

    coordinate_request = CoordinateRouteRequest.model_validate(
        {
            "transport_mode": "walk",
            "start": {"type": "Point", "coordinates": [12.0, 55.0]},
            "end": {"type": "Point", "coordinates": [12.1, 55.1]},
            "route_options": {},
        }
    )

    assert coordinate_request.transport_mode == "walk"
    assert coordinate_request.route_options.route_selection_method == "shortest"


def test_layer_properties_accepts_legacy_attribute_name() -> None:
    """Layer properties should support `attribute` as a backward-compatible alias."""
    properties = LayerProperties.model_validate({"attribute": "snow", "value": 0.7})

    assert properties.overlay_attribute == "snow"
    assert properties.value == 0.7


def test_route_option_defaults_use_shortest_method() -> None:
    """Default options should use the shortest-path method."""
    options = RouteComputationOptions()

    assert options.route_selection_method == "shortest"
    assert options.objective_weights.scenic == DEFAULT_INTEGER
