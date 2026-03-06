"""Tests for geocoding helpers and main module endpoint wrappers."""

import geopandas as gpd
import pytest
from fastapi import HTTPException
from shapely.geometry import MultiPolygon, Polygon

from app.geocoding import reverse_geocode_address
from app.graph_state import GRAPH_STATE
from app.main import (
    create_route_from_address,
    create_route_from_coordinates,
    get_current_boundary,
    list_layers,
    reverse_geocode,
)
from app.models import (
    AddressRouteRequest,
    CoordinateRouteRequest,
    LayerFeatureCollection,
    ReverseGeocodeResponse,
    RouteComputationOptions,
    RouteFeatureCollection,
)


class _FakeResponse:
    """Simple fake response object for mocking requests.get."""

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

    response = reverse_geocode_address(12.0, 55.0)

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

    response = reverse_geocode_address(12.0, 55.0)

    assert response.address == ""


def test_main_route_helper_builds_from_addresses(
    monkeypatch: pytest.MonkeyPatch,
    dummy_route_feature_collection: RouteFeatureCollection,
) -> None:
    """Address route helper should geocode and delegate to route builder."""

    def fake_geocode(_address: str) -> tuple[float, float]:
        return (55.0, 12.0)

    def fake_route_builder(**_kwargs: object) -> RouteFeatureCollection:
        return dummy_route_feature_collection

    monkeypatch.setattr("app.main.ox.geocode", fake_geocode)
    monkeypatch.setattr(
        "app.main.build_route_feature_collection",
        fake_route_builder,
    )

    request = AddressRouteRequest(
        transport_mode="bike",
        origin="A",
        destination="B",
        route_options=RouteComputationOptions(),
    )

    result = create_route_from_address(request)

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

    request = CoordinateRouteRequest.model_validate(
        {
            "transport_mode": "walk",
            "origin": {"type": "Point", "coordinates": [12.0, 55.0]},
            "destination": {"type": "Point", "coordinates": [12.1, 55.1]},
            "route_options": {},
        }
    )

    result = create_route_from_coordinates(request)

    assert result is dummy_route_feature_collection


def test_list_layers_and_boundary_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Endpoint wrappers should call service helpers and return their output."""
    geodataframe = gpd.GeoDataFrame(
        {"geometry": []}, geometry="geometry", crs="EPSG:4326"
    )
    empty_collection = LayerFeatureCollection(type="FeatureCollection", features=[])

    def fake_get_edges_for_mode(
        _state: object,
        _mode: str,
    ) -> gpd.GeoDataFrame:
        return geodataframe

    def fake_build_layer_feature_collection(
        *_args: object,
        **_kwargs: object,
    ) -> LayerFeatureCollection:
        return empty_collection

    monkeypatch.setattr(
        "app.main.get_edges_for_mode",
        fake_get_edges_for_mode,
    )
    monkeypatch.setattr(
        "app.main.build_layer_feature_collection",
        fake_build_layer_feature_collection,
    )

    layers = list_layers("snow", "bike")

    assert layers is empty_collection

    GRAPH_STATE.boundary_polygon = MultiPolygon(
        [Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])]
    )
    boundary = get_current_boundary()
    assert boundary.features[0].properties.name == "Copenhagen Municipality"


def test_get_current_boundary_raises_when_not_loaded() -> None:
    """Boundary endpoint should fail if startup resources were not loaded."""
    GRAPH_STATE.boundary_polygon = None

    with pytest.raises(HTTPException):
        get_current_boundary()


def test_reverse_geocode_endpoint_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    """Main reverse endpoint should delegate directly to geocoding helper."""
    monkeypatch.setattr(
        "app.main.reverse_geocode_address",
        lambda longitude, latitude, zoom_level=18: ReverseGeocodeResponse(
            address=f"{longitude},{latitude},{zoom_level}"
        ),
    )

    response = reverse_geocode(12.0, 55.0, 17)

    assert response.address == "12.0,55.0,17"


def test_address_route_helper_surfaces_geocoding_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Address route helper should map geocoding exceptions to HTTP 400."""

    def failing_geocode(_value: str) -> tuple[float, float]:
        raise RuntimeError("failed")

    monkeypatch.setattr("app.main.ox.geocode", failing_geocode)
    request = AddressRouteRequest(
        transport_mode="bike",
        origin="A",
        destination="B",
        route_options=RouteComputationOptions(),
    )

    with pytest.raises(HTTPException):
        create_route_from_address(request)
