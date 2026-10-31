from __future__ import annotations

import pytest

from bento.domain.pairing import PairingCode, PairingCodeInvalidError, PairingState, can_transition


def test_pairing_code_formats_links() -> None:
    code = PairingCode(nameplate="K7Q2", secret="MXR9T4WA")

    assert code.format() == "K7Q2-MXR9-T4WA"
    assert code.link() == "bento://join?v=1&c=K7Q2-MXR9-T4WA"
    assert code.web_link("https://bento.example/") == "https://bento.example/join#v=1&c=K7Q2-MXR9-T4WA"
    assert code.password == b"MXR9T4WA"


@pytest.mark.parametrize(
    "value",
    [
        "K7Q2-MXR9-T4WA",
        "  k7q2 mxr9 t4wa ",
        "K7Q2MXR9T4WA",
        "bento://join?v=1&c=K7Q2-MXR9-T4WA",
        "https://bento.example/join#v=1&c=K7Q2-MXR9-T4WA",
        "https://bento.example/join?v=1&c=k7q2-mxr9-t4wa",
    ],
)
def test_pairing_code_parse_accepts_codes_and_links(value: str) -> None:
    assert PairingCode.parse(value) == PairingCode(nameplate="K7Q2", secret="MXR9T4WA")


def test_pairing_code_parse_maps_crockford_aliases() -> None:
    assert PairingCode.parse("O1IL-oiLl-0000").format() == "0111-0111-0000"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "K7Q2-MXR9",
        "K7Q2-MXR9-T4WA-1234",
        "K7Q2-MXR9-T4WU",
        "bento://join?v=1",
        "https://bento.example/join#v=1&c=",
        "K7Q2-MXR9-T4W!",
    ],
)
def test_pairing_code_parse_rejects_invalid_input(value: str) -> None:
    with pytest.raises(PairingCodeInvalidError) as error:
        PairingCode.parse(value)
    assert error.value.code == "pairing_code_invalid"


def test_pairing_state_transitions() -> None:
    assert can_transition(PairingState.WAITING, PairingState.CONNECTED)
    assert can_transition(PairingState.APPROVING, PairingState.NEEDS_TELEGRAM_LOGIN)
    assert can_transition(PairingState.BOOTSTRAPPING, PairingState.COMPLETED)
    assert not can_transition(PairingState.WAITING, PairingState.APPROVING)
    assert not can_transition(PairingState.COMPLETED, PairingState.WAITING)
    assert not can_transition(PairingState.BOOTSTRAPPING, PairingState.CANCELLED)
    dead_ends = {state for state in PairingState if not any(can_transition(state, target) for target in PairingState)}
    assert dead_ends == {state for state in PairingState if state.terminal}
