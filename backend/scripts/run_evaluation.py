"""Run routing evaluation experiments and export CSV data.

Place this file in backend/scripts/run_evaluation.py and run it from the backend
folder, for example:

    uv run python scripts/run_evaluation.py --pairs 20 --seed 7 --travel-mode cycling \
        --min-distance 2000 --max-distance 8000 --pair-filter active

The script loads the same graph state as the FastAPI app, samples
origin-destination pairs from graph nodes, runs shortest, weighted, and Pareto
routing, and writes CSV files to evaluation-output/.

The script intentionally calls the route-planning layer directly instead of the
HTTP endpoint. This measures server-side routing and serialization without
browser caching, geocoding, or front-end rendering noise.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import statistics
import sys
import time
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import networkx as nx

# Make `app` importable when the script is placed in backend/scripts.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import route_planner as route_planner_module  # noqa: E402
from app.costs import (  # noqa: E402
    build_weighted_edge_cost_function,
    compute_edge_cost_components,
    normalize_route_preference_weights,
)
from app.graph_state import (  # noqa: E402
    GRAPH_STATE,
    get_graph_for_travel_mode,
    load_graph_state,
)
from app.main import OVERLAY_DIRECTORY, PLACE_NAME  # noqa: E402
from app.models import (  # noqa: E402
    RouteCoordinates,
    RoutePlanningOptions,
    RoutePreferenceWeights,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True, slots=True)
class Pair:
    pair_id: int
    origin_node: int
    destination_node: int
    origin_longitude: float
    origin_latitude: float
    destination_longitude: float
    destination_latitude: float
    shortest_distance_m: float
    shortest_snow_penalty: float
    shortest_uphill_penalty: float
    shortest_scenic_penalty: float
    shortest_snow_free_score: float
    shortest_flat_score: float
    shortest_scenic_score: float


@dataclass(frozen=True, slots=True)
class WeightProfile:
    name: str
    scenic_weight: int
    snow_free_weight: int
    flat_weight: int


WEIGHT_PROFILES: tuple[WeightProfile, ...] = (
    WeightProfile("neutral", scenic_weight=0, snow_free_weight=0, flat_weight=0),
    WeightProfile("scenic", scenic_weight=100, snow_free_weight=0, flat_weight=0),
    WeightProfile("snow_free", scenic_weight=0, snow_free_weight=100, flat_weight=0),
    WeightProfile("flat", scenic_weight=0, snow_free_weight=0, flat_weight=100),
    WeightProfile("balanced", scenic_weight=50, snow_free_weight=50, flat_weight=50),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--pairs", type=int, default=20)
    _ = parser.add_argument("--seed", type=int, default=7)
    _ = parser.add_argument(
        "--travel-mode", choices=["walking", "cycling"], default="cycling"
    )
    _ = parser.add_argument("--min-distance", type=float, default=1_000.0)
    _ = parser.add_argument("--max-distance", type=float, default=5_000.0)
    _ = parser.add_argument("--max-sampling-attempts", type=int, default=20_000)
    _ = parser.add_argument(
        "--pair-filter",
        choices=["random", "active", "changed"],
        default="random",
        help=(
            "random accepts any pair within the distance interval; active requires "
            "the shortest path to cross at least one non-default overlay; changed is "
            "a diagnostic filter requiring at least one weighted profile to change "
            "the scalar shortest path. Use active for the thesis benchmark."
        ),
    )
    _ = parser.add_argument("--active-epsilon", type=float, default=1e-6)
    _ = parser.add_argument("--pareto-max-routes", type=int, default=3)
    _ = parser.add_argument("--pareto-max-labels-per-node", type=int, default=40)
    _ = parser.add_argument("--pareto-max-total-labels", type=int, default=50_000)
    _ = parser.add_argument("--out", type=Path, default=Path("evaluation-output"))
    _ = parser.add_argument(
        "--profiles",
        default=",".join(profile.name for profile in WEIGHT_PROFILES),
        help="Comma-separated subset of: neutral,scenic,snow_free,flat,balanced",
    )

    return parser.parse_args()


def load_profiles(profile_arg: str) -> list[WeightProfile]:
    names = {name.strip() for name in profile_arg.split(",") if name.strip()}
    profiles = [profile for profile in WEIGHT_PROFILES if profile.name in names]

    if not profiles:
        raise SystemExit("No valid weight profiles selected.")

    return profiles


def node_coordinates(graph: nx.MultiDiGraph, node_id: int) -> tuple[float, float]:
    node = graph.nodes[node_id]

    return float(node["x"]), float(node["y"])


def percent_score(penalty: float, distance: float) -> float:
    if distance <= 0:
        return 0.0
    return max(0.0, min(100.0, (1.0 - penalty / distance) * 100.0))


def _select_shortest_edge_attributes(
    graph: nx.MultiDiGraph, u: int, v: int
) -> dict[str, Any]:
    payload = graph.get_edge_data(u, v)
    if not isinstance(payload, dict) or not payload:
        raise nx.NetworkXNoPath
    return min(payload.values(), key=lambda attrs: float(attrs.get("length", 0.0)))


def path_cost_vector(
    graph: nx.MultiDiGraph, node_path: list[int]
) -> tuple[float, float, float, float]:
    distance = snow = hills = scenic = 0.0

    for u, v in pairwise(node_path):
        edge_attrs = _select_shortest_edge_attributes(graph, u, v)
        d, s, h, c = compute_edge_cost_components(edge_attrs)
        distance += d
        snow += s
        hills += h
        scenic += c

    return distance, snow, hills, scenic


def path_has_active_objective(
    cost_vector: tuple[float, float, float, float], *, epsilon: float
) -> bool:
    distance, snow_penalty, uphill_penalty, scenic_penalty = cost_vector
    return (
        snow_penalty > epsilon
        or uphill_penalty > epsilon
        or scenic_penalty < distance - epsilon
    )


def weighted_path_signature(
    graph: nx.MultiDiGraph, source: int, target: int, profile: WeightProfile
) -> tuple[int, ...]:
    weights = RoutePreferenceWeights(
        scenic_weight=profile.scenic_weight,
        snow_free_weight=profile.snow_free_weight,
        flat_weight=profile.flat_weight,
    )
    return tuple(
        nx.shortest_path(
            graph,
            source=source,
            target=target,
            weight=build_weighted_edge_cost_function(
                normalize_route_preference_weights(weights)
            ),
        )
    )


def weighted_path_changes(
    graph: nx.MultiDiGraph, source: int, target: int, profiles: list[WeightProfile]
) -> bool:
    neutral = weighted_path_signature(graph, source, target, WEIGHT_PROFILES[0])
    return any(
        weighted_path_signature(graph, source, target, profile) != neutral
        for profile in profiles
        if profile.name != "neutral"
    )


def sample_pairs(
    graph: nx.MultiDiGraph,
    *,
    count: int,
    seed: int,
    min_distance: float,
    max_distance: float,
    max_attempts: int,
    pair_filter: str,
    active_epsilon: float,
    profiles: list[WeightProfile],
) -> list[Pair]:
    rng = random.Random(seed)
    nodes = list(graph.nodes)
    pairs: list[Pair] = []
    seen: set[tuple[int, int]] = set()

    for _attempt in range(max_attempts):
        if len(pairs) >= count:
            break

        origin_node, destination_node = rng.sample(nodes, 2)
        if (origin_node, destination_node) in seen:
            continue
        seen.add((origin_node, destination_node))

        try:
            shortest_path = nx.shortest_path(
                graph,
                source=origin_node,
                target=destination_node,
                weight="length",
            )
            cost_vector = path_cost_vector(graph, shortest_path)
        except nx.NetworkXNoPath, nx.NodeNotFound:
            continue

        distance, snow_penalty, uphill_penalty, scenic_penalty = cost_vector
        if not (min_distance <= distance <= max_distance):
            continue

        if pair_filter in {"active", "changed"} and not path_has_active_objective(
            cost_vector,
            epsilon=active_epsilon,
        ):
            continue

        if pair_filter == "changed" and not weighted_path_changes(
            graph,
            origin_node,
            destination_node,
            profiles,
        ):
            continue

        origin_lon, origin_lat = node_coordinates(graph, origin_node)
        destination_lon, destination_lat = node_coordinates(graph, destination_node)
        pairs.append(
            Pair(
                pair_id=len(pairs),
                origin_node=origin_node,
                destination_node=destination_node,
                origin_longitude=origin_lon,
                origin_latitude=origin_lat,
                destination_longitude=destination_lon,
                destination_latitude=destination_lat,
                shortest_distance_m=distance,
                shortest_snow_penalty=snow_penalty,
                shortest_uphill_penalty=uphill_penalty,
                shortest_scenic_penalty=scenic_penalty,
                shortest_snow_free_score=percent_score(snow_penalty, distance),
                shortest_flat_score=percent_score(uphill_penalty, distance),
                shortest_scenic_score=percent_score(scenic_penalty, distance),
            )
        )

    if len(pairs) < count:
        raise SystemExit(
            f"Only sampled {len(pairs)} valid pairs after {max_attempts} attempts. "
            "Try widening --min-distance/--max-distance, increasing "
            "--max-sampling-attempts, lowering --pairs, or using --pair-filter random."
        )

    return pairs


def route_signature(coordinates: Iterable[Any]) -> str:
    rounded = []
    for coordinate in coordinates:
        lon = float(coordinate[0])
        lat = float(coordinate[1])
        rounded.append((round(lon, 6), round(lat, 6)))
    payload = json.dumps(rounded, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def route_options(
    *,
    method: str,
    profile: WeightProfile,
    pareto_max_routes: int,
    pareto_max_labels_per_node: int,
    pareto_max_total_labels: int,
) -> RoutePlanningOptions:
    return RoutePlanningOptions(
        route_optimization_method=method,  # type: ignore[arg-type]
        preference_weights=RoutePreferenceWeights(
            scenic_weight=profile.scenic_weight,
            snow_free_weight=profile.snow_free_weight,
            flat_weight=profile.flat_weight,
        ),
        pareto_max_routes=pareto_max_routes,
        pareto_max_labels_per_node=pareto_max_labels_per_node,
        pareto_max_total_labels=pareto_max_total_labels,
    )


def run_one_request(
    *,
    pair: Pair,
    travel_mode: str,
    method: str,
    profile: WeightProfile,
    pareto_max_routes: int,
    pareto_max_labels_per_node: int,
    pareto_max_total_labels: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    coordinates = RouteCoordinates(
        origin_longitude=pair.origin_longitude,
        origin_latitude=pair.origin_latitude,
        destination_longitude=pair.destination_longitude,
        destination_latitude=pair.destination_latitude,
    )
    options = route_options(
        method=method,
        profile=profile,
        pareto_max_routes=pareto_max_routes,
        pareto_max_labels_per_node=pareto_max_labels_per_node,
        pareto_max_total_labels=pareto_max_total_labels,
    )

    pareto_stats: dict[str, Any] = {
        "total_labels": "",
        "destination_labels": "",
        "hit_total_label_cap": "",
    }

    original_pareto_search = route_planner_module.run_pareto_label_search

    def instrumented_pareto_search(*args: Any, **kwargs: Any):
        labels, destination_label_ids = original_pareto_search(*args, **kwargs)
        pareto_stats["total_labels"] = len(labels)
        pareto_stats["destination_labels"] = len(destination_label_ids)
        pareto_stats["hit_total_label_cap"] = len(labels) >= pareto_max_total_labels
        return labels, destination_label_ids

    start = time.perf_counter()
    try:
        if method == "pareto":
            with patch(
                "app.route_planner.run_pareto_label_search",
                side_effect=instrumented_pareto_search,
            ):
                response = route_planner_module.build_route_feature_collection(
                    graph_state=GRAPH_STATE,
                    route_coordinates=coordinates,
                    travel_mode=travel_mode,  # type: ignore[arg-type]
                    route_options=options,
                )
        else:
            response = route_planner_module.build_route_feature_collection(
                graph_state=GRAPH_STATE,
                route_coordinates=coordinates,
                travel_mode=travel_mode,  # type: ignore[arg-type]
                route_options=options,
            )
        success = True
        error = ""
    except Exception as exception:  # noqa: BLE001 - evaluation should log failures.
        response = None
        success = False
        error = repr(exception)

    runtime_ms = (time.perf_counter() - start) * 1000.0

    run_row = {
        "pair_id": pair.pair_id,
        "travel_mode": travel_mode,
        "method": method,
        "profile": profile.name,
        "scenic_weight": profile.scenic_weight,
        "snow_free_weight": profile.snow_free_weight,
        "flat_weight": profile.flat_weight,
        "runtime_ms": runtime_ms,
        "success": success,
        "error": error,
        "route_count": len(response.features) if response is not None else 0,
        "origin_node": pair.origin_node,
        "destination_node": pair.destination_node,
        "reference_shortest_distance_m": pair.shortest_distance_m,
        **pareto_stats,
    }

    route_rows: list[dict[str, Any]] = []
    if response is not None:
        for feature in response.features:
            breakdown = feature.properties.penalty_breakdown
            if breakdown is None:
                continue
            distance = float(breakdown.distance)
            snow_penalty = float(breakdown.snow_penalty)
            uphill_penalty = float(breakdown.uphill_penalty)
            scenic_penalty = float(breakdown.scenic_penalty)
            route_rows.append(
                {
                    "pair_id": pair.pair_id,
                    "travel_mode": travel_mode,
                    "method": method,
                    "profile": profile.name,
                    "route_index": feature.properties.route_index,
                    "route_count": response.meta.route_count,
                    "pareto_rank": feature.properties.pareto_rank or "",
                    "selection_score": feature.properties.selection_score or "",
                    "distance_m": distance,
                    "snow_penalty": snow_penalty,
                    "uphill_penalty": uphill_penalty,
                    "scenic_penalty": scenic_penalty,
                    "snow_free_score": percent_score(snow_penalty, distance),
                    "flat_score": percent_score(uphill_penalty, distance),
                    "scenic_score": percent_score(scenic_penalty, distance),
                    "signature": route_signature(feature.geometry.coordinates),
                }
            )

    return run_row, route_rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise SystemExit(f"No rows to write for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def pair_rows(
    pairs: list[Pair], *, pair_filter: str, min_distance: float, max_distance: float
) -> list[dict[str, Any]]:
    return [
        {
            "pair_id": pair.pair_id,
            "pair_filter": pair_filter,
            "min_distance_m": min_distance,
            "max_distance_m": max_distance,
            "origin_node": pair.origin_node,
            "destination_node": pair.destination_node,
            "origin_longitude": pair.origin_longitude,
            "origin_latitude": pair.origin_latitude,
            "destination_longitude": pair.destination_longitude,
            "destination_latitude": pair.destination_latitude,
            "shortest_distance_m": pair.shortest_distance_m,
            "shortest_snow_penalty": pair.shortest_snow_penalty,
            "shortest_uphill_penalty": pair.shortest_uphill_penalty,
            "shortest_scenic_penalty": pair.shortest_scenic_penalty,
            "shortest_snow_free_score": pair.shortest_snow_free_score,
            "shortest_flat_score": pair.shortest_flat_score,
            "shortest_scenic_score": pair.shortest_scenic_score,
        }
        for pair in pairs
    ]


def main() -> None:
    args = parse_args()
    profiles = load_profiles(args.profiles)

    print("Loading graphs and overlays ...", flush=True)
    load_graph_state(
        place_name=PLACE_NAME,
        overlay_directory=OVERLAY_DIRECTORY,
        graph_state=GRAPH_STATE,
    )
    graph = get_graph_for_travel_mode(GRAPH_STATE, args.travel_mode)

    print("Sampling origin-destination pairs ...", flush=True)
    pairs = sample_pairs(
        graph,
        count=args.pairs,
        seed=args.seed,
        min_distance=args.min_distance,
        max_distance=args.max_distance,
        max_attempts=args.max_sampling_attempts,
        pair_filter=args.pair_filter,
        active_epsilon=args.active_epsilon,
        profiles=profiles,
    )
    print(
        f"Sampled {len(pairs)} pairs; shortest-distance median "
        f"{statistics.median(pair.shortest_distance_m for pair in pairs):.0f} m.",
        flush=True,
    )

    run_rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []

    requests: list[tuple[Pair, str, WeightProfile]] = []
    for pair in pairs:
        requests.append((pair, "shortest", WEIGHT_PROFILES[0]))
        for profile in profiles:
            requests.append((pair, "weighted", profile))
            requests.append((pair, "pareto", profile))

    print(f"Running {len(requests)} route requests ...", flush=True)
    for index, (pair, method, profile) in enumerate(requests, start=1):
        print(
            f"[{index}/{len(requests)}] pair={pair.pair_id} method={method} profile={profile.name}",
            flush=True,
        )
        run_row, rows_for_request = run_one_request(
            pair=pair,
            travel_mode=args.travel_mode,
            method=method,
            profile=profile,
            pareto_max_routes=args.pareto_max_routes,
            pareto_max_labels_per_node=args.pareto_max_labels_per_node,
            pareto_max_total_labels=args.pareto_max_total_labels,
        )
        run_rows.append(run_row)
        route_rows.extend(rows_for_request)

    args.out.mkdir(parents=True, exist_ok=True)
    write_csv(
        args.out / "pairs.csv",
        pair_rows(
            pairs,
            pair_filter=args.pair_filter,
            min_distance=args.min_distance,
            max_distance=args.max_distance,
        ),
    )
    write_csv(args.out / "runs.csv", run_rows)
    write_csv(args.out / "routes.csv", route_rows)

    failure_count = sum(1 for row in run_rows if not row["success"])
    print(f"Done. Wrote CSV files to {args.out}.")
    if failure_count:
        print(f"Warning: {failure_count} requests failed. Inspect runs.csv.")


if __name__ == "__main__":
    main()
