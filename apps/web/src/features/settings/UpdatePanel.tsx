import { useState } from "react";
import type { ReactNode } from "react";
import { Download, RefreshCw, Rocket } from "lucide-react";

import type { DesktopPlatform, UpdateState } from "../../api/settingsDesktop";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import type { CalloutTone } from "../../components/Callout";
import { Dialog } from "../../components/Dialog";
import { ProgressBar } from "../../components/ProgressBar";
import { Spinner } from "../../components/Spinner";
import { t } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import { useUpdateController } from "./useUpdateController";

export function UpdatePanel({ desktop }: { desktop: DesktopPlatform }) {
  const updater = useUpdateController(desktop);
  const [confirmInstall, setConfirmInstall] = useState(false);
  const { state } = updater;
  const downloading = state.status === "downloading";
  const manual = state.installMode === "manual";

  return (
    <section aria-labelledby="desktop-update-title" className="grid gap-4 border-b border-line px-5 py-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <span aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-md bg-accent-soft text-accent-ink">
            <Rocket className="size-[1.125rem]" strokeWidth={1.75} />
          </span>
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink-muted">{t("settings.update.eyebrow")}</p>
            <h3 className="text-base font-semibold text-ink" id="desktop-update-title">{t("settings.update.title")}</h3>
            <p className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-ink-muted">
              {t("settings.update.currentVersion")}
              <Badge className="font-mono">{state.currentVersion || desktop.version}</Badge>
            </p>
          </div>
        </div>
        <UpdateAction state={state} supported={updater.supported} onCheck={updater.check} onDownload={updater.download} onInstall={() => setConfirmInstall(true)} />
      </div>

      <div aria-atomic="true" aria-live={state.status === "error" ? "assertive" : "polite"}>
        <StatusContent state={state} supported={updater.supported} />
      </div>

      {downloading ? <DownloadProgress state={state} /> : null}

      <Dialog
        actions={
          <>
            <Button onClick={() => setConfirmInstall(false)} variant="ghost">{t("settings.update.installLater")}</Button>
            <Button leadingIcon={<Rocket />} onClick={() => { setConfirmInstall(false); void updater.install(); }} variant="primary">
              {manual ? t("settings.update.showPackage") : t("settings.update.installConfirm")}
            </Button>
          </>
        }
        icon={<Rocket />}
        onOpenChange={setConfirmInstall}
        open={confirmInstall}
        title={manual ? t("settings.update.manualTitle") : t("settings.update.installTitle")}
      >
        <p>{manual ? t("settings.update.manualBody") : t("settings.update.installBody")}</p>
        <p className="mt-3 font-medium text-ink">{manual ? t("settings.update.manualReminder") : t("settings.update.installReminder")}</p>
      </Dialog>
    </section>
  );
}

function UpdateAction({ onCheck, onDownload, onInstall, state, supported }: { onCheck: () => Promise<void>; onDownload: () => Promise<void>; onInstall: () => void; state: UpdateState; supported: boolean }) {
  if (state.status === "available") {
    return <Button className="self-start" leadingIcon={<Download />} onClick={() => void onDownload()} size="sm" variant="primary">{t("settings.update.download")}</Button>;
  }
  if (state.status === "downloaded") {
    return (
      <Button className="self-start" leadingIcon={<Rocket />} onClick={onInstall} size="sm" variant="primary">
        {state.installMode === "manual" ? t("update.installManual") : t("update.restart")}
      </Button>
    );
  }
  const busy = state.status === "checking" || state.status === "downloading" || state.status === "installing";
  return (
    <Button
      className="self-start"
      disabled={!supported || busy}
      leadingIcon={<RefreshCw className={cx(state.status === "checking" && "motion-safe:animate-spin")} />}
      onClick={() => void onCheck()}
      size="sm"
    >
      {state.status === "error" ? t("settings.update.retry") : t("settings.update.check")}
    </Button>
  );
}

function StatusContent({ state, supported }: { state: UpdateState; supported: boolean }) {
  if (!supported) return <Status>{t("settings.update.unsupported")}</Status>;
  switch (state.status) {
    case "checking": return <Status busy>{t("settings.update.checking")}</Status>;
    case "available": return <Status title={`${t("settings.update.available")} ${state.availableVersion ?? ""}`} tone="info">{releaseDetails(state)}</Status>;
    case "not-available": return <Status title={t("settings.update.upToDate")} tone="success" />;
    case "downloading": return <Status busy>{t("settings.update.downloading")}</Status>;
    case "downloaded": return <Status title={`${t("settings.update.ready")} ${state.availableVersion ?? ""}`} tone="success">{t("settings.update.readyBody")}</Status>;
    case "installing": return <Status busy>{t("settings.update.installing")}</Status>;
    case "error":
      return (
        <Status title={t("settings.update.error")} tone="danger">
          <span>{updateErrorBody(state.error?.code)}</span>
          {state.error?.code ? <span className="mt-1 block font-mono text-xs">{`${t("settings.update.errorCode")} ${state.error.code}`}</span> : null}
        </Status>
      );
    default: return <Status>{t("update.idle")}</Status>;
  }
}

function Status({ busy = false, children, title, tone = "neutral" }: { busy?: boolean; children?: ReactNode; title?: string; tone?: CalloutTone }) {
  return (
    <Callout icon={busy ? <Spinner className="text-accent-ink" /> : undefined} title={title} tone={tone}>
      {children}
    </Callout>
  );
}

function DownloadProgress({ state }: { state: UpdateState }) {
  const progress = state.progress;
  const percent = clamp(progress?.percent ?? 0, 0, 100);
  return (
    <div className="grid gap-1.5">
      <ProgressBar label={t("settings.update.progressLabel")} value={percent} />
      <div className="flex items-center justify-between gap-3 text-xs font-medium tabular-nums text-ink-muted">
        <span>{formatBytes(progress?.transferredBytes ?? 0)} {t("settings.update.of")} {formatBytes(progress?.totalBytes ?? 0)}</span>
        <span>{new Intl.NumberFormat("es", { maximumFractionDigits: 1 }).format(percent)}%</span>
      </div>
    </div>
  );
}

function releaseDetails(state: UpdateState) {
  if (!state.releaseName && !state.releaseNotes) return null;
  return (
    <details className="group/notes">
      <summary className="focus-ring w-fit rounded-xs font-medium text-accent-ink hover:underline">{t("settings.update.releaseNotes")}</summary>
      {state.releaseName ? <p className="mt-2 font-medium text-ink">{state.releaseName}</p> : null}
      {state.releaseNotes ? <p className="mt-1 whitespace-pre-wrap text-sm">{state.releaseNotes}</p> : null}
    </details>
  );
}

function updateErrorBody(code?: string): string {
  if (!code) return t("settings.update.errorBody");
  if (/network|download|response/u.test(code)) return t("settings.update.errorNetwork");
  if (/checksum|digest|metadata|size|verif|signature|manifest|hash/u.test(code)) return t("settings.update.errorVerification");
  if (/development|platform_unsupported|install_unsupported/u.test(code)) return t("settings.update.errorUnsupported");
  if (/install|updater|package_manager/u.test(code)) return t("settings.update.errorInstall");
  return t("settings.update.errorBody");
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${new Intl.NumberFormat("es", { maximumFractionDigits: 1 }).format(bytes / 1024 ** exponent)} ${units[exponent]}`;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Number.isFinite(value) ? value : min));
}
