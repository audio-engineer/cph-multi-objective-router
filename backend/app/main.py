"""FastAPI composition layer for the multi-objective router."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

import osmnx as ox
from fastapi import Depends, FastAPI, HTTPException, Query
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
    RouteComputationOptions,
    RouteCoordinates,
    RouteFeatureCollection,
    RouteObjectiveWeights,
    RouteSelectionMethod,
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


@dataclass(frozen=True, slots=True)
class ParetoRoutingLimits:
    """Upper bounds controlling the pareto label-setting search."""

    max_routes: int
    max_labels_per_node: int
    max_total_labels: int


def build_route_objective_weights(
    scenic: Annotated[int, Query(ge=0, le=100)] = 0,
    avoid_snow: Annotated[int, Query(ge=0, le=100)] = 0,
    avoid_uphill: Annotated[int, Query(ge=0, le=100)] = 0,
) -> RouteObjectiveWeights:
    """Build route objective weights from GET query parameters."""
    return RouteObjectiveWeights(
        scenic=scenic,
        avoid_snow=avoid_snow,
        avoid_uphill=avoid_uphill,
    )


def build_pareto_routing_limits(
    pareto_max_routes: Annotated[int, Query(ge=1, le=25)] = 8,
    pareto_max_labels_per_node: Annotated[int, Query(ge=5, le=200)] = 40,
    pareto_max_total_labels: Annotated[int, Query(ge=1_000, le=500_000)] = 50_000,
) -> ParetoRoutingLimits:
    """Build pareto-routing search limits from GET query parameters."""
    return ParetoRoutingLimits(
        max_routes=pareto_max_routes,
        max_labels_per_node=pareto_max_labels_per_node,
        max_total_labels=pareto_max_total_labels,
    )


def build_route_computation_options(
    route_objective_weights: Annotated[
        RouteObjectiveWeights,
        Depends(build_route_objective_weights),
    ],
    pareto_routing_limits: Annotated[
        ParetoRoutingLimits,
        Depends(build_pareto_routing_limits),
    ],
    route_selection_method: Annotated[RouteSelectionMethod, Query()] = "shortest",
) -> RouteComputationOptions:
    """Build route computation options from GET query parameters."""
    return RouteComputationOptions(
        route_selection_method=route_selection_method,
        objective_weights=route_objective_weights,
        pareto_max_routes=pareto_routing_limits.max_routes,
        pareto_max_labels_per_node=pareto_routing_limits.max_labels_per_node,
        pareto_max_total_labels=pareto_routing_limits.max_total_labels,
    )


def build_route_coordinates_from_query(
    origin_longitude: float,
    origin_latitude: float,
    destination_longitude: float,
    destination_latitude: float,
) -> RouteCoordinates:
    """Build route coordinates from GET query parameters."""
    return RouteCoordinates(
        origin_longitude=origin_longitude,
        origin_latitude=origin_latitude,
        destination_longitude=destination_longitude,
        destination_latitude=destination_latitude,
    )


def build_address_route_request_from_query(
    transport_mode: TransportMode,
    origin: str,
    destination: str,
    route_options: Annotated[
        RouteComputationOptions,
        Depends(build_route_computation_options),
    ],
) -> AddressRouteRequest:
    """Build an address route request from GET query parameters."""
    return AddressRouteRequest(
        transport_mode=transport_mode,
        origin=origin,
        destination=destination,
        route_options=route_options,
    )


def build_coordinate_route_request_from_query(
    transport_mode: TransportMode,
    route_coordinates: Annotated[
        RouteCoordinates,
        Depends(build_route_coordinates_from_query),
    ],
    route_options: Annotated[
        RouteComputationOptions,
        Depends(build_route_computation_options),
    ],
) -> CoordinateRouteRequest:
    """Build a coordinate route request from GET query parameters."""
    return CoordinateRouteRequest.model_validate(
        {
            "transport_mode": transport_mode,
            "origin": {
                "type": "Point",
                "coordinates": [
                    route_coordinates.origin_longitude,
                    route_coordinates.origin_latitude,
                ],
            },
            "destination": {
                "type": "Point",
                "coordinates": [
                    route_coordinates.destination_longitude,
                    route_coordinates.destination_latitude,
                ],
            },
            "route_options": route_options.model_dump(),
        }
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


@app.get("/routes/by-address", response_model=RouteFeatureCollection)
def create_route_from_address(
    request: Annotated[
        AddressRouteRequest,
        Depends(build_address_route_request_from_query),
    ],
) -> RouteFeatureCollection:
    """Compute a route from address inputs."""
    return _build_route_from_address_request(request)


@app.get("/routes/by-coordinates", response_model=RouteFeatureCollection)
def create_route_from_coordinates(
    request: Annotated[
        CoordinateRouteRequest,
        Depends(build_coordinate_route_request_from_query),
    ],
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
