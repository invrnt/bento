"""Median / P90 per benchmark and metric from Macrobenchmark's *-benchmarkData.json (benchmark/run.sh output)."""
import json
import sys


def pct(values, p):
    values = sorted(values)
    if not values:
        return float("nan")
    k = (len(values) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


for path in sys.argv[1:]:
    for bench in json.load(open(path))["benchmarks"]:
        name = f'{bench["className"].rsplit(".", 1)[-1]}.{bench["name"]}'
        for metric, data in sorted(bench.get("metrics", {}).items()):
            runs = data.get("runs", [])
            print(f"{name:55s} {metric:42s} median {pct(runs, .5):9.1f}  p90 {pct(runs, .9):9.1f}  n={len(runs)}")
        for metric, data in sorted(bench.get("sampledMetrics", {}).items()):
            print(f"{name:55s} {metric:42s} P50 {data['P50']:9.1f}  P90 {data['P90']:9.1f}  P99 {data['P99']:9.1f}")
