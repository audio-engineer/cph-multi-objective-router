"""Tests for geocoding helpers and main module endpoint wrappers."""

import geopandas as gpd
import pytest
from fastapi import HTTPException
from shapely.geometry import MultiPolygon, Polygon

from app.geocoding import reverse_geocode_to_address
from app.graph_state import GRAPH_STATE
from app.main import (
    build_address_route_request_from_params,
    build_coordinate_route_request_from_params,
    build_pareto_search_limits,
    build_route_planning_options,
    build_route_preference_weights,
    compute_route_by_address,
    compute_route_by_coordinates,
    get_current_boundary,
    list_overlay_features,
    reverse_geocode,
)
from app.models import (
    OverlayFeatureCollection,
    ReverseGeocodeResponse,
    RouteCoordinates,
    RouteFeatureCollection,
    RoutePlanningOptions,
)


class _FakeResponse:
    """Simple fake response object for mocking requests.get."""

    _payload: object

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        """Mimic successful HTTP status."""

    def json(self) -> object:
        """Return predefined payload."""
        return self._payload


def test_reverse_geocode_address_formats_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reverse geocode helper should build road + house number string."""

    def fake_get(*_args: object, **_kwargs: object) -> _FakeResponse:
        return _FakeResponse({"address": {"road": "Test Road", "house_number": "5"}})

    monkeypatch.setattr(
        "app.geocoding.requests.get",
        fake_get,
    )

    response = reverse_geocode_to_address(12.0, 55.0)

    assert response.address == "Test Road 5"


def test_reverse_geocode_address_returns_empty_for_unexpected_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected payload types should produce an empty address string."""

    def fake_get(*_args: object, **_kwargs: object) -> _FakeResponse:
        return _FakeResponse(["unexpected"])

    monkeypatch.setattr(
        "app.geocoding.requests.get",
        fake_get,
    )

    response = reverse_geocode_to_address(12.0, 55.0)

    assert response.address == ""


def test_main_route_helper_builds_from_addresses(
    monkeypatch: pytest.MonkeyPatch,
    dummy_route_feature_collection: RouteFeatureCollection,
) -> None:
    """Address route helper should geocode and delegate to route builder."""

    def fake_geocode(_address: str) -> tuple[float, float]:
        return 55.0, 12.0

    def fake_route_builder(**_kwargs: object) -> RouteFeatureCollection:
        return dummy_route_feature_collection

    monkeypatch.setattr("app.main.ox.geocode", fake_geocode)
    monkeypatch.setattr(
        "app.main.build_route_feature_collection",
        fake_route_builder,
    )

    request = build_address_route_request_from_params(
        travel_mode="cycling",
        origin="A",
        destination="B",
        route_options=RoutePlanningOptions(),
    )

    result = compute_route_by_address(request)

    assert result is dummy_route_feature_collection


def test_main_coordinate_route_helper_delegates(
    monkeypatch: pytest.MonkeyPatch,
    dummy_route_feature_collection: RouteFeatureCollection,
) -> None:
    """Coordinate route helper should transform coordinates and delegate."""

    def fake_route_builder(**_kwargs: object) -> RouteFeatureCollection:
        return dummy_route_feature_collection

    monkeypatch.setattr(
        "app.main.build_route_feature_collection",
        fake_route_builder,
    )

    request = build_coordinate_route_request_from_params(
        travel_mode="walking",
        route_coordinates=RouteCoordinates(12.0, 55.0, 12.1, 55.1),
        route_options=RoutePlanningOptions(),
    )

    result = compute_route_by_coordinates(request)

    assert result is dummy_route_feature_collection


def test_list_layers_and_boundary_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Endpoint wrappers should call service helpers and return their output."""
    geodataframe = gpd.GeoDataFrame(
        {"geometry": []}, geometry="geometry", crs="EPSG:4326"
    )
    empty_collection = OverlayFeatureCollection(type="FeatureCollection", features=[])

    def fake_get_edges_for_mode(
        _state: object,
        _mode: str,
    ) -> gpd.GeoDataFrame:
        return geodataframe

    def fake_build_layer_feature_collection(
        *_args: object,
        **_kwargs: object,
    ) -> OverlayFeatureCollection:
        return empty_collection

    monkeypatch.setattr(
        "app.main.get_edge_geodataframe_for_travel_mode",
        fake_get_edges_for_mode,
    )
    monkeypatch.setattr(
        "app.main.build_overlay_feature_collection",
        fake_build_layer_feature_collection,
    )

    layers = list_overlay_features("snow", "cycling")

    assert layers is empty_collection

    GRAPH_STATE.boundary_geometry = MultiPolygon(
        [Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])]
    )
    boundary = get_current_boundary()
    assert boundary.features[0].properties.name == "Copenhagen Municipality"


def test_get_current_boundary_raises_when_not_loaded() -> None:
    """Boundary endpoint should fail if startup resources were not loaded."""
    GRAPH_STATE.boundary_geometry = None

    with pytest.raises(HTTPException):
        _ = get_current_boundary()


def test_reverse_geocode_endpoint_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    """Main reverse endpoint should delegate directly to geocoding helper."""

    def fake_reverse_geocode_address(
        longitude: float,
        latitude: float,
        zoom_level: int = 18,
    ) -> ReverseGeocodeResponse:
        return ReverseGeocodeResponse(address=f"{longitude},{latitude},{zoom_level}")

    monkeypatch.setattr(
        "app.main.reverse_geocode_to_address",
        fake_reverse_geocode_address,
    )

    response = reverse_geocode(12.0, 55.0, 17)

    assert response.address == "12.0,55.0,17"


def test_build_route_computation_options_from_query_values() -> None:
    """Query-param option helper should construct nested routing options."""
    route_options = build_route_planning_options(
        route_optimization_method="pareto",
        route_preference_weights=build_route_preference_weights(
            scenic_weight=10,
            snow_free_weight=20,
            flat_weight=30,
        ),
        pareto_search_limits=build_pareto_search_limits(
            pareto_max_routes=3,
            pareto_max_labels_per_node=25,
            pareto_max_total_labels=12_000,
        ),
    )

    assert route_options.route_optimization_method == "pareto"
    assert route_options.preference_weights.scenic_weight == 10
    assert route_options.preference_weights.snow_free_weight == 20
    assert route_options.preference_weights.flat_weight == 30
    assert route_options.pareto_max_routes == 3


def test_address_route_helper_surfaces_geocoding_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Address route helper should map geocoding exceptions to HTTP 400."""

    def failing_geocode(_value: str) -> tuple[float, float]:
        raise RuntimeError("failed")

    monkeypatch.setattr("app.main.ox.geocode", failing_geocode)
    request = build_address_route_request_from_params(
        travel_mode="cycling",
        origin="A",
        destination="B",
        route_options=RoutePlanningOptions(),
    )

    with pytest.raises(HTTPException):
        _ = compute_route_by_address(request)
