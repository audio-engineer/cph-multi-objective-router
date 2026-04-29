import { RoutePanel, type RoutePanelHandle } from "@/RoutePanel.tsx";
import { useEffect, useRef, useState } from "react";
import { Map } from "@/Map.tsx";
import type {
  RouteFeatureCollection,
  RouteFeature,
  Point,
  BoundaryFeatureCollection,
} from "@/client";
import { StatusNotice } from "@/StatusNotice.tsx";
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
  computeRouteByAddressRoutesByAddressGetQueryKey,
  computeRouteByAddressRoutesByAddressGetOptions,
  computeRouteByCoordinatesRoutesByCoordinatesGetQueryKey,
  computeRouteByCoordinatesRoutesByCoordinatesGetOptions,
  getCurrentBoundaryBoundariesCurrentGetOptions,
  reverseGeocodeGeocodingReverseGetOptions,
} from "@/client/@tanstack/react-query.gen.ts";
import type {
  ActiveRouteEndpoint,
  RouteEndpoint,
  TravelMode,
} from "@/types/global.ts";
import { toTurfFeature } from "@/utils.ts";

type MarkerSource = "drag" | "pick";

export type RoutePlanningMode = "shortest" | "multi-objective";
export type RouteOptimizationMethod = "shortest" | "weighted" | "pareto";

interface RouteSearchOptions {
  travelMode: TravelMode;
  routePlanningMode: RoutePlanningMode;
  routeOptimizationMethod: RouteOptimizationMethod;
  scenicWeight: number;
  snowFreeWeight: number;
  flatWeight: number;
}

interface AddressRouteSearchRequest extends RouteSearchOptions {
  source: "address";
  origin: string;
  destination: string;
}

interface CoordinateRouteSearchRequest extends RouteSearchOptions {
  source: "coordinates";
  origin: Point;
  destination: Point;
}

type RouteSearchRequest =
  | AddressRouteSearchRequest
  | CoordinateRouteSearchRequest;

export interface SearchHistoryEntry {
  key: string;
  request: RouteSearchRequest;
  originLabel: string;
  destinationLabel: string;
  createdAt: string;
}

const routeStaleTimeMs = 1000 * 60 * 60 * 24; // 24 hours
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

const resolveRouteOptimizationMethod = (
  routePlanningMode: RoutePlanningMode,
  routeOptimizationMethod: RouteOptimizationMethod,
): RouteOptimizationMethod => {
  if (routePlanningMode === "shortest") {
    return "shortest";
  }

  return routeOptimizationMethod === "shortest"
    ? "weighted"
    : routeOptimizationMethod;
};

const normalizeRouteSearchRequest = (
  routeSearchRequest: RouteSearchRequest,
): RouteSearchRequest => {
  const nextMethod = resolveRouteOptimizationMethod(
    routeSearchRequest.routePlanningMode,
    routeSearchRequest.routeOptimizationMethod,
  );

  const nextWeights =
    routeSearchRequest.routePlanningMode === "multi-objective"
      ? {
          scenicWeight: routeSearchRequest.scenicWeight,
          snowFreeWeight: routeSearchRequest.snowFreeWeight,
          flatWeight: routeSearchRequest.flatWeight,
        }
      : {
          scenicWeight: 0,
          snowFreeWeight: 0,
          flatWeight: 0,
        };

  if (routeSearchRequest.source === "address") {
    return {
      ...routeSearchRequest,
      origin: normalizeAddress(routeSearchRequest.origin),
      destination: normalizeAddress(routeSearchRequest.destination),
      routeOptimizationMethod: nextMethod,
      ...nextWeights,
    };
  }

  return {
    ...routeSearchRequest,
    origin: normalizePoint(routeSearchRequest.origin),
    destination: normalizePoint(routeSearchRequest.destination),
    routeOptimizationMethod: nextMethod,
    ...nextWeights,
  };
};

