"""Sync, activity, jobs, reindex."""

from __future__ import annotations

import time
from typing import Any

from bento.interfaces.cli.catalog import Command, arg
from bento.interfaces.cli.commands.common import date_text, iterate
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.output import Output, human_size

JOB_STATES = ("queued", "running", "succeeded", "failed", "retrying")
WATCH_INTERVAL = 2.0


def render_sync(out: Output, data: dict[str, Any]) -> None:
    pairs: list[tuple[str, Any]] = [
        (out.t("sync.state"), out.t(f"sync.state.{data.get('state')}")),
        (out.t("sync.pending"), data.get("pending_ops")),
        (out.t("sync.last_push"), date_text(data.get("last_push_at"))),
        (out.t("sync.last_pull"), date_text(data.get("last_pull_at"))),
    ]
    bootstrap = data.get("bootstrap")
    if bootstrap:
        pairs.append((out.t("sync.bootstrap"), f"{bootstrap.get('done')}/{bootstrap.get('total')}"))
    if data.get("waiting_until"):
        pairs.append((out.t("sync.waiting_until"), date_text(data["waiting_until"])))
    error = data.get("error")
    if error:
        pairs.append((out.t("sync.error"), out.t.error_message(error.get("code", ""), error.get("message", ""), error.get("details") or {})))
    out.fields(pairs)


def sync_status(ctx: Context) -> int:
    ctx.out.result(ctx.api.get("/sync/status"), render_sync)
    return 0


def sync_now(ctx: Context) -> int:
    data = ctx.api.post("/sync/now")
    ctx.out.result(data, lambda out, doc: out.line(out.t("sync.requested" if doc.get("accepted") else "sync.local_only")))
    return 0


def render_activity(out: Output, data: dict[str, Any]) -> None:
    uploads = data.get("uploads") or {}
    downloads = data.get("downloads") or {}
    out.line(out.t(f"activity.summary.{data.get('summary')}"))
    for label, stats in ((out.t("activity.uploads"), uploads), (out.t("activity.downloads"), downloads)):
        if stats.get("active") or stats.get("queued"):
            eta = stats.get("eta_seconds")
            eta_text = f", ~{max(1, round(eta / 60))} min" if isinstance(eta, int) and eta > 0 else ""
            out.line(
                f"  {label}: {stats.get('active', 0)} + {stats.get('queued', 0)} "
                f"({human_size(stats.get('bytes_done'), out.lang)}/{human_size(stats.get('bytes_total'), out.lang)}{eta_text})"
            )
    for item in data.get("attention") or []:
        out.line("  ! " + out.t.attention(item))


def activity(ctx: Context) -> int:
    if not ctx.args.watch:
        ctx.out.result(ctx.api.get("/activity"), render_activity)
        return 0
    # NDJSON snapshots in JSON mode; a refreshed summary for humans. Ctrl+C stops (exit 130).
    previous: Any = None
    while True:
        snapshot = ctx.api.get("/activity")
        if snapshot != previous:
            if ctx.out.json_mode:
                ctx.out.json(snapshot, compact=True)
            else:
                ctx.out.line(f"[{time.strftime('%H:%M:%S')}]")
                render_activity(ctx.out, snapshot)
            previous = snapshot
        time.sleep(WATCH_INTERVAL)


def jobs_ls(ctx: Context) -> int:
    state = ctx.args.state
    items = []
    for job in iterate(ctx, "/jobs", {"limit": 200}):
        if state is None or job.get("status") == state:
            items.append(job)
        if len(items) >= ctx.args.limit:
            break
    ctx.out.result(
        {"items": items},
        lambda out, doc: out.table(
            [out.t(f"col.{name}") for name in ("id", "type", "state", "attempts", "modified", "error")],
            [[job["id"], job["type"], job["status"], f"{job['attempts']}/{job['max_attempts']}", date_text(job.get("updated_at")), (job.get("error") or "")[:60]] for job in doc["items"]],
            empty=out.t("jobs.empty"),
        ),
    )
    return 0


def jobs_retry(ctx: Context) -> int:
    job = ctx.api.post(f"/jobs/{ctx.args.id}/retry")
    ctx.out.result(job, lambda out, doc: out.line(out.t("jobs.retried", id=doc["id"])))
    return 0


def reindex(ctx: Context) -> int:
    data = ctx.api.post("/admin/reindex")
    ctx.out.result(data, lambda out, doc: out.line(out.t("reindex.queued", count=doc.get("enqueued", 0))))
    return 0


COMMANDS = (
    Command(("sync",), "Sync between your devices", "Sincronización entre tus dispositivos", default_child="status"),
    Command(("sync", "status"), "Sync state", "Estado de la sincronización", sync_status, output="SyncStatus"),
    Command(("sync", "now"), "Sync now", "Sincroniza ahora", sync_now, output="SyncNow"),
    Command(
        ("activity",),
        "Uploads, downloads and items needing attention",
        "Subidas, descargas y avisos",
        activity,
        (arg("--watch", en="Keep watching (NDJSON with --json)", es="Sigue mirando (NDJSON con --json)", action="store_true"),),
        output="Activity",
    ),
    Command(("jobs",), "Background jobs", "Tareas en segundo plano", default_child="ls"),
    Command(
        ("jobs", "ls"),
        "List background jobs",
        "Lista las tareas en segundo plano",
        jobs_ls,
        (
            arg("--state", en="Only jobs in this state", es="Solo tareas en este estado", choices=JOB_STATES, metavar="S"),
            arg("--limit", en="Maximum jobs", es="Máximo de tareas", type=int, default=50),
        ),
        output="JobList",
    ),
    Command(("jobs", "retry"), "Retry a failed job", "Reintenta una tarea fallida", jobs_retry, (arg("id", en="Job id", es="Id de la tarea", metavar="ID"),), output="Job"),
    Command(("reindex",), "Rebuild search indexes in the background", "Reconstruye los índices de búsqueda", reindex, output="Reindex"),
)
