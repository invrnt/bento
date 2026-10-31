"""Sync engine: publish local ops, apply peers' batches, keys grants, snapshots, and bootstrap.

Binding protocol: `orchestration/architecture/telegram-first.md` § Sync Protocol and § Integration Rules.
Application code depends on ports only; every Sync document leaves the device sealed.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta

from bento.application.sync.batching import (
    MAX_BATCH_BYTES,
    MAX_BATCH_OPS,
    assets_to_check,
    held_asset_id,
    plan_flush,
    released_asset_id,
)
from bento.application.sync.envelope import envelope_epoch
from bento.application.sync.keys import KeysGrantApplier, parse_keys_message
from bento.application.sync.ports import (
    AssetHoldState,
    FullStatePublisherPort,
    HoldStatePort,
    SyncApplierPort,
    SyncOutboxStorePort,
    SyncStateStorePort,
)
from bento.application.sync.snapshot import parse_snapshot, snapshot_payload
from bento.application.sync.state import (
    BOOTSTRAP,
    CAPTURE,
    CURSOR,
    EPOCH_FLOOR,
    INITIAL_PUBLISH,
    LAST_PULL_AT,
    LAST_PUSH_AT,
    LAST_SNAPSHOT_AT,
    OPS_SINCE_SNAPSHOT,
    SNAPSHOT_REQUESTED_AT,
    VAULT_SCOPED_KEYS,
    SyncStateValues,
)
from bento.domain.errors import IntegrityError, ValidationFailedError
from bento.domain.security import SealPurpose, VaultKeyring
from bento.domain.sync import SyncBatch, SyncMessageKind, SyncMessageRef
from bento.domain.vault import SnapshotPointer, VaultHeader
from bento.ports.pairing import DeviceRepositoryPort
from bento.ports.repositories import ClockPort
from bento.ports.security import VaultCryptoPort
from bento.ports.sync import EntityState, HlcSourcePort, OutboxEntry, SnapshotSourcePort
from bento.ports.telegram import VaultTransportPort
from bento.ports.vault import VaultContext, VaultSessionPort

LOGGER = logging.getLogger("bento.sync")


@dataclass(frozen=True, slots=True)
class SyncPolicy:
    flush_min_age_ms: int = 3_000
    max_batch_ops: int = MAX_BATCH_OPS
    max_batch_bytes: int = MAX_BATCH_BYTES
    post_interval_seconds: float = 2.0
    """Batches, snapshots, and headers share a 1 message / 2 s budget on the Sync channel."""
    held_recheck_seconds: float = 60.0
    list_page_size: int = 100
    outbox_page_size: int = 2_000
    snapshot_after_ops: int = 2_000
    snapshot_interval: timedelta = timedelta(hours=24)
    bootstrap_progress_every: int = 500


@dataclass(frozen=True, slots=True)
class EpochFloor:
    epoch: int
    message_id: int


@dataclass(frozen=True, slots=True)
class PullResult:
    messages: int = 0
    applied_batches: int = 0
    applied_fields: int = 0


class SyncEngine:
    def __init__(
        self,
        *,
        vault: VaultSessionPort,
        transport: VaultTransportPort,
        crypto: VaultCryptoPort,
        outbox: SyncOutboxStorePort,
        state: SyncStateStorePort,
        applier: SyncApplierPort,
        snapshots: SnapshotSourcePort,
        hlc: HlcSourcePort,
        holds: HoldStatePort,
        publisher: FullStatePublisherPort,
        devices: DeviceRepositoryPort,
        clock: ClockPort,
        policy: SyncPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._vault = vault
        self._transport = transport
        self._crypto = crypto
        self._outbox = outbox
        self._state = state
        self._values = SyncStateValues(state)
        self._applier = applier
        self._snapshots = snapshots
        self._hlc = hlc
        self._holds = holds
        self._publisher = publisher
        self._keys = KeysGrantApplier(crypto=crypto, devices=devices, values=self._values, clock=clock)
        self._clock = clock
        self._policy = policy or SyncPolicy()
        self._sleep = sleep
        self._monotonic = monotonic
        self._lock = asyncio.Lock()
        self._held: dict[int, str] = {}
        self._scanned_through = 0
        self._last_full_check = float("-inf")
        self._last_post_at = float("-inf")
        self._caught_up = False

    @property
    def policy(self) -> SyncPolicy:
        return self._policy

    # Attach, initial publish, bootstrap

    async def prepare(self, context: VaultContext) -> VaultContext:
        """Enable capture for this vault, run the initial publish once, and bootstrap a device without cursor."""
        async with self._lock:
            vault_id, device_id = context.layout.vault_id, context.device.device_id
            capture = await self._values.get_json(CAPTURE)
            if not isinstance(capture, dict) or capture.get("vault_id") != vault_id or capture.get("device_id") != device_id:
                if isinstance(capture, dict) and capture.get("vault_id") != vault_id:
                    await self._reset_vault_state()
                # Capture first: changes committed from now on are captured, earlier ones are in the full state.
                await self._values.set_json(CAPTURE, {"vault_id": vault_id, "device_id": device_id})
            if await self._state.get_value(INITIAL_PUBLISH) != vault_id:
                count = await self._publisher.publish_full_state()
                await self._state.set_value(INITIAL_PUBLISH, vault_id)
                if count:
                    LOGGER.info("Initial publish queued %s ops", count)
            if await self._state.get_value(LAST_SNAPSHOT_AT) is None:
                await self._values.set_datetime(LAST_SNAPSHOT_AT, self._clock.now())
            if await self._state.get_value(CURSOR) is None:
                await self._bootstrap(context)
            return context

    async def _reset_vault_state(self) -> None:
        for key in VAULT_SCOPED_KEYS:
            await self._values.delete(key)
        await self._outbox.clear()
        self._held.clear()
        self._scanned_through = 0
        self._caught_up = False

    async def _bootstrap(self, context: VaultContext) -> None:
        await self._values.set_json(BOOTSTRAP, {"done": 0, "total": 0})
        header = await self._vault.read_header()
        covers = 0
        if header is not None and header.snapshot is not None:
            covers = await self._apply_snapshot_message(context, header.snapshot)
            await self._values.set_datetime(LAST_SNAPSHOT_AT, header.snapshot.created_at)
        await self._values.set_int(OPS_SINCE_SNAPSHOT, 0)
        # The bootstrap marker stays until the following pull reaches the tip.
        await self._values.set_int(CURSOR, covers)

    async def _apply_snapshot_message(self, context: VaultContext, pointer: SnapshotPointer) -> int:
        envelope = await self._transport.download_sync_document(context.layout, pointer.message_id)
        payload = self._crypto.open_json(context.keyring, SealPurpose.SNAPSHOT, envelope, aad=_aad(context))
        snapshot = parse_snapshot(payload)
        if snapshot.vault_id != context.layout.vault_id:
            raise IntegrityError("snapshot")
        total = len(snapshot.states)
        await self._values.set_json(BOOTSTRAP, {"done": 0, "total": total})
        await self._applier.apply_snapshot(self._with_progress(snapshot.states, total), snapshot.purged)
        await self._values.set_json(BOOTSTRAP, {"done": total, "total": total})
        return min(pointer.covers_through_message_id, snapshot.covers_through_message_id)

    async def _with_progress(self, states: Sequence[EntityState], total: int) -> AsyncIterator[EntityState]:
        every = max(1, self._policy.bootstrap_progress_every)
        for index, entity_state in enumerate(states):
            if index and index % every == 0:
                await self._values.set_json(BOOTSTRAP, {"done": index, "total": total})
            yield entity_state

    # Flush

    async def flush_due(self) -> bool:
        backlog = await self._outbox.backlog(after_seq=self._scanned_through)
        if backlog.count:
            return (
                backlog.count >= self._policy.max_batch_ops
                or backlog.total_bytes >= self._policy.max_batch_bytes
                or backlog.oldest_age_ms >= self._policy.flush_min_age_ms
            )
        return bool(self._held) and self._monotonic() - self._last_full_check >= self._policy.held_recheck_seconds

    async def flush(self, context: VaultContext, *, force: bool = False) -> int:
        """Publish due outbox ops in sealed batches; returns the number of ops published."""
        async with self._lock:
            if not force and not await self.flush_due():
                return 0
            published = 0
            try:
                while True:
                    count, more = await self._flush_round(context)
                    published += count
                    if not more:
                        return published
            except BaseException:
                # Unposted entries must be planned again: rescan the whole outbox next time.
                self._scanned_through = 0
                self._held.clear()
                raise

    async def _flush_round(self, context: VaultContext) -> tuple[int, bool]:
        fresh = await self._outbox.page(after_seq=self._scanned_through, limit=self._policy.outbox_page_size)
        held_assets = set(self._held.values())
        full_check = self._monotonic() - self._last_full_check >= self._policy.held_recheck_seconds
        releases = {asset_id for entry in fresh if (asset_id := released_asset_id(entry.operation)) is not None}
        check = set(assets_to_check(fresh)) | (held_assets if full_check else releases & held_assets)
        states = await self._holds.asset_states(frozenset(check)) if check else {}
        if full_check:
            self._last_full_check = self._monotonic()

        revisit_seqs = tuple(
            seq for seq, asset_id in self._held.items() if states.get(asset_id, AssetHoldState.LOCAL) != AssetHoldState.LOCAL
        )
        revisit = await self._outbox_entries(revisit_seqs)
        known = {entry.seq for entry in revisit}
        for seq in revisit_seqs:
            if seq not in known:
                self._held.pop(seq, None)
        entries = sorted((*revisit, *fresh), key=lambda entry: entry.seq)
        plan = plan_flush(
            entries,
            states,
            max_ops=self._policy.max_batch_ops,
            max_bytes=self._policy.max_batch_bytes,
        )
        if plan.dropped:
            await self._outbox.remove(plan.dropped)
        for seq in plan.dropped:
            self._held.pop(seq, None)
        by_seq = {entry.seq: entry for entry in entries}
        for seq in plan.held:
            asset_id = held_asset_id(by_seq[seq].operation)
            if asset_id is not None:
                self._held[seq] = asset_id
        if fresh:
            self._scanned_through = max(self._scanned_through, fresh[-1].seq)

        published = 0
        for batch in plan.batches:
            await self._post_batch(context, batch)
            for entry in batch:
                self._held.pop(entry.seq, None)
            published += len(batch)
        return published, len(fresh) >= self._policy.outbox_page_size

    async def _outbox_entries(self, seqs: tuple[int, ...]) -> tuple[OutboxEntry, ...]:
        if not seqs:
            return ()
        wanted = set(seqs)
        found: list[OutboxEntry] = []
        after = min(wanted) - 1
        last = max(wanted)
        while after < last:
            page = await self._outbox.page(after_seq=after, limit=self._policy.outbox_page_size)
            if not page:
                break
            found.extend(entry for entry in page if entry.seq in wanted)
            after = page[-1].seq
        return tuple(found)

    async def _post_batch(self, context: VaultContext, entries: tuple[OutboxEntry, ...]) -> None:
        context = await self._latest_keyring(context)
        batch = SyncBatch(
            batch_id=str(uuid.uuid4()),
            device_id=context.device.device_id,
            ops=tuple(entry.operation for entry in entries),
        )
        envelope = self._crypto.seal_json(context.keyring, SealPurpose.SYNC, batch.to_dict(), aad=_aad(context))
        await self._pace()
        await self._transport.post_sync_document(context.layout, SyncMessageKind.BATCH, envelope)
        self._last_post_at = self._monotonic()
        self._caught_up = False
        # Only after Telegram confirmed the message; a crash before this re-sends ops that peers ignore by HLC.
        await self._outbox.remove(tuple(entry.seq for entry in entries))
        await self._values.set_datetime(LAST_PUSH_AT, self._clock.now())
        await self._values.set_int(OPS_SINCE_SNAPSHOT, await self._values.get_int(OPS_SINCE_SNAPSHOT) + len(entries))

    async def _latest_keyring(self, context: VaultContext) -> VaultContext:
        """A rotation by another process (device removal in the API) must not be sealed over with the old epoch."""
        current = await self._vault.current()
        if current is not None and current.keyring.current_epoch > context.keyring.current_epoch:
            return replace(context, keyring=current.keyring)
        return context

    async def _pace(self) -> None:
        wait = self._policy.post_interval_seconds - (self._monotonic() - self._last_post_at)
        if wait > 0:
            await self._sleep(wait)

    # Pull

    async def pull(self, context: VaultContext) -> tuple[VaultContext, PullResult]:
        """Process Sync messages after the cursor; returns the (possibly re-keyed) context."""
        async with self._lock:
            cursor = await self._values.get_int(CURSOR)
            floor = await self._floor()
            messages = batches = fields = 0
            while True:
                refs = await self._transport.list_sync_messages(
                    context.layout, after_message_id=cursor, limit=self._policy.list_page_size
                )
                for ref in refs:
                    if ref.message_id <= cursor:
                        continue
                    context, floor, applied = await self._process(context, ref, floor)
                    if applied is not None:
                        batches += 1
                        fields += applied
                    messages += 1
                    cursor = ref.message_id
                    await self._values.set_int(CURSOR, cursor)
                if len(refs) < self._policy.list_page_size:
                    break
            await self._values.set_datetime(LAST_PULL_AT, self._clock.now())
            if await self._state.get_value(BOOTSTRAP) is not None:
                await self._values.delete(BOOTSTRAP)
            self._caught_up = True
            return context, PullResult(messages=messages, applied_batches=batches, applied_fields=fields)

    async def _process(
        self, context: VaultContext, ref: SyncMessageRef, floor: EpochFloor | None
    ) -> tuple[VaultContext, EpochFloor | None, int | None]:
        if ref.kind == SyncMessageKind.BATCH:
            return context, floor, await self._apply_batch_message(context, ref, floor)
        if ref.kind == SyncMessageKind.KEYS:
            context, floor = await self._apply_keys_message(context, ref, floor)
            return context, floor, None
        if ref.kind == SyncMessageKind.HEADER:
            return context, await self._observe_header(context, ref, floor), None
        # Snapshots matter only while bootstrapping (through the header); pairing has its own cursor.
        return context, floor, None

    async def _apply_batch_message(self, context: VaultContext, ref: SyncMessageRef, floor: EpochFloor | None) -> int | None:
        envelope = await self._transport.download_sync_document(context.layout, ref.message_id)
        below_floor = _below_floor(envelope, ref.message_id, floor)
        try:
            batch = SyncBatch.from_dict(
                self._crypto.open_json(context.keyring, SealPurpose.SYNC, envelope, aad=_aad(context))
            )
        except (IntegrityError, ValidationFailedError) as exc:
            LOGGER.warning("Integrity: skipped Sync batch %s (%s)", ref.message_id, exc.code)
            return None
        own = batch.device_id == context.device.device_id
        if below_floor:
            LOGGER.warning("Integrity: rejected Sync batch %s sealed below the key epoch floor", ref.message_id)
            if own:
                # Peers reject it too: publish the same ops again under the current epoch.
                for operation in batch.ops:
                    await self._outbox.record(operation)
            return None
        if own or await self._state.is_batch_applied(batch.batch_id):
            return None
        operations = tuple(sorted(batch.ops, key=lambda operation: operation.hlc))
        applied = await self._applier.apply_batch(
            batch.batch_id, ref.message_id, operations, sender=batch.device_id, sent_at=ref.created_at
        )
        await self._values.set_int(OPS_SINCE_SNAPSHOT, await self._values.get_int(OPS_SINCE_SNAPSHOT) + len(operations))
        return applied

    async def _apply_keys_message(
        self, context: VaultContext, ref: SyncMessageRef, floor: EpochFloor | None
    ) -> tuple[VaultContext, EpochFloor | None]:
        try:
            message = parse_keys_message(await self._transport.download_sync_document(context.layout, ref.message_id))
        except ValidationFailedError:
            LOGGER.warning("Integrity: skipped malformed or unsupported keys message %s", ref.message_id)
            return context, floor
        if message.vault_id != context.layout.vault_id:
            return context, floor
        try:
            merged = await self._keys.apply(message, context)
        except IntegrityError as exc:
            LOGGER.warning("Integrity: rejected keys grant in message %s (%s)", ref.message_id, exc.details.get("what"))
            merged = None
        if merged is not None:
            await self._vault.update_keyring(merged)
            context = replace(context, keyring=merged)
            LOGGER.info("Applied vault key epoch %s", merged.current_epoch)
        # Only an epoch this device already holds raises the floor, so even a rejected message cannot strand it.
        if message.epoch in context.keyring.keys:
            floor = await self._raise_floor(floor, message.epoch, ref.message_id)
        return context, floor

    async def _observe_header(self, context: VaultContext, ref: SyncMessageRef, floor: EpochFloor | None) -> EpochFloor | None:
        if ref.text is None:
            return floor
        try:
            header = VaultHeader.from_json(ref.text)
        except ValidationFailedError:
            return floor
        if header.vault_id != context.layout.vault_id or not self._header_valid(context.keyring, header):
            return floor
        if header.snapshot is not None:
            last = await self._values.get_datetime(LAST_SNAPSHOT_AT)
            if last is None or header.snapshot.created_at > last:
                await self._values.set_datetime(LAST_SNAPSHOT_AT, header.snapshot.created_at)
                await self._values.set_int(OPS_SINCE_SNAPSHOT, 0)
        return await self._raise_floor(floor, header.current_epoch, ref.message_id)

    def _header_valid(self, keyring: VaultKeyring, header: VaultHeader) -> bool:
        if header.current_epoch not in keyring.keys:
            return False
        at_epoch = VaultKeyring(vault_id=keyring.vault_id, current_epoch=header.current_epoch, keys=keyring.keys)
        return self._crypto.verify_header_mac(at_epoch, header.canonical_unsigned_bytes(), header.mac)

    async def _floor(self) -> EpochFloor | None:
        value = await self._values.get_json(EPOCH_FLOOR)
        if not isinstance(value, dict):
            return None
        try:
            return EpochFloor(epoch=int(value["epoch"]), message_id=int(value["message_id"]))
        except (KeyError, TypeError, ValueError):
            return None

    async def _raise_floor(self, floor: EpochFloor | None, epoch: int, message_id: int) -> EpochFloor | None:
        if floor is not None and epoch <= floor.epoch:
            return floor
        raised = EpochFloor(epoch=epoch, message_id=message_id)
        await self._values.set_json(EPOCH_FLOOR, {"epoch": epoch, "message_id": message_id})
        return raised

    # Snapshots

    async def snapshot_due(self) -> bool:
        if await self._state.get_value(SNAPSHOT_REQUESTED_AT) is not None:
            return True
        ops = await self._values.get_int(OPS_SINCE_SNAPSHOT)
        if ops >= self._policy.snapshot_after_ops:
            return True
        last = await self._values.get_datetime(LAST_SNAPSHOT_AT)
        return ops > 0 and last is not None and self._clock.now() - last >= self._policy.snapshot_interval

    async def maybe_snapshot(self, context: VaultContext, *, force: bool = False) -> bool:
        """Create a snapshot when due and this device has applied everything up to the tip."""
        async with self._lock:
            if not self._caught_up or (await self._outbox.backlog(after_seq=self._scanned_through)).count:
                return False
            if not force and not await self.snapshot_due():
                return False
            await self._create_snapshot(context)
            return True

    async def _create_snapshot(self, context: VaultContext) -> None:
        now = self._clock.now()
        cursor = await self._values.get_int(CURSOR)
        states = [entity_state async for entity_state in self._snapshots.iter_states()]
        payload = snapshot_payload(
            snapshot_id=str(uuid.uuid4()),
            device_id=context.device.device_id,
            vault_id=context.layout.vault_id,
            covers_through_message_id=cursor,
            created_at=now,
            states=states,
            purged=await self._snapshots.purged(),
        )
        envelope = self._crypto.seal_json(context.keyring, SealPurpose.SNAPSHOT, payload, aad=_aad(context))
        await self._pace()
        ref = await self._transport.post_sync_document(context.layout, SyncMessageKind.SNAPSHOT, envelope)
        self._last_post_at = self._monotonic()
        pointer = SnapshotPointer(message_id=ref.message_id, covers_through_message_id=cursor, created_at=now)
        await self._pace()
        await self._vault.update_header(lambda header: replace(header, snapshot=pointer))
        self._last_post_at = self._monotonic()
        self._caught_up = False
        await self._values.set_datetime(LAST_SNAPSHOT_AT, now)
        await self._values.set_int(OPS_SINCE_SNAPSHOT, 0)
        await self._values.delete(SNAPSHOT_REQUESTED_AT)
        LOGGER.info("Published a sync snapshot with %s entities", len(states))

    async def request_snapshot(self) -> None:
        await self._values.set_datetime(SNAPSHOT_REQUESTED_AT, self._clock.now())

    # One full cycle

    async def sync_once(self, context: VaultContext, *, force_flush: bool = False) -> VaultContext:
        context = await self.prepare(context)
        await self.flush(context, force=force_flush)
        context, _ = await self.pull(context)
        await self.maybe_snapshot(context)
        return context


def _aad(context: VaultContext) -> bytes:
    return context.layout.vault_id.encode("utf-8")


def _below_floor(envelope: bytes, message_id: int, floor: EpochFloor | None) -> bool:
    if floor is None or message_id <= floor.message_id:
        return False
    epoch = envelope_epoch(envelope)
    return epoch is not None and epoch < floor.epoch
