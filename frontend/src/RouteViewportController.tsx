import { useMap } from "react-leaflet";
import L from "leaflet";
import { fitBoundsBesidePanel, toGeoJsonObject } from "@/utils.ts";
import { useEffect } from "react";
import type { RouteFeatureCollection } from "@/client";

interface RouteBoundsControllerProps {
  routes: RouteFeatureCollection | undefined;
  selectedStepIndex: number | null;
}

export const RouteViewportController = ({
  routes,
  selectedStepIndex,
}: RouteBoundsControllerProps) => {
  const map = useMap();

  const fitDisplayedRouteBounds = () => {
    if (!routes) {
      return;
    }

    const bounds = L.geoJSON(toGeoJsonObject(routes)).getBounds();

    if (bounds.isValid()) {
      // map.fitBounds(bounds, { padding: [30, 30] });

      fitBoundsBesidePanel(map, bounds);
    }
  };

  useEffect(() => {
    fitDisplayedRouteBounds();

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routes]);

  useEffect(() => {
    if (selectedStepIndex === null) {
      fitDisplayedRouteBounds();
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedStepIndex, routes]);

  return null;
};
