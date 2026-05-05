"""Run routing evaluation experiments and export CSV data.

Place this file in backend/scripts/run_evaluation.py and run it from the backend
folder, for example:

    uv run python scripts/run_evaluation.py --pairs 20 --seed 7 \
        --travel-mode cycling --min-distance 2000 --max-distance 8000 \
        --pair-filter active

The script loads the same graph state as the FastAPI app, samples
origin-destination pairs from graph nodes, runs shortest, weighted, and Pareto
routing, and writes CSV files to evaluation-output/.

The script intentionally calls the route-planning layer directly instead of the
HTTP endpoint. This measures server-side routing and serialization without
browser caching, geocoding, or front-end rendering noise.
"""

# ruff: noqa: T201

import argparse
import csv
import hashlib
import json
import random
import statistics
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
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
    select_parallel_edge_attributes,
)
from app.graph_state import (  # noqa: E402
    GRAPH_STATE,
    get_graph_for_travel_mode,
    load_graph_state,
)
from app.main import OVERLAY_DIRECTORY, PLACE_NAME  # noqa: E402
from app.models import (  # noqa: E402
    ParetoSearchLabel,
    RouteCoordinates,
    RouteFeatureCollection,
    RouteOptimizationMethod,
    RoutePlanningOptions,
    RoutePreferenceWeights,
    TravelMode,
)
from app.value_parsing import parse_float_or_default  # noqa: E402

if TYPE_CHECKING:
    from app.typing_aliases import EdgeAttributeMap, MultiDiGraphAny


type _CsvValue = str | int | float | bool
type _CsvRow = dict[str, _CsvValue]
type _PairFilter = Literal["random", "active", "changed"]
type _RouteCoordinate = Sequence[float]
type _ShortestPathFunction = Callable[..., list[int]]


@dataclass(frozen=True, slots=True)
class _Pair:
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
class _WeightProfile:
    name: str
    scenic_weight: int
    snow_free_weight: int
    flat_weight: int


@dataclass(frozen=True, slots=True)
class _RunEvaluationArgs:
    pairs: int
    seed: int
    travel_mode: TravelMode
    min_distance: float
    max_distance: float
    max_sampling_attempts: int
    pair_filter: _PairFilter
    active_epsilon: float
    pareto_max_routes: int
    pareto_max_labels_per_node: int
    pareto_max_total_labels: int
    out: Path
    profiles: str


@dataclass(frozen=True, slots=True)
class _SamplingOptions:
    count: int
    seed: int
    min_distance: float
    max_distance: float
    max_attempts: int
    pair_filter: _PairFilter
    active_epsilon: float


@dataclass(frozen=True, slots=True)
class _RoutingOptions:
    travel_mode: TravelMode
    pareto_max_routes: int
    pareto_max_labels_per_node: int
    pareto_max_total_labels: int


WEIGHT_PROFILES: tuple[_WeightProfile, ...] = (
    _WeightProfile("neutral", scenic_weight=0, snow_free_weight=0, flat_weight=0),
    _WeightProfile("scenic", scenic_weight=100, snow_free_weight=0, flat_weight=0),
    _WeightProfile("snow_free", scenic_weight=0, snow_free_weight=100, flat_weight=0),
    _WeightProfile("flat", scenic_weight=0, snow_free_weight=0, flat_weight=100),
    _WeightProfile("balanced", scenic_weight=50, snow_free_weight=50, flat_weight=50),
)


def _parse_travel_mode(value: object) -> TravelMode:
    if value in {"walking", "cycling"}:
        return cast("TravelMode", value)

    error_message = f"Unsupported travel mode: {value}"
    raise SystemExit(error_message)


def _parse_pair_filter(value: object) -> _PairFilter:
    if value in {"random", "active", "changed"}:
        return cast("_PairFilter", value)

    error_message = f"Unsupported pair filter: {value}"
    raise SystemExit(error_message)


def _parse_path(value: object) -> Path:
    if isinstance(value, Path):
        return value

    return Path(str(value))


def _parse_int(value: object) -> int:
    if isinstance(value, int):
        return value

    if isinstance(value, str):
        return int(value)

    error_message = f"Expected integer argument, got {value!r}."
    raise SystemExit(error_message)


def _parse_float(value: object) -> float:
    if isinstance(value, int | float | str):
        return float(value)

    error_message = f"Expected numeric argument, got {value!r}."
    raise SystemExit(error_message)


