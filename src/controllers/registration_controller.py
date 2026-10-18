from typing import Tuple

from controllers.base_controller import BaseController
from errors import InvalidDocumentNumber
from repositories import RegistrationRepository
from utils.document_number import normalize_document_number, person_type_of


class RegistrationController(BaseController):
    """Cadastros: vínculos CPF <-> CNPJ (R4) e dispositivos (registered_device, que a R1 não lê mais: S2)."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = RegistrationRepository(self.context)

    def register_device(self, payload: dict) -> Tuple[dict, bool]:
        document_number = normalize_document_number(payload["document_number"])
        if person_type_of(document_number) is None:
            raise InvalidDocumentNumber("document_number")

        device, created = self.repository.register_device(document_number, payload["device_id"])
        result = {
            "document_number": device.document_number,
            "device_id": device.device_id,
            "registered_at": device.registered_at.isoformat(),
        }
        self.session.commit()
        return result, created

    def link_person(self, payload: dict) -> Tuple[dict, bool]:
        cpf = normalize_document_number(payload["cpf"])
        if person_type_of(cpf) != "PF":
            raise InvalidDocumentNumber("cpf")
        cnpj = normalize_document_number(payload["cnpj"])
        if person_type_of(cnpj) != "PJ":
            raise InvalidDocumentNumber("cnpj")

        link, created = self.repository.link_person(cpf, cnpj, payload["relation"])
        self.session.flush()
        result = {
            "cpf": link.cpf.strip(),
            "cnpj": link.cnpj.strip(),
            "relation": link.relation,
            "created_at": link.created_at.isoformat(),
        }
        self.session.commit()
        return result, created
