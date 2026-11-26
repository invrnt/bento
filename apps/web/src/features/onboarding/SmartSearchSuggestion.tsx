import { useEffect, useRef, useState } from "react";
import { CircleCheck, Sparkles } from "lucide-react";

import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import { Button } from "../../components/Button";
import { t } from "../../i18n/dictionary";
import { ActivationSheet } from "../settings/smart-search/ActivationSheet";
import { useSmartSearchMutations, useSmartSearchStatus } from "../settings/smart-search/useSmartSearch";

export type SmartSearchSuggestionProps = {
  client?: ApiClient;
};

/**
 * D8: when the API says this machine qualifies (`suggest_in_onboarding`: at least 4 cores and
 * 8 GiB, not Android), the last setup step suggests search by meaning. The browser cannot tell:
 * Firefox and Safari report no memory at all. It only opens the confirmation sheet; nothing
 * downloads until "Descargar y activar".
 */
export function SmartSearchSuggestion({ client = apiClient }: SmartSearchSuggestionProps) {
  const [sheetOpen, setSheetOpen] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [started, setStarted] = useState(false);
  // Read once; Ajustes › Búsqueda inteligente follows the download after setup.
  const live = useSmartSearchStatus(client, { enabled: !started, idlePollIntervalMs: null });
  const actions = useSmartSearchMutations(client, live);
  const startedRef = useRef<HTMLParagraphElement | null>(null);
  const status = live.status;

  // The sheet's trigger is gone once the download starts: keep keyboard focus on the confirmation.
  useEffect(() => {
    if (started) startedRef.current?.focus();
  }, [started]);

  if (started) {
    return (
      <p className="mt-4 flex items-start gap-2.5 rounded-lg border border-line bg-subtle p-3.5 text-sm text-ink-muted outline-none" ref={startedRef} role="status" tabIndex={-1}>
        <CircleCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-success-ink" />
        {t("smartSearch.suggest.started")}
      </p>
    );
  }

  if (dismissed || !status?.suggest_in_onboarding || status.state !== "off" || status.locked || !status.model) return null;

  async function confirm() {
    const next = await actions.activate();
    if (!next) return;
    setSheetOpen(false);
    setStarted(true);
  }

  return (
    <section aria-labelledby="smart-search-suggestion" className="mt-4 flex flex-col gap-3 rounded-lg border border-accent/20 bg-accent-soft p-3.5 sm:flex-row sm:items-start">
      <span aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-md bg-raised text-accent-ink shadow-xs ring-1 ring-line">
        <Sparkles className="size-[1.125rem]" strokeWidth={1.75} />
      </span>
      <div className="grid min-w-0 flex-1 gap-0.5">
        <h2 className="text-base font-medium text-ink" id="smart-search-suggestion">{t("smartSearch.suggest.title")}</h2>
        <p className="text-sm text-ink-muted">{t("smartSearch.suggest.body")}</p>
        <div className="mt-2.5 flex flex-wrap gap-2">
          <Button
            onClick={() => {
              actions.clearError();
              setSheetOpen(true);
            }}
            size="sm"
            variant="primary"
          >
            {t("smartSearch.suggest.details")}
          </Button>
          <Button onClick={() => setDismissed(true)} size="sm" variant="ghost">
            {t("smartSearch.suggest.dismiss")}
          </Button>
        </div>
      </div>
      <ActivationSheet
        client={client}
        error={actions.error?.action === "activate" ? actions.error.error : null}
        onConfirm={() => void confirm()}
        onOpenChange={(open) => {
          setSheetOpen(open);
          if (!open) actions.clearError();
        }}
        open={sheetOpen}
        pending={actions.pending === "activate"}
        status={status}
      />
    </section>
  );
}
