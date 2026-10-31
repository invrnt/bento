import { useState } from "react";

import { absoluteApiPath } from "../../api/client";
import { accountAvatarPath } from "../../api/account";
import { cx } from "../../lib/cx";

export type AccountAvatarProps = {
  className?: string;
  name: string;
  /** Bumps the image URL after a new sign-in. */
  revision?: number | string;
  size?: "sm" | "md" | "lg";
};

const sizes = {
  lg: "size-14 text-lg",
  md: "size-10 text-base",
  sm: "size-8 text-sm",
};

/** Telegram profile photo from `/api/account/avatar`, falling back to initials. */
export function AccountAvatar({ className, name, revision, size = "md" }: AccountAvatarProps) {
  const [failed, setFailed] = useState(false);
  const src = `${absoluteApiPath(accountAvatarPath)}${revision === undefined ? "" : `?v=${encodeURIComponent(String(revision))}`}`;

  return (
    <span
      aria-hidden="true"
      className={cx(
        "relative grid shrink-0 place-items-center overflow-hidden rounded-full bg-accent-soft font-semibold text-accent-ink ring-1 ring-line",
        sizes[size],
        className,
      )}
    >
      <span>{initials(name)}</span>
      {failed ? null : (
        <img alt="" className="absolute inset-0 size-full object-cover" decoding="async" onError={() => setFailed(true)} src={src} />
      )}
    </span>
  );
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? [parts[0], parts[parts.length - 1]] : parts.slice(0, 1);
  return letters.map((part) => Array.from(part)[0]?.toLocaleUpperCase() ?? "").join("") || "·";
}
