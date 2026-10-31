import { useEffect, useState } from "react";

import { ErrorState, LoadingState } from "../../components/States";
import { t } from "../../i18n/dictionary";
import { formatMessage } from "../../lib/format";
import { contentUrl } from "./quickLookModel";
import type { QuickLookItem } from "./quickLookModel";

/** Text previews read only the first 256 KB through a Range request. */
export const textPreviewBytes = 256 * 1024;

type PreviewState =
  | { status: "loading" }
  | { status: "error" }
  | { content: string; status: "text"; truncated: boolean }
  | { status: "pdf"; url: string };

/** Inline PDF (blob URL in an iframe) or text (`pre`) streamed from `/content`. */
export function DocumentPreview({ item }: { item: QuickLookItem }) {
  const [state, setState] = useState<PreviewState>({ status: "loading" });
  const isText = item.kind === "text";
  const url = contentUrl(item);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    let cancelled = false;

    setState({ status: "loading" });
    void (async () => {
      try {
        const response = await fetch(url, {
          headers: isText ? { Range: `bytes=0-${textPreviewBytes - 1}` } : undefined,
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Preview request failed with status ${response.status}`);
        }

        if (isText) {
          const content = await response.text();
          const total = totalBytes(response.headers?.get?.("content-range") ?? null);
          if (!cancelled) {
            setState({ content, status: "text", truncated: response.status === 206 && total !== null && total > textPreviewBytes });
          }
          return;
        }

        const blob = await response.blob();
        if (typeof URL.createObjectURL !== "function") {
          throw new Error("Inline PDF preview is not supported here");
        }
        objectUrl = URL.createObjectURL(blob);
        if (cancelled) {
          revoke(objectUrl);
          return;
        }
        setState({ status: "pdf", url: objectUrl });
      } catch {
        if (!controller.signal.aborted && !cancelled) {
          setState({ status: "error" });
        }
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
      if (objectUrl) {
        revoke(objectUrl);
      }
    };
  }, [isText, url]);

  if (state.status === "loading") {
    return <LoadingState className="text-ink-muted" label={t("quicklook.loading")} />;
  }

  if (state.status === "error") {
    return <ErrorState body={t("quicklook.error")} className="w-full max-w-md" title={item.name} />;
  }

  if (state.status === "pdf") {
    return (
      <iframe
        className="size-full max-w-5xl animate-fade-in rounded-lg border border-line bg-sunken shadow-xl"
        src={state.url}
        title={formatMessage("quicklook.frameTitle", { name: item.name })}
      />
    );
  }

  return (
    <div className="flex size-full max-w-4xl animate-fade-in flex-col overflow-hidden rounded-lg border border-line bg-raised shadow-xl">
      <pre
        aria-label={item.name}
        className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap p-5 font-mono text-sm leading-relaxed text-ink"
        tabIndex={0}
      >
        {state.content || t("quicklook.empty")}
      </pre>
      {state.truncated ? (
        <p className="border-t border-line bg-subtle px-5 py-2 text-xs text-ink-muted">{t("quicklook.truncated")}</p>
      ) : null}
    </div>
  );
}

function totalBytes(contentRange: string | null): number | null {
  const match = contentRange ? /\/(\d+)\s*$/.exec(contentRange) : null;
  return match ? Number(match[1]) : null;
}

function revoke(url: string) {
  if (typeof URL.revokeObjectURL === "function") {
    URL.revokeObjectURL(url);
  }
}
