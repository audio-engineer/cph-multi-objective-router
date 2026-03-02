import {
  FeatureGroup,
  GeoJSON,
  Popup,
  useMap,
  useMapEvents,
} from "react-leaflet";
import type { Attribute, TravelMode } from "@/types/global.ts";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { layerLayerGetOptions } from "@/client/@tanstack/react-query.gen.ts";
import { toGeoJsonObject } from "@/utils.ts";
import { Text } from "@mantine/core";
import type { Feature } from "geojson";
import L from "leaflet";

interface AttributeOverlayProps {
  attribute: Attribute;
  travelMode: TravelMode;
}

const boundsToBbox = (map: L.Map) => {
  const bounds = map.getBounds();

  return `${String(bounds.getWest())},${String(bounds.getSouth())},${String(bounds.getEast())},${String(bounds.getNorth())}`;
};

export const AttributeOverlay = ({
  attribute,
  travelMode,
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
    ...layerLayerGetOptions({
      query: {
        attribute,
        mode: travelMode,
        bbox,
        min_value: 0.01,
        limit: 20000,
      },
    }),
    placeholderData: (layerFeatureCollection) => layerFeatureCollection,
    staleTime: 0,
  });

  const style = useMemo(() => {
    let color = "#ffffff";

    switch (attribute) {
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
  }, [attribute]);

  if (layerQuery.isLoading || !layerQuery.data) {
    return null;
  }

  return (
    <FeatureGroup>
      <Popup>
        <Text>{attribute}</Text>
      </Popup>
      <GeoJSON data={toGeoJsonObject(layerQuery.data)} style={style} />
    </FeatureGroup>
  );
};
