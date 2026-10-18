"""Regras da v2 pela porta da frente: faixas da R2, escopo do desconto da R7, N1, N2 e R9.

Substitui os antigos testes de unidade (tests/unit/), que importavam o src/.
Aqui tudo passa pela API: cada teste monta o próprio pedaço do grafo com
POST /pix/transaction e confere só o que volta (status, reasons, risk_score).
Os pesos citados nos comentários são os de regras_antifraude.txt; o teste não
lê o config.py.
"""
import uuid
from datetime import datetime, timedelta

import pytest

from tests.utils import ObjectGenerator, PayloadGenerator, RandomGenerator
from tests.utils.payload_generator import DAY, NIGHT, OLD_ACCOUNT, only_digits

OUR_ISPB = "00000000"
OUR_BRANCH = "0001"


def at(base: str, **delta) -> str:
    return (datetime.fromisoformat(base) + timedelta(**delta)).isoformat()


def score(response: dict) -> float:
    return response["metadata"]["risk_score"]


def reasons(response: dict) -> list:
    return response["metadata"].get("reasons", [])


def random_ip() -> str:
    """IP de documentação (TEST-NET-3) que nenhum outro teste usa."""
    digest = uuid.uuid4().bytes
    return f"203.{digest[0]}.{digest[1]}.{digest[2] or 1}"


def new_customer() -> dict:
    """Conta nossa com dispositivo cadastrado (sem R1 no caminho)."""
    customer = {
        "source_document_number": RandomGenerator.generate_cpf(),
        "source_account_number": PayloadGenerator.random_account_number(),
        "device_id": PayloadGenerator.random_device_id(),
    }
    ObjectGenerator.register_device(only_digits(customer["source_document_number"]), customer["device_id"])
    return customer


def pix(**kwargs) -> dict:
    return ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(**kwargs))


class TestR2Bands:
    """Faixas da R2 sobre a média noturna (R$ 200): > 3x pesa 0.20, > 5x pesa 0.40.

    Quatro noites de histórico: a R2 já vale (>= 3 noites) e a R6 ainda não
    (precisa de 5 Pix), então a R2 é o único sinal de valor no score.
    """

    def customer_with_nights(self, nights: int = 4, amount: int = 20000) -> dict:
        customer = new_customer()
        for days_ago in range(nights + 5, 5, -1):
            pix(amount=amount, transaction_date=at(NIGHT, days=-days_ago), destination_opening_date=OLD_ACCOUNT,
                **customer)
        return customer

    def night_pix(self, amount: int) -> dict:
        return pix(amount=amount, transaction_date=at(NIGHT, minutes=45), **self.customer_with_nights())

    def test_exactly_three_times_the_average_passes(self):
        assert "desvio_noturno" not in reasons(self.night_pix(60000))

    def test_just_above_three_times_adds_weight_without_rejecting(self):
        response = self.night_pix(60001)
        assert "desvio_noturno" in reasons(response)
        assert response["status"] != "rejected"

    def test_exactly_five_times_is_still_the_moderate_band(self):
        moderate = self.night_pix(60001)
        five_times = self.night_pix(100000)
        assert "desvio_noturno" in reasons(five_times)
        # Mesmo peso (0.20): mesmos sinais, mesmo histórico, mesmo score.
        assert reasons(five_times) == reasons(moderate)
        assert score(five_times) == pytest.approx(score(moderate), abs=0.005)

    def test_above_five_times_weighs_more(self):
        moderate = self.night_pix(100000)
        high = self.night_pix(100001)
        assert reasons(high) == reasons(moderate)
        assert high["status"] != "rejected"
        # 0.40 contra 0.20 no noisy-OR: a diferença aparece no score.
        assert score(high) > score(moderate) + 0.05


