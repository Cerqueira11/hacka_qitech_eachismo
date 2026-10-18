from fastapi import status as http_status
from fastapi.responses import JSONResponse

from controllers import RegistrationController
from utils.schema_handler import SchemaHandler


def _response(result: dict, created: bool) -> JSONResponse:
    # 201 quando criou agora; 200 quando o cadastro já existia.
    status_code = http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK
    return JSONResponse(content=result, status_code=status_code)


class RegistrationResource:
    """Porta de entrada HTTP dos cadastros que alimentam as regras antifraude."""

    @SchemaHandler.validate("post_device.json")
    def on_post_device(self, payload: dict) -> JSONResponse:
        result, created = RegistrationController().register_device(payload)
        return _response(result, created)

    @SchemaHandler.validate("post_person_link.json")
    def on_post_person_link(self, payload: dict) -> JSONResponse:
        result, created = RegistrationController().link_person(payload)
        return _response(result, created)
