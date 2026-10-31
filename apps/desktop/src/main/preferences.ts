import { randomBytes } from "node:crypto";
import { mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { DesktopPreferences, DesktopPreferencesPatch } from "../shared/contracts";

export const DEFAULT_PREFERENCES: Readonly<DesktopPreferences> = Object.freeze({
  keepRunningInBackground: true,
  // Off until onboarding completes; the renderer then enables it through the bridge.
  launchAtLogin: false,
  autoDownloadUpdates: true,
});

const MAX_REMEMBERED_ATTENTION = 500;
const ATTENTION_ID = /^[A-Za-z0-9._:-]{1,200}$/u;

interface InternalState {
  backgroundNoticeShown: boolean;
  notifiedAttentionIds: string[];
}

interface StateDocument {
  schemaVersion: 1;
  preferences: DesktopPreferences;
  internal: InternalState;
}

export type PreferencesEffect = (next: DesktopPreferences, previous: DesktopPreferences) => Promise<void>;

/** Desktop-only preferences and internal UI state, persisted atomically under the desktop user-data folder. */
export class DesktopStateStore {
  private document: StateDocument = defaultDocument();
  private writes: Promise<void> = Promise.resolve();
  private loaded = false;

  constructor(private readonly filePath: string) {}

  /** Never blocks startup: a missing or invalid document falls back to defaults. */
  async load(): Promise<{ recovered: boolean }> {
    this.loaded = true;
    let raw: string;
    try {
      raw = await readFile(this.filePath, "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return { recovered: false };
      return { recovered: true };
    }
    try {
      const parsed = parseDocument(JSON.parse(raw));
      if (parsed) {
        this.document = parsed;
        return { recovered: false };
      }
    } catch {
      // Fall through to defaults.
    }
    this.document = defaultDocument();
    return { recovered: true };
  }

  get preferences(): DesktopPreferences {
    return { ...this.document.preferences };
  }

  get backgroundNoticeShown(): boolean {
    return this.document.internal.backgroundNoticeShown;
  }

  get notifiedAttentionIds(): ReadonlySet<string> {
    return new Set(this.document.internal.notifiedAttentionIds);
  }

  /** Applies side effects first; the patch persists only if they succeed. */
  async updatePreferences(patch: DesktopPreferencesPatch, effect?: PreferencesEffect): Promise<DesktopPreferences> {
    this.assertLoaded();
    const previous = this.preferences;
    const next: DesktopPreferences = { ...previous, ...patch };
    if (effect) await effect(next, previous);
    this.document = { ...this.document, preferences: next };
    await this.persist();
    return this.preferences;
  }

  async markBackgroundNoticeShown(): Promise<void> {
    this.assertLoaded();
    if (this.document.internal.backgroundNoticeShown) return;
    this.document = { ...this.document, internal: { ...this.document.internal, backgroundNoticeShown: true } };
    await this.persist();
  }

  async rememberAttention(ids: readonly string[]): Promise<void> {
    this.assertLoaded();
    const current = this.document.internal.notifiedAttentionIds;
    const additions = ids.filter((id) => ATTENTION_ID.test(id) && !current.includes(id));
    if (!additions.length) return;
    const notifiedAttentionIds = [...current, ...additions].slice(-MAX_REMEMBERED_ATTENTION);
    this.document = { ...this.document, internal: { ...this.document.internal, notifiedAttentionIds } };
    await this.persist();
  }

  private assertLoaded(): void {
    if (!this.loaded) throw new Error("Desktop state was used before it was loaded");
  }

  private persist(): Promise<void> {
    const snapshot = `${JSON.stringify(this.document)}\n`;
    const write = this.writes.then(() => atomicWrite(this.filePath, snapshot));
    this.writes = write.catch(() => undefined);
    return write;
  }
}

function defaultDocument(): StateDocument {
  return {
    schemaVersion: 1,
    preferences: { ...DEFAULT_PREFERENCES },
    internal: { backgroundNoticeShown: false, notifiedAttentionIds: [] },
  };
}

function parseDocument(value: unknown): StateDocument | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const document = value as Partial<StateDocument>;
  if (document.schemaVersion !== 1 || !document.preferences || typeof document.preferences !== "object") return null;
  const preferences: DesktopPreferences = { ...DEFAULT_PREFERENCES };
  for (const key of Object.keys(DEFAULT_PREFERENCES) as Array<keyof DesktopPreferences>) {
    const candidate = (document.preferences as Partial<DesktopPreferences>)[key];
    if (candidate === undefined) continue;
    if (typeof candidate !== "boolean") return null;
    preferences[key] = candidate;
  }
  const internal = document.internal as Partial<InternalState> | undefined;
  const ids = Array.isArray(internal?.notifiedAttentionIds)
    ? internal.notifiedAttentionIds.filter((id): id is string => typeof id === "string" && ATTENTION_ID.test(id)).slice(-MAX_REMEMBERED_ATTENTION)
    : [];
  return {
    schemaVersion: 1,
    preferences,
    internal: { backgroundNoticeShown: internal?.backgroundNoticeShown === true, notifiedAttentionIds: ids },
  };
}

async function atomicWrite(filePath: string, contents: string): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true, mode: 0o700 });
  const temporary = `${filePath}.${randomBytes(6).toString("hex")}.tmp`;
  try {
    await writeFile(temporary, contents, { encoding: "utf8", mode: 0o600, flag: "wx" });
    await rename(temporary, filePath);
  } catch (error) {
    await unlink(temporary).catch(() => undefined);
    throw error;
  }
}
