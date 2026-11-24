import { randomBytes } from "node:crypto";
import { chmod, mkdir, rename, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import type { ApiEndpoint } from "./sidecars";

/** Read by `bento --target auto|desktop`; schema in `orchestration/architecture/cli-runtime.md`. */
export const CLI_ENDPOINT_FILE = "cli-endpoint.json";

export interface CliEndpointDocument {
  version: 1;
  kind: "desktop";
  url: string;
  token: string;
  pid: number;
  app_version: string;
  started_at: string;
}

export interface CliEndpointFileOptions {
  /** `<userData>/bento-desktop` */
  directory: string;
  pid: number;
  appVersion: string;
  now?: () => Date;
  warn?: (message: string, context?: Record<string, unknown>) => void;
}

export function cliEndpointDocument(endpoint: ApiEndpoint, options: { pid: number; appVersion: string; startedAt: Date }): CliEndpointDocument {
  return {
    version: 1,
    kind: "desktop",
    url: `http://127.0.0.1:${endpoint.port}`,
    token: endpoint.cliToken,
    pid: options.pid,
    app_version: options.appVersion,
    started_at: options.startedAt.toISOString(),
  };
}

/**
 * Publishes the desktop API for the local CLI. Writes are atomic (temp file + rename, `0600`) and
 * serialized, so the file always describes the latest ready API or does not exist.
 */
export class CliEndpointFile {
  readonly filePath: string;
  private queue: Promise<void> = Promise.resolve();
  private readonly now: () => Date;

  constructor(private readonly options: CliEndpointFileOptions) {
    this.filePath = path.join(options.directory, CLI_ENDPOINT_FILE);
    this.now = options.now ?? (() => new Date());
  }

  /** Follows `SidecarSupervisor`'s `api-endpoint` event. */
  update(endpoint: ApiEndpoint | null): Promise<void> {
    return endpoint ? this.publish(endpoint) : this.remove();
  }

  publish(endpoint: ApiEndpoint): Promise<void> {
    const document = cliEndpointDocument(endpoint, { pid: this.options.pid, appVersion: this.options.appVersion, startedAt: this.now() });
    return this.enqueue(() => this.write(document), "desktop CLI endpoint could not be written");
  }

  remove(): Promise<void> {
    return this.enqueue(() => removeIfPresent(this.filePath), "desktop CLI endpoint could not be removed");
  }

  /** Resolves once every queued write/removal has finished. */
  flush(): Promise<void> {
    return this.queue;
  }

  private enqueue(operation: () => Promise<void>, failure: string): Promise<void> {
    // Errors are reported without the document: it carries the CLI token.
    this.queue = this.queue.then(operation).catch((error: unknown) => {
      this.options.warn?.(failure, { code: (error as NodeJS.ErrnoException | undefined)?.code ?? "unknown" });
    });
    return this.queue;
  }

  private async write(document: CliEndpointDocument): Promise<void> {
    await mkdir(this.options.directory, { recursive: true, mode: 0o700 });
    const temporary = path.join(this.options.directory, `.${CLI_ENDPOINT_FILE}.${randomBytes(6).toString("hex")}.tmp`);
    try {
      await writeFile(temporary, `${JSON.stringify(document)}\n`, { encoding: "utf8", mode: 0o600, flag: "wx" });
      // `mode` is subject to the umask; make the permission explicit before the file becomes visible.
      if (process.platform !== "win32") await chmod(temporary, 0o600);
      await rename(temporary, this.filePath);
    } catch (error) {
      await removeIfPresent(temporary).catch(() => undefined);
      throw error;
    }
  }
}

async function removeIfPresent(filePath: string): Promise<void> {
  try {
    await unlink(filePath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
}
