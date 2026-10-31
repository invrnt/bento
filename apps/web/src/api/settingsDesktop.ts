import type { FieldIssue, RestartPlan } from "./settings";

export type DesktopPlatform = {
  arch: string;
  desktop: true;
  platform: "darwin" | "linux" | "win32";
  locale?: string;
  recoveryMode: boolean;
  /** `os`: OS keychain wraps the device key; `file`: a 0600 key file in the data directory. */
  secureStorage: "os" | "file";
  version: string;
};

export type SecretOperation =
  | { operation: "clear" }
  | { operation: "set"; value: string }
  | { operation: "unchanged" };

export type DesktopApplyResult = {
  errors?: FieldIssue[];
  ok: boolean;
  restartPlan?: RestartPlan | { affectedKeys: string[]; mode: string; services: string[] };
  revision: number;
  rolledBack?: boolean;
};

export type ApplyProgress = {
  message?: string;
  phase: "validating" | "persisting" | "secrets" | "restarting" | "verifying" | "rolling-back" | "complete";
  status: "failed" | "ok" | "started";
};

export type UpdateProgress = {
  bytesPerSecond?: number;
  percent: number;
  totalBytes: number;
  transferredBytes: number;
};

export type UpdateError = {
  code: string;
  message?: string;
};

export type UpdateState = {
  availableVersion?: string;
  currentVersion: string;
  error?: UpdateError;
  installMode: "automatic" | "manual" | "unsupported";
  progress?: UpdateProgress;
  releaseDate?: string;
  releaseName?: string;
  releaseNotes?: string;
  releaseUrl?: string;
  status: "available" | "checking" | "downloaded" | "downloading" | "error" | "idle" | "installing" | "not-available";
};

export type DesktopNavigationTarget = "activity" | "drive" | "settings" | "recovery-kit";

/** Telegram-first bridge additions (orchestration/architecture/desktop-bridge-telegram-first.md). */
export type BentoDesktopBridge = {
  onDeepLink?(listener: (link: { code: string; kind: "join" }) => void): () => void;
  onNavigate?(listener: (event: { attentionId?: string; target: DesktopNavigationTarget }) => void): () => void;
  preferences?: {
    get(): Promise<{ autoDownloadUpdates: boolean; keepRunningInBackground: boolean; launchAtLogin: boolean }>;
    set(
      patch: Partial<{ autoDownloadUpdates: boolean; keepRunningInBackground: boolean; launchAtLogin: boolean }>,
    ): Promise<{ autoDownloadUpdates: boolean; keepRunningInBackground: boolean; launchAtLogin: boolean }>;
  };
  savePageAsPdf?(request?: { suggestedName?: string }): Promise<{ fileName?: string; saved: boolean }>;
  lifecycle: {
    onStatus(listener: (status: { recoveryMode: boolean; state: string }) => void): () => void;
    status(): Promise<{ recoveryMode: boolean; state: string }>;
  };
  pickDirectory(options?: { title?: string }): Promise<{ canceled: boolean; path?: string }>;
  pickFile(options?: { filters?: { extensions: string[]; name: string }[]; title?: string }): Promise<{ canceled: boolean; path?: string }>;
  platform(): Promise<DesktopPlatform>;
  settings: {
    apply(input: { dataMigration?: "copy" | "use-empty"; revision: number; runProbes?: boolean; secrets: Record<string, SecretOperation>; values: Record<string, unknown> }): Promise<DesktopApplyResult>;
    onProgress(listener: (event: ApplyProgress) => void): () => void;
    probe(input: { kind: "ffmpeg" | "model-file" | "ocr" | "writable-directory"; path?: string }): Promise<{ code?: string; status: "failed" | "ok" }>;
  };
  updates?: {
    check(): Promise<UpdateState>;
    download(): Promise<UpdateState>;
    getState(): Promise<UpdateState>;
    install(): Promise<{ action: "manual" | "restarting"; packageManager?: string }>;
    onState(listener: (state: UpdateState) => void): () => void;
  };
};

declare global {
  interface Window {
    bento?: BentoDesktopBridge;
  }
}

export function desktopBridge(): BentoDesktopBridge | null {
  return typeof window !== "undefined" && window.bento ? window.bento : null;
}

export async function detectDesktopPlatform(): Promise<DesktopPlatform | null> {
  const bridge = desktopBridge();
  if (!bridge) return null;
  try {
    return await bridge.platform();
  } catch {
    return null;
  }
}
