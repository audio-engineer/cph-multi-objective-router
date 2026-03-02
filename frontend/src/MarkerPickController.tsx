import type { PickMode } from "@/RoutePanel.tsx";
import type { Point } from "@/client";
import { useMapEvents } from "react-leaflet";

interface MarkerPickControllerProps {
  pickMode: PickMode;
  onPickStart: (point: Point) => Promise<boolean>;
  onPickEnd: (point: Point) => Promise<boolean>;
}

export const MarkerPickController = ({
  pickMode,
  onPickStart,
  onPickEnd,
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

      if (pickMode === "start") {
        void onPickStart(point);

        return;
      }

      void onPickEnd(point);
    },
  });

  return null;
};
