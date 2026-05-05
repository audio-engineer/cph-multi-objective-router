"""Generate evaluation summary tables and figures from CSV output.

Run from the backend folder after run_evaluation.py:

    uv run python scripts/plot_evaluation.py --input evaluation-output \
        --figures ../paper/figures

The script writes summary CSV files and vector PDF figures.
"""

# ruff: noqa: T201

import argparse
import csv
import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Protocol

    class _Pyplot(Protocol):
        def figure(self, *, figsize: tuple[float, float]) -> object: ...

        def boxplot(
            self,
            x: Sequence[Sequence[float]],
            *,
            tick_labels: Sequence[str],
            showfliers: bool,
        ) -> object: ...

        def ylabel(self, ylabel: str) -> object: ...

        def yscale(self, value: str) -> None: ...

        def tight_layout(self) -> None: ...

        def savefig(self, fname: Path) -> None: ...

        def close(self) -> None: ...

        def scatter(
            self,
            x: Sequence[float],
            y: Sequence[float],
            **kwargs: object,
        ) -> object: ...

        def axhline(self, y: float, *, linewidth: float) -> object: ...

        def axvline(self, x: float, *, linewidth: float) -> object: ...

        def xlabel(self, xlabel: str) -> object: ...

        def legend(self, *, frameon: bool) -> object: ...

        def bar(self, x: Sequence[str], height: Sequence[float]) -> object: ...

        def ylim(self, bottom: float, top: float) -> tuple[float, float]: ...

        def hist(self, x: Sequence[float], *, bins: int) -> object: ...

    plt: _Pyplot
else:
    import matplotlib.pyplot as plt


type _CsvValue = str | int | float | bool
type _CsvInputRow = Mapping[str, str]
type _CsvRow = Mapping[str, _CsvValue]
type _CsvOutputRow = dict[str, _CsvValue]


@dataclass(frozen=True, slots=True)
class _PlotEvaluationArgs:
    input: Path
    figures: Path


def _parse_path(value: object) -> Path:
    if isinstance(value, Path):
        return value

    return Path(str(value))


