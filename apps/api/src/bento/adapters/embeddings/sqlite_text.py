from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.search.sqlite_fts import preferred_text_rows
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetTextModel


class SQLiteEmbeddingTextCatalog:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def text_for_asset(self, asset_id: str) -> str | None:
        """Document text (text files, PDF text layers) first, then metadata; OCR text only without document text."""
        with session_scope(self._session_factory) as session:
            rows = session.execute(
                select(AssetTextModel.source, AssetTextModel.text)
                .where(AssetTextModel.asset_id == asset_id)
                .order_by(AssetTextModel.source.asc(), AssetTextModel.id.asc())
            ).all()
        texts = [text.strip() for _, text in preferred_text_rows([(source, text) for source, text in rows])]
        text = "\n".join(text for text in texts if text)
        return text or None
