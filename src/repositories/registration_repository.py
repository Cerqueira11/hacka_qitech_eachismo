from typing import Tuple

from sqlalchemy.dialects.postgresql import insert

from database import Context
from models import PersonLink, RegisteredDevice


class RegistrationRepository:
    """Cadastros: vínculos CPF <-> CNPJ (R4) e dispositivos (registered_device, fora da R1 desde a S2)."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def register_device(self, document_number: str, device_id: str) -> Tuple[RegisteredDevice, bool]:
        """Devolve (dispositivo, criado_agora). Cadastrar de novo não é erro."""
        statement = (
            insert(RegisteredDevice)
            .values(document_number=document_number, device_id=device_id)
            .on_conflict_do_nothing()
            .returning(RegisteredDevice)
        )
        created = self.session.scalars(statement).first()
        if created is not None:
            return created, True
        existing = self.session.get(RegisteredDevice, (document_number, device_id))
        return existing, False

    def link_person(self, cpf: str, cnpj: str, relation: str) -> Tuple[PersonLink, bool]:
        """Devolve (vínculo, criado_agora). Se o vínculo já existe, a relação é atualizada."""
        existing = self.session.get(PersonLink, (cpf, cnpj))
        if existing is not None:
            existing.relation = relation
            return existing, False

        statement = (
            insert(PersonLink)
            .values(cpf=cpf, cnpj=cnpj, relation=relation)
            .on_conflict_do_update(index_elements=["cpf", "cnpj"], set_={"relation": relation})
            .returning(PersonLink)
        )
        return self.session.scalars(statement).one(), True
