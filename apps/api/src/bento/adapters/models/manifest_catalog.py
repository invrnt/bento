"""`ModelCatalogPort` over a parsed model manifest (`infrastructure/models/manifest.json`, schema 1)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bento.domain.smart_search import InvalidModelSpecError, ModelSpec, parse_manifest


class ManifestModelCatalog:
    """The models one Bento release offers. Each `model_id` appears at one pinned revision; a newer
    release that bumps the revision is what `update_available` compares against."""

    def __init__(self, specs: tuple[ModelSpec, ...], default_model_id: str) -> None:
        if not specs:
            raise InvalidModelSpecError("A model catalog needs at least one model")
        if default_model_id not in {spec.model_id for spec in specs}:
            raise InvalidModelSpecError("default_model_id must name a manifest model", {"got": default_model_id})
        self._specs = specs
        self._default_model_id = default_model_id

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ManifestModelCatalog:
        specs, default_model_id = parse_manifest(data)
        return cls(specs, default_model_id)

    @classmethod
    def from_path(cls, path: Path) -> ManifestModelCatalog:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InvalidModelSpecError("Model manifest could not be read", {"error": type(exc).__name__}) from exc
        if not isinstance(data, Mapping):
            raise InvalidModelSpecError("Model manifest must be a JSON object")
        return cls.from_mapping(data)

    @property
    def default_model_id(self) -> str:
        return self._default_model_id

    def default(self) -> ModelSpec:
        spec = self.get(self._default_model_id)
        assert spec is not None  # checked in __init__
        return spec

    def get(self, model_id: str, revision: str | None = None) -> ModelSpec | None:
        for spec in self._specs:
            if spec.model_id == model_id and (revision is None or spec.revision == revision):
                return spec
        return None

    def all(self) -> tuple[ModelSpec, ...]:
        return self._specs
