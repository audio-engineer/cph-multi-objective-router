"""Route planning logic independent from FastAPI endpoint wiring."""

import heapq
from collections.abc import Callable
from dataclasses import dataclass
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
    compute_edge_objective_components,
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
    ParetoPathLabel,
    RouteComputationOptions,
    RouteCoordinates,
    RouteCostVector,
    RouteFeature,
    RouteFeatureCollection,
    RouteMeta,
    RouteObjectiveCostBreakdown,
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


@dataclass(frozen=True, slots=True)
class ResolvedRouteCandidate:
    """A fully resolved route candidate ready for response serialization."""

    path_node_ids: list[int]
    segment_edge_attributes: list[EdgeAttributes]
    total_cost_vector: RouteCostVector
    selection_score: float
    pareto_rank: int | None = None


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
    segment_edge_attributes = resolve_route_segment_edges(path_node_ids, edge_selector)

    return build_route_steps_from_edges(segment_edge_attributes)


def resolve_route_segment_edges(
    path_node_ids: list[int],
    edge_selector: EdgeSelector,
) -> list[EdgeAttributes]:
    """Resolve edge attributes for each segment in a node path."""
    segment_edge_attributes: list[EdgeAttributes] = []

    for source_node_id, target_node_id in pairwise(path_node_ids):
        edge_attributes = edge_selector(source_node_id, target_node_id)

        if edge_attributes is None:
            error_message = (
                "Missing edge attributes for segment "
                f"{source_node_id}->{target_node_id}."
            )

            raise ValueError(error_message)

        segment_edge_attributes.append(edge_attributes)

    return segment_edge_attributes


