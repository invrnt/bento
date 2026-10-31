/**
 * Client-side navigation for components that are not handed the router's `navigate`
 * callback (toasts, dialogs inside feature pages). `App` re-renders on `popstate`.
 */
export function navigateTo(href: string): void {
  if (`${window.location.pathname}${window.location.search}` === href) {
    return;
  }

  window.history.pushState({}, "", href);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