class TestR7DiscountScope:
    """O desconto da R7 só alcança a família desvio de valor (R2/R6), nunca os outros sinais."""

    def customer_paying_rent(self):
        customer = new_customer()
        for day in range(85, 26, -1):  # ~60 Pix pequenos de R$ 50 nos últimos 90 dias
            pix(amount=5000, transaction_date=at(DAY, days=-day, hours=-3), destination_opening_date=OLD_ACCOUNT,
                **customer)
        landlord = {
            "destination_document_number": RandomGenerator.generate_cpf(),
            "destination_account_number": PayloadGenerator.random_account_number(),
            "destination_opening_date": OLD_ACCOUNT,
        }
        for days_ago in (120, 90, 60, 30):  # aluguel de R$ 1.500 todo mês
            pix(amount=150000, transaction_date=at(DAY, days=-days_ago), **landlord, **customer)
        return customer, landlord

    def test_discount_does_not_reach_independent_signal(self):
        with_geo_customer, with_geo_landlord = self.customer_paying_rent()
        without_geo_customer, without_geo_landlord = self.customer_paying_rent()

        rent = pix(amount=150000, transaction_date=DAY, **with_geo_landlord, **with_geo_customer)
        rent_without_geo = pix(
            amount=150000, transaction_date=DAY, include_geolocation=False,
            **without_geo_landlord, **without_geo_customer,
        )

        assert "pagamento_recorrente" in reasons(rent)
        assert set(reasons(rent_without_geo)) == set(reasons(rent)) | {"sem_geolocalizacao"}
        # Sem geolocalização entra um peso independente de 0.10 inteiro: se o
        # desconto da R7 alcançasse esse sinal, ele entraria menor que 0.10.
        assert 1 - score(rent_without_geo) == pytest.approx((1 - score(rent)) * (1 - 0.10), abs=0.003)


class TestN1SharedIp:
    """N1: o mesmo IP em 3 contas de origem diferentes em 24h pesa."""

    def test_third_account_on_same_ip_adds_weight(self):
        ip = random_ip()
        responses = [
            pix(amount=5000, transaction_date=at(DAY, hours=hour), ip=ip, **new_customer())
            for hour in range(3)
        ]
        assert "ip_compartilhado" not in reasons(responses[1])
        assert "ip_compartilhado" in reasons(responses[2])

    def test_same_account_on_same_ip_is_not_shared(self):
        ip, customer = random_ip(), new_customer()
        responses = [pix(amount=5000, transaction_date=at(DAY, hours=hour), ip=ip, **customer) for hour in range(3)]
        assert all("ip_compartilhado" not in reasons(response) for response in responses)


class TestN2AccountTakeoverCombo:
    """N2: dispositivo não cadastrado + IP nunca visto na origem + destino desconhecido -> 2FA."""

    def customer_with_history(self) -> dict:
        customer = new_customer()
        customer["ip"] = random_ip()
        pix(amount=5000, transaction_date=at(DAY, days=-3), destination_opening_date=OLD_ACCOUNT, **customer)
        return customer

    def from_new_device(self, customer: dict, ip: str) -> dict:
        # Abaixo de R$ 200: a R1 só pesa, não rejeita.
        return pix(
            amount=5000, transaction_date=DAY, destination_opening_date=OLD_ACCOUNT,
            source_document_number=customer["source_document_number"],
            source_account_number=customer["source_account_number"],
            device_id=PayloadGenerator.random_device_id(), ip=ip,
        )

    def test_new_device_new_ip_unknown_destination_asks_2fa(self):
        response = self.from_new_device(self.customer_with_history(), random_ip())
        assert response["status"] == "two_factor_required"
        assert "combo_tomada_conta" in reasons(response)

    def test_known_ip_breaks_the_combo(self):
        customer = self.customer_with_history()
        response = self.from_new_device(customer, customer["ip"])
        assert "combo_tomada_conta" not in reasons(response)
        assert "dispositivo_nao_cadastrado" in reasons(response)

    def test_first_pix_of_the_account_has_no_ip_history(self):
        response = pix(amount=5000, transaction_date=DAY, destination_opening_date=OLD_ACCOUNT, ip=random_ip())
        assert "combo_tomada_conta" not in reasons(response)
        assert "dispositivo_nao_cadastrado" in reasons(response)


