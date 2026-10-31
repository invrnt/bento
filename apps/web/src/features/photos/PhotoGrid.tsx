import type { PhotoAsset } from "../../api/photos";
import { PhotoCard } from "./PhotoCard";

export type PhotoGridProps = {
  assets: PhotoAsset[];
  onOpen: (asset: PhotoAsset) => void;
  showFavoriteMarkers?: boolean;
};

export function PhotoGrid({ assets, onOpen, showFavoriteMarkers = true }: PhotoGridProps) {
  return (
    <div className="flex flex-wrap content-start gap-1.5 [--row-h:9rem] after:grow-[1000000] after:content-[''] sm:[--row-h:11rem] lg:[--row-h:13rem]">
      {assets.map((asset) => (
        <PhotoCard asset={asset} key={asset.id} onOpen={onOpen} showFavoriteMarker={showFavoriteMarkers} />
      ))}
    </div>
  );
}
