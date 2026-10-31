export interface DockLike {
  hide(): void;
  show(): Promise<void> | void;
}

export interface LifecycleWindow {
  on(event: "close", listener: (event: { preventDefault(): void }) => void): unknown;
  show(): void;
  hide(): void;
  focus(): void;
  restore(): void;
  isMinimized(): boolean;
  isDestroyed(): boolean;
}

export interface WindowLifecycleOptions {
  platform: NodeJS.Platform;
  dock?: DockLike;
  keepRunningInBackground: () => boolean;
  isQuitting: () => boolean;
  onHiddenToBackground: () => void;
}

/**
 * Closing the window hides it while Bento keeps running in the tray. Quitting (tray "Salir",
 * OS shutdown, updates) is never blocked. On macOS the dock icon is hidden only while the window is closed.
 */
export class WindowLifecycle {
  constructor(private readonly options: WindowLifecycleOptions) {}

  attach(window: LifecycleWindow): void {
    window.on("close", (event) => {
      if (this.options.isQuitting() || !this.options.keepRunningInBackground()) return;
      event.preventDefault();
      this.hide(window);
      this.options.onHiddenToBackground();
    });
  }

  show(window: LifecycleWindow): void {
    if (window.isDestroyed()) return;
    if (this.options.platform === "darwin") void this.options.dock?.show();
    if (window.isMinimized()) window.restore();
    window.show();
    window.focus();
  }

  hide(window: LifecycleWindow): void {
    if (window.isDestroyed()) return;
    window.hide();
    if (this.options.platform === "darwin") this.options.dock?.hide();
  }
}
