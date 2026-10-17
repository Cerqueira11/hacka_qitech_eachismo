from datetime import datetime
from typing import List, Optional
from uuid import UUID

from database import Context
from models import TransactionHistory


class TransactionRepository:
    """A camada que fala com a tabela transaction_history."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(
        self,
        transaction_data: dict,
        geolocation_id: Optional[UUID] = None,
    ) -> TransactionHistory:
        tx = TransactionHistory()
        tx.amount = transaction_data["amount"]
        tx.source_account_branch = transaction_data["source_account_branch"]
        tx.source_account_number = transaction_data["source_account_number"]
        tx.destination_account_branch = transaction_data["destination_account_branch"]
        tx.destination_account_number = transaction_data["destination_account_number"]
        tx.source_device_id = transaction_data["source_device_id"]
        tx.source_device_channel = transaction_data["source_device_channel"]
        tx.source_ip = transaction_data["source_ip"]
        tx.source_geolocation = geolocation_id

        if "transaction_date" in transaction_data and transaction_data["transaction_date"]:
            if isinstance(transaction_data["transaction_date"], str):
                tx.transaction_date = datetime.fromisoformat(transaction_data["transaction_date"])
            else:
                tx.transaction_date = transaction_data["transaction_date"]

        self.session.add(tx)
        return tx

    def get_by_key_pix(self, key_pix: int) -> Optional[TransactionHistory]:
        return (
            self.session.query(TransactionHistory)
            .filter(TransactionHistory.key_pix == key_pix)
            .first()
        )

    def list_by_source_account(
        self, branch: int, number: int, limit: int = 100
    ) -> List[TransactionHistory]:
        return (
            self.session.query(TransactionHistory)
            .filter(
                TransactionHistory.source_account_branch == branch,
                TransactionHistory.source_account_number == number,
            )
            .order_by(TransactionHistory.transaction_date.desc())
            .limit(limit)
            .all()
        )

    def list_by_destination_account(
        self, branch: int, number: int, limit: int = 100
    ) -> List[TransactionHistory]:
        return (
            self.session.query(TransactionHistory)
            .filter(
                TransactionHistory.destination_account_branch == branch,
                TransactionHistory.destination_account_number == number,
            )
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
