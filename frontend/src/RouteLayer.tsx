import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import type { RouteFeatureCollection } from "@/client";
import { fitBoundsRightOfPanel, toGeoJsonObject } from "@/utils.ts";

export const RouteLayer = ({
  route,
}: {
  route: RouteFeatureCollection | undefined;
}) => {
  const map = useMap();
  const layerRef = useRef<L.GeoJSON>(null);

  useEffect(() => {
    layerRef.current ??= L.geoJSON(undefined, {
      style: { weight: 5, opacity: 0.9 },
    }).addTo(map);

    const layer = layerRef.current;

    layer.clearLayers();

    if (route) {
      layer.addData(toGeoJsonObject(route));

      const bounds = layer.getBounds();

      if (bounds.isValid()) {
        fitBoundsRightOfPanel(map, bounds);
      }
    }
  }, [route, map]);

  return null;
};
