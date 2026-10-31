import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import path from "node:path";
import { EventEmitter } from "node:events";
import { BENTO_ORIGIN, LifecycleState, ProbeRequest, ProbeResult } from "../shared/contracts";
import { RedactingLog } from "./redaction";
import { DEVICE_WRAPPING_KEY_ENV } from "./device-key";
import { LineSplitter } from "./line-splitter";

interface LaunchCommand { executable: string; prefixArguments: string[] }
interface SpawnedProcess {
  pid?: number;
  exitCode: number | null;
  kill(signal?: NodeJS.Signals): boolean;
  once(event: "exit", listener: (code: number | null, signal: NodeJS.Signals | null) => void): this;
  once(event: "error", listener: (error: Error) => void): this;
  on(event: "exit", listener: (code: number | null, signal: NodeJS.Signals | null) => void): this;
  removeListener(event: "exit", listener: (code: number | null, signal: NodeJS.Signals | null) => void): this;
  stdout?: NodeJS.ReadableStream | null;
  stderr?: NodeJS.ReadableStream | null;
}

/** The API sidecar binds 127.0.0.1:0 itself and reports the port with exactly this stdout line. */
export const API_READY_PREFIX = "BENTO_API_READY ";
export const DESKTOP_API_TOKEN_ENV = "BENTO_DESKTOP_API_TOKEN";
export const SIDECAR_PATH_ENV = "BENTO_SIDECAR_PATH";
/** Never inherited by sidecars; main sets the token for the API process only. */
const STRIPPED_SIDECAR_ENVIRONMENT = [DEVICE_WRAPPING_KEY_ENV, DESKTOP_API_TOKEN_ENV, SIDECAR_PATH_ENV, "API_PORT"] as const;
const TOKEN_HISTORY = 8;

export interface SidecarSupervisorOptions {
  command: LaunchCommand;
  dataDir: string;
  secretEnvironment?: Record<string, string>;
  /** Non-secret runtime configuration (build config, dev storage backend). */
  runtimeEnvironment?: Record<string, string>;
  /** Inherited variables removed from every sidecar environment. */
  strippedEnvironment?: readonly string[];
  /** base64url device wrapping key; omitted when the backend uses its key file. */
  deviceWrappingKey?: string;
  spawnProcess?: (executable: string, args: string[], options: { env: NodeJS.ProcessEnv; stdio: ["ignore", "pipe", "pipe"] }) => SpawnedProcess;
  fetch?: typeof globalThis.fetch;
  randomToken?: () => string;
  delay?: (milliseconds: number) => Promise<void>;
  log?: RedactingLog;
  readinessTimeoutMs?: number;
  shutdownTimeoutMs?: number;
}

export class SidecarSupervisor extends EventEmitter {
  private api: SpawnedProcess | null = null;
  private worker: SpawnedProcess | null = null;
  /** 0 until the running API announced its port; reset as soon as that API is going away. */
  private apiPort = 0;
  private token = "";
  private issuedTokens: string[] = [];
  private stopping = false;
  private stateValue: LifecycleState = "starting";
  private crashTimes: number[] = [];
  private restartAttempt = 0;
  private secretEnvironment: Record<string, string>;
  private readonly spawnProcess: NonNullable<SidecarSupervisorOptions["spawnProcess"]>;
  private readonly fetchImpl: typeof globalThis.fetch;
  private readonly randomToken: () => string;
  private readonly delay: (milliseconds: number) => Promise<void>;
  private readonly log: RedactingLog;
  private readonly readinessTimeoutMs: number;
  private readonly shutdownTimeoutMs: number;

