from datetime import datetime
from typing import Optional
from uuid import UUID

from database import Context
from models import StatusResultHistory


class StatusResultHistoryRepository:
    """A camada que fala com a tabela status_result_history."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(
        self,
        key_pix: int,
        status: str,
        date: Optional[datetime] = None,
        metadata_key: Optional[UUID] = None,
    ) -> StatusResultHistory:
        history = StatusResultHistory()
        history.key_pix = key_pix
        history.status = status
        if date:
            history.date = date
        history.metadata_key = metadata_key

        self.session.add(history)
        return history

    def get_latest_by_pix(self, key_pix: int) -> Optional[StatusResultHistory]:
        return (
            self.session.query(StatusResultHistory)
            .filter(StatusResultHistory.key_pix == key_pix)
            .order_by(StatusResultHistory.date.desc())
            .first()
        )
