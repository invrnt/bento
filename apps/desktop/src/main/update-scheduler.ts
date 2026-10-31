import { UpdateState } from "../shared/contracts";
import { Scheduler } from "./activity";

export const UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;

export interface ScheduledUpdates {
  readonly state: UpdateState;
  initialize(): Promise<UpdateState>;
  check(): Promise<UpdateState>;
  download(): Promise<UpdateState>;
}

export interface UpdateSchedulerOptions {
  updates: ScheduledUpdates;
  autoDownload: () => boolean;
  intervalMs?: number;
  schedule?: Scheduler;
}

/**
 * Checks metadata at startup and every 6 h. With `autoDownloadUpdates`, an available update is
 * downloaded and verified in the background; the existing controller keeps every verification and
 * fail-closed rule, and installation stays an explicit user action.
 */
export class UpdateScheduler {
  private cancelTimer: (() => void) | null = null;
  private running = false;
  private cycle: Promise<void> | null = null;
  private readonly intervalMs: number;
  private readonly schedule: Scheduler;

  constructor(private readonly options: UpdateSchedulerOptions) {
    this.intervalMs = options.intervalMs ?? UPDATE_CHECK_INTERVAL_MS;
    this.schedule = options.schedule ?? ((callback, delayMs) => {
      const timer = setTimeout(callback, delayMs);
      return () => clearTimeout(timer);
    });
  }

  start(): Promise<void> {
    if (this.running) return this.cycle ?? Promise.resolve();
    this.running = true;
    return this.tick();
  }

  stop(): void {
    this.running = false;
    this.cancelTimer?.();
    this.cancelTimer = null;
  }

  /** One check (+ background download when enabled); never throws. */
  runCycle(): Promise<void> {
    this.cycle ??= this.check().finally(() => { this.cycle = null; });
    return this.cycle;
  }

  /** Called when the preference changes; downloads right away if an update is already waiting. */
  async autoDownloadChanged(): Promise<void> {
    if (this.options.autoDownload() && this.options.updates.state.status === "available") await this.download();
  }

  private async tick(): Promise<void> {
    this.cancelTimer = null;
    if (!this.running) return;
    await this.runCycle();
    if (this.running) this.cancelTimer = this.schedule(() => void this.tick(), this.intervalMs);
  }

  private async check(): Promise<void> {
    try {
      await this.options.updates.initialize();
      const state = this.options.updates.state;
      // Never overlap a running download or install.
      if (state.status === "downloading" || state.status === "installing") return;
      const checked = await this.options.updates.check();
      if (checked.status === "available" && this.options.autoDownload()) await this.download();
    } catch {
      // The controller exposes a bounded error code in its state; the next cycle retries.
    }
  }

  private async download(): Promise<void> {
    try {
      await this.options.updates.download();
    } catch {
      // Verification failures surface as `status: "error"`; nothing is staged.
    }
  }
}
