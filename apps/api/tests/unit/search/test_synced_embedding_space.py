from __future__ import annotations

from bento.adapters.search.sqlite_vec import is_unknown_peer_space, unknown_peer_space_id, vec_table_name
from bento.adapters.sync.index_data import _parse_embedding, _valid_space
from bento.application.sync.asset_index import embedding_fields, fit_index_fields
from bento.application.sync.codec import decode_vector
from bento.domain.smart_search import PeerVectorDecision, parse_space_id, peer_vector_decision, space_id_for

SPACE = space_id_for("embeddinggemma-2-q8_0", "6ea3e3a309d12a4779cfda98b8c19800d2d5da71", 4)


def test_the_synced_embedding_carries_its_space() -> None:
    fields = embedding_fields(provider="managed", dimensions=4, vector=(1.0, 0.0, 0.0, 0.0), space=SPACE)

    embedding = fields["embedding"]
    assert embedding["space"] == SPACE
    assert embedding["provider"] == "managed"
    assert embedding["dimensions"] == 4
    assert decode_vector(embedding["vector_b64_f32"], 4) == (1.0, 0.0, 0.0, 0.0)
    assert "chunks" not in embedding


def test_callers_without_a_space_send_their_legacy_space() -> None:
    fields = embedding_fields(provider="mock", dimensions=2, vector=(0.0, 1.0))

    assert fields["embedding"]["space"] == "legacy:mock/2"


def test_every_chunk_travels_with_its_page_and_chunk_zero_stays_readable_by_old_peers() -> None:
    chunks = [(1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0)]

    embedding = embedding_fields(
        provider="managed", dimensions=4, vector=chunks[0], space=SPACE, chunks=chunks, pages=[1, 1, 2]
    )["embedding"]

    assert decode_vector(embedding["vector_b64_f32"], 4) == chunks[0]
    assert [(item["chunk_no"], item["page"]) for item in embedding["chunks"]] == [(0, 1), (1, 1), (2, 2)]
    assert [decode_vector(item["vector_b64_f32"], 4) for item in embedding["chunks"]] == chunks
    parsed = _parse_embedding(embedding)
    assert parsed.space_id == SPACE
    assert parsed.vectors == tuple(chunks)
    assert parsed.pages == (1, 1, 2)


def test_extra_chunks_are_left_out_before_the_op_outgrows_the_cap() -> None:
    chunks = [tuple(float(i == j) for j in range(4)) for i in range(4)]
    fields = embedding_fields(provider="managed", dimensions=4, vector=chunks[0], space=SPACE, chunks=chunks)

    fitted = fit_index_fields(fields, max_bytes=200)

    assert "chunks" not in fitted["embedding"]
    assert fitted["embedding"]["space"] == SPACE
    assert fitted["embedding"]["vector_b64_f32"] == fields["embedding"]["vector_b64_f32"]


def test_old_peers_without_space_are_an_unknown_space() -> None:
    old = {"provider": "mock", "dimensions": 2, "vector_b64_f32": embedding_fields(provider="mock", dimensions=2, vector=(1.0, 0.0))["embedding"]["vector_b64_f32"]}

    parsed = _parse_embedding(old)

    assert parsed.space_id is None
    assert peer_vector_decision("legacy:mock/2", parsed.space_id, parsed.dimensions) is PeerVectorDecision.STORE_ONLY
    unknown = unknown_peer_space_id("mock", 2)
    assert is_unknown_peer_space(unknown) and unknown != "legacy:mock/2"
    assert parse_space_id(unknown)[2] == 2


def test_malformed_or_mismatched_spaces_are_unknown() -> None:
    assert _valid_space(SPACE, 4) == SPACE
    assert _valid_space(SPACE, 8) is None  # the id says 4 dims
    assert _valid_space("not-a-space", 4) is None
    assert _valid_space(None, 4) is None
    assert _valid_space(unknown_peer_space_id("mock", 4), 4) is None


def test_vec_tables_are_named_per_space() -> None:
    other = space_id_for("embeddinggemma-2-q8_0", "6ea3e3a309d12a4779cfda98b8c19800d2d5da71", 8)

    assert vec_table_name(SPACE).startswith("asset_embedding_vec_")
    assert len(vec_table_name(SPACE)) == len("asset_embedding_vec_") + 8
    assert vec_table_name(SPACE) != vec_table_name(other)
    assert vec_table_name(SPACE) == vec_table_name(SPACE)
