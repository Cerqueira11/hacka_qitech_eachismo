from tests.utils import PayloadGenerator, RequestGenerator

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

    def test_post_pix_transaction_invalid_schema(self):
        # Falta campos obrigatórios
        status, response = RequestGenerator.POST_pix_transaction({})

        assert status == 400
        assert response["code"] == "QIT000001"
