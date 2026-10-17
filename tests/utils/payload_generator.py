import random
import uuid
from typing import Optional

from tests.utils.random_generator import RandomGenerator


class PayloadGenerator:
    """Gera payloads prontos para os testes da API."""

    @staticmethod
    def create_pix_transaction_payload(
        transaction_id: Optional[str] = None,
        amount: int = 150000,
        transaction_date: str = "2026-10-17T22:15:00-03:00",
        source_document_number: Optional[str] = None,
        destination_document_number: Optional[str] = None,
        source_branch: str = "0001",
        source_account_number: Optional[str] = None,
        destination_participant: str = "60701190",
        destination_branch: str = "3675",
        destination_account_number: Optional[str] = None,
        device_id: Optional[str] = None,
        channel: str = "app",
        ip: str = "198.51.100.23",
        latitude: float = -23.56,
        longitude: float = -46.65,
        include_geolocation: bool = True,
    ) -> dict:
        # Ids e contas aleatórios: cada teste cria o próprio Pix sem esbarrar
        # na idempotência (mesmo "id") nem no grafo de outro teste.
        if transaction_id is None:
            transaction_id = f"pix-{uuid.uuid4().hex[:16]}"
        if source_account_number is None:
            source_account_number = str(random.randrange(10_000, 99_999_999))
        if destination_account_number is None:
            destination_account_number = str(random.randrange(10_000, 99_999_999))
        if device_id is None:
            device_id = f"dvc-{uuid.uuid4().hex[:8]}"

        source = {
            "device_id": device_id,
            "channel": channel,
            "ip": ip,
        }
        if include_geolocation:
            source["geolocation"] = {"latitude": latitude, "longitude": longitude}

        return {
            "id": transaction_id,
            "amount": amount,
            "transaction_date": transaction_date,
            "source_account": {
                "branch": source_branch,
                "account_number": source_account_number,
                "opening_date": "2025-03-02T10:00:00-03:00",
                "owner": {"document_number": source_document_number or RandomGenerator.generate_cpf()},
            },
            "destination_account": {
                "participant": destination_participant,
                "branch": destination_branch,
                "account_number": destination_account_number,
                "opening_date": "2026-10-10T09:00:00-03:00",
                "owner": {"document_number": destination_document_number or RandomGenerator.generate_cpf()},
            },
            "source": source,
        }
