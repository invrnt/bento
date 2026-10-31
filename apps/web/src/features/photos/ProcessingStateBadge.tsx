import { Badge } from "../../components/Badge";
import type { BadgeTone } from "../../components/Badge";
import { t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import type { PhotoProcessingState } from "../../api/photos";

const stateLabels: Record<PhotoProcessingState, MessageKey> = {
  blob_stored: "photos.state.blobStored",
  created: "photos.state.created",
  embedding_pending: "photos.state.embeddingPending",
  embedding_ready: "photos.state.embeddingReady",
  failed: "photos.state.failed",
  failed_partial: "photos.state.partialFailure",
  indexed: "photos.state.indexed",
  metadata_extracted: "photos.state.metadataExtracted",
  ocr_pending: "photos.state.ocrPending",
  ocr_ready: "photos.state.ocrReady",
  thumbnail_pending: "photos.state.thumbnailPending",
  thumbnail_ready: "photos.state.thumbnailReady",
};

const stateTones: Record<PhotoProcessingState, BadgeTone> = {
  blob_stored: "neutral",
  created: "neutral",
  embedding_pending: "warning",
  embedding_ready: "success",
  failed: "danger",
  failed_partial: "warning",
  indexed: "success",
  metadata_extracted: "neutral",
  ocr_pending: "warning",
  ocr_ready: "success",
  thumbnail_pending: "warning",
  thumbnail_ready: "success",
};

export type ProcessingStateBadgeProps = {
  className?: string;
  state: PhotoProcessingState | null;
};

export function ProcessingStateBadge({ className, state }: ProcessingStateBadgeProps) {
  if (!state) {
    return null;
  }

  const tone = stateTones[state] ?? "neutral";

  return (
    <Badge className={className} dot pulse={tone === "warning"} tone={tone}>
      {t(stateLabels[state])}
    </Badge>
  );
}
