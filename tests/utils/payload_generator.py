import uuid
from typing import Optional


class PayloadGenerator:
    """Gera payloads prontos para os testes da API."""

    @staticmethod
    def create_pix_transaction_payload(
        amount: int = 15000,
        source_account_branch: int = 1,
        source_account_number: int = 1001,
        destination_account_branch: int = 1,
        destination_account_number: int = 2002,
        source_device_id: Optional[str] = None,
        source_device_channel: str = "MOBILE",
        source_ip: str = "192.168.0.10",
        latitude: float = -23.55052,
        longitude: float = -46.633308,
        include_geolocation: bool = True,
        transaction_date: Optional[str] = "2026-10-17T12:00:00-03:00",
        **kwargs,
    ) -> dict:
        if source_device_id is None:
            source_device_id = f"dev-{uuid.uuid4().hex[:12]}"

        payload = {
            "amount": amount,
            "source_account_branch": source_account_branch,
            "source_account_number": source_account_number,
            "destination_account_branch": destination_account_branch,
            "destination_account_number": destination_account_number,
            "source_device_id": source_device_id,
            "source_device_channel": source_device_channel,
            "source_ip": source_ip,
        }

        if include_geolocation:
            payload["geolocation"] = {
                "latitude": latitude,
                "longitude": longitude,
            }

        if transaction_date:
            payload["transaction_date"] = transaction_date

        payload.update(kwargs)
        return payload
