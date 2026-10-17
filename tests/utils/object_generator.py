from typing import Optional

from tests.utils.payload_generator import PayloadGenerator
from tests.utils.request_generator import RequestGenerator


class ObjectGenerator:
    """Cria entidades através da API para preparação de cenários de teste."""

    @staticmethod
    def create_pix_transaction(payload: Optional[dict] = None) -> dict:
        if payload is None:
            payload = PayloadGenerator.create_pix_transaction_payload()

        status, response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        return response
