// Progressive enhancement only: every page works and shows usable instructions without it.
// Decides between the Android and the desktop variant of a page from the browser's own
// platform hints. Nothing is stored or sent anywhere.

/**
 * "android" when either the client hints or the user-agent string say Android, otherwise
 * "desktop". Either signal is enough: a false positive only shows the install help first.
 */
export function detectPlatform(nav) {
  const hinted = nav?.userAgentData?.platform;
  if (typeof hinted === "string" && hinted.trim().toLowerCase() === "android") return "android";
  const userAgent = typeof nav?.userAgent === "string" ? nav.userAgent : "";
  return /\bAndroid\b/u.test(userAgent) ? "android" : "desktop";
}

/** Shows `[data-platform]` elements that match the platform and hides the others. */
export function applyPlatform(doc, platform) {
  for (const element of doc.querySelectorAll("[data-platform]")) {
    element.hidden = element.getAttribute("data-platform") !== platform;
  }
}
