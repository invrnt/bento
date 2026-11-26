from __future__ import annotations

import asyncio

import pytest

from bento.adapters.embeddings import DisabledEmbeddingProvider, MockEmbeddingProvider
from bento.domain.errors import EmbeddingsDisabledError


def test_mock_embedding_provider_is_deterministic_for_text() -> None:
    async def scenario() -> None:
        provider = MockEmbeddingProvider(dimensions=4)

        first_record, first_vector = await provider.embed_text("asset_1", "Factura cafe")
        second_record, second_vector = await provider.embed_text("asset_1", "Factura cafe")

        assert first_record == second_record
        assert first_vector == second_vector
        assert len(first_vector) == 4

    asyncio.run(scenario())


def test_disabled_embedding_provider_reports_disabled() -> None:
    async def scenario() -> None:
        provider = DisabledEmbeddingProvider()

        assert await provider.is_enabled() is False
        with pytest.raises(EmbeddingsDisabledError):
            await provider.embed_text("asset_1", "hello")

    asyncio.run(scenario())

