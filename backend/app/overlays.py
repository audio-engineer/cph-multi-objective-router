"""Overlay loading and application logic for graph edges."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import geopandas as gpd
import numpy as np
import numpy.typing as npt
from shapely import STRtree
from shapely.geometry import LineString as ShapelyLineString
from shapely.geometry import MultiPolygon as ShapelyMultiPolygon
from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon as ShapelyPolygon

from app.models import OVERLAY_KEYS, OverlayKey
from app.value_parsing import parse_float_or_default

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.typing_aliases import EdgeAttributeMap, MultiDiGraphAny

type OverlayPolygonIndexArray = npt.NDArray[np.int64]
type MergeStrategy = Literal["max", "last"]


@dataclass(frozen=True, slots=True)
class OverlayAssignmentContext:
    """Shared context for applying one overlay attribute across graph edges."""

    graph: MultiDiGraphAny
    overlay_tree: STRtree
    overlay_polygons: list[ShapelyPolygon]
    polygon_value_by_id: dict[int, float]
    overlay_key: OverlayKey
    merge_strategy: MergeStrategy


def _resolve_overlay_path(relative_overlay_path: str) -> Path:
    """Resolve an overlay path relative to the backend directory."""
    backend_directory = Path(__file__).resolve().parent.parent

    return backend_directory / relative_overlay_path


def get_edge_geometry_linestring(
    graph: MultiDiGraphAny,
    source_node_id: int,
    target_node_id: int,
    edge_attributes: EdgeAttributeMap,
) -> ShapelyLineString:
    """Return edge geometry or fallback to a straight node-to-node segment."""
    geometry = edge_attributes.get("geometry")

    if isinstance(geometry, ShapelyLineString):
        return geometry

    start_node = graph.nodes[source_node_id]
    end_node = graph.nodes[target_node_id]

    start_longitude = parse_float_or_default(start_node.get("x"), default=0.0)
    start_latitude = parse_float_or_default(start_node.get("y"), default=0.0)
    end_longitude = parse_float_or_default(end_node.get("x"), default=0.0)
    end_latitude = parse_float_or_default(end_node.get("y"), default=0.0)

    return ShapelyLineString(
        [
            (start_longitude, start_latitude),
            (end_longitude, end_latitude),
        ]
    )


def load_overlay_geometries(
    relative_overlay_path: str,
) -> tuple[list[ShapelyPolygon], list[float]]:
    """Load overlay polygons and corresponding values from GeoJSON."""
    overlay_path = _resolve_overlay_path(relative_overlay_path)
    read_file = cast(
        "Callable[..., gpd.GeoDataFrame]",
        gpd.read_file,
    )
    overlay_geodataframe = read_file(overlay_path).to_crs("EPSG:4326")

    if "value" not in overlay_geodataframe.columns:
        error_message = (
            f"{relative_overlay_path} column 'value' not found in overlay GeoJSON."
        )

        raise ValueError(error_message)

    if overlay_geodataframe.empty:
        error_message = f"{relative_overlay_path} contains no features."

        raise ValueError(error_message)

    polygons: list[ShapelyPolygon] = []
    values: list[float] = []

    geometry_values = cast("list[object]", overlay_geodataframe.geometry.to_list())
    overlay_raw_values = cast("list[object]", overlay_geodataframe["value"].to_list())

    for geometry, raw_value in zip(
        geometry_values,
        overlay_raw_values,
        strict=True,
    ):
        overlay_value = parse_float_or_default(raw_value, default=0.0)

        if isinstance(geometry, ShapelyPolygon):
            polygons.append(geometry)
            values.append(overlay_value)
            continue

        if isinstance(geometry, ShapelyMultiPolygon):
            for polygon in geometry.geoms:
                polygons.append(polygon)
                values.append(overlay_value)
            continue

        error_message = (
            f"{relative_overlay_path} contains non-polygon geometry: {type(geometry)}"
        )

        raise TypeError(error_message)

    return polygons, values


def _collect_midpoint_overlay_values(
    midpoint: ShapelyPoint,
    candidate_polygon_indices: OverlayPolygonIndexArray,
    overlay_polygons: list[ShapelyPolygon],
    polygon_value_by_id: dict[int, float],
) -> list[float]:
    """Collect overlay values of polygons covering the midpoint."""
    overlay_values: list[float] = []

    candidate_index_list = cast(
        "list[int]", candidate_polygon_indices.astype(int).tolist()
    )

    for candidate_index in candidate_index_list:
        polygon = overlay_polygons[int(candidate_index)]

        if polygon.covers(midpoint):
            overlay_values.append(polygon_value_by_id[id(polygon)])

    return overlay_values


def _apply_overlay_key_to_edge(
    context: OverlayAssignmentContext,
    source_node_id: int,
    target_node_id: int,
    edge_attributes: EdgeAttributeMap,
) -> None:
    """Apply overlay value to a single edge when midpoint intersects polygons."""
    edge_linestring = get_edge_geometry_linestring(
        graph=context.graph,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_attributes=edge_attributes,
    )
    edge_midpoint = edge_linestring.interpolate(0.5, normalized=True)

    candidate_polygon_indices = context.overlay_tree.query(edge_midpoint)

    if len(candidate_polygon_indices) == 0:
        return

    matching_overlay_values = _collect_midpoint_overlay_values(
        midpoint=edge_midpoint,
        candidate_polygon_indices=candidate_polygon_indices,
        overlay_polygons=context.overlay_polygons,
        polygon_value_by_id=context.polygon_value_by_id,
    )

    if not matching_overlay_values:
        return

    overlay_value = (
        max(matching_overlay_values)
        if context.merge_strategy == "max"
        else matching_overlay_values[-1]
    )
    edge_attributes[context.overlay_key] = float(overlay_value)


def initialize_edge_overlay_values(graph: MultiDiGraphAny) -> None:
    """Ensure every edge has all overlay attributes initialized to zero."""
    for source_node_id, target_node_id, edge_attributes in graph.edges(data=True):
        _ = source_node_id, target_node_id

        for overlay_attribute in OVERLAY_KEYS:
            edge_attributes.setdefault(overlay_attribute, 0.0)


def apply_overlay_key(
    graph: MultiDiGraphAny,
    overlay_key: OverlayKey,
    overlay_polygons: list[ShapelyPolygon],
    overlay_values: list[float],
    merge_strategy: MergeStrategy = "max",
) -> None:
    """Apply one overlay attribute across all graph edges."""
    context = OverlayAssignmentContext(
        graph=graph,
        overlay_tree=STRtree(overlay_polygons),
        overlay_polygons=overlay_polygons,
        polygon_value_by_id={
            id(polygon): value
            for polygon, value in zip(overlay_polygons, overlay_values, strict=True)
        },
        overlay_key=overlay_key,
        merge_strategy=merge_strategy,
    )

    for source_node_id, target_node_id, edge_attributes in graph.edges(data=True):
        _apply_overlay_key_to_edge(
            context=context,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            edge_attributes=edge_attributes,
        )


def load_and_apply_overlays(graph: MultiDiGraphAny, overlay_directory: str) -> None:
    """Load and apply all overlay files to a graph."""
    initialize_edge_overlay_values(graph)

    for overlay_attribute in OVERLAY_KEYS:
        polygons, values = load_overlay_geometries(
            f"{overlay_directory}/{overlay_attribute}.json"
        )
        apply_overlay_key(
            graph=graph,
            overlay_key=overlay_attribute,
            overlay_polygons=polygons,
            overlay_values=values,
            merge_strategy="max",
        )
