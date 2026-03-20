"""Tests for graph overlay loading and application."""

from typing import cast

import geopandas as gpd
import networkx as nx
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon

from app.overlays import (
    apply_overlay_attribute,
    get_edge_linestring,
    initialize_overlay_attributes,
    load_overlay_polygons,
)
from app.value_parsing import coerce_float


@pytest.fixture
def overlay_graph() -> nx.MultiDiGraph[int]:
    """Create a graph with one edge suitable for overlay tests."""
    graph: nx.MultiDiGraph[int] = nx.MultiDiGraph()
    graph.add_node(1, x=0.0, y=0.0)
    graph.add_node(2, x=2.0, y=0.0)
    _ = graph.add_edge(1, 2, length=2.0)

    return graph


def test_get_edge_linestring_builds_fallback_from_nodes(
    overlay_graph: nx.MultiDiGraph[int],
) -> None:
    """When geometry is missing, edge linestring should be derived from node coords."""
    edge_line = get_edge_linestring(overlay_graph, 1, 2, {"length": 2.0})

    assert list(edge_line.coords) == [(0.0, 0.0), (2.0, 0.0)]


def test_initialize_and_apply_overlay_attribute(
    overlay_graph: nx.MultiDiGraph[int],
) -> None:
    """Overlay application should set the attribute on covering edges."""
    initialize_overlay_attributes(overlay_graph)

    polygon = Polygon([(0.5, -1.0), (1.5, -1.0), (1.5, 1.0), (0.5, 1.0)])
    apply_overlay_attribute(
        overlay_graph,
        overlay_attribute="snow",
        overlay_polygons=[polygon],
        overlay_values=[0.8],
    )

    edge_data = overlay_graph.get_edge_data(1, 2)
    assert edge_data is not None
    first_edge = edge_data[0]
    assert coerce_float(cast("object", first_edge["snow"])) == 0.8


def test_load_overlay_polygons_handles_polygon_and_multipolygon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Overlay loader should flatten MultiPolygon inputs and preserve values."""
    polygon = Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
    multipolygon = MultiPolygon([polygon])
    geodataframe = gpd.GeoDataFrame(
        {
            "value": [0.2, 0.4],
            "geometry": [polygon, multipolygon],
        },
        crs="EPSG:4326",
    )

    def fake_read_file(_path: object) -> gpd.GeoDataFrame:
        return geodataframe

    monkeypatch.setattr("app.overlays.gpd.read_file", fake_read_file)

    polygons, values = load_overlay_polygons("data/overlays/snow.json")

    assert len(polygons) == 2
    assert values == [0.2, 0.4]


def test_load_overlay_polygons_raises_for_invalid_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Overlay loader should reject non-polygon geometries."""
    geodataframe = gpd.GeoDataFrame(
        {
            "value": [0.5],
            "geometry": [Point(0.0, 0.0)],
        },
        crs="EPSG:4326",
    )

    def fake_read_file(_path: object) -> gpd.GeoDataFrame:
        return geodataframe

    monkeypatch.setattr("app.overlays.gpd.read_file", fake_read_file)

    with pytest.raises(TypeError):
        _ = load_overlay_polygons("data/overlays/scenic.json")
