"""A API externa de dispositivo (R1), do ponto de vista do teste.

Quem responde no docker compose é o mockserver: sem expectativa cadastrada
ele devolve 404, que a R1 lê como "dispositivo não cadastrado". Por isso só
os casos "cadastrado" e "fora do ar" precisam de expectativa.

O motor olha registered_device antes: um device que a API já confirmou uma
vez não gera nova chamada.
"""

from urllib.parse import quote

from tests.utils.mock_utils import BaseExpectation, Mock
from tests.utils.payload_generator import only_digits


def device_path(document_number: str, device_id: str) -> str:
    return f"/devices/{quote(only_digits(document_number), safe='')}/{quote(device_id, safe='')}"


class DeviceApiMock:
    @staticmethod
    def registered(document_number: str, device_id: str, times: int = None) -> None:
        """A API responde 200 "registered": true. Com `times`, só nas próximas `times` chamadas
        (depois disso o mockserver volta ao 404)."""
        Mock().add_expectations(
            BaseExpectation.generate_expectation(
                "GET",
                device_path(document_number, device_id),
                {"document_number": only_digits(document_number), "device_id": device_id, "registered": True},
                200,
                number_of_calls=times,
            )
        )

    @staticmethod
    def calls(document_number: str, device_id: str) -> int:
        """Quantas vezes o motor chamou a API para este (documento, device)."""
        return len(Mock().retrieve_requests(method="GET", path=device_path(document_number, device_id)))

    @staticmethod
    def unavailable(document_number: str, device_id: str, status_code: int = 503) -> None:
        Mock().add_expectations(
            BaseExpectation.generate_expectation(
                "GET",
                device_path(document_number, device_id),
                {"message": "Service Unavailable"},
                status_code,
            )
        )
