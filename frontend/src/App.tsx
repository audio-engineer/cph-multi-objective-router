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
import {
  Box,
  Button,
  Flex,
  Loader,
  type MantineColor,
  Text,
} from "@mantine/core";
import { useLocalStorage } from "@mantine/hooks";
import { point as turfPoint } from "@turf/helpers";
import booleanPointInPolygon from "@turf/boolean-point-in-polygon";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import {
  createRouteFromAddressRoutesByAddressGetQueryKey,
  createRouteFromAddressRoutesByAddressGetOptions,
  createRouteFromCoordinatesRoutesByCoordinatesGetQueryKey,
  createRouteFromCoordinatesRoutesByCoordinatesGetOptions,
  getCurrentBoundaryBoundariesCurrentGetOptions,
  reverseGeocodeGeocodingReverseGetOptions,
} from "@/client/@tanstack/react-query.gen.ts";
import type { TransportMode } from "@/types/global.ts";
import { toTurfFeature } from "@/utils.ts";

type MarkerKind = "origin" | "destination";
type MarkerSource = "drag" | "pick";

export type Mode = "shortest" | "advanced";
export type RouteSelectionMethod = "shortest" | "weighted" | "pareto";

interface SearchSettings {
  transportMode: TransportMode;
  mode: Mode;
  method: RouteSelectionMethod;
  scenic: number;
  snow: number;
  uphill: number;
}

type AddressSearchRequest = SearchSettings & {
  source: "address";
  origin: string;
  destination: string;
};
type CoordinateSearchRequest = SearchSettings & {
  source: "coords";
  origin: Point;
  destination: Point;
};

type SearchRequest = AddressSearchRequest | CoordinateSearchRequest;

export interface SearchHistoryEntry {
  key: string;
  request: SearchRequest;
  originLabel: string;
  destinationLabel: string;
  createdAt: string;
}

const routeStaleTimeMs = 1000 * 60 * 60 * 24;
const historyStorageKey = "cph-multi-objective-router:search-history:v1";
const maxHistoryEntries = 20;
const sliderSearchDelayMs = 1000;

const normalizeAddress = (value: string) => value.trim().replace(/\s+/g, " ");

const normalizePoint = (point: Point): Point => ({
  ...point,
  coordinates: [
    Number(point.coordinates[0].toFixed(6)),
    Number(point.coordinates[1].toFixed(6)),
  ],
});

const resolveMethodForMode = (
  mode: Mode,
  method: RouteSelectionMethod,
): RouteSelectionMethod => {
  if (mode === "shortest") {
    return "shortest";
  }

  return method === "shortest" ? "weighted" : method;
};

const canonicalizeSearchRequest = (request: SearchRequest): SearchRequest => {
  const nextMethod = resolveMethodForMode(request.mode, request.method);
  const nextWeights =
    request.mode === "advanced"
      ? {
          scenic: request.scenic,
          snow: request.snow,
          uphill: request.uphill,
        }
      : {
          scenic: 0,
          snow: 0,
          uphill: 0,
        };

  if (request.source === "address") {
    return {
      ...request,
      origin: normalizeAddress(request.origin),
      destination: normalizeAddress(request.destination),
      method: nextMethod,
      ...nextWeights,
    };
  }

  return {
    ...request,
    origin: normalizePoint(request.origin),
    destination: normalizePoint(request.destination),
    method: nextMethod,
    ...nextWeights,
  };
};

const buildRouteQueryKey = (request: SearchRequest) => {
  const canonical = canonicalizeSearchRequest(request);

  if (canonical.source === "address") {
    return createRouteFromAddressRoutesByAddressGetQueryKey({
      query: {
        transport_mode: canonical.transportMode,
        origin: canonical.origin,
        destination: canonical.destination,
        route_selection_method: canonical.method,
        scenic: canonical.scenic,
        avoid_snow: canonical.snow,
        avoid_uphill: canonical.uphill,
        pareto_max_routes: 3,
      },
    });
  }

  return createRouteFromCoordinatesRoutesByCoordinatesGetQueryKey({
    query: {
      transport_mode: canonical.transportMode,
      origin_longitude: canonical.origin.coordinates[0],
      origin_latitude: canonical.origin.coordinates[1],
      destination_longitude: canonical.destination.coordinates[0],
      destination_latitude: canonical.destination.coordinates[1],
      route_selection_method: canonical.method,
      scenic: canonical.scenic,
      avoid_snow: canonical.snow,
      avoid_uphill: canonical.uphill,
      pareto_max_routes: 3,
    },
  });
};

