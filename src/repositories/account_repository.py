import uuid
from typing import Optional

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from database import Context
from dtos.pix_transaction_input import AccountInput
from models import AccountNode


class AccountRepository:
    """A camada que fala com a tabela account_node (os nós do grafo)."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def upsert(self, account: AccountInput) -> AccountNode:
        """Cria o nó se ele não existe; se existe, devolve o que já está no banco.

        Um INSERT ... ON CONFLICT só, em vez de "busca e, se não achar, cria":
        dois Pix simultâneos para a mesma conta nova não brigam pela chave única.

        O documento de um nó existente NÃO é sobrescrito. Se o payload trouxer
        outro titular para a mesma conta, quem decide o que isso significa é a
        análise antifraude (regra 3), não o repositório.
        """
        statement = insert(AccountNode).values(
            id_account=uuid.uuid4(),
            participant=account.participant,
            branch=account.branch,
            account_number=account.account_number,
            document_number=account.document_number,
            person_type=account.person_type,
            opening_date=account.opening_date,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_account_node_identity",
            set_={
                "updated_at": func.now(),
                "opening_date": func.coalesce(AccountNode.opening_date, statement.excluded.opening_date),
            },
        ).returning(AccountNode)

        return self.session.scalars(statement, execution_options={"populate_existing": True}).one()

    def get_by_id(self, id_account: uuid.UUID) -> Optional[AccountNode]:
        return self.session.query(AccountNode).filter(AccountNode.id_account == id_account).first()
