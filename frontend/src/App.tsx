import {
  type PickMode,
  RoutePanel,
  type RoutePanelHandle,
} from "@/RoutePanel.tsx";
import { useEffect, useRef, useState } from "react";
import { Map } from "@/Map.tsx";
import type {
  RouteFeatureCollection,
  RouteFeature,
  Point,
  BoundaryFeatureCollection,
} from "@/client";
import { StatusBar } from "@/StatusBar.tsx";
import { Button, Loader, type MantineColor, Text } from "@mantine/core";
import { point as turfPoint } from "@turf/helpers";
import booleanPointInPolygon from "@turf/boolean-point-in-polygon";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import {
  createRouteFromCoordinatesRoutesByCoordinatesPostMutation,
  createRouteFromAddressRoutesByAddressPostMutation,
  getCurrentBoundaryBoundariesCurrentGetOptions,
  reverseGeocodeGeocodingReverseGetOptions,
} from "@/client/@tanstack/react-query.gen.ts";
import type { TransportMode } from "@/types/global.ts";
import { toTurfFeature } from "@/utils.ts";

type MarkerKind = "origin" | "destination";
type MarkerSource = "drag" | "pick";
type LastSearch =
  | { source: "address"; origin: string; destination: string }
  | { source: "coords"; origin: Point; destination: Point };
export type Mode = "shortest" | "advanced";
export type RouteSelectionMethod = "shortest" | "weighted" | "pareto";

const inBoundsBbox = (
  point: Point,
  boundaryFeatureCollection: BoundaryFeatureCollection,
) => {
  const [minLon, minLat, maxLon, maxLat] =
    boundaryFeatureCollection.meta.bounds;
  const [lon, lat] = point.coordinates;

  return lon >= minLon && lon <= maxLon && lat >= minLat && lat <= maxLat;
};

const isInsideBoundary = (
  point: Point,
  boundaryFeatureCollection: BoundaryFeatureCollection,
) => {
  if (!inBoundsBbox(point, boundaryFeatureCollection)) {
    return false;
  }

  const boundaryFeature = boundaryFeatureCollection.features[0];

  return booleanPointInPolygon(
    turfPoint(point.coordinates as [number, number]),
    toTurfFeature(boundaryFeature),
  );
};

