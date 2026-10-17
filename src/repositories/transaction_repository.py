from typing import List, Optional
from uuid import UUID

from database import Context
from dtos.pix_transaction_input import PixTransactionInput
from models import AccountNode, Geolocation, TransactionHistory


class TransactionRepository:
    """A camada que fala com a tabela transaction_history (as arestas do grafo)."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(
        self,
        data: PixTransactionInput,
        source_account: AccountNode,
        destination_account: AccountNode,
        geolocation: Optional[Geolocation] = None,
        risk_score: Optional[float] = None,
    ) -> TransactionHistory:
        tx = TransactionHistory(
            transaction_id=data.transaction_id,
            amount=data.amount,
            source_device_id=data.device_id,
            source_device_channel=data.channel,
            source_ip=data.ip,
            transaction_date=data.transaction_date,
            risk_score=risk_score,
        )
        # Relações em vez de ids: as chaves geradas no INSERT só existem
        # depois do flush, e o SQLAlchemy resolve a ordem sozinho.
        tx.source_account = source_account
        tx.destination_account = destination_account
        tx.geolocation = geolocation
        self.session.add(tx)
        return tx

    def get_by_key_pix(self, key_pix: int) -> Optional[TransactionHistory]:
        return (
            self.session.query(TransactionHistory)
            .filter(TransactionHistory.key_pix == key_pix)
            .first()
        )

    def get_by_transaction_id(self, transaction_id: str) -> Optional[TransactionHistory]:
        return (
            self.session.query(TransactionHistory)
            .filter(TransactionHistory.transaction_id == transaction_id)
            .first()
        )

    def list_by_source_account(self, account_id: UUID, limit: int = 100) -> List[TransactionHistory]:
        return (
            self.session.query(TransactionHistory)
            .filter(TransactionHistory.source_account_id == account_id)
            .order_by(TransactionHistory.transaction_date.desc())
            .limit(limit)
            .all()
        )

    def list_by_destination_account(self, account_id: UUID, limit: int = 100) -> List[TransactionHistory]:
        return (
            self.session.query(TransactionHistory)
            .filter(TransactionHistory.destination_account_id == account_id)
            .order_by(TransactionHistory.transaction_date.desc())
            .limit(limit)
            .all()
        )

    def list_by_device(self, device_id: str, limit: int = 100) -> List[TransactionHistory]:
        return (
            self.session.query(TransactionHistory)
            .filter(TransactionHistory.source_device_id == device_id)
            .order_by(TransactionHistory.transaction_date.desc())
            .limit(limit)
            .all()
        )
