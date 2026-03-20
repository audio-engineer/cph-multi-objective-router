"""FastAPI composition layer for the multi-objective router."""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import osmnx as ox
from fastapi import FastAPI, HTTPException
from geojson_pydantic import MultiPolygon as PydanticMultiPolygon
from shapely.geometry import MultiPolygon as ShapelyMultiPolygon
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry import mapping
from starlette.middleware.cors import CORSMiddleware

from app.geocoding import reverse_geocode_address
from app.graph_state import (
    GRAPH_STATE,
    get_edges_for_mode,
    load_graph_state,
)
from app.layer_service import build_layer_feature_collection
from app.models import (
    AddressRouteRequest,
    BoundaryFeature,
    BoundaryFeatureCollection,
    BoundaryMeta,
    BoundaryProperties,
    CoordinateRouteRequest,
    LayerFeatureCollection,
    OverlayAttribute,
    ReverseGeocodeResponse,
    RouteCoordinates,
    RouteFeatureCollection,
    TransportMode,
)
from app.route_planner import build_route_feature_collection

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

PLACE_NAME = "Copenhagen Municipality, Capital Region of Denmark, Denmark"
OVERLAY_DIRECTORY = "data/overlays"


def _normalize_boundary_polygon(boundary_geometry: object) -> ShapelyMultiPolygon:
    """Normalize boundary geometry to a MultiPolygon."""
    if isinstance(boundary_geometry, ShapelyPolygon):
        return ShapelyMultiPolygon([boundary_geometry])

    if isinstance(boundary_geometry, ShapelyMultiPolygon):
        return boundary_geometry

    raise HTTPException(status_code=500, detail="Boundary has invalid geometry type.")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Load graph resources on startup."""
    load_graph_state(
        place_name=PLACE_NAME,
        overlay_directory=OVERLAY_DIRECTORY,
        graph_state=GRAPH_STATE,
    )

    yield


app = FastAPI(lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_route_from_address_request(
    request: AddressRouteRequest,
) -> RouteFeatureCollection:
    """Build route response for address-based requests."""
    try:
        origin_latitude, origin_longitude = ox.geocode(request.origin)
        destination_latitude, destination_longitude = ox.geocode(request.destination)
    except Exception as exception:  # pragma: no cover - network/service failure path
        raise HTTPException(
            status_code=400,
            detail=f"Geocoding failed: {exception}",
        ) from exception

    return build_route_feature_collection(
        graph_state=GRAPH_STATE,
        route_coordinates=RouteCoordinates(
            origin_longitude=origin_longitude,
            origin_latitude=origin_latitude,
            destination_longitude=destination_longitude,
            destination_latitude=destination_latitude,
        ),
        transport_mode=request.transport_mode,
        route_options=request.route_options,
    )


def _build_route_from_coordinate_request(
    request: CoordinateRouteRequest,
) -> RouteFeatureCollection:
    """Build route response for coordinate-based requests."""
    raw_origin_longitude, raw_origin_latitude = request.origin.coordinates[:2]
    raw_destination_longitude, raw_destination_latitude = (
        request.destination.coordinates[:2]
    )

    return build_route_feature_collection(
        graph_state=GRAPH_STATE,
        route_coordinates=RouteCoordinates(
            origin_longitude=float(raw_origin_longitude),
            origin_latitude=float(raw_origin_latitude),
            destination_longitude=float(raw_destination_longitude),
            destination_latitude=float(raw_destination_latitude),
        ),
        transport_mode=request.transport_mode,
        route_options=request.route_options,
    )


@app.get("/layers", response_model=LayerFeatureCollection)
def list_layers(
    overlay_attribute: OverlayAttribute,
    transport_mode: TransportMode,
    bounding_box: str | None = None,
    minimum_value: float = 0.01,
    max_features: int = 20_000,
) -> LayerFeatureCollection:
    """Get overlay layer features for the selected transport network."""
    edge_geodataframe = get_edges_for_mode(GRAPH_STATE, transport_mode)

    return build_layer_feature_collection(
        edge_geodataframe,
        overlay_attribute=overlay_attribute,
        bounding_box=bounding_box,
        minimum_attribute_value=minimum_value,
        feature_limit=max_features,
    )


@app.get("/boundaries/current", response_model=BoundaryFeatureCollection)
def get_current_boundary() -> BoundaryFeatureCollection:
    """Get boundary geometry for the loaded routing area."""
    boundary_geometry = GRAPH_STATE.boundary_polygon

    if boundary_geometry is None:
        raise HTTPException(status_code=500, detail="Graph not loaded.")

    boundary_polygon = _normalize_boundary_polygon(boundary_geometry)

    boundary_geometry = PydanticMultiPolygon.model_validate(mapping(boundary_polygon))

    return BoundaryFeatureCollection(
        type="FeatureCollection",
        features=[
            BoundaryFeature(
                type="Feature",
                properties=BoundaryProperties(name="Copenhagen Municipality"),
                geometry=boundary_geometry,
            )
        ],
        meta=BoundaryMeta(bounds=boundary_polygon.bounds),
    )


@app.post("/routes/by-address", response_model=RouteFeatureCollection)
def create_route_from_address(
    request: AddressRouteRequest,
) -> RouteFeatureCollection:
    """Compute a route from address inputs."""
    return _build_route_from_address_request(request)


@app.post("/routes/by-coordinates", response_model=RouteFeatureCollection)
def create_route_from_coordinates(
    request: CoordinateRouteRequest,
) -> RouteFeatureCollection:
    """Compute a route from coordinate inputs."""
    return _build_route_from_coordinate_request(request)


@app.get("/geocoding/reverse")
def reverse_geocode(
    longitude: float,
    latitude: float,
    zoom_level: int = 18,
) -> ReverseGeocodeResponse:
    """Get the nearest address for the given coordinates."""
    return reverse_geocode_address(longitude, latitude, zoom_level=zoom_level)
