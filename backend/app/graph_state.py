"""Graph loading and in-memory application state."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import osmnx as ox
from fastapi import HTTPException
from shapely.geometry import MultiPolygon as ShapelyMultiPolygon
from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon as ShapelyPolygon

from app.overlays import load_and_apply_overlays

if TYPE_CHECKING:
    from collections.abc import Callable

    import geopandas as gpd

    from app.models import TravelMode
    from app.typing_aliases import MultiDiGraphAny

type BoundaryGeometry = ShapelyPolygon | ShapelyMultiPolygon


@dataclass(slots=True)
class LoadedGraphState:
    """All in-memory graph artifacts required by API endpoints."""

    cycling_graph: MultiDiGraphAny | None = None
    walking_graph: MultiDiGraphAny | None = None
    cycling_nodes: gpd.GeoDataFrame | None = None
    walking_nodes: gpd.GeoDataFrame | None = None
    cycling_edges: gpd.GeoDataFrame | None = None
    walking_edges: gpd.GeoDataFrame | None = None
    boundary_geometry: BoundaryGeometry | None = None


GRAPH_STATE = LoadedGraphState()


def _graph_to_node_geodataframe(graph: MultiDiGraphAny) -> gpd.GeoDataFrame:
    """Call OSMnx graph_to_gdfs with the node-only signature."""
    graph_to_gdfs = cast(
        "Callable[..., gpd.GeoDataFrame]",
        ox.graph_to_gdfs,
    )

    return graph_to_gdfs(
        graph,
        nodes=True,
        edges=False,
    )


def _graph_to_edge_geodataframe(graph: MultiDiGraphAny) -> gpd.GeoDataFrame:
    """Call OSMnx graph_to_gdfs with the edge-only signature."""
    graph_to_gdfs = cast(
        "Callable[..., gpd.GeoDataFrame]",
        ox.graph_to_gdfs,
    )

    return graph_to_gdfs(
        graph,
        nodes=False,
        edges=True,
        fill_edge_geometry=True,
    )


def _load_graph_from_place(
    place_name: str,
    *,
    network_type: str,
) -> MultiDiGraphAny:
    """Call OSMnx graph_from_place with a typed return value."""
    graph_from_place = cast(
        "Callable[..., MultiDiGraphAny]",
        ox.graph_from_place,
    )

    return graph_from_place(place_name, network_type=network_type)


def _geocode_place_to_geodataframe(place_name: str) -> gpd.GeoDataFrame:
    """Call OSMnx geocode_to_gdf with a typed return value."""
    geocode_to_gdf = cast(
        "Callable[[str], gpd.GeoDataFrame]",
        ox.geocode_to_gdf,
    )

    return geocode_to_gdf(place_name)


def _build_node_geodataframe(graph: MultiDiGraphAny) -> gpd.GeoDataFrame:
    """Build node GeoDataFrame from a graph, ensuring WGS84 CRS."""
    node_geodataframe = _graph_to_node_geodataframe(graph)

    return node_geodataframe.set_crs("EPSG:4326", allow_override=True)


def _build_edge_geodataframe(graph: MultiDiGraphAny) -> gpd.GeoDataFrame:
    """Build edge GeoDataFrame from a graph, ensuring WGS84 CRS."""
    edge_geodataframe = _graph_to_edge_geodataframe(graph)

    return edge_geodataframe.set_crs("EPSG:4326", allow_override=True)


def load_boundary_geometry(place_name: str) -> ShapelyMultiPolygon:
    """Load and normalize place boundary geometry as a MultiPolygon."""
    boundary_geodataframe = _geocode_place_to_geodataframe(place_name)
    boundary_geometry = boundary_geodataframe.geometry.iloc[0]

    if isinstance(boundary_geometry, ShapelyPolygon):
        return ShapelyMultiPolygon([boundary_geometry])

    if isinstance(boundary_geometry, ShapelyMultiPolygon):
        return boundary_geometry

    error_message = f"Unexpected geometry type: {type(boundary_geometry)}"

    raise TypeError(error_message)


def load_graph_state(
    *,
    place_name: str,
    overlay_directory: str,
    graph_state: LoadedGraphState,
) -> None:
    """Load graphs, overlays, edge indexes, and boundaries into state."""
    bike_graph = _load_graph_from_place(place_name, network_type="bike")
    walk_graph = _load_graph_from_place(place_name, network_type="walk")

    load_and_apply_overlays(bike_graph, overlay_directory)
    load_and_apply_overlays(walk_graph, overlay_directory)

    graph_state.cycling_graph = bike_graph
    graph_state.walking_graph = walk_graph
    graph_state.cycling_nodes = _build_node_geodataframe(bike_graph)
    graph_state.walking_nodes = _build_node_geodataframe(walk_graph)
    graph_state.cycling_edges = _build_edge_geodataframe(bike_graph)
    graph_state.walking_edges = _build_edge_geodataframe(walk_graph)
    graph_state.boundary_geometry = load_boundary_geometry(place_name)


def get_graph_for_travel_mode(
    graph_state: LoadedGraphState,
    travel_mode: TravelMode,
) -> MultiDiGraphAny:
    """Return the loaded graph for the requested transport mode."""
    selected_graph = (
        graph_state.cycling_graph
        if travel_mode == "cycling"
        else graph_state.walking_graph
    )

    if selected_graph is None:
        raise HTTPException(status_code=500, detail="Graph not loaded.")

    return selected_graph


def get_edge_geodataframe_for_travel_mode(
    graph_state: LoadedGraphState,
    travel_mode: TravelMode,
) -> gpd.GeoDataFrame:
    """Return the loaded edge GeoDataFrame for the requested transport mode."""
    selected_edges = (
        graph_state.cycling_edges
        if travel_mode == "cycling"
        else graph_state.walking_edges
    )

    if selected_edges is None:
        raise HTTPException(status_code=500, detail="Edge index not loaded.")

    return selected_edges


def get_node_geodataframe_for_travel_mode(
    graph_state: LoadedGraphState,
    travel_mode: TravelMode,
) -> gpd.GeoDataFrame:
    """Return the loaded node GeoDataFrame for the requested transport mode."""
    selected_nodes = (
        graph_state.cycling_nodes
        if travel_mode == "cycling"
        else graph_state.walking_nodes
    )

    if selected_nodes is None:
        raise HTTPException(status_code=500, detail="Node index not loaded.")

    return selected_nodes


def validate_coordinate_within_boundary(
    graph_state: LoadedGraphState,
    longitude: float,
    latitude: float,
) -> None:
    """Validate that a coordinate is inside the configured boundary."""
    boundary_polygon = graph_state.boundary_geometry

    if boundary_polygon is None:
        return

    if not boundary_polygon.covers(ShapelyPoint(longitude, latitude)):
        raise HTTPException(status_code=400, detail="Point is outside boundary.")
