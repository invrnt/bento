import { contextBridge, ipcRenderer } from "electron";
import type {
  BentoDesktopBridge,
  DeepLink,
  DesktopPreferences,
  DesktopPreferencesPatch,
  DirectoryPickerRequest,
  FilePickerRequest,
  IPC_CHANNELS as SharedChannels,
  LifecycleStatus,
  NavigateRequest,
  PlatformMetadata,
  ProbeRequest,
  ProbeResult,
  ProgressEvent,
  SavePdfRequest,
  SavePdfResult,
  SettingsApplyRequest,
  SettingsApplyResult,
  UpdateInstallResult,
  UpdateState,
} from "../shared/contracts";

// Sandboxed preloads can only require "electron", so the channel table is inlined here.
// Typing it as the shared table makes any drift (missing, extra, or renamed channel) a compile error.
export const IPC_CHANNELS: typeof SharedChannels = {
  platform: "bento:platform",
  pickDirectory: "bento:pick-directory",
  pickFile: "bento:pick-file",
  settingsApply: "bento:settings-apply",
  settingsProbe: "bento:settings-probe",
  settingsProgress: "bento:settings-progress",
  lifecycleStatus: "bento:lifecycle-status",
  lifecycleChanged: "bento:lifecycle-changed",
  updatesState: "bento:updates-state",
  updatesCheck: "bento:updates-check",
  updatesDownload: "bento:updates-download",
  updatesInstall: "bento:updates-install",
  updatesChanged: "bento:updates-changed",
  preferencesGet: "bento:preferences-get",
  preferencesSet: "bento:preferences-set",
  deepLinkSubscribe: "bento:deep-link-subscribe",
  deepLinkUnsubscribe: "bento:deep-link-unsubscribe",
  deepLinkReceived: "bento:deep-link",
  navigateSubscribe: "bento:navigate-subscribe",
  navigateUnsubscribe: "bento:navigate-unsubscribe",
  navigateRequested: "bento:navigate",
  savePageAsPdf: "bento:save-page-as-pdf",
};

interface NarrowIpcRenderer {
  invoke(channel: string, payload?: unknown): Promise<unknown>;
  on(channel: string, listener: (_event: unknown, payload: unknown) => void): void;
  removeListener(channel: string, listener: (_event: unknown, payload: unknown) => void): void;
}

export function createBentoBridge(ipc: NarrowIpcRenderer): BentoDesktopBridge {
  const subscribe = <T>(channel: string, listener: (payload: T) => void): (() => void) => {
    const guarded = (_event: unknown, payload: unknown): void => listener(payload as T);
    ipc.on(channel, guarded);
    return () => ipc.removeListener(channel, guarded);
  };

  // Buffered streams: main holds events until the first listener subscribes and flushes them once.
  const buffered = <T>(event: string, subscribeChannel: string, unsubscribeChannel: string) => {
    let listeners = 0;
    return (listener: (payload: T) => void): (() => void) => {
      const remove = subscribe(event, listener);
      listeners += 1;
      if (listeners === 1) void Promise.resolve(ipc.invoke(subscribeChannel)).catch(() => undefined);
      let active = true;
      return () => {
        if (!active) return;
        active = false;
        remove();
        listeners -= 1;
        if (listeners === 0) void Promise.resolve(ipc.invoke(unsubscribeChannel)).catch(() => undefined);
      };
    };
  };

  return Object.freeze({
    platform: () => ipc.invoke(IPC_CHANNELS.platform) as Promise<PlatformMetadata>,
    pickDirectory: (request: DirectoryPickerRequest = {}) =>
      ipc.invoke(IPC_CHANNELS.pickDirectory, request) as Promise<{ canceled: boolean; path?: string }>,
    pickFile: (request: FilePickerRequest = {}) =>
      ipc.invoke(IPC_CHANNELS.pickFile, request) as Promise<{ canceled: boolean; path?: string }>,
    settings: Object.freeze({
      apply: (request: SettingsApplyRequest) =>
        ipc.invoke(IPC_CHANNELS.settingsApply, request) as Promise<SettingsApplyResult>,
      probe: (request: ProbeRequest) => ipc.invoke(IPC_CHANNELS.settingsProbe, request) as Promise<ProbeResult>,
      onProgress: (listener: (event: ProgressEvent) => void) =>
        subscribe(IPC_CHANNELS.settingsProgress, listener),
    }),
    lifecycle: Object.freeze({
      status: () => ipc.invoke(IPC_CHANNELS.lifecycleStatus) as Promise<LifecycleStatus>,
      onStatus: (listener: (status: LifecycleStatus) => void) =>
        subscribe(IPC_CHANNELS.lifecycleChanged, listener),
    }),
    updates: Object.freeze({
      getState: () => ipc.invoke(IPC_CHANNELS.updatesState) as Promise<UpdateState>,
      check: () => ipc.invoke(IPC_CHANNELS.updatesCheck) as Promise<UpdateState>,
      download: () => ipc.invoke(IPC_CHANNELS.updatesDownload) as Promise<UpdateState>,
      install: () => ipc.invoke(IPC_CHANNELS.updatesInstall) as Promise<UpdateInstallResult>,
      onState: (listener: (state: UpdateState) => void) =>
        subscribe(IPC_CHANNELS.updatesChanged, listener),
    }),
    preferences: Object.freeze({
      get: () => ipc.invoke(IPC_CHANNELS.preferencesGet) as Promise<DesktopPreferences>,
      set: (patch: DesktopPreferencesPatch) => ipc.invoke(IPC_CHANNELS.preferencesSet, patch) as Promise<DesktopPreferences>,
    }),
    onDeepLink: buffered<DeepLink>(IPC_CHANNELS.deepLinkReceived, IPC_CHANNELS.deepLinkSubscribe, IPC_CHANNELS.deepLinkUnsubscribe),
    onNavigate: buffered<NavigateRequest>(IPC_CHANNELS.navigateRequested, IPC_CHANNELS.navigateSubscribe, IPC_CHANNELS.navigateUnsubscribe),
    savePageAsPdf: (request: SavePdfRequest = {}) =>
      ipc.invoke(IPC_CHANNELS.savePageAsPdf, request) as Promise<SavePdfResult>,
  });
}

contextBridge.exposeInMainWorld("bento", createBentoBridge(ipcRenderer));

declare global {
  interface Window {
    bento: BentoDesktopBridge;
  }
}
