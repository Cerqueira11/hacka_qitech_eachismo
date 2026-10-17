from typing import List, Optional
from models import TransactionHistory


class PixTransactionDTO:
    """Traduz o modelo de transação PIX e seus resultados para dicionários serializáveis em JSON."""

    @staticmethod
    def obj_to_dict(transaction: TransactionHistory) -> dict:
        dto = dict()
        dto["key_pix"] = transaction.key_pix
        dto["amount"] = transaction.amount
        dto["source_account_branch"] = transaction.source_account_branch
        dto["source_account_number"] = transaction.source_account_number
        dto["destination_account_branch"] = transaction.destination_account_branch
        dto["destination_account_number"] = transaction.destination_account_number
        dto["source_device_id"] = transaction.source_device_id
        dto["source_device_channel"] = transaction.source_device_channel
        dto["source_ip"] = str(transaction.source_ip) if transaction.source_ip else None
        dto["transaction_date"] = (
            transaction.transaction_date.isoformat() if transaction.transaction_date else None
        )

        if transaction.geolocation:
            dto["geolocation"] = {
                "id_geolocation": str(transaction.geolocation.id_geolocation),
                "latitude": float(transaction.geolocation.latitude),
                "longitude": float(transaction.geolocation.longitude),
            }
        else:
            dto["geolocation"] = None

        dto["status_history"] = []
        if transaction.status_history:
            for item in transaction.status_history:
                dto["status_history"].append(
                    {
                        "key": str(item.key),
                        "status": item.status,
                        "date": item.date.isoformat() if item.date else None,
                        "metadata_key": str(item.metadata_key) if item.metadata_key else None,
                    }
                )
            dto["status"] = transaction.status_history[0].status
        else:
            dto["status"] = None

        return dto

    @staticmethod
    def only_key(transaction: TransactionHistory, status: Optional[str] = None) -> dict:
        current_status = status
        if current_status is None and transaction.status_history:
            current_status = transaction.status_history[0].status

        return {
            "key_pix": transaction.key_pix,
            "status": current_status,
        }

    @staticmethod
    def list_obj_to_list_dict(transactions: List[TransactionHistory]) -> List[dict]:
        return [PixTransactionDTO.obj_to_dict(t) for t in transactions]
