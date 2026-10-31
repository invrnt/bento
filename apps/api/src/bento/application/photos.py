from __future__ import annotations

from dataclasses import dataclass

from bento.domain.assets import Asset
from bento.domain.errors import AlbumNotFoundError, AssetNotFoundError
from bento.domain.photos import Album, TimelineGroup
from bento.ports.repositories import AlbumRepositoryPort, AssetRepositoryPort, ClockPort


@dataclass(frozen=True, slots=True)
class TimelineQuery:
    cursor: str | None = None
    limit: int = 50


@dataclass(frozen=True, slots=True)
class TimelineResult:
    groups: tuple[TimelineGroup, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class CreateAlbumCommand:
    title: str


@dataclass(frozen=True, slots=True)
class AddAlbumAssetCommand:
    album_id: str
    asset_id: str


class PhotosUseCases:
    def __init__(
        self,
        *,
        assets: AssetRepositoryPort,
        albums: AlbumRepositoryPort,
        clock: ClockPort,
    ) -> None:
        self._assets = assets
        self._albums = albums
        self._clock = clock

    async def timeline(self, query: TimelineQuery) -> TimelineResult:
        groups, next_cursor = await self._assets.list_photos_timeline(cursor=query.cursor, limit=query.limit)
        return TimelineResult(groups=groups, next_cursor=next_cursor)

    async def toggle_favorite(self, asset_id: str) -> Asset:
        asset = await self._assets.get(asset_id)
        if asset is None:
            raise AssetNotFoundError(asset_id)
        updated = asset.toggle_favorite(self._clock.now())
        await self._assets.save(updated)
        return updated

    async def create_album(self, command: CreateAlbumCommand) -> Album:
        now = self._clock.now()
        album = Album(
            id=await self._albums.next_id(),
            title=command.title,
            asset_ids=frozenset(),
            created_at=now,
            updated_at=now,
        )
        await self._albums.add(album)
        return album

    async def list_albums(self, *, cursor: str | None = None, limit: int = 50) -> tuple[tuple[Album, ...], str | None]:
        return await self._albums.list(cursor=cursor, limit=limit)

    async def get_album(self, album_id: str) -> Album:
        return await self._require_album(album_id)

    async def add_asset_to_album(self, command: AddAlbumAssetCommand) -> Album:
        album = await self._require_album(command.album_id)
        if await self._assets.get(command.asset_id) is None:
            raise AssetNotFoundError(command.asset_id)
        updated = album.add_asset(command.asset_id, self._clock.now())
        await self._albums.save(updated)
        return updated

    async def remove_asset_from_album(self, command: AddAlbumAssetCommand) -> Album:
        album = await self._require_album(command.album_id)
        updated = album.remove_asset(command.asset_id, self._clock.now())
        await self._albums.save(updated)
        return updated

    async def _require_album(self, album_id: str) -> Album:
        album = await self._albums.get(album_id)
        if album is None:
            raise AlbumNotFoundError(album_id)
        return album
