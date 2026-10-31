import { createPortal } from "react-dom";

import type { QrMatrix } from "../../api/qr";
import { BrandMark } from "../../components/BrandMark";
import { QrCode } from "../../components/QrCode";
import { t } from "../../i18n/dictionary";
import { formatDate, tf } from "../onboarding/format";
import { recoveryGroups } from "./recoveryCode";

// Printing (browser) and `savePageAsPdf` (desktop) render only this sheet, always in light colors.
const printCss = `
[data-bento-print-root] { display: none; }
@media print {
  @page { size: A4; margin: 18mm; }
  body > *:not([data-bento-print-root]) { display: none !important; }
  [data-bento-print-root] { display: block !important; color-scheme: light; }
  html, body { background: var(--color-white) !important; }
}
`;

export type RecoveryKitSheetProps = {
  accountName?: string | null;
  code: string;
  createdAt?: string | null;
  qr?: QrMatrix | null;
};

/** The printable "Kit de recuperación de Bento" page. Hidden on screen. */
export function RecoveryKitSheet({ accountName, code, createdAt, qr = null }: RecoveryKitSheetProps) {
  if (typeof document === "undefined") return null;
  const created = formatDate(createdAt);

  return createPortal(
    <div data-bento-print-root="" data-testid="recovery-kit-sheet">
      <style>{printCss}</style>
      <article className="mx-auto max-w-[44rem] bg-white p-2 text-ink">
        <header className="flex items-center gap-3 border-b border-line pb-5">
          <BrandMark className="size-10" />
          <div>
            <h1 className="text-2xl font-semibold tracking-tighter">{t("recovery.sheet.title")}</h1>
            <p className="text-sm text-ink-muted">{t("app.tagline")}</p>
          </div>
        </header>
        <dl className="mt-6 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-base">
          {accountName ? (
            <>
              <dt className="text-ink-muted">{t("recovery.sheet.account")}</dt>
              <dd className="font-medium">{accountName}</dd>
            </>
          ) : null}
          {created ? (
            <>
              <dt className="text-ink-muted">{t("recovery.sheet.created")}</dt>
              <dd className="font-medium">{created}</dd>
            </>
          ) : null}
          <dt className="text-ink-muted">{t("recovery.sheet.printed")}</dt>
          <dd className="font-medium">{formatDate(new Date().toISOString())}</dd>
        </dl>
        <section className="mt-8">
          <h2 className="text-sm font-semibold uppercase tracking-[0.08em] text-ink-muted">{t("recovery.code.label")}</h2>
          <div className="mt-3 flex items-center gap-6 rounded-xl border-2 border-ink p-5">
            <div className="grid flex-1 grid-cols-3 gap-3">
              {recoveryGroups(code).map((group, index) => (
                <span className="text-center font-mono text-2xl font-semibold tracking-[0.16em]" key={`${group}-${index}`}>
                  {group}
                </span>
              ))}
            </div>
            {qr ? (
              <div className="w-32 shrink-0">
                <QrCode label={t("recovery.sheet.qr")} matrix={qr} />
              </div>
            ) : null}
          </div>
        </section>
        <p className="mt-8 text-md font-medium">{t("recovery.sheet.keep")}</p>
        <p className="mt-3 text-base text-ink-muted">{t("recovery.sheet.howTo")}</p>
        <p className="mt-6 rounded-lg border border-line p-4 text-base">
          <strong className="font-semibold">{t("recovery.sheet.warningTitle")}</strong> {t("recovery.sheet.warning")}
        </p>
        <p className="mt-8 text-xs text-ink-subtle">{tf("recovery.sheet.footer", { brand: t("app.brand") })}</p>
      </article>
    </div>,
    document.body,
  );
}
