import { constants } from "node:fs";
import { randomBytes } from "node:crypto";
import { copyFile, link, open, rename, unlink } from "node:fs/promises";
import path from "node:path";
import { SavePdfRequest, SavePdfResult } from "../shared/contracts";
import { assertMainWindowFrame, SenderEventLike, SenderFrameLike } from "./sender";
import { validateSafePath } from "./validation";

export interface PdfWebContents {
  readonly mainFrame: SenderFrameLike;
  printToPDF(options: { printBackground: boolean; pageSize: "A4" }): Promise<Buffer>;
}

export interface PdfWindow {
  readonly webContents: PdfWebContents;
  isDestroyed(): boolean;
}

export interface SaveDialogResult {
  canceled: boolean;
  filePath?: string;
}

export interface PdfSaverOptions {
  window: () => PdfWindow | null;
  documentsDirectory: () => string;
  defaultFileName: string;
  dialogTitle: string;
  filterName: string;
  showSaveDialog: (window: PdfWindow, options: {
    title: string;
    defaultPath: string;
    filters: Array<{ name: string; extensions: string[] }>;
    properties: Array<"createDirectory" | "showOverwriteConfirmation">;
  }) => Promise<SaveDialogResult>;
  /** With `exclusive`, rejects with `EEXIST` instead of replacing an existing file. */
  writeFileAtomic?: (filePath: string, data: Uint8Array, options?: { exclusive?: boolean }) => Promise<void>;
}

const MAX_NAME_ATTEMPTS = 100;

/**
 * Prints the main window's current page to PDF and saves it where the user chooses.
 * The renderer never supplies HTML, URLs, or paths, only an optional file name suggestion.
 */
export class PdfSaver {
  private busy = false;

  constructor(private readonly options: PdfSaverOptions) {}

  async save(event: SenderEventLike, request: SavePdfRequest): Promise<SavePdfResult> {
    const window = assertMainWindowFrame(event, this.options.window());
    if (this.busy) throw new Error("pdf_save_in_progress");
    this.busy = true;
    let data: Buffer | null = null;
    try {
      data = await window.webContents.printToPDF({ printBackground: true, pageSize: "A4" });
      const result = await this.options.showSaveDialog(window, {
        title: this.options.dialogTitle,
        defaultPath: path.join(this.options.documentsDirectory(), pdfFileName(request.suggestedName, this.options.defaultFileName)),
        filters: [{ name: this.options.filterName, extensions: ["pdf"] }],
        properties: ["createDirectory", "showOverwriteConfirmation"],
      });
      if (result.canceled || !result.filePath) return { saved: false };
      const chosen = validateSafePath(result.filePath);
      const write = this.options.writeFileAtomic ?? writeFileAtomic;
      if (path.extname(chosen).toLowerCase() === ".pdf") {
        // The dialog itself confirmed replacing this exact path.
        await write(chosen, data);
        return { saved: true, fileName: path.basename(chosen) };
      }
      // Appending `.pdf` names a file the dialog never asked about: never replace it.
      for (let attempt = 1; attempt <= MAX_NAME_ATTEMPTS; attempt += 1) {
        const target = `${chosen}${attempt === 1 ? "" : ` (${attempt})`}.pdf`;
        try {
          await write(target, data, { exclusive: true });
          return { saved: true, fileName: path.basename(target) };
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
        }
      }
      throw Object.assign(new Error("A free file name could not be found"), { code: "EEXIST" });
    } finally {
      // The recovery kit is sensitive; do not leave it in memory longer than necessary.
      data?.fill(0);
      this.busy = false;
    }
  }
}

export function pdfFileName(suggested: string | undefined, fallback: string): string {
  const name = suggested?.trim() || fallback;
  return name.toLowerCase().endsWith(".pdf") ? name : `${name}.pdf`;
}

/**
 * Writes beside the target (same filesystem), flushes, then renames; owner-only permissions.
 * `exclusive` publishes with a hard link (or an exclusive copy where links are unsupported), so an
 * existing file is never replaced and the call rejects with `EEXIST`.
 */
export async function writeFileAtomic(filePath: string, data: Uint8Array, options: { exclusive?: boolean } = {}): Promise<void> {
  const temporary = path.join(path.dirname(filePath), `.${path.basename(filePath)}.${randomBytes(6).toString("hex")}.tmp`);
  const handle = await open(temporary, "wx", 0o600);
  try {
    await handle.writeFile(data);
    await handle.sync();
    await handle.close();
    if (!options.exclusive) {
      await rename(temporary, filePath);
      return;
    }
    try {
      await link(temporary, filePath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "EEXIST") throw error;
      await copyFile(temporary, filePath, constants.COPYFILE_EXCL);
    }
    await unlink(temporary);
  } catch (error) {
    await handle.close().catch(() => undefined);
    await unlink(temporary).catch(() => undefined);
    throw error;
  }
}