def _parse_args() -> _RunEvaluationArgs:
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

    values = cast("Mapping[str, object]", vars(parser.parse_args()))

    return _RunEvaluationArgs(
        pairs=_parse_int(values["pairs"]),
        seed=_parse_int(values["seed"]),
        travel_mode=_parse_travel_mode(values["travel_mode"]),
        min_distance=_parse_float(values["min_distance"]),
        max_distance=_parse_float(values["max_distance"]),
        max_sampling_attempts=_parse_int(values["max_sampling_attempts"]),
        pair_filter=_parse_pair_filter(values["pair_filter"]),
        active_epsilon=_parse_float(values["active_epsilon"]),
        pareto_max_routes=_parse_int(values["pareto_max_routes"]),
        pareto_max_labels_per_node=_parse_int(values["pareto_max_labels_per_node"]),
        pareto_max_total_labels=_parse_int(values["pareto_max_total_labels"]),
        out=_parse_path(values["out"]),
        profiles=str(values["profiles"]),
    )


def _load_profiles(profile_arg: str) -> list[_WeightProfile]:
    names = {name.strip() for name in profile_arg.split(",") if name.strip()}
    profiles = [profile for profile in WEIGHT_PROFILES if profile.name in names]

    if not profiles:
        error_message = "No valid weight profiles selected."
        raise SystemExit(error_message)

    return profiles


def _node_coordinates(graph: MultiDiGraphAny, node_id: int) -> tuple[float, float]:
    node = cast("Mapping[str, object]", graph.nodes[node_id])

    return (
        parse_float_or_default(node.get("x"), default=0.0),
        parse_float_or_default(node.get("y"), default=0.0),
    )


def _percent_score(penalty: float, distance: float) -> float:
    if distance <= 0:
        return 0.0

    return max(0.0, min(100.0, (1.0 - penalty / distance) * 100.0))


def _select_shortest_edge_attributes(
    graph: MultiDiGraphAny, source_node_id: int, target_node_id: int
) -> EdgeAttributeMap:
    edge_attributes = select_parallel_edge_attributes(
        graph,
        source_node_id,
        target_node_id,
        ranking_key=lambda attrs: parse_float_or_default(
            attrs.get("length"),
            default=0.0,
        ),
    )

    if edge_attributes is None:
        raise nx.NetworkXNoPath

    return edge_attributes


def _path_cost_vector(
    graph: MultiDiGraphAny, node_path: Sequence[int]
) -> tuple[float, float, float, float]:
    distance = snow = hills = scenic = 0.0

    for source_node_id, target_node_id in pairwise(node_path):
        edge_attrs = _select_shortest_edge_attributes(
            graph, source_node_id, target_node_id
        )
        edge_distance, snow_penalty, hill_penalty, scenic_penalty = (
            compute_edge_cost_components(edge_attrs)
        )
        distance += edge_distance
        snow += snow_penalty
        hills += hill_penalty
        scenic += scenic_penalty

    return distance, snow, hills, scenic


def _path_has_active_objective(
    cost_vector: tuple[float, float, float, float], *, epsilon: float
) -> bool:
    distance, snow_penalty, uphill_penalty, scenic_penalty = cost_vector

    return (
        snow_penalty > epsilon
        or uphill_penalty > epsilon
        or scenic_penalty < distance - epsilon
    )


def _weighted_path_signature(
    graph: MultiDiGraphAny,
    source_node_id: int,
    target_node_id: int,
    profile: _WeightProfile,
) -> tuple[int, ...]:
    weights = RoutePreferenceWeights(
        scenic_weight=profile.scenic_weight,
        snow_free_weight=profile.snow_free_weight,
        flat_weight=profile.flat_weight,
    )
    shortest_path = cast("_ShortestPathFunction", nx.shortest_path)

    return tuple(
        shortest_path(
            graph,
            source=source_node_id,
            target=target_node_id,
            weight=build_weighted_edge_cost_function(
                normalize_route_preference_weights(weights)
            ),
        )
    )


def _weighted_path_changes(
    graph: MultiDiGraphAny,
    source_node_id: int,
    target_node_id: int,
    profiles: Sequence[_WeightProfile],
) -> bool:
    neutral = _weighted_path_signature(
        graph, source_node_id, target_node_id, WEIGHT_PROFILES[0]
    )

    return any(
        _weighted_path_signature(graph, source_node_id, target_node_id, profile)
        != neutral
        for profile in profiles
        if profile.name != "neutral"
    )


