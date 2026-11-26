from __future__ import annotations

import itertools

import pytest

from bento.domain.indexing import IndexProviderState
from bento.domain.smart_search import (
    BACKLOG_REINDEX_THRESHOLD,
    IllegalSmartSearchTransitionError,
    SmartSearchError,
    SmartSearchErrorCode as Code,
    SmartSearchEvent as Event,
    SmartSearchEventKind as Kind,
    SmartSearchState as State,
    SmartSearchStatus as Status,
    transition,
    with_download_progress,
    with_index_progress,
)

SPACE = "embeddinggemma-2-q8_0@6ea3e3a309d12a4779cfda98b8c19800d2d5da71/512"


def status_in(state: State, *, code: Code | None = None, failed: State | None = None) -> Status:
    if state is State.ERROR:
        return Status(state=state, error_code=code or Code.DOWNLOAD, failed_step=failed or State.DOWNLOADING)
    return Status(state=state, space_id=None if state is State.OFF else SPACE, bytes_total=100)


# The contract table: (state, event kind, error code or None) -> target state.
LEGAL: dict[tuple[State, Kind, Code | None], State] = {
    (State.OFF, Kind.ACTIVATE, None): State.DOWNLOADING,
    (State.DOWNLOADING, Kind.PAUSE, None): State.PAUSED,
    (State.PAUSED, Kind.RESUME, None): State.DOWNLOADING,
    (State.DOWNLOADING, Kind.NETWORK_LOST, None): State.DOWNLOADING,
    (State.DOWNLOADING, Kind.NETWORK_RESTORED, None): State.DOWNLOADING,
    (State.DOWNLOADING, Kind.DOWNLOADED, None): State.VERIFYING,
    (State.VERIFYING, Kind.VERIFIED, None): State.STARTING,
    (State.STARTING, Kind.RUNTIME_READY, None): State.INDEXING,
    (State.INDEXING, Kind.INDEXED, None): State.READY,
    (State.READY, Kind.BACKLOG, None): State.INDEXING,  # with backlog > threshold
    (State.DOWNLOADING, Kind.FAIL, Code.DOWNLOAD): State.ERROR,
    (State.DOWNLOADING, Kind.FAIL, Code.SPACE): State.ERROR,
    (State.VERIFYING, Kind.FAIL, Code.CHECKSUM): State.ERROR,
    (State.STARTING, Kind.FAIL, Code.RUNTIME): State.ERROR,
    (State.INDEXING, Kind.FAIL, Code.RUNTIME): State.ERROR,
    (State.READY, Kind.FAIL, Code.RUNTIME): State.ERROR,
    (State.ERROR, Kind.RETRY, None): State.DOWNLOADING,  # failed step of the fixture
    **{(s, Kind.CANCEL, None): State.OFF for s in (State.DOWNLOADING, State.PAUSED, State.VERIFYING, State.STARTING, State.ERROR)},
    **{(s, Kind.REMOVE, None): State.OFF for s in State if s is not State.OFF},
}


def _event(kind: Kind, code: Code | None) -> Event:
    return Event(kind=kind, error_code=code, backlog=BACKLOG_REINDEX_THRESHOLD + 1, bytes_total=100, space_id=SPACE)


@pytest.mark.parametrize(
    ("state", "kind", "code"),
    [
        (state, kind, code)
        for state, kind in itertools.product(State, Kind)
        for code in ([None, *Code] if kind is Kind.FAIL else [None])
    ],
    ids=lambda v: getattr(v, "value", str(v)),
)
def test_every_transition_is_either_in_the_table_or_raises(state: State, kind: Kind, code: Code | None) -> None:
    current = status_in(state)
    key = (state, kind, code)
    if key in LEGAL:
        assert transition(current, _event(kind, code)).state is LEGAL[key]
    else:
        with pytest.raises(IllegalSmartSearchTransitionError) as info:
            transition(current, _event(kind, code))
        assert info.value.code == "illegal_smart_search_transition"


