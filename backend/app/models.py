"""Pydantic schemas and domain models for the routing API."""

from dataclasses import dataclass
from typing import ClassVar, Literal

from geojson_pydantic import LineString as PydanticLineString  # noqa: TC002
from geojson_pydantic import MultiPolygon as PydanticMultiPolygon  # noqa: TC002
from geojson_pydantic import Point as PydanticPoint  # noqa: TC002
from pydantic import BaseModel, ConfigDict, Field

type TravelMode = Literal["walking", "cycling"]
type OverlayKey = Literal["snow", "scenic", "hills"]
type GraphLayerKey = Literal[
    "cycling_nodes",
    "cycling_edges",
    "walking_nodes",
    "walking_edges",
]
type RouteOptimizationMethod = Literal["shortest", "weighted", "pareto"]

OVERLAY_KEYS: tuple[OverlayKey, ...] = ("snow", "scenic", "hills")
GRAPH_LAYER_KEYS: tuple[GraphLayerKey, ...] = (
    "cycling_nodes",
    "cycling_edges",
    "walking_nodes",
    "walking_edges",
)


class RoutePreferenceWeights(BaseModel):
    """User-defined weights for route optimization objectives."""

    scenic_weight: int = Field(default=0, ge=0, le=100)
    snow_free_weight: int = Field(default=0, ge=0, le=100)
    flat_weight: int = Field(default=0, ge=0, le=100)


def build_default_route_preference_weights() -> RoutePreferenceWeights:
    """Build default objective weights for request options."""
    return RoutePreferenceWeights()


class RoutePlanningOptions(BaseModel):
    """Options controlling how routes are computed."""

    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)

    route_optimization_method: RouteOptimizationMethod = Field(default="shortest")
    preference_weights: RoutePreferenceWeights = Field(
        default_factory=build_default_route_preference_weights,
    )

    pareto_max_routes: int = Field(default=8, ge=1, le=25)
    pareto_max_labels_per_node: int = Field(default=40, ge=5, le=200)
    pareto_max_total_labels: int = Field(default=50_000, ge=1_000, le=500_000)


def build_default_route_options() -> RoutePlanningOptions:
    """Build default routing options for route requests."""
    return RoutePlanningOptions()


class CoordinatesRouteRequest(BaseModel):
    """Route request where origin and destination are coordinates."""

    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)

    travel_mode: TravelMode
    origin: PydanticPoint
    destination: PydanticPoint
    route_options: RoutePlanningOptions = Field(
        default_factory=build_default_route_options
    )


class AddressRouteRequest(BaseModel):
    """Route request where origin and destination are addresses."""

    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)

    travel_mode: TravelMode
    origin: str
    destination: str
    route_options: RoutePlanningOptions = Field(
        default_factory=build_default_route_options
    )


class RouteStepSummary(BaseModel):
    """A high-level navigation step on the route."""

    street: str
    distance: float
    segment_index_from: int
    segment_index_to: int
    penalty_breakdown: RoutePenaltyBreakdown


class RoutePenaltyBreakdown(BaseModel):
    """Objective-aligned route cost totals."""

    distance: float
    snow_penalty: float
    uphill_penalty: float
    scenic_penalty: float


class RouteProperties(BaseModel):
    """Properties attached to a route feature."""

    route_index: int = Field(description="Zero-based route index within the response")
    distance: float = Field(description="Route distance in metres")
    steps: list[RouteStepSummary]
    penalty_breakdown: RoutePenaltyBreakdown | None = None
    pareto_rank: int | None = None
    selection_score: float | None = None


class RouteFeature(BaseModel):
    """Route feature geometry and properties."""

    type: Literal["Feature"]
    geometry: PydanticLineString
    properties: RouteProperties


class RouteMeta(BaseModel):
    """Metadata attached to a route response."""

    origin: PydanticPoint
    destination: PydanticPoint
    route_optimization_method: RouteOptimizationMethod
    route_count: int
    recommended_route_index: int


class RouteFeatureCollection(BaseModel):
    """Route FeatureCollection plus metadata."""

    type: Literal["FeatureCollection"]
    features: list[RouteFeature]
    meta: RouteMeta


class BoundaryProperties(BaseModel):
    """Properties attached to a boundary feature."""

    name: str


class BoundaryFeature(BaseModel):
    """Boundary feature geometry and properties."""

    type: Literal["Feature"]
    geometry: PydanticMultiPolygon
    properties: BoundaryProperties


class BoundaryMeta(BaseModel):
    """Metadata attached to a boundary response."""

    bounds: tuple[float, float, float, float]


class BoundaryFeatureCollection(BaseModel):
    """Boundary FeatureCollection plus metadata."""

    type: Literal["FeatureCollection"]
    features: list[BoundaryFeature]
    meta: BoundaryMeta


class OverlayFeatureProperties(BaseModel):
    """Properties attached to a layer feature."""

    overlay_key: OverlayKey
    value: float


class OverlayFeature(BaseModel):
    """Layer feature geometry and properties."""

    type: Literal["Feature"]
    geometry: PydanticLineString
    properties: OverlayFeatureProperties


class OverlayFeatureCollection(BaseModel):
    """Layer FeatureCollection."""

    type: Literal["FeatureCollection"]
    features: list[OverlayFeature]


class GraphLayerFeatureProperties(BaseModel):
    """Properties attached to a graph layer feature."""

    graph_layer_key: GraphLayerKey


class GraphNodeFeature(BaseModel):
    """Graph node feature geometry and properties."""

    type: Literal["Feature"]
    geometry: PydanticPoint
    properties: GraphLayerFeatureProperties


class GraphEdgeFeature(BaseModel):
    """Graph edge feature geometry and properties."""

    type: Literal["Feature"]
    geometry: PydanticLineString
    properties: GraphLayerFeatureProperties


class GraphLayerFeatureCollection(BaseModel):
    """Graph layer FeatureCollection."""

    type: Literal["FeatureCollection"]
    features: list[GraphNodeFeature | GraphEdgeFeature]


class ReverseGeocodeResponse(BaseModel):
    """Address response for reverse geocoding."""

    address: str


@dataclass(frozen=True, slots=True)
class AggregatedRouteStep:
    """A grouped step along contiguous segments with the same street."""

    street: str
    distance: float
    segment_index_from: int
    segment_index_to: int
    snow_penalty: float
    uphill_penalty: float
    scenic_penalty: float


@dataclass(frozen=True, slots=True)
class NormalizedRoutePreferenceWeights:
    """Objective weights scaled to [0.0, 1.0]."""

    scenic_weight: float
    snow_free_weight: float
    flat_weight: float


@dataclass(frozen=True, slots=True)
class RouteCoordinates:
    """Origin and destination coordinates in lon/lat order."""

    origin_longitude: float
    origin_latitude: float
    destination_longitude: float
    destination_latitude: float


type ParetoCostVector = tuple[float, float, float, float]


@dataclass(slots=True)
class ParetoSearchLabel:
    """A label in the Martins multi-objective shortest-path search."""

    node_id: int
    cost_vector: ParetoCostVector
    previous_label_id: int | None
    previous_edge_key: tuple[int, int, int] | None
