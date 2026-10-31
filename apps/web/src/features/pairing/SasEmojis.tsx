import { t } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import { tf } from "../onboarding/format";

/** The 4 short-authentication emojis both devices must show. */
export function SasEmojis({ className, emojis }: { className?: string; emojis: string[] }) {
  return (
    <div
      aria-label={tf("pairing.sas.label", { emojis: emojis.join(" ") })}
      className={cx("flex flex-wrap justify-center gap-2.5", className)}
      data-testid="sas-emojis"
      role="img"
    >
      {emojis.map((emoji, index) => (
        <span
          aria-hidden="true"
          className="grid size-16 place-items-center rounded-xl border border-line bg-subtle text-[2rem] leading-none shadow-xs sm:size-[4.5rem] sm:text-[2.25rem]"
          key={`${emoji}-${index}`}
        >
          {emoji}
        </span>
      ))}
    </div>
  );
}

export function SasHint() {
  return <p className="text-center text-sm text-ink-muted">{t("pairing.sas.hint")}</p>;
}
