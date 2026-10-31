import { useState } from "react";
import { LockOpen, Send } from "lucide-react";

import { shareAssetToTelegram } from "../../api/telegram";
import type { TelegramChat } from "../../api/telegram";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { Dialog } from "../../components/Dialog";
import { Input } from "../../components/Input";
import { showToast } from "../../components/Toast";
import { t } from "../../i18n/dictionary";
import { formatMessage } from "../../lib/format";
import { chatTitle, TelegramChatPicker } from "./TelegramChatPicker";
import { telegramErrorMessage } from "./telegramErrors";
import type { ListChats } from "./useTelegramChats";

export type ShareTarget = { id: string; name: string };

export type ShareApi = {
  listChats?: ListChats;
  share?: (assetId: string, chatId: number, caption?: string) => Promise<unknown>;
};

export type ShareToTelegramDialogProps = {
  api?: ShareApi;
  onClose: () => void;
  /** The file to send; `null` keeps the dialog closed. */
  target: ShareTarget | null;
};

/** Sends a plaintext copy of one file to a Telegram chat, saying so before it happens. */
export function ShareToTelegramDialog({ api, onClose, target }: ShareToTelegramDialogProps) {
  if (!target) {
    return null;
  }

  return <ShareDialogBody api={api} key={target.id} onClose={onClose} target={target} />;
}

function ShareDialogBody({ api = {}, onClose, target }: { api?: ShareApi; onClose: () => void; target: ShareTarget }) {
  const share = api.share ?? ((assetId: string, chatId: number, caption?: string) => shareAssetToTelegram(assetId, chatId, caption));
  const [chat, setChat] = useState<TelegramChat | null>(null);
  const [caption, setCaption] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send() {
    if (!chat) {
      return;
    }

    setSending(true);
    setError(null);
    try {
      await share(target.id, chat.id, caption.trim() || undefined);
      onClose();
      showToast({ icon: <Send />, message: formatMessage("share.sent", { chat: chatTitle(chat) }), tone: "success" });
    } catch (caught) {
      setError(telegramErrorMessage(caught));
      setSending(false);
    }
  }

  return (
    <Dialog
      actions={
        <>
          <Button onClick={onClose} variant="ghost">
            {t("share.cancel")}
          </Button>
          <Button disabled={!chat} form="share-telegram-form" leadingIcon={<Send />} loading={sending} type="submit" variant="primary">
            {t("share.send")}
          </Button>
        </>
      }
      description={target.name}
      icon={<Send />}
      onOpenChange={(open) => {
        if (!open && !sending) {
          onClose();
        }
      }}
      open
      title={t("share.title")}
    >
      <div className="grid gap-4">
        <TelegramChatPicker listChats={api.listChats} onSelect={setChat} selectedId={chat?.id ?? null} />
        {/* Only the caption submits on Enter; Enter in the chat search must not send. */}
        <form
          id="share-telegram-form"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <Input
            label={t("share.caption.label")}
            maxLength={1024}
            onChange={(event) => setCaption(event.currentTarget.value)}
            placeholder={t("share.caption.placeholder")}
            value={caption}
          />
        </form>
        <Callout icon={<LockOpen />} tone="info">
          {t("share.plaintextNotice")}
        </Callout>
        {error ? (
          <Callout role="alert" tone="danger">
            {error}
          </Callout>
        ) : null}
      </div>
    </Dialog>
  );
}