const getErrorMessage = (error: unknown) => {
  if (isAxiosError(error)) {
    const data = error.response?.data as unknown;

    if (data && typeof data === "object" && "detail" in data) {
      const detail = (data as { detail?: unknown }).detail;

      if (typeof detail === "string") {
        return detail;
      }
    }

    return error.message;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return "Unknown error";
};

const App = () => {
  const [minBoundaryDelayDone, setMinBoundaryDelayDone] = useState(false);

  const [routes, setRoutes] = useState<RouteFeatureCollection>();
  const [selectedRouteIndex, setSelectedRouteIndex] = useState<number | null>(
    null,
  );
  const [selectedStepIndex, setSelectedStepIndex] = useState<number | null>(
    null,
  );

  const [pickMode, setPickMode] = useState<PickMode>(null);
  const [originPosition, setOriginPosition] = useState<Point | null>(null);
  const [destinationPosition, setDestinationPosition] = useState<Point | null>(
    null,
  );

  const routePanelRef = useRef<RoutePanelHandle>(null);

  const [status, setStatus] = useState("Ready.");
  const [statusColor, setStatusColor] = useState("green");
  const statusTimeoutRef = useRef<number | null>(null);

  const [transportMode, setTransportMode] = useState<TransportMode>("walk");

  const [mode, setMode] = useState<Mode>("shortest");
  const [method, setMethod] = useState<RouteSelectionMethod>("shortest");
  const [scenic, setScenic] = useState(0);
  const [snow, setSnow] = useState(0);
  const [uphill, setUphill] = useState(0);

  const lastSearchRef = useRef<LastSearch | null>(null);

  const queryClient = useQueryClient();

  const boundaryQuery = useQuery({
    ...getCurrentBoundaryBoundariesCurrentGetOptions(),
  });

  useEffect(() => {
    const timeout = setTimeout(() => {
      setMinBoundaryDelayDone(true);
    }, 1000);

    return () => {
      clearTimeout(timeout);
    };
  }, []);

  const boundary = boundaryQuery.data;

  const boundaryLoading =
    boundaryQuery.isLoading ||
    (boundaryQuery.isSuccess && !minBoundaryDelayDone);

  const boundaryErrorMessage = boundaryQuery.isError
    ? getErrorMessage(boundaryQuery.error)
    : null;

  const reverseGeocode = async (kind: MarkerKind, point: Point) => {
    const [lon, lat] = point.coordinates;

    try {
      const options = reverseGeocodeGeocodingReverseGetOptions({
        query: { longitude: lon, latitude: lat },
      });

      const data = await queryClient.fetchQuery(options);

      if (!data.address) {
        return;
      }

      if (kind === "origin") {
        routePanelRef.current?.setOrigin(data.address);

        return;
      }

      routePanelRef.current?.setDestination(data.address);
    } catch (error) {
      setStatusWithTtl(getErrorMessage(error), "red", 5000);
    }
  };

  const buildRouteOptions = () => ({
    route_selection_method: method,
    objective_weights: {
      scenic,
      avoid_snow: snow,
      avoid_uphill: uphill,
    },
  });

  const routeMutationSuccess = (data: RouteFeatureCollection) => {
    setRoutes(data);
    setSelectedRouteIndex(null);
    setSelectedStepIndex(null);
    setOriginPosition(data.meta.origin);
    setDestinationPosition(data.meta.destination);

    setStatusWithTtl("Ready.", "green", 500);
  };

  const routeAddressMutation = useMutation({
    ...createRouteFromAddressRoutesByAddressPostMutation(),
    onMutate: () => {
      setStatusWithTtl("Calculating route...", "blue", 1000);
    },
    onSuccess: routeMutationSuccess,
    onError: (error) => {
      setStatusWithTtl(getErrorMessage(error), "red", 5000);
    },
  });

  const routeCoordinatesMutation = useMutation({
    ...createRouteFromCoordinatesRoutesByCoordinatesPostMutation(),
    onMutate: () => {
      setStatusWithTtl("Calculating route...", "blue", 1000);
    },
    onSuccess: routeMutationSuccess,
    onError: (error) => {
      setStatusWithTtl(getErrorMessage(error), "red", 5000);
    },
  });

  const loading =
    routeAddressMutation.isPending || routeCoordinatesMutation.isPending;

  const searchByAddress = async (origin: string, destination: string) => {
    lastSearchRef.current = {
      source: "address",
      origin,
      destination,
    };

    await routeAddressMutation.mutateAsync({
      body: {
        transport_mode: transportMode,
        origin,
        destination,
        route_options: buildRouteOptions(),
      },
    });
  };

  const searchByCoords = async (origin: Point, destination: Point) => {
    lastSearchRef.current = {
      source: "coords",
      origin,
      destination,
    };

    try {
      await routeCoordinatesMutation.mutateAsync({
        body: {
          transport_mode: transportMode,
          origin,
          destination,
          route_options: buildRouteOptions(),
        },
      });

      return true;
    } catch {
      return false;
    }
  };

  const handleTransportModeChange = (transportMode: TransportMode) => {
    setTransportMode(transportMode);

    const lastSearch = lastSearchRef.current;

    if (!lastSearch) {
      return;
    }

    if (lastSearch.source === "address") {
      void routeAddressMutation.mutateAsync({
        body: {
          transport_mode: transportMode,
          origin: lastSearch.origin,
          destination: lastSearch.destination,
          route_options: buildRouteOptions(),
        },
      });

      return;
    }

    void routeCoordinatesMutation.mutateAsync({
      body: {
        transport_mode: transportMode,
        origin: lastSearch.origin,
        destination: lastSearch.destination,
        route_options: buildRouteOptions(),
      },
    });
  };

  const setStatusWithTtl = (
    message: string,
    color: MantineColor,
    ttlMs?: number,
  ) => {
    setStatus(message);
    setStatusColor(color);

    if (statusTimeoutRef.current) {
      clearTimeout(statusTimeoutRef.current);

      statusTimeoutRef.current = null;
    }

    if (ttlMs) {
      statusTimeoutRef.current = setTimeout(() => {
        setStatus("Ready.");
        setStatusColor("green");

        statusTimeoutRef.current = null;
      }, ttlMs) as unknown as number;
    }
  };

  const getMarkerPosition = (kind: MarkerKind) =>
    kind === "origin" ? originPosition : destinationPosition;

  const setMarkerPosition = (kind: MarkerKind, point: Point | null) => {
    if (kind === "origin") {
      setOriginPosition(point);

      return;
    }

    setDestinationPosition(point);
  };

  const getOtherMarkerPosition = (kind: MarkerKind) =>
    kind === "origin" ? destinationPosition : originPosition;

  const applyMarkerUpdate = async (
    kind: MarkerKind,
    position: Point,
    source: MarkerSource,
  ) => {
    const markerName = kind === "origin" ? "Origin" : "Destination";

    if (!boundary || !isInsideBoundary(position, boundary)) {
      setStatusWithTtl(
        `${markerName} marker must be inside Copenhagen Municipality.`,
        "red",
        2000,
      );

      return false;
    }

    const previousPosition = getMarkerPosition(kind);
    const otherMarkerPosition = getOtherMarkerPosition(kind);

    if (source === "pick") {
      setPickMode(null);
    }

    setMarkerPosition(kind, position);
    await reverseGeocode(kind, position);

    if (!otherMarkerPosition) {
      return true;
    }

    const origin = kind === "origin" ? position : otherMarkerPosition;
    const destination = kind === "destination" ? position : otherMarkerPosition;

    const ok = await searchByCoords(origin, destination);

    if (ok) {
      return true;
    }

    setStatusWithTtl(`${markerName} marker could not be set.`, "red", 2000);

    setMarkerPosition(kind, previousPosition ?? null);

    return false;
  };

  const onOriginDragged = async (position: Point) =>
    applyMarkerUpdate("origin", position, "drag");

  const onDestinationDragged = async (position: Point) =>
    applyMarkerUpdate("destination", position, "drag");

  const onPickOrigin = async (position: Point) =>
    applyMarkerUpdate("origin", position, "pick");

  const onPickDestination = async (position: Point) =>
    applyMarkerUpdate("destination", position, "pick");

  const onTogglePickOrigin = () => {
    setPickMode((pickMode) => (pickMode === "origin" ? null : "origin"));
  };

  const onTogglePickDestination = () => {
    setPickMode((pickMode) =>
      pickMode === "destination" ? null : "destination",
    );
  };

  const handleClearAll = () => {
    setPickMode(null);
    setOriginPosition(null);
    setDestinationPosition(null);
    setRoutes(undefined);
    setSelectedRouteIndex(null);
    setSelectedStepIndex(null);

    lastSearchRef.current = null;
    routePanelRef.current?.clearAllFields();

    setStatusWithTtl("Ready.", "green", 500);
  };

  useEffect(() => {
    if (pickMode === "origin") {
      setStatusWithTtl("Click on the map to place the origin marker.", "grape");
    }

    if (pickMode === "destination") {
      setStatusWithTtl(
        "Click on the map to place the destination marker.",
        "grape",
      );
    }

    if (!pickMode) {
      // setStatusWithTtl("Ready.", "green");
    }
  }, [destinationPosition, pickMode, originPosition]);

  if (boundaryLoading) {
    return (
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          height: "100vh",
        }}
      >
        <Loader />
      </div>
    );
  }

  if (boundaryErrorMessage || !boundary) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 12,
          justifyContent: "center",
          alignItems: "center",
          height: "100vh",
        }}
      >
        <Text>Map boundary could not be loaded.</Text>
        {boundaryErrorMessage && (
          <Text c="dimmed" size="sm">
            {boundaryErrorMessage}
          </Text>
        )}
        <Button
          onClick={() => {
            void boundaryQuery.refetch();
          }}
        >
          Retry
        </Button>
      </div>
    );
  }

  const selectedRoute: RouteFeature | null =
    routes && selectedRouteIndex != null
      ? (routes.features[selectedRouteIndex] ?? null)
      : null;

  return (
    <div style={{ height: "100vh", width: "100%" }}>
      <Map
        boundary={boundary}
        routes={routes}
        selectedRouteIndex={selectedRouteIndex}
        originPosition={originPosition}
        destinationPosition={destinationPosition}
        onOriginDragged={onOriginDragged}
        onDestinationDragged={onDestinationDragged}
        selectedStepIndex={selectedStepIndex}
        pickMode={pickMode}
        onPickOrigin={onPickOrigin}
        onPickDestination={onPickDestination}
        transportMode={transportMode}
      />
      <RoutePanel
        ref={routePanelRef}
        searchByAddress={searchByAddress}
        routes={routes}
        loading={loading}
        selectedRouteIndex={selectedRouteIndex}
        onSelectRouteIndex={(routeIndex) => {
          setSelectedRouteIndex(routeIndex);
          setSelectedStepIndex(null);
        }}
        onBackToRouteList={() => {
          setSelectedRouteIndex(null);
          setSelectedStepIndex(null);
        }}
        selectedRoute={selectedRoute}
        selectedStepIndex={selectedStepIndex}
        onSelectStepIndex={setSelectedStepIndex}
        onTogglePickOrigin={onTogglePickOrigin}
        onTogglePickDestination={onTogglePickDestination}
        pickMode={pickMode}
        hasOriginMarker={originPosition !== null}
        hasDestinationMarker={destinationPosition !== null}
        onClearAll={handleClearAll}
        transportMode={transportMode}
        setTransportMode={handleTransportModeChange}
        mode={mode}
        setMode={setMode}
        method={method}
        setMethod={setMethod}
        snow={snow}
        setSnow={setSnow}
        scenic={scenic}
        setScenic={setScenic}
        uphill={uphill}
        setUphill={setUphill}
      />
      <StatusBar message={status} color={statusColor} />
    </div>
  );
};

export default App;