def _sample_pairs(
    graph: MultiDiGraphAny,
    options: _SamplingOptions,
    profiles: Sequence[_WeightProfile],
) -> list[_Pair]:
    rng = random.Random(options.seed)  # noqa: S311 - deterministic benchmark sampling.
    nodes = list(cast("Iterable[int]", graph.nodes))
    pairs: list[_Pair] = []
    seen: set[tuple[int, int]] = set()
    shortest_path = cast("_ShortestPathFunction", nx.shortest_path)

    for _attempt in range(options.max_attempts):
        if len(pairs) >= options.count:
            break

        origin_node, destination_node = rng.sample(nodes, 2)
        if (origin_node, destination_node) in seen:
            continue

        seen.add((origin_node, destination_node))

        try:
            path = shortest_path(
                graph,
                source=origin_node,
                target=destination_node,
                weight="length",
            )
            cost_vector = _path_cost_vector(graph, path)
        except nx.NetworkXNoPath, nx.NodeNotFound:
            continue

        distance, snow_penalty, uphill_penalty, scenic_penalty = cost_vector
        if not (options.min_distance <= distance <= options.max_distance):
            continue

        if options.pair_filter in {
            "active",
            "changed",
        } and not _path_has_active_objective(
            cost_vector,
            epsilon=options.active_epsilon,
        ):
            continue

        if options.pair_filter == "changed" and not _weighted_path_changes(
            graph,
            origin_node,
            destination_node,
            profiles,
        ):
            continue

        origin_lon, origin_lat = _node_coordinates(graph, origin_node)
        destination_lon, destination_lat = _node_coordinates(graph, destination_node)
        pairs.append(
            _Pair(
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
                shortest_snow_free_score=_percent_score(snow_penalty, distance),
                shortest_flat_score=_percent_score(uphill_penalty, distance),
                shortest_scenic_score=_percent_score(scenic_penalty, distance),
            )
        )

    if len(pairs) < options.count:
        count = len(pairs)
        attempts = options.max_attempts
        sampled = f"Only sampled {count} valid pairs after {attempts} attempts."
        advice = "Try widening --min-distance/--max-distance, increasing"
        command_hint = (
            "--max-sampling-attempts, lowering --pairs, or using --pair-filter random."
        )
        error_message = f"{sampled} {advice} {command_hint}"
        raise SystemExit(error_message)

    return pairs


def _route_signature(coordinates: Iterable[_RouteCoordinate]) -> str:
    rounded: list[tuple[float, float]] = []

    for coordinate in coordinates:
        lon = float(coordinate[0])
        lat = float(coordinate[1])
        rounded.append((round(lon, 6), round(lat, 6)))

    payload = json.dumps(rounded, separators=(",", ":"))

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _route_options(
    *,
    method: RouteOptimizationMethod,
    profile: _WeightProfile,
    routing_options: _RoutingOptions,
) -> RoutePlanningOptions:
    return RoutePlanningOptions(
        route_optimization_method=method,
        preference_weights=RoutePreferenceWeights(
            scenic_weight=profile.scenic_weight,
            snow_free_weight=profile.snow_free_weight,
            flat_weight=profile.flat_weight,
        ),
        pareto_max_routes=routing_options.pareto_max_routes,
        pareto_max_labels_per_node=routing_options.pareto_max_labels_per_node,
        pareto_max_total_labels=routing_options.pareto_max_total_labels,
    )


def _run_one_request(
    pair: _Pair,
    method: RouteOptimizationMethod,
    profile: _WeightProfile,
    routing_options: _RoutingOptions,
) -> tuple[_CsvRow, list[_CsvRow]]:
    coordinates = RouteCoordinates(
        origin_longitude=pair.origin_longitude,
        origin_latitude=pair.origin_latitude,
        destination_longitude=pair.destination_longitude,
        destination_latitude=pair.destination_latitude,
    )
    options = _route_options(
        method=method,
        profile=profile,
        routing_options=routing_options,
    )

    pareto_stats: _CsvRow = {
        "total_labels": "",
        "destination_labels": "",
        "hit_total_label_cap": "",
    }

    original_pareto_search = route_planner_module.run_pareto_label_search

    def instrumented_pareto_search(
        graph: MultiDiGraphAny,
        origin_node_id: int,
        destination_node_id: int,
        *,
        max_labels_per_node: int,
        max_total_labels: int,
    ) -> tuple[list[ParetoSearchLabel], list[int]]:
        labels, destination_label_ids = original_pareto_search(
            graph,
            origin_node_id,
            destination_node_id,
            max_labels_per_node=max_labels_per_node,
            max_total_labels=max_total_labels,
        )
        pareto_stats["total_labels"] = len(labels)
        pareto_stats["destination_labels"] = len(destination_label_ids)
        pareto_stats["hit_total_label_cap"] = (
            len(labels) >= routing_options.pareto_max_total_labels
        )

        return labels, destination_label_ids

    start = time.perf_counter()
    try:
        if method == "pareto":
            with patch(
                "app.route_planner.run_pareto_label_search",
                side_effect=instrumented_pareto_search,
            ):
                response: RouteFeatureCollection | None = (
                    route_planner_module.build_route_feature_collection(
                        graph_state=GRAPH_STATE,
                        route_coordinates=coordinates,
                        travel_mode=routing_options.travel_mode,
                        route_options=options,
                    )
                )
        else:
            response = route_planner_module.build_route_feature_collection(
                graph_state=GRAPH_STATE,
                route_coordinates=coordinates,
                travel_mode=routing_options.travel_mode,
                route_options=options,
            )
        success = True
        error = ""
    except Exception as exception:  # noqa: BLE001 - evaluation should log failures.
        response = None
        success = False
        error = repr(exception)

    runtime_ms = (time.perf_counter() - start) * 1000.0

    run_row: _CsvRow = {
        "pair_id": pair.pair_id,
        "travel_mode": routing_options.travel_mode,
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

    route_rows: list[_CsvRow] = []
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
                    "travel_mode": routing_options.travel_mode,
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
                    "snow_free_score": _percent_score(snow_penalty, distance),
                    "flat_score": _percent_score(uphill_penalty, distance),
                    "scenic_score": _percent_score(scenic_penalty, distance),
                    "signature": _route_signature(
                        cast("Iterable[_RouteCoordinate]", feature.geometry.coordinates)
                    ),
                }
            )

    return run_row, route_rows


