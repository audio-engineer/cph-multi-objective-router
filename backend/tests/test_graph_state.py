"""Tests for graph state loading and access utilities."""

import geopandas as gpd
import networkx as nx
import pytest
from fastapi import HTTPException
from shapely.geometry import MultiPolygon, Point, Polygon

from app.graph_state import (
    LoadedGraphState,
    get_edges_for_mode,
    get_graph_for_mode,
    load_boundary_polygon,
    load_graph_state,
    validate_point_within_boundary,
)


def test_get_graph_and_edges_for_mode() -> None:
    """Graph and edge accessors should return values when state is populated."""
    graph: nx.MultiDiGraph[int] = nx.MultiDiGraph()
    geodataframe = gpd.GeoDataFrame(
        {"geometry": []}, geometry="geometry", crs="EPSG:4326"
    )
    state = LoadedGraphState(
        bike_graph=graph,
        walk_graph=graph,
        bike_edges=geodataframe,
        walk_edges=geodataframe,
    )

    assert get_graph_for_mode(state, "bike") is graph
    assert get_edges_for_mode(state, "walk").equals(geodataframe)


def test_get_graph_for_mode_raises_when_missing() -> None:
    """Accessor should raise HTTP 500 when graph state is missing."""
    with pytest.raises(HTTPException):
        _ = get_graph_for_mode(LoadedGraphState(), "bike")


def test_validate_point_within_boundary() -> None:
    """Boundary validation should pass inside and fail outside."""
    boundary = MultiPolygon([Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)])])
    state = LoadedGraphState(boundary_polygon=boundary)

    validate_point_within_boundary(state, 1.0, 1.0)

    with pytest.raises(HTTPException):
        validate_point_within_boundary(state, 5.0, 5.0)


def test_load_boundary_polygon(monkeypatch: pytest.MonkeyPatch) -> None:
    """Boundary loader should normalize polygon geometries to MultiPolygon."""
    geodataframe = gpd.GeoDataFrame(
        {"geometry": [Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])]},
        crs="EPSG:4326",
    )

    def fake_geocode_to_gdf(_place: str) -> gpd.GeoDataFrame:
        return geodataframe

    monkeypatch.setattr("app.graph_state.ox.geocode_to_gdf", fake_geocode_to_gdf)

    loaded_boundary = load_boundary_polygon("place")

    assert loaded_boundary.geom_type == "MultiPolygon"


def test_load_graph_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Graph state loader should populate bike/walk graphs, edges, and boundary."""
    bike_graph: nx.MultiDiGraph[int] = nx.MultiDiGraph()
    walk_graph: nx.MultiDiGraph[int] = nx.MultiDiGraph()
    geodataframe = gpd.GeoDataFrame(
        {"geometry": []}, geometry="geometry", crs="EPSG:4326"
    )
    boundary = MultiPolygon([Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])])

    def fake_graph_from_place(_place: str, network_type: str) -> nx.MultiDiGraph[int]:
        if network_type == "bike":
            return bike_graph

        return walk_graph

    def fake_apply_all_overlays(
        _graph: nx.MultiDiGraph[int],
        _overlay_directory: str,
    ) -> None:
        return None

    def fake_build_edge_geodataframe(
        _graph: nx.MultiDiGraph[int],
    ) -> gpd.GeoDataFrame:
        return geodataframe

    def fake_load_boundary_polygon(_place: str) -> MultiPolygon:
        return boundary

    monkeypatch.setattr("app.graph_state.ox.graph_from_place", fake_graph_from_place)
    monkeypatch.setattr("app.graph_state.apply_all_overlays", fake_apply_all_overlays)
    monkeypatch.setattr(
        "app.graph_state.build_edge_geodataframe",
        fake_build_edge_geodataframe,
    )
    monkeypatch.setattr(
        "app.graph_state.load_boundary_polygon",
        fake_load_boundary_polygon,
    )

    state = LoadedGraphState()
    load_graph_state(
        place_name="place",
        overlay_directory="data/overlays",
        graph_state=state,
    )

    assert state.bike_graph is bike_graph
    assert state.walk_graph is walk_graph
    assert state.bike_edges is geodataframe
    assert state.walk_edges is geodataframe
    assert state.boundary_polygon is boundary


def test_load_boundary_polygon_raises_for_invalid_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boundary loader should fail for unexpected geometry types."""
    geodataframe = gpd.GeoDataFrame(
        {"geometry": [Point(0.0, 0.0)]},
        crs="EPSG:4326",
    )

    def fake_geocode_to_gdf(_place: str) -> gpd.GeoDataFrame:
        return geodataframe

    monkeypatch.setattr("app.graph_state.ox.geocode_to_gdf", fake_geocode_to_gdf)

    with pytest.raises(TypeError):
        _ = load_boundary_polygon("place")
