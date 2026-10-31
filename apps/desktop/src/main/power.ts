import { Scheduler } from "./activity";

export interface PowerMonitorLike {
  isOnBatteryPower(): boolean;
  on(event: "on-battery" | "on-ac", listener: () => void): unknown;
  removeListener(event: "on-battery" | "on-ac", listener: () => void): unknown;
}

export interface PowerApiClient {
  apiFetch(pathname: string, init?: RequestInit): Promise<Response>;
}

export interface PowerReporterOptions {
  monitor: PowerMonitorLike;
  client: PowerApiClient;
  isReady: () => boolean;
  /** Linux emits no on-battery/on-ac events, so the state is also polled. */
  pollMs?: number;
  schedule?: Scheduler;
}

/** Reports battery/AC state to `POST /api/backup/power` on start, on change, and after API restarts. */
export class PowerReporter {
  private lastReported: boolean | null = null;
  private cancelTimer: (() => void) | null = null;
  private running = false;
  private reporting: Promise<void> = Promise.resolve();
  private readonly pollMs: number;
  private readonly schedule: Scheduler;
  private readonly onBattery = (): void => { void this.report(true); };
  private readonly onAc = (): void => { void this.report(false); };

  constructor(private readonly options: PowerReporterOptions) {
    this.pollMs = options.pollMs ?? 60_000;
    this.schedule = options.schedule ?? ((callback, delayMs) => {
      const timer = setTimeout(callback, delayMs);
      return () => clearTimeout(timer);
    });
  }

  get reported(): boolean | null {
    return this.lastReported;
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.options.monitor.on("on-battery", this.onBattery);
    this.options.monitor.on("on-ac", this.onAc);
    void this.poll();
  }

  stop(): void {
    this.running = false;
    this.options.monitor.removeListener("on-battery", this.onBattery);
    this.options.monitor.removeListener("on-ac", this.onAc);
    this.cancelTimer?.();
    this.cancelTimer = null;
  }

  /** The backend keeps power state in memory, so a restarted API must hear it again. */
  apiRestarted(): Promise<void> {
    this.lastReported = null;
    return this.report(this.currentState());
  }

  report(onBattery: boolean | null = this.currentState()): Promise<void> {
    const run = this.reporting.then(() => this.send(onBattery));
    this.reporting = run.catch(() => undefined);
    return run;
  }

  private async poll(): Promise<void> {
    this.cancelTimer = null;
    if (!this.running) return;
    await this.report();
    if (this.running) this.cancelTimer = this.schedule(() => void this.poll(), this.pollMs);
  }

  private currentState(): boolean | null {
    try {
      return this.options.monitor.isOnBatteryPower();
    } catch {
      return null;
    }
  }

  private async send(onBattery: boolean | null): Promise<void> {
    if (onBattery === null || onBattery === this.lastReported || !this.options.isReady()) return;
    try {
      const response = await this.options.client.apiFetch("/api/backup/power", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ on_battery: onBattery }),
      });
      await response.body?.cancel().catch(() => undefined);
      // Unreported states (404 before the endpoint exists, transient errors) retry on the next poll or event.
      if (response.ok) this.lastReported = onBattery;
    } catch {
      // Retried on the next poll or event.
    }
  }
}
