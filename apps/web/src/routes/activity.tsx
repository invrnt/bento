import { ActivityPage } from "../features/activity/ActivityPage";

/** `/activity?attention=<id>` highlights one attention item (desktop notifications link here). */
export function ActivityRoute() {
  const focusAttentionId = new URLSearchParams(window.location.search).get("attention");
  return <ActivityPage focusAttentionId={focusAttentionId} />;
}

export default ActivityRoute;
