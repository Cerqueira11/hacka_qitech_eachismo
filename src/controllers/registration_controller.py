from typing import Tuple

from controllers.base_controller import BaseController
from errors import InvalidDocumentNumber
from repositories import RegistrationRepository
from utils.document_number import normalize_document_number, person_type_of


class RegistrationController(BaseController):
    """Cadastro de vínculos CPF <-> CNPJ (R4).

    Dispositivo não se cadastra por aqui: registered_device é cache interno da
    R1, gravado só quando a API externa de dispositivo confirma.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = RegistrationRepository(self.context)

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
