from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from bento.adapters.embeddings import (
    EmbeddingInputTooLongError,
    EmbeddingModelUnavailableError,
    EmbeddingServerError,
    LlamaCppEmbeddingProvider,
)
from bento.domain.smart_search import (
    EmbeddingSpace,
    Modality,
    ModelSpec,
    UnsupportedModalityError,
    estimate_tokens,
    parse_manifest,
    truncate_and_renormalize,
)
from bento.ports.models import EndpointInfo
from tests.fakes.llama_server import FakeLlamaServer, fake_vector

MANIFEST = json.loads((Path(__file__).parents[1] / "smart_search" / "manifest_v1.json").read_text(encoding="utf-8"))
SPECS, _ = parse_manifest(MANIFEST)
EG2, QWEN = SPECS
KEY = "unit-test-key"
STARTED = "2026-11-26T00:00:00+00:00"


@pytest.fixture
def short_dir() -> Iterator[Path]:
    """Unix socket paths must stay short (macOS temp dirs are long)."""
    base = "/tmp" if os.path.isdir("/tmp") else None
    path = Path(tempfile.mkdtemp(prefix="bento-t-", dir=base))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def key_file(tmp_path: Path, key: str = KEY) -> Path:
    path = tmp_path / "embedder.key"
    path.write_text(key, encoding="utf-8")
    return path


def endpoint(base_url: str, space_id: str, key_path: Path) -> EndpointInfo:
    return EndpointInfo(space_id=space_id, base_url=base_url, api_key_file=key_path, pid=None, started_at=STARTED)


def provider_for(
    spec: ModelSpec, fake: FakeLlamaServer, tmp_path: Path, *, dims: int | None = None
) -> LlamaCppEmbeddingProvider:
    space = spec.space(dims)
    info = endpoint(fake.base_url, space.id, key_file(tmp_path))
    return LlamaCppEmbeddingProvider(spec=spec, space=space, endpoint=lambda: info)


def test_query_prefix_key_and_model_on_the_wire(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key=KEY, dims=768) as fake:
            provider = provider_for(EG2, fake, tmp_path, dims=512)  # a truncated space (512 was the D9 default)

            vector = await provider.embed_query("  fotos de la playa  ")

            assert fake.state.embedding_inputs() == [["task: search result | query: fotos de la playa"]]
            request = fake.state.embedding_requests()[0]
            assert request["authorization"] == f"Bearer {KEY}"
            assert request["body"]["model"] == EG2.model_id
            expected = fake_vector("task: search result | query: fotos de la playa", 768)
            assert vector == truncate_and_renormalize(expected, 512)

    asyncio.run(scenario())


def test_document_prefix_uses_title_or_none(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key=KEY, dims=768) as fake:
            provider = provider_for(EG2, fake, tmp_path)

            await provider.embed_documents(["Factura de la luz de marzo"], title="luz_marzo.pdf")
            await provider.embed_documents(["Sin título"])

            assert fake.state.embedding_inputs() == [
                ["title: luz_marzo.pdf | text: Factura de la luz de marzo"],
                ["title: none | text: Sin título"],
            ]

    asyncio.run(scenario())


def test_qwen_prefixes_and_no_client_eos(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key=KEY, dims=1024) as fake:
            provider = provider_for(QWEN, fake, tmp_path)

            await provider.embed_query("recibo del agua")
            await provider.embed_documents(["Canal de aguas municipal"], title="agua.pdf")

            query_inputs, document_inputs = fake.state.embedding_inputs()
            assert query_inputs == ["Instruct: Given a search query, retrieve relevant files\nQuery:recibo del agua"]
            assert document_inputs == ["Canal de aguas municipal"]
            assert all("<|endoftext|>" not in text for text in [*query_inputs, *document_inputs])

    asyncio.run(scenario())


def test_documents_are_sent_in_batches_of_eight_in_order(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key=KEY, dims=768) as fake:
            provider = provider_for(EG2, fake, tmp_path, dims=512)
            texts = [f"fragmento {index}" for index in range(19)]

            vectors = await provider.embed_documents(texts, title="doc.txt")

            assert [len(batch) for batch in fake.state.embedding_inputs()] == [8, 8, 3]
            assert len(vectors) == 19
            for text, vector in zip(texts, vectors, strict=True):
                expected = fake_vector(f"title: doc.txt | text: {text}", 768)
                assert vector == truncate_and_renormalize(expected, 512)

    asyncio.run(scenario())