  constructor(private readonly options: SidecarSupervisorOptions) {
    super();
    this.secretEnvironment = { ...options.secretEnvironment };
    this.spawnProcess = options.spawnProcess ?? ((executable, args, childOptions) => spawn(executable, args, childOptions));
    this.fetchImpl = options.fetch ?? globalThis.fetch;
    this.randomToken = options.randomToken ?? (() => randomBytes(32).toString("base64url"));
    this.delay = options.delay ?? ((milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)));
    this.log = options.log ?? new RedactingLog(() => undefined, () => [
      ...this.redactionValues(),
      ...Object.values(this.secretEnvironment),
      ...(options.deviceWrappingKey ? [options.deviceWrappingKey] : []),
    ]);
    this.readinessTimeoutMs = options.readinessTimeoutMs ?? 30_000;
    this.shutdownTimeoutMs = options.shutdownTimeoutMs ?? 5_000;
  }

  get status(): { state: LifecycleState; recoveryMode: boolean } {
    return { state: this.stateValue, recoveryMode: this.stateValue === "recovery" };
  }

  /** Per-launch API tokens issued by this process, for log redaction. */
  redactionValues(): readonly string[] {
    return [...this.issuedTokens];
  }

  /** Resolves once sidecars are ready; rejects if the supervisor enters recovery or stops. */
  waitUntilReady(timeoutMs = 120_000): Promise<void> {
    if (this.stateValue === "ready") return Promise.resolve();
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => { cleanup(); reject(new Error("Desktop services are not ready")); }, timeoutMs);
      const listener = (status: { state: LifecycleState }): void => {
        if (status.state === "ready") { cleanup(); resolve(); }
        else if (status.state === "recovery" || status.state === "stopping") { cleanup(); reject(new Error("Desktop services are not available")); }
      };
      const cleanup = (): void => { clearTimeout(timeout); this.removeListener("status", listener); };
      this.on("status", listener);
    });
  }

  setDataDir(dataDir: string): void {
    this.options.dataDir = dataDir;
  }

  setSecretEnvironment(values: Record<string, string>): void {
    this.secretEnvironment = { ...values };
  }

  async start(): Promise<void> {
    this.stopping = false;
    this.setState("starting");
    const token = this.issueToken();
    await this.runToCompletion("migrate", []);
    await this.startApiAndWait(token);
    this.worker = this.launch("worker", []);
    this.monitor("worker", this.worker);
    this.restartAttempt = 0;
    this.setState("ready");
  }

  async stop(): Promise<void> {
    this.stopping = true;
    this.setState("stopping");
    this.apiPort = 0;
    await Promise.all([this.terminate(this.worker), this.terminate(this.api)]);
    this.worker = null;
    this.api = null;
  }

  async restart(services: readonly string[], secretEnvironment?: Record<string, string>): Promise<void> {
    if (secretEnvironment) this.secretEnvironment = { ...secretEnvironment };
    this.setState("restarting");
    const wasStopping = this.stopping;
    this.stopping = true;
    try {
      if (services.includes("api") || services.includes("desktop")) {
        const oldWorker = this.worker;
        const oldApi = this.api;
        this.worker = null;
        this.api = null;
        this.apiPort = 0;
        await this.terminate(oldWorker);
        await this.terminate(oldApi);
        this.stopping = wasStopping;
        await this.startApiAndWait(this.issueToken());
        this.worker = this.launch("worker", []);
        this.monitor("worker", this.worker);
      } else if (services.includes("worker")) {
        const oldWorker = this.worker;
        this.worker = null;
        await this.terminate(oldWorker);
        this.stopping = wasStopping;
        this.worker = this.launch("worker", []);
        this.monitor("worker", this.worker);
      }
    } finally {
      this.stopping = wasStopping;
    }
    this.setState("ready");
  }

  async verify(): Promise<void> {
    const response = await this.apiFetch("/api/desktop/readiness");
    if (!response.ok || (await response.json() as { status?: string }).status !== "ready") {
      throw new Error("Desktop API did not become healthy");
    }
  }

  async apiFetch(pathname: string, init: RequestInit = {}): Promise<Response> {
    assertApiPath(pathname);
    // The token only ever goes to a port the running API reported over its own stdout.
    if (this.apiPort === 0 || !this.token) throw new Error("Desktop API is not available");
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${this.token}`);
    headers.set("Origin", BENTO_ORIGIN);
    return this.fetchImpl(`http://127.0.0.1:${this.apiPort}${pathname}`, { ...init, headers, redirect: "error" });
  }

  async apiJson<T>(pathname: string, init: RequestInit = {}): Promise<T> {
    const response = await this.apiFetch(pathname, init);
    const body = await response.json() as T;
    if (!response.ok) throw Object.assign(new Error(`Bento API request failed (${response.status})`), { response: body });
    return body;
  }

  async runProbe(request: ProbeRequest): Promise<ProbeResult> {
    const arguments_: string[] = [request.kind];
    if (request.path) arguments_.push("--path", request.path);
    const result = await this.runToCompletion("probe", arguments_, {}, true);
    try {
      return JSON.parse(result.stdout.trim()) as ProbeResult;
    } catch {
      return { status: "failed", code: "invalid_probe_response" };
    }
  }

  private issueToken(): string {
    const token = this.randomToken();
    if (token.length < 32) throw new Error("Desktop launch token is too short");
    this.issuedTokens = [...this.issuedTokens, token].slice(-TOKEN_HISTORY);
    return token;
  }

  private async startApiAndWait(token: string): Promise<void> {
    this.apiPort = 0;
    this.token = token;
    let announce: (port: number) => void = () => undefined;
    const announced = new Promise<number>((resolve) => { announce = resolve; });
    // The API receives its token only through its environment and binds its own loopback port.
    const api = this.launch("api", [], { [DESKTOP_API_TOKEN_ENV]: token }, (line) => {
      const port = parseApiReadyLine(line);
      if (port !== null) announce(port);
    });
    this.api = api;
    this.monitor("api", api);
    const deadline = Date.now() + this.readinessTimeoutMs;
    let port: number;
    try {
      port = await waitForAnnouncement(api, announced, deadline);
    } catch (error) {
      await this.terminate(api);
      throw error;
    }
    if (this.api !== api || api.exitCode !== null) throw new Error("Desktop API exited during startup");
    this.apiPort = port;
    while (Date.now() < deadline) {
      if (api.exitCode !== null) throw new Error("Desktop API exited during startup");
      try {
        await this.verify();
        return;
      } catch {
        await this.delay(100);
      }
    }
    await this.terminate(api);
    throw new Error("Timed out waiting for authenticated desktop API readiness");
  }

  private environment(extra: Record<string, string> = {}): NodeJS.ProcessEnv {
    const inherited: NodeJS.ProcessEnv = { ...process.env };
    for (const key of [...STRIPPED_SIDECAR_ENVIRONMENT, ...(this.options.strippedEnvironment ?? [])]) delete inherited[key];
    return {
      ...inherited,
      ...this.options.runtimeEnvironment,
      BENTO_RUNTIME_MODE: "desktop",
      HOST: "127.0.0.1",
      DATA_DIR: this.options.dataDir,
      BENTO_DESKTOP_ORIGIN: BENTO_ORIGIN,
      ...secretEnvironment(this.secretEnvironment),
      ...(this.options.deviceWrappingKey ? { [DEVICE_WRAPPING_KEY_ENV]: this.options.deviceWrappingKey } : {}),
      ...extra,
    };
  }

  private launch(
    command: string,
    args: string[],
    extraEnvironment: Record<string, string> = {},
    onStdoutLine?: (line: string) => void,
  ): SpawnedProcess {
    const child = this.spawnProcess(
      this.options.command.executable,
      [...this.options.command.prefixArguments, command, ...args],
      { env: this.environment(extraEnvironment), stdio: ["ignore", "pipe", "pipe"] },
    );
    // Redaction runs per complete line, never per chunk.
    const stdout = new LineSplitter((line) => {
      onStdoutLine?.(line);
      this.log.write("info", "sidecar output", { command, output: line });
    });
    const stderr = new LineSplitter((line) => this.log.write("warn", "sidecar diagnostic", { command, output: line }));
    child.stdout?.setEncoding("utf8");
    child.stderr?.setEncoding("utf8");
    child.stdout?.on("data", (chunk) => stdout.push(String(chunk)));
    child.stdout?.on("end", () => stdout.end());
    child.stderr?.on("data", (chunk) => stderr.push(String(chunk)));
    child.stderr?.on("end", () => stderr.end());
    return child;
  }

  private async runToCompletion(command: string, args: string[], extraEnvironment: Record<string, string> = {}, tolerateFailure = false): Promise<{ stdout: string }> {
    const child = this.launch(command, args, extraEnvironment);
    let stdout = "";
    child.stdout?.on("data", (chunk) => { stdout += String(chunk); });
    const code = await new Promise<number>((resolve, reject) => {
      child.once("error", reject);
      child.once("exit", (exitCode) => resolve(exitCode ?? 1));
    });
    if (code !== 0 && !tolerateFailure) throw new Error(`${command} sidecar failed with exit code ${code}`);
    return { stdout };
  }

  private monitor(kind: "api" | "worker", child: SpawnedProcess): void {
    child.on("exit", () => {
      // A dead API's port can be taken by anyone; stop sending the token there at once.
      if (kind === "api" && this.api === child) this.apiPort = 0;
      if (!this.stopping && (kind === "api" ? this.api === child : this.worker === child)) void this.recoverFromCrash(kind);
    });
  }

  private async recoverFromCrash(kind: "api" | "worker"): Promise<void> {
    const now = Date.now();
    this.crashTimes = [...this.crashTimes.filter((timestamp) => now - timestamp < 60_000), now];
    if (this.crashTimes.length >= 3) {
      this.setState("recovery");
      await Promise.all([this.terminate(this.worker), this.terminate(this.api)]);
      return;
    }
    this.restartAttempt += 1;
    await this.delay(Math.min(500 * 2 ** (this.restartAttempt - 1), 8_000));
    try {
      await this.restart(kind === "api" ? ["api", "worker"] : ["worker"]);
    } catch (error) {
      this.log.write("error", "sidecar restart failed", { kind, error: String(error) });
      await this.recoverFromCrash(kind);
    }
  }

  private async terminate(child: SpawnedProcess | null): Promise<void> {
    if (!child || child.exitCode !== null) return;
    const exited = new Promise<void>((resolve) => child.once("exit", () => resolve()));
    child.kill("SIGTERM");
    const graceful = await Promise.race([exited.then(() => true), this.delay(this.shutdownTimeoutMs).then(() => false)]);
    if (!graceful && child.exitCode === null) {
      child.kill("SIGKILL");
      await Promise.race([exited, this.delay(1_000)]);
    }
  }

  private setState(state: LifecycleState): void {
    this.stateValue = state;
    this.emit("status", this.status);
  }
}

