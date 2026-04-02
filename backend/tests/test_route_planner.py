"""Tests for route planning utilities."""

import networkx as nx
import pytest
from fastapi import HTTPException

from app.graph_state import LoadedGraphState
from app.models import RouteCoordinates, RoutePlanningOptions, RoutePreferenceWeights
from app.route_planner import (
    build_route_feature_collection,
    dominates_cost_vector,
    run_pareto_label_search,
)


def test_dominates_cost_vector() -> None:
    """Pareto dominance should require no-worse costs and one strict improvement."""
    assert dominates_cost_vector((1.0, 2.0, 3.0, 4.0), (1.0, 3.0, 3.0, 5.0))
    assert not dominates_cost_vector((1.0, 2.0, 3.0, 4.0), (0.5, 3.0, 3.0, 5.0))


def test_calculate_pareto_frontier_labels_returns_nondominated_routes() -> None:
    """Martins search should keep both nondominated routes to the destination."""
    graph: nx.MultiDiGraph[int] = nx.MultiDiGraph()
    graph.add_node(1, x=12.0, y=55.0)
    graph.add_node(2, x=12.1, y=55.0)
    graph.add_node(3, x=12.0, y=55.1)
    graph.add_node(4, x=12.1, y=55.1)
    _ = graph.add_edge(1, 2, length=50.0, snow=1.0, scenic=0.0)
    _ = graph.add_edge(2, 4, length=50.0, snow=1.0, scenic=0.0)
    _ = graph.add_edge(1, 3, length=80.0, snow=0.0, scenic=1.0)
    _ = graph.add_edge(3, 4, length=80.0, snow=0.0, scenic=1.0)

    _, destination_label_ids = run_pareto_label_search(
        graph,
        1,
        4,
        max_labels_per_node=10,
        max_total_labels=100,
    )

    assert len(destination_label_ids) == 2


def test_build_route_feature_collection_success(
    monkeypatch: pytest.MonkeyPatch,
    simple_graph: nx.MultiDiGraph[int],
) -> None:
    """Feature collection builder should create geometry, metadata, and distance."""
    state = LoadedGraphState(cycling_graph=simple_graph)

    call_count = {"value": 0}

    def fake_nearest_nodes(
        _graph: nx.MultiDiGraph[int],
        *,
        X: float,
        Y: float,
    ) -> int:
        _ = X, Y
        call_count["value"] += 1

        if call_count["value"] == 1:
            return 1

        return 3

    monkeypatch.setattr(
        "app.route_planner.ox.distance.nearest_nodes", fake_nearest_nodes
    )

    feature_collection = build_route_feature_collection(
        graph_state=state,
        route_coordinates=RouteCoordinates(12.0, 55.0, 12.2, 55.2),
        travel_mode="cycling",
        route_options=RoutePlanningOptions(route_optimization_method="shortest"),
    )

    assert len(feature_collection.features) == 1
    assert feature_collection.features[0].properties.route_index == 0
    assert feature_collection.features[0].properties.distance == 220.0
    assert feature_collection.meta.origin.coordinates[0] == 12.0
    assert feature_collection.meta.destination.coordinates[0] == 12.2
    assert feature_collection.meta.route_optimization_method == "shortest"
    assert feature_collection.meta.route_count == 1


