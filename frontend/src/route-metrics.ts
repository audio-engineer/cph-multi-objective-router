import type {
  RouteFeature,
  RouteObjectiveCostBreakdown,
  RouteStepResponse,
} from "@/client";
import type { TransportMode } from "@/types/global.ts";

export interface RouteComfortScores {
  snowlessComfort: number;
  uphillComfort: number;
  scenicComfort: number;
}

export interface RouteProgressionDatum extends RouteComfortScores {
  stepLabel: string;
}

export const objectiveScoreLabels = {
  snowlessComfort: "Snowless",
  uphillComfort: "Flat",
  scenicComfort: "Scenic",
} as const satisfies Record<keyof RouteComfortScores, string>;

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

const getFallbackObjectiveCosts = (
  distance: number,
): RouteObjectiveCostBreakdown => ({
  distance,
  snow_penalty: distance,
  uphill_penalty: distance,
  scenic_penalty: distance,
});

export const toComfortPercent = (penalty: number, distance: number) => {
  if (distance <= 0) {
    return 0;
  }

  return clamp((1 - penalty / distance) * 100, 0, 100);
};

export const getComfortScores = (
  objectiveCosts: RouteObjectiveCostBreakdown,
): RouteComfortScores => ({
  snowlessComfort: toComfortPercent(
    objectiveCosts.snow_penalty,
    objectiveCosts.distance,
  ),
  uphillComfort: toComfortPercent(
    objectiveCosts.uphill_penalty,
    objectiveCosts.distance,
  ),
  scenicComfort: toComfortPercent(
    objectiveCosts.scenic_penalty,
    objectiveCosts.distance,
  ),
});

export const getRouteComfortScores = (
  route: RouteFeature,
): RouteComfortScores =>
  getComfortScores(
    route.properties.objective_costs ??
      getFallbackObjectiveCosts(route.properties.distance),
  );

export const getRouteSpeedKmPerHour = (
  transportMode: TransportMode,
  walkingSpeed: number,
  bikingSpeed: number,
) => (transportMode === "walk" ? walkingSpeed : bikingSpeed);

export const estimateRouteDurationMinutes = (
  distanceMeters: number,
  speedKmPerHour: number,
) => {
  if (distanceMeters <= 0 || speedKmPerHour <= 0) {
    return 0;
  }

  return (distanceMeters / 1000 / speedKmPerHour) * 60;
};

export const formatDuration = (durationMinutes: number) => {
  const roundedMinutes = Math.max(0, Math.round(durationMinutes));

  if (roundedMinutes < 60) {
    return `${String(roundedMinutes)} min`;
  }

  const hours = Math.floor(roundedMinutes / 60);
  const minutes = roundedMinutes % 60;

  if (minutes === 0) {
    return `${String(hours)} h`;
  }

  return `${String(hours)} h ${String(minutes).padStart(2, "0")} min`;
};

const buildBucketLabel = (startIndex: number, endIndex: number) => {
  const start = startIndex + 1;
  const end = endIndex + 1;

  if (start === end) {
    return String(start);
  }

  return `${String(start)}-${String(end)}`;
};

export const buildRouteProgressionData = (
  steps: RouteStepResponse[],
  maxPoints = 10,
): RouteProgressionDatum[] => {
  if (steps.length === 0) {
    return [];
  }

  const bucketSize =
    steps.length <= maxPoints ? 1 : Math.ceil(steps.length / maxPoints);

  const progressionData: RouteProgressionDatum[] = [];

  for (
    let bucketStart = 0;
    bucketStart < steps.length;
    bucketStart += bucketSize
  ) {
    const bucketSteps = steps.slice(bucketStart, bucketStart + bucketSize);
    const bucketObjectiveCosts = bucketSteps.reduce(
      (totals, step) => {
        const objectiveCosts = step.objective_costs;

        return {
          distance: totals.distance + objectiveCosts.distance,
          snow_penalty: totals.snow_penalty + objectiveCosts.snow_penalty,
          uphill_penalty: totals.uphill_penalty + objectiveCosts.uphill_penalty,
          scenic_penalty: totals.scenic_penalty + objectiveCosts.scenic_penalty,
        };
      },
      {
        distance: 0,
        snow_penalty: 0,
        uphill_penalty: 0,
        scenic_penalty: 0,
      } satisfies RouteObjectiveCostBreakdown,
    );

    progressionData.push({
      stepLabel: buildBucketLabel(
        bucketStart,
        Math.min(bucketStart + bucketSize - 1, steps.length - 1),
      ),
      ...getComfortScores(bucketObjectiveCosts),
    });
  }

  return progressionData;
};
