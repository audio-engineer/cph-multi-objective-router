import {
  FeatureGroup,
  GeoJSON,
  Popup,
  useMap,
  useMapEvents,
} from "react-leaflet";
import type {
  GraphLayerKey,
  MapOverlayKey,
  TravelMode,
} from "@/types/global.ts";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  listGraphLayerFeaturesGraphLayersGetOptions,
  listOverlayFeaturesLayersGetOptions,
} from "@/client/@tanstack/react-query.gen.ts";
import { capitalize, toGeoJsonObject } from "@/utils.ts";
import { Text } from "@mantine/core";
import type { Feature } from "geojson";
import L from "leaflet";

interface ThematicOverlayLayerProps {
  mapOverlayKey: MapOverlayKey;
  travelMode: TravelMode;
  graphLayerKey?: never;
}

interface GraphOverlayLayerProps {
  graphLayerKey: GraphLayerKey;
  travelMode?: never;
  mapOverlayKey?: never;
}

type OverlayLayerProps = ThematicOverlayLayerProps | GraphOverlayLayerProps;

const mapBoundsToBoundingBox = (map: L.Map) => {
  const bounds = map.getBounds();

  return `${String(bounds.getWest())},${String(bounds.getSouth())},${String(bounds.getEast())},${String(bounds.getNorth())}`;
};

export const OverlayLayer = ({
  mapOverlayKey,
  travelMode,
  graphLayerKey,
}: OverlayLayerProps) => {
  const map = useMap();
  const isGraphLayer = graphLayerKey !== undefined;
  const isNodeLayer = isGraphLayer && graphLayerKey.endsWith("_nodes");
  const pointColor =
    isGraphLayer && graphLayerKey.startsWith("cycling_")
      ? "#2f9e44"
      : "#1c7ed6";

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

  const graphLayerQuery = useQuery({
    ...listGraphLayerFeaturesGraphLayersGetOptions({
      query: {
        graph_layer_key: graphLayerKey ?? "cycling_edges",
        bounding_box: boundingBox,
        max_features: 108000,
      },
    }),
    enabled: isGraphLayer,
    placeholderData: (layerFeatureCollection) => layerFeatureCollection,
    staleTime: 0,
  });

  const thematicOverlayQuery = useQuery({
    ...listOverlayFeaturesLayersGetOptions({
      query: {
        overlay_key: mapOverlayKey ?? "snow",
        travel_mode: travelMode ?? "walking",
        bounding_box: boundingBox,
        minimum_value: 0.01,
        max_features: 20000,
      },
    }),
    enabled: !isGraphLayer,
    placeholderData: (layerFeatureCollection) => layerFeatureCollection,
    staleTime: 0,
  });

  const overlayData = isGraphLayer
    ? graphLayerQuery.data
    : thematicOverlayQuery.data;

  const style = (feature?: Feature) => {
    if (isGraphLayer) {
      return {
        color: pointColor,
        weight: isNodeLayer ? 1 : 2,
        opacity: 0.8,
      };
    }

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

    const value = Number(feature?.properties?.value ?? 0);
    const opacity = Math.max(0.1, Math.min(1, value));

    return {
      color,
      weight: 4,
      opacity,
    };
  };

  if (overlayData === undefined) {
    return null;
  }

  return (
    <FeatureGroup>
      <Popup>
        <Text>{capitalize(mapOverlayKey ?? graphLayerKey)} area</Text>
        {/*<Text>Intensity: {overlayQuery.data.features[0].properties.value}/1</Text>*/}
      </Popup>
      <GeoJSON
        data={toGeoJsonObject(overlayData)}
        style={style}
        pointToLayer={
          isNodeLayer
            ? (_feature, latlng) =>
                L.circleMarker(latlng, {
                  radius: 3,
                  color: pointColor,
                  weight: 1,
                  fillColor: pointColor,
                  fillOpacity: 0.75,
                })
            : undefined
        }
      />
    </FeatureGroup>
  );
};
