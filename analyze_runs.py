#!/usr/bin/env python3
"""Analyze AIG runs under data/benchmarks/<benchmark>/<script><N>/yosys.aig."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd
from aigverse import read_aiger_into_aig, to_edge_list

from utils import FUNCTION_MAP

# Metrics that require a separate optimized AIG tree (not available in this layout).
UNSUPPORTED_METRICS = {"abs_size_diff", "rel_size_diff"}
SUPPORTED_METRICS = sorted(name for name in FUNCTION_MAP if name not in UNSUPPORTED_METRICS)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze AIG files under "
            "data/benchmarks/<benchmark>/<script><N>/yosys.aig (N=1..100 by default)."
        )
    )
    parser.add_argument(
        "--benchmark",
        required=True,
        help="Benchmark name (directory under data/benchmarks/).",
    )
    parser.add_argument(
        "--script",
        required=True,
        help="Script name prefix (directories are named <script>1, <script>2, ...).",
    )
    parser.add_argument(
        "--metric",
        choices=SUPPORTED_METRICS,
        help="Similarity / distance metric for pairwise comparisons.",
    )
    parser.add_argument(
        "--mode",
        choices=("pairwise", "stats"),
        default="pairwise",
        help=(
            "pairwise: compare all run pairs with --metric (default). "
            "stats: collect per-run AIG characteristics (no --metric needed)."
        ),
    )
    parser.add_argument(
        "--data-root",
        default="data/benchmarks",
        help="Root directory containing benchmark folders (default: data/benchmarks).",
    )
    parser.add_argument(
        "--aig-filename",
        default="yosys.aig",
        help="AIG file name inside each run directory (default: yosys.aig).",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="First run index (inclusive, default: 1).",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=100,
        help="Last run index (inclusive, default: 100).",
    )
    parser.add_argument(
        "--save-path",
        default="data/results",
        help="Directory for output CSV files (default: data/results).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if any expected run directory or AIG file is missing.",
    )
    return parser.parse_args()


def run_dir_name(script: str, run_id: int) -> str:
    return f"{script}{run_id}"


def resolve_run_path(
    data_root: str,
    benchmark: str,
    script: str,
    run_id: int,
    aig_filename: str,
) -> str:
    return os.path.join(
        data_root,
        benchmark,
        run_dir_name(script, run_id),
        aig_filename,
    )


def discover_runs(
    data_root: str,
    benchmark: str,
    script: str,
    start: int,
    end: int,
    aig_filename: str,
    strict: bool,
) -> List[Tuple[int, str]]:
    if start < 1 or end < start:
        raise ValueError(f"Invalid run range: start={start}, end={end}")

    benchmark_dir = os.path.join(data_root, benchmark)
    if not os.path.isdir(benchmark_dir):
        raise FileNotFoundError(
            f"Benchmark directory not found: {benchmark_dir}\n"
            f"Expected layout: {data_root}/<benchmark>/<script><N>/{aig_filename}"
        )

    runs: List[Tuple[int, str]] = []
    missing: List[str] = []

    for run_id in range(start, end + 1):
        path = resolve_run_path(data_root, benchmark, script, run_id, aig_filename)
        if os.path.isfile(path):
            runs.append((run_id, path))
        else:
            missing.append(path)

    if not runs:
        raise FileNotFoundError(
            f"No AIG files found for benchmark={benchmark!r}, script={script!r} "
            f"in range {start}..{end}.\n"
            f"Example expected path: "
            f"{resolve_run_path(data_root, benchmark, script, start, aig_filename)}"
        )

    if missing:
        message = (
            f"Missing {len(missing)} / {end - start + 1} expected AIG files "
            f"(found {len(runs)})."
        )
        if strict:
            preview = "\n".join(f"  - {path}" for path in missing[:10])
            more = "" if len(missing) <= 10 else f"\n  ... and {len(missing) - 10} more"
            raise FileNotFoundError(f"{message}\n{preview}{more}")
        print(f"Warning: {message}", file=sys.stderr)

    return runs


def load_aigs(runs: Sequence[Tuple[int, str]]):
    aigs = {}
    for run_id, path in runs:
        print(f"Loading run {run_id}: {path}")
        aigs[run_id] = read_aiger_into_aig(path)
    return aigs


def aig_attr(aig, name: str):
    """Read an AIG statistic whether it is exposed as a method or a property."""
    value = getattr(aig, name)
    return value() if callable(value) else value


def collect_stats(aigs: Dict[int, object]) -> pd.DataFrame:
    rows = []
    for run_id in sorted(aigs):
        aig = aigs[run_id]
        rows.append(
            {
                "run_id": run_id,
                "num_pis": aig_attr(aig, "num_pis"),
                "num_pos": aig_attr(aig, "num_pos"),
                "num_gates": aig_attr(aig, "num_gates"),
                "num_edges": len(to_edge_list(aig)),
                "num_levels": aig_attr(aig, "num_levels"),
            }
        )
    return pd.DataFrame(rows)


def pairwise_scores(
    aigs: Dict[int, object],
    metric_name: str,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    comparison_function = FUNCTION_MAP[metric_name]
    run_ids = sorted(aigs)
    matrix = pd.DataFrame(index=run_ids, columns=run_ids, dtype=float)
    pairs = []

    for i, run_i in enumerate(run_ids):
        matrix.loc[run_i, run_i] = 0.0
        for run_j in run_ids[i + 1 :]:
            score = comparison_function(aigs[run_i], aigs[run_j])
            matrix.loc[run_i, run_j] = score
            matrix.loc[run_j, run_i] = score
            pairs.append({"run_i": run_i, "run_j": run_j, "score": score})
            print(f"Compared {run_i} vs {run_j}: {score}")

    return matrix, pd.DataFrame(pairs)


def output_prefix(benchmark: str, script: str, mode: str, metric: Optional[str]) -> str:
    safe_benchmark = benchmark.replace(os.sep, "_")
    safe_script = script.replace(os.sep, "_")
    if mode == "stats":
        return f"{safe_benchmark}__{safe_script}__stats"
    return f"{safe_benchmark}__{safe_script}__{metric}"


def main() -> None:
    args = parse_arguments()

    if args.mode == "pairwise" and not args.metric:
        raise SystemExit("error: --metric is required when --mode pairwise")

    runs = discover_runs(
        data_root=args.data_root,
        benchmark=args.benchmark,
        script=args.script,
        start=args.start,
        end=args.end,
        aig_filename=args.aig_filename,
        strict=args.strict,
    )
    aigs = load_aigs(runs)

    os.makedirs(args.save_path, exist_ok=True)
    prefix = output_prefix(args.benchmark, args.script, args.mode, args.metric)

    if args.mode == "stats":
        stats_df = collect_stats(aigs)
        out_path = os.path.join(args.save_path, f"{prefix}.csv")
        stats_df.to_csv(out_path, index=False)
        print(f"Saved per-run stats to {out_path}")
        print(stats_df.describe(include="all"))
        return

    matrix_df, pairs_df = pairwise_scores(aigs, args.metric)
    matrix_path = os.path.join(args.save_path, f"{prefix}_matrix.csv")
    pairs_path = os.path.join(args.save_path, f"{prefix}_pairs.csv")
    matrix_df.to_csv(matrix_path, index_label="run_id")
    pairs_df.to_csv(pairs_path, index=False)
    print(f"Saved similarity matrix to {matrix_path}")
    print(f"Saved pairwise scores to {pairs_path}")
    if not pairs_df.empty:
        print(pairs_df["score"].describe())


if __name__ == "__main__":
    main()