def build_route_steps_from_edges(
    segment_edge_attributes: list[EdgeAttributes],
) -> list[RouteStep]:
    """Build grouped route steps from an ordered edge sequence."""
    route_steps: list[RouteStep] = []
    current_step: RouteStep | None = None

    for segment_index, edge_attributes in enumerate(segment_edge_attributes):
        (
            segment_distance,
            snow_penalty,
            uphill_penalty,
            scenic_penalty,
        ) = compute_edge_objective_components(edge_attributes)
        street_name = _resolve_street_name(edge_attributes)

        if current_step is None:
            current_step = RouteStep(
                street=street_name,
                distance=segment_distance,
                segment_index_from=segment_index,
                segment_index_to=segment_index + 1,
                snow_penalty=snow_penalty,
                uphill_penalty=uphill_penalty,
                scenic_penalty=scenic_penalty,
            )
            continue

        if street_name == current_step.street:
            current_step = RouteStep(
                street=current_step.street,
                distance=current_step.distance + segment_distance,
                segment_index_from=current_step.segment_index_from,
                segment_index_to=segment_index + 1,
                snow_penalty=current_step.snow_penalty + snow_penalty,
                uphill_penalty=current_step.uphill_penalty + uphill_penalty,
                scenic_penalty=current_step.scenic_penalty + scenic_penalty,
            )
            continue

        route_steps.append(current_step)
        current_step = RouteStep(
            street=street_name,
            distance=segment_distance,
            segment_index_from=segment_index,
            segment_index_to=segment_index + 1,
            snow_penalty=snow_penalty,
            uphill_penalty=uphill_penalty,
            scenic_penalty=scenic_penalty,
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


def dominates_cost_vector(
    candidate_cost_vector: RouteCostVector,
    other_cost_vector: RouteCostVector,
) -> bool:
    """Return whether one route cost vector Pareto-dominates another."""
    less_equal_all = all(
        left_cost <= right_cost
        for left_cost, right_cost in zip(
            candidate_cost_vector,
            other_cost_vector,
            strict=True,
        )
    )
    less_than_any = any(
        left_cost < right_cost
        for left_cost, right_cost in zip(
            candidate_cost_vector,
            other_cost_vector,
            strict=True,
        )
    )

    return less_equal_all and less_than_any


def is_dominated_by_existing_labels(
    labels: list[ParetoPathLabel],
    existing_label_ids: list[int],
    candidate_cost_vector: RouteCostVector,
) -> bool:
    """Return whether any existing label dominates the candidate label."""
    return any(
        dominates_cost_vector(
            labels[existing_label_id].cost_vector,
            candidate_cost_vector,
        )
        for existing_label_id in existing_label_ids
    )


def build_surviving_label_ids(
    labels: list[ParetoPathLabel],
    existing_label_ids: list[int],
    candidate_label_id: int,
    candidate_cost_vector: RouteCostVector,
    max_labels_per_node: int,
) -> list[int]:
    """Filter dominated labels and enforce the per-node label cap."""
    surviving_label_ids = [
        existing_label_id
        for existing_label_id in existing_label_ids
        if not dominates_cost_vector(
            candidate_cost_vector,
            labels[existing_label_id].cost_vector,
        )
    ]
    surviving_label_ids.append(candidate_label_id)

    if len(surviving_label_ids) <= max_labels_per_node:
        return surviving_label_ids

    def sort_key_for_label_id(label_id: int) -> tuple[float, float]:
        if label_id == candidate_label_id:
            return candidate_cost_vector[0], sum(candidate_cost_vector)

        label_cost_vector = labels[label_id].cost_vector

        return label_cost_vector[0], sum(label_cost_vector)

    surviving_label_ids.sort(key=sort_key_for_label_id)

    return surviving_label_ids[:max_labels_per_node]


def filter_nondominated_destination_label_ids(
    labels: list[ParetoPathLabel],
    target_label_ids: list[int],
) -> list[int]:
    """Return the nondominated label IDs among destination labels."""
    nondominated_label_ids: list[int] = []

    for label_id in target_label_ids:
        candidate_cost_vector = labels[label_id].cost_vector

        if any(
            dominates_cost_vector(
                labels[other_label_id].cost_vector,
                candidate_cost_vector,
            )
            for other_label_id in target_label_ids
            if other_label_id != label_id
        ):
            continue

        nondominated_label_ids.append(label_id)

    return nondominated_label_ids


def calculate_pareto_frontier_labels(
    graph: MultiDiGraphAny,
    origin_node_id: int,
    destination_node_id: int,
    *,
    max_labels_per_node: int,
    max_total_labels: int,
) -> tuple[list[ParetoPathLabel], list[int]]:
    """Run Martins' label-setting algorithm and return nondominated target labels."""
    labels: list[ParetoPathLabel] = []
    labels_at: dict[int, list[int]] = {origin_node_id: []}

    start_label = ParetoPathLabel(
        node_id=origin_node_id,
        cost_vector=(0.0, 0.0, 0.0, 0.0),
        previous_label_id=None,
        previous_edge_key=None,
    )
    labels.append(start_label)
    labels_at[origin_node_id].append(0)

    heap: list[tuple[tuple[float, float], int]] = []
    heapq.heappush(heap, ((0.0, 0.0), 0))

    def is_active_label(node_id: int, label_id: int) -> bool:
        return label_id in labels_at.get(node_id, [])

    while heap:
        if len(labels) >= max_total_labels:
            break

        _, label_id = heapq.heappop(heap)
        current_label = labels[label_id]

        if not is_active_label(current_label.node_id, label_id):
            continue

        source_node_id = current_label.node_id

        outgoing_edges = cast(
            "list[tuple[int, int, int, EdgeAttributes]]",
            list(
                graph.out_edges(
                    source_node_id,
                    keys=True,
                    data=True,
                )
            ),
        )

        for _, target_node_id, parallel_edge_key, edge_attributes in outgoing_edges:
            edge_cost_vector = compute_edge_objective_components(edge_attributes)
            new_cost_vector = (
                current_label.cost_vector[0] + edge_cost_vector[0],
                current_label.cost_vector[1] + edge_cost_vector[1],
                current_label.cost_vector[2] + edge_cost_vector[2],
                current_label.cost_vector[3] + edge_cost_vector[3],
            )

            existing_label_ids = labels_at.get(target_node_id, [])

            if is_dominated_by_existing_labels(
                labels,
                existing_label_ids,
                new_cost_vector,
            ):
                continue

            candidate_label_id = len(labels)
            surviving_label_ids = build_surviving_label_ids(
                labels,
                existing_label_ids,
                candidate_label_id,
                new_cost_vector,
                max_labels_per_node,
            )

            if candidate_label_id not in surviving_label_ids:
                continue

            new_label = ParetoPathLabel(
                node_id=target_node_id,
                cost_vector=new_cost_vector,
                previous_label_id=label_id,
                previous_edge_key=(source_node_id, target_node_id, parallel_edge_key),
            )
            labels.append(new_label)
            labels_at[target_node_id] = surviving_label_ids

            heapq.heappush(
                heap,
                ((new_cost_vector[0], sum(new_cost_vector)), candidate_label_id),
            )

    target_label_ids = labels_at.get(destination_node_id, [])

    return labels, filter_nondominated_destination_label_ids(labels, target_label_ids)


def reconstruct_label_node_path(
    labels: list[ParetoPathLabel],
    label_id: int,
) -> list[int]:
    """Reconstruct the node path of a Pareto label."""
    node_path: list[int] = []
    current_label_id: int | None = label_id

    while current_label_id is not None:
        node_path.append(labels[current_label_id].node_id)
        current_label_id = labels[current_label_id].previous_label_id

    node_path.reverse()

    return node_path


def reconstruct_label_edge_keys(
    labels: list[ParetoPathLabel],
    label_id: int,
) -> list[tuple[int, int, int]]:
    """Reconstruct the traversed edge keys of a Pareto label."""
    edge_keys: list[tuple[int, int, int]] = []
    current_label_id: int | None = label_id

    while current_label_id is not None:
        previous_edge_key = labels[current_label_id].previous_edge_key

        if previous_edge_key is not None:
            edge_keys.append(previous_edge_key)

        current_label_id = labels[current_label_id].previous_label_id

    edge_keys.reverse()

    return edge_keys


def get_edge_attributes_for_edge_key(
    graph: MultiDiGraphAny,
    edge_key: tuple[int, int, int],
) -> EdgeAttributes:
    """Load edge attributes for a specific parallel edge key."""
    source_node_id, target_node_id, parallel_edge_key = edge_key
    edge_attributes = graph.get_edge_data(
        source_node_id,
        target_node_id,
        parallel_edge_key,
    )

    return cast("EdgeAttributes", edge_attributes)


def sum_route_cost_vectors(
    segment_edge_attributes: list[EdgeAttributes],
) -> RouteCostVector:
    """Sum objective cost components across a route."""
    total_distance = 0.0
    total_snow_penalty = 0.0
    total_uphill_penalty = 0.0
    total_scenic_penalty = 0.0

    for edge_attributes in segment_edge_attributes:
        (
            distance,
            snow_penalty,
            uphill_penalty,
            scenic_penalty,
        ) = compute_edge_objective_components(edge_attributes)
        total_distance += distance
        total_snow_penalty += snow_penalty
        total_uphill_penalty += uphill_penalty
        total_scenic_penalty += scenic_penalty

    return (
        total_distance,
        total_snow_penalty,
        total_uphill_penalty,
        total_scenic_penalty,
    )


def compute_route_selection_score(
    route_cost_vector: RouteCostVector,
    route_objective_weights: RouteObjectiveWeights,
) -> float:
    """Scalarize a route cost vector using the configured objective weights."""
    normalized_weights = normalize_route_objective_weights(route_objective_weights)
    distance, snow_penalty, uphill_penalty, scenic_penalty = route_cost_vector

    return (
        distance
        + normalized_weights.avoid_snow * snow_penalty
        + normalized_weights.avoid_uphill * uphill_penalty
        + normalized_weights.scenic * scenic_penalty
    )


def build_resolved_route_candidate(
    path_node_ids: list[int],
    segment_edge_attributes: list[EdgeAttributes],
    *,
    route_objective_weights: RouteObjectiveWeights,
    pareto_rank: int | None = None,
) -> ResolvedRouteCandidate:
    """Build a resolved route candidate from a path and edge sequence."""
    total_cost_vector = sum_route_cost_vectors(segment_edge_attributes)

    return ResolvedRouteCandidate(
        path_node_ids=path_node_ids,
        segment_edge_attributes=segment_edge_attributes,
        total_cost_vector=total_cost_vector,
        selection_score=compute_route_selection_score(
            total_cost_vector,
            route_objective_weights,
        ),
        pareto_rank=pareto_rank,
    )


def build_single_route_candidate(
    path_node_ids: list[int],
    edge_selector: EdgeSelector,
    *,
    route_objective_weights: RouteObjectiveWeights,
) -> ResolvedRouteCandidate:
    """Resolve one shortest/weighted path into a uniform route candidate."""
    segment_edge_attributes = resolve_route_segment_edges(path_node_ids, edge_selector)

    return build_resolved_route_candidate(
        path_node_ids,
        segment_edge_attributes,
        route_objective_weights=route_objective_weights,
    )


def build_pareto_route_candidates(
    graph: MultiDiGraphAny,
    origin_node_id: int,
    destination_node_id: int,
    route_options: RouteComputationOptions,
) -> list[ResolvedRouteCandidate]:
    """Build sorted pareto-optimal route candidates for a source-destination pair."""
    labels, destination_label_ids = calculate_pareto_frontier_labels(
        graph,
        origin_node_id,
        destination_node_id,
        max_labels_per_node=route_options.pareto_max_labels_per_node,
        max_total_labels=route_options.pareto_max_total_labels,
    )

    if not destination_label_ids:
        raise NetworkXNoPath

    ranked_label_ids = sorted(
        destination_label_ids,
        key=lambda label_id: compute_route_selection_score(
            labels[label_id].cost_vector,
            route_options.objective_weights,
        ),
    )[: route_options.pareto_max_routes]

    route_candidates: list[ResolvedRouteCandidate] = []

    for pareto_rank, label_id in enumerate(ranked_label_ids, start=1):
        path_node_ids = reconstruct_label_node_path(labels, label_id)
        edge_keys = reconstruct_label_edge_keys(labels, label_id)
        segment_edge_attributes = [
            get_edge_attributes_for_edge_key(graph, edge_key) for edge_key in edge_keys
        ]

        route_candidates.append(
            build_resolved_route_candidate(
                path_node_ids,
                segment_edge_attributes,
                route_objective_weights=route_options.objective_weights,
                pareto_rank=pareto_rank,
            )
        )

    return route_candidates


def compute_route_candidates(
    graph: MultiDiGraphAny,
    origin_node_id: int,
    destination_node_id: int,
    route_options: RouteComputationOptions,
) -> list[ResolvedRouteCandidate]:
    """Compute resolved route candidates for the selected routing method."""
    if route_options.route_selection_method == "weighted":
        path_node_ids = compute_weighted_shortest_path(
            graph,
            origin_node_id,
            destination_node_id,
            route_options.objective_weights,
        )

        return [
            build_single_route_candidate(
                path_node_ids,
                edge_selector=lambda source_node_id, target_node_id: (
                    select_best_parallel_edge_by_scalar_cost(
                        graph,
                        source_node_id,
                        target_node_id,
                        normalize_route_objective_weights(
                            route_options.objective_weights
                        ),
                    )
                ),
                route_objective_weights=route_options.objective_weights,
            )
        ]

    if route_options.route_selection_method == "pareto":
        return build_pareto_route_candidates(
            graph,
            origin_node_id,
            destination_node_id,
            route_options,
        )

    path_node_ids = compute_shortest_distance_path(
        graph,
        origin_node_id,
        destination_node_id,
    )

    return [
        build_single_route_candidate(
            path_node_ids,
            edge_selector=lambda source_node_id, target_node_id: (
                select_shortest_length_edge(graph, source_node_id, target_node_id)
            ),
            route_objective_weights=RouteObjectiveWeights(),
        )
    ]


def compute_route_path(
    graph: MultiDiGraphAny,
    origin_node_id: int,
    destination_node_id: int,
    route_options: RouteComputationOptions,
) -> list[int]:
    """Compute the primary path according to the selected route method."""
    route_candidates = compute_route_candidates(
        graph,
        origin_node_id,
        destination_node_id,
        route_options,
    )

    if not route_candidates:
        raise NetworkXNoPath

    return route_candidates[0].path_node_ids


def compute_route_steps_for_method(
    graph: MultiDiGraphAny,
    path_node_ids: list[int],
    route_options: RouteComputationOptions,
) -> list[RouteStep]:
    """Build route steps for single-path routing methods."""
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


def build_route_step_responses(route_steps: list[RouteStep]) -> list[RouteStepResponse]:
    """Convert internal route steps into response models."""
    return [
        RouteStepResponse(
            street=route_step.street,
            distance=route_step.distance,
            segment_index_from=route_step.segment_index_from,
            segment_index_to=route_step.segment_index_to,
            objective_costs=RouteObjectiveCostBreakdown(
                distance=route_step.distance,
                snow_penalty=route_step.snow_penalty,
                uphill_penalty=route_step.uphill_penalty,
                scenic_penalty=route_step.scenic_penalty,
            ),
        )
        for route_step in route_steps
    ]


def build_route_objective_cost_breakdown(
    route_cost_vector: RouteCostVector,
) -> RouteObjectiveCostBreakdown:
    """Convert a route cost vector into a named response object."""
    distance, snow_penalty, uphill_penalty, scenic_penalty = route_cost_vector

    return RouteObjectiveCostBreakdown(
        distance=distance,
        snow_penalty=snow_penalty,
        uphill_penalty=uphill_penalty,
        scenic_penalty=scenic_penalty,
    )


def build_route_feature(
    graph: MultiDiGraphAny,
    route_candidate: ResolvedRouteCandidate,
    *,
    route_index: int,
) -> RouteFeature:
    """Serialize one resolved route candidate into a GeoJSON route feature."""
    route_steps = build_route_steps_from_edges(route_candidate.segment_edge_attributes)

    return RouteFeature(
        type="Feature",
        properties=RouteProperties(
            route_index=route_index,
            distance=route_candidate.total_cost_vector[0],
            steps=build_route_step_responses(route_steps),
            objective_costs=build_route_objective_cost_breakdown(
                route_candidate.total_cost_vector
            ),
            pareto_rank=route_candidate.pareto_rank,
            selection_score=route_candidate.selection_score,
        ),
        geometry=PydanticLineString(
            type="LineString",
            coordinates=_build_path_coordinates(graph, route_candidate.path_node_ids),
        ),
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
        route_candidates = compute_route_candidates(
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

    if not route_candidates:
        raise HTTPException(status_code=500, detail="No path found.")

    return RouteFeatureCollection(
        type="FeatureCollection",
        features=[
            build_route_feature(
                graph,
                route_candidate,
                route_index=route_index,
            )
            for route_index, route_candidate in enumerate(route_candidates)
        ],
        meta=RouteMeta(
            origin=_build_node_point(graph, origin_node_id),
            destination=_build_node_point(graph, destination_node_id),
            route_selection_method=route_options.route_selection_method,
            route_count=len(route_candidates),
            recommended_route_index=0,
        ),
    )
