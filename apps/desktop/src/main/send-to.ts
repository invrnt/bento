import { randomBytes } from "node:crypto";
import { constants as fsConstants } from "node:fs";
import { FileHandle, lstat, open, realpath } from "node:fs/promises";
import path from "node:path";
import { RedactingLog } from "./redaction";

export const MAX_SEND_TO_FILES = 2_000;
const MAX_PATH_LENGTH = 4_096;
const UPLOAD_CHUNK_BYTES = 1024 * 1024;

export type SendToRejection = "invalid" | "missing" | "directory" | "symlink" | "not_regular" | "duplicate" | "too_many";

export interface SendToValidation {
  accepted: string[];
  rejected: Partial<Record<SendToRejection, number>>;
}

export interface SendToFileSystem {
  lstat(filePath: string): Promise<{ isFile(): boolean; isDirectory(): boolean; isSymbolicLink(): boolean }>;
  realpath(filePath: string): Promise<string>;
}

const defaultFileSystem: SendToFileSystem = { lstat, realpath };

/**
 * Accepts only regular files given by absolute path. Symbolic links (as the selected item) and
 * directories are rejected, duplicates collapse to their canonical path, and batches are capped.
 */
export async function validateSendToBatch(candidates: readonly unknown[], fs: SendToFileSystem = defaultFileSystem): Promise<SendToValidation> {
  const accepted: string[] = [];
  const seen = new Set<string>();
  const rejected: SendToValidation["rejected"] = {};
  const reject = (reason: SendToRejection): void => { rejected[reason] = (rejected[reason] ?? 0) + 1; };
  for (const candidate of candidates) {
    if (accepted.length >= MAX_SEND_TO_FILES) {
      reject("too_many");
      continue;
    }
    if (typeof candidate !== "string" || candidate.length === 0 || candidate.length > MAX_PATH_LENGTH ||
      candidate.includes("\0") || !path.isAbsolute(candidate)) {
      reject("invalid");
      continue;
    }
    const resolved = path.resolve(candidate);
    if (resolved === path.parse(resolved).root) {
      reject("directory");
      continue;
    }
    let info: Awaited<ReturnType<SendToFileSystem["lstat"]>>;
    try {
      info = await fs.lstat(resolved);
    } catch {
      reject("missing");
      continue;
    }
    if (info.isSymbolicLink()) { reject("symlink"); continue; }
    if (info.isDirectory()) { reject("directory"); continue; }
    if (!info.isFile()) { reject("not_regular"); continue; }
    let canonical: string;
    try {
      canonical = await fs.realpath(resolved);
    } catch {
      reject("missing");
      continue;
    }
    if (seen.has(canonical)) { reject("duplicate"); continue; }
    seen.add(canonical);
    accepted.push(canonical);
  }
  return { accepted, rejected };
}

/** WHATWG multipart/form-data filename escaping (what browsers send). */
export function multipartFilename(name: string): string {
  return name.normalize("NFC").replace(/\r/gu, "%0D").replace(/\n/gu, "%0A").replace(/"/gu, "%22");
}

export interface MultipartUpload {
  contentType: string;
  body: ReadableStream<Uint8Array>;
}

export function multipartFileUpload(filename: string, content: AsyncIterable<Uint8Array>, boundary = randomBoundary()): MultipartUpload {
  if (!/^[A-Za-z0-9'()+_,\-./:=?]{1,70}$/u.test(boundary)) throw new TypeError("multipart boundary is invalid");
  const head = Buffer.from(
    `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${multipartFilename(filename)}"\r\n` +
    "Content-Type: application/octet-stream\r\n\r\n",
    "utf8",
  );
  const tail = Buffer.from(`\r\n--${boundary}--\r\n`, "utf8");
  async function* parts(): AsyncGenerator<Uint8Array> {
    yield head;
    for await (const chunk of content) yield chunk;
    yield tail;
  }
  return { contentType: `multipart/form-data; boundary=${boundary}`, body: streamFrom(parts()) };
}

function randomBoundary(): string {
  return `----BentoDesktop${randomBytes(16).toString("hex")}`;
}

function streamFrom(iterable: AsyncIterable<Uint8Array>): ReadableStream<Uint8Array> {
  const iterator = iterable[Symbol.asyncIterator]();
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const { done, value } = await iterator.next();
        if (done) controller.close();
        else controller.enqueue(value);
      } catch (error) {
        controller.error(error);
      }
    },
    async cancel() {
      await iterator.return?.(undefined);
    },
  });
}

