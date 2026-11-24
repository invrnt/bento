from __future__ import annotations

from typing import Any

from bento.adapters.telegram_mtproto.account import sent_code_shape
from bento.domain.vault import VaultCreationProgress, VaultCreationState, VaultCreationStep


def _states(progress: VaultCreationProgress) -> dict[str, str]:
    return {step.value: state.value for step, state in progress.steps}


def test_progress_marks_steps_and_fails_the_running_one() -> None:
    progress = VaultCreationProgress.started()
    assert set(_states(progress).values()) == {"pending"}
    progress = progress.mark(VaultCreationStep.FILES, VaultCreationState.DONE).mark(
        VaultCreationStep.SYNC, VaultCreationState.RUNNING
    )
    failed = progress.failed("telegram_flood_wait")
    assert failed.state == VaultCreationState.FAILED and failed.error_code == "telegram_flood_wait"
    assert _states(failed) == {"files": "done", "sync": "failed", "inbox": "pending", "header": "pending", "device": "pending"}
    assert set(_states(progress.finished()).values()) == {"done"}


def test_sent_code_shape_reads_length_and_delivery_from_telethon_types() -> None:
    from telethon.tl import types

    assert sent_code_shape(types.auth.SentCodeTypeApp(length=5)) == (5, "app")
    assert sent_code_shape(types.auth.SentCodeTypeSms(length=6)) == (6, "sms")
    assert sent_code_shape(types.auth.SentCodeTypeFlashCall(pattern="123*")) == (None, "flash_call")
    assert sent_code_shape(None) == (None, None)

    class Odd:
        length: Any = True

    assert sent_code_shape(Odd()) == (None, None)
