import { BrowserWindow, dialog, IpcMain, IpcMainInvokeEvent, OpenDialogOptions } from "electron";
import {
  BENTO_ORIGIN,
  DesktopPreferences,
  DesktopPreferencesPatch,
  IPC_CHANNELS,
  LifecycleStatus,
  PlatformMetadata,
  ProbeResult,
  ProgressEvent,
  SavePdfRequest,
  SavePdfResult,
  SettingsApplyResult,
  UpdateInstallResult,
  UpdateState,
} from "../shared/contracts";
import { RendererTarget } from "./renderer-events";
import { assertMainWindowFrame } from "./sender";
import {
  validateDirectoryPicker,
  validateFilePicker,
  validatePreferencesPatch,
  validateProbe,
  validateSafePath,
  validateSavePdfRequest,
  validateSettingsApply,
} from "./validation";

export interface IpcDependencies {
  ipcMain: IpcMain;
  window: () => BrowserWindow | null;
  platform: () => Promise<PlatformMetadata>;
  lifecycleStatus: () => LifecycleStatus;
  applySettings: (request: ReturnType<typeof validateSettingsApply>, progress: (event: ProgressEvent) => void) => Promise<SettingsApplyResult>;
  runProbe: (request: ReturnType<typeof validateProbe>) => Promise<ProbeResult>;
  updates: {
    state: UpdateState;
    check(): Promise<UpdateState>;
    download(): Promise<UpdateState>;
    install(): Promise<UpdateInstallResult>;
  };
  preferences: {
    get(): DesktopPreferences | Promise<DesktopPreferences>;
    set(patch: DesktopPreferencesPatch): Promise<DesktopPreferences>;
  };
  deepLinks: RendererSubscription;
  navigation: RendererSubscription;
  savePageAsPdf(event: IpcMainInvokeEvent, request: SavePdfRequest): Promise<SavePdfResult>;
}

export interface RendererSubscription {
  subscribe(target: RendererTarget): void;
  unsubscribe(target: RendererTarget): void;
}

const COMMAND_CHANNELS = [
  IPC_CHANNELS.platform,
  IPC_CHANNELS.lifecycleStatus,
  IPC_CHANNELS.pickDirectory,
  IPC_CHANNELS.pickFile,
  IPC_CHANNELS.settingsApply,
  IPC_CHANNELS.settingsProbe,
  IPC_CHANNELS.updatesState,
  IPC_CHANNELS.updatesCheck,
  IPC_CHANNELS.updatesDownload,
  IPC_CHANNELS.updatesInstall,
  IPC_CHANNELS.preferencesGet,
  IPC_CHANNELS.preferencesSet,
  IPC_CHANNELS.deepLinkSubscribe,
  IPC_CHANNELS.deepLinkUnsubscribe,
  IPC_CHANNELS.navigateSubscribe,
  IPC_CHANNELS.navigateUnsubscribe,
  IPC_CHANNELS.savePageAsPdf,
] as const;

function assertTrustedSender(event: IpcMainInvokeEvent): void {
  const url = event.senderFrame?.url ?? event.sender.getURL();
  const parsed = new URL(url);
  if (parsed.protocol !== "bento:" || parsed.host !== "app") throw new Error("Untrusted IPC sender");
}

export function registerIpcHandlers(dependencies: IpcDependencies): () => void {
  const handle = (channel: string, listener: (event: IpcMainInvokeEvent, payload: unknown) => unknown): void => {
    dependencies.ipcMain.handle(channel, async (event, payload) => {
      assertTrustedSender(event);
      return listener(event, payload);
    });
  };

  handle(IPC_CHANNELS.platform, () => dependencies.platform());
  handle(IPC_CHANNELS.lifecycleStatus, () => dependencies.lifecycleStatus());
  handle(IPC_CHANNELS.pickDirectory, async (_event, payload) => {
    const request = validateDirectoryPicker(payload);
    const options: OpenDialogOptions = {
      title: request.title,
      properties: ["openDirectory", "createDirectory", "promptToCreate"],
    };
    const owner = dependencies.window();
    const result = owner ? await dialog.showOpenDialog(owner, options) : await dialog.showOpenDialog(options);
    if (result.canceled || result.filePaths.length !== 1) return { canceled: true };
    return { canceled: false, path: validateSafePath(result.filePaths[0]) };
  });
  handle(IPC_CHANNELS.pickFile, async (_event, payload) => {
    const request = validateFilePicker(payload);
    const options: OpenDialogOptions = {
      title: request.title,
      filters: request.filters,
      properties: ["openFile"],
    };
    const owner = dependencies.window();
    const result = owner ? await dialog.showOpenDialog(owner, options) : await dialog.showOpenDialog(options);
    if (result.canceled || result.filePaths.length !== 1) return { canceled: true };
    return { canceled: false, path: validateSafePath(result.filePaths[0]) };
  });
  handle(IPC_CHANNELS.settingsApply, async (_event, payload) => {
    const request = validateSettingsApply(payload);
    return dependencies.applySettings(request, (progress) => {
      dependencies.window()?.webContents.send(IPC_CHANNELS.settingsProgress, progress);
    });
  });
  handle(IPC_CHANNELS.settingsProbe, (_event, payload) => dependencies.runProbe(validateProbe(payload)));
  handle(IPC_CHANNELS.updatesState, (_event, payload) => { assertNoPayload(payload); return dependencies.updates.state; });
  handle(IPC_CHANNELS.updatesCheck, (_event, payload) => { assertNoPayload(payload); return dependencies.updates.check(); });
  handle(IPC_CHANNELS.updatesDownload, (_event, payload) => { assertNoPayload(payload); return dependencies.updates.download(); });
  handle(IPC_CHANNELS.updatesInstall, (_event, payload) => { assertNoPayload(payload); return dependencies.updates.install(); });
  handle(IPC_CHANNELS.preferencesGet, (_event, payload) => { assertNoPayload(payload); return dependencies.preferences.get(); });
  handle(IPC_CHANNELS.preferencesSet, (_event, payload) => dependencies.preferences.set(validatePreferencesPatch(payload)));
  const subscription = (stream: RendererSubscription, subscribe: boolean) => (event: IpcMainInvokeEvent, payload: unknown): void => {
    assertNoPayload(payload);
    assertMainWindowFrame(event, dependencies.window());
    if (subscribe) stream.subscribe(event.sender);
    else stream.unsubscribe(event.sender);
  };
  handle(IPC_CHANNELS.deepLinkSubscribe, subscription(dependencies.deepLinks, true));
  handle(IPC_CHANNELS.deepLinkUnsubscribe, subscription(dependencies.deepLinks, false));
  handle(IPC_CHANNELS.navigateSubscribe, subscription(dependencies.navigation, true));
  handle(IPC_CHANNELS.navigateUnsubscribe, subscription(dependencies.navigation, false));
  handle(IPC_CHANNELS.savePageAsPdf, (event, payload) => dependencies.savePageAsPdf(event, validateSavePdfRequest(payload)));

  return () => {
    for (const channel of COMMAND_CHANNELS) dependencies.ipcMain.removeHandler(channel);
  };
}

function assertNoPayload(payload: unknown): void {
  if (payload !== undefined) throw new TypeError("This IPC command does not accept a payload");
}

export { IPC_CHANNELS, BENTO_ORIGIN };
