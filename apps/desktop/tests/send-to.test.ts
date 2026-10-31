import { mkdir, mkdtemp, realpath, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MAX_SEND_TO_FILES,
  multipartFilename,
  multipartFileUpload,
  openRegularFile,
  SendToUploader,
  validateSendToBatch,
} from "../src/main/send-to";

const roots: string[] = [];

async function workspace(): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), "bento-send-to-"));
  roots.push(root);
  // Canonical form (macOS /private/var, Windows long names) so expectations match accepted paths.
  return realpath(root);
}

async function bodyText(stream: ReadableStream<Uint8Array> | null | undefined): Promise<string> {
  return Buffer.from(await new Response(stream ?? null).arrayBuffer()).toString("utf8");
}

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

describe("Send to Bento validation", () => {
  it("accepts regular files and rejects directories, missing, relative, and duplicate paths", async () => {
    const root = await workspace();
    const photo = path.join(root, "photo.jpg");
    const notes = path.join(root, "notes.txt");
    await writeFile(photo, "jpeg");
    await writeFile(notes, "text");
    await mkdir(path.join(root, "folder"));
    const result = await validateSendToBatch([
      photo,
      notes,
      path.join(root, "folder"),
      path.join(root, "missing.pdf"),
      "relative.txt",
      `${photo}\0.exe`,
      path.join(root, ".", "photo.jpg"),
      42,
    ]);
    expect(result.accepted).toEqual([photo, notes]);
    expect(result.rejected).toEqual({ directory: 1, missing: 1, invalid: 3, duplicate: 1 });
  });

  it.skipIf(process.platform === "win32")("rejects a selected symbolic link instead of following it out of the selection", async () => {
    const root = await workspace();
    const secret = path.join(root, "outside", "id_ed25519");
    await mkdir(path.dirname(secret));
    await writeFile(secret, "private key");
    const link = path.join(root, "innocent.jpg");
    await symlink(secret, link);
    const result = await validateSendToBatch([link]);
    expect(result.accepted).toEqual([]);
    expect(result.rejected).toEqual({ symlink: 1 });
    await expect(openRegularFile(link)).rejects.toMatchObject({ code: "ELOOP" });
  });

  it.skipIf(process.platform === "win32")("rejects devices and other non-regular files", async () => {
    const result = await validateSendToBatch(["/dev/null"]);
    expect(result).toEqual({ accepted: [], rejected: { not_regular: 1 } });
  });

  it(`caps each batch at ${MAX_SEND_TO_FILES} files`, async () => {
    const fs = {
      lstat: vi.fn(async () => ({ isFile: () => true, isDirectory: () => false, isSymbolicLink: () => false })),
      realpath: vi.fn(async (value: string) => value),
    };
    const candidates = Array.from({ length: MAX_SEND_TO_FILES + 5 }, (_value, index) => path.resolve(`/tmp/file-${index}.jpg`));
    const result = await validateSendToBatch(candidates, fs);
    expect(result.accepted).toHaveLength(MAX_SEND_TO_FILES);
    expect(result.rejected).toEqual({ too_many: 5 });
    expect(fs.lstat).toHaveBeenCalledTimes(MAX_SEND_TO_FILES);
  });
});

