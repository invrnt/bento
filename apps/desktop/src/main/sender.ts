export interface SenderFrameLike {
  readonly processId: number;
  readonly routingId: number;
  readonly parent: unknown;
}

export interface SenderEventLike {
  readonly sender: unknown;
  readonly senderFrame: SenderFrameLike | null;
}

export interface MainWindowLike<Contents extends { readonly mainFrame: SenderFrameLike }> {
  readonly webContents: Contents;
  isDestroyed(): boolean;
}

export class UntrustedSenderError extends Error {
  constructor() { super("This command is only available to the main window"); }
}

/** Requires the IPC message to come from the main window's top-level frame (never a subframe or another window). */
export function assertMainWindowFrame<Contents extends { readonly mainFrame: SenderFrameLike }, Window extends MainWindowLike<Contents>>(
  event: SenderEventLike,
  window: Window | null,
): Window {
  if (!window || window.isDestroyed() || event.sender !== window.webContents) throw new UntrustedSenderError();
  const frame = event.senderFrame;
  const main = window.webContents.mainFrame;
  if (!frame || frame.parent !== null || frame.processId !== main.processId || frame.routingId !== main.routingId) {
    throw new UntrustedSenderError();
  }
  return window;
}