const formatPointLabel = (point: Point) =>
  `${point.coordinates[1].toFixed(5)}, ${point.coordinates[0].toFixed(5)}`;

const upsertHistoryEntry = (
  currentEntries: SearchHistoryEntry[],
  nextEntry: SearchHistoryEntry,
) => {
  const withoutDuplicate = currentEntries.filter(
    (entry) => entry.key !== nextEntry.key,
  );

  return [nextEntry, ...withoutDuplicate].slice(0, maxHistoryEntries);
};

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

  const [routeLoading, setRouteLoading] = useState(false);
  const [committedSearch, setCommittedSearch] = useState<SearchRequest | null>(
    null,
  );
  const [searchHistory, setSearchHistory, removeSearchHistory] =
    useLocalStorage<SearchHistoryEntry[]>({
      key: historyStorageKey,
      defaultValue: [],
      getInitialValueInEffect: false,
    });

  const latestSearchIdRef = useRef(0);
  const sliderSearchTimeoutRef = useRef<number | null>(null);

  const queryClient = useQueryClient();

  const boundaryQuery = useQuery({
    ...getCurrentBoundaryBoundariesCurrentGetOptions(),
    staleTime: Infinity,
  });

  useEffect(() => {
    const timeout = setTimeout(() => {
      setMinBoundaryDelayDone(true);
    }, 1000);

    return () => {
      clearTimeout(timeout);
    };
  }, []);

  useEffect(() => {
    return () => {
      if (statusTimeoutRef.current != null) {
        clearTimeout(statusTimeoutRef.current);
      }

      if (sliderSearchTimeoutRef.current != null) {
        clearTimeout(sliderSearchTimeoutRef.current);
      }
    };
  }, []);

  const clearScheduledSliderSearch = () => {
    if (sliderSearchTimeoutRef.current != null) {
      clearTimeout(sliderSearchTimeoutRef.current);

      sliderSearchTimeoutRef.current = null;
    }
  };

  const boundary = boundaryQuery.data;

  const boundaryLoading =
    boundaryQuery.isLoading ||
    (boundaryQuery.isSuccess && !minBoundaryDelayDone);

  const boundaryErrorMessage = boundaryQuery.isError
    ? getErrorMessage(boundaryQuery.error)
    : null;

  const getCurrentSearchSettings = (
    overrides: Partial<SearchSettings> = {},
  ): SearchSettings => {
    const nextMode = overrides.mode ?? mode;
    const requestedMethod = overrides.method ?? method;

    return {
      transportMode: overrides.transportMode ?? transportMode,
      mode: nextMode,
      method: resolveMethodForMode(nextMode, requestedMethod),
      scenic: overrides.scenic ?? scenic,
      snow: overrides.snow ?? snow,
      uphill: overrides.uphill ?? uphill,
    };
  };

  const buildAddressSearchRequest = (
    origin: string,
    destination: string,
    overrides: Partial<SearchSettings> = {},
  ): AddressSearchRequest =>
    canonicalizeSearchRequest({
      source: "address",
      origin,
      destination,
      ...getCurrentSearchSettings(overrides),
    }) as AddressSearchRequest;

  const buildCoordinateSearchRequest = (
    origin: Point,
    destination: Point,
    overrides: Partial<SearchSettings> = {},
  ): CoordinateSearchRequest =>
    canonicalizeSearchRequest({
      source: "coords",
      origin,
      destination,
      ...getCurrentSearchSettings(overrides),
    }) as CoordinateSearchRequest;

  const rebuildCommittedSearch = (
    baseRequest: SearchRequest,
    overrides: Partial<SearchSettings> = {},
  ): SearchRequest => {
    if (baseRequest.source === "address") {
      return buildAddressSearchRequest(
        baseRequest.origin,
        baseRequest.destination,
        overrides,
      );
    }

    return buildCoordinateSearchRequest(
      baseRequest.origin,
      baseRequest.destination,
      overrides,
    );
  };

  const getAddressRouteQueryOptions = (request: AddressSearchRequest) =>
    createRouteFromAddressRoutesByAddressGetOptions({
      query: {
        transport_mode: request.transportMode,
        origin: request.origin,
        destination: request.destination,
        route_selection_method: request.method,
        scenic: request.scenic,
        avoid_snow: request.snow,
        avoid_uphill: request.uphill,
        pareto_max_routes: 3,
      },
    });

  const getCoordinateRouteQueryOptions = (request: CoordinateSearchRequest) =>
    createRouteFromCoordinatesRoutesByCoordinatesGetOptions({
      query: {
        transport_mode: request.transportMode,
        origin_longitude: request.origin.coordinates[0],
        origin_latitude: request.origin.coordinates[1],
        destination_longitude: request.destination.coordinates[0],
        destination_latitude: request.destination.coordinates[1],
        route_selection_method: request.method,
        scenic: request.scenic,
        avoid_snow: request.snow,
        avoid_uphill: request.uphill,
        pareto_max_routes: 3,
      },
    });

  const fetchRoute = async (request: SearchRequest) => {
    if (request.source === "address") {
      const options = getAddressRouteQueryOptions(request);

      return queryClient.fetchQuery({
        ...options,
        staleTime: routeStaleTimeMs,
      });
    }

    const options = getCoordinateRouteQueryOptions(request);

    return queryClient.fetchQuery({
      ...options,
      staleTime: routeStaleTimeMs,
    });
  };

  const applyRouteResult = (data: RouteFeatureCollection) => {
    setRoutes(data);
    setSelectedRouteIndex(null);
    setSelectedStepIndex(null);
    setOriginPosition(data.meta.origin);
    setDestinationPosition(data.meta.destination);
    setStatusWithTtl("Ready.", "green", 500);
  };

  const pushSearchHistory = (request: SearchRequest) => {
    const originLabel =
      request.source === "address"
        ? request.origin
        : formatPointLabel(request.origin);

    const destinationLabel =
      request.source === "address"
        ? request.destination
        : formatPointLabel(request.destination);

    const entry: SearchHistoryEntry = {
      key: JSON.stringify(buildRouteQueryKey(request)),
      request,
      originLabel,
      destinationLabel,
      createdAt: new Date().toISOString(),
    };

    setSearchHistory((currentEntries) =>
      upsertHistoryEntry(currentEntries, entry),
    );
  };

  const hasFreshCachedRoute = (request: SearchRequest) => {
    const queryState = queryClient.getQueryState<RouteFeatureCollection>(
      buildRouteQueryKey(request),
    );

    if (!queryState?.dataUpdatedAt) {
      return false;
    }

    if (routeStaleTimeMs === Infinity) {
      return true;
    }

    return Date.now() - queryState.dataUpdatedAt < routeStaleTimeMs;
  };

  const executeSearch = async (request: SearchRequest) => {
    const canonicalRequest = canonicalizeSearchRequest(request);
    const searchId = ++latestSearchIdRef.current;
    const cached = hasFreshCachedRoute(canonicalRequest);

    if (!cached) {
      setRouteLoading(true);
      setStatusWithTtl("Calculating route...", "blue");
    }

    try {
      const data = await fetchRoute(canonicalRequest);

      if (searchId !== latestSearchIdRef.current) {
        return true;
      }

      applyRouteResult(data);
      setCommittedSearch(canonicalRequest);
      pushSearchHistory(canonicalRequest);

      return true;
    } catch (error) {
      if (searchId === latestSearchIdRef.current) {
        setStatusWithTtl(getErrorMessage(error), "red", 5000);
      }

      return false;
    } finally {
      if (!cached && searchId === latestSearchIdRef.current) {
        setRouteLoading(false);
      }
    }
  };

  const searchByAddress = async (origin: string, destination: string) =>
    executeSearch(buildAddressSearchRequest(origin, destination));

  const searchByCoords = async (origin: Point, destination: Point) =>
    executeSearch(buildCoordinateSearchRequest(origin, destination));

  const scheduleCommittedSearchRefresh = (
    overrides: Partial<SearchSettings> = {},
  ) => {
    clearScheduledSliderSearch();

    if (!committedSearch) {
      return;
    }

    sliderSearchTimeoutRef.current = window.setTimeout(() => {
      sliderSearchTimeoutRef.current = null;
      void executeSearch(rebuildCommittedSearch(committedSearch, overrides));
    }, sliderSearchDelayMs);
  };

  const handleTransportModeChange = (nextTransportMode: TransportMode) => {
    clearScheduledSliderSearch();
    setTransportMode(nextTransportMode);

    if (!committedSearch) {
      return;
    }

    void executeSearch(
      rebuildCommittedSearch(committedSearch, {
        transportMode: nextTransportMode,
      }),
    );
  };

  const handleModeChange = (nextMode: Mode) => {
    clearScheduledSliderSearch();

    const nextMethod = resolveMethodForMode(
      nextMode,
      nextMode === "advanced" && method === "shortest" ? "weighted" : method,
    );

    setMode(nextMode);
    setMethod(nextMethod);

    if (!committedSearch) {
      return;
    }

    void executeSearch(
      rebuildCommittedSearch(committedSearch, {
        mode: nextMode,
        method: nextMethod,
      }),
    );
  };

  const handleMethodChange = (nextMethod: RouteSelectionMethod) => {
    clearScheduledSliderSearch();
    setMethod(nextMethod);

    if (!committedSearch) {
      return;
    }

    void executeSearch(
      rebuildCommittedSearch(committedSearch, {
        method: nextMethod,
      }),
    );
  };

  const handleScenicChangeEnd = (nextScenic: number) => {
    setScenic(nextScenic);
    scheduleCommittedSearchRefresh({ scenic: nextScenic });
  };

  const handleSnowChangeEnd = (nextSnow: number) => {
    setSnow(nextSnow);
    scheduleCommittedSearchRefresh({ snow: nextSnow });
  };

  const handleUphillChangeEnd = (nextUphill: number) => {
    setUphill(nextUphill);
    scheduleCommittedSearchRefresh({ uphill: nextUphill });
  };

  const handleSelectHistoryEntry = async (entry: SearchHistoryEntry) => {
    clearScheduledSliderSearch();

    setTransportMode(entry.request.transportMode);
    setMode(entry.request.mode);
    setMethod(entry.request.method);
    setScenic(entry.request.scenic);
    setSnow(entry.request.snow);
    setUphill(entry.request.uphill);

    if (entry.request.source === "address") {
      routePanelRef.current?.setOrigin(entry.request.origin);
      routePanelRef.current?.setDestination(entry.request.destination);
    } else {
      setOriginPosition(entry.request.origin);
      setDestinationPosition(entry.request.destination);
      routePanelRef.current?.setOrigin(entry.originLabel);
      routePanelRef.current?.setDestination(entry.destinationLabel);
    }

    await executeSearch(entry.request);
  };

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
    clearScheduledSliderSearch();

    setPickMode(null);
    setOriginPosition(null);
    setDestinationPosition(null);
    setRoutes(undefined);
    setSelectedRouteIndex(null);
    setSelectedStepIndex(null);
    setCommittedSearch(null);
    setRouteLoading(false);

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
      <Flex justify="center" align="center" h="100vh">
        <Loader />
      </Flex>
    );
  }

  if (boundaryErrorMessage || !boundary) {
    return (
      <Flex
        h="100vh"
        direction="column"
        gap={12}
        justify="center"
        align="center"
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
      </Flex>
    );
  }

  const selectedRoute: RouteFeature | null =
    routes && selectedRouteIndex != null
      ? (routes.features[selectedRouteIndex] ?? null)
      : null;

  return (
    <Box h="100vh" w="100%">
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
        loading={routeLoading}
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
        onTransportModeChange={handleTransportModeChange}
        mode={mode}
        onModeChange={handleModeChange}
        method={method}
        onMethodChange={handleMethodChange}
        scenic={scenic}
        onScenicChange={setScenic}
        onScenicChangeEnd={handleScenicChangeEnd}
        snow={snow}
        onSnowChange={setSnow}
        onSnowChangeEnd={handleSnowChangeEnd}
        uphill={uphill}
        onUphillChange={setUphill}
        onUphillChangeEnd={handleUphillChangeEnd}
        searchHistory={searchHistory}
        onSelectHistoryEntry={handleSelectHistoryEntry}
        onClearHistory={removeSearchHistory}
      />
      <StatusBar message={status} color={statusColor} />
    </Box>
  );
};

export default App;
