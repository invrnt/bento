import { EventEmitter } from "node:events";

export const ACTIVITY_SUMMARIES = ["up_to_date", "uploading", "downloading", "syncing", "paused", "offline", "attention"] as const;
export const ATTENTION_KINDS = ["upload_failed", "sync_error", "flood_wait", "recovery_kit", "inbox_failed"] as const;
export const ATTENTION_ACTIONS = ["retry", "open_settings", "save_recovery_kit", "none"] as const;

export type ActivitySummary = typeof ACTIVITY_SUMMARIES[number];
export type AttentionKind = typeof ATTENTION_KINDS[number];
export type AttentionAction = typeof ATTENTION_ACTIONS[number];

export interface TransferStats {
  active: number;
  queued: number;
  bytesTotal: number;
  bytesDone: number;
  etaSeconds: number | null;
}

export interface AttentionItem {
  id: string;
  /** Unknown kinds from newer backends are kept as "unknown" so they still surface. */
  kind: AttentionKind | "unknown";
  action: AttentionAction;
  retryAfterSeconds?: number;
}

export interface ActivitySnapshot {
  summary: ActivitySummary;
  uploads: TransferStats;
  downloads: TransferStats;
  attention: AttentionItem[];
}

export interface BackupPolicy {
  paused: boolean;
  effectivePaused: boolean;
  onBattery: boolean;
}

export interface ActivityState {
  available: boolean;
  activity: ActivitySnapshot | null;
  policy: BackupPolicy | null;
}

const MAX_ATTENTION_ITEMS = 50;
const ATTENTION_ID = /^[A-Za-z0-9._:-]{1,200}$/u;

function count(value: unknown): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : 0;
}

function transfer(value: unknown): TransferStats {
  const input = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const eta = input.eta_seconds;
  return {
    active: count(input.active),
    queued: count(input.queued),
    bytesTotal: count(input.bytes_total),
    bytesDone: count(input.bytes_done),
    etaSeconds: typeof eta === "number" && Number.isFinite(eta) && eta >= 0 ? Math.round(eta) : null,
  };
}

/** Defensive parse of `GET /api/activity`; returns null for anything that is not a usable payload. */
export function parseActivity(value: unknown): ActivitySnapshot | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const input = value as Record<string, unknown>;
  if (typeof input.summary !== "string" || !(ACTIVITY_SUMMARIES as readonly string[]).includes(input.summary)) return null;
  const attention: AttentionItem[] = [];
  if (Array.isArray(input.attention)) {
    for (const candidate of input.attention.slice(0, MAX_ATTENTION_ITEMS)) {
      if (!candidate || typeof candidate !== "object") continue;
      const item = candidate as Record<string, unknown>;
      if (typeof item.id !== "string" || !ATTENTION_ID.test(item.id)) continue;
      const kind = typeof item.kind === "string" && (ATTENTION_KINDS as readonly string[]).includes(item.kind)
        ? item.kind as AttentionKind
        : "unknown";
      const action = typeof item.action === "string" && (ATTENTION_ACTIONS as readonly string[]).includes(item.action)
        ? item.action as AttentionAction
        : "none";
      const params = item.params && typeof item.params === "object" ? item.params as Record<string, unknown> : {};
      const retry = params.retry_after_seconds;
      attention.push({
        id: item.id,
        kind,
        action,
        ...(typeof retry === "number" && Number.isFinite(retry) && retry > 0 ? { retryAfterSeconds: Math.round(retry) } : {}),
      });
    }
  }
  return { summary: input.summary as ActivitySummary, uploads: transfer(input.uploads), downloads: transfer(input.downloads), attention };
}

export function parsePolicy(value: unknown): BackupPolicy | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const input = value as Record<string, unknown>;
  if (typeof input.paused !== "boolean") return null;
  return {
    paused: input.paused,
    effectivePaused: typeof input.effective_paused === "boolean" ? input.effective_paused : input.paused,
    onBattery: input.on_battery === true,
  };
}

export interface ActivityApiClient {
  apiFetch(pathname: string, init?: RequestInit): Promise<Response>;
}

export type Scheduler = (callback: () => void, delayMs: number) => () => void;

export interface ActivityMonitorOptions {
  client: ActivityApiClient;
  isReady: () => boolean;
  intervalMs?: number;
  schedule?: Scheduler;
}

/**
 * Polls activity and backup policy through the authenticated loopback client. A missing or
 * failing endpoint yields `available: false` so the tray falls back to a neutral state.
 */
export class ActivityMonitor extends EventEmitter {
  private stateValue: ActivityState = { available: false, activity: null, policy: null };
  private cancelTimer: (() => void) | null = null;
  private running = false;
  private suspended = false;
  private inFlight: Promise<void> | null = null;
  private readonly intervalMs: number;
  private readonly schedule: Scheduler;

  constructor(private readonly options: ActivityMonitorOptions) {
    super();
    this.intervalMs = options.intervalMs ?? 5_000;
    this.schedule = options.schedule ?? ((callback, delayMs) => {
      const timer = setTimeout(callback, delayMs);
      return () => clearTimeout(timer);
    });
  }

  get state(): ActivityState {
    return structuredClone(this.stateValue);
  }

  get isPolling(): boolean {
    return this.running && !this.suspended;
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    void this.tick();
  }

  stop(): void {
    this.running = false;
    this.cancelTimer?.();
    this.cancelTimer = null;
  }

  /** System sleep: stop polling until `resume`. */
  suspend(): void {
    this.suspended = true;
    this.cancelTimer?.();
    this.cancelTimer = null;
  }

  resume(): void {
    if (!this.suspended) return;
    this.suspended = false;
    if (this.running) void this.tick();
  }

  refresh(): Promise<void> {
    this.inFlight ??= this.poll().finally(() => { this.inFlight = null; });
    return this.inFlight;
  }

  async setPaused(paused: boolean): Promise<BackupPolicy | null> {
    try {
      const response = await this.options.client.apiFetch("/api/backup/policy", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paused }),
      });
      const policy = response.ok ? parsePolicy(await response.json().catch(() => null)) : null;
      if (policy) this.update({ ...this.stateValue, policy });
      void this.refresh();
      return policy;
    } catch {
      return null;
    }
  }

  private async tick(): Promise<void> {
    this.cancelTimer = null;
    if (!this.running || this.suspended) return;
    await this.refresh();
    if (this.running && !this.suspended && !this.cancelTimer) this.cancelTimer = this.schedule(() => void this.tick(), this.intervalMs);
  }

  private async poll(): Promise<void> {
    if (!this.options.isReady()) {
      this.update({ available: false, activity: null, policy: this.stateValue.policy });
      return;
    }
    const [activity, policy] = await Promise.all([
      this.getJson("/api/activity", parseActivity),
      this.getJson("/api/backup/policy", parsePolicy),
    ]);
    this.update({ available: activity !== null, activity, policy });
  }

  private async getJson<T>(pathname: string, parse: (value: unknown) => T | null): Promise<T | null> {
    try {
      const response = await this.options.client.apiFetch(pathname);
      if (!response.ok) {
        await response.body?.cancel().catch(() => undefined);
        return null;
      }
      return parse(await response.json());
    } catch {
      return null;
    }
  }

  private update(next: ActivityState): void {
    const changed = JSON.stringify(next) !== JSON.stringify(this.stateValue);
    this.stateValue = next;
    if (changed) this.emit("state", this.state);
  }
}
