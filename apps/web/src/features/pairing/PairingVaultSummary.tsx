import { useId } from "react";
import { CalendarDays, MonitorSmartphone } from "lucide-react";

import type { PairingVault } from "../../api/pairing";
import { t } from "../../i18n/dictionary";
import { formatPlural } from "../../lib/format";
import { formatLongDate, tf } from "../onboarding/format";

/** "Nube a la que se unirá este equipo: creada el … · 3 dispositivos", shown next to the emojis. */
export function PairingVaultSummary({ vault }: { vault: PairingVault | null }) {
  const labelId = useId();
  const created = formatLongDate(vault?.created_at);
  const count = vault?.devices_count ?? null;
  if (!created && count === null) return null;

  return (
    <div aria-labelledby={labelId} className="grid justify-items-center gap-1 text-center" role="group">
      <p className="text-xs font-medium text-ink-subtle" id={labelId}>
        {t("join.pairing.vaultLabel")}
      </p>
      <p className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-sm text-ink-muted">
        {created ? (
          <span className="inline-flex items-center gap-1.5">
            <CalendarDays aria-hidden="true" className="size-3.5 shrink-0" />
            {tf("join.pairing.vaultCreated", { date: created })}
          </span>
        ) : null}
        {count !== null ? (
          <span className="inline-flex items-center gap-1.5 tabular-nums">
            <MonitorSmartphone aria-hidden="true" className="size-3.5 shrink-0" />
            {formatPlural(count, { one: "join.pairing.vaultDevices.one", other: "join.pairing.vaultDevices.other" })}
          </span>
        ) : null}
      </p>
    </div>
  );
}