describe("Send to Bento upload request", () => {
  it("escapes multipart filenames like browsers do", () => {
    expect(multipartFilename('a"b\r\nc.jpg')).toBe("a%22b%0D%0Ac.jpg");
    expect(multipartFilename("Café.jpg")).toBe("Café.jpg");
  });

  it("streams a single multipart file part with a fixed field name", async () => {
    async function* content() {
      yield Buffer.from("hello ");
      yield Buffer.from("world");
    }
    const upload = multipartFileUpload('fo"to.jpg', content(), "BentoBoundary123");
    expect(upload.contentType).toBe("multipart/form-data; boundary=BentoBoundary123");
    expect(await bodyText(upload.body)).toBe(
      "--BentoBoundary123\r\n" +
      'Content-Disposition: form-data; name="file"; filename="fo%22to.jpg"\r\n' +
      "Content-Type: application/octet-stream\r\n\r\n" +
      "hello world\r\n--BentoBoundary123--\r\n",
    );
    expect(() => multipartFileUpload("x", content(), "bad\r\nboundary")).toThrow(TypeError);
  });

  it("uploads accepted files one at a time through the authenticated client and reports a summary", async () => {
    const root = await workspace();
    const first = path.join(root, "first.png");
    const second = path.join(root, "second.pdf");
    await writeFile(first, "PNGDATA");
    await writeFile(second, "PDFDATA");
    const requests: Array<{ pathname: string; init: RequestInit; body: string }> = [];
    let active = 0;
    const client = {
      apiFetch: vi.fn(async (pathname: string, init: RequestInit = {}) => {
        active += 1;
        expect(active).toBe(1);
        const body = await bodyText(init.body as ReadableStream<Uint8Array>);
        requests.push({ pathname, init, body });
        active -= 1;
        return new Response("{}", { status: requests.length === 2 ? 500 : 200 });
      }),
    };
    const onComplete = vi.fn();
    const waitUntilReady = vi.fn(async () => undefined);
    const uploader = new SendToUploader({ client, waitUntilReady, onComplete, boundary: () => "B0undary" });
    const summary = await uploader.enqueue([first, second, path.join(root, "missing.jpg")]);

    expect(summary).toEqual({ added: 1, failed: 1, rejected: 1 });
    expect(onComplete).toHaveBeenCalledWith(summary);
    expect(waitUntilReady).toHaveBeenCalledTimes(1);
    expect(requests.map((request) => request.pathname)).toEqual(["/api/assets/upload", "/api/assets/upload"]);
    expect(requests[0]!.init.method).toBe("POST");
    expect(new Headers(requests[0]!.init.headers).get("content-type")).toBe("multipart/form-data; boundary=B0undary");
    expect((requests[0]!.init as RequestInit & { duplex?: string }).duplex).toBe("half");
    expect(requests[0]!.body).toContain('filename="first.png"');
    expect(requests[0]!.body).toContain("PNGDATA");
    expect(requests[1]!.body).toContain("PDFDATA");
    // Paths never leave the device; only the file name is sent.
    expect(requests[0]!.body).not.toContain(root);
  });

  it("closes every opened file even when the request fails before reading it", async () => {
    const close = vi.fn(async () => undefined);
    const uploader = new SendToUploader({
      client: { apiFetch: vi.fn(async () => { throw new Error("connection refused"); }) },
      waitUntilReady: async () => undefined,
      onComplete: vi.fn(),
      fs: {
        lstat: async () => ({ isFile: () => true, isDirectory: () => false, isSymbolicLink: () => false }),
        realpath: async (value) => value,
      },
      openForUpload: async () => ({ chunks: (async function* () { yield Buffer.from("x"); })(), close }),
    });
    await expect(uploader.enqueue([path.resolve("/tmp/a.jpg")])).resolves.toEqual({ added: 0, failed: 1, rejected: 0 });
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("serializes batches and reports nothing for an empty hand-off", async () => {
    const onComplete = vi.fn();
    const order: string[] = [];
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const uploader = new SendToUploader({
      client: { apiFetch: vi.fn(async () => new Response("{}", { status: 200 })) },
      waitUntilReady: async () => { order.push("ready"); await gate; },
      onComplete,
      fs: {
        lstat: async () => ({ isFile: () => true, isDirectory: () => false, isSymbolicLink: () => false }),
        realpath: async (value) => value,
      },
      openForUpload: async (filePath) => {
        order.push(path.basename(filePath));
        return { chunks: (async function* () { yield Buffer.from("x"); })(), close: async () => undefined };
      },
    });
    const first = uploader.enqueue([path.resolve("/tmp/one.jpg")]);
    const second = uploader.enqueue([path.resolve("/tmp/two.jpg")]);
    release();
    await Promise.all([first, second]);
    expect(order).toEqual(["ready", "one.jpg", "ready", "two.jpg"]);
    await uploader.enqueue([]);
    expect(onComplete).toHaveBeenCalledTimes(2);
  });

  it("counts every accepted file as failed when Bento services are not available", async () => {
    const root = await workspace();
    const file = path.join(root, "a.txt");
    await writeFile(file, "x");
    const client = { apiFetch: vi.fn() };
    const uploader = new SendToUploader({ client, waitUntilReady: async () => { throw new Error("recovery"); }, onComplete: vi.fn() });
    await expect(uploader.enqueue([file])).resolves.toEqual({ added: 0, failed: 1, rejected: 0 });
    expect(client.apiFetch).not.toHaveBeenCalled();
  });
});
