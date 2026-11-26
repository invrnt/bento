import { Download, ExternalLink, Sparkles } from "lucide-react";

import { apiClient } from "../../../api/client";
import type { ApiClient } from "../../../api/client";
import { smartSearchErrorCodes, smartSearchLicenseHref, smartSearchUsePolicyUrl } from "../../../api/smartSearch";
import type { SmartSearchStatus } from "../../../api/smartSearch";
import { Button } from "../../../components/Button";
import { Callout } from "../../../components/Callout";
import { Dialog } from "../../../components/Dialog";
import { t } from "../../../i18n/dictionary";
import { formatBytes, formatMessage } from "../../../lib/format";
import { errorCode } from "../../onboarding/apiErrors";
import { actionErrorMessage, hasRoomForModel, requiredBytes, spaceMessage } from "./model";

export type ActivationSheetProps = {
  client?: ApiClient;
  /** The last activation failure, shown inside the sheet. */
  error: unknown;
  onConfirm: () => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  pending: boolean;
  status: SmartSearchStatus | null;
};

const linkClasses = "focus-ring inline-flex items-center gap-1 rounded-xs font-medium text-accent-ink underline-offset-2 hover:underline [&_svg]:size-3.5";

/**
 * "Activar la búsqueda por significado": size, download host, license and use policy, shown
 * before anything is downloaded. Only "Descargar y activar" starts the download.
 */
export function ActivationSheet({ client = apiClient, error, onConfirm, onOpenChange, open, pending, status }: ActivationSheetProps) {
  const model = status?.model ?? null;
  const room = hasRoomForModel(status);
  const policyUrl = model ? smartSearchUsePolicyUrl(model.model_id) : null;
  const noSpaceRefused = errorCode(error) === smartSearchErrorCodes.noSpace;
  const showSpace = Boolean(model) && (!room || noSpaceRefused);

  return (
    <Dialog
      actions={
        <>
          <Button onClick={() => onOpenChange(false)} variant="ghost">
            {t("smartSearch.activate.cancel")}
          </Button>
          <Button disabled={!model || !room} leadingIcon={<Download />} loading={pending} onClick={onConfirm} variant="primary">
            {t("smartSearch.activate.confirm")}
          </Button>
        </>
      }
      icon={<Sparkles />}
      onOpenChange={onOpenChange}
      open={open}
      title={t("smartSearch.activate.title")}
    >
      {model ? (
        <div className="grid gap-4">
          <p>{formatMessage("smartSearch.activate.body", { host: model.download_host, size: formatBytes(model.size_bytes) })}</p>
          <div className="grid gap-1.5 rounded-lg border border-line bg-subtle p-3.5 text-sm">
            <p className="font-medium text-ink">
              {formatMessage("smartSearch.activate.license", { license: model.license_spdx, modelName: model.display_name })}
            </p>
            <p className="flex flex-wrap gap-x-4 gap-y-1">
              <a className={linkClasses} href={smartSearchLicenseHref(model, client)} rel="noreferrer" target="_blank">
                {t("smartSearch.activate.licenseLink")}
                <ExternalLink aria-hidden="true" />
              </a>
              {policyUrl ? (
                <a className={linkClasses} href={policyUrl} rel="noreferrer" target="_blank">
                  {t("smartSearch.activate.policyLink")}
                  <ExternalLink aria-hidden="true" />
                </a>
              ) : null}
            </p>
          </div>
          {showSpace ? (
            <Callout role="alert" tone="warning">
              {noSpaceRefused
                ? actionErrorMessage(error)
                : spaceMessage(requiredBytes(model.size_bytes), status?.free_bytes ?? 0)}
            </Callout>
          ) : null}
          {error && !noSpaceRefused ? (
            <Callout role="alert" tone="danger">
              {actionErrorMessage(error)}
            </Callout>
          ) : null}
        </div>
      ) : (
        <p>{t("smartSearch.activate.unavailable")}</p>
      )}
    </Dialog>
  );
}
