import { SettingsPage } from "../features/settings/SettingsPage";
import { settingsLocation } from "../features/settings/sections";
import { useSettingsController } from "../features/settings/useSettingsController";

export type SettingsRouteProps = {
  onNavigate: (href: string) => void;
  onStartSetup?: () => void;
  pathname: string;
  search?: string;
};

export function SettingsRoute({ onNavigate, onStartSetup, pathname, search = "" }: SettingsRouteProps) {
  const settings = useSettingsController();
  const location = settingsLocation(pathname, search);
  return <SettingsPage controller={settings} focus={location.focus} onNavigate={onNavigate} onStartSetup={onStartSetup} section={location.section} />;
}

export default SettingsRoute;
