from typing import Optional, Tuple

from tests.utils.payload_generator import PayloadGenerator, only_digits
from tests.utils.request_generator import RequestGenerator


class ObjectGenerator:
    """Cria entidades através da API para preparação de cenários de teste."""

    @staticmethod
    def create_pix_transaction(payload: Optional[dict] = None) -> dict:
        if payload is None:
            payload = PayloadGenerator.create_pix_transaction_payload()
        status, response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201, response
        return response

    @staticmethod
    def register_device(document_number: str, device_id: str) -> None:
        status, response = RequestGenerator.POST_device(
            PayloadGenerator.create_device_payload(document_number, device_id)
        )
        assert status in (200, 201), response

    @staticmethod
    def create_pix_from_registered_device(**kwargs) -> Tuple[dict, dict]:
        """Cadastra o dispositivo da origem antes do Pix: tira a R1 do caminho.

        Devolve (payload, resposta).
        """
        payload = PayloadGenerator.create_pix_transaction_payload(**kwargs)
        ObjectGenerator.register_device(
            only_digits(payload["source_account"]["owner"]["document_number"]),
            payload["source"]["device_id"],
        )
        return payload, ObjectGenerator.create_pix_transaction(payload)
