"""Route planning logic independent from FastAPI endpoint wiring."""

from collections.abc import Callable
from itertools import pairwise
from typing import TYPE_CHECKING, cast

import networkx as nx
import osmnx as ox
from fastapi import HTTPException
from geojson_pydantic import LineString as PydanticLineString
from geojson_pydantic import Point as PydanticPoint
from geojson_pydantic.types import Position2D, Position3D
from networkx.exception import NetworkXNoPath

from app.costs import (
    FALLBACK_EDGE_COST,
    build_networkx_weight_function,
    normalize_route_objective_weights,
    select_best_parallel_edge_by_scalar_cost,
    select_parallel_edge,
)
from app.graph_state import (
    LoadedGraphState,
    get_graph_for_mode,
    validate_point_within_boundary,
)
from app.models import (
    RouteComputationOptions,
    RouteCoordinates,
    RouteFeature,
    RouteFeatureCollection,
    RouteMeta,
    RouteObjectiveWeights,
    RouteProperties,
    RouteStep,
    RouteStepResponse,
    TransportMode,
)
from app.value_parsing import coerce_float

if TYPE_CHECKING:
    from app.typing_aliases import EdgeAttributes, MultiDiGraphAny


type EdgeSelector = Callable[[int, int], EdgeAttributes | None]
type ShortestPathFunction = Callable[..., list[int]]
type PathWeightFunction = Callable[..., float | int]
type NearestNodeFunction = Callable[..., int]


def _coerce_street_component(value: object) -> str | None:
    """Normalize OSM string/list name fields into displayable text."""
    if value is None:
        return None

    if isinstance(value, list) and value:
        street_components = cast("list[object]", value)

        return str(street_components[0])

    scalar_value = cast("object", value)

    return str(scalar_value)


def _resolve_street_name(edge_attributes: EdgeAttributes) -> str:
    """Resolve user-facing street label from OSM edge attributes."""
    street_name = _coerce_street_component(edge_attributes.get("name"))
    street_reference = _coerce_street_component(edge_attributes.get("ref"))

    if street_name:
        return street_name

    if street_reference:
        return street_reference

    highway_type = _coerce_street_component(edge_attributes.get("highway"))

    if highway_type:
        return f"{highway_type} (unnamed)"

    return "Unnamed road"


def select_shortest_length_edge(
    graph: MultiDiGraphAny,
    source_node_id: int,
    target_node_id: int,
) -> EdgeAttributes | None:
    """Select the shortest parallel edge for a node pair."""
    return select_parallel_edge(
        graph,
        source_node_id,
        target_node_id,
        ranking_key=lambda edge_attributes: coerce_float(
            edge_attributes.get("length"),
            default=FALLBACK_EDGE_COST,
        ),
    )


def build_route_steps(
    path_node_ids: list[int],
    edge_selector: EdgeSelector,
) -> list[RouteStep]:
    """Build grouped route steps by merging adjacent segments on the same street."""
    route_steps: list[RouteStep] = []
    current_step: RouteStep | None = None

    for segment_index, (source_node_id, target_node_id) in enumerate(
        pairwise(path_node_ids)
    ):
        edge_attributes = edge_selector(source_node_id, target_node_id)

        if edge_attributes is None:
            continue

        segment_distance = coerce_float(edge_attributes.get("length"), default=0.0)
        street_name = _resolve_street_name(edge_attributes)

        if current_step is None:
            current_step = RouteStep(
                street=street_name,
                distance=segment_distance,
                segment_index_from=segment_index,
                segment_index_to=segment_index + 1,
            )
            continue

        if street_name == current_step.street:
            current_step = RouteStep(
                street=current_step.street,
                distance=current_step.distance + segment_distance,
                segment_index_from=current_step.segment_index_from,
                segment_index_to=segment_index + 1,
            )
            continue

        route_steps.append(current_step)
        current_step = RouteStep(
            street=street_name,
            distance=segment_distance,
            segment_index_from=segment_index,
            segment_index_to=segment_index + 1,
        )

    if current_step is not None:
        route_steps.append(current_step)

    return route_steps


def compute_weighted_shortest_path(
    graph: MultiDiGraphAny,
    origin_node_id: int,
    destination_node_id: int,
    route_objective_weights: RouteObjectiveWeights,
) -> list[int]:
    """Compute weighted shortest path using objective-based edge costs."""
    normalized_weights = normalize_route_objective_weights(route_objective_weights)
    shortest_path = cast("ShortestPathFunction", nx.shortest_path)

    return shortest_path(
        graph,
        source=origin_node_id,
        target=destination_node_id,
        weight=build_networkx_weight_function(normalized_weights),
    )


def compute_shortest_distance_path(
    graph: MultiDiGraphAny,
    origin_node_id: int,
    destination_node_id: int,
) -> list[int]:
    """Compute shortest path by distance using length-weighted Dijkstra."""
    shortest_path = cast("ShortestPathFunction", nx.shortest_path)

    return shortest_path(
        graph,
        source=origin_node_id,
        target=destination_node_id,
        weight="length",
    )


