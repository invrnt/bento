import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import {
  exportSettings,
  getSettings,
  getSettingsSchema,
  getSettingsValues,
  patchSettings,
  previewSettingsImport,
  reclaimStorage,
  validateSettings,
} from "../../api/settings";
import type {
  FieldIssue,
  PublicSettings,
  RestartPlan,
  SettingsImportPreview,
  SettingsSchema,
  SettingsValidation,
  SettingsValues,
  StorageReclaimResult,
} from "../../api/settings";
import { desktopBridge, detectDesktopPlatform } from "../../api/settingsDesktop";
import type { ApplyProgress, DesktopPlatform } from "../../api/settingsDesktop";

/** Probe kinds the desktop bridge accepts (the Bot API connection test is gone). */
export const desktopProbeKinds: ReadonlySet<string> = new Set(["writable-directory", "model-file", "ffmpeg", "ocr"]);

export type ApplyOutcome = { restartPlan: RestartPlan | null; rolledBack: boolean };

export type SettingsController = {
  applyOutcome: ApplyOutcome | null;
  applyProgress: ApplyProgress[];
  conflict: boolean;
  dataMigration: "copy" | "use-empty" | null;
  desktop: DesktopPlatform | null;
  dirty: boolean;
  dismissImport: () => void;
  discard: () => void;
  draft: Record<string, unknown>;
  error: Error | null;
  exportSafe: () => Promise<void>;
  fieldErrors: Record<string, FieldIssue[]>;
  importPreview: SettingsImportPreview | null;
  importPreviewFromFile: (file: File) => Promise<void>;
  importValues: () => void;
  isApplying: boolean;
  isLoading: boolean;
  isReclaiming: boolean;
  isValidating: boolean;
  pickPath: (key: string, file?: boolean) => Promise<void>;
  probe: (key: string, kind: string) => Promise<void>;
  publicSettings: PublicSettings | null;
  reclaim: () => Promise<void>;
  reclaimError: Error | null;
  reclaimResult: StorageReclaimResult | null;
  refresh: () => Promise<void>;
  resetGroup: (group: string) => void;
  save: () => Promise<void>;
  schema: SettingsSchema | null;
  setDataMigration: (choice: "copy" | "use-empty" | null) => void;
  setValue: (key: string, value: unknown) => void;
  validate: (runProbes?: boolean) => Promise<SettingsValidation | null>;
  validation: SettingsValidation | null;
  values: SettingsValues | null;
};

