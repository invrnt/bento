import { useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { Upload } from "lucide-react";

import { Button } from "../../components/Button";
import type { ButtonVariant } from "../../components/Button";
import type { PhotosApi } from "../../api/photos";
import { t } from "../../i18n/dictionary";

export type PhotoUploadButtonProps = {
  api: PhotosApi;
  label?: string;
  onUploaded: () => void;
  variant?: ButtonVariant;
};

export function PhotoUploadButton({ api, label = t("photos.upload"), onUploaded, variant = "primary" }: PhotoUploadButtonProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);

  async function onChange(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    if (!file) {
      return;
    }

    setUploading(true);
    try {
      await api.uploadPhoto(file);
      onUploaded();
    } finally {
      setUploading(false);
      input.value = "";
    }
  }

  return (
    <>
      <input
        accept="image/*,video/*"
        aria-label={t("photos.upload")}
        className="sr-only"
        onChange={onChange}
        ref={inputRef}
        tabIndex={-1}
        type="file"
      />
      <Button
        leadingIcon={<Upload />}
        loading={uploading}
        onClick={() => inputRef.current?.click()}
        variant={variant}
      >
        {uploading ? t("photos.uploading") : label}
      </Button>
    </>
  );
}
