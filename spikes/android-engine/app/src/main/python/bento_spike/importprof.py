"""Per-module import timing (self and cumulative), the in-process equivalent of `python -X importtime`."""

from __future__ import annotations

import sys
import time
from importlib.abc import MetaPathFinder

records: dict[str, list[float]] = {}  # name -> [cumulative_s, self_s]
_stack: list[list[float]] = []


class _TimingLoader:
    def __init__(self, loader: object, name: str) -> None:
        self._loader = loader
        self._name = name

    def __getattr__(self, item: str) -> object:
        return getattr(self._loader, item)

    def create_module(self, spec: object) -> object:
        return self._loader.create_module(spec)  # type: ignore[attr-defined]

    def exec_module(self, module: object) -> None:
        frame = [0.0]  # time spent in nested imports
        _stack.append(frame)
        started = time.perf_counter()
        try:
            self._loader.exec_module(module)  # type: ignore[attr-defined]
        finally:
            elapsed = time.perf_counter() - started
            _stack.pop()
            if _stack:
                _stack[-1][0] += elapsed
            records[self._name] = [elapsed, elapsed - frame[0]]


class _TimingFinder(MetaPathFinder):
    def find_spec(self, name, path, target=None):  # type: ignore[no-untyped-def]
        for finder in sys.meta_path:
            if finder is self or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(name, path, target)
            if spec is not None:
                if spec.loader is not None and hasattr(spec.loader, "exec_module"):
                    spec.loader = _TimingLoader(spec.loader, name)  # type: ignore[assignment]
                return spec
        return None


def enable() -> None:
    if not any(isinstance(finder, _TimingFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _TimingFinder())


def disable() -> None:
    sys.meta_path[:] = [finder for finder in sys.meta_path if not isinstance(finder, _TimingFinder)]


def top(count: int = 20) -> dict[str, list[dict[str, float]]]:
    def rows(index: int) -> list[dict[str, float]]:
        ordered = sorted(records.items(), key=lambda item: item[1][index], reverse=True)[:count]
        return [{"module": name, "cumulative_ms": round(c * 1000, 1), "self_ms": round(s * 1000, 1)} for name, (c, s) in ordered]

    top_level: dict[str, float] = {}
    for name, (_, self_s) in records.items():
        root = name.split(".")[0]
        top_level[root] = top_level.get(root, 0.0) + self_s
    packages = sorted(top_level.items(), key=lambda item: item[1], reverse=True)[:count]
    return {
        "by_self": rows(1),
        "by_cumulative": rows(0),
        "by_top_level_package_self_ms": [{"package": name, "self_ms": round(s * 1000, 1)} for name, s in packages],
        "modules_imported": len(records),
    }
