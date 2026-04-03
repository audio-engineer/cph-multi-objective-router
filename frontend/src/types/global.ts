export type TravelMode = "cycling" | "walking";

export type RouteEndpoint = "origin" | "destination";
export type ActiveRouteEndpoint = RouteEndpoint | null;

export type MapOverlayKey = "snow" | "scenic" | "hills";
export type GraphLayerKey =
  | "cycling_nodes"
  | "cycling_edges"
  | "walking_nodes"
  | "walking_edges";
