"""Calling Kotlin bridges: typed errors from `BridgeException(code, message)` and JSON results."""

from __future__ import annotations

import json
from typing import Any


class BridgeError(RuntimeError):
    """A bridge call failed. `code` is the Kotlin `BridgeException.code` (or `io` for anything unexpected)."""

    code = "io"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.code)
        if code is not None:
            self.code = code


class BridgeUnsupportedError(BridgeError):
    code = "unsupported"


class BridgeNotFoundError(BridgeError):
    code = "not_found"


class BridgePermissionDeniedError(BridgeError):
    code = "permission_denied"


class BridgeCancelledError(BridgeError):
    code = "cancelled"


class BridgeIOError(BridgeError):
    code = "io"


_ERRORS: dict[str, type[BridgeError]] = {
    cls.code: cls
    for cls in (BridgeUnsupportedError, BridgeNotFoundError, BridgePermissionDeniedError, BridgeCancelledError, BridgeIOError)
}


def bridge_error(exc: BaseException) -> BridgeError:
    """Map an exception raised by a bridge call to a typed `BridgeError`.

    Chaquopy raises Java exceptions as Python exceptions whose Kotlin properties are reachable as getters
    (`getCode()`); Python fakes raise exceptions with a `code` attribute. Messages are reduced to the code so
    nothing host-specific (paths, URIs) reaches logs or job errors.
    """
    if isinstance(exc, BridgeError):
        return exc
    code = _attribute(exc, "code", "getCode")
    if not isinstance(code, str) or code not in _ERRORS:
        return BridgeIOError("bridge call failed")
    return _ERRORS[code](f"bridge call failed: {code}")


def call(bridge: Any, method: str, *args: Any) -> Any:
    """`bridge.method(*args)` with errors mapped to `BridgeError`. `str` results are plain Python strings."""
    try:
        result = getattr(bridge, method)(*args)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise bridge_error(exc) from None
    return str(result) if _is_java_string(result) else result


def call_json(bridge: Any, method: str, *args: Any) -> Any:
    raw = call(bridge, method, *args)
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        raise BridgeIOError(f"{method} returned malformed JSON") from None


def _attribute(exc: BaseException, name: str, getter: str) -> object:
    value = getattr(exc, name, None)
    if value is None:
        method = getattr(exc, getter, None)
        if callable(method):
            try:
                value = method()
            except Exception:  # noqa: BLE001
                return None
    return str(value) if value is not None and not isinstance(value, str) and _is_java_string(value) else value


def _is_java_string(value: object) -> bool:
    return type(value).__name__ == "String" and not isinstance(value, str)
