"""Cost and weighting utilities for route optimization."""

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, cast

from app.models import NormalizedRoutePreferenceWeights, RoutePreferenceWeights
from app.value_parsing import parse_float_or_default

if TYPE_CHECKING:
    from app.typing_aliases import EdgeAttributeMap, MultiDiGraphAny

FALLBACK_EDGE_COST = 1e18


def _coerce_edge_attribute_mapping(candidate: object) -> EdgeAttributeMap | None:
    """Convert mapping-like edge payload to a string-keyed dict."""
    if not isinstance(candidate, Mapping):
        return None

    candidate_mapping = cast("Mapping[object, object]", candidate)

    if not all(isinstance(key, str) for key in candidate_mapping):
        return None

    return {
        key: value for key, value in candidate_mapping.items() if isinstance(key, str)
    }


def _extract_parallel_edge_attribute_mappings(
    candidate: object,
) -> list[EdgeAttributeMap]:
    """Extract parallel edge attribute dictionaries from a NetworkX payload."""
    parallel_edges: list[EdgeAttributeMap] = []

    if not isinstance(candidate, Mapping):
        return parallel_edges

    for edge_candidate in candidate.values():
        edge_attributes = _coerce_edge_attribute_mapping(edge_candidate)

        if edge_attributes is not None:
            parallel_edges.append(edge_attributes)

    return parallel_edges


def normalize_route_preference_weights(
    route_preference_weights: RoutePreferenceWeights,
) -> NormalizedRoutePreferenceWeights:
    """Normalize objective weights from 0-100 percentages to 0.0-1.0."""
    return NormalizedRoutePreferenceWeights(
        scenic_weight=route_preference_weights.scenic_weight / 100.0,
        snow_free_weight=route_preference_weights.snow_free_weight / 100.0,
        flat_weight=route_preference_weights.flat_weight / 100.0,
    )


def compute_edge_cost_components(
    edge_attributes: EdgeAttributeMap,
) -> tuple[float, float, float, float]:
    """Compute distance and objective-aligned edge costs."""
    distance_meters = parse_float_or_default(edge_attributes.get("length"), default=0.0)

    snow_intensity = parse_float_or_default(edge_attributes.get("snow"), default=0.0)
    hill_intensity = parse_float_or_default(edge_attributes.get("hills"), default=0.0)
    scenic_value = parse_float_or_default(edge_attributes.get("scenic"), default=0.0)

    snow_penalty = distance_meters * snow_intensity
    hill_penalty = distance_meters * hill_intensity
    scenic_penalty = distance_meters * (1.0 - scenic_value)

    return (
        distance_meters,
        snow_penalty,
        hill_penalty,
        scenic_penalty,
    )


def _compute_weighted_edge_cost(
    edge_attributes: EdgeAttributeMap,
    normalized_weights: NormalizedRoutePreferenceWeights,
) -> float:
    """Compute a single scalar cost for an edge."""
    (
        distance_meters,
        snow_penalty,
        hill_penalty,
        scenic_penalty,
    ) = compute_edge_cost_components(edge_attributes)

    return (
        distance_meters
        + normalized_weights.snow_free_weight * snow_penalty
        + normalized_weights.flat_weight * hill_penalty
        + normalized_weights.scenic_weight * scenic_penalty
    )


def build_weighted_edge_cost_function(
    normalized_weights: NormalizedRoutePreferenceWeights,
) -> Callable[[int, int, object], float]:
    """Create a weight function compatible with NetworkX MultiDiGraph."""

    def edge_weight(
        _source_node_id: int,
        _target_node_id: int,
        networkx_edge_payload: object,
    ) -> float:
        direct_edge_attributes = _coerce_edge_attribute_mapping(networkx_edge_payload)

        if direct_edge_attributes is not None and "length" in direct_edge_attributes:
            return _compute_weighted_edge_cost(
                direct_edge_attributes, normalized_weights
            )

        parallel_edge_attributes = _extract_parallel_edge_attribute_mappings(
            networkx_edge_payload
        )

        if not parallel_edge_attributes:
            return FALLBACK_EDGE_COST

        return min(
            _compute_weighted_edge_cost(edge_attributes, normalized_weights)
            for edge_attributes in parallel_edge_attributes
        )

    return edge_weight


def select_parallel_edge_attributes(
    graph: MultiDiGraphAny,
    source_node_id: int,
    target_node_id: int,
    *,
    ranking_key: Callable[[EdgeAttributeMap], float],
) -> EdgeAttributeMap | None:
    """Select one parallel edge according to the provided ranking key."""
    parallel_edges_payload = graph.get_edge_data(source_node_id, target_node_id)
    parallel_edge_attributes = _extract_parallel_edge_attribute_mappings(
        parallel_edges_payload
    )

    if not parallel_edge_attributes:
        return None

    return min(parallel_edge_attributes, key=ranking_key)


def select_lowest_cost_parallel_edge(
    graph: MultiDiGraphAny,
    source_node_id: int,
    target_node_id: int,
    normalized_weights: NormalizedRoutePreferenceWeights,
) -> EdgeAttributeMap | None:
    """Select the lowest scalar-cost parallel edge for a graph segment."""
    return select_parallel_edge_attributes(
        graph,
        source_node_id,
        target_node_id,
        ranking_key=lambda edge_attributes: _compute_weighted_edge_cost(
            edge_attributes,
            normalized_weights,
        ),
    )