def test_happy_path_with_pause_and_network_drop() -> None:
    s = transition(Status(), Event(Kind.ACTIVATE, bytes_total=1000, space_id=SPACE))
    s = with_download_progress(s, 400)
    s = transition(s, Event(Kind.NETWORK_LOST))
    assert s.waiting_network and s.state is State.DOWNLOADING
    s = transition(s, Event(Kind.PAUSE))
    assert s.state is State.PAUSED and not s.waiting_network and s.bytes_done == 400
    s = transition(s, Event(Kind.RESUME))
    s = transition(s, Event(Kind.DOWNLOADED))
    assert s.bytes_done == 1000
    s = transition(s, Event(Kind.VERIFIED))
    s = transition(s, Event(Kind.RUNTIME_READY))
    s = with_index_progress(s, 5, 20)
    assert (s.indexed_done, s.indexed_total) == (5, 20)
    s = transition(s, Event(Kind.INDEXED))
    assert s.state is State.READY and s.indexed_done == 20 and s.space_id == SPACE
    assert s.search_available and s.legacy_embeddings_state() is IndexProviderState.READY


def test_download_error_retry_resumes_from_partial_file() -> None:
    s = with_download_progress(transition(Status(), Event(Kind.ACTIVATE, bytes_total=1000)), 600)
    s = transition(s, Event(Kind.FAIL, error_code=Code.DOWNLOAD))
    assert s.failed_step is State.DOWNLOADING and s.legacy_embeddings_state() is IndexProviderState.FAILED
    s = transition(s, Event(Kind.RETRY))
    assert s.state is State.DOWNLOADING and s.bytes_done == 600 and s.error_code is None


def test_checksum_error_retry_restarts_from_zero() -> None:
    s = transition(transition(Status(), Event(Kind.ACTIVATE, bytes_total=1000)), Event(Kind.DOWNLOADED))
    s = transition(s, Event(Kind.FAIL, error_code=Code.CHECKSUM))
    s = transition(s, Event(Kind.RETRY))
    assert s.state is State.DOWNLOADING and s.bytes_done == 0


@pytest.mark.parametrize("failed", [State.STARTING, State.INDEXING])
def test_runtime_error_retry_returns_to_failed_step(failed: State) -> None:
    s = transition(Status(state=failed, space_id=SPACE), Event(Kind.FAIL, error_code=Code.RUNTIME))
    assert transition(s, Event(Kind.RETRY)).state is failed


def test_ready_losing_runtime_restarts_and_returns_to_ready() -> None:
    s = transition(Status(state=State.READY, space_id=SPACE), Event(Kind.FAIL, error_code=Code.RUNTIME))
    s = transition(s, Event(Kind.RETRY))
    assert s.state is State.STARTING
    assert transition(s, Event(Kind.RUNTIME_READY)).state is State.READY


def test_small_backlog_does_not_flicker_ready() -> None:
    ready = Status(state=State.READY, space_id=SPACE)
    assert transition(ready, Event(Kind.BACKLOG, backlog=1)) == ready
    assert transition(ready, Event(Kind.BACKLOG, backlog=BACKLOG_REINDEX_THRESHOLD)) == ready
    grown = transition(ready, Event(Kind.BACKLOG, backlog=BACKLOG_REINDEX_THRESHOLD + 1))
    assert grown.state is State.INDEXING and grown.indexed_total == BACKLOG_REINDEX_THRESHOLD + 1
    assert grown.search_available


def test_cancel_and_remove_leave_a_clean_off_status() -> None:
    s = with_download_progress(transition(Status(), Event(Kind.ACTIVATE, bytes_total=10)), 5)
    assert transition(s, Event(Kind.CANCEL)) == Status()
    assert transition(Status(state=State.READY, space_id=SPACE), Event(Kind.REMOVE)) == Status()


def test_status_invariants() -> None:
    with pytest.raises(SmartSearchError):
        Status(state=State.ERROR)
    with pytest.raises(SmartSearchError):
        Status(state=State.READY, error_code=Code.RUNTIME)
    with pytest.raises(SmartSearchError):
        Status(state=State.PAUSED, waiting_network=True)
    with pytest.raises(SmartSearchError):
        with_download_progress(Status(state=State.READY), 1)
    with pytest.raises(SmartSearchError):
        with_index_progress(Status(state=State.READY), 1, 2)
    assert Status().legacy_embeddings_state() is IndexProviderState.DISABLED
    assert Status(state=State.VERIFYING).legacy_embeddings_state() is IndexProviderState.PENDING


def test_download_progress_is_clamped() -> None:
    s = transition(Status(), Event(Kind.ACTIVATE, bytes_total=10))
    assert with_download_progress(s, 99).bytes_done == 10
    assert with_download_progress(s, -3).bytes_done == 0
