from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import PixTransactionController
from utils.schema_handler import SchemaHandler


class PixTransactionResource:
    """Porta de entrada HTTP para transações PIX."""

    @SchemaHandler.validate("post_pix_transaction.json")
    def on_post(self, payload: dict) -> JSONResponse:
        controller = PixTransactionController()
        result, created = controller.create(payload)

        # 201 quando o Pix foi analisado agora; 200 quando o mesmo "id" já
        # tinha veredito e a resposta é a mesma de antes (idempotência).
        status_code = http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK
        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=status_code,
        )

    def on_get_by_id(self, id: str) -> JSONResponse:
        controller = PixTransactionController()
        result = controller.get_by_id(id)
        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=http_status.HTTP_200_OK,
        )

    @SchemaHandler.validate("post_2fa_result.json")
    def on_post_2fa(self, id: str, payload: dict) -> JSONResponse:
        controller = PixTransactionController()
        result = controller.submit_2fa(id, payload)
        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=http_status.HTTP_200_OK,
        )

    def on_post_fraud(self, id: str) -> JSONResponse:
        controller = PixTransactionController()
        result = controller.report_fraud(id)
        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=http_status.HTTP_200_OK,
        )
