export type MainLanguage = "es" | "en";

export type AttentionCopyKind = "upload_failed" | "sync_error" | "flood_wait" | "recovery_kit" | "inbox_failed" | "generic";

export interface MainStrings {
  language: MainLanguage;
  locale: string;
  tray: {
    upToDate: string;
    uploading(files: number, etaSeconds: number | null): string;
    downloading(files: number, etaSeconds: number | null): string;
    syncing: string;
    paused: string;
    offline: string;
    attention: string;
    starting: string;
    stopping: string;
    recovery: string;
    neutral: string;
    tooltip(status: string): string;
  };
  menu: {
    open: string;
    pauseBackup: string;
    resumeBackup: string;
    restartToUpdate: string;
    installUpdate: string;
    quit: string;
  };
  /** Application menu (packaged builds); other entries use Electron's localized role labels. */
  appMenu: {
    view: string;
  };
  notifications: {
    backgroundTitle: string;
    backgroundBody(platform: NodeJS.Platform): string;
    attentionTitle(kind: AttentionCopyKind, params: { waitMinutes?: number }): string;
    attentionBody: string;
    attentionSummary(count: number): string;
    filesAdded(count: number): string;
    filesFailed(count: number): string;
    filesNoneAdded: string;
  };
  pdf: {
    dialogTitle: string;
    defaultFileName: string;
    filterName: string;
  };
}

/** Main cannot use the renderer dictionary, so it keeps this small typed table. */
export function selectLanguage(locales: readonly string[]): MainLanguage {
  const first = locales.find((locale) => typeof locale === "string" && locale.length > 0);
  return first?.toLowerCase().startsWith("en") ? "en" : "es";
}

const LOCALE_TAG = /^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{1,8}){0,4}$/u;

export function normalizeLocale(locales: readonly string[], language: MainLanguage): string {
  const candidate = locales.find((locale) => typeof locale === "string" && LOCALE_TAG.test(locale));
  return candidate ? candidate.replace(/_/gu, "-").slice(0, 35) : language;
}

export function createStrings(locales: readonly string[]): MainStrings {
  const language = selectLanguage(locales);
  const locale = normalizeLocale(locales, language);
  return language === "en" ? english(locale) : spanish(locale);
}

function formatCount(locale: string, value: number): string {
  try {
    return new Intl.NumberFormat(locale).format(value);
  } catch {
    return String(value);
  }
}

