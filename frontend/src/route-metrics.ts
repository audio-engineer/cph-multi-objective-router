import type {
  RouteFeature,
  RoutePenaltyBreakdown,
  RouteStepSummary,
} from "@/client";
import type { TravelMode } from "@/types/global.ts";

export interface RouteScores {
  snowFreeScore: number;
  flatScore: number;
  scenicScore: number;
}

export interface RouteScoreProfileDatum extends RouteScores {
  stepLabel: string;
}

export const routeScoreLabels = {
  snowFreeScore: "Snow-free",
  flatScore: "Flat",
  scenicScore: "Scenic",
} as const satisfies Record<keyof RouteScores, string>;

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

const getFallbackObjectiveCosts = (
  distance: number,
): RoutePenaltyBreakdown => ({
  distance,
  snow_penalty: distance,
  uphill_penalty: distance,
  scenic_penalty: distance,
});

export const toPercentScore = (score: number, distance: number) => {
  if (distance <= 0) {
    return 0;
  }

  return clamp((1 - score / distance) * 100, 0, 100);
};

export const getScoreObject = (
  objectiveCosts: RoutePenaltyBreakdown,
): RouteScores => ({
  snowFreeScore: toPercentScore(
    objectiveCosts.snow_penalty,
    objectiveCosts.distance,
  ),
  flatScore: toPercentScore(
    objectiveCosts.uphill_penalty,
    objectiveCosts.distance,
  ),
  scenicScore: toPercentScore(
    objectiveCosts.scenic_penalty,
    objectiveCosts.distance,
  ),
});

export const getRouteScores = (route: RouteFeature): RouteScores =>
  getScoreObject(
    route.properties.penalty_breakdown ??
      getFallbackObjectiveCosts(route.properties.distance),
  );

export const getTravelSpeedKmh = (
  travelMode: TravelMode,
  walkingSpeed: number,
  cyclingSpeed: number,
) => (travelMode === "walking" ? walkingSpeed : cyclingSpeed);

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

const buildStepRangeLabel = (startIndex: number, endIndex: number) => {
  const start = startIndex + 1;
  const end = endIndex + 1;

  if (start === end) {
    return String(start);
  }

  return `${String(start)}-${String(end)}`;
};

export const buildRouteScoreProfile = (
  steps: RouteStepSummary[],
  maxPoints = 10,
): RouteScoreProfileDatum[] => {
  if (steps.length === 0) {
    return [];
  }

  const bucketSize =
    steps.length <= maxPoints ? 1 : Math.ceil(steps.length / maxPoints);

  const routeScoreProfile: RouteScoreProfileDatum[] = [];

  for (
    let bucketStart = 0;
    bucketStart < steps.length;
    bucketStart += bucketSize
  ) {
    const bucketSteps = steps.slice(bucketStart, bucketStart + bucketSize);
    const bucketObjectiveCosts = bucketSteps.reduce(
      (totals, step) => {
        const objectiveCosts = step.penalty_breakdown;

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
      } satisfies RoutePenaltyBreakdown,
    );

    routeScoreProfile.push({
      stepLabel: buildStepRangeLabel(
        bucketStart,
        Math.min(bucketStart + bucketSize - 1, steps.length - 1),
      ),
      ...getScoreObject(bucketObjectiveCosts),
    });
  }

  return routeScoreProfile;
};