class TestR9PassThrough:
    """R9: recebe de muitas origens (fan-in >= 8), repassa para poucos destinos
    (fan-out <= 3) e não retém o dinheiro (saiu / entrou >= 0.80) -> 2FA.
    """

    def as_destination(self, account: dict) -> dict:
        return {
            "destination_participant": OUR_ISPB,
            "destination_branch": OUR_BRANCH,
            "destination_account_number": account["source_account_number"],
            "destination_document_number": account["source_document_number"],
            "destination_opening_date": OLD_ACCOUNT,
        }

    def receive(self, account: dict, senders: int, amount: int = 10000) -> None:
        """`senders` origens diferentes pagam a conta, uma por dia (longe do fan-in de 1h da R8)."""
        for day in range(senders):
            pix(amount=amount, transaction_date=at(DAY, days=-30 + day), **self.as_destination(account),
                **new_customer())

    def pay_out(self, account: dict, amounts: list) -> None:
        """A conta paga um destino diferente por valor, dias depois de receber."""
        for index, amount in enumerate(amounts):
            pix(amount=amount, transaction_date=at(DAY, days=-10 + index), destination_opening_date=OLD_ACCOUNT,
                **account)

    def mule(self) -> dict:
        """Recebeu R$ 800 de 8 origens e repassou R$ 700 para um destino só (ratio 0.875)."""
        account = new_customer()
        self.receive(account, senders=8)
        self.pay_out(account, [70000])
        return account

    def test_destination_pass_through_asks_2fa(self):
        response = pix(amount=5000, transaction_date=DAY, **self.as_destination(self.mule()), **new_customer())
        assert response["status"] == "two_factor_required"
        assert "destino_conta_passagem" in reasons(response)
        assert "origem_conta_passagem" not in reasons(response)

    def test_source_pass_through_asks_2fa(self):
        response = pix(amount=5000, transaction_date=DAY, destination_opening_date=OLD_ACCOUNT, **self.mule())
        assert response["status"] == "two_factor_required"
        assert "origem_conta_passagem" in reasons(response)
        assert "destino_conta_passagem" not in reasons(response)

    def test_both_sides_can_fire(self):
        response = pix(amount=5000, transaction_date=DAY, **self.as_destination(self.mule()), **self.mule())
        assert response["status"] == "two_factor_required"
        assert {"origem_conta_passagem", "destino_conta_passagem"} <= set(reasons(response))

    def test_low_fan_in_does_not_fire(self):
        account = new_customer()
        self.receive(account, senders=7)  # uma origem a menos que o mínimo
        self.pay_out(account, [65000])    # ratio 0.93
        # A saída vem antes: o Pix recebido em seguida já seria a 8ª origem.
        from_account = pix(amount=1000, transaction_date=DAY, destination_opening_date=OLD_ACCOUNT, **account)
        to_account = pix(amount=5000, transaction_date=DAY, **self.as_destination(account), **new_customer())
        assert "origem_conta_passagem" not in reasons(from_account)
        assert "destino_conta_passagem" not in reasons(to_account)

    def test_high_fan_out_does_not_fire(self):
        # Recebe de muitos e espalha para muitos destinos: parece varejo, não mula.
        account = new_customer()
        self.receive(account, senders=8)
        self.pay_out(account, [17500, 17500, 17500, 17500])  # 4 destinos, ratio 0.875
        response = pix(amount=5000, transaction_date=DAY, **self.as_destination(account), **new_customer())
        assert "destino_conta_passagem" not in reasons(response)

    def test_account_that_retains_money_does_not_fire(self):
        # Recebe de muitos e repassa pouco (ratio 0.125): varejista legítimo.
        account = new_customer()
        self.receive(account, senders=8)
        self.pay_out(account, [10000])
        response = pix(amount=5000, transaction_date=DAY, **self.as_destination(account), **new_customer())
        assert "destino_conta_passagem" not in reasons(response)

    def test_account_that_never_received_does_not_fire(self):
        # Nada entrou: não há o que repassar, mesmo pagando para poucos destinos.
        account = new_customer()
        self.pay_out(account, [5000, 5000])
        response = pix(amount=5000, transaction_date=DAY, destination_opening_date=OLD_ACCOUNT, **account)
        assert "origem_conta_passagem" not in reasons(response)
