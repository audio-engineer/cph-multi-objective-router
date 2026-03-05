import type { GeoJsonObject, Feature, Polygon, MultiPolygon } from "geojson";
import type {
  BoundaryFeature,
  BoundaryFeatureCollection,
  LayerFeatureCollection,
  RouteFeatureCollection,
} from "@/client";
import L from "leaflet";
import { basePadding, leftMargin } from "@/constants.ts";

export const toGeoJsonObject = (
  featureCollection:
    | RouteFeatureCollection
    | BoundaryFeatureCollection
    | LayerFeatureCollection,
): GeoJsonObject => {
  const copy = { ...featureCollection };

  if (copy.bbox === null) {
    delete copy.bbox;
  }

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
    ...(feature.id == null ? {} : { id: feature.id }),
    ...(feature.bbox == null ? {} : { bbox: feature.bbox }),
  };
};

export const fitBoundsRightOfPanel = (
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
