"""Command groups. Each module exposes `COMMANDS`; `registry()` is the catalog's single source."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bento.interfaces.cli.catalog import Command


@lru_cache(maxsize=1)
def registry() -> tuple[Command, ...]:
    from bento.interfaces.cli.commands import (
        account,
        agent,
        backup,
        devices,
        drive,
        pairing,
        photos,
        runtime,
        search,
        settings,
        setup,
        sync,
        telegram,
        transfer_cmds,
        trash,
        vault,
    )

    groups = (
        setup,
        account,
        vault,
        pairing,
        devices,
        drive,
        transfer_cmds,
        search,
        photos,
        trash,
        backup,
        sync,
        telegram,
        settings,
        runtime,
        agent,
    )
    commands = tuple(command for module in groups for command in module.COMMANDS)
    paths = [command.path for command in commands]
    duplicates = {path for path in paths if paths.count(path) > 1}
    if duplicates:
        raise AssertionError(f"duplicate commands: {sorted(duplicates)}")
    return commands
