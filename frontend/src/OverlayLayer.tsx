import {
  FeatureGroup,
  GeoJSON,
  Popup,
  useMap,
  useMapEvents,
} from "react-leaflet";
import type { MapOverlayKey, TravelMode } from "@/types/global.ts";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listOverlayFeaturesLayersGetOptions } from "@/client/@tanstack/react-query.gen.ts";
import { capitalize, toGeoJsonObject } from "@/utils.ts";
import { Text } from "@mantine/core";
import type { Feature } from "geojson";
import L from "leaflet";

interface OverlayLayerProps {
  mapOverlayKey: MapOverlayKey;
  travelMode: TravelMode;
}

const mapBoundsToBoundingBox = (map: L.Map) => {
  const bounds = map.getBounds();

  return `${String(bounds.getWest())},${String(bounds.getSouth())},${String(bounds.getEast())},${String(bounds.getNorth())}`;
};

export const OverlayLayer = ({
  mapOverlayKey,
  travelMode,
}: OverlayLayerProps) => {
  const map = useMap();

  const [boundingBox, setBoundingBox] = useState(() =>
    mapBoundsToBoundingBox(map),
  );

  useMapEvents({
    moveend: () => {
      setBoundingBox(mapBoundsToBoundingBox(map));
    },
    zoomend: () => {
      setBoundingBox(mapBoundsToBoundingBox(map));
    },
  });

  const overlayQuery = useQuery({
    ...listOverlayFeaturesLayersGetOptions({
      query: {
        overlay_key: mapOverlayKey,
        travel_mode: travelMode,
        bounding_box: boundingBox,
        minimum_value: 0.01,
        max_features: 20000,
      },
    }),
    placeholderData: (layerFeatureCollection) => layerFeatureCollection,
    staleTime: 0,
  });

  const style = useMemo(() => {
    let color = "#ffffff";

    switch (mapOverlayKey) {
      case "snow":
        color = "#fa4561";
        break;
      case "scenic":
        color = "#4dfa8c";
        break;
      case "hills":
        color = "#a652ff";
        break;
    }

    return (feature?: Feature) => {
      const value = Number(feature?.properties?.value ?? 0);

      const opacity = Math.max(0.1, Math.min(1, value));

      return {
        color,
        weight: 4,
        opacity,
      };
    };
  }, [mapOverlayKey]);

  if (overlayQuery.isLoading || !overlayQuery.data) {
    return null;
  }

  return (
    <FeatureGroup>
      <Popup>
        <Text>{capitalize(mapOverlayKey)} area</Text>
        {/*<Text>Intensity: {overlayQuery.data.features[0].properties.value}/1</Text>*/}
      </Popup>
      <GeoJSON data={toGeoJsonObject(overlayQuery.data)} style={style} />
    </FeatureGroup>
  );
};
