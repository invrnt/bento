"""Worker handler for `model_download` jobs (smart search model files).

The handler is thin: `SmartSearchActivationService.run_download_job` owns the flow. A network outage that
outlasts the in-job waits raises `ModelDownloadRetryLater`, so the queue retries the job with backoff and the
status keeps `waiting_network`; on the job's last attempt the status becomes `error(download)` instead.
`WorkBudgetExceeded` (bounded runs) propagates, so the dispatcher requeues the job without spending an attempt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from bento.application.smart_search.activation import (
    DownloadJobResult,
    SmartSearchActivationService,
    SmartSearchHooksPort,
)
from bento.domain.jobs import Job, JobType
from bento.domain.smart_search import ModelSpec
from bento.ports.jobs import JobQueuePort
from bento.ports.repositories import ClockPort

LOGGER = logging.getLogger("bento.worker.models")

MODEL_JOB_TYPES = frozenset({JobType.MODEL_DOWNLOAD})


@dataclass(frozen=True, slots=True)
class ModelDownloadJobHandler:
    activation: SmartSearchActivationService

    def handles(self, job_type: JobType) -> bool:
        return job_type in MODEL_JOB_TYPES

    async def handle(self, job: Job) -> DownloadJobResult:
        if job.type is not JobType.MODEL_DOWNLOAD:
            raise RuntimeError(f"No model handler for {job.type.value}")
        final_attempt = job.attempts + 1 >= job.max_attempts
        result = await self.activation.run_download_job(job.payload, final_attempt=final_attempt)
        LOGGER.info("Model download job %s finished: %s", job.id, result.value)
        return result


class _WorkerProviderSwitch:
    """The worker never changes `embeddings_provider`; only the API's activation flow does."""

    async def locked(self) -> bool:
        return False

    async def enable(self) -> None:
        return None

    async def disable(self) -> None:
        return None


def build_model_download_handler(
    *,
    data_dir: Path,
    session_factory: sessionmaker[Session],
    clock: ClockPort,
    jobs: JobQueuePort,
    app_version: str,
    hooks: SmartSearchHooksPort | None = None,
) -> ModelDownloadJobHandler:
    """Composition for `interfaces/worker/main.py` (one line: `model_download=build_model_download_handler(...)`).

    `hooks.starting` is where the runtime owner starts llama-server for the verified space."""
    from bento.adapters.models.http_downloader import HttpModelDownloader
    from bento.adapters.models.sqlite_status import SQLiteSmartSearchStatusRepository
    from bento.application.smart_search.activation import NoopSmartSearchHooks
    from bento.infrastructure.models import (
        download_user_agent,
        license_text,
        model_notice_text,
        model_store,
        packaged_model_catalog,
    )

    store = model_store(data_dir)

    def write_license(spec: ModelSpec) -> None:
        store.write_license(spec, license_text(spec.license_spdx), model_notice_text(spec.model_id))

    activation = SmartSearchActivationService(
        catalog=packaged_model_catalog(),
        store=store,
        repository=SQLiteSmartSearchStatusRepository(session_factory, clock),
        jobs=jobs,
        provider_switch=_WorkerProviderSwitch(),
        hooks=hooks or NoopSmartSearchHooks(),
        downloader=HttpModelDownloader(user_agent=download_user_agent(app_version)),
        write_license=write_license,
    )
    return ModelDownloadJobHandler(activation)