def test_matryoshka_truncation_renormalises(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key=KEY, dims=768) as fake:
            for dims in (768, 256, 128):
                provider = provider_for(EG2, fake, tmp_path, dims=dims)
                (vector,) = await provider.embed_documents(["hola"])
                assert len(vector) == dims
                assert math.isclose(math.fsum(v * v for v in vector), 1.0, rel_tol=1e-9)

    asyncio.run(scenario())


def test_server_vector_shorter_than_space_is_an_error(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key=KEY, dims=64) as fake:
            provider = provider_for(EG2, fake, tmp_path)
            with pytest.raises(EmbeddingServerError, match="unusable vector"):
                await provider.embed_query("hola")

    asyncio.run(scenario())


def test_inputs_over_ubatch_are_rejected_before_sending(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key=KEY, dims=768) as fake:
            provider = provider_for(EG2, fake, tmp_path)
            too_long = "palabra " * 800
            assert estimate_tokens(EG2.format_document(too_long, None)) >= EG2.ubatch_tokens

            with pytest.raises(EmbeddingInputTooLongError):
                await provider.embed_documents(["corto", too_long])

            assert fake.state.embedding_requests() == []

    asyncio.run(scenario())


def test_long_query_is_cut_to_fit_the_batch(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key=KEY, dims=768) as fake:
            provider = provider_for(EG2, fake, tmp_path)

            await provider.embed_query("palabra " * 2000)

            (sent,) = fake.state.embedding_inputs()[0]
            assert sent.startswith("task: search result | query: palabra")
            assert estimate_tokens(sent) < EG2.ubatch_tokens

    asyncio.run(scenario())


def test_wrong_key_is_a_server_error(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key="the-real-key", dims=768) as fake:
            provider = provider_for(EG2, fake, tmp_path)
            with pytest.raises(EmbeddingServerError, match="401"):
                await provider.embed_query("hola")

    asyncio.run(scenario())


def test_server_error_carries_status_and_short_message(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key=KEY, dims=768, embedding_status=500) as fake:
            provider = provider_for(EG2, fake, tmp_path)
            with pytest.raises(EmbeddingServerError, match="500: Injected failure"):
                await provider.embed_documents(["texto privado"])

    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform == "win32", reason="Unix sockets: Linux and macOS")
def test_unix_socket_endpoint(tmp_path: Path, short_dir: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key=KEY, dims=768, socket_path=str(short_dir / "embedder.sock")) as fake:
            assert fake.base_url.startswith("http+unix://")
            provider = provider_for(EG2, fake, tmp_path)

            vector = await provider.embed_query("factura")

            assert len(vector) == 768  # D9: the default space keeps EG2's native dims
            assert fake.state.embedding_requests()[0]["authorization"] == f"Bearer {KEY}"

    asyncio.run(scenario())


def test_text_only_space_rejects_images(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key=KEY, dims=768) as fake:
            provider = provider_for(EG2, fake, tmp_path)
            image = tmp_path / "foto.jpg"
            image.write_bytes(b"\xff\xd8\xff")

            with pytest.raises(UnsupportedModalityError):
                await provider.embed_image(image)

            assert fake.state.requests == []

    asyncio.run(scenario())


