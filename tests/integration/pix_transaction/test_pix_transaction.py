from tests.utils import PayloadGenerator, RequestGenerator
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

        # Mesmo "id" com outro valor: idempotência ganha, não reanalisa.
        payload["amount"] = 1
        status, second = RequestGenerator.POST_pix_transaction(payload)

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
