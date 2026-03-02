import {
  type PickMode,
  RoutePanel,
  type RoutePanelHandle,
} from "@/RoutePanel.tsx";
import { useEffect, useRef, useState } from "react";
import { Map } from "@/Map.tsx";
import {
  type RouteFeatureCollection,
  type Point,
  type StepResponse,
  type BoundaryFeatureCollection,
} from "@/client";
import { StatusBar } from "@/StatusBar.tsx";
import { Button, Loader, type MantineColor, Text } from "@mantine/core";
import { point as turfPoint } from "@turf/helpers";
import booleanPointInPolygon from "@turf/boolean-point-in-polygon";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import {
  routeCoordinatesRouteCoordsPostMutation,
  routeRoutePostMutation,
  boundaryBoundaryGetOptions,
  reverseGeocodeReverseGetOptions,
} from "@/client/@tanstack/react-query.gen.ts";
import type { TravelMode } from "@/types/global.ts";

type MarkerKind = "start" | "end";
type MarkerSource = "drag" | "pick";
type LastSearch =
  | { source: "address"; from: string; to: string }
  | { source: "coords"; start: Point; end: Point };

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
    boundaryFeature,
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

  const [route, setRoute] = useState<RouteFeatureCollection>();
  const [distance, setDistance] = useState<number | null>(null);
  const [steps, setSteps] = useState<StepResponse[] | null>(null);
  const [selectedStepIndex, setSelectedStepIndex] = useState<number | null>(
    null,
  );

  const [pickMode, setPickMode] = useState<PickMode>(null);
  const [startPos, setStartPos] = useState<Point | null>(null);
  const [endPos, setEndPos] = useState<Point | null>(null);

  const routePanelRef = useRef<RoutePanelHandle>(null);

  const [status, setStatus] = useState("Ready.");
  const [statusColor, setStatusColor] = useState<MantineColor>("green");
  const statusTimeoutRef = useRef<number | null>(null);

  const [travelMode, setTravelMode] = useState<TravelMode>("walk");

  const lastSearchRef = useRef<LastSearch | null>(null);

  const queryClient = useQueryClient();

  const boundaryQuery = useQuery({
    ...boundaryBoundaryGetOptions(),
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
      const options = reverseGeocodeReverseGetOptions({
        query: { lon, lat },
      });

      const data = await queryClient.fetchQuery(options);

      if (!data.address) {
        return;
      }

      if (kind === "start") {
        routePanelRef.current?.setFrom(data.address);

        return;
      }

      routePanelRef.current?.setTo(data.address);
    } catch (error) {
      setStatusWithTtl(getErrorMessage(error), "red", 5000);
    }
  };

  const routeMutationSuccess = (data: RouteFeatureCollection) => {
    const properties = data.features[0].properties;

    setRoute(data);
    setDistance(properties.distance);
    setSteps(properties.steps);
    setSelectedStepIndex(null);
    setStartPos(data.meta.start);
    setEndPos(data.meta.end);

    setStatusWithTtl("Ready.", "green", 500);
  };

  const routeAddressMutation = useMutation({
    ...routeRoutePostMutation(),
    onMutate: () => {
      setStatusWithTtl("Calculating route...", "blue", 1000);
    },
    onSuccess: routeMutationSuccess,
    onError: (error) => {
      setStatusWithTtl(getErrorMessage(error), "red", 5000);
    },
  });

  const routeCoordinatesMutation = useMutation({
    ...routeCoordinatesRouteCoordsPostMutation(),
    onMutate: () => {
      setStatusWithTtl("Calculating route...", "blue", 1000);
    },
    onSuccess: routeMutationSuccess,
    onError: (error) => {
      setStatusWithTtl(getErrorMessage(error), "red", 5000);
    },
  });

  const loading = routeAddressMutation.isPending;

  const searchByAddress = async (from: string, to: string) => {
    lastSearchRef.current = { source: "address", from, to };

    await routeAddressMutation.mutateAsync({
      body: {
        travel_mode: travelMode,
        from,
        to,
      },
    });
  };

  const searchByCoords = async (start: Point, end: Point) => {
    lastSearchRef.current = { source: "coords", start, end };

    try {
      await routeCoordinatesMutation.mutateAsync({
        body: { travel_mode: travelMode, start, end },
      });

      return true;
    } catch {
      return false;
    }
  };

  const handleTravelModeChange = (mode: TravelMode) => {
    setTravelMode(mode);

    const lastSearch = lastSearchRef.current;

    if (!lastSearch) {
      return;
    }

    if (lastSearch.source === "address") {
      void routeAddressMutation.mutateAsync({
        body: {
          travel_mode: mode,
          from: lastSearch.from,
          to: lastSearch.to,
        },
      });

      return;
    }

    void routeCoordinatesMutation.mutateAsync({
      body: {
        travel_mode: mode,
        start: lastSearch.start,
        end: lastSearch.end,
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
      }, ttlMs);
    }
  };

  const getMarkerPosition = (kind: MarkerKind) =>
    kind === "start" ? startPos : endPos;

  const setMarkerPosition = (kind: MarkerKind, point: Point | null) => {
    if (kind === "start") {
      setStartPos(point);

      return;
    }

    setEndPos(point);
  };

  const getOtherMarkerPosition = (kind: MarkerKind) =>
    kind === "start" ? endPos : startPos;

  const applyMarkerUpdate = async (
    kind: MarkerKind,
    position: Point,
    source: MarkerSource,
  ) => {
    const markerName = kind === "start" ? "Start" : "End";

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

    const start = kind === "start" ? position : otherMarkerPosition;
    const end = kind === "end" ? position : otherMarkerPosition;

    const ok = await searchByCoords(start, end);

    if (ok) {
      return true;
    }

    setStatusWithTtl(`${markerName} marker could not be set.`, "red", 2000);

    setMarkerPosition(kind, previousPosition ?? null);

    return false;
  };

  const onStartDragged = async (pos: Point) =>
    applyMarkerUpdate("start", pos, "drag");

  const onEndDragged = async (pos: Point) =>
    applyMarkerUpdate("end", pos, "drag");

  const onPickStart = async (pos: Point) =>
    applyMarkerUpdate("start", pos, "pick");

  const onPickEnd = async (pos: Point) => applyMarkerUpdate("end", pos, "pick");

  const onTogglePickStart = () => {
    setPickMode((pickMode) => (pickMode === "start" ? null : "start"));
  };

  const onTogglePickEnd = () => {
    setPickMode((pickMode) => (pickMode === "end" ? null : "end"));
  };

  const clearAll = () => {
    setPickMode(null);
    setStartPos(null);
    setEndPos(null);
    setRoute(undefined);
    setDistance(null);
    setSteps(null);
    setSelectedStepIndex(null);

    lastSearchRef.current = null;
    routePanelRef.current?.clearAllFields();

    setStatusWithTtl("Ready.", "green", 500);
  };

  useEffect(() => {
    if (pickMode === "start") {
      setStatusWithTtl("Click on the map to place the start marker.", "grape");
    }

    if (pickMode === "end") {
      setStatusWithTtl("Click on the map to place the end marker.", "grape");
    }

    if (!pickMode) {
      // setStatusWithTtl("Ready.", "green");
    }
  }, [endPos, pickMode, startPos]);

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

  return (
    <div style={{ height: "100vh", width: "100%" }}>
      <Map
        boundary={boundary}
        route={route}
        startPosition={startPos}
        endPosition={endPos}
        onStartDragged={onStartDragged}
        onEndDragged={onEndDragged}
        steps={steps}
        selectedStepIndex={selectedStepIndex}
        pickMode={pickMode}
        onPickStart={onPickStart}
        onPickEnd={onPickEnd}
        travelMode={travelMode}
      />
      <RoutePanel
        ref={routePanelRef}
        searchByAddress={searchByAddress}
        distance={distance}
        loading={loading}
        steps={steps}
        selectedStepIndex={selectedStepIndex}
        onSelectStepIndex={setSelectedStepIndex}
        onTogglePickStart={onTogglePickStart}
        onTogglePickEnd={onTogglePickEnd}
        pickMode={pickMode}
        hasStartMarker={startPos !== null}
        hasEndMarker={endPos !== null}
        onClearAll={clearAll}
        travelMode={travelMode}
        setTravelMode={handleTravelModeChange}
      />
      <StatusBar message={status} color={statusColor} />
    </div>
  );
};

export default App;
