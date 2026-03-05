"""Shared pytest fixtures for backend tests."""

# pylint: disable=duplicate-code, unsubscriptable-object

import networkx as nx
import pytest
from geojson_pydantic import LineString as PydanticLineString
from geojson_pydantic import Point as PydanticPoint
from geojson_pydantic.types import Position2D

from app.models import (
    RouteFeature,
    RouteFeatureCollection,
    RouteMeta,
    RouteProperties,
)


@pytest.fixture
def simple_graph() -> nx.MultiDiGraph[int]:
    """Create a small graph suitable for route planner and overlay tests."""
    graph: nx.MultiDiGraph[int] = nx.MultiDiGraph()
    graph.add_node(1, x=12.0, y=55.0)
    graph.add_node(2, x=12.1, y=55.1)
    graph.add_node(3, x=12.2, y=55.2)
    graph.add_edge(1, 2, length=100.0, name="Main Street")
    graph.add_edge(2, 3, length=120.0, name="Main Street")

    return graph


@pytest.fixture
def dummy_route_feature_collection() -> RouteFeatureCollection:
    """Create a minimal valid RouteFeatureCollection for endpoint delegation tests."""
    origin = Position2D(12.0, 55.0)
    destination = Position2D(12.1, 55.1)

    return RouteFeatureCollection(
        type="FeatureCollection",
        features=[
            RouteFeature(
                type="Feature",
                properties=RouteProperties(distance=100.0, steps=[]),
                geometry=PydanticLineString(
                    type="LineString",
                    coordinates=[origin, destination],
                ),
            )
        ],
        meta=RouteMeta(
            origin=PydanticPoint(type="Point", coordinates=origin),
            destination=PydanticPoint(type="Point", coordinates=destination),
        ),
    )