def _write_csv(path: Path, rows: Sequence[_CsvRow]) -> None:
    if not rows:
        error_message = f"No rows to write for {path}"
        raise SystemExit(error_message)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _pair_rows(
    pairs: Sequence[_Pair],
    *,
    pair_filter: _PairFilter,
    min_distance: float,
    max_distance: float,
) -> list[_CsvRow]:
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


def _main() -> None:
    args = _parse_args()
    profiles = _load_profiles(args.profiles)
    sampling_options = _SamplingOptions(
        count=args.pairs,
        seed=args.seed,
        min_distance=args.min_distance,
        max_distance=args.max_distance,
        max_attempts=args.max_sampling_attempts,
        pair_filter=args.pair_filter,
        active_epsilon=args.active_epsilon,
    )
    routing_options = _RoutingOptions(
        travel_mode=args.travel_mode,
        pareto_max_routes=args.pareto_max_routes,
        pareto_max_labels_per_node=args.pareto_max_labels_per_node,
        pareto_max_total_labels=args.pareto_max_total_labels,
    )

    print("Loading graphs and overlays ...", flush=True)
    load_graph_state(
        place_name=PLACE_NAME,
        overlay_directory=OVERLAY_DIRECTORY,
        graph_state=GRAPH_STATE,
    )
    graph = get_graph_for_travel_mode(GRAPH_STATE, args.travel_mode)

    print("Sampling origin-destination pairs ...", flush=True)
    pairs = _sample_pairs(graph, sampling_options, profiles)
    median_distance = statistics.median(pair.shortest_distance_m for pair in pairs)
    sampled_message = " ".join(
        (
            f"Sampled {len(pairs)} pairs;",
            f"shortest-distance median {median_distance:.0f} m.",
        )
    )
    print(sampled_message, flush=True)

    run_rows: list[_CsvRow] = []
    route_rows: list[_CsvRow] = []

    requests: list[tuple[_Pair, RouteOptimizationMethod, _WeightProfile]] = []
    for pair in pairs:
        requests.append((pair, "shortest", WEIGHT_PROFILES[0]))
        for profile in profiles:
            requests.append((pair, "weighted", profile))
            requests.append((pair, "pareto", profile))

    print(f"Running {len(requests)} route requests ...", flush=True)
    for index, (pair, method, profile) in enumerate(requests, start=1):
        progress = " ".join(
            (
                f"[{index}/{len(requests)}]",
                f"pair={pair.pair_id}",
                f"method={method}",
                f"profile={profile.name}",
            )
        )
        print(progress, flush=True)
        run_row, rows_for_request = _run_one_request(
            pair,
            method,
            profile,
            routing_options,
        )
        run_rows.append(run_row)
        route_rows.extend(rows_for_request)

    args.out.mkdir(parents=True, exist_ok=True)
    _write_csv(
        args.out / "pairs.csv",
        _pair_rows(
            pairs,
            pair_filter=args.pair_filter,
            min_distance=args.min_distance,
            max_distance=args.max_distance,
        ),
    )
    _write_csv(args.out / "runs.csv", run_rows)
    _write_csv(args.out / "routes.csv", route_rows)

    failure_count = sum(1 for row in run_rows if row["success"] is False)
    print(f"Done. Wrote CSV files to {args.out}.")
    if failure_count:
        print(f"Warning: {failure_count} requests failed. Inspect runs.csv.")


if __name__ == "__main__":
    _main()
