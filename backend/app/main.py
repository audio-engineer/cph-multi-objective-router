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

from app.geocoding import reverse_geocode_to_address
from app.graph_layer_service import build_graph_layer_feature_collection
from app.graph_state import (
    GRAPH_STATE,
    get_edge_geodataframe_for_travel_mode,
    get_node_geodataframe_for_travel_mode,
    load_graph_state,
)
from app.layer_service import build_overlay_feature_collection
from app.models import (
    AddressRouteRequest,
    BoundaryFeature,
    BoundaryFeatureCollection,
    BoundaryMeta,
    BoundaryProperties,
    CoordinatesRouteRequest,
    GraphLayerFeatureCollection,
    GraphLayerKey,
    OverlayFeatureCollection,
    OverlayKey,
    ReverseGeocodeResponse,
    RouteCoordinates,
    RouteFeatureCollection,
    RouteOptimizationMethod,
    RoutePlanningOptions,
    RoutePreferenceWeights,
    TravelMode,
)
from app.route_planner import build_route_feature_collection

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

PLACE_NAME = "Copenhagen Municipality, Capital Region of Denmark, Denmark"
OVERLAY_DIRECTORY = "data/overlays"


def _as_multipolygon(boundary_geometry: object) -> ShapelyMultiPolygon:
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


def _compute_route_from_address_request(
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
        travel_mode=request.travel_mode,
        route_options=request.route_options,
    )


def _compute_route_from_coordinate_request(
    request: CoordinatesRouteRequest,
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
        travel_mode=request.travel_mode,
        route_options=request.route_options,
    )


@dataclass(frozen=True, slots=True)
class ParetoSearchLimits:
    """Upper bounds controlling the pareto label-setting search."""

    max_routes: int
    max_labels_per_node: int
    max_total_labels: int


def build_route_preference_weights(
    scenic_weight: Annotated[int, Query(ge=0, le=100)] = 0,
    snow_free_weight: Annotated[int, Query(ge=0, le=100)] = 0,
    flat_weight: Annotated[int, Query(ge=0, le=100)] = 0,
) -> RoutePreferenceWeights:
    """Build route objective weights from GET query parameters."""
    return RoutePreferenceWeights(
        scenic_weight=scenic_weight,
        snow_free_weight=snow_free_weight,
        flat_weight=flat_weight,
    )


def build_pareto_search_limits(
    pareto_max_routes: Annotated[int, Query(ge=1, le=25)] = 8,
    pareto_max_labels_per_node: Annotated[int, Query(ge=5, le=200)] = 40,
    pareto_max_total_labels: Annotated[int, Query(ge=1_000, le=500_000)] = 50_000,
) -> ParetoSearchLimits:
    """Build pareto-routing search limits from GET query parameters."""
    return ParetoSearchLimits(
        max_routes=pareto_max_routes,
        max_labels_per_node=pareto_max_labels_per_node,
        max_total_labels=pareto_max_total_labels,
    )


def build_route_planning_options(
    route_preference_weights: Annotated[
        RoutePreferenceWeights,
        Depends(build_route_preference_weights),
    ],
    pareto_search_limits: Annotated[
        ParetoSearchLimits,
        Depends(build_pareto_search_limits),
    ],
    route_optimization_method: Annotated[RouteOptimizationMethod, Query()] = "shortest",
) -> RoutePlanningOptions:
    """Build route computation options from GET query parameters."""
    return RoutePlanningOptions(
        route_optimization_method=route_optimization_method,
        preference_weights=route_preference_weights,
        pareto_max_routes=pareto_search_limits.max_routes,
        pareto_max_labels_per_node=pareto_search_limits.max_labels_per_node,
        pareto_max_total_labels=pareto_search_limits.max_total_labels,
    )


