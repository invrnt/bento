"""Summarize a CPython `-X importtime` log: top modules by self and cumulative time, and per top-level package."""
import re
import sys
from collections import defaultdict

rows = []
for line in open(sys.argv[1]):
    m = re.match(r"import time:\s+(\d+) \|\s+(\d+) \|(\s*)(\S+)", line)
    if m:
        rows.append((int(m[1]), int(m[2]), len(m[3]) // 2, m[4]))
n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
total_self = sum(r[0] for r in rows)
print(f"modules={len(rows)} total_self_ms={total_self/1000:.0f}")
print("\n| # | module | self ms | cumulative ms |\n|---|---|---|---|")
for i, r in enumerate(sorted(rows, key=lambda r: -r[1])[:n], 1):
    print(f"| {i} | `{r[3]}` | {r[0]/1000:.1f} | {r[1]/1000:.1f} |")
print("\n| # | module (by self) | self ms |\n|---|---|---|")
for i, r in enumerate(sorted(rows, key=lambda r: -r[0])[:n], 1):
    print(f"| {i} | `{r[3]}` | {r[0]/1000:.1f} |")
pkg = defaultdict(int)
for r in rows:
    pkg[r[3].split(".")[0]] += r[0]
print("\n| package | self ms | share |\n|---|---|---|")
for name, us in sorted(pkg.items(), key=lambda x: -x[1])[:n]:
    print(f"| `{name}` | {us/1000:.0f} | {100*us/total_self:.0f}% |")
