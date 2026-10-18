"""Cenários das regras antifraude (regras_antifraude.txt), de fora para dentro.

Cada teste monta o próprio pedaço do grafo com contas, documentos e
dispositivos aleatórios: os testes podem rodar em qualquer ordem e quantas
vezes quiser, sem limpar o banco. Os scores esperados saem das fórmulas da
ETAPA 4; se os pesos em src/antifraud/config.py mudarem, eles mudam junto.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from tests.utils import ObjectGenerator, PayloadGenerator, RandomGenerator, RequestGenerator
from tests.utils import dict_personas as persona
from tests.utils.device_api_mock import DeviceApiMock
from tests.utils.payload_generator import DAY, NIGHT, OLD_ACCOUNT, only_digits

# Origem desta instituição (INSTITUTION_ISPB padrão): usado quando uma conta
# precisa aparecer como destino e, depois, como origem (o mesmo nó).
OUR_ISPB = "00000000"


def at(base: str, **delta) -> str:
    return (datetime.fromisoformat(base) + timedelta(**delta)).isoformat()


def score(response: dict) -> float:
    return response["metadata"]["risk_score"]


def reasons(response: dict) -> list:
    return response["metadata"].get("reasons", [])


def approx(value: float):
    return pytest.approx(value, abs=1e-4)


def in_parallel(payloads: list) -> list:
    """Dispara todos os POSTs ao mesmo tempo (rajada da mesma origem, C4)."""
    with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
        return list(pool.map(ObjectGenerator.create_pix_transaction, payloads))


class TestStatementExample:
    """O payload do enunciado (R$ 1.500 às 22:15, destino aberto há 7 dias)."""

    def statement_payload(self, device_id: str) -> dict:
        return PayloadGenerator.create_pix_transaction_payload(
            amount=150000,
            transaction_date=NIGHT,
            source_document_number="123.456.789-09",
            destination_document_number="987.654.321-00",
            device_id=device_id,
        )

    def test_unregistered_device_is_rejected(self):
        payload = self.statement_payload(PayloadGenerator.random_device_id())

        response = ObjectGenerator.create_pix_transaction(payload)

        assert response["status"] == "rejected"
        assert "limite_dispositivo_novo" in reasons(response)
        # Limite regulatório não tem piso: o score é só o dos sinais extras.
        assert score(response) == approx(0.28)

    def test_registered_device_is_approved_even_at_night(self):
        device_id = PayloadGenerator.random_device_id()
        ObjectGenerator.register_device("12345678909", device_id)

        response = ObjectGenerator.create_pix_transaction(self.statement_payload(device_id))

        # Sem limite noturno: R$ 1.500 às 22:15 passa.
        assert response["status"] == "approved"
        assert reasons(response) == ["destino_conta_nova", "destino_desconhecido"]
        assert score(response) == approx(0.28)


class TestR1UnregisteredDevice:
    def test_small_amount_passes_with_weight(self):
        payload = PayloadGenerator.create_pix_transaction_payload(amount=15000)

        response = ObjectGenerator.create_pix_transaction(payload)

        assert response["status"] == "approved"
        assert "dispositivo_nao_cadastrado" in reasons(response)
        assert score(response) == approx(1 - 0.85 * 0.8 * 0.9)

    def test_exactly_200_is_allowed(self):
        payload = PayloadGenerator.create_pix_transaction_payload(amount=20000)

        response = ObjectGenerator.create_pix_transaction(payload)

        assert response["status"] == "approved"

    def test_daily_limit_of_1000(self):
        document, account, device = RandomGenerator.generate_cpf(), PayloadGenerator.random_account_number(), "dvc-r1"
        for hour in range(5):  # 5 x R$ 190 = R$ 950 no dia
            ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
                amount=19000, transaction_date=at(DAY, hours=-6 + hour), source_document_number=document,
                source_account_number=account, device_id=device,
            ))

        response = ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
            amount=19000, transaction_date=DAY, source_document_number=document,
            source_account_number=account, device_id=device,
        ))

        assert response["status"] == "rejected"
        assert "limite_dispositivo_novo" in reasons(response)

    def test_unknown_device_over_200_is_rejected(self):
        # Mockserver sem expectativa: 404 -> dispositivo não cadastrado (S2).
        payload = PayloadGenerator.create_pix_transaction_payload(amount=30000, transaction_date=DAY)

        response = ObjectGenerator.create_pix_transaction(payload)

        assert response["status"] == "rejected"
        assert "limite_dispositivo_novo" in reasons(response)

    def test_registered_device_has_no_r1(self):
        _, response = ObjectGenerator.create_pix_from_registered_device(amount=30000, transaction_date=DAY)

        assert "limite_dispositivo_novo" not in reasons(response)
        assert "dispositivo_nao_cadastrado" not in reasons(response)

    def test_device_api_unavailable_asks_2fa(self):
        payload = PayloadGenerator.create_pix_transaction_payload(amount=150000, transaction_date=DAY)
        DeviceApiMock.unavailable(payload["source_account"]["owner"]["document_number"], payload["source"]["device_id"])

        response = ObjectGenerator.create_pix_transaction(payload)

        # Nunca aprovar às cegas, nunca rejeitar por falha nossa.
        assert response["status"] == "two_factor_required"
        assert "device_api_indisponivel" in reasons(response)
        assert "limite_dispositivo_novo" not in reasons(response)

    def test_parallel_burst_respects_daily_limit(self):
        """T3: 6 Pix de R$ 200 ao mesmo tempo, device não cadastrado: no máximo 5 passam."""
        document, account, device = (
            RandomGenerator.generate_cpf(), PayloadGenerator.random_account_number(),
            PayloadGenerator.random_device_id(),
        )
        payloads = [
            PayloadGenerator.create_pix_transaction_payload(
                amount=20000, transaction_date=DAY, source_document_number=document,
                source_account_number=account, device_id=device,
            )
            for _ in range(6)
        ]

        responses = in_parallel(payloads)

        rejected = [r for r in responses if r["status"] == "rejected"]
        assert len(responses) - len(rejected) == 5
        assert len(rejected) == 1
        assert "limite_dispositivo_novo" in reasons(rejected[0])


class TestR2NightPattern:
    """C3: só peso, nunca REJECT; compara a noite corrente com as noites anteriores."""

    def new_customer(self, nights: int = 5, amount: int = 20000):
        """Cliente com `nights` noites anteriores, cada uma com um Pix de `amount` (média noturna = amount)."""
        document, account, device = (
            RandomGenerator.generate_cpf(), PayloadGenerator.random_account_number(),
            PayloadGenerator.random_device_id(),
        )
        ObjectGenerator.register_device(only_digits(document), device)
        for days_ago in range(nights + 5, 5, -1):
            ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
                amount=amount, transaction_date=at(NIGHT, days=-days_ago), source_document_number=document,
                source_account_number=account, device_id=device, destination_opening_date=OLD_ACCOUNT,
            ))
        return document, account, device

    def pix(self, customer, amount: int, when: str) -> dict:
        document, account, device = customer
        return ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
            amount=amount, transaction_date=when, source_document_number=document,
            source_account_number=account, device_id=device,
        ))

    def test_night_spike_adds_weight_but_never_rejects(self):
        """T6: média noturna de R$ 200, R$ 2.000 às 23h -> peso 0.40, sem REJECT."""
        response = self.pix(self.new_customer(), 200000, at(NIGHT, minutes=45))

        assert response["status"] != "rejected"
        assert "desvio_noturno" in reasons(response)

    def test_less_than_three_nights_has_no_weight(self):
        """T7: só duas noites com Pix -> R2 não pesa (o valor isolado fica com a R6)."""
        response = self.pix(self.new_customer(nights=2), 150000, at(NIGHT, minutes=45))

        assert response["status"] != "rejected"
        assert "desvio_noturno" not in reasons(response)

    def test_night_amount_within_pattern_passes(self):
        response = self.pix(self.new_customer(), 25000, at(NIGHT, minutes=45))

        assert response["status"] == "approved"
        assert "desvio_noturno" not in reasons(response)

    def test_day_pix_has_no_r2(self):
        response = self.pix(self.new_customer(), 200000, at(DAY, hours=1))  # 15h

        assert "desvio_noturno" not in reasons(response)
        assert "valor_atipico" in reasons(response)

    def test_night_sum_crosses_midnight(self):
        """A noite é ancorada no início: o Pix da 1h soma com o das 21h do dia anterior."""
        customer = self.new_customer()
        first = self.pix(customer, 40000, at(NIGHT, hours=-1, minutes=-15))     # 21h: 2x a média
        second = self.pix(customer, 30000, at(NIGHT, hours=2, minutes=45))      # 1h: soma 3.5x

        assert "desvio_noturno" not in reasons(first)
        assert "desvio_noturno" in reasons(second)
        assert "valor_atipico" not in reasons(second)  # isolado, R$ 300 está no padrão

    def test_r2_and_r6_count_once(self):
        """R2 e R6 são a mesma família: de noite o peso não dobra (C3)."""
        at_night = self.pix(self.new_customer(), 200000, NIGHT)
        by_day = self.pix(self.new_customer(), 200000, at(NIGHT, hours=-8))

        assert {"desvio_noturno", "valor_atipico"} <= set(reasons(at_night))
        assert "desvio_noturno" not in reasons(by_day)
        assert "valor_atipico" in reasons(by_day)
        assert score(at_night) == pytest.approx(score(by_day), abs=0.005)

    def test_no_night_limit_without_history(self):
        _, response = ObjectGenerator.create_pix_from_registered_device(amount=500000, transaction_date=NIGHT)

        assert response["status"] == "approved"
        assert "desvio_noturno" not in reasons(response)


class TestR3AccountOwner:
    """C2: sem DICT; só nó verificado (que já foi origem) tem documento para divergir."""

    def our_account_pays(self, account: str, owner: str, **kwargs):
        return ObjectGenerator.create_pix_from_registered_device(
            transaction_date=DAY, source_account_number=account, source_document_number=owner, **kwargs,
        )

    def someone_pays(self, account: str, owner: str, **kwargs):
        return ObjectGenerator.create_pix_from_registered_device(
            transaction_date=DAY, destination_participant=OUR_ISPB, destination_branch="0001",
            destination_account_number=account, destination_document_number=owner, **kwargs,
        )

    def test_first_pix_between_unknown_accounts_has_no_r3(self):
        """T2: origem e destino nunca vistos (destino sem chave) -> sem REJECT da R3."""
        _, response = ObjectGenerator.create_pix_from_registered_device(transaction_date=DAY)

        assert "vinculo_nao_confere" not in reasons(response)
        assert response["status"] == "approved"

    def test_verified_source_with_other_document_is_rejected(self):
        account = PayloadGenerator.random_account_number()
        self.our_account_pays(account, RandomGenerator.generate_cpf())

        _, response = self.our_account_pays(account, RandomGenerator.generate_cpf())

        assert response["status"] == "rejected"
        assert "vinculo_nao_confere" in reasons(response)
        assert score(response) == approx(0.80)

    def test_wrong_cpf_as_destination_is_fixed_when_account_pays(self):
        """T5: entrou como destino com CPF errado; ao pagar como origem, o nó é corrigido."""
        account, owner, typo = (
            PayloadGenerator.random_account_number(), RandomGenerator.generate_cpf(), RandomGenerator.generate_cpf()
        )
        self.someone_pays(account, typo)

        _, as_source = self.our_account_pays(account, owner)
        _, paid_with_owner = self.someone_pays(account, owner)
        _, paid_with_typo = self.someone_pays(account, typo)

        assert "vinculo_nao_confere" not in reasons(as_source)
        assert as_source["status"] == "approved"
        assert "vinculo_nao_confere" not in reasons(paid_with_owner)
        # Agora o nó é verificado com o documento do cliente: o CPF errado não passa mais.
        assert "vinculo_nao_confere" in reasons(paid_with_typo)

    def test_verified_destination_with_other_document_is_rejected_without_floor(self):
        account = PayloadGenerator.random_account_number()
        self.our_account_pays(account, RandomGenerator.generate_cpf())

        _, response = self.someone_pays(account, RandomGenerator.generate_cpf())

        assert response["status"] == "rejected"
        assert "vinculo_nao_confere" in reasons(response)
        assert score(response) < 0.80

    def test_destination_only_seen_as_destination_never_conflicts(self):
        account = PayloadGenerator.random_account_number()
        ObjectGenerator.create_pix_from_registered_device(transaction_date=DAY, destination_account_number=account)

        _, response = ObjectGenerator.create_pix_from_registered_device(
            transaction_date=DAY, destination_account_number=account,
            destination_document_number=RandomGenerator.generate_cpf(),
        )

        assert "vinculo_nao_confere" not in reasons(response)

    def test_same_owner_with_unpadded_branch_is_the_same_account(self):
        account, owner = PayloadGenerator.random_account_number(), RandomGenerator.generate_cpf()
        self.our_account_pays(account, owner, source_branch="0042")

        _, response = self.our_account_pays("000" + account, owner, source_branch="42")

        assert "vinculo_nao_confere" not in reasons(response)


class TestR4PersonFraud:
    def test_mule_destination_is_rejected(self):
        _, response = ObjectGenerator.create_pix_from_registered_device(
            transaction_date=DAY, destination_document_number=persona.MULE,
        )

        assert response["status"] == "rejected"
        assert "destino_marcado" in reasons(response)
        assert score(response) == approx(1.0)

    def test_scammer_source_is_rejected(self):
        _, response = ObjectGenerator.create_pix_from_registered_device(
            transaction_date=DAY, source_document_number=persona.SCAMMER,
        )

        assert response["status"] == "rejected"
        assert "origem_marcada" in reasons(response)
        assert score(response) == approx(1.0)

    def test_destination_under_analysis_small_amount_asks_2fa(self):
        _, response = ObjectGenerator.create_pix_from_registered_device(
            amount=30000, transaction_date=DAY, destination_document_number=persona.UNDER_ANALYSIS,
        )

        assert response["status"] == "two_factor_required"
        assert "destino_em_analise" in reasons(response)
        assert score(response) == approx(1 - 0.6 * 0.8 * 0.9)

    def test_destination_under_analysis_never_blocks_by_itself(self):
        _, response = ObjectGenerator.create_pix_from_registered_device(
            amount=150000, transaction_date=DAY, destination_document_number=persona.UNDER_ANALYSIS,
        )

        # Acima do limite menor o peso sobe (0.40 -> 0.70), mas continua 2FA.
        assert response["status"] == "two_factor_required"
        assert score(response) == approx(1 - 0.3 * 0.8 * 0.9)

    def test_account_takeover_source_asks_2fa(self):
        _, response = ObjectGenerator.create_pix_from_registered_device(
            transaction_date=DAY, source_document_number=persona.ACCOUNT_TAKEOVER,
        )

        assert response["status"] == "two_factor_required"
        assert "origem_conta_roubada" in reasons(response)

    def test_weak_signal_only_adds_weight(self):
        _, response = ObjectGenerator.create_pix_from_registered_device(
            transaction_date=DAY, destination_document_number=persona.WEAK_SIGNAL,
        )

        assert response["status"] == "approved"
        assert "destino_sinal_fraco" in reasons(response)
        assert score(response) == approx(1 - 0.7 * 0.8 * 0.9)

    def test_dict_unavailable_asks_2fa(self):
        _, response = ObjectGenerator.create_pix_from_registered_device(
            transaction_date=DAY, destination_document_number=persona.DICT_UNAVAILABLE,
        )

        assert response["status"] == "two_factor_required"
        assert "dict_indisponivel" in reasons(response)

    def test_partner_of_mule_company_asks_2fa(self):
        partner = RandomGenerator.generate_cpf()
        status, _ = RequestGenerator.POST_person_link(
            PayloadGenerator.create_person_link_payload(partner, persona.MULE_CNPJ, "PARTNER")
        )
        assert status == 201

        _, response = ObjectGenerator.create_pix_from_registered_device(
            transaction_date=DAY, source_document_number=partner,
        )

        assert response["status"] == "two_factor_required"
        assert "vinculado_marcado" in reasons(response)
        assert score(response) == approx(1 - 0.4 * 0.8 * 0.9)


class TestR5Location:
    def test_missing_geolocation_adds_weight(self):
        _, response = ObjectGenerator.create_pix_from_registered_device(
            transaction_date=DAY, include_geolocation=False,
        )

        assert response["status"] == "approved"
        assert "sem_geolocalizacao" in reasons(response)
        assert score(response) == approx(1 - 0.9 * 0.8 * 0.9)

    def test_impossible_travel_asks_2fa(self):
        payload, _ = ObjectGenerator.create_pix_from_registered_device(amount=5000, transaction_date=DAY)

        # Mesma conta, mesmo device: São Paulo e, 30 minutos depois, Recife.
        response = ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
            amount=5000, transaction_date=at(DAY, minutes=30),
            source_document_number=payload["source_account"]["owner"]["document_number"],
            source_account_number=payload["source_account"]["account_number"],
            device_id=payload["source"]["device_id"], latitude=-8.05, longitude=-34.88,
        ))

        assert response["status"] == "two_factor_required"
        assert "viagem_impossivel" in reasons(response)

    def test_far_from_usual_location_asks_2fa(self):
        payload, _ = ObjectGenerator.create_pix_from_registered_device(
            amount=5000, transaction_date=at(DAY, days=-6), destination_opening_date=OLD_ACCOUNT,
        )
        common = dict(
            source_document_number=payload["source_account"]["owner"]["document_number"],
            source_account_number=payload["source_account"]["account_number"],
            device_id=payload["source"]["device_id"], amount=5000,
        )
        for days_ago in (4, 2):  # 3 Pix em São Paulo
            ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
                transaction_date=at(DAY, days=-days_ago), destination_opening_date=OLD_ACCOUNT, **common,
            ))

        # Porto Alegre, dois dias depois: longe do centróide, mas não é viagem impossível.
        response = ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
            transaction_date=DAY, latitude=-30.03, longitude=-51.23, **common,
        ))

        assert response["status"] == "two_factor_required"
        assert "localizacao_atipica" in reasons(response)


class TestR6R7AmountAndRecurrence:
    def customer_with_small_history(self):
        payload, _ = ObjectGenerator.create_pix_from_registered_device(
            amount=5000, transaction_date=at(DAY, days=-86), destination_opening_date=OLD_ACCOUNT,
        )
        common = dict(
            source_document_number=payload["source_account"]["owner"]["document_number"],
            source_account_number=payload["source_account"]["account_number"],
            device_id=payload["source"]["device_id"],
        )
        for day in range(85, 26, -1):  # ~60 Pix pequenos de R$ 50 nos últimos 90 dias
            ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
                amount=5000, transaction_date=at(DAY, days=-day, hours=-3), destination_opening_date=OLD_ACCOUNT,
                **common,
            ))
        return common

    def test_atypical_amount_adds_weight(self):
        common = self.customer_with_small_history()

        response = ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
            amount=150000, transaction_date=DAY, **common,
        ))

        assert "valor_atipico" in reasons(response)
        assert "pagamento_recorrente" not in reasons(response)

    def test_monthly_payment_gets_discount(self):
        common = self.customer_with_small_history()
        landlord, landlord_account = RandomGenerator.generate_cpf(), PayloadGenerator.random_account_number()
        for days_ago in (120, 90, 60, 30):  # aluguel de R$ 1.500 todo mês
            ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
                amount=150000, transaction_date=at(DAY, days=-days_ago), destination_document_number=landlord,
                destination_account_number=landlord_account, destination_opening_date=OLD_ACCOUNT, **common,
            ))

        rent = ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
            amount=150000, transaction_date=DAY, destination_document_number=landlord,
            destination_account_number=landlord_account, destination_opening_date=OLD_ACCOUNT, **common,
        ))
        stranger = ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
            amount=150000, transaction_date=at(DAY, hours=2), destination_opening_date=OLD_ACCOUNT, **common,
        ))

        assert rent["status"] == "approved"
        assert {"valor_atipico", "pagamento_recorrente"} <= set(reasons(rent))
        assert "pagamento_recorrente" not in reasons(stranger)
        assert score(rent) < score(stranger)

    def test_big_amount_without_history_adds_weight(self):
        _, response = ObjectGenerator.create_pix_from_registered_device(amount=600000, transaction_date=DAY)

        assert "valor_alto_sem_historico" in reasons(response)


class TestR8Velocity:
    def test_fifth_pix_in_ten_minutes_asks_2fa(self):
        payload, _ = ObjectGenerator.create_pix_from_registered_device(amount=5000, transaction_date=DAY)
        common = dict(
            source_document_number=payload["source_account"]["owner"]["document_number"],
            source_account_number=payload["source_account"]["account_number"],
            device_id=payload["source"]["device_id"], amount=5000,
        )
        responses = [
            ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
                transaction_date=at(DAY, minutes=minute), **common,
            ))
            for minute in (2, 4, 6, 8)
        ]

        assert all("velocity_origem" not in reasons(r) for r in responses[:3])
        assert responses[3]["status"] == "two_factor_required"
        assert "velocity_origem" in reasons(responses[3])

    def test_parallel_burst_triggers_velocity(self):
        """T11: 10 Pix simultâneos da mesma origem. Com o lock, cada um enxerga os anteriores.

        A R8 conta a tentativa atual (>= 5 em 10 min): aciona do 5º ao 10º.
        """
        payload, _ = ObjectGenerator.create_pix_from_registered_device(amount=5000, transaction_date=at(DAY, hours=-2))
        payloads = [
            PayloadGenerator.create_pix_transaction_payload(
                amount=5000, transaction_date=DAY,
                source_document_number=payload["source_account"]["owner"]["document_number"],
                source_account_number=payload["source_account"]["account_number"],
                device_id=payload["source"]["device_id"],
            )
            for _ in range(10)
        ]

        responses = in_parallel(payloads)

        flagged = [r for r in responses if "velocity_origem" in reasons(r)]
        assert len(flagged) == 6
        assert all(r["status"] == "two_factor_required" for r in flagged)

    def test_fan_in_to_new_account(self):
        destination, owner = PayloadGenerator.random_account_number(), RandomGenerator.generate_cpf()
        responses = [
            ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
                amount=5000, transaction_date=at(DAY, minutes=minute), destination_account_number=destination,
                destination_document_number=owner,
            ))
            for minute in range(10)  # 10 origens diferentes em 10 minutos
        ]

        assert "fan_in_destino" not in reasons(responses[8])
        assert "fan_in_destino" in reasons(responses[9])

    def test_device_shared_by_three_accounts(self):
        device = PayloadGenerator.random_device_id()
        responses = [
            ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
                amount=5000, transaction_date=at(DAY, hours=hour), device_id=device,
            ))
            for hour in range(3)
        ]

        assert "device_compartilhado" not in reasons(responses[1])
        assert "device_compartilhado" in reasons(responses[2])


class TestExtraSignals:
    def test_known_old_destination_has_no_extra_weight(self):
        payload, first = ObjectGenerator.create_pix_from_registered_device(
            amount=5000, transaction_date=at(DAY, days=-1), destination_opening_date=OLD_ACCOUNT,
        )
        assert reasons(first) == ["destino_desconhecido"]

        second = ObjectGenerator.create_pix_transaction(PayloadGenerator.create_pix_transaction_payload(
            amount=5000, transaction_date=DAY,
            source_document_number=payload["source_account"]["owner"]["document_number"],
            source_account_number=payload["source_account"]["account_number"],
            device_id=payload["source"]["device_id"],
            destination_document_number=payload["destination_account"]["owner"]["document_number"],
            destination_account_number=payload["destination_account"]["account_number"],
            destination_opening_date=OLD_ACCOUNT,
        ))

        assert second["status"] == "approved"
        assert reasons(second) == []
