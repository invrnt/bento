"""Settings: list, get, set (validated by the server first), schema."""

from __future__ import annotations

from typing import Any

from bento.interfaces.cli.catalog import Command, arg
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.errors import CliError, usage
from bento.interfaces.cli.output import Output

_TRUE = {"1", "true", "yes", "on", "si", "sí"}
_FALSE = {"0", "false", "no", "off"}


def _display(entry: dict[str, Any]) -> str:
    if "configured" in entry:
        return "•••" if entry.get("configured") else "-"
    value = entry.get("value")
    return "-" if value is None or value == "" else str(value)


def ls(ctx: Context) -> int:
    data = ctx.api.get("/settings/values")

    def render(out: Output, doc: dict[str, Any]) -> None:
        rows = [
            [key, _display(entry), entry.get("source", ""), out.t("yes") if entry.get("locked") else ""]
            for key, entry in sorted((doc.get("values") or {}).items())
        ]
        out.table([out.t("col.key"), out.t("col.value"), out.t("col.source"), out.t("col.locked")], rows)

    ctx.out.result(data, render)
    return 0


def get(ctx: Context) -> int:
    data = ctx.api.get("/settings/values")
    entry = (data.get("values") or {}).get(ctx.args.key)
    if entry is None:
        raise CliError("setting_not_found", "Unknown setting", {"key": ctx.args.key})
    document = {"key": ctx.args.key, **entry, "revision": data.get("revision")}
    ctx.out.result(document, lambda out, doc: out.line(_display(doc)))
    return 0


def coerce(raw: str, field: dict[str, Any]) -> Any:
    kind = field.get("type")
    text = raw.strip()
    if kind == "boolean":
        if text.lower() in _TRUE:
            return True
        if text.lower() in _FALSE:
            return False
        raise usage("Expected true/false", key=field.get("key"), value=raw)
    if kind == "integer":
        try:
            return int(text)
        except ValueError as exc:
            raise usage("Expected an integer", key=field.get("key"), value=raw) from exc
    if kind == "number":
        try:
            return float(text)
        except ValueError as exc:
            raise usage("Expected a number", key=field.get("key"), value=raw) from exc
    return raw


def parse_assignments(values: list[str], schema: dict[str, Any]) -> dict[str, Any]:
    fields = {field["key"]: field for field in schema.get("fields") or []}
    parsed: dict[str, Any] = {}
    for item in values:
        key, separator, raw = item.partition("=")
        key = key.strip()
        if not separator or not key:
            raise usage("Use KEY=VALUE", value=item)
        field = fields.get(key)
        if field is None:
            raise CliError("setting_not_found", "Unknown setting", {"key": key})
        if field.get("secret"):
            raise usage("Secrets cannot be set from the CLI", key=key)
        parsed[key] = coerce(raw, field)
    return parsed


def set_values(ctx: Context) -> int:
    schema = ctx.api.get("/settings/schema")
    values = parse_assignments(ctx.args.assignments, schema)
    validation = ctx.api.post("/settings/validate", {"values": values})
    if not validation.get("valid", False):
        raise CliError("validation_failed", "The settings are not valid", {"errors": validation.get("errors") or []}, 2)
    current = ctx.api.get("/settings/values")
    data = ctx.api.patch("/settings/values", {"values": values, "revision": current.get("revision", 0)})
    document = {**data, "changed": sorted(values), "warnings": validation.get("warnings") or []}

    def render(out: Output, doc: dict[str, Any]) -> None:
        out.line(out.t("settings.saved", keys=", ".join(doc["changed"])))
        plan = doc.get("restart_plan") or {}
        if plan.get("services"):
            out.line(out.t("settings.restart", services=", ".join(plan["services"])))
        for warning in doc["warnings"]:
            out.line(f"! {warning.get('key')}: {warning.get('message')}")

    ctx.out.result(document, render)
    return 0


def schema(ctx: Context) -> int:
    data = ctx.api.get("/settings/schema")
    ctx.out.result(
        data,
        lambda out, doc: out.table(
            [out.t("col.key"), out.t("col.type"), out.t("col.default"), out.t("col.choices")],
            [
                [field["key"], field["type"], "" if field.get("default") is None else field["default"], ",".join(map(str, (field.get("constraints") or {}).get("choices") or []))]
                for field in doc.get("fields") or []
                if field.get("editable", True)
            ],
        ),
    )
    return 0


COMMANDS = (
    Command(("settings",), "Bento settings", "Configuración de Bento", default_child="ls"),
    Command(("settings", "ls"), "Show effective settings", "Muestra la configuración efectiva", ls, output="SettingsValues"),
    Command(("settings", "get"), "Show one setting", "Muestra un ajuste", get, (arg("key", en="Setting key", es="Clave", metavar="KEY"),), output="SettingValue"),
    Command(
        ("settings", "set"),
        "Change settings (validated first)",
        "Cambia ajustes (se validan antes)",
        set_values,
        (arg("assignments", en="KEY=VALUE pairs", es="Pares CLAVE=VALOR", nargs="+", metavar="KEY=VALUE"),),
        output="SettingsValues",
    ),
    Command(("settings", "schema"), "Editable settings and their types", "Ajustes editables y sus tipos", schema, output="SettingsSchema"),
)