def _parse_args() -> _PlotEvaluationArgs:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--input", type=Path, default=Path("evaluation-output"))
    _ = parser.add_argument(
        "--figures", type=Path, default=Path("evaluation-output/figures")
    )
    values = cast("Mapping[str, object]", vars(parser.parse_args()))

    return _PlotEvaluationArgs(
        input=_parse_path(values["input"]),
        figures=_parse_path(values["figures"]),
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    with path.open(newline="", encoding="utf-8") as file:
        for raw_row in csv.DictReader(file):
            row = {
                key: value
                for key, value in raw_row.items()
                if key is not None and isinstance(value, str)
            }
            rows.append(row)

    return rows


def _as_text(row: _CsvRow, key: str) -> str:
    value = row.get(key, "")

    if isinstance(value, str):
        return value

    return str(value)


def _as_float(row: _CsvRow, key: str, default: float = math.nan) -> float:
    value = row.get(key, "")

    if value == "":
        return default

    return float(value)


def _percentile(values: Sequence[float], q: float) -> float:
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


def _write_csv(path: Path, rows: Sequence[_CsvRow]) -> None:
    if not rows:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _shortest_by_pair(routes: Sequence[_CsvInputRow]) -> dict[str, _CsvInputRow]:
    result: dict[str, _CsvInputRow] = {}

    for row in routes:
        if row["method"] == "shortest" and row["route_index"] == "0":
            result[row["pair_id"]] = row

    return result


def _add_quality_fields(routes: Sequence[_CsvInputRow]) -> list[_CsvOutputRow]:
    shortest = _shortest_by_pair(routes)
    enriched: list[_CsvOutputRow] = []

    for row in routes:
        base = shortest.get(row["pair_id"])
        if base is None:
            continue

        distance = _as_float(row, "distance_m")
        base_distance = _as_float(base, "distance_m")
        distance_overhead_pct = (
            ((distance / base_distance) - 1.0) * 100.0
            if base_distance > 0
            else math.nan
        )
        score_gains = (
            _as_float(row, "snow_free_score") - _as_float(base, "snow_free_score"),
            _as_float(row, "flat_score") - _as_float(base, "flat_score"),
            _as_float(row, "scenic_score") - _as_float(base, "scenic_score"),
        )
        enriched_row = cast("_CsvOutputRow", dict(row))
        enriched_row.update(
            {
                "distance_overhead_pct": distance_overhead_pct,
                "max_score_gain_pp": max(score_gains),
                "snow_free_gain_pp": score_gains[0],
                "flat_gain_pp": score_gains[1],
                "scenic_gain_pp": score_gains[2],
            }
        )
        enriched.append(enriched_row)

    return enriched


def _summarize_runs(runs: Sequence[_CsvInputRow]) -> list[_CsvOutputRow]:
    by_method: defaultdict[str, list[_CsvInputRow]] = defaultdict(list)

    for row in runs:
        if row["success"] == "True":
            by_method[row["method"]].append(row)

    rows: list[_CsvOutputRow] = []
    for method, group in sorted(by_method.items()):
        runtimes = [_as_float(row, "runtime_ms") for row in group]
        route_counts = [_as_float(row, "route_count") for row in group]
        total_labels = [
            _as_float(row, "total_labels") for row in group if row["total_labels"]
        ]
        destination_labels = [
            _as_float(row, "destination_labels")
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
                "p95_runtime_ms": round(_percentile(runtimes, 0.95), 2),
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


def _summarize_quality(
    enriched: Sequence[_CsvRow], *, include_neutral: bool
) -> list[_CsvOutputRow]:
    by_method: defaultdict[str, list[_CsvRow]] = defaultdict(list)

    for row in enriched:
        method = _as_text(row, "method")
        profile = _as_text(row, "profile")
        if method == "shortest":
            continue
        if not include_neutral and profile == "neutral":
            continue
        by_method[method].append(row)

    rows: list[_CsvOutputRow] = []
    for method, group in sorted(by_method.items()):
        overhead = [_as_float(row, "distance_overhead_pct") for row in group]
        gain = [_as_float(row, "max_score_gain_pp") for row in group]
        rows.append(
            {
                "method": method,
                "profile_scope": "all_profiles"
                if include_neutral
                else "preference_profiles",
                "route_rows": len(group),
                "median_distance_overhead_pct": round(statistics.median(overhead), 2),
                "p95_distance_overhead_pct": round(_percentile(overhead, 0.95), 2),
                "median_max_score_gain_pp": round(statistics.median(gain), 2),
                "p95_max_score_gain_pp": round(_percentile(gain, 0.95), 2),
            }
        )

    return rows


def _summarize_quality_by_profile(
    enriched: Sequence[_CsvRow],
) -> list[_CsvOutputRow]:
    by_group: defaultdict[tuple[str, str], list[_CsvRow]] = defaultdict(list)

    for row in enriched:
        method = _as_text(row, "method")
        profile = _as_text(row, "profile")
        if method != "shortest":
            by_group[(method, profile)].append(row)

    rows: list[_CsvOutputRow] = []
    for (method, profile), group in sorted(by_group.items()):
        overhead = [_as_float(row, "distance_overhead_pct") for row in group]
        gain = [_as_float(row, "max_score_gain_pp") for row in group]
        rows.append(
            {
                "method": method,
                "profile": profile,
                "route_rows": len(group),
                "median_distance_overhead_pct": round(statistics.median(overhead), 2),
                "p95_distance_overhead_pct": round(_percentile(overhead, 0.95), 2),
                "median_max_score_gain_pp": round(statistics.median(gain), 2),
                "p95_max_score_gain_pp": round(_percentile(gain, 0.95), 2),
            }
        )

    return rows


def _summarize_sensitivity(routes: Sequence[_CsvInputRow]) -> list[_CsvOutputRow]:
    # Top route only, because this is what the UI recommends by default.
    groups: defaultdict[tuple[str, str], dict[str, str]] = defaultdict(dict)

    for row in routes:
        if row["method"] == "shortest" or row["route_index"] != "0":
            continue
        groups[(row["method"], row["pair_id"])][row["profile"]] = row["signature"]

    by_method: defaultdict[str, list[int]] = defaultdict(list)
    changed_from_neutral: defaultdict[str, list[int]] = defaultdict(list)
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

    rows: list[_CsvOutputRow] = []
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


def _plot_runtime(runs: Sequence[_CsvInputRow], output: Path) -> None:
    methods = ["shortest", "weighted", "pareto"]
    data = [
        [
            _as_float(row, "runtime_ms")
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


def _plot_detour_gain(enriched: Sequence[_CsvRow], output: Path) -> None:
    _ = plt.figure(figsize=(3.35, 2.35))

    for method, marker in [("weighted", "o"), ("pareto", "x")]:
        group = [
            row
            for row in enriched
            if _as_text(row, "method") == method
            and _as_text(row, "profile") != "neutral"
        ]
        _ = plt.scatter(
            [_as_float(row, "distance_overhead_pct") for row in group],
            [_as_float(row, "max_score_gain_pp") for row in group],
            marker=marker,
            s=16,
            alpha=0.75,
            label=method,
        )

    _ = plt.axhline(0.0, linewidth=0.8)
    _ = plt.axvline(0.0, linewidth=0.8)
    _ = plt.xlabel("Distance overhead vs. shortest (%)")
    _ = plt.ylabel("Best score gain (pp)")
    _ = plt.legend(frameon=False)
    plt.tight_layout()
    plt.savefig(output)
    plt.close()


def _plot_sensitivity(summary: Sequence[_CsvRow], output: Path) -> None:
    methods = [_as_text(row, "method") for row in summary]
    values = [_as_float(row, "mean_unique_top_routes") for row in summary]
    _ = plt.figure(figsize=(3.35, 2.20))
    _ = plt.bar(methods, values)
    _ = plt.ylabel("Mean unique top routes")
    _ = plt.ylim(0.0, max([*values, 1.0]) + 0.5)
    plt.tight_layout()
    plt.savefig(output)
    plt.close()


def _plot_pareto_labels(runs: Sequence[_CsvInputRow], output: Path) -> None:
    labels = [
        _as_float(row, "total_labels") / 1000.0
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


def _main() -> None:
    args = _parse_args()
    args.figures.mkdir(parents=True, exist_ok=True)

    runs = _read_csv(args.input / "runs.csv")
    routes = _read_csv(args.input / "routes.csv")
    enriched = _add_quality_fields(routes)

    run_summary = _summarize_runs(runs)
    quality_summary = _summarize_quality(enriched, include_neutral=True)
    quality_preference_summary = _summarize_quality(enriched, include_neutral=False)
    quality_by_profile = _summarize_quality_by_profile(enriched)
    sensitivity_summary = _summarize_sensitivity(routes)

    _write_csv(args.input / "runtime_summary.csv", run_summary)
    _write_csv(args.input / "route_quality_summary.csv", quality_summary)
    _write_csv(
        args.input / "route_quality_preference_summary.csv", quality_preference_summary
    )
    _write_csv(args.input / "route_quality_by_profile.csv", quality_by_profile)
    _write_csv(args.input / "sensitivity_summary.csv", sensitivity_summary)
    _write_csv(args.input / "routes_enriched.csv", enriched)

    _plot_runtime(runs, args.figures / "evaluation_runtime_boxplot.pdf")
    _plot_detour_gain(enriched, args.figures / "evaluation_detour_gain_scatter.pdf")
    _plot_sensitivity(
        sensitivity_summary, args.figures / "evaluation_weight_sensitivity.pdf"
    )
    _plot_pareto_labels(runs, args.figures / "evaluation_pareto_labels_histogram.pdf")

    print("Wrote summary CSV files and figures to", args.input, "and", args.figures)


if __name__ == "__main__":
    _main()
