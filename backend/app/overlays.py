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

from app.models import OVERLAY_ATTRIBUTE_NAMES, OverlayAttribute
from app.value_parsing import coerce_float

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.typing_aliases import EdgeAttributes, MultiDiGraphAny

type PolygonIndexArray = npt.NDArray[np.int64]


@dataclass(frozen=True, slots=True)
class OverlayApplicationContext:
    """Shared context for applying one overlay attribute across graph edges."""

    graph: MultiDiGraphAny
    overlay_tree: STRtree
    overlay_polygons: list[ShapelyPolygon]
    polygon_value_by_id: dict[int, float]
    overlay_attribute: OverlayAttribute
    combination_mode: Literal["max", "last"]


def _overlay_file_path(relative_overlay_path: str) -> Path:
    """Resolve an overlay path relative to the backend directory."""
    backend_directory = Path(__file__).resolve().parent.parent

    return backend_directory / relative_overlay_path


def get_edge_linestring(
    graph: MultiDiGraphAny,
    source_node_id: int,
    target_node_id: int,
    edge_attributes: EdgeAttributes,
) -> ShapelyLineString:
    """Return edge geometry or fallback to a straight node-to-node segment."""
    geometry = edge_attributes.get("geometry")

    if isinstance(geometry, ShapelyLineString):
        return geometry

    start_node = graph.nodes[source_node_id]
    end_node = graph.nodes[target_node_id]

    start_longitude = coerce_float(start_node.get("x"), default=0.0)
    start_latitude = coerce_float(start_node.get("y"), default=0.0)
    end_longitude = coerce_float(end_node.get("x"), default=0.0)
    end_latitude = coerce_float(end_node.get("y"), default=0.0)

    return ShapelyLineString(
        [
            (start_longitude, start_latitude),
            (end_longitude, end_latitude),
        ]
    )


def load_overlay_polygons(
    relative_overlay_path: str,
) -> tuple[list[ShapelyPolygon], list[float]]:
    """Load overlay polygons and corresponding values from GeoJSON."""
    overlay_path = _overlay_file_path(relative_overlay_path)
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
        overlay_value = coerce_float(raw_value, default=0.0)

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


def _collect_covering_overlay_values(
    midpoint: ShapelyPoint,
    candidate_indices: PolygonIndexArray,
    overlay_polygons: list[ShapelyPolygon],
    polygon_value_by_id: dict[int, float],
) -> list[float]:
    """Collect overlay values of polygons covering the midpoint."""
    overlay_values: list[float] = []

    candidate_index_list = cast("list[int]", candidate_indices.astype(int).tolist())

    for candidate_index in candidate_index_list:
        polygon = overlay_polygons[int(candidate_index)]

        if polygon.covers(midpoint):
            overlay_values.append(polygon_value_by_id[id(polygon)])

    return overlay_values


def _apply_overlay_to_edge(
    context: OverlayApplicationContext,
    source_node_id: int,
    target_node_id: int,
    edge_attributes: EdgeAttributes,
) -> None:
    """Apply overlay value to a single edge when midpoint intersects polygons."""
    edge_line = get_edge_linestring(
        graph=context.graph,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_attributes=edge_attributes,
    )
    midpoint = edge_line.interpolate(0.5, normalized=True)

    candidate_indices = context.overlay_tree.query(midpoint)

    if len(candidate_indices) == 0:
        return

    covering_values = _collect_covering_overlay_values(
        midpoint=midpoint,
        candidate_indices=candidate_indices,
        overlay_polygons=context.overlay_polygons,
        polygon_value_by_id=context.polygon_value_by_id,
    )

    if not covering_values:
        return

    overlay_value = (
        max(covering_values)
        if context.combination_mode == "max"
        else covering_values[-1]
    )
    edge_attributes[context.overlay_attribute] = float(overlay_value)


def initialize_overlay_attributes(graph: MultiDiGraphAny) -> None:
    """Ensure every edge has all overlay attributes initialized to zero."""
    for source_node_id, target_node_id, edge_attributes in graph.edges(data=True):
        _ = source_node_id, target_node_id

        for overlay_attribute in OVERLAY_ATTRIBUTE_NAMES:
            edge_attributes.setdefault(overlay_attribute, 0.0)


def apply_overlay_attribute(
    graph: MultiDiGraphAny,
    overlay_attribute: OverlayAttribute,
    overlay_polygons: list[ShapelyPolygon],
    overlay_values: list[float],
    combination_mode: Literal["max", "last"] = "max",
) -> None:
    """Apply one overlay attribute across all graph edges."""
    context = OverlayApplicationContext(
        graph=graph,
        overlay_tree=STRtree(overlay_polygons),
        overlay_polygons=overlay_polygons,
        polygon_value_by_id={
            id(polygon): value
            for polygon, value in zip(overlay_polygons, overlay_values, strict=True)
        },
        overlay_attribute=overlay_attribute,
        combination_mode=combination_mode,
    )

    for source_node_id, target_node_id, edge_attributes in graph.edges(data=True):
        _apply_overlay_to_edge(
            context=context,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            edge_attributes=edge_attributes,
        )


def apply_all_overlays(graph: MultiDiGraphAny, overlay_directory: str) -> None:
    """Load and apply all overlay files to a graph."""
    initialize_overlay_attributes(graph)

    for overlay_attribute in OVERLAY_ATTRIBUTE_NAMES:
        polygons, values = load_overlay_polygons(
            f"{overlay_directory}/{overlay_attribute}.json"
        )
        apply_overlay_attribute(
            graph=graph,
            overlay_attribute=overlay_attribute,
            overlay_polygons=polygons,
            overlay_values=values,
            combination_mode="max",
        )
