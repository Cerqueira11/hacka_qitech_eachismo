"""O grafo visto de fora: o risco de uma conta contamina quem transaciona com ela.

O teste não olha o banco. Ele compara dois Pix idênticos (mesmo valor, mesma
hora, mesmos sinais de regra) cuja única diferença é a vizinhança da conta de
destino — e cobra que o risk_score reflita essa diferença.
"""

from datetime import datetime, timedelta

from tests.utils import ObjectGenerator, PayloadGenerator, RandomGenerator
from tests.utils import dict_personas as persona
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
    def test_neighbor_under_analysis_raises_destination_risk(self):
        clean = build_neighborhood(RandomGenerator.generate_cpf())
        exposed = build_neighborhood(persona.UNDER_ANALYSIS)
        # O Pix para a conta em análise pediu 2FA, não foi rejeitado: a ligação existe.
        assert exposed["first_hop_status"] == "two_factor_required"

        to_clean = pay(clean)
        to_exposed = pay(exposed)

        # Mesmas regras acionadas nos dois; só a vizinhança muda.
        assert to_clean["metadata"]["reasons"] == to_exposed["metadata"]["reasons"]
        assert score(to_exposed) > score(to_clean) + 0.05

    def test_rejected_pix_does_not_propagate(self):
        clean = build_neighborhood(RandomGenerator.generate_cpf())
        blocked = build_neighborhood(persona.MULE)
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
