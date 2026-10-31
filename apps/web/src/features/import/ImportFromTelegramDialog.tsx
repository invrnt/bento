import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronLeft, FileText, Film, Image, Import, Music, RotateCw } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { importFromTelegram } from "../../api/telegram";
import type { TelegramChat, TelegramMediaItem } from "../../api/telegram";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { CheckboxBox } from "../../components/Checkbox";
import { Dialog } from "../../components/Dialog";
import { SegmentedControl } from "../../components/SegmentedControl";
import { LoadingState } from "../../components/States";
import { showToast } from "../../components/Toast";
import { t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import { formatBytes, formatDay, formatMessage, formatPlural } from "../../lib/format";
import { navigateTo } from "../../lib/navigation";
import { appRoutes } from "../activity/activityModel";
import { activityStore } from "../activity/activityStore";
import { chatTitle, TelegramChatPicker } from "../share/TelegramChatPicker";
import { telegramErrorMessage } from "../share/telegramErrors";
import type { ListChats } from "../share/useTelegramChats";
import { useTelegramMedia } from "./useTelegramMedia";
import type { ListMedia, MediaFilter } from "./useTelegramMedia";

export type ImportApi = {
  importMedia?: (request: { all?: boolean; chat_id: number; message_ids?: number[] }) => Promise<{ job_id: string; queued: number }>;
  listChats?: ListChats;
  listMedia?: ListMedia;
};

export type ImportFromTelegramDialogProps = {
  api?: ImportApi;
  onClose: () => void;
  onNavigate?: (href: string) => void;
  open: boolean;
};

const kindStyles: Record<TelegramMediaItem["kind"], { icon: LucideIcon; label: MessageKey; tile: string }> = {
  audio: { icon: Music, label: "import.kind.audio", tile: "bg-kind-audio-soft text-kind-audio" },
  document: { icon: FileText, label: "import.kind.document", tile: "bg-kind-doc-soft text-kind-doc" },
  photo: { icon: Image, label: "import.kind.photo", tile: "bg-kind-image-soft text-kind-image" },
  video: { icon: Film, label: "import.kind.video", tile: "bg-kind-video-soft text-kind-video" },
};

/** Two steps: choose a chat (Saved Messages first), then pick media and import in the background. */
export function ImportFromTelegramDialog({ api, onClose, onNavigate = navigateTo, open }: ImportFromTelegramDialogProps) {
  return open ? <ImportDialogBody api={api} onClose={onClose} onNavigate={onNavigate} /> : null;
}

function ImportDialogBody({
  api = {},
  onClose,
  onNavigate,
}: {
  api?: ImportApi;
  onClose: () => void;
  onNavigate: (href: string) => void;
}) {
  const importMedia = api.importMedia ?? importFromTelegram;
  const [step, setStep] = useState<"chat" | "media">("chat");
  const [chat, setChat] = useState<TelegramChat | null>(null);
  const [kind, setKind] = useState<MediaFilter>("all");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [wholeChat, setWholeChat] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const media = useTelegramMedia(step === "media" && chat ? chat.id : null, kind, api.listMedia);
  const selectedCount = useMemo(() => media.items.filter((item) => selected.has(item.message_id)).length, [media.items, selected]);
  const allLoadedSelected = media.items.length > 0 && selectedCount === media.items.length;
  const canSelectWholeChat = allLoadedSelected && Boolean(media.nextCursor) && kind === "all";

  function changeKind(next: MediaFilter) {
    setKind(next);
    setSelected(new Set());
    setWholeChat(false);
  }

  function toggle(item: TelegramMediaItem) {
    setWholeChat(false);
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(item.message_id)) {
        next.delete(item.message_id);
      } else {
        next.add(item.message_id);
      }
      return next;
    });
  }

  function toggleAll() {
    setWholeChat(false);
    setSelected(allLoadedSelected ? new Set() : new Set(media.items.map((item) => item.message_id)));
  }

  function toggleWholeChat() {
    if (wholeChat) {
      setSelected(new Set());
    }
    setWholeChat(!wholeChat);
  }

  async function submit() {
    if (!chat || (!wholeChat && selectedCount === 0)) {
      return;
    }

    setSubmitting(true);
    setError(null);
    const messageIds = media.items.filter((item) => selected.has(item.message_id)).map((item) => item.message_id);
    try {
      const result = await importMedia(wholeChat ? { all: true, chat_id: chat.id } : { chat_id: chat.id, message_ids: messageIds });
      onClose();
      void activityStore.refresh();
      showToast({
        action: { label: t("import.viewProgress"), onAction: () => onNavigate(appRoutes.activity) },
        icon: <Import />,
        message: formatPlural(result.queued ?? messageIds.length, { one: "import.started.one", other: "import.started.other" }),
        tone: "success",
      });
    } catch (caught) {
      setError(telegramErrorMessage(caught));
      setSubmitting(false);
    }
  }

  const submitLabel = wholeChat
    ? t("import.submitAll")
    : formatPlural(Math.max(1, selectedCount), { one: "import.submit.one", other: "import.submit.other" });

  return (
    <Dialog
      actions={
        <>
          <Button onClick={onClose} variant="ghost">
            {t("import.cancel")}
          </Button>
          {step === "chat" ? (
            <Button disabled={!chat} onClick={() => setStep("media")} variant="primary">
              {t("import.continue")}
            </Button>
          ) : (
            <Button
              disabled={!wholeChat && selectedCount === 0}
              leadingIcon={<Import />}
              loading={submitting}
              onClick={() => void submit()}
              variant="primary"
            >
              {submitLabel}
            </Button>
          )}
        </>
      }
      description={step === "media" && chat ? formatMessage("import.fromChat", { chat: chatTitle(chat) }) : t("import.chooseChat")}
      icon={<Import />}
      onOpenChange={(isOpen) => {
        if (!isOpen && !submitting) {
          onClose();
        }
      }}
      open
      size="lg"
      title={t("import.title")}
    >
      {step === "chat" ? (
        <TelegramChatPicker listChats={api.listChats} onSelect={setChat} selectedId={chat?.id ?? null} />
      ) : (
        <div className="grid gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button
              className="-ml-2"
              leadingIcon={<ChevronLeft />}
              onClick={() => {
                setStep("chat");
                setSelected(new Set());
                setWholeChat(false);
              }}
              size="sm"
              variant="ghost"
            >
              {t("import.changeChat")}
            </Button>
            <SegmentedControl<MediaFilter>
              ariaLabel={t("import.filter.label")}
              onChange={changeKind}
              options={[
                { label: t("import.filter.all"), value: "all" },
                { label: t("import.filter.photo"), value: "photo" },
                { label: t("import.filter.video"), value: "video" },
                { label: t("import.filter.document"), value: "document" },
              ]}
              size="sm"
              value={kind}
            />
          </div>

          {media.status === "loading" ? <LoadingState className="min-h-56" label={t("import.media.loading")} /> : null}
          {media.status === "error" ? (
            <Callout
              action={
                <Button leadingIcon={<RotateCw />} onClick={media.retry} size="sm">
                  {t("common.retry")}
                </Button>
              }
              role="alert"
              tone="danger"
            >
              {t("import.media.error")} {telegramErrorMessage(media.error)}
            </Callout>
          ) : null}
          {media.status === "ready" && media.items.length === 0 ? (
            <p className="grid min-h-40 place-items-center rounded-lg border border-dashed border-line-strong/80 p-6 text-center text-sm text-ink-muted">
              {kind === "all" ? t("import.media.empty") : t("import.media.emptyFilter")}
            </p>
          ) : null}

          {media.status === "ready" && media.items.length > 0 ? (
            <>
              <SelectAllRow
                allSelected={allLoadedSelected || wholeChat}
                count={wholeChat ? null : selectedCount}
                onToggle={toggleAll}
                someSelected={!wholeChat && selectedCount > 0 && !allLoadedSelected}
              />
              {canSelectWholeChat || wholeChat ? (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-accent-soft px-3 py-2 text-sm text-ink" role="status">
                  <span>{wholeChat ? t("import.wholeChatSelected") : formatMessage("import.allVisibleSelected", { count: media.items.length })}</span>
                  <button
                    className="focus-ring rounded-xs font-medium text-accent-ink hover:underline"
                    onClick={toggleWholeChat}
                    type="button"
                  >
                    {wholeChat ? t("import.clearSelection") : t("import.selectWholeChat")}
                  </button>
                </div>
              ) : null}
              <div
                aria-label={t("import.media.label")}
                className="grid max-h-[22rem] grid-cols-2 gap-2 overflow-y-auto overscroll-contain p-0.5 sm:grid-cols-3"
                role="group"
              >
                {media.items.map((item) => (
                  <MediaTile item={item} key={item.message_id} onToggle={() => toggle(item)} selected={wholeChat || selected.has(item.message_id)} />
                ))}
              </div>
              {media.nextCursor ? (
                <div className="flex justify-center">
                  <Button loading={media.loadingMore} onClick={() => void media.loadMore()} size="sm" variant="ghost">
                    {t("import.loadMore")}
                  </Button>
                </div>
              ) : null}
              <p className="text-xs text-ink-subtle">{t("import.noDuplicates")}</p>
            </>
          ) : null}

          {error ? (
            <Callout role="alert" tone="danger">
              {error}
            </Callout>
          ) : null}
        </div>
      )}
    </Dialog>
  );
}

