from os import environ

from tests.utils.requisition import ClientRequisition, BaseConnectorResponse

INTERNAL_TOKEN = environ.get("INTERNAL_TOKEN", "default_token")


class RequestGenerator:
    """Envia requisições HTTP prontas para os testes de integração."""

    @staticmethod
    def POST_pix_transaction(payload: dict) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "POST",
            "/pix/transaction",
            payload=payload,
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def GET_pix_transaction(transaction_id: str) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "GET",
            f"/pix/transaction/{transaction_id}",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def POST_device(payload: dict, token: str = INTERNAL_TOKEN) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "POST",
            "/device",
            payload=payload,
            headers={"INTERNAL-TOKEN": token},
        )
        return response.response_status, response.response_json

    @staticmethod
    def POST_person_link(payload: dict, token: str = INTERNAL_TOKEN) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "POST",
            "/person_link",
            payload=payload,
            headers={"INTERNAL-TOKEN": token},
        )
        return response.response_status, response.response_json
