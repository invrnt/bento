import {
  Activity,
  BookOpen,
  CircleAlert,
  CircleCheck,
  Clock,
  FileText,
  Film,
  Image,
  RefreshCw,
  RotateCw,
  ScanText,
  Send,
  Sparkles,
  Tags,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Badge } from "../../components/Badge";
import type { BadgeTone } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { PageHeader } from "../../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import type { JobRecord, JobStatus, JobType } from "../../api/jobs";
import { t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";

export type JobsPageProps = {
  error?: Error | null;
  isLoading?: boolean;
  isReindexing?: boolean;
  jobs: JobRecord[];
  onReindex: () => void;
  onRetry: (jobId: string) => void;
  onRetryLoad?: () => void;
  retryingJobId?: string | null;
};

type JobStatKind = "failed" | "pending" | "running" | "succeeded";

type JobStat = {
  key: MessageKey;
  kind: JobStatKind;
  value: number;
};

const statStyles: Record<JobStatKind, { icon: LucideIcon; tile: string }> = {
  failed: { icon: CircleAlert, tile: "bg-danger-soft text-danger-ink" },
  pending: { icon: Clock, tile: "bg-warning-soft text-warning-ink" },
  running: { icon: Activity, tile: "bg-accent-soft text-accent-ink" },
  succeeded: { icon: CircleCheck, tile: "bg-success-soft text-success-ink" },
};

const statusTones: Record<JobStatus, { pulse: boolean; tone: BadgeTone }> = {
  failed: { pulse: false, tone: "danger" },
  queued: { pulse: false, tone: "neutral" },
  retrying: { pulse: false, tone: "warning" },
  running: { pulse: true, tone: "accent" },
  succeeded: { pulse: false, tone: "success" },
};

const statusLabels: Record<JobStatus, MessageKey> = {
  failed: "jobs.status.failed",
  queued: "jobs.status.queued",
  retrying: "jobs.status.retrying",
  running: "jobs.status.running",
  succeeded: "jobs.status.succeeded",
};

const typeLabels: Record<JobType, MessageKey> = {
  embedding: "jobs.type.embedding",
  journal_export: "jobs.type.journal_export",
  metadata: "jobs.type.metadata",
  ocr: "jobs.type.ocr",
  pdf_thumbnail: "jobs.type.pdf_thumbnail",
  reindex: "jobs.type.reindex",
  telegram_import: "jobs.type.telegram_import",
  thumbnail: "jobs.type.thumbnail",
  video_thumbnail: "jobs.type.video_thumbnail",
};

const typeIcons: Record<JobType, LucideIcon> = {
  embedding: Sparkles,
  journal_export: BookOpen,
  metadata: Tags,
  ocr: ScanText,
  pdf_thumbnail: FileText,
  reindex: RefreshCw,
  telegram_import: Send,
  thumbnail: Image,
  video_thumbnail: Film,
};

const headerCellClasses = "h-10 px-4 text-left text-xs font-medium whitespace-nowrap text-ink-muted";
const cellClasses = "px-4 py-3 align-middle";

export function JobsPage({
  error,
  isLoading = false,
  isReindexing = false,
  jobs,
  onReindex,
  onRetry,
  onRetryLoad,
  retryingJobId,
}: JobsPageProps) {
  const stats = jobStats(jobs);

  return (
    <div className="mx-auto grid w-full max-w-6xl gap-8">
      <PageHeader
        actions={
          <Button leadingIcon={<RefreshCw />} loading={isReindexing} onClick={onReindex} variant="primary">
            {isReindexing ? t("jobs.admin.reindexing") : t("jobs.admin.reindex")}
          </Button>
        }
        description={t("jobs.header.body")}
        title={t("jobs.header.title")}
      />

      <dl aria-label={t("jobs.stats.label")} className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {stats.map((stat) => {
          const { icon: Icon, tile } = statStyles[stat.kind];

          return (
            <Card className="flex items-start justify-between gap-3" key={stat.key} padding="sm">
              <div className="min-w-0">
                <dt className="text-sm text-ink-muted">{t(stat.key)}</dt>
                <dd className="mt-1 text-3xl font-semibold tracking-tighter tabular-nums text-ink">{stat.value}</dd>
              </div>
              <span aria-hidden="true" className={cx("grid size-9 shrink-0 place-items-center rounded-md", tile)}>
                <Icon className="size-[1.125rem]" />
              </span>
            </Card>
          );
        })}
      </dl>

      {error ? <ErrorState body={t("jobs.error.body")} onRetry={onRetryLoad} /> : null}
      {isLoading && jobs.length === 0 ? <LoadingState /> : null}
      {!isLoading && !error && jobs.length === 0 ? (
        <EmptyState body={t("jobs.empty.body")} icon={<CircleCheck />} title={t("jobs.empty.title")} />
      ) : null}
      {jobs.length > 0 ? (
        <Card className="overflow-hidden" padding="none">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[52rem] border-collapse text-base">
              <caption className="sr-only">{t("jobs.table.caption")}</caption>
              <thead className="bg-subtle">
                <tr>
                  <th className={headerCellClasses} scope="col">
                    {t("jobs.field.type")}
                  </th>
                  <th className={headerCellClasses} scope="col">
                    {t("jobs.field.status")}
                  </th>
                  <th className={headerCellClasses} scope="col">
                    {t("jobs.field.attempts")}
                  </th>
                  <th className={headerCellClasses} scope="col">
                    {t("jobs.field.error")}
                  </th>
                  <th className={headerCellClasses} scope="col">
                    {t("jobs.field.created")}
                  </th>
                  <th className={headerCellClasses} scope="col">
                    {t("jobs.field.updated")}
                  </th>
                  <th className={headerCellClasses} scope="col">
                    <span className="sr-only">{t("common.retry")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <JobRow isRetrying={retryingJobId === job.id} job={job} key={job.id} onRetry={onRetry} />
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}
    </div>
  );
}

function JobRow({ isRetrying, job, onRetry }: { isRetrying: boolean; job: JobRecord; onRetry: (jobId: string) => void }) {
  const TypeIcon = typeIcons[job.type] ?? Activity;
  const status = statusTones[job.status] ?? { pulse: false, tone: "neutral" as const };
  const failed = job.status === "failed";

  return (
    <tr className="border-t border-line transition-colors duration-150 hover:bg-hover">
      <td className={cx(cellClasses, "whitespace-nowrap")}>
        <span className="flex items-center gap-2.5">
          <span aria-hidden="true" className="grid size-7 shrink-0 place-items-center rounded-sm bg-sunken text-ink-muted">
            <TypeIcon className="size-3.5" />
          </span>
          <span className="font-medium text-ink">{jobTypeLabel(job.type)}</span>
        </span>
      </td>
      <td className={cellClasses}>
        <Badge dot pulse={status.pulse} tone={status.tone}>
          {jobStatusLabel(job.status)}
        </Badge>
      </td>
      <td className={cx(cellClasses, "whitespace-nowrap text-sm tabular-nums text-ink-muted")}>
        {job.attempts} / {job.max_attempts}
      </td>
      <td className={cx(cellClasses, "min-w-52 max-w-sm")}>
        {job.error ? (
          <span className={cx("line-clamp-2 text-sm", failed ? "text-danger-ink" : "text-ink-muted")}>{job.error}</span>
        ) : (
          <span className="text-sm text-ink-subtle">
            <span aria-hidden="true">—</span>
            <span className="sr-only">{t("common.unknown")}</span>
          </span>
        )}
      </td>
      <td className={cx(cellClasses, "whitespace-nowrap text-sm tabular-nums text-ink-muted")}>{formatDate(job.created_at)}</td>
      <td className={cx(cellClasses, "whitespace-nowrap text-sm tabular-nums text-ink-muted")}>{formatDate(job.updated_at)}</td>
      <td className={cx(cellClasses, "text-right")}>
        {failed ? (
          <Button
            aria-label={t("jobs.retry.aria").replace("{id}", job.id)}
            leadingIcon={<RotateCw />}
            loading={isRetrying}
            onClick={() => onRetry(job.id)}
            size="sm"
          >
            {isRetrying ? t("jobs.retry.pending") : t("common.retry")}
          </Button>
        ) : null}
      </td>
    </tr>
  );
}

export function jobStats(jobs: JobRecord[]): JobStat[] {
  return [
    { key: "jobs.stats.running", kind: "running", value: jobs.filter((job) => job.status === "running").length },
    {
      key: "jobs.stats.pending",
      kind: "pending",
      value: jobs.filter((job) => job.status === "queued" || job.status === "retrying").length,
    },
    { key: "jobs.stats.failed", kind: "failed", value: jobs.filter((job) => job.status === "failed").length },
    { key: "jobs.stats.succeeded", kind: "succeeded", value: jobs.filter((job) => job.status === "succeeded").length },
  ];
}

function jobStatusLabel(status: JobStatus): string {
  return t(statusLabels[status] ?? "common.unknown");
}

function jobTypeLabel(type: JobType): string {
  return t(typeLabels[type] ?? "common.unknown");
}

function formatDate(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return t("common.unknown");
  }

  return new Intl.DateTimeFormat(t("app.locale"), {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}
