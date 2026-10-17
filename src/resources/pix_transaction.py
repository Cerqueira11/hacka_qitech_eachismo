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
        result = controller.create(payload)

        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=http_status.HTTP_201_CREATED,
        )

    def on_get_by_id(self, id: int) -> JSONResponse:
        controller = PixTransactionController()
        result = controller.get_by_id(id)

        return JSONResponse(
            content=jsonable_encoder(result),
            status_code=http_status.HTTP_200_OK,
        )
