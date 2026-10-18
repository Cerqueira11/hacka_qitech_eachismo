from tests.utils import PayloadGenerator, RandomGenerator, RequestGenerator
from tests.utils.dict_api_mock import DictApiMock
from tests.utils.requisition import ClientRequisition

STATUSES = ("approved", "rejected", "two_factor_required")


class TestPixTransaction:
    def test_creates_pix_transaction_success(self):
        payload = PayloadGenerator.create_pix_transaction_payload()

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201
        assert set(response.keys()) == {"key", "status", "metadata"}
        assert response["key"]
        assert response["status"] in STATUSES
        assert isinstance(response["metadata"], dict)

    def test_metadata_has_score_and_reasons_but_no_weights(self):
        payload = PayloadGenerator.create_pix_transaction_payload()

        _, response = RequestGenerator.POST_pix_transaction(payload)

        assert set(response["metadata"].keys()) == {"risk_score", "reasons"}
        assert 0 <= response["metadata"]["risk_score"] <= 1
        assert all(isinstance(reason, str) for reason in response["metadata"]["reasons"])

    def test_get_pix_transaction_by_id(self):
        payload = PayloadGenerator.create_pix_transaction_payload(amount=25000)
        status, created = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        status, fetched = RequestGenerator.GET_pix_transaction(payload["id"])

        assert status == 200
        assert fetched == created

    def test_get_pix_transaction_not_found(self):
        status, response = RequestGenerator.GET_pix_transaction("pix-nao-existe")

        assert status == 404
        assert response["code"] == "QIT001015"

    def test_post_same_id_twice_returns_same_verdict(self):
        payload = PayloadGenerator.create_pix_transaction_payload()
        status, first = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        status, second = RequestGenerator.POST_pix_transaction(payload)

        assert status == 200
        assert second == first

    def test_same_id_with_other_amount_is_conflict(self):
        """T4: mesmo id com outro corpo não herda o veredito antigo (C4)."""
        payload = PayloadGenerator.create_pix_transaction_payload()
        status, _ = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        status, response = RequestGenerator.POST_pix_transaction({**payload, "amount": payload["amount"] + 1})

        assert status == 409
        assert response["code"] == "QIT001016"

    def test_same_id_with_equivalent_payload_returns_same_verdict(self):
        """T12: agência "1" x "0001", CPF com/sem máscara, zeros à esquerda e outro fuso: mesmo Pix."""
        payload = PayloadGenerator.create_pix_transaction_payload(
            source_branch="0001", transaction_date="2026-10-17T22:15:00-03:00"
        )
        status, first = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        source_account = dict(payload["source_account"])
        source_account["branch"] = "1"
        source_account["account_number"] = "000" + source_account["account_number"]
        source_account["owner"] = {"document_number": "".join(c for c in source_account["owner"]["document_number"] if c.isdigit())}
        retry = {
            "source": payload["source"],
            "transaction_date": "2026-10-18T01:15:00+00:00",
            "destination_account": payload["destination_account"],
            "source_account": source_account,
            "amount": payload["amount"],
            "id": payload["id"],
        }
        status, second = RequestGenerator.POST_pix_transaction(retry)

        assert status == 200
        assert second == first

    def test_post_without_token_is_forbidden(self):
        payload = PayloadGenerator.create_pix_transaction_payload()

        response = ClientRequisition.send("POST", "/pix/transaction", payload=payload)

        assert response.response_status == 403
        assert response.response_json["code"] == "QIT000002"


class TestPixTransactionValidation:
    def test_post_pix_transaction_invalid_schema(self):
        # Falta campos obrigatórios
        status, response = RequestGenerator.POST_pix_transaction({})

        assert status == 400
        assert response["code"] == "QIT000001"

    def test_unknown_field_is_rejected(self):
        payload = PayloadGenerator.create_pix_transaction_payload()
        payload["foo"] = 1

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 400
        assert response["code"] == "QIT000001"

    def test_invalid_cpf_check_digit(self):
        payload = PayloadGenerator.create_pix_transaction_payload(source_document_number="123.456.789-00")

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 422
        assert response["code"] == "QIT001008"

    def test_transaction_date_without_timezone(self):
        payload = PayloadGenerator.create_pix_transaction_payload(transaction_date="2026-10-17T22:15:00")

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 422
        assert response["code"] == "QIT001007"

    def test_opening_date_after_transaction(self):
        payload = PayloadGenerator.create_pix_transaction_payload(
            destination_opening_date="2026-10-18T09:00:00-03:00"
        )

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 422
        assert response["code"] == "QIT001009"

    def test_invalid_ip(self):
        payload = PayloadGenerator.create_pix_transaction_payload(ip="999.1.1.1")

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 422
        assert response["code"] == "QIT001010"

    def test_rejected_input_is_not_recorded(self):
        payload = PayloadGenerator.create_pix_transaction_payload(ip="999.1.1.1")
        RequestGenerator.POST_pix_transaction(payload)

        status, _ = RequestGenerator.GET_pix_transaction(payload["id"])

        assert status == 404


