import type { PickMode } from "@/RoutePanel.tsx";
import type { Point } from "@/client";
import { useMapEvents } from "react-leaflet";

interface MarkerPickControllerProps {
  pickMode: PickMode;
  onPickOrigin: (point: Point) => Promise<boolean>;
  onPickDestination: (point: Point) => Promise<boolean>;
}

export const MarkerPickController = ({
  pickMode,
  onPickOrigin,
  onPickDestination,
}: MarkerPickControllerProps) => {
  useMapEvents({
    click: (leafletMouseEvent) => {
      if (!pickMode) {
        return;
      }

      const point: Point = {
        type: "Point",
        coordinates: [
          leafletMouseEvent.latlng.lng,
          leafletMouseEvent.latlng.lat,
        ],
      };

      if (pickMode === "origin") {
        void onPickOrigin(point);

        return;
      }

      void onPickDestination(point);
    },
  });

  return null;
};
