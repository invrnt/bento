from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.mappers import device_from_model, device_to_model
from bento.domain.devices import Device
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import DeviceModel


class SQLiteDeviceRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def list(self, *, include_removed: bool = False) -> tuple[Device, ...]:
        statement = select(DeviceModel).order_by(DeviceModel.added_at, DeviceModel.id)
        if not include_removed:
            statement = statement.where(DeviceModel.removed_at.is_(None))
        with session_scope(self._session_factory) as session:
            return tuple(device_from_model(model) for model in session.scalars(statement))

    async def get(self, device_id: str) -> Device | None:
        with session_scope(self._session_factory) as session:
            model = session.get(DeviceModel, device_id)
            return device_from_model(model) if model is not None else None

    async def save(self, device: Device) -> None:
        with session_scope(self._session_factory) as session:
            if device.current:
                # Only one row describes this device.
                session.execute(
                    update(DeviceModel)
                    .where(DeviceModel.id != device.id, DeviceModel.is_current.is_(True))
                    .values(is_current=False)
                )
            session.merge(device_to_model(device))
