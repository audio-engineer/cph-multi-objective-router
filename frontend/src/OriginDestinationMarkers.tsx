import { Marker, Popup } from "react-leaflet";
import type { Point } from "@/client";
import { type Marker as LeafletMarker } from "leaflet";

interface OriginDestinationMarkersProps {
  origin: Point | null;
  destination: Point | null;
  onOriginDragEnd: (position: Point) => Promise<boolean>;
  onDestinationDragEnd: (position: Point) => Promise<boolean>;
}

export const OriginDestinationMarkers = ({
  origin,
  destination,
  onOriginDragEnd,
  onDestinationDragEnd,
}: OriginDestinationMarkersProps) => {
  if (!origin && !destination) {
    return null;
  }

  return (
    <>
      {origin && (
        <Marker
          position={{ lng: origin.coordinates[0], lat: origin.coordinates[1] }}
          draggable
          eventHandlers={{
            dragend: (dragEndEvent) => {
              const marker = dragEndEvent.target as LeafletMarker;
              const { lng, lat } = marker.getLatLng();

              void onOriginDragEnd({
                type: "Point",
                coordinates: [lng, lat] as [number, number],
              });
            },
          }}
        >
          <Popup>Origin</Popup>
        </Marker>
      )}
      {destination && (
        <Marker
          position={{
            lng: destination.coordinates[0],
            lat: destination.coordinates[1],
          }}
          draggable
          eventHandlers={{
            dragend: (dragEndEvent) => {
              const marker = dragEndEvent.target as LeafletMarker;
              const { lng, lat } = marker.getLatLng();

              void onDestinationDragEnd({
                type: "Point",
                coordinates: [lng, lat] as [number, number],
              });
            },
          }}
        >
          <Popup>Destination</Popup>
        </Marker>
      )}
    </>
  );
};