def test_build_route_feature_collection_returns_pareto_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pareto routing should return multiple ranked routes with steps and costs."""
    graph: nx.MultiDiGraph[int] = nx.MultiDiGraph()
    graph.add_node(1, x=12.0, y=55.0)
    graph.add_node(2, x=12.1, y=55.0)
    graph.add_node(3, x=12.0, y=55.1)
    graph.add_node(4, x=12.1, y=55.1)
    _ = graph.add_edge(1, 2, length=50.0, snow=1.0, scenic=0.0, name="Snow Road")
    _ = graph.add_edge(2, 4, length=50.0, snow=1.0, scenic=0.0, name="Snow Road")
    _ = graph.add_edge(1, 3, length=80.0, snow=0.0, scenic=1.0, name="Scenic Way")
    _ = graph.add_edge(3, 4, length=80.0, snow=0.0, scenic=1.0, name="Scenic Way")
    state = LoadedGraphState(cycling_graph=graph)

    sequence = [1, 4]

    def fake_nearest_nodes(
        _graph: nx.MultiDiGraph[int],
        *,
        X: float,
        Y: float,
    ) -> int:
        _ = X, Y
        return sequence.pop(0)

    monkeypatch.setattr(
        "app.route_planner.ox.distance.nearest_nodes",
        fake_nearest_nodes,
    )

    feature_collection = build_route_feature_collection(
        graph_state=state,
        route_coordinates=RouteCoordinates(12.0, 55.0, 12.1, 55.1),
        travel_mode="cycling",
        route_options=RoutePlanningOptions(
            route_optimization_method="pareto",
            preference_weights=RoutePreferenceWeights(
                scenic_weight=0,
                snow_free_weight=100,
                flat_weight=0,
            ),
            pareto_max_routes=2,
        ),
    )

    assert len(feature_collection.features) == 2
    assert feature_collection.meta.route_optimization_method == "pareto"
    assert feature_collection.meta.route_count == 2
    assert feature_collection.features[0].properties.route_index == 0
    assert feature_collection.features[0].properties.pareto_rank == 1
    assert feature_collection.features[0].properties.steps[0].street == "Scenic Way"
    assert feature_collection.features[0].properties.penalty_breakdown is not None
    assert (
        feature_collection.features[0].properties.steps[0].penalty_breakdown.distance
        == 160.0
    )
    assert (
        feature_collection.features[0]
        .properties.steps[0]
        .penalty_breakdown.scenic_penalty
        == 0.0
    )
    assert feature_collection.features[1].properties.route_index == 1
    assert feature_collection.features[1].properties.pareto_rank == 2


def test_build_route_feature_collection_handles_snapping_error(
    monkeypatch: pytest.MonkeyPatch,
    simple_graph: nx.MultiDiGraph[int],
) -> None:
    """Snapping failures should be mapped to HTTP 400."""
    state = LoadedGraphState(cycling_graph=simple_graph)

    def fake_nearest_nodes(
        _graph: nx.MultiDiGraph[int],
        *,
        X: float,
        Y: float,
    ) -> int:
        _ = X, Y
        raise RuntimeError("snap failed")

    monkeypatch.setattr(
        "app.route_planner.ox.distance.nearest_nodes", fake_nearest_nodes
    )

    with pytest.raises(HTTPException):
        _ = build_route_feature_collection(
            graph_state=state,
            route_coordinates=RouteCoordinates(12.0, 55.0, 12.2, 55.2),
            travel_mode="cycling",
            route_options=RoutePlanningOptions(route_optimization_method="shortest"),
        )


def test_build_route_feature_collection_handles_no_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NetworkX no-path errors should be mapped to HTTP 500."""
    graph: nx.MultiDiGraph[int] = nx.MultiDiGraph()
    graph.add_node(1, x=12.0, y=55.0)
    graph.add_node(2, x=12.2, y=55.2)
    state = LoadedGraphState(cycling_graph=graph)

    sequence = [1, 2]

    def fake_nearest_nodes(
        _graph: nx.MultiDiGraph[int],
        *,
        X: float,
        Y: float,
    ) -> int:
        _ = X, Y
        return sequence.pop(0)

    monkeypatch.setattr(
        "app.route_planner.ox.distance.nearest_nodes", fake_nearest_nodes
    )

    with pytest.raises(HTTPException):
        _ = build_route_feature_collection(
            graph_state=state,
            route_coordinates=RouteCoordinates(12.0, 55.0, 12.2, 55.2),
            travel_mode="cycling",
            route_options=RoutePlanningOptions(route_optimization_method="shortest"),
        )