def test_multimodal_space_sends_image_content_parts_without_prefix(tmp_path: Path) -> None:
    async def scenario() -> None:
        multimodal = replace(EG2, modalities=frozenset({Modality.TEXT, Modality.IMAGE}))
        with FakeLlamaServer(api_key=KEY, dims=768) as fake:
            space = multimodal.space(with_images=True)
            info = endpoint(fake.base_url, space.id, key_file(tmp_path))
            provider = LlamaCppEmbeddingProvider(spec=multimodal, space=space, endpoint=lambda: info)
            image = tmp_path / "preview.jpg"
            image.write_bytes(b"\xff\xd8\xffpreview")

            vector = await provider.embed_image(image)

            assert len(vector) == 768
            (inputs,) = fake.state.embedding_inputs()
            encoded = base64.b64encode(b"\xff\xd8\xffpreview").decode("ascii")
            assert inputs == [{"content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}]}]

    asyncio.run(scenario())


def test_no_endpoint_means_unavailable(tmp_path: Path) -> None:
    async def scenario() -> None:
        provider = LlamaCppEmbeddingProvider(spec=EG2, space=EG2.space(), endpoint=lambda: None)

        assert await provider.is_enabled() is False
        with pytest.raises(EmbeddingModelUnavailableError):
            await provider.embed_query("hola")

    asyncio.run(scenario())


def test_endpoint_of_another_model_is_not_used(tmp_path: Path) -> None:
    async def scenario() -> None:
        info = endpoint("http://127.0.0.1:9", QWEN.space().id, key_file(tmp_path))
        provider = LlamaCppEmbeddingProvider(spec=EG2, space=EG2.space(), endpoint=lambda: info)

        assert await provider.is_enabled() is False

    asyncio.run(scenario())


def test_endpoint_serving_other_dims_of_the_same_model_is_used(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key=KEY, dims=768) as fake:
            info = endpoint(fake.base_url, EG2.space(768).id, key_file(tmp_path))
            provider = LlamaCppEmbeddingProvider(spec=EG2, space=EG2.space(256), endpoint=lambda: info)

            assert await provider.is_enabled() is True
            assert len(await provider.embed_query("hola")) == 256

    asyncio.run(scenario())


def test_connection_failure_asks_the_runtime_to_ensure_and_retries(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key=KEY, dims=768) as dead:
            dead_url = dead.base_url
        key = key_file(tmp_path)
        space = EG2.space()
        current = {"info": endpoint(dead_url, space.id, key)}
        calls: list[str] = []
        with FakeLlamaServer(api_key=KEY, dims=768) as live:

            async def ensure() -> EndpointInfo:
                calls.append("ensure")
                current["info"] = endpoint(live.base_url, space.id, key)
                return current["info"]

            provider = LlamaCppEmbeddingProvider(spec=EG2, space=space, endpoint=lambda: current["info"], ensure=ensure)

            vectors = await provider.embed_documents(["uno", "dos"])

            assert calls == ["ensure"]
            assert len(vectors) == 2
            assert [len(batch) for batch in live.state.embedding_inputs()] == [2]

    asyncio.run(scenario())


def test_empty_documents_send_nothing(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key=KEY, dims=768) as fake:
            provider = provider_for(EG2, fake, tmp_path)
            assert await provider.embed_documents([]) == ()
            assert fake.state.requests == []

    asyncio.run(scenario())


def test_space_must_belong_to_the_spec() -> None:
    with pytest.raises(ValueError, match="does not belong"):
        LlamaCppEmbeddingProvider(spec=EG2, space=QWEN.space(), endpoint=lambda: None)
    with pytest.raises(ValueError, match="batch_size"):
        LlamaCppEmbeddingProvider(spec=EG2, space=EG2.space(), endpoint=lambda: None, batch_size=9)


def test_model_served_by_the_runtime_wins_over_the_configured_one(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(api_key=KEY, dims=1024) as fake:
            key = key_file(tmp_path)
            served: dict[str, tuple[ModelSpec, EmbeddingSpace] | None] = {"model": None}
            info = endpoint(fake.base_url, QWEN.space(768).id, key)

            async def ensure() -> EndpointInfo:
                served["model"] = (QWEN, QWEN.space(768))  # the status activated Qwen at 768 dims
                return info

            provider = LlamaCppEmbeddingProvider(
                spec=EG2,
                space=EG2.space(),
                endpoint=lambda: info if served["model"] else None,
                ensure=ensure,
                model_source=lambda: served["model"],
            )
            assert provider.space == EG2.space()

            vector = await provider.embed_query("factura")

            assert fake.state.embedding_inputs() == [
                ["Instruct: Given a search query, retrieve relevant files\nQuery:factura"]
            ]
            assert len(vector) == 768
            assert provider.space == QWEN.space(768) and provider.spec == QWEN

    asyncio.run(scenario())
