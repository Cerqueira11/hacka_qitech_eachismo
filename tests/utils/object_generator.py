from typing import Optional, Tuple

from tests.utils.device_api_mock import DeviceApiMock
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
        """Faz a API de dispositivo (mockserver) responder "registered": true.

        No primeiro Pix o motor não acha o device em registered_device, chama a
        API, recebe o 200 e grava na tabela.
        """
        DeviceApiMock.registered(only_digits(document_number), device_id)

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