export interface UploadApiClient {
  apiFetch(pathname: string, init?: RequestInit): Promise<Response>;
}

export interface SendToSummary {
  added: number;
  failed: number;
  rejected: number;
}

export interface OpenedUpload {
  chunks: AsyncIterable<Uint8Array>;
  /** Idempotent; always called after the request settles. */
  close(): Promise<void>;
}

export interface SendToUploaderOptions {
  client: UploadApiClient;
  waitUntilReady: () => Promise<void>;
  onComplete: (summary: SendToSummary) => void;
  log?: RedactingLog;
  fs?: SendToFileSystem;
  openForUpload?: (filePath: string) => Promise<OpenedUpload>;
  boundary?: () => string;
}

/** Uploads Send-to batches one file at a time through the authenticated loopback client. */
export class SendToUploader {
  private queue: Promise<unknown> = Promise.resolve();

  constructor(private readonly options: SendToUploaderOptions) {}

  enqueue(candidates: readonly unknown[]): Promise<SendToSummary> {
    const run = this.queue.then(() => this.process(candidates));
    this.queue = run.catch(() => undefined);
    return run;
  }

  private async process(candidates: readonly unknown[]): Promise<SendToSummary> {
    const validation = await validateSendToBatch(candidates, this.options.fs);
    const rejected = Object.values(validation.rejected).reduce((total, count) => total + (count ?? 0), 0);
    const summary: SendToSummary = { added: 0, failed: 0, rejected };
    if (rejected) this.options.log?.write("warn", "send-to items rejected", { reasons: validation.rejected });
    if (validation.accepted.length) {
      try {
        await this.options.waitUntilReady();
      } catch {
        summary.failed = validation.accepted.length;
        this.options.onComplete(summary);
        return summary;
      }
      for (const filePath of validation.accepted) {
        if (await this.uploadOne(filePath)) summary.added += 1;
        else summary.failed += 1;
      }
    }
    if (summary.added || summary.failed || summary.rejected) this.options.onComplete(summary);
    return summary;
  }

  private async uploadOne(filePath: string): Promise<boolean> {
    let opened: OpenedUpload | null = null;
    try {
      opened = await (this.options.openForUpload ?? openRegularFile)(filePath);
      const upload = multipartFileUpload(path.basename(filePath), opened.chunks, this.options.boundary?.());
      const response = await this.options.client.apiFetch("/api/assets/upload", {
        method: "POST",
        headers: { "Content-Type": upload.contentType },
        body: upload.body,
        // Node fetch requires half duplex for streaming request bodies.
        duplex: "half",
      } as RequestInit);
      await response.body?.cancel().catch(() => undefined);
      if (!response.ok) this.options.log?.write("warn", "send-to upload rejected", { status: response.status });
      return response.ok;
    } catch (error) {
      this.options.log?.write("warn", "send-to upload failed", { code: (error as NodeJS.ErrnoException).code ?? "upload_failed" });
      return false;
    } finally {
      await opened?.close().catch(() => undefined);
    }
  }
}

/** Opens without following a final symlink (where supported) and re-checks the handle is a regular file. */
export async function openRegularFile(filePath: string): Promise<OpenedUpload> {
  const noFollow = fsConstants.O_NOFOLLOW ?? 0;
  if (!noFollow && (await lstat(filePath)).isSymbolicLink()) throw Object.assign(new Error("symlink"), { code: "ELOOP" });
  const handle = await open(filePath, fsConstants.O_RDONLY | noFollow);
  try {
    if (!(await handle.stat()).isFile()) throw Object.assign(new Error("not a regular file"), { code: "EINVAL" });
  } catch (error) {
    await handle.close().catch(() => undefined);
    throw error;
  }
  let closed: Promise<void> | null = null;
  return {
    chunks: readHandle(handle),
    close: () => (closed ??= handle.close().catch(() => undefined)),
  };
}

async function* readHandle(handle: FileHandle): AsyncGenerator<Uint8Array> {
  const buffer = Buffer.allocUnsafe(UPLOAD_CHUNK_BYTES);
  while (true) {
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, null);
    if (bytesRead === 0) break;
    yield Buffer.from(buffer.subarray(0, bytesRead));
  }
}