export function useSettingsController(client: ApiClient = apiClient): SettingsController {
  const [schema, setSchema] = useState<SettingsSchema | null>(null);
  const [values, setValues] = useState<SettingsValues | null>(null);
  const [publicSettings, setPublicSettings] = useState<PublicSettings | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [desktop, setDesktop] = useState<DesktopPlatform | null>(null);
  const [dataMigration, setDataMigration] = useState<"copy" | "use-empty" | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [validation, setValidation] = useState<SettingsValidation | null>(null);
  const [conflict, setConflict] = useState(false);
  const [applyProgress, setApplyProgress] = useState<ApplyProgress[]>([]);
  const [applyOutcome, setApplyOutcome] = useState<ApplyOutcome | null>(null);
  const [importPreview, setImportPreview] = useState<SettingsImportPreview | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isApplying, setIsApplying] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [isReclaiming, setIsReclaiming] = useState(false);
  const [reclaimError, setReclaimError] = useState<Error | null>(null);
  const [reclaimResult, setReclaimResult] = useState<StorageReclaimResult | null>(null);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [nextSchema, nextValues, nextPublic, nextDesktop] = await Promise.all([
        getSettingsSchema(client),
        getSettingsValues(client),
        getSettings(client),
        detectDesktopPlatform(),
      ]);
      setSchema(nextSchema);
      setValues(nextValues);
      setPublicSettings(nextPublic);
      setDraft(snapshotDraft(nextValues));
      setValidation(null);
      setConflict(false);
      setDataMigration(null);
      setDesktop(nextDesktop);
    } catch (caught) {
      setError(asError(caught));
    } finally {
      setIsLoading(false);
    }
  }, [client]);

  useEffect(() => { void refresh(); }, [refresh]);

  const dirty = useMemo(() => {
    if (!values) return false;
    return Object.entries(draft).some(([key, value]) => !sameValue(value, values.values[key]?.value));
  }, [draft, values]);

  const discard = useCallback(() => {
    if (!values) return;
    setDraft(snapshotDraft(values));
    setValidation(null);
    setApplyOutcome(null);
    setConflict(false);
    setDataMigration(null);
  }, [values]);

  const setValue = useCallback((key: string, value: unknown) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setValidation((current) => current ? { ...current, errors: current.errors.filter((issue) => issue.key !== key) } : null);
  }, []);

  const changedValues = useCallback(() => {
    if (!values) return {};
    return Object.fromEntries(Object.entries(draft).filter(([key, value]) => !sameValue(value, values.values[key]?.value)));
  }, [draft, values]);

  const validate = useCallback(async (runProbes = false) => {
    setIsValidating(true);
    setConflict(false);
    try {
      const result = await validateSettings({ run_probes: runProbes, values: changedValues() }, client);
      setValidation(result);
      return result;
    } catch (caught) {
      setError(asError(caught));
      return null;
    } finally {
      setIsValidating(false);
    }
  }, [changedValues, client]);

  const save = useCallback(async () => {
    if (!values || !dirty) return;
    setIsApplying(true);
    setApplyProgress([]);
    setApplyOutcome(null);
    setConflict(false);
    setError(null);
    const bridge = desktopBridge();
    let unsubscribe: () => void = () => undefined;
    try {
      if (bridge) {
        unsubscribe = bridge.settings.onProgress((event) => setApplyProgress((current) => [...current, event]));
        // Desktop secrets are gone: Telegram sessions and keys live in the backend key store.
        const result = await bridge.settings.apply({ dataMigration: dataMigration ?? undefined, revision: values.revision, runProbes: true, secrets: {}, values: changedValues() });
        if (!result.ok) {
          const errors = result.errors ?? [];
          setValidation(emptyValidation(errors));
          setApplyOutcome({ restartPlan: normalizeRestartPlan(result.restartPlan), rolledBack: Boolean(result.rolledBack) });
          return;
        }
        setApplyOutcome({ restartPlan: normalizeRestartPlan(result.restartPlan), rolledBack: false });
      } else {
        const checked = await validateSettings({ run_probes: true, values: changedValues() }, client);
        setValidation(checked);
        if (!checked.valid) return;
        const result = await patchSettings({ revision: values.revision, values: changedValues() }, client);
        setApplyOutcome({ restartPlan: result.restart_plan, rolledBack: false });
      }
      await refresh();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) setConflict(true);
      else setError(asError(caught));
    } finally {
      unsubscribe();
      setIsApplying(false);
    }
  }, [changedValues, client, dataMigration, dirty, refresh, values]);

  const resetGroup = useCallback((group: string) => {
    if (!schema) return;
    setDraft((current) => ({
      ...current,
      ...Object.fromEntries(schema.fields.filter((field) => field.group === group && field.editable && !field.locked && !field.secret).map((field) => [field.key, field.default])),
    }));
  }, [schema]);

  const pickPath = useCallback(async (key: string, file = false) => {
    const bridge = desktopBridge();
    if (!bridge) return;
    const result = file
      ? await bridge.pickFile({ filters: [{ extensions: ["gguf"], name: "GGUF" }] })
      : await bridge.pickDirectory();
    if (!result.canceled && result.path) setValue(key, result.path);
  }, [setValue]);

  const probe = useCallback(async (key: string, kind: string) => {
    const bridge = desktopBridge();
    const normalized = kind.replaceAll("_", "-");
    if (!bridge || !desktopProbeKinds.has(normalized)) return;
    const path = typeof draft[key] === "string" ? draft[key] as string : undefined;
    const result = await bridge.settings.probe({ kind: normalized as "ffmpeg" | "model-file" | "ocr" | "writable-directory", path });
    setValidation((current) => ({
      ...(current ?? emptyValidation([])),
      probes: [...(current?.probes.filter((item) => item.key !== key) ?? []), { key, message: null, status: result.status }],
      valid: result.status === "ok" && (current?.valid ?? true),
    }));
  }, [draft]);

  const importPreviewFromFile = useCallback(async (file: File) => {
    const content = await file.text();
    setImportPreview(await previewSettingsImport(content, client));
  }, [client]);

  const importValues = useCallback(() => {
    const imported = importPreview?.values ?? Object.fromEntries((importPreview?.items ?? []).filter((item) => !item.secret && !item.locked && item.status !== "invalid" && "value" in item).map((item) => [item.key, item.value]));
    if (imported && typeof imported === "object") setDraft((current) => ({ ...current, ...imported }));
    setImportPreview(null);
  }, [importPreview]);

  const exportSafe = useCallback(async () => {
    const payload = await exportSettings(client);
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "bento-settings.json";
    link.click();
    URL.revokeObjectURL(url);
  }, [client]);

  const reclaim = useCallback(async () => {
    setIsReclaiming(true); setReclaimError(null); setReclaimResult(null);
    try { setReclaimResult(await reclaimStorage(client)); setPublicSettings(await getSettings(client)); }
    catch (caught) { setReclaimError(asError(caught)); }
    finally { setIsReclaiming(false); }
  }, [client]);

  const fieldErrors = useMemo(() => (validation?.errors ?? []).reduce<Record<string, FieldIssue[]>>((all, issue) => {
    all[issue.key] = [...(all[issue.key] ?? []), issue];
    return all;
  }, {}), [validation]);

  return { applyOutcome, applyProgress, conflict, dataMigration, desktop, dirty, discard, dismissImport: () => setImportPreview(null), draft, error, exportSafe, fieldErrors, importPreview, importPreviewFromFile, importValues, isApplying, isLoading, isReclaiming, isValidating, pickPath, probe, publicSettings, reclaim, reclaimError, reclaimResult, refresh, resetGroup, save, schema, setDataMigration, setValue, validate, validation, values };
}

function snapshotDraft(snapshot: SettingsValues): Record<string, unknown> {
  return Object.fromEntries(Object.entries(snapshot.values).filter(([, item]) => "value" in item).map(([key, item]) => [key, item.value]));
}
function sameValue(left: unknown, right: unknown) { return JSON.stringify(left) === JSON.stringify(right); }
function asError(caught: unknown) { return caught instanceof Error ? caught : new Error(String(caught)); }
function emptyValidation(errors: FieldIssue[]): SettingsValidation { return { errors, probes: [], restart_plan: { affected_keys: [], mode: "live", services: [] }, valid: false, warnings: [] }; }
function normalizeRestartPlan(plan: { affectedKeys?: string[]; affected_keys?: string[]; mode: string; services: string[] } | undefined): RestartPlan | null {
  if (!plan) return null;
  return { affected_keys: plan.affected_keys ?? plan.affectedKeys ?? [], mode: plan.mode as RestartPlan["mode"], services: plan.services };
}
