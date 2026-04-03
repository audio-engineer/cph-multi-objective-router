"""Graph layer filtering and serialization logic."""

from typing import TYPE_CHECKING

from fastapi import HTTPException
from geojson_pydantic import LineString as PydanticLineString
from geojson_pydantic import Point as PydanticPoint
from geojson_pydantic.types import Position, Position2D
from shapely.geometry import LineString as ShapelyLineString
from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon as ShapelyPolygon

from app.models import (
    GraphEdgeFeature,
    GraphLayerFeatureCollection,
    GraphLayerFeatureProperties,
    GraphLayerKey,
    GraphNodeFeature,
)

if TYPE_CHECKING:
    import geopandas as gpd
    from shapely.coords import CoordinateSequence

from app.layer_service import parse_bounding_box_string


def filter_graph_features(
    geodataframe: gpd.GeoDataFrame,
    *,
    bounding_box: str | None,
    max_features: int,
) -> gpd.GeoDataFrame:
    """Filter graph features by bbox and row limit."""
    filtered_features = geodataframe

    if bounding_box is not None:
        min_longitude, min_latitude, max_longitude, max_latitude = (
            parse_bounding_box_string(bounding_box)
        )
        bounding_geometry = ShapelyPolygon.from_bounds(
            min_longitude,
            min_latitude,
            max_longitude,
            max_latitude,
        )
        matching_indices = filtered_features.sindex.query(
            bounding_geometry,
            predicate="intersects",
        )
        filtered_features = filtered_features.iloc[matching_indices]

    if len(filtered_features) > max_features:
        filtered_features = filtered_features.head(max_features)

    return filtered_features


def build_graph_layer_feature_collection(
    geodataframe: gpd.GeoDataFrame,
    *,
    graph_layer_key: GraphLayerKey,
    bounding_box: str | None,
    max_features: int,
) -> GraphLayerFeatureCollection:
    """Build graph layer FeatureCollection response from node or edge data."""
    filtered_features = filter_graph_features(
        geodataframe,
        bounding_box=bounding_box,
        max_features=max_features,
    )

    graph_features: list[GraphNodeFeature | GraphEdgeFeature] = []

    for row in filtered_features.itertuples():
        geometry = row.geometry

        if isinstance(geometry, ShapelyPoint):
            graph_features.append(
                GraphNodeFeature(
                    type="Feature",
                    properties=GraphLayerFeatureProperties(
                        graph_layer_key=graph_layer_key
                    ),
                    geometry=PydanticPoint(
                        type="Point",
                        coordinates=Position2D(
                            float(geometry.x),
                            float(geometry.y),
                        ),
                    ),
                )
            )
            continue

        if isinstance(geometry, ShapelyLineString):
            coordinates: CoordinateSequence = geometry.coords

            if len(coordinates) == 0:
                continue

            line_coordinates: list[Position] = [
                Position2D(float(longitude), float(latitude))
                for longitude, latitude in coordinates
            ]
            graph_features.append(
                GraphEdgeFeature(
                    type="Feature",
                    properties=GraphLayerFeatureProperties(
                        graph_layer_key=graph_layer_key
                    ),
                    geometry=PydanticLineString(
                        type="LineString",
                        coordinates=line_coordinates,
                    ),
                )
            )
            continue

        raise HTTPException(
            status_code=500,
            detail="Graph layer contains unsupported geometry.",
        )

    return GraphLayerFeatureCollection(
        type="FeatureCollection",
        features=graph_features,
    )
