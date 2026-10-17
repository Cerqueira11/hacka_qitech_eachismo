from tests.utils import PayloadGenerator, RequestGenerator


class TestPixTransaction:
    def test_creates_pix_transaction_success(self):
        payload = PayloadGenerator.create_pix_transaction_payload()

        status, response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201
        assert "key_pix" in response
        assert response["amount"] == payload["amount"]
        assert response["source_account_branch"] == payload["source_account_branch"]
        assert response["source_account_number"] == payload["source_account_number"]
        assert response["status"] in ("approved", "rejected", "two_factor_required")
        assert response["geolocation"] is not None
        assert response["geolocation"]["latitude"] == payload["geolocation"]["latitude"]

    def test_get_pix_transaction_by_id(self):
        payload = PayloadGenerator.create_pix_transaction_payload(amount=25000)
        status, created = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        key_pix = created["key_pix"]

        status, fetched = RequestGenerator.GET_pix_transaction(key_pix)
        assert status == 200
        assert fetched["key_pix"] == key_pix
        assert fetched["amount"] == 25000
        assert len(fetched["status_history"]) > 0

    def test_get_pix_transaction_not_found(self):
        status, response = RequestGenerator.GET_pix_transaction(999999999)
        assert status == 404
        assert response["code"] == "QIT001015"

    def test_post_pix_transaction_invalid_schema(self):
        # Falta campos obrigatórios
        status, response = RequestGenerator.POST_pix_transaction({})
        assert status == 400
        assert response["code"] == "QIT000001"
