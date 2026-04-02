import type { Point } from "@/client";
import { useMapEvents } from "react-leaflet";
import type { ActiveRouteEndpoint } from "@/types/global.ts";

interface MarkerPickControllerProps {
  activeRouteEndpoint: ActiveRouteEndpoint;
  onPickOrigin: (point: Point) => Promise<boolean>;
  onPickDestination: (point: Point) => Promise<boolean>;
}

export const MarkerPickController = ({
  activeRouteEndpoint,
  onPickOrigin,
  onPickDestination,
}: MarkerPickControllerProps) => {
  useMapEvents({
    click: (leafletMouseEvent) => {
      if (!activeRouteEndpoint) {
        return;
      }

      const point: Point = {
        type: "Point",
        coordinates: [
          leafletMouseEvent.latlng.lng,
          leafletMouseEvent.latlng.lat,
        ],
      };

      if (activeRouteEndpoint === "origin") {
        void onPickOrigin(point);

        return;
      }

      void onPickDestination(point);
    },
  });

  return null;
};
