import { ArrowLeft, Compass } from "lucide-react";

import { Button } from "../components/Button";
import { EmptyState } from "../components/States";
import { t } from "../i18n/dictionary";
import type { MessageKey } from "../i18n/dictionary";

export type RoutePlaceholderProps = {
  bodyKey: MessageKey;
  titleKey: MessageKey;
};

export function RoutePlaceholder({ bodyKey, titleKey }: RoutePlaceholderProps) {
  return (
    <div className="mx-auto grid w-full max-w-3xl flex-1 content-center">
      <EmptyState
        action={
          <Button leadingIcon={<ArrowLeft />} onClick={goHome}>
            {t("route.notFound.action")}
          </Button>
        }
        body={t(bodyKey)}
        icon={<Compass />}
        title={t(titleKey)}
      />
    </div>
  );
}

function goHome() {
  window.history.pushState({}, "", "/photos");
  window.dispatchEvent(new PopStateEvent("popstate"));
}
