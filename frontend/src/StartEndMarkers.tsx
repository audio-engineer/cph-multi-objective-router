import { Marker, Popup } from "react-leaflet";
import type { Point } from "@/client";
import { type Marker as LeafletMarker } from "leaflet";

export const StartEndMarkers = ({
  start,
  end,
  onStartDragEnd,
  onEndDragEnd,
}: {
  start: Point | null;
  end: Point | null;
  onStartDragEnd: (pos: Point) => Promise<boolean>;
  onEndDragEnd: (pos: Point) => Promise<boolean>;
}) => {
  if (!start && !end) {
    return null;
  }

  return (
    <>
      {start && (
        <Marker
          position={{ lng: start.coordinates[0], lat: start.coordinates[1] }}
          draggable
          eventHandlers={{
            dragend: (dragEndEvent) => {
              const marker = dragEndEvent.target as LeafletMarker;
              const { lng, lat } = marker.getLatLng();

              void onStartDragEnd({
                type: "Point",
                coordinates: [lng, lat] as [number, number],
              });
            },
          }}
        >
          <Popup>Start</Popup>
        </Marker>
      )}
      {end && (
        <Marker
          position={{ lng: end.coordinates[0], lat: end.coordinates[1] }}
          draggable
          eventHandlers={{
            dragend: (dragEndEvent) => {
              const marker = dragEndEvent.target as LeafletMarker;
              const { lng, lat } = marker.getLatLng();

              void onEndDragEnd({
                type: "Point",
                coordinates: [lng, lat] as [number, number],
              });
            },
          }}
        >
          <Popup>End</Popup>
        </Marker>
      )}
    </>
  );
};