function SelectAllRow({
  allSelected,
  count,
  onToggle,
  someSelected,
}: {
  allSelected: boolean;
  count: number | null;
  onToggle: () => void;
  someSelected: boolean;
}) {
  const ref = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (ref.current) {
      ref.current.indeterminate = someSelected;
    }
  }, [someSelected]);

  return (
    <div className="flex h-8 items-center justify-between gap-3">
      <label className="inline-flex cursor-pointer select-none items-center gap-2.5 text-sm font-medium text-ink-muted transition-colors hover:text-ink">
        <CheckboxBox aria-label={t("import.selectAll")} checked={allSelected} onChange={onToggle} ref={ref} />
        <span>{t("import.selectAll")}</span>
      </label>
      {count !== null && count > 0 ? (
        <span className="text-sm tabular-nums text-ink-subtle">
          {formatPlural(count, { one: "import.selected.one", other: "import.selected.other" })}
        </span>
      ) : null}
    </div>
  );
}

function MediaTile({ item, onToggle, selected }: { item: TelegramMediaItem; onToggle: () => void; selected: boolean }) {
  const style = kindStyles[item.kind] ?? kindStyles.document;
  const Icon = style.icon;
  const name = item.filename || t(style.label);
  const meta = [item.filename ? t(style.label) : null, formatBytes(item.size_bytes), formatDay(item.date)].filter(Boolean).join(" · ");

  return (
    <button
      aria-checked={selected}
      aria-label={formatMessage("import.toggle", { name })}
      className={cx(
        "focus-ring relative flex min-w-0 flex-col rounded-lg border p-1.5 text-left transition-[background-color,border-color] duration-150",
        selected ? "border-accent bg-accent-soft" : "border-line bg-raised hover:border-line-strong hover:bg-subtle",
      )}
      onClick={onToggle}
      role="checkbox"
      type="button"
    >
      <span aria-hidden="true" className={cx("grid aspect-[4/3] w-full place-items-center rounded-md", style.tile)}>
        <Icon className="size-7" strokeWidth={1.75} />
      </span>
      <span className="mt-2 truncate px-1 text-sm font-medium text-ink">{name}</span>
      <span className="truncate px-1 pb-0.5 text-xs tabular-nums text-ink-subtle">{meta}</span>
      <span
        aria-hidden="true"
        className={cx(
          "absolute left-3 top-3 grid size-4 place-items-center rounded-[5px] border shadow-sm",
          selected ? "border-accent bg-accent text-on-accent" : "border-line-strong bg-raised",
        )}
      >
        {selected ? <Check className="size-3" strokeWidth={3} /> : null}
      </span>
    </button>
  );
}
