import path from "node:path";
import { LifecycleState, UpdateState } from "../shared/contracts";
import { ActivityState } from "./activity";
import { MainStrings } from "./i18n";

export type TrayIconState = "idle" | "syncing" | "paused" | "attention";
export const TRAY_ICON_STATES: readonly TrayIconState[] = ["idle", "syncing", "paused", "attention"];

export interface TrayModel {
  icon: TrayIconState;
  status: string;
  tooltip: string;
  backupAction: "pause" | "resume" | null;
  updateAction: "restart" | "install" | null;
}

export interface TrayInput {
  lifecycle: LifecycleState;
  activity: ActivityState;
  update: Pick<UpdateState, "status" | "installMode"> | null;
}

const MAX_TOOLTIP = 127;

/** Pure mapping from lifecycle + activity payloads to what the tray shows. */
export function trayModel(input: TrayInput, strings: MainStrings): TrayModel {
  const { activity } = input.activity;
  let icon: TrayIconState = "idle";
  let status = strings.tray.neutral;
  if (input.lifecycle === "starting" || input.lifecycle === "restarting") {
    status = strings.tray.starting;
  } else if (input.lifecycle === "stopping") {
    status = strings.tray.stopping;
  } else if (input.lifecycle === "recovery") {
    icon = "attention";
    status = strings.tray.recovery;
  } else if (activity) {
    switch (activity.summary) {
      case "up_to_date":
        status = strings.tray.upToDate;
        break;
      case "uploading":
        icon = "syncing";
        status = strings.tray.uploading(Math.max(1, activity.uploads.active + activity.uploads.queued), activity.uploads.etaSeconds);
        break;
      case "downloading":
        icon = "syncing";
        status = strings.tray.downloading(Math.max(1, activity.downloads.active + activity.downloads.queued), activity.downloads.etaSeconds);
        break;
      case "syncing":
        icon = "syncing";
        status = strings.tray.syncing;
        break;
      case "paused":
        icon = "paused";
        status = strings.tray.paused;
        break;
      case "offline":
        icon = "paused";
        status = strings.tray.offline;
        break;
      case "attention":
        icon = "attention";
        status = strings.tray.attention;
        break;
    }
  }
  const policy = input.activity.policy;
  const backupAction = input.lifecycle === "ready" && policy ? (policy.paused ? "resume" : "pause") : null;
  const updateAction = input.update?.status === "downloaded"
    ? input.update.installMode === "automatic" ? "restart" : input.update.installMode === "manual" ? "install" : null
    : null;
  const tooltip = strings.tray.tooltip(status);
  return {
    icon,
    status,
    tooltip: tooltip.length > MAX_TOOLTIP ? `${tooltip.slice(0, MAX_TOOLTIP - 1)}…` : tooltip,
    backupAction,
    updateAction,
  };
}

/** Icon file for a state: macOS template images, PNG elsewhere (Linux uses a larger bitmap). */
export function trayIconPath(root: string, platform: NodeJS.Platform, state: TrayIconState): string {
  if (platform === "darwin") return path.join(root, `tray-${state}Template.png`);
  if (platform === "linux") return path.join(root, `tray-${state}-linux.png`);
  return path.join(root, `tray-${state}.png`);
}

export interface TrayMenuItem {
  label?: string;
  type?: "normal" | "separator";
  enabled?: boolean;
  click?: () => void;
}

export interface TrayLike {
  setImage(image: unknown): void;
  setToolTip(toolTip: string): void;
  setContextMenu(menu: unknown): void;
  on(event: "click", listener: () => void): unknown;
  destroy(): void;
}

export interface TrayActions {
  open(): void;
  setBackupPaused(paused: boolean): void;
  installUpdate(): void;
  quit(): void;
}

export interface TrayControllerOptions {
  platform: NodeJS.Platform;
  iconRoot: string;
  strings: MainStrings;
  createTray: (image: unknown) => TrayLike;
  loadImage: (filePath: string) => unknown;
  buildMenu: (template: TrayMenuItem[]) => unknown;
  actions: TrayActions;
}

export function trayMenuTemplate(model: TrayModel, strings: MainStrings, actions: TrayActions): TrayMenuItem[] {
  const items: TrayMenuItem[] = [
    { label: model.status, enabled: false },
    { type: "separator" },
    { label: strings.menu.open, click: () => actions.open() },
  ];
  if (model.backupAction === "pause") items.push({ label: strings.menu.pauseBackup, click: () => actions.setBackupPaused(true) });
  if (model.backupAction === "resume") items.push({ label: strings.menu.resumeBackup, click: () => actions.setBackupPaused(false) });
  if (model.updateAction) {
    items.push({
      label: model.updateAction === "restart" ? strings.menu.restartToUpdate : strings.menu.installUpdate,
      click: () => actions.installUpdate(),
    });
  }
  items.push({ type: "separator" }, { label: strings.menu.quit, click: () => actions.quit() });
  return items;
}

export class TrayController {
  private tray: TrayLike | null = null;
  private rendered: string | null = null;
  private readonly images = new Map<TrayIconState, unknown>();

  constructor(private readonly options: TrayControllerOptions) {}

  render(model: TrayModel): void {
    const key = JSON.stringify(model);
    if (key === this.rendered) return;
    const image = this.image(model.icon);
    if (!this.tray) {
      this.tray = this.options.createTray(image);
      // macOS opens the context menu on click; Windows/Linux activation opens the window.
      if (this.options.platform !== "darwin") this.tray.on("click", () => this.options.actions.open());
    } else {
      this.tray.setImage(image);
    }
    this.tray.setToolTip(model.tooltip);
    // Linux requires setting the menu again after any change.
    this.tray.setContextMenu(this.options.buildMenu(trayMenuTemplate(model, this.options.strings, this.options.actions)));
    this.rendered = key;
  }

  destroy(): void {
    this.tray?.destroy();
    this.tray = null;
    this.rendered = null;
  }

  private image(state: TrayIconState): unknown {
    let image = this.images.get(state);
    if (!image) {
      image = this.options.loadImage(trayIconPath(this.options.iconRoot, this.options.platform, state));
      this.images.set(state, image);
    }
    return image;
  }
}
