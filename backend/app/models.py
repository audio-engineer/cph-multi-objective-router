"""Pydantic schemas and domain models for the routing API."""

# pylint: disable=too-few-public-methods

from dataclasses import dataclass
from typing import Literal

from geojson_pydantic import Feature as PydanticFeature
from geojson_pydantic import FeatureCollection as PydanticFeatureCollection
from geojson_pydantic import LineString as PydanticLineString
from geojson_pydantic import MultiPolygon as PydanticMultiPolygon
from geojson_pydantic import Point as PydanticPoint
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

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

    model_config = ConfigDict(populate_by_name=True)

    route_selection_method: RouteSelectionMethod = Field(
        default="shortest",
        validation_alias=AliasChoices(
            "route_selection_method",
            "route_method",
            "method",
        ),
    )
    objective_weights: RouteObjectiveWeights = Field(
        default_factory=build_default_route_objective_weights,
        validation_alias=AliasChoices("objective_weights", "weights"),
    )

    pareto_max_routes: int = Field(default=8, ge=1, le=25)
    pareto_max_labels_per_node: int = Field(default=40, ge=5, le=200)
    pareto_max_total_labels: int = Field(default=50_000, ge=1_000, le=500_000)


def build_default_route_options() -> RouteComputationOptions:
    """Build default routing options for route requests."""
    return RouteComputationOptions()


class CoordinateRouteRequest(BaseModel):
    """Route request where origin and destination are coordinates."""

    model_config = ConfigDict(populate_by_name=True)

    transport_mode: TransportMode = Field(
        validation_alias=AliasChoices("transport_mode", "travel_mode")
    )
    origin: PydanticPoint = Field(validation_alias=AliasChoices("origin", "start"))
    destination: PydanticPoint = Field(
        validation_alias=AliasChoices("destination", "end")
    )
    route_options: RouteComputationOptions = Field(
        default_factory=build_default_route_options,
        validation_alias=AliasChoices("route_options", "options"),
    )


class AddressRouteRequest(BaseModel):
    """Route request where origin and destination are addresses."""

    model_config = ConfigDict(populate_by_name=True)

    transport_mode: TransportMode = Field(
        validation_alias=AliasChoices("transport_mode", "travel_mode")
    )
    origin: str = Field(validation_alias=AliasChoices("origin", "from"))
    destination: str = Field(validation_alias=AliasChoices("destination", "to"))
    route_options: RouteComputationOptions = Field(
        default_factory=build_default_route_options,
        validation_alias=AliasChoices("route_options", "options"),
    )


class RouteStepResponse(BaseModel):
    """A high-level navigation step on the route."""

    street: str
    distance: float
    segment_index_from: int
    segment_index_to: int


class RouteProperties(BaseModel):
    """Properties attached to a route feature."""

    distance: float = Field(description="Route distance in metres")
    steps: list[RouteStepResponse]


class RouteFeature(PydanticFeature[PydanticLineString, RouteProperties]):
    """Route feature geometry + properties."""

    geometry: PydanticLineString
    properties: RouteProperties


class RouteMeta(BaseModel):
    """Metadata attached to a route response."""

    origin: PydanticPoint
    destination: PydanticPoint


class RouteFeatureCollection(PydanticFeatureCollection[RouteFeature]):
    """Route FeatureCollection plus metadata."""

    meta: RouteMeta


class BoundaryProperties(BaseModel):
    """Properties attached to a boundary feature."""

    name: str


class BoundaryFeature(PydanticFeature[PydanticMultiPolygon, BoundaryProperties]):
    """Boundary feature geometry + properties."""

    geometry: PydanticMultiPolygon
    properties: BoundaryProperties


class BoundaryMeta(BaseModel):
    """Metadata attached to a boundary response."""

    bounds: tuple[float, float, float, float]


class BoundaryFeatureCollection(PydanticFeatureCollection[BoundaryFeature]):
    """Boundary FeatureCollection plus metadata."""

    meta: BoundaryMeta


class LayerProperties(BaseModel):
    """Properties attached to a layer feature."""

    overlay_attribute: OverlayAttribute = Field(
        validation_alias=AliasChoices("overlay_attribute", "attribute")
    )
    value: float


class LayerFeature(PydanticFeature[PydanticLineString, LayerProperties]):
    """Layer feature geometry + properties."""

    geometry: PydanticLineString
    properties: LayerProperties


class LayerFeatureCollection(PydanticFeatureCollection[LayerFeature]):
    """Layer FeatureCollection."""


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
