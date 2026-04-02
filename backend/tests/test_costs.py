"""Tests for edge cost and weighting utilities."""

import networkx as nx

from app import costs
from app.models import NormalizedRoutePreferenceWeights, RoutePreferenceWeights
from app.value_parsing import parse_float_or_default


def test_normalize_route_objective_weights() -> None:
    """Weights should be normalized from percentages to [0.0, 1.0]."""
    weights = RoutePreferenceWeights(
        scenic_weight=25, snow_free_weight=50, flat_weight=75
    )

    normalized = costs.normalize_route_preference_weights(weights)

    assert normalized.scenic_weight == 0.25
    assert normalized.snow_free_weight == 0.5
    assert normalized.flat_weight == 0.75


def test_compute_edge_objective_components() -> None:
    """Objective component calculation should derive penalties from edge metadata."""
    components = costs.compute_edge_cost_components(
        {"length": 100.0, "snow": 0.2, "hills": 0.3, "scenic": 0.8}
    )

    assert components[0] == 100.0
    assert components[1] == 20.0
    assert components[2] == 30.0
    assert round(components[3], 10) == 20.0


def test_networkx_weight_function_handles_direct_parallel_and_invalid_payloads() -> (
    None
):
    """Weight function should cover direct edge dicts, parallel edges, and fallback."""
    normalized = NormalizedRoutePreferenceWeights(
        scenic_weight=0.0,
        snow_free_weight=1.0,
        flat_weight=0.0,
    )
    weight_function = costs.build_weighted_edge_cost_function(normalized)

    direct = weight_function(1, 2, {"length": 10.0, "snow": 0.5})
    parallel = weight_function(
        1,
        2,
        {
            0: {"length": 10.0, "snow": 1.0},
            1: {"length": 5.0, "snow": 0.0},
        },
    )
    fallback = weight_function(1, 2, "invalid")

    assert direct == 15.0
    assert parallel == 5.0
    assert fallback == costs.FALLBACK_EDGE_COST


def test_select_best_parallel_edge_by_scalar_cost() -> None:
    """Parallel edge selector should return the edge with the smallest scalar score."""
    graph: nx.MultiDiGraph[int] = nx.MultiDiGraph()
    graph.add_node(1)
    graph.add_node(2)
    _ = graph.add_edge(1, 2, length=100.0, snow=1.0)
    _ = graph.add_edge(1, 2, length=90.0, snow=0.0)

    normalized = NormalizedRoutePreferenceWeights(
        scenic_weight=0.0,
        snow_free_weight=1.0,
        flat_weight=0.0,
    )

    selected = costs.select_lowest_cost_parallel_edge(graph, 1, 2, normalized)

    assert selected is not None
    assert parse_float_or_default(selected["length"]) == 90.0
