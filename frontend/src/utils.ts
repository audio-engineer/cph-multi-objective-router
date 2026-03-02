import type { GeoJsonObject } from "geojson";
import type {
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
