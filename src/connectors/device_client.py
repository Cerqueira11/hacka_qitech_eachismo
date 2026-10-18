"""Cliente da API externa de dispositivo cadastrado (R1, decisão S2).

O formato real da API ainda não existe. O contrato abaixo é a suposição
usada pelo mock, e o motor depende de um campo só, o booleano "registered":

    GET /devices/{document_number}/{device_id}
      200 {"document_number": "...", "device_id": "...", "registered": true}
      404 -> registered = false (dispositivo desconhecido)

Só é chamada quando o device não está em registered_device (DeviceRepository).

Qualquer outra coisa (timeout, erro de rede, 5xx, 429, 200 sem o booleano)
vira DeviceApiUnavailable: quem chama decide o que fazer (a R1 pede 2FA).
Se o formato real for diferente, só este arquivo muda.
"""

from urllib.parse import quote

import requests

from connectors.rest_connector import RestConnector
from constants import DEVICE_API_INTERNAL_TOKEN, DEVICE_API_TIMEOUT, DEVICE_API_URL


class DeviceApiUnavailable(Exception):
    """A API de dispositivo não respondeu de forma utilizável."""


class DeviceApiClient(RestConnector):
    def __init__(
        self,
        base_url: str = DEVICE_API_URL,
        timeout: float = DEVICE_API_TIMEOUT,
        internal_token: str = DEVICE_API_INTERNAL_TOKEN,
    ) -> None:
        super().__init__(__name__, base_url, timeout, internal_token)

    def is_registered(self, document_number: str, device_id: str) -> bool:
        if not self.base_url:
            raise DeviceApiUnavailable("DEVICE_API_URL não configurada")

        endpoint = f"/devices/{quote(document_number, safe='')}/{quote(device_id, safe='')}"
        try:
            response = self.send(endpoint, "GET")
        except requests.RequestException as error:
            raise DeviceApiUnavailable(f"{type(error).__name__}: {error}") from error

        if response.status == 404:
            return False
        if response.status == 200:
            body = response.json if isinstance(response.json, dict) else {}
            registered = body.get("registered")
            if isinstance(registered, bool):
                return registered
            raise DeviceApiUnavailable("200 sem o campo booleano 'registered'")
        raise DeviceApiUnavailable(f"HTTP {response.status}")
