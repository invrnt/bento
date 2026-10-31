import { useId } from "react";
import type { ReactNode } from "react";

import { Card } from "../../components/Card";
import { CheckboxBox } from "../../components/Checkbox";
import { cx } from "../../lib/cx";

export type SettingsCardProps = {
  action?: ReactNode;
  children?: ReactNode;
  description?: ReactNode;
  footer?: ReactNode;
  icon: ReactNode;
  id?: string;
  title: string;
};

/** One compartment of a settings section: icon tile, title, help and rows. */
export function SettingsCard({ action, children, description, footer, icon, id, title }: SettingsCardProps) {
  const titleId = useId();

  return (
    <Card aria-labelledby={titleId} as="section" className="overflow-hidden" id={id} padding="none">
      <div className="flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 gap-3.5">
          <span aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-md bg-accent-soft text-accent-ink [&_svg]:size-[1.125rem]">
            {icon}
          </span>
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-ink" id={titleId}>
              {title}
            </h2>
            {description ? <div className="mt-0.5 text-sm text-ink-muted">{description}</div> : null}
          </div>
        </div>
        {action ? <div className="flex shrink-0 flex-wrap gap-2 self-start">{action}</div> : null}
      </div>
      {children ? <div className="divide-y divide-line border-t border-line">{children}</div> : null}
      {footer ? <div className="border-t border-line bg-subtle px-5 py-3">{footer}</div> : null}
    </Card>
  );
}

export type ToggleRowProps = {
  checked: boolean;
  description?: ReactNode;
  disabled?: boolean;
  label: string;
  onChange: (checked: boolean) => void;
  trailing?: ReactNode;
};

/** A labelled on/off row; the whole row is clickable. */
export function ToggleRow({ checked, description, disabled, label, onChange, trailing }: ToggleRowProps) {
  const descriptionId = useId();

  return (
    <label className={cx("flex items-start gap-4 px-5 py-4", disabled ? "cursor-not-allowed" : "cursor-pointer hover:bg-hover")}>
      <span className="grid min-w-0 flex-1 gap-0.5">
        <span className="flex flex-wrap items-center gap-2 text-base font-medium text-ink">
          {label}
          {trailing}
        </span>
        {description ? (
          <span className="text-sm text-ink-muted" id={descriptionId}>
            {description}
          </span>
        ) : null}
      </span>
      <CheckboxBox
        aria-describedby={description ? descriptionId : undefined}
        aria-label={label}
        boxClassName="mt-1"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
    </label>
  );
}
