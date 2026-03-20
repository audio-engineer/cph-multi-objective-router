"""Tests for route planning utilities."""

import networkx as nx
import pytest
from fastapi import HTTPException

from app.graph_state import LoadedGraphState
from app.models import RouteComputationOptions, RouteCoordinates, RouteObjectiveWeights
from app.route_planner import (
    build_route_feature_collection,
    build_route_steps,
    compute_route_path,
    compute_route_steps_for_method,
)


def test_build_route_steps_merges_adjacent_segments() -> None:
    """Step builder should merge contiguous segments on the same resolved street."""
    path = [1, 2, 3]

    def edge_selector(source: int, target: int) -> dict[str, object] | None:
        if source == 1 and target == 2:
            return {"name": "Main", "length": 10.0}

        if source == 2 and target == 3:
            return {"name": "Main", "length": 20.0}

        return None

    steps = build_route_steps(path, edge_selector)

    assert len(steps) == 1
    assert steps[0].street == "Main"
    assert steps[0].distance == 30.0


def test_compute_route_path_for_methods(simple_graph: nx.MultiDiGraph[int]) -> None:
    """Route path selection should cover shortest, weighted, and pareto modes."""
    shortest_options = RouteComputationOptions(route_selection_method="shortest")
    weighted_options = RouteComputationOptions(
        route_selection_method="weighted",
        objective_weights=RouteObjectiveWeights(scenic=0, avoid_snow=0, avoid_uphill=0),
    )
    pareto_options = RouteComputationOptions(route_selection_method="pareto")

    shortest_path = compute_route_path(simple_graph, 1, 3, shortest_options)
    weighted_path = compute_route_path(simple_graph, 1, 3, weighted_options)
    pareto_path = compute_route_path(simple_graph, 1, 3, pareto_options)

    assert shortest_path == [1, 2, 3]
    assert weighted_path == [1, 2, 3]
    assert pareto_path == []


def test_compute_route_steps_for_method(simple_graph: nx.MultiDiGraph[int]) -> None:
    """Step strategy should return steps for shortest/weighted and empty for pareto."""
    path = [1, 2, 3]

    shortest_steps = compute_route_steps_for_method(
        simple_graph,
        path,
        RouteComputationOptions(route_selection_method="shortest"),
    )
    weighted_steps = compute_route_steps_for_method(
        simple_graph,
        path,
        RouteComputationOptions(route_selection_method="weighted"),
    )
    pareto_steps = compute_route_steps_for_method(
        simple_graph,
        path,
        RouteComputationOptions(route_selection_method="pareto"),
    )

    assert len(shortest_steps) == 1
    assert len(weighted_steps) == 1
    assert not pareto_steps


def test_build_route_feature_collection_success(
    monkeypatch: pytest.MonkeyPatch,
    simple_graph: nx.MultiDiGraph[int],
) -> None:
    """Feature collection builder should create geometry, metadata, and distance."""
    state = LoadedGraphState(bike_graph=simple_graph)

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
        transport_mode="bike",
        route_options=RouteComputationOptions(route_selection_method="shortest"),
    )

    assert len(feature_collection.features) == 1
    assert feature_collection.features[0].properties.distance == 220.0
    assert feature_collection.meta.origin.coordinates[0] == 12.0
    assert feature_collection.meta.destination.coordinates[0] == 12.2


def test_build_route_feature_collection_handles_snapping_error(
    monkeypatch: pytest.MonkeyPatch,
    simple_graph: nx.MultiDiGraph[int],
) -> None:
    """Snapping failures should be mapped to HTTP 400."""
    state = LoadedGraphState(bike_graph=simple_graph)

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
            transport_mode="bike",
            route_options=RouteComputationOptions(route_selection_method="shortest"),
        )


def test_build_route_feature_collection_handles_no_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NetworkX no-path errors should be mapped to HTTP 500."""
    graph: nx.MultiDiGraph[int] = nx.MultiDiGraph()
    _ = graph.add_node(1, x=12.0, y=55.0)
    _ = graph.add_node(2, x=12.2, y=55.2)
    state = LoadedGraphState(bike_graph=graph)

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
            transport_mode="bike",
            route_options=RouteComputationOptions(route_selection_method="shortest"),
        )
