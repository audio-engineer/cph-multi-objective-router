"""Layer filtering and serialization logic."""

from typing import TYPE_CHECKING, cast

from fastapi import HTTPException
from geojson_pydantic import LineString as PydanticLineString
from geojson_pydantic.types import Position, Position2D
from shapely.geometry import LineString as ShapelyLineString
from shapely.geometry import Polygon as ShapelyPolygon

from app.models import (
    LayerFeature,
    LayerFeatureCollection,
    LayerProperties,
    OverlayAttribute,
)
from app.value_parsing import coerce_float

if TYPE_CHECKING:
    from collections.abc import Callable

    import geopandas as gpd
    from shapely.coords import CoordinateSequence

BOUNDING_BOX_PARTS = 4


def parse_bounding_box(bounding_box: str) -> tuple[float, float, float, float]:
    """Parse minLon,minLat,maxLon,maxLat string to numeric bounds."""
    parts = [part.strip() for part in bounding_box.split(",")]

    if len(parts) != BOUNDING_BOX_PARTS:
        raise HTTPException(
            status_code=400,
            detail="bbox must be minLon, minLat, maxLon, maxLat",
        )

    try:
        min_longitude, min_latitude, max_longitude, max_latitude = map(float, parts)
    except ValueError as exception:
        raise HTTPException(
            status_code=400,
            detail="bbox values must be numbers",
        ) from exception

    if min_longitude >= max_longitude or min_latitude >= max_latitude:
        raise HTTPException(status_code=400, detail="bbox is invalid")

    return min_longitude, min_latitude, max_longitude, max_latitude


def filter_edges_for_layer(
    edge_geodataframe: gpd.GeoDataFrame,
    *,
    bounding_box: str | None,
    overlay_attribute: OverlayAttribute,
    minimum_attribute_value: float,
    feature_limit: int,
) -> gpd.GeoDataFrame:
    """Filter edges by bbox, overlay value threshold, and row limit."""
    filtered_edges = edge_geodataframe

    if bounding_box is not None:
        min_longitude, min_latitude, max_longitude, max_latitude = parse_bounding_box(
            bounding_box
        )
        bounding_geometry = ShapelyPolygon.from_bounds(
            min_longitude,
            min_latitude,
            max_longitude,
            max_latitude,
        )
        matching_indices = filtered_edges.sindex.query(
            bounding_geometry,
            predicate="intersects",
        )
        filtered_edges = filtered_edges.iloc[matching_indices]

    if overlay_attribute not in filtered_edges.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Missing edge attribute '{overlay_attribute}'.",
        )

    minimum_value = float(minimum_attribute_value)
    filtered_edges = filtered_edges[
        filtered_edges[overlay_attribute].astype(float) >= minimum_value
    ]

    if len(filtered_edges) > feature_limit:
        filtered_edges = filtered_edges.head(feature_limit)

    return filtered_edges


def build_layer_features(
    filtered_edges: gpd.GeoDataFrame,
    overlay_attribute: OverlayAttribute,
) -> list[LayerFeature]:
    """Convert filtered edge rows into layer GeoJSON features."""
    layer_features: list[LayerFeature] = []

    for row in filtered_edges.itertuples():
        geometry = row.geometry

        if not isinstance(geometry, ShapelyLineString):
            continue

        coordinates: CoordinateSequence = geometry.coords

        if len(coordinates) == 0:
            continue

        line_coordinates: list[Position] = [
            Position2D(float(longitude), float(latitude))
            for longitude, latitude in coordinates
        ]
        row_to_dict = cast("Callable[[], dict[str, object]]", row._asdict)
        row_values = row_to_dict()
        overlay_value = coerce_float(row_values.get(overlay_attribute), default=0.0)

        layer_features.append(
            LayerFeature(
                type="Feature",
                properties=LayerProperties(
                    overlay_attribute=overlay_attribute,
                    value=overlay_value,
                ),
                geometry=PydanticLineString(
                    type="LineString",
                    coordinates=line_coordinates,
                ),
            )
        )

    return layer_features


def build_layer_feature_collection(
    edge_geodataframe: gpd.GeoDataFrame,
    *,
    overlay_attribute: OverlayAttribute,
    bounding_box: str | None,
    minimum_attribute_value: float,
    feature_limit: int,
) -> LayerFeatureCollection:
    """Build layer FeatureCollection response from edge data."""
    filtered_edges = filter_edges_for_layer(
        edge_geodataframe,
        bounding_box=bounding_box,
        overlay_attribute=overlay_attribute,
        minimum_attribute_value=minimum_attribute_value,
        feature_limit=feature_limit,
    )
    layer_features = build_layer_features(filtered_edges, overlay_attribute)

    return LayerFeatureCollection(type="FeatureCollection", features=layer_features)
