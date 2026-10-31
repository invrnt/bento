import { useId, useState } from "react";
import { Bookmark, Check, Megaphone, RotateCw, Search, User, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { TelegramChat } from "../../api/telegram";
import { Button } from "../../components/Button";
import { Input } from "../../components/Input";
import { Spinner } from "../../components/Spinner";
import { t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import { telegramErrorMessage } from "./telegramErrors";
import { useTelegramChats } from "./useTelegramChats";
import type { ListChats } from "./useTelegramChats";

const kindIcons: Record<TelegramChat["kind"], LucideIcon> = {
  channel: Megaphone,
  group: Users,
  saved: Bookmark,
  user: User,
};

const kindKeys: Record<TelegramChat["kind"], MessageKey> = {
  channel: "telegram.kind.channel",
  group: "telegram.kind.group",
  saved: "telegram.kind.saved",
  user: "telegram.kind.user",
};

/** Saved Messages is shown in the user's language whatever Telegram calls it. */
export function chatTitle(chat: TelegramChat): string {
  return chat.kind === "saved" ? t("telegram.savedMessages") : chat.title;
}

export type TelegramChatPickerProps = {
  listChats?: ListChats;
  onSelect: (chat: TelegramChat) => void;
  selectedId: number | null;
};

/** Searchable recent chats as a radio group (arrow keys move between chats). */
export function TelegramChatPicker({ listChats, onSelect, selectedId }: TelegramChatPickerProps) {
  const [query, setQuery] = useState("");
  const chats = useTelegramChats(query, listChats);
  const groupName = useId();

  return (
    <div className="grid gap-3">
      <Input
        data-autofocus
        hideLabel
        label={t("telegram.chats.searchLabel")}
        leadingIcon={<Search />}
        onChange={(event) => setQuery(event.currentTarget.value)}
        placeholder={t("telegram.chats.searchPlaceholder")}
        type="search"
        value={query}
      />
      <fieldset className="min-w-0">
        <legend className="sr-only">{t("telegram.chats.label")}</legend>
        <div className="h-72 overflow-y-auto overscroll-contain rounded-lg border border-line bg-raised">
          {chats.status === "loading" && chats.chats.length === 0 ? (
            <p className="flex items-center gap-2.5 p-4 text-sm text-ink-muted" role="status">
              <Spinner />
              {t("telegram.chats.loading")}
            </p>
          ) : null}
          {chats.status === "error" ? (
            <div className="grid justify-items-start gap-3 p-4" role="alert">
              <p className="text-sm text-ink-muted">
                {t("telegram.chats.error")} {telegramErrorMessage(chats.error)}
              </p>
              <Button leadingIcon={<RotateCw />} onClick={chats.retry} size="sm">
                {t("common.retry")}
              </Button>
            </div>
          ) : null}
          {chats.status === "ready" && chats.chats.length === 0 ? (
            <p className="p-4 text-sm text-ink-muted">{query.trim() ? t("telegram.chats.empty") : t("telegram.chats.emptyRecent")}</p>
          ) : null}
          {chats.chats.length > 0 ? (
            <div className={cx("divide-y divide-line transition-opacity duration-150", chats.status === "loading" && "opacity-60")}>
              {chats.chats.map((chat) => (
                <ChatOption chat={chat} checked={chat.id === selectedId} groupName={groupName} key={chat.id} onSelect={onSelect} />
              ))}
            </div>
          ) : null}
        </div>
      </fieldset>
    </div>
  );
}

function ChatOption({
  chat,
  checked,
  groupName,
  onSelect,
}: {
  chat: TelegramChat;
  checked: boolean;
  groupName: string;
  onSelect: (chat: TelegramChat) => void;
}) {
  const Icon = kindIcons[chat.kind] ?? User;
  const saved = chat.kind === "saved";

  return (
    <label
      className={cx(
        "flex cursor-pointer items-center gap-3 px-3 py-2.5 outline-2 -outline-offset-2 outline-transparent transition-colors duration-150 has-[:focus-visible]:outline-focus",
        checked ? "bg-accent-soft" : "hover:bg-hover",
      )}
    >
      <input checked={checked} className="sr-only" name={groupName} onChange={() => onSelect(chat)} type="radio" value={String(chat.id)} />
      <span
        aria-hidden="true"
        className={cx(
          "grid size-9 shrink-0 place-items-center rounded-full [&_svg]:size-4",
          saved ? "bg-accent-soft text-accent-ink" : "bg-sunken text-ink-muted",
          checked && !saved && "bg-raised",
        )}
      >
        <Icon strokeWidth={1.75} />
      </span>
      <span className="grid min-w-0 flex-1 leading-tight">
        <span className="truncate text-base font-medium text-ink">{chatTitle(chat)}</span>
        <span className="mt-0.5 truncate text-xs text-ink-muted">{t(kindKeys[chat.kind] ?? "telegram.kind.user")}</span>
      </span>
      {checked ? <Check aria-hidden="true" className="size-4 shrink-0 text-accent-ink" /> : null}
    </label>
  );
}
