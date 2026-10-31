import { Monitor, Moon, Sun } from "lucide-react";

import { t } from "../i18n/dictionary";
import { setThemePreference, useThemePreference } from "../lib/theme";
import type { ThemePreference } from "../lib/theme";
import { SegmentedControl } from "./SegmentedControl";

export function ThemeSwitcher() {
  const preference = useThemePreference();

  return (
    <SegmentedControl<ThemePreference>
      ariaLabel={t("theme.label")}
      iconOnly
      onChange={setThemePreference}
      options={[
        { icon: <Monitor />, label: t("theme.system"), value: "system" },
        { icon: <Sun />, label: t("theme.light"), value: "light" },
        { icon: <Moon />, label: t("theme.dark"), value: "dark" },
      ]}
      size="sm"
      stretch
      value={preference}
    />
  );
}