def build_route_coordinates_from_params(
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


def build_address_route_request_from_params(
    travel_mode: TravelMode,
    origin: str,
    destination: str,
    route_options: Annotated[
        RoutePlanningOptions,
        Depends(build_route_planning_options),
    ],
) -> AddressRouteRequest:
    """Build an address route request from GET query parameters."""
    return AddressRouteRequest(
        travel_mode=travel_mode,
        origin=origin,
        destination=destination,
        route_options=route_options,
    )


def build_coordinate_route_request_from_params(
    travel_mode: TravelMode,
    route_coordinates: Annotated[
        RouteCoordinates,
        Depends(build_route_coordinates_from_params),
    ],
    route_options: Annotated[
        RoutePlanningOptions,
        Depends(build_route_planning_options),
    ],
) -> CoordinatesRouteRequest:
    """Build a coordinate route request from GET query parameters."""
    return CoordinatesRouteRequest.model_validate(
        {
            "travel_mode": travel_mode,
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


@app.get("/layers", response_model=OverlayFeatureCollection)
def list_overlay_features(
    overlay_key: OverlayKey,
    travel_mode: TravelMode,
    bounding_box: str | None = None,
    minimum_value: float = 0.01,
    max_features: int = 20_000,
) -> OverlayFeatureCollection:
    """Get overlay layer features for the selected transport network."""
    edge_geodataframe = get_edge_geodataframe_for_travel_mode(GRAPH_STATE, travel_mode)

    return build_overlay_feature_collection(
        edge_geodataframe,
        overlay_key=overlay_key,
        bounding_box=bounding_box,
        minimum_overlay_value=minimum_value,
        max_features=max_features,
    )


@app.get("/graph-layers", response_model=GraphLayerFeatureCollection)
def list_graph_layer_features(
    graph_layer_key: GraphLayerKey,
    bounding_box: str | None = None,
    max_features: int = 20_000,
) -> GraphLayerFeatureCollection:
    """Get raw OSMnx graph node or edge features for a selected network."""
    is_cycling_layer = graph_layer_key.startswith("cycling_")
    is_node_layer = graph_layer_key.endswith("_nodes")
    travel_mode: TravelMode = "cycling" if is_cycling_layer else "walking"

    geodataframe = (
        get_node_geodataframe_for_travel_mode(GRAPH_STATE, travel_mode)
        if is_node_layer
        else get_edge_geodataframe_for_travel_mode(GRAPH_STATE, travel_mode)
    )

    return build_graph_layer_feature_collection(
        geodataframe,
        graph_layer_key=graph_layer_key,
        bounding_box=bounding_box,
        max_features=max_features,
    )


@app.get("/boundaries/current", response_model=BoundaryFeatureCollection)
def get_current_boundary() -> BoundaryFeatureCollection:
    """Get boundary geometry for the loaded routing area."""
    boundary_geometry = GRAPH_STATE.boundary_geometry

    if boundary_geometry is None:
        raise HTTPException(status_code=500, detail="Graph not loaded.")

    boundary_polygon = _as_multipolygon(boundary_geometry)

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
def compute_route_by_address(
    request: Annotated[
        AddressRouteRequest,
        Depends(build_address_route_request_from_params),
    ],
) -> RouteFeatureCollection:
    """Compute a route from address inputs."""
    return _compute_route_from_address_request(request)


@app.get("/routes/by-coordinates", response_model=RouteFeatureCollection)
def compute_route_by_coordinates(
    request: Annotated[
        CoordinatesRouteRequest,
        Depends(build_coordinate_route_request_from_params),
    ],
) -> RouteFeatureCollection:
    """Compute a route from coordinate inputs."""
    return _compute_route_from_coordinate_request(request)


@app.get("/geocoding/reverse")
def reverse_geocode(
    longitude: float,
    latitude: float,
    zoom_level: int = 18,
) -> ReverseGeocodeResponse:
    """Get the nearest address for the given coordinates."""
    return reverse_geocode_to_address(longitude, latitude, zoom_level=zoom_level)