function eta(seconds: number | null, lessThanMinute: string): string | null {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < 60) return lessThanMinute;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.round(minutes / 60)} h`;
}

function spanish(locale: string): MainStrings {
  const count = (value: number) => formatCount(locale, value);
  const files = (value: number) => (value === 1 ? "1 archivo" : `${count(value)} archivos`);
  const withEta = (base: string, seconds: number | null) => {
    const remaining = eta(seconds, "menos de 1 min");
    return remaining ? `${base} · ${remaining}` : base;
  };
  return {
    language: "es",
    locale,
    tray: {
      upToDate: "Todo al día",
      uploading: (value, seconds) => withEta(`Subiendo ${files(value)}`, seconds),
      downloading: (value, seconds) => withEta(`Descargando ${files(value)}`, seconds),
      syncing: "Sincronizando…",
      paused: "Respaldo en pausa",
      offline: "Sin conexión — se reanudará solo",
      attention: "Bento necesita tu atención",
      starting: "Iniciando…",
      stopping: "Cerrando…",
      recovery: "Bento necesita reiniciarse",
      neutral: "Bento está abierto",
      tooltip: (status) => `Bento — ${status}`,
    },
    menu: {
      open: "Abrir Bento",
      pauseBackup: "Pausar respaldo",
      resumeBackup: "Reanudar respaldo",
      restartToUpdate: "Reiniciar para actualizar",
      installUpdate: "Instalar actualización…",
      quit: "Salir",
    },
    appMenu: {
      view: "Ver",
    },
    notifications: {
      backgroundTitle: "Bento sigue funcionando en segundo plano",
      backgroundBody: (platform) => platform === "darwin"
        ? "Lo encuentras en la barra de menús. Elige «Salir» para cerrarlo."
        : "Lo encuentras en la bandeja del sistema. Elige «Salir» para cerrarlo.",
      attentionTitle: (kind, params) => {
        switch (kind) {
          case "upload_failed": return "No se pudo subir un archivo";
          case "sync_error": return "La sincronización necesita atención";
          case "flood_wait": return params.waitMinutes ? `Telegram pidió esperar ${count(params.waitMinutes)} min` : "Telegram pidió esperar un momento";
          case "recovery_kit": return "Guarda tu kit de recuperación";
          case "inbox_failed": return "No se pudo importar algo de tu Bandeja";
          default: return "Bento necesita tu atención";
        }
      },
      attentionBody: "Abre Bento para revisarlo.",
      attentionSummary: (value) => `Bento tiene ${count(value)} avisos para ti`,
      filesAdded: (value) => (value === 1 ? "1 archivo añadido a Bento" : `${count(value)} archivos añadidos a Bento`),
      filesFailed: (value) => (value === 1 ? "1 archivo no se pudo añadir." : `${count(value)} archivos no se pudieron añadir.`),
      filesNoneAdded: "No se pudieron añadir los archivos",
    },
    pdf: {
      dialogTitle: "Guardar kit de recuperación",
      defaultFileName: "Kit de recuperación de Bento.pdf",
      filterName: "Documento PDF",
    },
  };
}

function english(locale: string): MainStrings {
  const count = (value: number) => formatCount(locale, value);
  const files = (value: number) => (value === 1 ? "1 file" : `${count(value)} files`);
  const withEta = (base: string, seconds: number | null) => {
    const remaining = eta(seconds, "less than 1 min");
    return remaining ? `${base} · ${remaining}` : base;
  };
  return {
    language: "en",
    locale,
    tray: {
      upToDate: "Everything is up to date",
      uploading: (value, seconds) => withEta(`Uploading ${files(value)}`, seconds),
      downloading: (value, seconds) => withEta(`Downloading ${files(value)}`, seconds),
      syncing: "Syncing…",
      paused: "Backup paused",
      offline: "Offline — will resume on its own",
      attention: "Bento needs your attention",
      starting: "Starting…",
      stopping: "Closing…",
      recovery: "Bento needs to restart",
      neutral: "Bento is open",
      tooltip: (status) => `Bento — ${status}`,
    },
    menu: {
      open: "Open Bento",
      pauseBackup: "Pause backup",
      resumeBackup: "Resume backup",
      restartToUpdate: "Restart to update",
      installUpdate: "Install update…",
      quit: "Quit",
    },
    appMenu: {
      view: "View",
    },
    notifications: {
      backgroundTitle: "Bento keeps running in the background",
      backgroundBody: (platform) => platform === "darwin"
        ? "You can find it in the menu bar. Choose “Quit” to close it."
        : "You can find it in the system tray. Choose “Quit” to close it.",
      attentionTitle: (kind, params) => {
        switch (kind) {
          case "upload_failed": return "A file could not be uploaded";
          case "sync_error": return "Sync needs your attention";
          case "flood_wait": return params.waitMinutes ? `Telegram asked to wait ${count(params.waitMinutes)} min` : "Telegram asked to wait a moment";
          case "recovery_kit": return "Save your recovery kit";
          case "inbox_failed": return "Something in your Inbox could not be imported";
          default: return "Bento needs your attention";
        }
      },
      attentionBody: "Open Bento to review it.",
      attentionSummary: (value) => `Bento has ${count(value)} notices for you`,
      filesAdded: (value) => (value === 1 ? "1 file added to Bento" : `${count(value)} files added to Bento`),
      filesFailed: (value) => (value === 1 ? "1 file could not be added." : `${count(value)} files could not be added.`),
      filesNoneAdded: "The files could not be added",
    },
    pdf: {
      dialogTitle: "Save recovery kit",
      defaultFileName: "Bento recovery kit.pdf",
      filterName: "PDF document",
    },
  };
}