/** Packaged builds always run the bundled sidecar; `BENTO_SIDECAR_PATH` is a development override only. */
export function resolveSidecarCommand(
  resourcesPath: string,
  packaged: boolean,
  apiProjectPath: string,
  environment: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
): LaunchCommand {
  if (packaged) {
    const executable = platform === "win32" ? "bento-sidecar.exe" : "bento-sidecar";
    return { executable: path.join(resourcesPath, "bento-sidecar", executable), prefixArguments: [] };
  }
  const override = environment[SIDECAR_PATH_ENV];
  if (override) return { executable: override, prefixArguments: [] };
  return { executable: "uv", prefixArguments: ["run", "--project", apiProjectPath, "bento-sidecar"] };
}

/** The port from a well-formed `BENTO_API_READY {"port":N}` line, otherwise `null`. */
export function parseApiReadyLine(line: string): number | null {
  if (!line.startsWith(API_READY_PREFIX) || line.length > 128) return null;
  let value: unknown;
  try {
    value = JSON.parse(line.slice(API_READY_PREFIX.length));
  } catch {
    return null;
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const keys = Object.keys(value);
  const port = (value as { port?: unknown }).port;
  if (keys.length !== 1 || keys[0] !== "port" || typeof port !== "number" || !Number.isInteger(port)) return null;
  return port >= 1 && port <= 65535 ? port : null;
}

function waitForAnnouncement(child: SpawnedProcess, announced: Promise<number>, deadline: number): Promise<number> {
  return new Promise((resolve, reject) => {
    if (child.exitCode !== null) {
      reject(new Error("Desktop API exited during startup"));
      return;
    }
    const cleanup = (): void => {
      clearTimeout(timeout);
      child.removeListener("exit", exited);
    };
    const exited = (): void => {
      cleanup();
      reject(new Error("Desktop API exited during startup"));
    };
    const timeout = setTimeout(() => {
      cleanup();
      reject(new Error("Timed out waiting for the desktop API to report its port"));
    }, Math.max(0, deadline - Date.now()));
    child.once("exit", exited);
    void announced.then((port) => {
      cleanup();
      resolve(port);
    });
  });
}

/**
 * User-entered secret settings forwarded to sidecars. Telegram-first runtime secrets (session, keyring,
 * device identity) live in the backend key store, so no settings secret is currently forwarded.
 */
export const SECRET_SETTING_KEYS: readonly string[] = Object.freeze([]);

export const SECRET_ENVIRONMENT: Readonly<Record<string, string>> = Object.freeze({});

function secretEnvironment(values: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(values).flatMap(([key, value]) => {
    const environmentKey = Object.hasOwn(SECRET_ENVIRONMENT, key) ? SECRET_ENVIRONMENT[key] : undefined;
    return environmentKey ? [[environmentKey, value]] : [];
  }));
}

function assertApiPath(value: string): void {
  if (!value.startsWith("/api/") || value.includes("\\") || value.includes("#")) {
    throw new Error("Only canonical Bento API routes can be requested");
  }
  let decoded: string;
  try {
    decoded = decodeURIComponent(value.split("?", 1)[0]);
  } catch {
    throw new Error("Only canonical Bento API routes can be requested");
  }
  if (!decoded.startsWith("/api/") || decoded.includes("//") || decoded.split("/").some((part) => part === "." || part === "..")) {
    throw new Error("Only canonical Bento API routes can be requested");
  }
}