def compute_route_path(
    graph: MultiDiGraphAny,
    origin_node_id: int,
    destination_node_id: int,
    route_options: RouteComputationOptions,
) -> list[int]:
    """Compute path according to selected route method."""
    if route_options.route_selection_method == "weighted":
        return compute_weighted_shortest_path(
            graph,
            origin_node_id,
            destination_node_id,
            route_options.objective_weights,
        )

    if route_options.route_selection_method == "pareto":
        return []

    return compute_shortest_distance_path(
        graph,
        origin_node_id,
        destination_node_id,
    )


def compute_route_steps_for_method(
    graph: MultiDiGraphAny,
    path_node_ids: list[int],
    route_options: RouteComputationOptions,
) -> list[RouteStep]:
    """Build route steps according to selected route method."""
    if route_options.route_selection_method == "weighted":
        normalized_weights = normalize_route_objective_weights(
            route_options.objective_weights
        )

        return build_route_steps(
            path_node_ids,
            edge_selector=lambda source_node_id, target_node_id: (
                select_best_parallel_edge_by_scalar_cost(
                    graph,
                    source_node_id,
                    target_node_id,
                    normalized_weights,
                )
            ),
        )

    if route_options.route_selection_method == "pareto":
        return []

    return build_route_steps(
        path_node_ids,
        edge_selector=lambda source_node_id, target_node_id: (
            select_shortest_length_edge(graph, source_node_id, target_node_id)
        ),
    )


def _build_path_coordinates(
    graph: MultiDiGraphAny,
    path_node_ids: list[int],
) -> list[Position2D | Position3D]:
    """Build route line coordinates from graph node IDs."""
    coordinates: list[Position2D | Position3D] = []

    for node_id in path_node_ids:
        node_attributes = graph.nodes[node_id]
        longitude = coerce_float(node_attributes.get("x"), default=0.0)
        latitude = coerce_float(node_attributes.get("y"), default=0.0)
        coordinates.append(Position2D(longitude, latitude))

    return coordinates


def _build_node_point(graph: MultiDiGraphAny, node_id: int) -> PydanticPoint:
    """Build a GeoJSON Point from a graph node."""
    node_attributes = graph.nodes[node_id]
    longitude = coerce_float(node_attributes.get("x"), default=0.0)
    latitude = coerce_float(node_attributes.get("y"), default=0.0)

    return PydanticPoint(
        type="Point",
        coordinates=Position2D(longitude, latitude),
    )


def _find_nearest_node_id(
    graph: MultiDiGraphAny,
    *,
    longitude: float,
    latitude: float,
) -> int:
    """Find the nearest graph node to a lon/lat coordinate."""
    nearest_nodes = cast("NearestNodeFunction", ox.distance.nearest_nodes)

    return int(
        nearest_nodes(
            graph,
            X=longitude,
            Y=latitude,
        )
    )


def build_route_feature_collection(
    *,
    graph_state: LoadedGraphState,
    route_coordinates: RouteCoordinates,
    transport_mode: TransportMode,
    route_options: RouteComputationOptions,
) -> RouteFeatureCollection:
    """Build a route FeatureCollection response for a request."""
    graph = get_graph_for_mode(graph_state, transport_mode)

    validate_point_within_boundary(
        graph_state,
        route_coordinates.origin_longitude,
        route_coordinates.origin_latitude,
    )
    validate_point_within_boundary(
        graph_state,
        route_coordinates.destination_longitude,
        route_coordinates.destination_latitude,
    )

    try:
        origin_node_id = _find_nearest_node_id(
            graph,
            longitude=route_coordinates.origin_longitude,
            latitude=route_coordinates.origin_latitude,
        )
        destination_node_id = _find_nearest_node_id(
            graph,
            longitude=route_coordinates.destination_longitude,
            latitude=route_coordinates.destination_latitude,
        )
    except Exception as exception:  # pragma: no cover - library failure path
        raise HTTPException(
            status_code=400,
            detail=f"Snapping to graph failed: {exception}",
        ) from exception

    try:
        path_node_ids = compute_route_path(
            graph,
            origin_node_id,
            destination_node_id,
            route_options,
        )
    except NetworkXNoPath:
        raise HTTPException(status_code=500, detail="No path found.") from None
    except Exception as exception:  # pragma: no cover - library failure path
        raise HTTPException(
            status_code=500,
            detail=f"Path calculation failed: {exception}",
        ) from exception

    route_steps = compute_route_steps_for_method(graph, path_node_ids, route_options)
    path_weight = cast("PathWeightFunction", nx.path_weight)
    route_distance_meters = (
        float(path_weight(graph, path_node_ids, weight="length"))
        if path_node_ids
        else 0.0
    )

    return RouteFeatureCollection(
        type="FeatureCollection",
        features=[
            RouteFeature(
                type="Feature",
                properties=RouteProperties(
                    distance=route_distance_meters,
                    steps=[
                        RouteStepResponse(
                            street=route_step.street,
                            distance=route_step.distance,
                            segment_index_from=route_step.segment_index_from,
                            segment_index_to=route_step.segment_index_to,
                        )
                        for route_step in route_steps
                    ],
                ),
                geometry=PydanticLineString(
                    type="LineString",
                    coordinates=_build_path_coordinates(graph, path_node_ids),
                ),
            )
        ],
        meta=RouteMeta(
            origin=_build_node_point(graph, origin_node_id),
            destination=_build_node_point(graph, destination_node_id),
        ),
    )
