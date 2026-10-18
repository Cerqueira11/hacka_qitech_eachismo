from typing import Tuple

from sqlalchemy.dialects.postgresql import insert

from database import Context
from models import PersonLink


class RegistrationRepository:
    """Cadastro de vínculos CPF <-> CNPJ (R4). Dispositivos: ver DeviceRepository."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

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
