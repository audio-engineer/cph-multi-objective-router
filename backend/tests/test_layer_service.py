"""Tests for layer filtering and feature serialization."""

from typing import cast

import geopandas as gpd
import pytest
from fastapi import HTTPException
from shapely.geometry import LineString, Point

from app.layer_service import (
    build_overlay_feature_collection,
    build_overlay_features,
    filter_edges_for_overlay,
    parse_bounding_box_string,
)
from app.value_parsing import parse_float_or_default


def _build_layer_gdf() -> gpd.GeoDataFrame:
    """Build a small GeoDataFrame with line and non-line geometries."""
    geodataframe = gpd.GeoDataFrame(
        {
            "snow": [0.2, 0.9],
            "scenic": [0.1, 0.8],
            "geometry": [
                LineString([(12.0, 55.0), (12.1, 55.1)]),
                Point(12.2, 55.2),
            ],
        },
        crs="EPSG:4326",
    )

    return geodataframe


def test_parse_bounding_box_valid_and_invalid() -> None:
    """Bounding box parser should accept valid input and reject malformed input."""
    assert parse_bounding_box_string("12.0,55.0,13.0,56.0") == (12.0, 55.0, 13.0, 56.0)

    with pytest.raises(HTTPException):
        _ = parse_bounding_box_string("12.0,55.0,13.0")


def test_filter_edges_for_layer_applies_threshold_and_limit() -> None:
    """Layer filtering should keep rows above threshold and respect limit."""
    geodataframe = _build_layer_gdf()

    filtered = filter_edges_for_overlay(
        geodataframe,
        bounding_box=None,
        overlay_key="snow",
        minimum_overlay_value=0.5,
        max_features=10,
    )

    assert len(filtered) == 1
    assert parse_float_or_default(cast("object", filtered.iloc[0]["snow"])) == 0.9


def test_filter_edges_for_layer_raises_for_missing_attribute() -> None:
    """Filtering should fail when the requested overlay attribute is missing."""
    geodataframe = _build_layer_gdf()

    with pytest.raises(HTTPException):
        _ = filter_edges_for_overlay(
            geodataframe,
            bounding_box=None,
            overlay_key="hills",
            minimum_overlay_value=0.0,
            max_features=10,
        )


def test_build_layer_features_and_collection() -> None:
    """Feature builders should only include line geometries."""
    geodataframe = _build_layer_gdf()

    features = build_overlay_features(geodataframe, "snow")
    collection = build_overlay_feature_collection(
        geodataframe,
        overlay_key="snow",
        bounding_box=None,
        minimum_overlay_value=0.0,
        max_features=10,
    )

    assert len(features) == 1
    assert features[0].properties.overlay_key == "snow"
    assert len(collection.features) == 1
