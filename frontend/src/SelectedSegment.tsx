import { Polyline, useMap } from "react-leaflet";
import { useEffect, useMemo } from "react";
import L from "leaflet";
import type { LineString, RouteStepSummary } from "@/client";
import { fitBoundsBesidePanel } from "@/utils.ts";

interface SelectedSegmentProps {
  lineString: LineString;
  selectedStep: RouteStepSummary | null;
}

export const SelectedSegment = ({
  lineString,
  selectedStep,
}: SelectedSegmentProps) => {
  const map = useMap();

  const segmentCoordinates = useMemo(() => {
    if (!selectedStep) {
      return null;
    }

    const startIndex = Math.max(0, selectedStep.segment_index_from);
    const endIndex = Math.min(
      lineString.coordinates.length - 1,
      selectedStep.segment_index_to,
    );

    if (endIndex <= startIndex) {
      return null;
    }

    return lineString.coordinates.slice(startIndex, endIndex + 1);
  }, [lineString, selectedStep]);

  useEffect(() => {
    if (!segmentCoordinates || segmentCoordinates.length === 0) {
      return;
    }

    const bounds = L.latLngBounds(
      segmentCoordinates.map((coordinate) =>
        L.latLng(coordinate[1], coordinate[0]),
      ),
    );

    if (bounds.isValid()) {
      // map.fitBounds(bounds, { padding: [40, 40], maxZoom: 18 });

      fitBoundsBesidePanel(map, bounds);
    }
  }, [segmentCoordinates, map]);

  if (!segmentCoordinates) {
    return null;
  }

  return (
    <Polyline
      positions={segmentCoordinates.map((coordinate) =>
        L.latLng(coordinate[1], coordinate[0]),
      )}
      pathOptions={{
        weight: 6,
        opacity: 0.8,
        color: "#bc1f1f",
      }}
    />
  );
};
