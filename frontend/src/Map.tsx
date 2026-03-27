import { useMemo } from "react";
import L from "leaflet";
import {
  GeoJSON,
  LayerGroup,
  LayersControl,
  MapContainer,
  TileLayer,
  ZoomControl,
} from "react-leaflet";
import { RouteLayer } from "@/RouteLayer.tsx";
import { OriginDestinationMarkers } from "@/OriginDestinationMarkers.tsx";
import { SelectedSegment } from "@/SelectedSegment.tsx";
import type {
  BoundaryFeatureCollection,
  RouteFeatureCollection,
  RouteFeature,
  Point,
  MultiPolygon,
} from "@/client";
import type { FeatureCollection } from "geojson";
import { toGeoJsonObject } from "@/utils.ts";
import { RouteBoundsController } from "@/RouteBoundsController.tsx";
import type { PickMode } from "@/RoutePanel.tsx";
import { MarkerPickController } from "@/MarkerPickController.tsx";
import { basePadding, leftMargin } from "@/constants.ts";
import { AttributeOverlay } from "@/AttributeOverlay.tsx";
import type { TransportMode } from "@/types/global.ts";
import { Box } from "@mantine/core";

interface MapProps {
  boundary: BoundaryFeatureCollection;
  routes: RouteFeatureCollection | undefined;
  selectedRouteIndex: number | null;
  originPosition: Point | null;
  destinationPosition: Point | null;
  onOriginDragged: (position: Point) => Promise<boolean>;
  onDestinationDragged: (position: Point) => Promise<boolean>;
  selectedStepIndex: number | null;
  pickMode: PickMode;
  onPickOrigin: (point: Point) => Promise<boolean>;
  onPickDestination: (point: Point) => Promise<boolean>;
  transportMode: TransportMode;
}

const extractOuterRingsAsHoles = (
  geometry: MultiPolygon,
): number[][][] | null => {
  const coords = geometry.coordinates;

  if (Array.isArray(coords)) {
    const holes: number[][][] = [];

    for (const poly of coords) {
      if (Array.isArray(poly) && Array.isArray(poly[0])) {
        holes.push(poly[0] as number[][]);
      }
    }

    return holes.length ? holes : null;
  }

  return null;
};

export const Map = ({
  boundary,
  routes,
  selectedRouteIndex,
  originPosition,
  destinationPosition,
  onOriginDragged,
  onDestinationDragged,
  selectedStepIndex,
  pickMode,
  onPickOrigin,
  onPickDestination,
  transportMode,
}: MapProps) => {
  const [minLong, minLat, maxLong, maxLat] = boundary.meta.bounds;
  const initialBounds = L.latLngBounds([minLat, minLong], [maxLat, maxLong]);

  const selectedRoute: RouteFeature | null =
    routes && selectedRouteIndex != null
      ? (routes.features[selectedRouteIndex] ?? null)
      : null;

  const visibleRoutes =
    routes && selectedRoute
      ? {
          ...routes,
          features: [selectedRoute],
        }
      : routes;

  const selectedStep =
    selectedRoute && selectedStepIndex != null
      ? (selectedRoute.properties.steps[selectedStepIndex] ?? null)
      : null;

  const maskGeoJson = useMemo<FeatureCollection | null>(() => {
    if (boundary.features.length === 0) {
      return null;
    }

    const geometry = boundary.features[0].geometry;

    const worldRing = [
      [-180, -90],
      [-180, 90],
      [180, 90],
      [180, -90],
      [-180, -90],
    ];

    const holes = extractOuterRingsAsHoles(geometry);

    if (!holes) {
      return null;
    }

    return {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {},
          geometry: {
            type: "Polygon",
            coordinates: [worldRing, ...holes],
          },
        },
      ],
    };
  }, [boundary]);

  return (
    <Box h="100vh" w="100%">
      <MapContainer
        bounds={initialBounds}
        boundsOptions={{
          paddingTopLeft: [leftMargin, basePadding],
          paddingBottomRight: [basePadding, basePadding],
          animate: true,
          maxZoom: 30,
        }}
        style={{ height: "100%", width: "100%" }}
        zoomControl={false}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {maskGeoJson && (
          <GeoJSON
            data={maskGeoJson}
            interactive={false}
            style={() => ({
              color: "#000",
              weight: 0,
              fillColor: "#000",
              fillOpacity: 0.2,
            })}
          />
        )}
        <GeoJSON
          data={toGeoJsonObject(boundary)}
          interactive={false}
          style={() => ({
            color: "#ff7878",
            weight: 1,
            fillOpacity: 0,
          })}
        />
        <RouteBoundsController
          route={visibleRoutes}
          selectedStepIndex={selectedStepIndex}
        />
        <MarkerPickController
          pickMode={pickMode}
          onPickOrigin={onPickOrigin}
          onPickDestination={onPickDestination}
        />
        <OriginDestinationMarkers
          origin={originPosition}
          destination={destinationPosition}
          onOriginDragEnd={onOriginDragged}
          onDestinationDragEnd={onDestinationDragged}
        />
        {/*<RouteLayer data={geoJson} />*/}
        {selectedRoute && (
          <SelectedSegment
            lineString={selectedRoute.geometry}
            step={selectedStep}
          />
        )}
        <LayersControl position="bottomright">
          <LayersControl.Overlay checked name="Route">
            <LayerGroup>
              <RouteLayer routes={visibleRoutes} />
            </LayerGroup>
          </LayersControl.Overlay>
          <LayersControl.Overlay name="Snow">
            <LayerGroup>
              <AttributeOverlay
                overlayAttribute="snow"
                transportMode={transportMode}
              />
            </LayerGroup>
          </LayersControl.Overlay>
          <LayersControl.Overlay name="Scenic">
            <LayerGroup>
              <AttributeOverlay
                overlayAttribute="scenic"
                transportMode={transportMode}
              />
            </LayerGroup>
          </LayersControl.Overlay>
          <LayersControl.Overlay name="Uphill">
            <LayerGroup>
              <AttributeOverlay
                overlayAttribute="uphill"
                transportMode={transportMode}
              />
            </LayerGroup>
          </LayersControl.Overlay>
        </LayersControl>
        <ZoomControl position="bottomright" />
      </MapContainer>
    </Box>
  );
};
