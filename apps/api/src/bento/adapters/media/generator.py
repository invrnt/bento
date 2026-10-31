from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

from bento.application.media.service import GeneratedMediaFile
from bento.domain.assets import Asset, AssetKind
from bento.domain.errors import UnsupportedMediaTypeError
from bento.domain.storage import BlobKind
from bento.infrastructure.child_processes import child_environment, resolve_executable


class LocalMediaGenerator:
    def __init__(self, cache_dir: Path | str) -> None:
        self._cache_dir = Path(cache_dir)

    async def generate(self, asset: Asset, source_path: Path) -> tuple[GeneratedMediaFile, ...]:
        if asset.kind == AssetKind.IMAGE:
            return await asyncio.to_thread(self._generate_image, asset, source_path)
        if asset.kind == AssetKind.PDF:
            return await asyncio.to_thread(self._generate_pdf, asset, source_path)
        if asset.kind == AssetKind.VIDEO:
            return await asyncio.to_thread(self._generate_video, asset, source_path)
        raise UnsupportedMediaTypeError(asset.metadata.mime_type)

    async def cleanup(self, generated_files: tuple[GeneratedMediaFile, ...]) -> None:
        await asyncio.to_thread(self._cleanup, generated_files)

    def _cleanup(self, generated_files: tuple[GeneratedMediaFile, ...]) -> None:
        parents: set[Path] = set()
        for generated in generated_files:
            try:
                generated.path.unlink(missing_ok=True)
            except OSError:
                continue
            parents.add(generated.path.parent)
        for parent in parents:
            try:
                parent.rmdir()
            except OSError:
                pass

    def _generate_image(self, asset: Asset, source_path: Path) -> tuple[GeneratedMediaFile, ...]:
        try:
            from PIL import Image, ImageOps
        except ImportError as exc:
            raise RuntimeError("Pillow is required for image thumbnails") from exc

        target_dir = self._asset_cache_dir(asset.id)
        generated: list[GeneratedMediaFile] = []
        with Image.open(source_path) as image:
            image = ImageOps.exif_transpose(image)
            for label, max_side in (("thumb-sm", 256), ("thumb-md", 512), ("preview", 1600)):
                copy = image.copy()
                copy.thumbnail((max_side, max_side))
                output = target_dir / f"{label}.jpg"
                rgb = copy.convert("RGB")
                rgb.save(output, format="JPEG", quality=85, optimize=True)
                width, height = rgb.size
                generated.append(
                    _generated_file(
                        path=output,
                        kind=BlobKind.PREVIEW if label == "preview" else BlobKind.THUMBNAIL,
                        filename=f"{asset.id}-{label}.jpg",
                        mime_type="image/jpeg",
                        width=width,
                        height=height,
                    )
                )
        return tuple(generated)

    def _generate_pdf(self, asset: Asset, source_path: Path) -> tuple[GeneratedMediaFile, ...]:
        try:
            import pypdfium2 as pdfium
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("pypdfium2 and Pillow are required for PDF thumbnails") from exc

        target_dir = self._asset_cache_dir(asset.id)
        document = pdfium.PdfDocument(str(source_path))
        try:
            if len(document) < 1:
                raise UnsupportedMediaTypeError(asset.metadata.mime_type)
            page = document[0]
            bitmap = page.render(scale=2)
            pil_image: Image.Image = bitmap.to_pil()
            pil_image.thumbnail((512, 512))
            thumb = target_dir / "pdf-thumb.jpg"
            pil_image.convert("RGB").save(thumb, format="JPEG", quality=85, optimize=True)
            preview = target_dir / "pdf-preview.jpg"
            pil_image.thumbnail((1600, 1600))
            pil_image.convert("RGB").save(preview, format="JPEG", quality=85, optimize=True)
        finally:
            document.close()
        return (
            _generated_file(
                path=thumb,
                kind=BlobKind.THUMBNAIL,
                filename=f"{asset.id}-pdf-thumb.jpg",
                mime_type="image/jpeg",
                width=None,
                height=None,
            ),
            _generated_file(
                path=preview,
                kind=BlobKind.PREVIEW,
                filename=f"{asset.id}-pdf-preview.jpg",
                mime_type="image/jpeg",
                width=None,
                height=None,
            ),
        )

    def _generate_video(self, asset: Asset, source_path: Path) -> tuple[GeneratedMediaFile, ...]:
        ffmpeg = resolve_executable("ffmpeg")
        ffprobe = resolve_executable("ffprobe")
        if ffmpeg is None or ffprobe is None:
            raise RuntimeError("ffmpeg and ffprobe are required for video thumbnails")

        target_dir = self._asset_cache_dir(asset.id)
        output = target_dir / "video-thumb.jpg"
        duration = _video_duration_seconds(ffprobe, source_path, target_dir)
        timestamp = min(1.0, duration * 0.1) if duration and duration > 0 else 0.0
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(source_path),
            "-frames:v",
            "1",
            "-vf",
            "scale='min(512,iw)':-2",
            "-y",
            str(output),
        ]
        completed = _run_tool(command, target_dir)
        if completed.returncode != 0:
            raise RuntimeError(_safe_process_error("ffmpeg", completed.stderr))
        return (
            _generated_file(
                path=output,
                kind=BlobKind.THUMBNAIL,
                filename=f"{asset.id}-video-thumb.jpg",
                mime_type="image/jpeg",
                width=None,
                height=None,
            ),
        )

    def _asset_cache_dir(self, asset_id: str) -> Path:
        target_dir = self._cache_dir / asset_id
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir


def _run_tool(command: list[str], working_directory: Path) -> subprocess.CompletedProcess[str]:
    """Run with an allowlisted environment and a Bento-owned working directory (no DLL planting)."""
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=child_environment(),
        cwd=working_directory,
        stdin=subprocess.DEVNULL,
    )


def _video_duration_seconds(ffprobe: str, source_path: Path, working_directory: Path) -> float | None:
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(source_path),
    ]
    completed = _run_tool(command, working_directory)
    if completed.returncode != 0:
        return None
    try:
        duration = json.loads(completed.stdout).get("format", {}).get("duration")
        return float(duration) if duration is not None else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _generated_file(
    *,
    path: Path,
    kind: BlobKind,
    filename: str,
    mime_type: str,
    width: int | None,
    height: int | None,
) -> GeneratedMediaFile:
    return GeneratedMediaFile(
        path=path,
        kind=kind,
        filename=filename,
        mime_type=mime_type,
        size_bytes=path.stat().st_size,
        sha256=_sha256(path),
        width=width,
        height=height,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_process_error(command: str, stderr: str) -> str:
    summary = " ".join(stderr.split())[:200]
    return f"{command} failed: {summary}" if summary else f"{command} failed"
