"""Multi-objective router back end."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast, get_args

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import requests
from fastapi import FastAPI, HTTPException
from geojson_pydantic import Feature as PydanticFeature
from geojson_pydantic import FeatureCollection as PydanticFeatureCollection
from geojson_pydantic import LineString as PydanticLineString
from geojson_pydantic import MultiPolygon as PydanticMultiPolygon
from geojson_pydantic import Point as PydanticPoint
from geojson_pydantic.types import Position2D, Position3D
from networkx.utils import pairwise
from pydantic import BaseModel, Field
from shapely import STRtree, box
from shapely.geometry import LineString as ShapelyLineString
from shapely.geometry import MultiPolygon as ShapelyMultiPolygon
from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry import mapping
from starlette.middleware.cors import CORSMiddleware

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from shapely.coords import CoordinateSequence

    type MultiDiGraphAny = nx.MultiDiGraph[Any]
else:
    MultiDiGraphAny = nx.MultiDiGraph


GRAPH_BIKE: MultiDiGraphAny | None = None
EDGES_BIKE: gpd.GeoDataFrame | None = None
GRAPH_WALK: MultiDiGraphAny | None = None
EDGES_WALK: gpd.GeoDataFrame | None = None
BOUNDARY: ShapelyMultiPolygon | None = None


@asynccontextmanager
# pylint: disable-next=unused-argument, redefined-outer-name
async def lifespan(app: FastAPI) -> AsyncGenerator[None, Any]:  # noqa: ARG001
    """Load graph on startup."""
    # pylint: disable-next=global-statement
    global GRAPH_BIKE, EDGES_BIKE, GRAPH_WALK, EDGES_WALK, BOUNDARY  # noqa: PLW0603

    place = "Copenhagen Municipality, Capital Region of Denmark, Denmark"

    GRAPH_BIKE = ox.graph_from_place(place, network_type="bike")
    GRAPH_WALK = ox.graph_from_place(place, network_type="walk")

    apply_all_overlays(GRAPH_BIKE, "data/overlays")
    apply_all_overlays(GRAPH_WALK, "data/overlays")

    EDGES_BIKE = build_edges_gdf(GRAPH_BIKE)
    EDGES_WALK = build_edges_gdf(GRAPH_WALK)

    boundary_gdf = ox.geocode_to_gdf(place)
    boundary_geometry = boundary_gdf.geometry.iloc[0]

    if isinstance(boundary_geometry, ShapelyPolygon):
        boundary_geometry = ShapelyMultiPolygon([boundary_geometry])

    if not isinstance(boundary_geometry, ShapelyMultiPolygon):
        type_error_message = f"Unexpected geometry type: {type(boundary_geometry)}"

        raise TypeError(type_error_message)

    BOUNDARY = boundary_geometry

    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    cast("Any", CORSMiddleware),
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ox.settings.nominatim_url = "http://localhost:8080/" # noqa: ERA001

TravelMode = Literal["bike", "walk"]
Attribute = Literal["snow", "scenic", "uphill"]


class RouteRequestCoordinate(BaseModel):
    """Route request with coordinates."""

    travel_mode: TravelMode
    start: PydanticPoint
    end: PydanticPoint


class RouteRequest(BaseModel):
    """Route request with addresses."""

    travel_mode: TravelMode
    from_: str = Field(alias="from")
    to: str


class StepResponse(BaseModel):
    """A step in the route."""

    street: str
    distance: float
    segment_index_from: int
    segment_index_to: int


class RouteProperties(BaseModel):
    """Properties of the route feature."""

    distance: float = Field(description="Route distance in metres")
    steps: list[StepResponse]


# pylint: disable-next=too-few-public-methods
class RouteFeature(PydanticFeature[PydanticLineString, RouteProperties]):
    """Route feature."""

    geometry: PydanticLineString
    properties: RouteProperties


class RouteMeta(BaseModel):
    """Metadata attached to the route response."""

    start: PydanticPoint
    end: PydanticPoint


# pylint: disable-next=too-few-public-methods
class RouteFeatureCollection(PydanticFeatureCollection[RouteFeature]):
    """FeatureCollection with metadata."""

    meta: RouteMeta


class BoundaryProperties(BaseModel):
    """Properties of the boundary feature."""

    name: str


# pylint: disable-next=too-few-public-methods
class BoundaryFeature(PydanticFeature[PydanticMultiPolygon, BoundaryProperties]):
    """Boundary feature."""

    geometry: PydanticMultiPolygon
    properties: BoundaryProperties


class BoundaryMeta(BaseModel):
    """Metadata attached to the boundary response."""

    bounds: tuple[float, float, float, float]


# pylint: disable-next=too-few-public-methods
class BoundaryFeatureCollection(PydanticFeatureCollection[BoundaryFeature]):
    """FeatureCollection with metadata."""

    meta: BoundaryMeta


class LayerProperties(BaseModel):
    """Properties of the layer feature."""

    attribute: Attribute
    value: float


# pylint: disable-next=too-few-public-methods
class LayerFeature(PydanticFeature[PydanticLineString, LayerProperties]):
    """Layer feature."""

    geometry: PydanticLineString
    properties: LayerProperties


# pylint: disable-next=too-few-public-methods
class LayerFeatureCollection(PydanticFeatureCollection[LayerFeature]):
    """FeatureCollection with metadata."""


class ReverseGeocodeResponse(BaseModel):
    """Reverse geocode response."""

    address: str


@dataclass
class Step:
    """A step in the route."""

    street: str
    distance: float
    segment_index_from: int
    segment_index_to: int


def edge_linestring(
    graph: MultiDiGraphAny, u: int, v: int, data: dict[str, Any]
) -> ShapelyLineString:
    """Return the linestring of the edge."""
    geometry = data.get("geometry")

    if isinstance(geometry, ShapelyLineString):
        return geometry

    # OSMnx node x=lon, y=lat
    return ShapelyLineString(
        [
            (graph.nodes[u]["x"], graph.nodes[u]["y"]),
            (graph.nodes[v]["x"], graph.nodes[v]["y"]),
        ]
    )


def load_overlay_polygons(path: str) -> tuple[list[ShapelyPolygon], list[float]]:
    """Load overlay polygons from GeoJSON."""
    gdf = gpd.read_file(Path(__file__).parent / ".." / path).to_crs("EPSG:4326")

    if "value" not in gdf.columns:
        value_error = f"{path} column 'value' not found in overlay GeoJSON."

        raise ValueError(value_error)

    if gdf.empty:
        value_error = f"{path} contains no features."

        raise ValueError(value_error)

    polygons: list[ShapelyPolygon] = []
    values: list[float] = []

    for geom, raw_value in zip(
        gdf.geometry.to_list(), gdf["value"].to_list(), strict=True
    ):
        value = float(raw_value)

        if isinstance(geom, ShapelyPolygon):
            polygons.append(geom)
            values.append(value)

            continue

        if isinstance(geom, ShapelyMultiPolygon):
            for poly in geom.geoms:
                polygons.append(poly)
                values.append(value)

            continue

        type_error = f"{path} contains non-polygon geometry: {type(geom)}"

        raise TypeError(type_error)

    return polygons, values


def _hit_values_for_point(
    midpoint: ShapelyPoint,
    candidates: np.ndarray,
    polygons: list[ShapelyPolygon],
    polygon_to_value: dict[int, float],
) -> list[float]:
    """Compute overlay hit values for a midpoint.

    Shapely's STRtree.query returns either indices (common in Shapely 2) or
    geometries depending on the configuration/version.
    """
    hit_vals: list[float] = []

    if len(candidates) == 0:
        return hit_vals

    if isinstance(candidates[0], (np.integer, int)):
        for idx in candidates:
            polygon = polygons[int(idx)]

            if polygon.covers(midpoint):
                hit_vals.append(polygon_to_value[id(polygon)])

    return hit_vals


def apply_overlay(
    graph: MultiDiGraphAny,
    attribute: str,
    polygons: list[ShapelyPolygon],
    values: list[float],
    combine: str = "max",
) -> None:
    """Apply an overlay to the graph."""
    tree = STRtree(polygons)
    polygon_to_value = {
        id(polygon): value for polygon, value in zip(polygons, values, strict=True)
    }

    for u, v, _, data in graph.edges(keys=True, data=True):
        line_string = edge_linestring(graph, u, v, data)
        midpoint = line_string.interpolate(0.5, normalized=True)

        candidates = tree.query(midpoint)

        if len(candidates) == 0:
            continue

        hit_vals = _hit_values_for_point(
            midpoint, candidates, polygons, polygon_to_value
        )

        if not hit_vals:
            continue

        new_val = max(hit_vals) if combine == "max" else hit_vals[-1]
        data[attribute] = float(new_val)


def initialize_edge_attributes(graph: MultiDiGraphAny) -> None:
    """Initialize edge attributes.

    Iterates over all edges in the graph and ensures that each edge's attribute
    dictionary contains all the custom attributes.
    """
    for _, _, _, data in graph.edges(keys=True, data=True):
        for attribute in get_args(Attribute):
            data.setdefault(attribute, 0.0)


def apply_all_overlays(graph: MultiDiGraphAny, overlay_dir: str) -> None:
    """Apply all overlays to the graph."""
    initialize_edge_attributes(graph)

    for attribute in get_args(Attribute):
        polygons, values = load_overlay_polygons(f"{overlay_dir}/{attribute}.json")

        apply_overlay(graph, attribute, polygons, values, combine="max")


def build_edges_gdf(graph: MultiDiGraphAny) -> gpd.GeoDataFrame:
    """Build a GeoDataFrame with edges."""
    # fill_edge_geometry=True ensures we always have LineString geometry
    gdf = ox.graph_to_gdfs(graph, nodes=False, edges=True, fill_edge_geometry=True)
    # Ensure CRS is set for bbox filtering
    gdf.set_crs("EPSG:4326", allow_override=True)

    return gdf


def parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    """Parse a bounding box string into minLon, minLat, maxLon, maxLat."""
    parts = [p.strip() for p in bbox.split(",")]
    number_of_parts = 4

    if len(parts) != number_of_parts:
        raise HTTPException(
            status_code=400, detail="bbox must be minLon, minLat, maxLon, maxLat"
        )

    try:
        min_lon, min_lat, max_lon, max_lat = map(float, parts)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="bbox values must be numbers"
        ) from exc

    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(status_code=400, detail="bbox is invalid")

    return min_lon, min_lat, max_lon, max_lat


def _as_str_name(value: str | list[Any] | None) -> str | None:
    if value is None:
        return None

    if isinstance(value, list) and value:
        return str(value[0])

    return str(value)


# pylint: disable-next=unsubscriptable-object
def build_route_steps(graph: nx.MultiDiGraph[Any], path: list[int]) -> list[Step]:
    """Build a step list.

    The step list includes all path segments along with street name, length, and
    indices.
    """
    steps: list[Step] = []

    current_name: str | None = None
    current_dist = 0.0
    current_from = 0
    current_to = 1

    for index, (u, v) in enumerate(pairwise(path)):
        edges = graph.get_edge_data(u, v)

        if not edges:
            continue

        # Choose the "best" edge between u->v; for shortest_path(weight="length"),
        # picking the minimal length edge usually matches the chosen route.
        data = min(edges.values(), key=lambda d: float(d.get("length", 1e18)))

        dist = float(data.get("length", 0.0))
        name = _as_str_name(data.get("name")) or _as_str_name(data.get("ref"))

        if not name:
            highway = _as_str_name(data.get("highway"))
            name = f"{highway} (unnamed)" if highway else "Unnamed road"

        if current_name is None:
            current_name = name
            current_dist = dist
            current_from = index
            current_to = index + 1
        elif name == current_name:
            current_dist += dist
            current_to = index + 1
        else:
            steps.append(
                Step(
                    street=current_name,
                    distance=current_dist,
                    segment_index_from=current_from,
                    segment_index_to=current_to,
                )
            )

            current_name = name
            current_dist = dist
            current_from = index
            current_to = index + 1

    if current_name is not None:
        steps.append(
            Step(
                street=current_name,
                distance=current_dist,
                segment_index_from=current_from,
                segment_index_to=current_to,
            )
        )

    return steps


def ensure_inside_boundary(lon: float, lat: float) -> None:
    """Raise an exception if the given point is outside the boundary."""
    if BOUNDARY is None:
        return

    if not BOUNDARY.covers(ShapelyPoint(lon, lat)):
        raise HTTPException(status_code=400, detail="Point is outside boundary.")


def build_feature_collection(
    lon_from: float, lat_from: float, lon_to: float, lat_to: float, mode: TravelMode
) -> RouteFeatureCollection:
    """Build a FeatureCollection with the route geometry."""
    graph = GRAPH_BIKE if mode == "bike" else GRAPH_WALK

    if graph is None:
        raise HTTPException(status_code=500, detail="Graph not loaded.")

    ensure_inside_boundary(lon_from, lat_from)
    ensure_inside_boundary(lon_to, lat_to)

    try:
        origin = ox.distance.nearest_nodes(graph, X=lon_from, Y=lat_from)
        destination = ox.distance.nearest_nodes(graph, X=lon_to, Y=lat_to)
    except Exception as exception:
        raise HTTPException(
            status_code=400, detail=f"Snapping to graph failed: {exception}"
        ) from exception

    try:
        path = nx.shortest_path(
            graph, source=origin, target=destination, weight="length"
        )
    except nx.exception.NetworkXNoPath:
        raise HTTPException(status_code=500, detail="No path found.") from None
    except Exception as exception:
        raise HTTPException(
            status_code=500, detail=f"Path calculation failed: {exception}"
        ) from exception

    steps = build_route_steps(graph, path)

    coordinates: list[Position2D | Position3D] = [
        Position2D(graph.nodes[node]["x"], graph.nodes[node]["y"]) for node in path
    ]

    start = Position2D(graph.nodes[origin]["x"], graph.nodes[origin]["y"])
    end = Position2D(graph.nodes[destination]["x"], graph.nodes[destination]["y"])

    distance = nx.path_weight(graph, path, weight="length")

    return RouteFeatureCollection(
        type="FeatureCollection",
        features=[
            RouteFeature(
                type="Feature",
                properties=RouteProperties(
                    distance=distance,
                    steps=[
                        StepResponse(
                            street=step.street,
                            distance=step.distance,
                            segment_index_from=step.segment_index_from,
                            segment_index_to=step.segment_index_to,
                        )
                        for step in steps
                    ],
                ),
                geometry=PydanticLineString(
                    type="LineString",
                    coordinates=coordinates,
                ),
            )
        ],
        meta=RouteMeta(
            start=PydanticPoint(
                type="Point",
                coordinates=start,
            ),
            end=PydanticPoint(
                type="Point",
                coordinates=end,
            ),
        ),
    )


def _filter_edges_view(
    gdf: gpd.GeoDataFrame,
    *,
    bbox: str | None,
    attribute: Attribute,
    min_value: float,
    limit: int,
) -> gpd.GeoDataFrame:
    """Apply bbox/value/limit filtering to the edge GeoDataFrame."""
    view = gdf

    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = parse_bbox(bbox)
        bbox_geometry = box(min_lon, min_lat, max_lon, max_lat)
        ifx = view.sindex.query(bbox_geometry, predicate="intersects")
        view = view.iloc[ifx]

    if attribute not in view.columns:
        raise HTTPException(
            status_code=400, detail=f"Missing edge attribute '{attribute}'."
        )

    view = view[view[attribute].astype(float) >= float(min_value)]

    if len(view) > limit:
        view = view.head(limit)

    return view


def _layer_features_from_view(
    view: gpd.GeoDataFrame, attribute: Attribute
) -> list[LayerFeature]:
    """Build layer features from a filtered edge view."""
    features: list[LayerFeature] = []

    for row in view.itertuples():
        geometry = row.geometry

        if geometry is None:
            continue

        if not isinstance(geometry, ShapelyLineString):
            continue

        coords: CoordinateSequence = geometry.coords

        if not coords:
            continue

        coordinates = [Position2D(float(x), float(y)) for x, y in coords]

        value = float(getattr(row, attribute))

        features.append(
            LayerFeature(
                type="Feature",
                properties=LayerProperties(
                    attribute=attribute,
                    value=value,
                ),
                geometry=PydanticLineString(
                    type="LineString",
                    coordinates=coordinates,
                ),
            )
        )

    return features


@app.get("/layer", response_model=LayerFeatureCollection)
def layer(
    attribute: Attribute,
    mode: TravelMode,
    bbox: str | None = None,
    min_value: float = 0.01,
    limit: int = 20000,
) -> LayerFeatureCollection:
    """Get a layer of the graph."""
    gdf = EDGES_BIKE if mode == "bike" else EDGES_WALK

    if gdf is None:
        raise HTTPException(status_code=500, detail="Edge index not loaded.")

    view = _filter_edges_view(
        gdf,
        bbox=bbox,
        attribute=attribute,
        min_value=min_value,
        limit=limit,
    )

    features = _layer_features_from_view(view, attribute)

    return LayerFeatureCollection(type="FeatureCollection", features=features)


@app.get("/boundary", response_model=BoundaryFeatureCollection)
def boundary() -> BoundaryFeatureCollection:
    """Get the boundary of the graph."""
    if BOUNDARY is None:
        raise HTTPException(status_code=500, detail="Graph not loaded.")

    bounds = BOUNDARY.bounds
    boundary_geometry = PydanticMultiPolygon.model_validate(mapping(BOUNDARY))

    return BoundaryFeatureCollection(
        type="FeatureCollection",
        features=[
            BoundaryFeature(
                type="Feature",
                properties=BoundaryProperties(name="Copenhagen Municipality"),
                geometry=boundary_geometry,
            )
        ],
        meta=BoundaryMeta(
            bounds=bounds,
        ),
    )


@app.post("/route", response_model=RouteFeatureCollection)
def route(request: RouteRequest) -> RouteFeatureCollection:
    """Get a route between two points."""
    try:
        lat_from, lon_from = ox.geocode(request.from_)
        lat_to, lon_to = ox.geocode(request.to)
    except Exception as exception:
        raise HTTPException(
            status_code=400, detail=f"Geocoding failed: {exception}"
        ) from exception

    return build_feature_collection(
        lon_from, lat_from, lon_to, lat_to, request.travel_mode
    )


@app.post("/route/coords", response_model=RouteFeatureCollection)
def route_coordinates(request: RouteRequestCoordinate) -> RouteFeatureCollection:
    """Get the coordinates of a route."""
    lon_from, lat_from = request.start.coordinates[:2]
    lon_to, lat_to = request.end.coordinates[:2]

    return build_feature_collection(
        lon_from, lat_from, lon_to, lat_to, request.travel_mode
    )


@app.get("/reverse")
def reverse_geocode(lon: float, lat: float, zoom: int = 18) -> ReverseGeocodeResponse:
    """Get the nearest address for the given coordinates."""
    url = ox.settings.nominatim_url.rstrip("/") + "/reverse"

    params: dict[str, str | int | float] = {
        "format": "jsonv2",
        "lat": lat,
        "lon": lon,
        "zoom": zoom,
    }

    headers = {
        "User-Agent": ox.settings.http_user_agent,
        "Referer": ox.settings.http_referer,
        "Accept-Language": ox.settings.http_accept_language,
    }

    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=ox.settings.requests_timeout,
        **ox.settings.requests_kwargs,
    )

    response.raise_for_status()

    json = response.json()

    address = json.get("address") or {}
    road = address.get("road") or ""
    house_number = address.get("house_number") or ""
    address_formatted = ", ".join([f"{road} {house_number}"])

    return ReverseGeocodeResponse(address=address_formatted)
