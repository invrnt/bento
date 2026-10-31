import { ScanText, Sparkles } from "lucide-react";

import { Badge } from "../../components/Badge";
import type { BadgeTone } from "../../components/Badge";
import { Callout } from "../../components/Callout";
import { ErrorState, LoadingState } from "../../components/States";
import { t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import { SettingsCard, ToggleRow } from "./SettingsCard";
import type { SettingsController } from "./useSettingsController";

type Capability = {
  description: MessageKey;
  key: "ocr_provider" | "embeddings_provider";
  label: MessageKey;
  onValue: string;
  state?: string;
};

const stateBadges: Record<string, { label: MessageKey; tone: BadgeTone }> = {
  disabled: { label: "smartSearch.state.off", tone: "neutral" },
  error: { label: "smartSearch.state.error", tone: "danger" },
  pending: { label: "smartSearch.state.pending", tone: "warning" },
  ready: { label: "smartSearch.state.ready", tone: "success" },
};

/**
 * Ajustes › Búsqueda inteligente: OCR and semantic search as two plain switches
 * mapped to `ocr_provider` and `embeddings_provider`; saved with the settings bar.
 */
export function SmartSearchSection({ controller }: { controller: SettingsController }) {
  if (controller.isLoading && !controller.schema) return <LoadingState />;
  if (controller.error && !controller.schema) return <ErrorState body={t("settings.settingsError.body")} onRetry={() => void controller.refresh()} />;

  const fields = new Map((controller.schema?.fields ?? []).map((field) => [field.key, field]));
  const capabilities: Capability[] = [
    {
      description: "smartSearch.ocr.body",
      key: "ocr_provider",
      label: "smartSearch.ocr.label",
      onValue: "rapidocr",
      state: controller.publicSettings?.ocr_state,
    },
    {
      description: "smartSearch.semantic.body",
      key: "embeddings_provider",
      label: "smartSearch.semantic.label",
      onValue: "jina",
      state: controller.publicSettings?.embeddings_state,
    },
  ];
  const visible = capabilities.filter((capability) => fields.has(capability.key));

  return (
    <div className="grid gap-4">
      <SettingsCard description={t("smartSearch.body")} icon={<Sparkles />} title={t("smartSearch.title")}>
        {visible.map((capability) => {
          const field = fields.get(capability.key)!;
          const saved = controller.values?.values[capability.key]?.value;
          const draft = controller.draft[capability.key];
          const enabled = typeof draft === "string" ? draft !== "disabled" : false;
          // Keep a non-default provider (e.g. `mock` in development) when it was already on.
          const onValue = typeof saved === "string" && saved !== "disabled" ? saved : capability.onValue;
          const locked = field.locked || !field.editable;
          const badge = capability.state ? stateBadges[capability.state] : undefined;
          return (
            <ToggleRow
              checked={enabled}
              description={
                <>
                  {t(capability.description)}
                  {locked ? <span className="mt-1 block text-xs">{t("smartSearch.locked")}</span> : null}
                </>
              }
              disabled={locked}
              key={capability.key}
              label={t(capability.label)}
              onChange={(checked) => controller.setValue(capability.key, checked ? onValue : "disabled")}
              trailing={badge && enabled === (saved !== "disabled") ? <Badge dot tone={badge.tone}>{t(badge.label)}</Badge> : null}
            />
          );
        })}
      </SettingsCard>
      <Callout icon={<ScanText />} tone="neutral">
        {t("smartSearch.footnote")}
      </Callout>
    </div>
  );
}
