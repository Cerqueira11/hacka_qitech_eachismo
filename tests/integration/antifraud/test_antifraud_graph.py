"""Testes black-box da propagação de risco no grafo através da API."""

from datetime import datetime, timedelta

from tests.utils import ObjectGenerator, PayloadGenerator, RandomGenerator
from tests.utils.dict_api_mock import DictApiMock
from tests.utils.payload_generator import DAY, OLD_ACCOUNT, only_digits
from tests.utils.request_generator import RequestGenerator

TWO_DAYS_AGO = (datetime.fromisoformat(DAY) - timedelta(days=2)).isoformat()


def score(response: dict) -> float:
    return response["metadata"]["risk_score"]


def build_neighborhood(neighbor_document: str) -> dict:
    """Conta A (nossa) pagou, dois dias atrás, uma conta cujo titular é `neighbor_document`.

    Devolve a conta A para servir de destino do Pix seguinte.
    """
    account_a = PayloadGenerator.random_account_number()
    owner_a = RandomGenerator.generate_cpf()
    device_a = PayloadGenerator.random_device_id()
    ObjectGenerator.register_device(only_digits(owner_a), device_a)
    payload = PayloadGenerator.create_pix_transaction_payload(
        amount=5000, transaction_date=TWO_DAYS_AGO, source_document_number=owner_a,
        source_account_number=account_a, device_id=device_a,
        destination_document_number=neighbor_document, destination_opening_date=OLD_ACCOUNT,
    )
    status, response = RequestGenerator.POST_pix_transaction(payload)
    assert status == 201, response
    return {"account": account_a, "owner": owner_a, "first_hop_status": response["status"]}


def pay(account: dict) -> dict:
    """Um Pix novo, de uma origem limpa e com dispositivo cadastrado, para a conta A."""
    _, response = ObjectGenerator.create_pix_from_registered_device(
        amount=5000, transaction_date=DAY,
        destination_participant="00000000", destination_branch="0001",
        destination_account_number=account["account"], destination_document_number=account["owner"],
        destination_opening_date="2025-03-02T10:00:00-03:00",
    )
    return response


class TestGraphPropagation:
    def test_neighbor_edge_risk_raises_destination_score(self):
        account_a = PayloadGenerator.random_account_number()
        owner_a = RandomGenerator.generate_cpf()
        device_a = PayloadGenerator.random_device_id()
        ObjectGenerator.register_device(only_digits(owner_a), device_a)

        payload = PayloadGenerator.create_pix_transaction_payload(
            amount=5000,
            transaction_date=TWO_DAYS_AGO,
            source_document_number=owner_a,
            source_account_number=account_a,
            source_opening_date=OLD_ACCOUNT,
            destination_document_number=RandomGenerator.generate_cpf(),
            destination_opening_date=OLD_ACCOUNT,
            device_id=device_a,
            include_geolocation=False,
        )
        status, edge_response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201, edge_response
        assert edge_response["status"] == "approved"
        assert abs(score(edge_response) - 0.19) < 0.01

        downstream = pay({"account": account_a, "owner": owner_a})

        # O score da aresta (0.19) supera o risco aprendido dos seus nós,
        # então deve elevar o score do Pix seguinte que atravessa essa ligação.
        assert score(downstream) > 0.13

    def test_neighbor_under_analysis_raises_destination_risk(self):
        clean = build_neighborhood(RandomGenerator.generate_cpf())
        under_analysis = RandomGenerator.generate_cpf()
        DictApiMock.under_analysis(under_analysis)
        exposed = build_neighborhood(under_analysis)
        # O Pix para a conta em análise pediu 2FA, não foi rejeitado: a ligação existe.
        assert exposed["first_hop_status"] == "two_factor_required"

        to_clean = pay(clean)
        to_exposed = pay(exposed)

        # Mesmas regras acionadas nos dois; só a vizinhança muda.
        assert to_clean["metadata"]["reasons"] == to_exposed["metadata"]["reasons"]
        assert score(to_exposed) > score(to_clean) + 0.05

    def test_rejected_pix_does_not_propagate(self):
        clean = build_neighborhood(RandomGenerator.generate_cpf())
        mule = RandomGenerator.generate_cpf()
        DictApiMock.mule(mule)
        blocked = build_neighborhood(mule)
        # O Pix para o laranja foi barrado: o dinheiro não passou por essa aresta.
        assert blocked["first_hop_status"] == "rejected"

        to_clean = pay(clean)
        to_blocked = pay(blocked)

        assert abs(score(to_blocked) - score(to_clean)) < 0.02

    def test_destination_learns_from_suspicious_pix(self):
        destination = PayloadGenerator.random_account_number()
        owner = RandomGenerator.generate_cpf()

        def pix_without_geolocation(minute: int) -> dict:
            # Origens diferentes, sem geolocalização e com dispositivo novo: os
            # mesmos sinais fracos em todo Pix.
            payload = PayloadGenerator.create_pix_transaction_payload(
                amount=5000, transaction_date=(datetime.fromisoformat(DAY) + timedelta(minutes=minute)).isoformat(),
                destination_account_number=destination, destination_document_number=owner,
                include_geolocation=False,
            )
            return ObjectGenerator.create_pix_transaction(payload)

        first = pix_without_geolocation(0)
        later = [pix_without_geolocation(minute) for minute in (5, 10, 15)]

        assert all(response["metadata"]["reasons"] == first["metadata"]["reasons"] for response in later)
        # Mesmas regras a cada Pix; o score sobe porque o destino acumula risco.
        assert score(later[0]) > score(first)
        assert score(later[-1]) > score(later[0])
