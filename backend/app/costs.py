"""Cost and weighting utilities for route optimization."""

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from app.models import NormalizedRouteObjectiveWeights, RouteObjectiveWeights
from app.value_parsing import coerce_float

if TYPE_CHECKING:
    from app.typing_aliases import EdgeAttributes, MultiDiGraphAny

FALLBACK_EDGE_COST = 1e18


def _coerce_edge_attributes(candidate: object) -> EdgeAttributes | None:
    """Convert mapping-like edge payload to a string-keyed dict."""
    if not isinstance(candidate, Mapping):
        return None

    if not all(isinstance(key, str) for key in candidate):
        return None

    return {str(key): value for key, value in candidate.items()}


def extract_parallel_edge_attributes(candidate: object) -> list[EdgeAttributes]:
    """Extract parallel edge attribute dictionaries from a NetworkX payload."""
    parallel_edges: list[EdgeAttributes] = []

    if not isinstance(candidate, Mapping):
        return parallel_edges

    for edge_candidate in candidate.values():
        edge_attributes = _coerce_edge_attributes(edge_candidate)

        if edge_attributes is not None:
            parallel_edges.append(edge_attributes)

    return parallel_edges


def normalize_route_objective_weights(
    route_objective_weights: RouteObjectiveWeights,
) -> NormalizedRouteObjectiveWeights:
    """Normalize objective weights from 0-100 percentages to 0.0-1.0."""
    return NormalizedRouteObjectiveWeights(
        scenic=route_objective_weights.scenic / 100.0,
        avoid_snow=route_objective_weights.avoid_snow / 100.0,
        avoid_uphill=route_objective_weights.avoid_uphill / 100.0,
    )


def compute_edge_objective_components(
    edge_attributes: EdgeAttributes,
) -> tuple[float, float, float, float]:
    """Compute distance and objective-aligned edge costs."""
    distance_meters = coerce_float(edge_attributes.get("length"), default=0.0)

    snow_exposure = coerce_float(edge_attributes.get("snow"), default=0.0)
    uphill_exposure = coerce_float(edge_attributes.get("uphill"), default=0.0)
    scenic_score = coerce_float(edge_attributes.get("scenic"), default=0.0)

    snow_penalty_cost = distance_meters * snow_exposure
    uphill_penalty_cost = distance_meters * uphill_exposure
    scenic_penalty_cost = distance_meters * (1.0 - scenic_score)

    return (
        distance_meters,
        snow_penalty_cost,
        uphill_penalty_cost,
        scenic_penalty_cost,
    )


def compute_scalar_edge_cost(
    edge_attributes: EdgeAttributes,
    normalized_weights: NormalizedRouteObjectiveWeights,
) -> float:
    """Compute a single scalar cost for an edge."""
    (
        distance_meters,
        snow_penalty_cost,
        uphill_penalty_cost,
        scenic_penalty_cost,
    ) = compute_edge_objective_components(edge_attributes)

    return (
        distance_meters
        + normalized_weights.avoid_snow * snow_penalty_cost
        + normalized_weights.avoid_uphill * uphill_penalty_cost
        + normalized_weights.scenic * scenic_penalty_cost
    )


def build_networkx_weight_function(
    normalized_weights: NormalizedRouteObjectiveWeights,
) -> Callable[[int, int, object], float]:
    """Create a weight function compatible with NetworkX MultiDiGraph."""

    def edge_weight(
        _source_node_id: int,
        _target_node_id: int,
        networkx_edge_payload: object,
    ) -> float:
        direct_edge_attributes = _coerce_edge_attributes(networkx_edge_payload)

        if direct_edge_attributes is not None and "length" in direct_edge_attributes:
            return compute_scalar_edge_cost(direct_edge_attributes, normalized_weights)

        parallel_edge_attributes = extract_parallel_edge_attributes(
            networkx_edge_payload
        )

        if not parallel_edge_attributes:
            return FALLBACK_EDGE_COST

        return min(
            compute_scalar_edge_cost(edge_attributes, normalized_weights)
            for edge_attributes in parallel_edge_attributes
        )

    return edge_weight


def select_parallel_edge(
    graph: MultiDiGraphAny,
    source_node_id: int,
    target_node_id: int,
    *,
    ranking_key: Callable[[EdgeAttributes], float],
) -> EdgeAttributes | None:
    """Select one parallel edge according to the provided ranking key."""
    parallel_edges_payload = graph.get_edge_data(source_node_id, target_node_id)
    parallel_edge_attributes = extract_parallel_edge_attributes(parallel_edges_payload)

    if not parallel_edge_attributes:
        return None

    return min(parallel_edge_attributes, key=ranking_key)


def select_best_parallel_edge_by_scalar_cost(
    graph: MultiDiGraphAny,
    source_node_id: int,
    target_node_id: int,
    normalized_weights: NormalizedRouteObjectiveWeights,
) -> EdgeAttributes | None:
    """Select the lowest scalar-cost parallel edge for a graph segment."""
    return select_parallel_edge(
        graph,
        source_node_id,
        target_node_id,
        ranking_key=lambda edge_attributes: compute_scalar_edge_cost(
            edge_attributes,
            normalized_weights,
        ),
    )
