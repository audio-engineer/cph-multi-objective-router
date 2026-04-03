"""Tests for graph layer filtering and feature serialization."""

import geopandas as gpd
from shapely.geometry import LineString, Point

from app.graph_layer_service import (
    build_graph_layer_feature_collection,
    filter_graph_features,
)


def test_filter_graph_features_applies_bbox_and_limit() -> None:
    """Graph feature filtering should keep rows within the bbox and obey the limit."""
    geodataframe = gpd.GeoDataFrame(
        {
            "geometry": [
                Point(12.0, 55.0),
                Point(12.4, 55.4),
                Point(13.0, 56.0),
            ]
        },
        geometry="geometry",
        crs="EPSG:4326",
    )

    filtered = filter_graph_features(
        geodataframe,
        bounding_box="11.9,54.9,12.5,55.5",
        max_features=2,
    )

    assert len(filtered) == 2


def test_build_graph_layer_feature_collection_serializes_points_and_lines() -> None:
    """Graph layer serialization should preserve point and line geometries."""
    node_geodataframe = gpd.GeoDataFrame(
        {"geometry": [Point(12.0, 55.0)]},
        geometry="geometry",
        crs="EPSG:4326",
    )
    edge_geodataframe = gpd.GeoDataFrame(
        {"geometry": [LineString([(12.0, 55.0), (12.1, 55.1)])]},
        geometry="geometry",
        crs="EPSG:4326",
    )

    node_collection = build_graph_layer_feature_collection(
        node_geodataframe,
        graph_layer_key="cycling_nodes",
        bounding_box=None,
        max_features=10,
    )
    edge_collection = build_graph_layer_feature_collection(
        edge_geodataframe,
        graph_layer_key="walking_edges",
        bounding_box=None,
        max_features=10,
    )

    assert node_collection.features[0].geometry.type == "Point"
    assert node_collection.features[0].properties.graph_layer_key == "cycling_nodes"
    assert edge_collection.features[0].geometry.type == "LineString"
    assert edge_collection.features[0].properties.graph_layer_key == "walking_edges"
