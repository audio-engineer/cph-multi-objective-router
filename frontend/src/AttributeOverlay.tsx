import {
  FeatureGroup,
  GeoJSON,
  Popup,
  useMap,
  useMapEvents,
} from "react-leaflet";
import type { OverlayAttribute, TransportMode } from "@/types/global.ts";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listLayersLayersGetOptions } from "@/client/@tanstack/react-query.gen.ts";
import { toGeoJsonObject } from "@/utils.ts";
import { Text } from "@mantine/core";
import type { Feature } from "geojson";
import L from "leaflet";

interface AttributeOverlayProps {
  overlayAttribute: OverlayAttribute;
  transportMode: TransportMode;
}

const boundsToBbox = (map: L.Map) => {
  const bounds = map.getBounds();

  return `${String(bounds.getWest())},${String(bounds.getSouth())},${String(bounds.getEast())},${String(bounds.getNorth())}`;
};

export const AttributeOverlay = ({
  overlayAttribute,
  transportMode,
}: AttributeOverlayProps) => {
  const map = useMap();

  const [bbox, setBbox] = useState<string>(() => boundsToBbox(map));

  useMapEvents({
    moveend: () => {
      setBbox(boundsToBbox(map));
    },
    zoomend: () => {
      setBbox(boundsToBbox(map));
    },
  });

  const layerQuery = useQuery({
    ...listLayersLayersGetOptions({
      query: {
        overlay_attribute: overlayAttribute,
        transport_mode: transportMode,
        bounding_box: bbox,
        minimum_value: 0.01,
        max_features: 20000,
      },
    }),
    placeholderData: (layerFeatureCollection) => layerFeatureCollection,
    staleTime: 0,
  });

  const style = useMemo(() => {
    let color = "#ffffff";

    switch (overlayAttribute) {
      case "snow":
        color = "#fa4561";
        break;
      case "scenic":
        color = "#4dfa8c";
        break;
      case "uphill":
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
  }, [overlayAttribute]);

  if (layerQuery.isLoading || !layerQuery.data) {
    return null;
  }

  return (
    <FeatureGroup>
      <Popup>
        <Text>
          {overlayAttribute.charAt(0).toUpperCase() + overlayAttribute.slice(1)}{" "}
          area
        </Text>
        {/*<Text>Intensity: {layerQuery.data.features[0].properties.value}/1</Text>*/}
      </Popup>
      <GeoJSON data={toGeoJsonObject(layerQuery.data)} style={style} />
    </FeatureGroup>
  );
};
