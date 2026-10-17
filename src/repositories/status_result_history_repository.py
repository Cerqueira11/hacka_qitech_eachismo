from datetime import datetime, timezone
from typing import Optional

from database import Context
from models import Metadata, StatusResultHistory, TransactionHistory


class StatusResultHistoryRepository:
    """A camada que fala com a tabela status_result_history."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(
        self,
        transaction: TransactionHistory,
        status: str,
        metadata: Optional[Metadata] = None,
        date: Optional[datetime] = None,
    ) -> StatusResultHistory:
        """Registra um veredito ligado à transação pela relação, não pelo key_pix.

        O key_pix só existe depois do INSERT da transação. Pendurando o
        veredito na relação, o SQLAlchemy grava a transação primeiro e preenche
        a chave estrangeira sozinho no flush.

        `date` é quando o veredito foi dado (agora), não quando o Pix aconteceu.
        """
        history = StatusResultHistory(
            status=status,
            date=date or datetime.now(timezone.utc),
            metadata_item=metadata,
        )
        transaction.status_history.append(history)
        self.session.add(history)
        return history

    def get_latest_by_pix(self, key_pix: int) -> Optional[StatusResultHistory]:
        return (
            self.session.query(StatusResultHistory)
            .filter(StatusResultHistory.key_pix == key_pix)
            .order_by(StatusResultHistory.date.desc())
            .first()
        )
