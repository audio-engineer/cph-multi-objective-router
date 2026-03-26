"""Tests for route planning utilities."""

import networkx as nx
import pytest
from fastapi import HTTPException

from app.graph_state import LoadedGraphState
from app.models import RouteComputationOptions, RouteCoordinates, RouteObjectiveWeights
from app.route_planner import (
    build_route_feature_collection,
    build_route_steps,
    calculate_pareto_frontier_labels,
    compute_route_path,
    compute_route_steps_for_method,
    dominates_cost_vector,
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
    pareto_graph: nx.MultiDiGraph[int] = nx.MultiDiGraph()
    pareto_graph.add_node(1, x=12.0, y=55.0)
    pareto_graph.add_node(2, x=12.1, y=55.0)
    pareto_graph.add_node(3, x=12.0, y=55.1)
    pareto_graph.add_node(4, x=12.1, y=55.1)
    _ = pareto_graph.add_edge(1, 2, length=50.0, snow=1.0, scenic=0.0)
    _ = pareto_graph.add_edge(2, 4, length=50.0, snow=1.0, scenic=0.0)
    _ = pareto_graph.add_edge(1, 3, length=80.0, snow=0.0, scenic=1.0)
    _ = pareto_graph.add_edge(3, 4, length=80.0, snow=0.0, scenic=1.0)
    pareto_options = RouteComputationOptions(
        route_selection_method="pareto",
        objective_weights=RouteObjectiveWeights(
            scenic=0,
            avoid_snow=100,
            avoid_uphill=0,
        ),
    )

    shortest_path = compute_route_path(simple_graph, 1, 3, shortest_options)
    weighted_path = compute_route_path(simple_graph, 1, 3, weighted_options)
    pareto_path = compute_route_path(pareto_graph, 1, 4, pareto_options)

    assert shortest_path == [1, 2, 3]
    assert weighted_path == [1, 2, 3]
    assert pareto_path == [1, 3, 4]


def test_compute_route_steps_for_method(simple_graph: nx.MultiDiGraph[int]) -> None:
    """Step strategy should return steps for shortest/weighted single-path methods."""
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

    assert len(shortest_steps) == 1
    assert len(weighted_steps) == 1


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

    _, destination_label_ids = calculate_pareto_frontier_labels(
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
    assert feature_collection.features[0].properties.route_index == 0
    assert feature_collection.features[0].properties.distance == 220.0
    assert feature_collection.meta.origin.coordinates[0] == 12.0
    assert feature_collection.meta.destination.coordinates[0] == 12.2
    assert feature_collection.meta.route_selection_method == "shortest"
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
    state = LoadedGraphState(bike_graph=graph)

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
        transport_mode="bike",
        route_options=RouteComputationOptions(
            route_selection_method="pareto",
            objective_weights=RouteObjectiveWeights(
                scenic=0,
                avoid_snow=100,
                avoid_uphill=0,
            ),
            pareto_max_routes=2,
        ),
    )

    assert len(feature_collection.features) == 2
    assert feature_collection.meta.route_selection_method == "pareto"
    assert feature_collection.meta.route_count == 2
    assert feature_collection.features[0].properties.route_index == 0
    assert feature_collection.features[0].properties.pareto_rank == 1
    assert feature_collection.features[0].properties.steps[0].street == "Scenic Way"
    assert feature_collection.features[0].properties.objective_costs is not None
    assert feature_collection.features[1].properties.route_index == 1
    assert feature_collection.features[1].properties.pareto_rank == 2


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
    graph.add_node(1, x=12.0, y=55.0)
    graph.add_node(2, x=12.2, y=55.2)
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
