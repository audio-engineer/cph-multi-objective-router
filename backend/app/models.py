"""Pydantic schemas and domain models for the routing API."""

from dataclasses import dataclass
from typing import ClassVar, Literal

from geojson_pydantic import LineString as PydanticLineString  # noqa: TC002
from geojson_pydantic import MultiPolygon as PydanticMultiPolygon  # noqa: TC002
from geojson_pydantic import Point as PydanticPoint  # noqa: TC002
from pydantic import BaseModel, ConfigDict, Field

TransportMode = Literal["bike", "walk"]
OverlayAttribute = Literal["snow", "scenic", "uphill"]
RouteSelectionMethod = Literal["shortest", "weighted", "pareto"]

OVERLAY_ATTRIBUTE_NAMES: tuple[OverlayAttribute, ...] = ("snow", "scenic", "uphill")


class RouteObjectiveWeights(BaseModel):
    """User-defined weights for route optimization objectives."""

    scenic: int = Field(default=0, ge=0, le=100)
    avoid_snow: int = Field(default=0, ge=0, le=100)
    avoid_uphill: int = Field(default=0, ge=0, le=100)


def build_default_route_objective_weights() -> RouteObjectiveWeights:
    """Build default objective weights for request options."""
    return RouteObjectiveWeights()


class RouteComputationOptions(BaseModel):
    """Options controlling how routes are computed."""

    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)

    route_selection_method: RouteSelectionMethod = Field(default="shortest")
    objective_weights: RouteObjectiveWeights = Field(
        default_factory=build_default_route_objective_weights,
    )

    pareto_max_routes: int = Field(default=8, ge=1, le=25)
    pareto_max_labels_per_node: int = Field(default=40, ge=5, le=200)
    pareto_max_total_labels: int = Field(default=50_000, ge=1_000, le=500_000)


def build_default_route_options() -> RouteComputationOptions:
    """Build default routing options for route requests."""
    return RouteComputationOptions()


class CoordinateRouteRequest(BaseModel):
    """Route request where origin and destination are coordinates."""

    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)

    transport_mode: TransportMode
    origin: PydanticPoint
    destination: PydanticPoint
    route_options: RouteComputationOptions = Field(
        default_factory=build_default_route_options
    )


class AddressRouteRequest(BaseModel):
    """Route request where origin and destination are addresses."""

    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)

    transport_mode: TransportMode
    origin: str
    destination: str
    route_options: RouteComputationOptions = Field(
        default_factory=build_default_route_options
    )


class RouteStepResponse(BaseModel):
    """A high-level navigation step on the route."""

    street: str
    distance: float
    segment_index_from: int
    segment_index_to: int


class RouteObjectiveCostBreakdown(BaseModel):
    """Objective-aligned route cost totals."""

    distance: float
    snow_penalty: float
    uphill_penalty: float
    scenic_penalty: float


class RouteProperties(BaseModel):
    """Properties attached to a route feature."""

    route_index: int = Field(description="Zero-based route index within the response")
    distance: float = Field(description="Route distance in metres")
    steps: list[RouteStepResponse]
    objective_costs: RouteObjectiveCostBreakdown | None = None
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
    route_selection_method: RouteSelectionMethod
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


class LayerProperties(BaseModel):
    """Properties attached to a layer feature."""

    overlay_attribute: OverlayAttribute
    value: float


class LayerFeature(BaseModel):
    """Layer feature geometry and properties."""

    type: Literal["Feature"]
    geometry: PydanticLineString
    properties: LayerProperties


class LayerFeatureCollection(BaseModel):
    """Layer FeatureCollection."""

    type: Literal["FeatureCollection"]
    features: list[LayerFeature]


class ReverseGeocodeResponse(BaseModel):
    """Address response for reverse geocoding."""

    address: str


@dataclass(frozen=True, slots=True)
class RouteStep:
    """A grouped step along contiguous segments with the same street."""

    street: str
    distance: float
    segment_index_from: int
    segment_index_to: int


@dataclass(frozen=True, slots=True)
class NormalizedRouteObjectiveWeights:
    """Objective weights scaled to [0.0, 1.0]."""

    scenic: float
    avoid_snow: float
    avoid_uphill: float


@dataclass(frozen=True, slots=True)
class RouteCoordinates:
    """Origin and destination coordinates in lon/lat order."""

    origin_longitude: float
    origin_latitude: float
    destination_longitude: float
    destination_latitude: float


type RouteCostVector = tuple[float, float, float, float]


@dataclass(slots=True)
class ParetoPathLabel:
    """A label in the Martins multi-objective shortest-path search."""

    node_id: int
    cost_vector: RouteCostVector
    previous_label_id: int | None
    previous_edge_key: tuple[int, int, int] | None
