import L from "leaflet";
import { Polyline } from "react-leaflet";
import type { RouteFeatureCollection } from "@/client";
import { getRouteColor } from "@/utils.ts";

interface RouteLayerProps {
  routes: RouteFeatureCollection | undefined;
}

export const RouteLayer = ({ routes }: RouteLayerProps) => {
  if (!routes) {
    return null;
  }

  return routes.features.map((route) => (
    <Polyline
      key={route.properties.route_index}
      positions={route.geometry.coordinates.map((coordinate) =>
        L.latLng(coordinate[1], coordinate[0]),
      )}
      pathOptions={{
        color: getRouteColor(route.properties.route_index),
        weight: 5,
        opacity: 0.9,
      }}
    />
  ));
};