def wrong_last_digit(document_number: str) -> str:
    """O mesmo documento com o último dígito verificador trocado."""
    return document_number[:-1] + str((int(document_number[-1]) + 1) % 10)


class TestPixDocumentNumber:
    """CPF ou CNPJ (numérico ou alfanumérico), com ou sem máscara. O resto é 422."""

    def assert_invalid_document(self, **document):
        payload = PayloadGenerator.create_pix_transaction_payload(**document)

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 422, response
        assert response["code"] == "QIT001008"

    def test_accepts_cpf_without_mask(self):
        cpf = RandomGenerator.generate_cpf().replace(".", "").replace("-", "")
        payload = PayloadGenerator.create_pix_transaction_payload(destination_document_number=cpf)

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201, response

    def test_accepts_numeric_cnpj_with_and_without_mask(self):
        masked = RandomGenerator.generate_cnpj()
        unmasked = masked.replace(".", "").replace("/", "").replace("-", "")
        for destination in (masked, unmasked):
            payload = PayloadGenerator.create_pix_transaction_payload(destination_document_number=destination)

            status, response = RequestGenerator.POST_pix_transaction(payload)

            assert status == 201, response
        # Os dois formatos chegam ao DICT como o mesmo documento, sem máscara.
        assert DictApiMock.calls(masked) == 2

    def test_accepts_cnpj_as_source(self):
        payload = PayloadGenerator.create_pix_transaction_payload(
            source_document_number=RandomGenerator.generate_cnpj()
        )

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201, response

    def test_accepts_alphanumeric_cnpj_in_lowercase(self):
        cnpj = RandomGenerator.generate_alphanumeric_cnpj()
        payload = PayloadGenerator.create_pix_transaction_payload(destination_document_number=cnpj.lower())

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201, response
        # A API põe as letras em maiúsculo antes de consultar o DICT.
        assert DictApiMock.calls(cnpj) == 1

    def test_invalid_cnpj_check_digit(self):
        self.assert_invalid_document(destination_document_number=wrong_last_digit(RandomGenerator.generate_cnpj()))

    def test_invalid_alphanumeric_cnpj_check_digit(self):
        self.assert_invalid_document(
            destination_document_number=wrong_last_digit(RandomGenerator.generate_alphanumeric_cnpj())
        )

    def test_invalid_cpf_check_digit_on_destination(self):
        self.assert_invalid_document(destination_document_number=wrong_last_digit(RandomGenerator.generate_cpf()))

    def test_cpf_with_all_digits_equal(self):
        # Passa na conta dos verificadores, mas a Receita não emite.
        self.assert_invalid_document(source_document_number="111.111.111-11")

    def test_cnpj_with_all_digits_equal(self):
        self.assert_invalid_document(destination_document_number="00.000.000/0000-00")

    def test_cpf_with_letters(self):
        # 11 caracteres: tamanho de CPF, mas CPF só tem dígitos.
        self.assert_invalid_document(source_document_number="1234567890A")

    def test_neither_cpf_nor_cnpj_length(self):
        # 12 dígitos: passa no schema, mas não é CPF (11) nem CNPJ (14).
        self.assert_invalid_document(destination_document_number="123456789012")

    def test_document_with_forbidden_characters_is_400(self):
        payload = PayloadGenerator.create_pix_transaction_payload(destination_document_number="123 456 789 09")

        status, response = RequestGenerator.POST_pix_transaction(payload)

        # Espaço não está no pattern do schema: barra antes da validação de CPF.
        assert status == 400
        assert response["code"] == "QIT000001"
