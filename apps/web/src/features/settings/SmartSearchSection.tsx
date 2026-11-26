import { ScanText, Sparkles } from "lucide-react";

import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import { Badge } from "../../components/Badge";
import type { BadgeTone } from "../../components/Badge";
import { Callout } from "../../components/Callout";
import { ErrorState, LoadingState } from "../../components/States";
import { t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import { SettingsCard, ToggleRow } from "./SettingsCard";
import { SemanticSearchPanel } from "./smart-search/SemanticSearchPanel";
import type { SettingsController } from "./useSettingsController";

const ocrBadges: Record<string, { label: MessageKey; tone: BadgeTone }> = {
  disabled: { label: "smartSearch.state.off", tone: "neutral" },
  error: { label: "smartSearch.badge.error", tone: "danger" },
  failed: { label: "smartSearch.badge.error", tone: "danger" },
  pending: { label: "smartSearch.badge.working", tone: "warning" },
  ready: { label: "smartSearch.state.ready", tone: "success" },
};

export type SmartSearchSectionProps = {
  client?: ApiClient;
  controller: SettingsController;
  /** Status poll while nothing runs; `null` reads it once. */
  idlePollIntervalMs?: number | null;
  /** Status poll while the model downloads, is checked, starts or indexes. */
  pollIntervalMs?: number;
};

/**
 * Ajustes › Búsqueda inteligente. OCR stays a plain switch saved with the settings bar
 * (`ocr_provider`); search by meaning is managed by `/api/smart-search` and never writes
 * `embeddings_provider` from here.
 */
export function SmartSearchSection({ client = apiClient, controller, idlePollIntervalMs, pollIntervalMs }: SmartSearchSectionProps) {
  if (controller.isLoading && !controller.schema) return <LoadingState />;
  if (controller.error && !controller.schema) return <ErrorState body={t("settings.settingsError.body")} onRetry={() => void controller.refresh()} />;

  const ocrField = controller.schema?.fields.find((field) => field.key === "ocr_provider");

  return (
    <div className="grid gap-4">
      <SettingsCard description={t("smartSearch.body")} icon={<Sparkles />} title={t("smartSearch.title")}>
        {ocrField ? <OcrRow controller={controller} locked={ocrField.locked || !ocrField.editable} /> : null}
        <SemanticSearchPanel client={client} idlePollIntervalMs={idlePollIntervalMs} pollIntervalMs={pollIntervalMs} />
      </SettingsCard>
      <Callout icon={<ScanText />} tone="neutral">
        {t("smartSearch.footnote")}
      </Callout>
    </div>
  );
}

function OcrRow({ controller, locked }: { controller: SettingsController; locked: boolean }) {
  const saved = controller.values?.values.ocr_provider?.value;
  const draft = controller.draft.ocr_provider;
  const enabled = typeof draft === "string" ? draft !== "disabled" : false;
  // Keep a non-default provider (e.g. `mock` in development) when it was already on.
  const onValue = typeof saved === "string" && saved !== "disabled" ? saved : "rapidocr";
  const state = controller.publicSettings?.ocr_state;
  const badge = state ? ocrBadges[state] : undefined;
  return (
    <ToggleRow
      checked={enabled}
      description={
        <>
          {t("smartSearch.ocr.body")}
          {locked ? <span className="mt-1 block text-xs">{t("smartSearch.locked")}</span> : null}
        </>
      }
      disabled={locked}
      label={t("smartSearch.ocr.label")}
      onChange={(checked) => controller.setValue("ocr_provider", checked ? onValue : "disabled")}
      trailing={badge && enabled === (saved !== "disabled") ? <Badge dot tone={badge.tone}>{t(badge.label)}</Badge> : null}
    />
  );
}
