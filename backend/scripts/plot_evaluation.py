"""Generate evaluation summary tables and figures from CSV output.

Run from the backend folder after run_evaluation.py:

    uv run python scripts/plot_evaluation.py --input evaluation-output --figures ../paper/figures

The script writes summary CSV files and vector PDF figures.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--input", type=Path, default=Path("evaluation-output"))
    _ = parser.add_argument(
        "--figures", type=Path, default=Path("evaluation-output/figures")
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def as_float(row: dict[str, str], key: str, default: float = math.nan) -> float:
    value = row.get(key, "")
    if value == "":
        return default
    return float(value)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return math.nan
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return sorted_values[int(index)]
    return sorted_values[lower] * (upper - index) + sorted_values[upper] * (
        index - lower
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def shortest_by_pair(routes: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    result = {}
    for row in routes:
        if row["method"] == "shortest" and row["route_index"] == "0":
            result[row["pair_id"]] = row
    return result


def add_quality_fields(routes: list[dict[str, str]]) -> list[dict[str, Any]]:
    shortest = shortest_by_pair(routes)
    enriched = []
    for row in routes:
        base = shortest.get(row["pair_id"])
        if base is None:
            continue
        distance = as_float(row, "distance_m")
        base_distance = as_float(base, "distance_m")
        distance_overhead_pct = (
            ((distance / base_distance) - 1.0) * 100.0
            if base_distance > 0
            else math.nan
        )
        score_gains = [
            as_float(row, "snow_free_score") - as_float(base, "snow_free_score"),
            as_float(row, "flat_score") - as_float(base, "flat_score"),
            as_float(row, "scenic_score") - as_float(base, "scenic_score"),
        ]
        enriched.append(
            {
                **row,
                "distance_overhead_pct": distance_overhead_pct,
                "max_score_gain_pp": max(score_gains),
                "snow_free_gain_pp": score_gains[0],
                "flat_gain_pp": score_gains[1],
                "scenic_gain_pp": score_gains[2],
            }
        )
    return enriched


def summarize_runs(runs: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_method: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in runs:
        if row["success"] == "True":
            by_method[row["method"]].append(row)

    rows = []
    for method, group in sorted(by_method.items()):
        runtimes = [as_float(row, "runtime_ms") for row in group]
        route_counts = [as_float(row, "route_count") for row in group]
        total_labels = [
            as_float(row, "total_labels") for row in group if row["total_labels"]
        ]
        destination_labels = [
            as_float(row, "destination_labels")
            for row in group
            if row["destination_labels"]
        ]
        cap_hits = [
            row.get("hit_total_label_cap") == "True"
            for row in group
            if row.get("hit_total_label_cap", "")
        ]
        rows.append(
            {
                "method": method,
                "requests": len(group),
                "median_runtime_ms": round(statistics.median(runtimes), 2),
                "p95_runtime_ms": round(percentile(runtimes, 0.95), 2),
                "max_runtime_ms": round(max(runtimes), 2),
                "median_route_count": round(statistics.median(route_counts), 2),
                "median_total_labels": round(statistics.median(total_labels), 2)
                if total_labels
                else "",
                "median_destination_labels": round(
                    statistics.median(destination_labels), 2
                )
                if destination_labels
                else "",
                "hit_label_cap_pct": round(100.0 * statistics.mean(cap_hits), 2)
                if cap_hits
                else "",
            }
        )
    return rows


def summarize_quality(
    enriched: list[dict[str, Any]], *, include_neutral: bool
) -> list[dict[str, Any]]:
    by_method: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        if row["method"] == "shortest":
            continue
        if not include_neutral and row["profile"] == "neutral":
            continue
        by_method[row["method"]].append(row)

    rows = []
    for method, group in sorted(by_method.items()):
        overhead = [float(row["distance_overhead_pct"]) for row in group]
        gain = [float(row["max_score_gain_pp"]) for row in group]
        rows.append(
            {
                "method": method,
                "profile_scope": "all_profiles"
                if include_neutral
                else "preference_profiles",
                "route_rows": len(group),
                "median_distance_overhead_pct": round(statistics.median(overhead), 2),
                "p95_distance_overhead_pct": round(percentile(overhead, 0.95), 2),
                "median_max_score_gain_pp": round(statistics.median(gain), 2),
                "p95_max_score_gain_pp": round(percentile(gain, 0.95), 2),
            }
        )
    return rows


def summarize_quality_by_profile(
    enriched: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_group: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        if row["method"] != "shortest":
            by_group[(row["method"], row["profile"])].append(row)

    rows = []
    for (method, profile), group in sorted(by_group.items()):
        overhead = [float(row["distance_overhead_pct"]) for row in group]
        gain = [float(row["max_score_gain_pp"]) for row in group]
        rows.append(
            {
                "method": method,
                "profile": profile,
                "route_rows": len(group),
                "median_distance_overhead_pct": round(statistics.median(overhead), 2),
                "p95_distance_overhead_pct": round(percentile(overhead, 0.95), 2),
                "median_max_score_gain_pp": round(statistics.median(gain), 2),
                "p95_max_score_gain_pp": round(percentile(gain, 0.95), 2),
            }
        )
    return rows


def summarize_sensitivity(routes: list[dict[str, str]]) -> list[dict[str, Any]]:
    # Top route only, because this is what the UI recommends by default.
    groups: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    for row in routes:
        if row["method"] == "shortest" or row["route_index"] != "0":
            continue
        groups[(row["method"], row["pair_id"])][row["profile"]] = row["signature"]

    by_method: dict[str, list[int]] = defaultdict(list)
    changed_from_neutral: dict[str, list[int]] = defaultdict(list)
    for (method, _pair_id), signatures_by_profile in groups.items():
        signatures = set(signatures_by_profile.values())
        by_method[method].append(len(signatures))
        neutral = signatures_by_profile.get("neutral")
        if neutral is not None:
            changed = any(
                signature != neutral
                for profile, signature in signatures_by_profile.items()
                if profile != "neutral"
            )
            changed_from_neutral[method].append(1 if changed else 0)

    rows = []
    for method in sorted(by_method):
        unique_counts = by_method[method]
        changed_counts = changed_from_neutral[method]
        rows.append(
            {
                "method": method,
                "pairs": len(unique_counts),
                "mean_unique_top_routes": round(statistics.mean(unique_counts), 2),
                "median_unique_top_routes": round(statistics.median(unique_counts), 2),
                "share_changed_from_neutral_pct": round(
                    100.0 * statistics.mean(changed_counts), 2
                )
                if changed_counts
                else "",
            }
        )
    return rows


def plot_runtime(runs: list[dict[str, str]], output: Path) -> None:
    methods = ["shortest", "weighted", "pareto"]
    data = [
        [
            as_float(row, "runtime_ms")
            for row in runs
            if row["method"] == method and row["success"] == "True"
        ]
        for method in methods
    ]
    _ = plt.figure(figsize=(3.35, 2.35))
    _ = plt.boxplot(data, tick_labels=methods, showfliers=False)
    _ = plt.ylabel("Runtime (ms, log scale)")
    plt.yscale("log")
    plt.tight_layout()
    plt.savefig(output)
    plt.close()


def plot_detour_gain(enriched: list[dict[str, Any]], output: Path) -> None:
    _ = plt.figure(figsize=(3.35, 2.35))
    for method, marker in [("weighted", "o"), ("pareto", "x")]:
        group = [
            row
            for row in enriched
            if row["method"] == method and row["profile"] != "neutral"
        ]
        _ = plt.scatter(
            [float(row["distance_overhead_pct"]) for row in group],
            [float(row["max_score_gain_pp"]) for row in group],
            marker=marker,
            s=16,
            alpha=0.75,
            label=method,
        )
    _ = plt.axhline(0, linewidth=0.8)
    _ = plt.axvline(0, linewidth=0.8)
    _ = plt.xlabel("Distance overhead vs. shortest (%)")
    _ = plt.ylabel("Best score gain (pp)")
    _ = plt.legend(frameon=False)
    plt.tight_layout()
    plt.savefig(output)
    plt.close()


def plot_sensitivity(summary: list[dict[str, Any]], output: Path) -> None:
    methods = [row["method"] for row in summary]
    values = [float(row["mean_unique_top_routes"]) for row in summary]
    plt.figure(figsize=(3.35, 2.20))
    plt.bar(methods, values)
    plt.ylabel("Mean unique top routes")
    plt.ylim(0, max(values + [1]) + 0.5)
    plt.tight_layout()
    plt.savefig(output)
    plt.close()


def plot_pareto_labels(runs: list[dict[str, str]], output: Path) -> None:
    labels = [
        as_float(row, "total_labels") / 1000.0
        for row in runs
        if row["method"] == "pareto" and row["total_labels"]
    ]
    if not labels:
        return
    _ = plt.figure(figsize=(3.35, 2.20))
    _ = plt.hist(labels, bins=12)
    _ = plt.xlabel("Labels generated (thousands)")
    _ = plt.ylabel("Requests")
    plt.tight_layout()
    plt.savefig(output)
    plt.close()


def main() -> None:
    args = parse_args()
    args.figures.mkdir(parents=True, exist_ok=True)

    runs = read_csv(args.input / "runs.csv")
    routes = read_csv(args.input / "routes.csv")
    enriched = add_quality_fields(routes)

    run_summary = summarize_runs(runs)
    quality_summary = summarize_quality(enriched, include_neutral=True)
    quality_preference_summary = summarize_quality(enriched, include_neutral=False)
    quality_by_profile = summarize_quality_by_profile(enriched)
    sensitivity_summary = summarize_sensitivity(routes)

    write_csv(args.input / "runtime_summary.csv", run_summary)
    write_csv(args.input / "route_quality_summary.csv", quality_summary)
    write_csv(
        args.input / "route_quality_preference_summary.csv", quality_preference_summary
    )
    write_csv(args.input / "route_quality_by_profile.csv", quality_by_profile)
    write_csv(args.input / "sensitivity_summary.csv", sensitivity_summary)
    write_csv(args.input / "routes_enriched.csv", enriched)

    plot_runtime(runs, args.figures / "evaluation_runtime_boxplot.pdf")
    plot_detour_gain(enriched, args.figures / "evaluation_detour_gain_scatter.pdf")
    plot_sensitivity(
        sensitivity_summary, args.figures / "evaluation_weight_sensitivity.pdf"
    )
    plot_pareto_labels(runs, args.figures / "evaluation_pareto_labels_histogram.pdf")

    print("Wrote summary CSV files and figures to", args.input, "and", args.figures)


if __name__ == "__main__":
    main()
