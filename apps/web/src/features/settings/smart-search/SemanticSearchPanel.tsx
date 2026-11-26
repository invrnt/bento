import { useEffect, useId, useRef, useState } from "react";
import type { RefObject } from "react";
import { Pause, Play, RefreshCw, RotateCcw, Trash2, X } from "lucide-react";

import { apiClient } from "../../../api/client";
import type { ApiClient } from "../../../api/client";
import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { Callout } from "../../../components/Callout";
import { CheckboxBox } from "../../../components/Checkbox";
import { Dialog } from "../../../components/Dialog";
import { t } from "../../../i18n/dictionary";
import { cx } from "../../../lib/cx";
import { formatMessage } from "../../../lib/format";
import { ActivationSheet } from "./ActivationSheet";
import { actionErrorMessage, cancellableStates, describeSmartSearch, formatModelBytes, removableStates, useThrottledAnnouncement } from "./model";
import { SmartSearchProgress } from "./SmartSearchProgress";
import { useSmartSearchMutations, useSmartSearchStatus } from "./useSmartSearch";

export type SemanticSearchPanelProps = {
  client?: ApiClient;
  idlePollIntervalMs?: number | null;
  pollIntervalMs?: number;
};

/**
 * "Buscar por significado" as a managed capability: one switch that opens the confirmation sheet,
 * then every state of the download, check, start and indexing with its actions.
 */
