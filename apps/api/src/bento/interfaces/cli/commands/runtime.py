"""Runtime: daemon control, services, doctor, version, completion."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from bento.interfaces.cli import cli_version
from bento.interfaces.cli.catalog import Command, arg
from bento.interfaces.cli.completion import SHELLS, completion_script
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.daemon import daemon_status, run_daemon, service_file, start_daemon, stop_daemon
from bento.interfaces.cli.errors import CliError
from bento.interfaces.cli.output import Output, human_size
from bento.interfaces.cli.profiles import write_private_json

LOG_NAMES = ("daemon", "api", "worker")


def _render_daemon(out: Output, data: dict[str, Any]) -> None:
    if data.get("running"):
        out.line(out.t("daemon.running", profile=data["profile"], url=data.get("url") or "?", pid=data.get("pid")))
        if not data.get("healthy"):
            out.line(out.t("daemon.unhealthy"))
    else:
        out.line(out.t("daemon.stopped", profile=data["profile"]))


def d_run(ctx: Context) -> int:
    return run_daemon(ctx.profile, ctx.environ, ready_timeout=max(ctx.timeout, 60.0))


def d_start(ctx: Context) -> int:
    start_daemon(ctx.profile, max(ctx.timeout, 60.0), environ=ctx.environ)
    ctx.out.result(daemon_status(ctx.profile), _render_daemon)
    return 0


def d_stop(ctx: Context) -> int:
    stopped = stop_daemon(ctx.profile, timeout=max(ctx.timeout, 20.0))
    data = {**daemon_status(ctx.profile), "stopped": stopped}
    ctx.out.result(data, lambda out, doc: out.line(out.t("daemon.stop_done" if doc["stopped"] else "daemon.not_running", profile=doc["profile"])))
    return 0


def d_restart(ctx: Context) -> int:
    stop_daemon(ctx.profile, timeout=max(ctx.timeout, 20.0))
    return d_start(ctx)


def d_status(ctx: Context) -> int:
    data = daemon_status(ctx.profile)
    ctx.out.result(data, _render_daemon)
    return 0


def _tail(path: Path, lines: int) -> list[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 256 * 1024))
            data = handle.read().decode("utf-8", "replace")
    except OSError:
        return []
    return data.splitlines()[-lines:]


def d_logs(ctx: Context) -> int:
    names = LOG_NAMES if ctx.args.name == "all" else (ctx.args.name,)
    files = {name: ctx.profile.log_file(name) for name in names}
    if ctx.out.json_mode and not ctx.args.follow:
        ctx.out.result({name: _tail(path, ctx.args.lines) for name, path in files.items()})
        return 0
    for name, path in files.items():
        lines = _tail(path, ctx.args.lines)
        if len(files) > 1 and lines:
            ctx.out.line(f"==> {name}.log <==")
        for line in lines:
            ctx.out.line(line)
    if not ctx.args.follow:
        return 0
    offsets = {name: (path.stat().st_size if path.exists() else 0) for name, path in files.items()}
    while True:
        for name, path in files.items():
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size < offsets[name]:
                offsets[name] = 0
            if size > offsets[name]:
                with path.open("rb") as handle:
                    handle.seek(offsets[name])
                    chunk = handle.read().decode("utf-8", "replace")
                offsets[name] = size
                for line in chunk.splitlines():
                    ctx.out.line(f"[{name}] {line}" if len(files) > 1 else line)
        time.sleep(0.5)


def d_install(ctx: Context) -> int:
    service = service_file(ctx.profile, ctx.environ)
    service.path.parent.mkdir(parents=True, exist_ok=True)
    service.path.write_text(service.content, encoding="utf-8")
    data = {"kind": service.kind, "path": str(service.path), "commands": list(service.commands)}

    def render(out: Output, doc: dict[str, Any]) -> None:
        out.line(out.t("service.written", path=doc["path"]))
        out.line(out.t("service.run_these"))
        for command in doc["commands"]:
            out.line(f"  {command}")

    ctx.out.result(data, render)
    return 0


def d_uninstall(ctx: Context) -> int:
    service = service_file(ctx.profile, ctx.environ)
    existed = service.path.exists()
    if existed:
        service.path.unlink()
    data = {"kind": service.kind, "path": str(service.path), "removed": existed, "commands": list(service.uninstall_commands)}

    def render(out: Output, doc: dict[str, Any]) -> None:
        out.line(out.t("service.removed" if doc["removed"] else "service.absent", path=doc["path"]))
        for command in doc["commands"]:
            out.line(f"  {command}")

    ctx.out.result(data, render)
    return 0


# version / doctor ----------------------------------------------------------------------------


def version(ctx: Context) -> int:
    target = ctx.try_target()
    data: dict[str, Any] = {"cli": cli_version(), "python": sys.version.split()[0], "platform": sys.platform, "api": None, "target": None}
    if target is not None:
        try:
            with ctx.client_for(target) as client:
                data["api"] = client.get("/version")
            data["target"] = target.public()
        except CliError:
            pass

    def render(out: Output, doc: dict[str, Any]) -> None:
        out.line(f"bento {doc['cli']}")
        if doc.get("api"):
            out.line(out.t("version.api", version=doc["api"].get("version"), kind=out.t("target." + doc["target"]["kind"])))

    ctx.out.result(data, render)
    return 0


def _check(name: str, status: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "detail": detail, **extra}


def doctor(ctx: Context) -> int:
    checks: list[dict[str, Any]] = [_check("cli", "ok", cli_version())]
    try:
        target = ctx.target
        checks.append(_check("target", "ok", f"{target.kind} {target.url}"))
    except CliError as error:
        checks.append(_check("target", "error", error.code))
        target = None
    if target is not None:
        api = ctx.api
        for name, path in (("version", "/version"), ("health", "/health")):
            try:
                data = api.get(path)
                detail = data.get("version") if name == "version" else data.get("storage_backend")
                checks.append(_check(name, "ok", str(detail)))
            except CliError as error:
                checks.append(_check(name, "error", error.code))
        try:
            account = api.get("/account")
            checks.append(_check("telegram", "ok" if account.get("step") == "authorized" else "warning", str(account.get("step"))))
        except CliError as error:
            checks.append(_check("telegram", "warning" if error.code in {"telegram_not_configured"} else "error", error.code))
        try:
            vault = api.get("/vault")
            state = str(vault.get("state"))
            checks.append(_check("vault", "ok" if state in {"ready", "local_only"} else "warning", state))
        except CliError as error:
            checks.append(_check("vault", "error", error.code))
        try:
            sync = api.get("/sync/status")
            error_info = sync.get("error") or {}
            checks.append(_check("sync", "warning" if error_info else "ok", str(error_info.get("code") or sync.get("state"))))
        except CliError as error:
            checks.append(_check("sync", "error", error.code))
        try:
            values = (api.get("/settings/values").get("values") or {})
            relay = (values.get("relay_url") or {}).get("value")
            checks.append(_check("relay", "ok" if relay else "warning", "configured" if relay else "not_configured"))
        except CliError:
            pass
    if target is None or target.kind == "daemon":
        data_dir = ctx.profile.data_dir
        if data_dir.exists():
            usage = shutil.disk_usage(data_dir)
            free_status = "ok" if usage.free > 2 * 1024**3 else "warning"
            checks.append(_check("disk", free_status, human_size(usage.free, ctx.out.lang) + " free", free_bytes=usage.free))
            key_file = data_dir / "secure" / "wrapping.key"
            if key_file.exists():
                checks.append(_check("device_key", "warning", "file_based_wrapping_key"))
        checks.append(_check("profile", "ok", ctx.profile.name, data_dir=str(data_dir)))
    worst = "error" if any(item["status"] == "error" for item in checks) else ("warning" if any(item["status"] == "warning" for item in checks) else "ok")
    document = {"status": worst, "checks": checks}

    def render(out: Output, doc: dict[str, Any]) -> None:
        marks = {"ok": "✓", "warning": "!", "error": "✗"}
        for item in doc["checks"]:
            out.line(f"{marks[item['status']]} {out.t('doctor.' + item['name'])}: {out.t('doctor.detail.' + item['detail']) if item['detail'] in DOCTOR_DETAILS else item['detail']}")

    ctx.out.result(document, render)
    return 1 if worst == "error" else 0


DOCTOR_DETAILS = frozenset({"file_based_wrapping_key", "not_configured", "configured"})


# completion / config -------------------------------------------------------------------------


def completion(ctx: Context) -> int:
    script = completion_script(ctx.args.shell)
    if ctx.out.json_mode:
        ctx.out.result({"shell": ctx.args.shell, "script": script})
    else:
        ctx.out.stdout.write(script)
    return 0


def config_lang(ctx: Context) -> int:
    ctx.profile.ensure()
    data = ctx.profile.config()
    data["lang"] = ctx.args.value
    write_private_json(ctx.profile.config_file, data)
    ctx.out.result(data, lambda out, doc: out.line(out.t("config.saved")))
    return 0


COMMANDS = (
    Command(("daemon",), "Background Bento for this profile (headless machines)", "Bento en segundo plano para este perfil (servidores)", default_child="status"),
    Command(("daemon", "status"), "Is the daemon running?", "¿Está el daemon en marcha?", d_status, output="DaemonStatus"),
    Command(("daemon", "start"), "Start the daemon in the background", "Inicia el daemon en segundo plano", d_start, output="DaemonStatus"),
    Command(("daemon", "stop"), "Stop the daemon", "Detiene el daemon", d_stop, output="DaemonStatus"),
    Command(("daemon", "restart"), "Restart the daemon", "Reinicia el daemon", d_restart, output="DaemonStatus"),
    Command(("daemon", "run"), "Run the supervisor in the foreground (services)", "Ejecuta el supervisor en primer plano (servicios)", d_run, output="none"),
    Command(
        ("daemon", "logs"),
        "Show daemon/API/worker logs",
        "Muestra los registros del daemon/API/worker",
        d_logs,
        (
            arg("-f", "--follow", en="Keep following", es="Sigue mostrando", action="store_true"),
            arg("-n", "--lines", en="Lines per file", es="Líneas por archivo", type=int, default=50),
            arg("--name", en="Which log", es="Qué registro", choices=("all", *LOG_NAMES), default="all"),
        ),
        output="DaemonLogs",
    ),
    Command(("daemon", "install-service"), "Start Bento at login (systemd user unit / launchd agent)", "Inicia Bento al entrar (systemd de usuario / launchd)", d_install, output="ServiceFile"),
    Command(("daemon", "uninstall-service"), "Remove the login service", "Quita el servicio de inicio", d_uninstall, output="ServiceFile"),
    Command(("doctor",), "Check connectivity, versions, Telegram, relay and disk", "Revisa conexión, versiones, Telegram, relay y disco", doctor, output="DoctorReport"),
    Command(("version",), "CLI and API versions", "Versiones de la CLI y la API", version, output="Version"),
    Command(
        ("completion",),
        "Print a shell completion script",
        "Imprime el script de autocompletado",
        completion,
        (arg("shell", en="Shell", es="Shell", choices=SHELLS),),
        output="text",
    ),
    Command(("config",), "CLI preferences for this profile", "Preferencias de la CLI para este perfil"),
    Command(
        ("config", "lang"),
        "Default language for this profile",
        "Idioma por defecto para este perfil",
        config_lang,
        (arg("value", en="Language", es="Idioma", choices=("es", "en")),),
        output="CliConfig",
    ),
)
