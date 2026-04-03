import type { GeoJsonObject, Feature, Polygon, MultiPolygon } from "geojson";
import type {
  BoundaryFeature,
  BoundaryFeatureCollection,
  GraphLayerFeatureCollection,
  OverlayFeatureCollection,
  RouteFeatureCollection,
} from "@/client";
import L from "leaflet";
import { basePadding, leftMargin, routeColors } from "@/constants.ts";

export const toGeoJsonObject = (
  featureCollection:
    | RouteFeatureCollection
    | BoundaryFeatureCollection
    | OverlayFeatureCollection
    | GraphLayerFeatureCollection,
): GeoJsonObject => {
  const copy = { ...featureCollection };

  // TODO Figure out what to do with those properties
  // if (copy.bbox === null) {
  //   delete copy.bbox;
  // }

  return copy as GeoJsonObject;
};

export const toTurfFeature = (
  feature: BoundaryFeature,
): Feature<Polygon | MultiPolygon> => {
  const geometry: MultiPolygon = {
    type: feature.geometry.type,
    coordinates: feature.geometry.coordinates,
    ...(feature.geometry.bbox == null ? {} : { bbox: feature.geometry.bbox }),
  };

  return {
    type: "Feature",
    geometry,
    properties: feature.properties,
    // TODO Figure out what to do with those properties
    // ...(feature.id == null ? {} : { id: feature.id }),
    // ...(feature.bbox == null ? {} : { bbox: feature.bbox }),
  };
};

export const fitBoundsBesidePanel = (
  map: L.Map,
  bounds: L.LatLngBounds,
  padding = 0,
) => {
  // Left margin + route panel width + base padding + padding
  const totalLeftPadding = leftMargin + padding;

  map.fitBounds(bounds, {
    paddingTopLeft: [totalLeftPadding, basePadding],
    paddingBottomRight: [basePadding, basePadding],
    maxZoom: 18,
  });
};

export const getRouteColor = (routeIndex: number) =>
  routeColors[routeIndex % routeColors.length];

export const capitalize = (string: string) =>
  string.charAt(0).toUpperCase() + string.slice(1);
