import { DeepLink } from "../shared/contracts";
import { Scheduler } from "./activity";
import { LaunchRequest, parseDeepLink, parseLaunchArguments } from "./deep-links";
import { MAX_SEND_TO_FILES } from "./send-to";

export interface LaunchHandlers {
  deepLink(link: DeepLink): void;
  rejectedDeepLink(): void;
  files(paths: string[]): void;
}

const MAX_PENDING_DEEP_LINKS = 16;
// Validation caps each batch at MAX_SEND_TO_FILES; keep a little more so overflow is still reported.
const MAX_PENDING_FILES = MAX_SEND_TO_FILES + 1;

/**
 * Collects OS hand-offs (cold-start argv, `second-instance`, macOS `open-url`/`open-file`) that can
 * arrive before the desktop runtime is ready, and dispatches them once handlers are attached.
 */
export class LaunchRouter {
  private handlers: LaunchHandlers | null = null;
  private pendingLinks: string[] = [];
  private pendingBatches: string[][] = [];
  private openFileBatch: string[] = [];
  private cancelOpenFileFlush: (() => void) | null = null;
  private readonly schedule: Scheduler;

  constructor(private readonly options: { openFileDebounceMs?: number; schedule?: Scheduler } = {}) {
    this.schedule = options.schedule ?? ((callback, delayMs) => {
      const timer = setTimeout(callback, delayMs);
      return () => clearTimeout(timer);
    });
  }

  /** Parses user arguments; deep links and files are routed, the parsed request is returned. */
  arguments(args: readonly unknown[]): LaunchRequest {
    const request = parseLaunchArguments(args);
    for (const link of request.deepLinks) this.deepLink(link);
    if (request.files.length) this.files(request.files);
    return request;
  }

  deepLink(raw: unknown): void {
    if (!this.handlers) {
      if (typeof raw === "string" && this.pendingLinks.length < MAX_PENDING_DEEP_LINKS) this.pendingLinks.push(raw);
      return;
    }
    const link = parseDeepLink(raw);
    if (link) this.handlers.deepLink(link);
    else this.handlers.rejectedDeepLink();
  }

  files(paths: readonly string[]): void {
    const batch = paths.slice(0, MAX_PENDING_FILES);
    if (!batch.length) return;
    if (this.handlers) this.handlers.files(batch);
    else if (this.pendingBatches.length < 8) this.pendingBatches.push(batch);
  }

  /** macOS delivers one `open-file` per item; group a burst into one batch. */
  openFile(filePath: string): void {
    if (this.openFileBatch.length < MAX_PENDING_FILES) this.openFileBatch.push(filePath);
    this.cancelOpenFileFlush?.();
    this.cancelOpenFileFlush = this.schedule(() => this.flushOpenFiles(), this.options.openFileDebounceMs ?? 300);
  }

  attach(handlers: LaunchHandlers): void {
    this.handlers = handlers;
    const links = this.pendingLinks;
    const batches = this.pendingBatches;
    this.pendingLinks = [];
    this.pendingBatches = [];
    for (const link of links) this.deepLink(link);
    for (const batch of batches) handlers.files(batch);
  }

  private flushOpenFiles(): void {
    this.cancelOpenFileFlush = null;
    const batch = this.openFileBatch;
    this.openFileBatch = [];
    this.files(batch);
  }
}
