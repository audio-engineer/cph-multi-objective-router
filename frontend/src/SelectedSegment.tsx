import { Polyline, useMap } from "react-leaflet";
import { useEffect, useMemo } from "react";
import L from "leaflet";
import type { LineString, StepResponse } from "@/client";
import { fitBoundsRightOfPanel } from "@/utils.ts";

interface SelectedSegmentProps {
  lineString: LineString;
  step: StepResponse | null;
}

export const SelectedSegment = ({ lineString, step }: SelectedSegmentProps) => {
  const map = useMap();

  const positions = useMemo(() => {
    if (!step) {
      return null;
    }

    const from = Math.max(0, step.segment_index_from);
    const to = Math.min(
      lineString.coordinates.length - 1,
      step.segment_index_to,
    );

    if (to <= from) {
      return null;
    }

    return lineString.coordinates.slice(from, to + 1);
  }, [lineString, step]);

  useEffect(() => {
    if (!positions || positions.length === 0) {
      return;
    }

    const bounds = L.latLngBounds(
      positions.map((pos) => L.latLng(pos[1], pos[0])),
    );

    if (bounds.isValid()) {
      // map.fitBounds(bounds, { padding: [40, 40], maxZoom: 18 });

      fitBoundsRightOfPanel(map, bounds);
    }
  }, [positions, map]);

  if (!positions) {
    return null;
  }

  return (
    <Polyline
      positions={positions.map((pos) => L.latLng(pos[1], pos[0]))}
      pathOptions={{
        weight: 6,
        opacity: 0.8,
        color: "#bc1f1f",
      }}
    />
  );
};
