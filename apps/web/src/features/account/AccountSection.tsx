import { useState } from "react";
import { LogOut, Send } from "lucide-react";

import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import { logout } from "../../api/account";
import type { AccountStatus } from "../../api/account";
import type { VaultStatus } from "../../api/vault";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { Card } from "../../components/Card";
import { Dialog } from "../../components/Dialog";
import { t } from "../../i18n/dictionary";
import { formatBytes, formatCount } from "../onboarding/format";
import { rememberLocalMode } from "../onboarding/localMode";
import { RecoverySection } from "../recovery/RecoverySection";
import { AccountAvatar } from "./AccountAvatar";

export type AccountSectionProps = {
  account: AccountStatus | null;
  client?: ApiClient;
  onChanged: () => void;
  onConnect?: () => void;
  vault: VaultStatus | null;
};

/** Ajustes › Cuenta y nube: Telegram account, usage, sign out and recovery kit. */
export function AccountSection({ account, client = apiClient, onChanged, onConnect, vault }: AccountSectionProps) {
  const [confirmSignOut, setConfirmSignOut] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutFailed, setSignOutFailed] = useState(false);
  const profile = account?.step === "authorized" ? account.account : null;
  const hasCloud = vault?.state === "ready" || vault?.state === "bootstrapping";

  async function signOut() {
    setSigningOut(true);
    setSignOutFailed(false);
    try {
      await logout(client);
      rememberLocalMode();
      setConfirmSignOut(false);
      onChanged();
    } catch {
      setSignOutFailed(true);
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <div className="grid gap-4">
      {profile ? (
        <Card aria-labelledby="account-title" as="section" padding="none">
          <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
            <AccountAvatar name={profile.display_name} revision={profile.user_id} size="lg" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="truncate text-lg font-semibold text-ink" id="account-title">
                  {profile.display_name}
                </h2>
                {profile.premium ? <Badge tone="accent">{t("account.premium")}</Badge> : null}
              </div>
              <p className="mt-0.5 truncate text-base text-ink-muted">
                {[profile.username ? `@${profile.username}` : null, profile.phone_masked].filter(Boolean).join(" · ") || t("account.connected")}
              </p>
            </div>
            <Button className="self-start sm:self-center" leadingIcon={<LogOut />} onClick={() => setConfirmSignOut(true)} variant="secondary">
              {t("account.signOut")}
            </Button>
          </div>
          {vault && hasCloud ? (
            <dl className="grid gap-4 border-t border-line bg-subtle px-5 py-4 sm:grid-cols-3">
              <Stat label={t("account.usage.space")} value={formatBytes(vault.usage?.bytes ?? 0)} />
              <Stat label={t("account.usage.files")} value={formatCount(vault.usage?.files ?? 0)} />
              <Stat label={t("account.usage.devices")} value={formatCount(vault.devices_count ?? 0)} />
            </dl>
          ) : null}
        </Card>
      ) : (
        <Card className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between" padding="md">
          <div className="flex min-w-0 gap-3.5">
            <span aria-hidden="true" className="grid size-10 shrink-0 place-items-center rounded-md bg-accent-soft text-accent-ink">
              <Send className="size-5" strokeWidth={1.75} />
            </span>
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-ink">{t("account.connect.title")}</h2>
              <p className="mt-0.5 text-base text-ink-muted">{t("account.connect.body")}</p>
            </div>
          </div>
          {onConnect ? (
            <Button className="self-start sm:self-center" onClick={onConnect} variant="primary">
              {t("account.connect.action")}
            </Button>
          ) : null}
        </Card>
      )}

      {vault?.state === "locked" ? (
        <Callout
          action={
            onConnect ? (
              <Button onClick={onConnect} size="sm" variant="primary">
                {t("account.locked.action")}
              </Button>
            ) : undefined
          }
          role="status"
          title={t("account.locked.title")}
          tone="warning"
        >
          {t("account.locked.body")}
        </Callout>
      ) : null}

      {hasCloud ? <RecoverySection accountName={profile?.display_name} client={client} onChanged={onChanged} vault={vault} /> : null}

      <Dialog
        actions={
          <>
            <Button disabled={signingOut} onClick={() => setConfirmSignOut(false)} variant="ghost">
              {t("setup.cancel")}
            </Button>
            <Button leadingIcon={<LogOut />} loading={signingOut} onClick={() => void signOut()} variant="danger">
              {t("account.signOut.confirm")}
            </Button>
          </>
        }
        icon={<LogOut />}
        onOpenChange={(open) => !signingOut && setConfirmSignOut(open)}
        open={confirmSignOut}
        title={t("account.signOut.title")}
        tone="danger"
      >
        <p>{t("account.signOut.body")}</p>
        {signOutFailed ? (
          <Callout className="mt-4" role="alert" tone="danger">
            {t("account.signOut.failed")}
          </Callout>
        ) : null}
      </Dialog>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums text-ink">{value}</dd>
    </div>
  );
}
