import { NavigateRequest, NavigationTarget } from "../shared/contracts";
import { AttentionItem } from "./activity";
import { AttentionCopyKind, MainStrings } from "./i18n";
import { SendToSummary } from "./send-to";

export interface NotificationOptions {
  title: string;
  body: string;
  silent?: boolean;
  icon?: string;
}

export interface NotificationLike {
  show(): void;
  on(event: "click" | "close" | "failed", listener: () => void): unknown;
}

export interface AttentionMemory {
  readonly notifiedAttentionIds: ReadonlySet<string>;
  rememberAttention(ids: readonly string[]): Promise<void>;
  readonly backgroundNoticeShown: boolean;
  markBackgroundNoticeShown(): Promise<void>;
}

export interface DesktopNotifierOptions {
  platform: NodeJS.Platform;
  strings: MainStrings;
  supported: () => boolean;
  create: (options: NotificationOptions) => NotificationLike;
  memory: AttentionMemory;
  /** Focuses the window and, when given, routes the renderer. */
  activate: (request: NavigateRequest | null) => void;
  /** While true (main window focused), new attention items are only remembered: Actividad already shows them. */
  quiet?: () => boolean;
  icon?: string;
}

/** Above this many new items, one summary notification is shown instead of several. */
const MAX_INDIVIDUAL_NOTIFICATIONS = 2;

export function attentionTarget(item: Pick<AttentionItem, "kind" | "action">): NavigationTarget {
  if (item.action === "save_recovery_kit" || item.kind === "recovery_kit") return "recovery-kit";
  if (item.action === "open_settings") return "settings";
  return "activity";
}

/** Native notifications only for things the user must act on, plus Send-to results and the one-time background notice. */
export class DesktopNotifier {
  // Electron drops click handlers of garbage-collected notifications, so keep them alive until closed.
  private readonly live = new Set<NotificationLike>();

  constructor(private readonly options: DesktopNotifierOptions) {}

  async attention(items: readonly AttentionItem[]): Promise<void> {
    const known = this.options.memory.notifiedAttentionIds;
    const fresh = items.filter((item) => !known.has(item.id));
    if (!fresh.length) return;
    await this.options.memory.rememberAttention(fresh.map((item) => item.id));
    if (this.options.quiet?.()) return;
    const { notifications } = this.options.strings;
    if (fresh.length > MAX_INDIVIDUAL_NOTIFICATIONS) {
      this.show({ title: notifications.attentionSummary(fresh.length), body: notifications.attentionBody }, { target: "activity" });
      return;
    }
    for (const item of fresh) {
      const kind: AttentionCopyKind = item.kind === "unknown" ? "generic" : item.kind;
      const waitMinutes = item.retryAfterSeconds ? Math.max(1, Math.ceil(item.retryAfterSeconds / 60)) : undefined;
      this.show(
        { title: notifications.attentionTitle(kind, { waitMinutes }), body: notifications.attentionBody },
        { target: attentionTarget(item), attentionId: item.id },
      );
    }
  }

  sendToSummary(summary: SendToSummary): void {
    const { notifications } = this.options.strings;
    const notAdded = summary.failed + summary.rejected;
    if (summary.added > 0) {
      this.show({ title: notifications.filesAdded(summary.added), body: notAdded ? notifications.filesFailed(notAdded) : "" }, { target: "drive" });
    } else if (notAdded > 0) {
      this.show({ title: notifications.filesNoneAdded, body: notifications.filesFailed(notAdded) }, { target: "activity" });
    }
  }

  /** Shown the first time closing the window keeps Bento running. */
  async backgroundNotice(): Promise<void> {
    if (this.options.memory.backgroundNoticeShown) return;
    await this.options.memory.markBackgroundNoticeShown();
    const { notifications } = this.options.strings;
    this.show({ title: notifications.backgroundTitle, body: notifications.backgroundBody(this.options.platform), silent: true }, null);
  }

  private show(options: NotificationOptions, request: NavigateRequest | null): void {
    if (!this.options.supported()) return;
    const notification = this.options.create({ ...options, ...(this.options.icon ? { icon: this.options.icon } : {}) });
    this.live.add(notification);
    const release = (): void => { this.live.delete(notification); };
    notification.on("click", () => {
      release();
      this.options.activate(request);
    });
    notification.on("close", release);
    notification.on("failed", release);
    notification.show();
  }

  get liveCount(): number {
    return this.live.size;
  }
}
