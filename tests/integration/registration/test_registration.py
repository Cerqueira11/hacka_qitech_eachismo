from tests.utils import PayloadGenerator, RandomGenerator, RequestGenerator
from tests.utils.dict_personas import MULE_CNPJ


class TestDevice:
    def test_registers_device_then_returns_existing(self):
        payload = PayloadGenerator.create_device_payload(
            RandomGenerator.generate_cpf(), PayloadGenerator.random_device_id()
        )

        status, created = RequestGenerator.POST_device(payload)
        assert status == 201
        assert created["device_id"] == payload["device_id"]
        # Documento volta sem máscara.
        assert created["document_number"] == "".join(c for c in payload["document_number"] if c.isdigit())

        status, again = RequestGenerator.POST_device(payload)
        assert status == 200
        assert again == created

    def test_accepts_cnpj_owner(self):
        payload = PayloadGenerator.create_device_payload(
            RandomGenerator.generate_cnpj(), PayloadGenerator.random_device_id()
        )

        status, _ = RequestGenerator.POST_device(payload)

        assert status == 201

    def test_invalid_document(self):
        payload = PayloadGenerator.create_device_payload("123.456.789-00", PayloadGenerator.random_device_id())

        status, response = RequestGenerator.POST_device(payload)

        assert status == 422
        assert response["code"] == "QIT001008"

    def test_missing_device_id(self):
        status, response = RequestGenerator.POST_device({"document_number": RandomGenerator.generate_cpf()})

        assert status == 400
        assert response["code"] == "QIT000001"

    def test_without_token_is_forbidden(self):
        payload = PayloadGenerator.create_device_payload(
            RandomGenerator.generate_cpf(), PayloadGenerator.random_device_id()
        )

        status, response = RequestGenerator.POST_device(payload, token="errado")

        assert status == 403
        assert response["code"] == "QIT000002"


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
        payload = PayloadGenerator.create_person_link_payload(MULE_CNPJ, RandomGenerator.generate_cnpj())

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