export function SemanticSearchPanel({ client = apiClient, idlePollIntervalMs, pollIntervalMs }: SemanticSearchPanelProps) {
  const live = useSmartSearchStatus(client, { idlePollIntervalMs, pollIntervalMs });
  const actions = useSmartSearchMutations(client, live);
  const announcement = useThrottledAnnouncement(live.status);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [removeOpen, setRemoveOpen] = useState(false);
  const [focusAfter, setFocusAfter] = useState<RefObject<HTMLElement | null> | null>(null);
  const switchRef = useRef<HTMLInputElement | null>(null);
  const primaryRef = useRef<HTMLButtonElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const removeRef = useRef<HTMLButtonElement | null>(null);
  const descriptionId = useId();

  const status = live.status;
  const state = status?.state ?? "off";
  const locked = Boolean(status?.locked);
  const busy = actions.pending !== null;
  const view = status ? describeSmartSearch(status) : null;
  const modelSize = formatModelBytes(status?.model?.size_bytes);

  // An action can remove its own button (cancel → off, remove → off). Once the answer is on screen,
  // keep keyboard focus on the trigger when it survived, or move it to the switch.
  useEffect(() => {
    if (!focusAfter || actions.pending) return;
    setFocusAfter(null);
    const active = typeof document === "undefined" ? null : document.activeElement;
    if (active && active !== document.body && active.isConnected) return;
    (focusAfter.current ?? switchRef.current)?.focus();
  }, [actions.pending, focusAfter, status]);

  function run(action: () => Promise<unknown>, trigger: RefObject<HTMLElement | null>) {
    if (busy) return;
    setFocusAfter(trigger);
    void action();
  }

  function onSwitch(checked: boolean) {
    if (locked || busy || !status) return;
    if (checked && state === "off") {
      actions.clearError();
      setSheetOpen(true);
      return;
    }
    if (checked) return;
    if (removableStates.has(state)) setRemoveOpen(true);
    else if (cancellableStates.has(state)) run(actions.cancel, switchRef);
  }

  async function confirmActivation() {
    const next = await actions.activate();
    if (next) setSheetOpen(false);
  }

  function confirmRemove() {
    setRemoveOpen(false);
    run(actions.remove, removeRef);
  }

  const primary =
    state === "downloading"
      ? { icon: <Pause />, label: t("smartSearch.action.pause"), onClick: () => run(actions.pause, primaryRef) }
      : state === "paused"
        ? { icon: <Play />, label: t("smartSearch.action.resume"), onClick: () => run(actions.resume, primaryRef) }
        : state === "error"
          ? { icon: <RotateCcw />, label: t("smartSearch.action.retry"), onClick: () => run(actions.retry, primaryRef) }
          : null;
  const showActions = Boolean(status) && !locked && state !== "off";
  const actionError = actions.error && actions.error.action !== "activate" ? actions.error.error : null;

  return (
    <div className="grid gap-3 px-5 py-4" data-testid="semantic-search">
      <label className={cx("flex items-start gap-4", locked || !status ? "cursor-not-allowed" : "cursor-pointer")}>
        <span className="grid min-w-0 flex-1 gap-0.5">
          <span className="flex flex-wrap items-center gap-2 text-base font-medium text-ink">
            {t("smartSearch.semantic.label")}
            {view ? <Badge dot pulse={view.badge.pulse} tone={view.badge.tone}>{view.badge.label}</Badge> : null}
          </span>
          <span className="text-sm text-ink-muted" id={descriptionId}>
            {t("smartSearch.semantic.body")}
            {locked ? <span className="mt-1 block text-xs">{t("smartSearch.locked")}</span> : null}
          </span>
        </span>
        <CheckboxBox
          aria-busy={busy || undefined}
          aria-describedby={descriptionId}
          aria-label={t("smartSearch.semantic.label")}
          boxClassName="mt-1"
          checked={state !== "off"}
          disabled={locked || !status}
          onChange={(event) => onSwitch(event.target.checked)}
          ref={switchRef}
        />
      </label>

      {status && state !== "off" && state !== "ready" ? <SmartSearchProgress status={status} /> : null}
      {status?.state === "ready" && status.model ? (
        <p className="text-sm text-ink-muted">{formatMessage("smartSearch.ready.detail", { modelName: status.model.display_name, size: modelSize })}</p>
      ) : null}

      {status?.state === "ready" && status.update_available && !locked ? (
        <Callout
          action={
            <Button aria-busy={actions.pending === "update" || undefined} leadingIcon={<RefreshCw />} onClick={() => run(actions.update, switchRef)} size="sm">
              {t("smartSearch.action.update")}
            </Button>
          }
          tone="info"
        >
          {formatMessage("smartSearch.update.available", { size: formatModelBytes(status.update_available.size_bytes) })}
        </Callout>
      ) : null}

      {showActions ? (
        <div className="flex flex-wrap gap-2">
          {primary ? (
            // One element for pause, resume and retry so focus stays put when the state flips.
            <Button aria-busy={busy || undefined} leadingIcon={primary.icon} onClick={primary.onClick} ref={primaryRef} size="sm">
              {primary.label}
            </Button>
          ) : null}
          {cancellableStates.has(state) ? (
            <Button aria-busy={actions.pending === "cancel" || undefined} leadingIcon={<X />} onClick={() => run(actions.cancel, cancelRef)} ref={cancelRef} size="sm" variant="ghost">
              {t("smartSearch.action.cancel")}
            </Button>
          ) : null}
          {removableStates.has(state) ? (
            <Button
              aria-busy={actions.pending === "remove" || undefined}
              leadingIcon={<Trash2 />}
              onClick={() => !busy && setRemoveOpen(true)}
              ref={removeRef}
              size="sm"
              variant="danger-ghost"
            >
              {formatMessage("smartSearch.action.remove", { size: modelSize })}
            </Button>
          ) : null}
        </div>
      ) : null}

      {actionError ? (
        <Callout role="alert" tone="danger">
          {actionErrorMessage(actionError)}
        </Callout>
      ) : null}
      {!status && live.error ? (
        <Callout
          action={
            <Button leadingIcon={<RefreshCw />} onClick={() => void live.refresh()} size="sm">
              {t("common.retry")}
            </Button>
          }
          role="alert"
          tone="danger"
        >
          {t("smartSearch.error.status")}
        </Callout>
      ) : null}

      <p aria-atomic="true" aria-live="polite" className="sr-only" data-testid="smart-search-announcer" role="status">
        {announcement}
      </p>

      <ActivationSheet
        client={client}
        error={actions.error?.action === "activate" ? actions.error.error : null}
        onConfirm={() => void confirmActivation()}
        onOpenChange={(open) => {
          setSheetOpen(open);
          if (!open) actions.clearError();
        }}
        open={sheetOpen}
        pending={actions.pending === "activate"}
        status={status}
      />

      <Dialog
        actions={
          <>
            <Button data-autofocus onClick={() => setRemoveOpen(false)} variant="ghost">
              {t("smartSearch.remove.keep")}
            </Button>
            <Button leadingIcon={<Trash2 />} onClick={confirmRemove} variant="danger">
              {t("smartSearch.remove.action")}
            </Button>
          </>
        }
        icon={<Trash2 />}
        onOpenChange={setRemoveOpen}
        open={removeOpen}
        title={formatMessage("smartSearch.action.remove", { size: modelSize })}
        tone="danger"
      >
        <p>{t("smartSearch.remove.confirm")}</p>
      </Dialog>
    </div>
  );
}
