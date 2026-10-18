"""A API externa de dispositivo (R1), do ponto de vista do teste.

Quem responde no docker compose é o mockserver: sem expectativa cadastrada
ele devolve 404, que a R1 lê como "dispositivo não cadastrado". Por isso só
os casos "cadastrado" e "fora do ar" precisam de expectativa.
"""

from urllib.parse import quote

from tests.utils.mock_utils import BaseExpectation, Mock
from tests.utils.payload_generator import only_digits


def device_path(document_number: str, device_id: str) -> str:
    return f"/devices/{quote(only_digits(document_number), safe='')}/{quote(device_id, safe='')}"


class DeviceApiMock:
    @staticmethod
    def registered(document_number: str, device_id: str) -> None:
        Mock().add_expectations(
            BaseExpectation.generate_expectation(
                "GET",
                device_path(document_number, device_id),
                {"document_number": only_digits(document_number), "device_id": device_id, "registered": True},
                200,
            )
        )

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