const buildRouteQueryKey = (routeSearchRequest: RouteSearchRequest) => {
  const normalizedRequest = normalizeRouteSearchRequest(routeSearchRequest);

  if (normalizedRequest.source === "address") {
    return computeRouteByAddressRoutesByAddressGetQueryKey({
      query: {
        travel_mode: normalizedRequest.travelMode,
        origin: normalizedRequest.origin,
        destination: normalizedRequest.destination,
        route_optimization_method: normalizedRequest.routeOptimizationMethod,
        scenic_weight: normalizedRequest.scenicWeight,
        snow_free_weight: normalizedRequest.snowFreeWeight,
        flat_weight: normalizedRequest.flatWeight,
        pareto_max_routes: 3,
      },
    });
  }

  return computeRouteByCoordinatesRoutesByCoordinatesGetQueryKey({
    query: {
      travel_mode: normalizedRequest.travelMode,
      origin_longitude: normalizedRequest.origin.coordinates[0],
      origin_latitude: normalizedRequest.origin.coordinates[1],
      destination_longitude: normalizedRequest.destination.coordinates[0],
      destination_latitude: normalizedRequest.destination.coordinates[1],
      route_optimization_method: normalizedRequest.routeOptimizationMethod,
      scenic_weight: normalizedRequest.scenicWeight,
      snow_free_weight: normalizedRequest.snowFreeWeight,
      flat_weight: normalizedRequest.flatWeight,
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

const isPointInsideBounds = (
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
  if (!isPointInsideBounds(point, boundaryFeatureCollection)) {
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

  const [activeRouteEndpoint, setActiveRouteEndpoint] =
    useState<ActiveRouteEndpoint>(null);
  const [originPosition, setOriginPosition] = useState<Point | null>(null);
  const [destinationPosition, setDestinationPosition] = useState<Point | null>(
    null,
  );

  const routePanelRef = useRef<RoutePanelHandle>(null);

  const [status, setStatus] = useState("Ready.");
  const [statusColor, setStatusColor] = useState("green");
  const statusTimeoutRef = useRef<number | null>(null);

  const [travelMode, setTravelMode] = useState<TravelMode>("walking");
  const [routePlanningMode, setRoutePlanningMode] =
    useState<RoutePlanningMode>("shortest");
  const [routeOptimizationMethod, setRouteOptimizationMethod] =
    useState<RouteOptimizationMethod>("shortest");
  const [scenicWeight, setScenicWeight] = useState(0);
  const [snowFreeWeight, setSnowFreeWeight] = useState(0);
  const [flatWeight, setFlatWeight] = useState(0);

  const [routeLoading, setRouteLoading] = useState(false);
  const [committedSearch, setCommittedSearch] =
    useState<RouteSearchRequest | null>(null);
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

  const getCurrentRouteSearchOptions = (
    overrides: Partial<RouteSearchOptions> = {},
  ): RouteSearchOptions => {
    const nextRoutePlanningMode =
      overrides.routePlanningMode ?? routePlanningMode;
    const requestedRouteOptimizationMethod =
      overrides.routeOptimizationMethod ?? routeOptimizationMethod;

    return {
      travelMode: overrides.travelMode ?? travelMode,
      routePlanningMode: nextRoutePlanningMode,
      routeOptimizationMethod: resolveRouteOptimizationMethod(
        nextRoutePlanningMode,
        requestedRouteOptimizationMethod,
      ),
      scenicWeight: overrides.scenicWeight ?? scenicWeight,
      snowFreeWeight: overrides.snowFreeWeight ?? snowFreeWeight,
      flatWeight: overrides.flatWeight ?? flatWeight,
    };
  };

  const createAddressRouteSearchRequest = (
    origin: string,
    destination: string,
    overrides: Partial<RouteSearchOptions> = {},
  ): AddressRouteSearchRequest =>
    normalizeRouteSearchRequest({
      source: "address",
      origin,
      destination,
      ...getCurrentRouteSearchOptions(overrides),
    }) as AddressRouteSearchRequest;

  const createCoordinateRouteSearchRequest = (
    origin: Point,
    destination: Point,
    overrides: Partial<RouteSearchOptions> = {},
  ): CoordinateRouteSearchRequest =>
    normalizeRouteSearchRequest({
      source: "coordinates",
      origin,
      destination,
      ...getCurrentRouteSearchOptions(overrides),
    }) as CoordinateRouteSearchRequest;

  const rebuildRouteSearchRequest = (
    baseRequest: RouteSearchRequest,
    overrides: Partial<RouteSearchOptions> = {},
  ): RouteSearchRequest => {
    if (baseRequest.source === "address") {
      return createAddressRouteSearchRequest(
        baseRequest.origin,
        baseRequest.destination,
        overrides,
      );
    }

    return createCoordinateRouteSearchRequest(
      baseRequest.origin,
      baseRequest.destination,
      overrides,
    );
  };

  const getAddressRouteQueryOptions = (
    addressRouteSearchRequest: AddressRouteSearchRequest,
  ) =>
    computeRouteByAddressRoutesByAddressGetOptions({
      query: {
        travel_mode: addressRouteSearchRequest.travelMode,
        origin: addressRouteSearchRequest.origin,
        destination: addressRouteSearchRequest.destination,
        route_optimization_method:
          addressRouteSearchRequest.routeOptimizationMethod,
        scenic_weight: addressRouteSearchRequest.scenicWeight,
        snow_free_weight: addressRouteSearchRequest.snowFreeWeight,
        flat_weight: addressRouteSearchRequest.flatWeight,
        pareto_max_routes: 3,
      },
    });

  const getCoordinateRouteQueryOptions = (
    coordinateRouteSearchRequest: CoordinateRouteSearchRequest,
  ) =>
    computeRouteByCoordinatesRoutesByCoordinatesGetOptions({
      query: {
        travel_mode: coordinateRouteSearchRequest.travelMode,
        origin_longitude: coordinateRouteSearchRequest.origin.coordinates[0],
        origin_latitude: coordinateRouteSearchRequest.origin.coordinates[1],
        destination_longitude:
          coordinateRouteSearchRequest.destination.coordinates[0],
        destination_latitude:
          coordinateRouteSearchRequest.destination.coordinates[1],
        route_optimization_method:
          coordinateRouteSearchRequest.routeOptimizationMethod,
        scenic_weight: coordinateRouteSearchRequest.scenicWeight,
        snow_free_weight: coordinateRouteSearchRequest.snowFreeWeight,
        flat_weight: coordinateRouteSearchRequest.flatWeight,
        pareto_max_routes: 3,
      },
    });

  const fetchRoute = async (routeSearchRequest: RouteSearchRequest) => {
    if (routeSearchRequest.source === "address") {
      const options = getAddressRouteQueryOptions(routeSearchRequest);

      return queryClient.fetchQuery({
        ...options,
        staleTime: routeStaleTimeMs,
      });
    }

    const options = getCoordinateRouteQueryOptions(routeSearchRequest);

    return queryClient.fetchQuery({
      ...options,
      staleTime: routeStaleTimeMs,
    });
  };

  const applyRouteSearchResult = (routes: RouteFeatureCollection) => {
    setRoutes(routes);
    setSelectedRouteIndex(null);
    setSelectedStepIndex(null);
    setOriginPosition(routes.meta.origin);
    setDestinationPosition(routes.meta.destination);
    setStatusWithTtl("Ready.", "green", 500);
  };

  const pushSearchHistory = (routeSearchRequest: RouteSearchRequest) => {
    const originLabel =
      routeSearchRequest.source === "address"
        ? routeSearchRequest.origin
        : formatPointLabel(routeSearchRequest.origin);

    const destinationLabel =
      routeSearchRequest.source === "address"
        ? routeSearchRequest.destination
        : formatPointLabel(routeSearchRequest.destination);

    const entry: SearchHistoryEntry = {
      key: JSON.stringify(buildRouteQueryKey(routeSearchRequest)),
      request: routeSearchRequest,
      originLabel,
      destinationLabel,
      createdAt: new Date().toISOString(),
    };

    setSearchHistory((currentEntries) =>
      upsertHistoryEntry(currentEntries, entry),
    );
  };

  const hasFreshCachedRoute = (routeSearchRequest: RouteSearchRequest) => {
    const queryState = queryClient.getQueryState<RouteFeatureCollection>(
      buildRouteQueryKey(routeSearchRequest),
    );

    if (!queryState?.dataUpdatedAt) {
      return false;
    }

    if (routeStaleTimeMs === Infinity) {
      return true;
    }

    return Date.now() - queryState.dataUpdatedAt < routeStaleTimeMs;
  };

  const executeSearch = async (routeSearchRequest: RouteSearchRequest) => {
    const normalizedRequest = normalizeRouteSearchRequest(routeSearchRequest);
    const searchId = ++latestSearchIdRef.current;
    const cached = hasFreshCachedRoute(normalizedRequest);

    if (!cached) {
      setRouteLoading(true);
      setStatusWithTtl("Calculating route...", "blue");
    }

    try {
      const data = await fetchRoute(normalizedRequest);

      if (searchId !== latestSearchIdRef.current) {
        return true;
      }

      applyRouteSearchResult(data);
      setCommittedSearch(normalizedRequest);
      pushSearchHistory(normalizedRequest);

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

  const runAddressRouteSearch = async (origin: string, destination: string) =>
    executeSearch(createAddressRouteSearchRequest(origin, destination));

  const runCoordinateRouteSearch = async (origin: Point, destination: Point) =>
    executeSearch(createCoordinateRouteSearchRequest(origin, destination));

  const scheduleCommittedSearchRefresh = (
    overrides: Partial<RouteSearchOptions> = {},
  ) => {
    clearScheduledSliderSearch();

    if (!committedSearch) {
      return;
    }

    sliderSearchTimeoutRef.current = setTimeout(() => {
      sliderSearchTimeoutRef.current = null;
      void executeSearch(rebuildRouteSearchRequest(committedSearch, overrides));
    }, sliderSearchDelayMs);
  };

  const handleTravelModeChange = (nextTravelMode: TravelMode) => {
    clearScheduledSliderSearch();
    setTravelMode(nextTravelMode);

    if (!committedSearch) {
      return;
    }

    void executeSearch(
      rebuildRouteSearchRequest(committedSearch, {
        travelMode: nextTravelMode,
      }),
    );
  };

  const handleRoutePlanningModeChange = (
    nextRoutePlanningMode: RoutePlanningMode,
  ) => {
    clearScheduledSliderSearch();

    const nextRouteOptimizationMethod = resolveRouteOptimizationMethod(
      nextRoutePlanningMode,
      nextRoutePlanningMode === "multi-objective" &&
        routeOptimizationMethod === "shortest"
        ? "weighted"
        : routeOptimizationMethod,
    );

    setRoutePlanningMode(nextRoutePlanningMode);
    setRouteOptimizationMethod(nextRouteOptimizationMethod);

    if (!committedSearch) {
      return;
    }

    void executeSearch(
      rebuildRouteSearchRequest(committedSearch, {
        routePlanningMode: nextRoutePlanningMode,
        routeOptimizationMethod: nextRouteOptimizationMethod,
      }),
    );
  };

  const handleRouteOptimizationMethodChange = (
    nextRouteOptimizationMethod: RouteOptimizationMethod,
  ) => {
    clearScheduledSliderSearch();
    setRouteOptimizationMethod(nextRouteOptimizationMethod);

    if (!committedSearch) {
      return;
    }

    void executeSearch(
      rebuildRouteSearchRequest(committedSearch, {
        routeOptimizationMethod: nextRouteOptimizationMethod,
      }),
    );
  };

  const handleScenicWeightChangeEnd = (nextScenicWeight: number) => {
    setScenicWeight(nextScenicWeight);
    scheduleCommittedSearchRefresh({ scenicWeight: nextScenicWeight });
  };

  const handleSnowFreeWeightChangeEnd = (nextSnowFreeWeight: number) => {
    setSnowFreeWeight(nextSnowFreeWeight);
    scheduleCommittedSearchRefresh({ snowFreeWeight: nextSnowFreeWeight });
  };

  const handleFlatWeightChangeEnd = (nextFlatWeight: number) => {
    setFlatWeight(nextFlatWeight);
    scheduleCommittedSearchRefresh({ flatWeight: nextFlatWeight });
  };

  const handleSelectHistoryEntry = async (
    searchHistoryEntry: SearchHistoryEntry,
  ) => {
    clearScheduledSliderSearch();

    setTravelMode(searchHistoryEntry.request.travelMode);
    setRoutePlanningMode(searchHistoryEntry.request.routePlanningMode);
    setRouteOptimizationMethod(
      searchHistoryEntry.request.routeOptimizationMethod,
    );
    setScenicWeight(searchHistoryEntry.request.scenicWeight);
    setSnowFreeWeight(searchHistoryEntry.request.snowFreeWeight);
    setFlatWeight(searchHistoryEntry.request.flatWeight);

    if (searchHistoryEntry.request.source === "address") {
      routePanelRef.current?.setOrigin(searchHistoryEntry.request.origin);
      routePanelRef.current?.setDestination(
        searchHistoryEntry.request.destination,
      );
    } else {
      setOriginPosition(searchHistoryEntry.request.origin);
      setDestinationPosition(searchHistoryEntry.request.destination);
      routePanelRef.current?.setOrigin(searchHistoryEntry.originLabel);
      routePanelRef.current?.setDestination(
        searchHistoryEntry.destinationLabel,
      );
    }

    await executeSearch(searchHistoryEntry.request);
  };

  const reverseGeocode = async (routeEndpoint: RouteEndpoint, point: Point) => {
    const [lon, lat] = point.coordinates;

    try {
      const options = reverseGeocodeGeocodingReverseGetOptions({
        query: { longitude: lon, latitude: lat },
      });

      const data = await queryClient.fetchQuery(options);

      if (!data.address) {
        return;
      }

      if (routeEndpoint === "origin") {
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
      }, ttlMs);
    }
  };

  const getMarkerPosition = (routeEndpoint: RouteEndpoint) =>
    routeEndpoint === "origin" ? originPosition : destinationPosition;

  const setMarkerPosition = (
    routeEndpoint: RouteEndpoint,
    point: Point | null,
  ) => {
    if (routeEndpoint === "origin") {
      setOriginPosition(point);

      return;
    }

    setDestinationPosition(point);
  };

  const getOtherMarkerPosition = (routeEndpoint: RouteEndpoint) =>
    routeEndpoint === "origin" ? destinationPosition : originPosition;

  const applyMarkerUpdate = async (
    routeEndpoint: RouteEndpoint,
    position: Point,
    source: MarkerSource,
  ) => {
    const markerName = routeEndpoint === "origin" ? "Origin" : "Destination";

    if (!boundary || !isInsideBoundary(position, boundary)) {
      setStatusWithTtl(
        `${markerName} marker must be inside Copenhagen Municipality.`,
        "red",
        2000,
      );

      return false;
    }

    const previousPosition = getMarkerPosition(routeEndpoint);
    const otherMarkerPosition = getOtherMarkerPosition(routeEndpoint);

    if (source === "pick") {
      setActiveRouteEndpoint(null);
    }

    setMarkerPosition(routeEndpoint, position);
    await reverseGeocode(routeEndpoint, position);

    if (!otherMarkerPosition) {
      return true;
    }

    const origin = routeEndpoint === "origin" ? position : otherMarkerPosition;
    const destination =
      routeEndpoint === "destination" ? position : otherMarkerPosition;

    const ok = await runCoordinateRouteSearch(origin, destination);

    if (ok) {
      return true;
    }

    setStatusWithTtl(`${markerName} marker could not be set.`, "red", 2000);

    setMarkerPosition(routeEndpoint, previousPosition ?? null);

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
    setActiveRouteEndpoint((activeRouteEndpoint) =>
      activeRouteEndpoint === "origin" ? null : "origin",
    );
  };

  const onTogglePickDestination = () => {
    setActiveRouteEndpoint((activeRouteEndpoint) =>
      activeRouteEndpoint === "destination" ? null : "destination",
    );
  };

  const handleClearAll = () => {
    clearScheduledSliderSearch();

    setActiveRouteEndpoint(null);
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
    if (activeRouteEndpoint === "origin") {
      setStatusWithTtl("Click on the map to place the origin marker.", "grape");
    }

    if (activeRouteEndpoint === "destination") {
      setStatusWithTtl(
        "Click on the map to place the destination marker.",
        "grape",
      );
    }

    if (!activeRouteEndpoint) {
      // setStatusWithTtl("Ready.", "green");
    }
  }, [destinationPosition, activeRouteEndpoint, originPosition]);

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
        activeRouteEndpoint={activeRouteEndpoint}
        onPickOrigin={onPickOrigin}
        onPickDestination={onPickDestination}
        travelMode={travelMode}
      />
      <RoutePanel
        ref={routePanelRef}
        searchByAddress={runAddressRouteSearch}
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
        activeRouteEndpoint={activeRouteEndpoint}
        hasOriginMarker={originPosition !== null}
        hasDestinationMarker={destinationPosition !== null}
        onClearAll={handleClearAll}
        travelMode={travelMode}
        onTravelModeChange={handleTravelModeChange}
        routePlanningMode={routePlanningMode}
        onRoutePlanningModeChange={handleRoutePlanningModeChange}
        routeOptimizationMethod={routeOptimizationMethod}
        onRouteOptimizationMethodChange={handleRouteOptimizationMethodChange}
        scenicWeight={scenicWeight}
        onScenicWeightChange={setScenicWeight}
        onScenicWeightChangeEnd={handleScenicWeightChangeEnd}
        snowFreeWeight={snowFreeWeight}
        onSnowFreeWeightChange={setSnowFreeWeight}
        onSnowFreeWeightChangeEnd={handleSnowFreeWeightChangeEnd}
        flatWeight={flatWeight}
        onFlatWeightChange={setFlatWeight}
        onFlatWeightChangeEnd={handleFlatWeightChangeEnd}
        searchHistory={searchHistory}
        onSelectHistoryEntry={handleSelectHistoryEntry}
        onClearHistory={removeSearchHistory}
      />
      <StatusNotice message={status} color={statusColor} />
    </Box>
  );
};

export default App;
