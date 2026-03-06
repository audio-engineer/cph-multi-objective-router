"""Tests for edge cost and weighting utilities."""

# pylint: disable=unsubscriptable-object

import networkx as nx
import pytest

from app import costs
from app.models import NormalizedRouteObjectiveWeights, RouteObjectiveWeights
from app.value_parsing import coerce_float


def test_normalize_route_objective_weights() -> None:
    """Weights should be normalized from percentages to [0.0, 1.0]."""
    weights = RouteObjectiveWeights(scenic=25, avoid_snow=50, avoid_uphill=75)

    normalized = costs.normalize_route_objective_weights(weights)

    assert normalized.scenic == 0.25
    assert normalized.avoid_snow == 0.5
    assert normalized.avoid_uphill == 0.75


def test_compute_edge_objective_components() -> None:
    """Objective component calculation should derive penalties from edge metadata."""
    components = costs.compute_edge_objective_components(
        {"length": 100.0, "snow": 0.2, "uphill": 0.3, "scenic": 0.8}
    )

    assert components == pytest.approx((100.0, 20.0, 30.0, 20.0))


def test_networkx_weight_function_handles_direct_parallel_and_invalid_payloads() -> (
    None
):
    """Weight function should cover direct edge dicts, parallel edges, and fallback."""
    normalized = NormalizedRouteObjectiveWeights(
        scenic=0.0,
        avoid_snow=1.0,
        avoid_uphill=0.0,
    )
    weight_function = costs.build_networkx_weight_function(normalized)

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
    graph.add_edge(1, 2, length=100.0, snow=1.0)
    graph.add_edge(1, 2, length=90.0, snow=0.0)

    normalized = NormalizedRouteObjectiveWeights(
        scenic=0.0,
        avoid_snow=1.0,
        avoid_uphill=0.0,
    )

    selected = costs.select_best_parallel_edge_by_scalar_cost(graph, 1, 2, normalized)

    assert selected is not None
    assert coerce_float(selected["length"]) == 90.0
