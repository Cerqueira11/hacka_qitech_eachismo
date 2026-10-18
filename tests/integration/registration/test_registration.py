from tests.utils import PayloadGenerator, RandomGenerator, RequestGenerator
from tests.utils.payload_generator import only_digits


class TestDevice:
    def test_device_registration_is_not_exposed(self):
        """registered_device é cache interno da R1: só a API externa de dispositivo põe alguém lá."""
        status, response = RequestGenerator.POST_device(
            {"document_number": RandomGenerator.generate_cpf(), "device_id": PayloadGenerator.random_device_id()}
        )

        assert status == 404
        assert response["code"] == "QIT000404"


class TestPersonLink:
    def test_links_cpf_to_cnpj_then_returns_existing(self):
        payload = PayloadGenerator.create_person_link_payload(
            RandomGenerator.generate_cpf(), RandomGenerator.generate_cnpj(), "SOLE_PROPRIETOR"
        )

        status, created = RequestGenerator.POST_person_link(payload)
        assert status == 201
        assert created["relation"] == "SOLE_PROPRIETOR"
        assert len(created["cpf"]) == 11
        assert len(created["cnpj"]) == 14

        status, again = RequestGenerator.POST_person_link(payload)
        assert status == 200
        assert again["cpf"] == created["cpf"] and again["cnpj"] == created["cnpj"]

    def test_accepts_alphanumeric_cnpj(self):
        # Exemplo oficial da Receita para o CNPJ alfanumérico.
        payload = PayloadGenerator.create_person_link_payload(RandomGenerator.generate_cpf(), "12.ABC.345/01DE-35")

        status, created = RequestGenerator.POST_person_link(payload)

        assert status in (200, 201)
        assert created["cnpj"] == "12ABC34501DE35"

    def test_cnpj_in_cpf_field(self):
        # Sem máscara (14 dígitos): passa no schema, mas é um CNPJ.
        cnpj_digits = only_digits(RandomGenerator.generate_cnpj())
        payload = PayloadGenerator.create_person_link_payload(cnpj_digits, RandomGenerator.generate_cnpj())

        status, response = RequestGenerator.POST_person_link(payload)

        assert status == 422
        assert response["code"] == "QIT001008"

    def test_cpf_in_cnpj_field(self):
        # "000.000.000-00" tem 14 caracteres: passa no schema, mas é um CPF.
        payload = PayloadGenerator.create_person_link_payload(
            RandomGenerator.generate_cpf(), RandomGenerator.generate_cpf()
        )

        status, response = RequestGenerator.POST_person_link(payload)

        assert status == 422
        assert response["code"] == "QIT001008"

    def test_invalid_relation(self):
        payload = PayloadGenerator.create_person_link_payload(
            RandomGenerator.generate_cpf(), RandomGenerator.generate_cnpj(), "PRIMO"
        )

        status, response = RequestGenerator.POST_person_link(payload)

        assert status == 400
        assert response["code"] == "QIT000001"
