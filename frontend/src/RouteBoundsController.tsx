import { useMap } from "react-leaflet";
import L from "leaflet";
import { fitBoundsRightOfPanel, toGeoJsonObject } from "@/utils.ts";
import { useEffect } from "react";
import type { RouteFeatureCollection } from "@/client";

interface RouteBoundsControllerProps {
  route: RouteFeatureCollection | undefined;
  selectedStepIndex: number | null;
}

export const RouteBoundsController = ({
  route,
  selectedStepIndex,
}: RouteBoundsControllerProps) => {
  const map = useMap();

  const fitRouteBounds = () => {
    if (!route) {
      return;
    }

    const bounds = L.geoJSON(toGeoJsonObject(route)).getBounds();

    if (bounds.isValid()) {
      // map.fitBounds(bounds, { padding: [30, 30] });

      fitBoundsRightOfPanel(map, bounds);
    }
  };

  useEffect(() => {
    fitRouteBounds();

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route]);

  useEffect(() => {
    if (selectedStepIndex === null) {
      fitRouteBounds();
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedStepIndex, route]);

  return null;
};
