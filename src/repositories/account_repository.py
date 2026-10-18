import uuid
from typing import Optional

from sqlalchemy import case, func, text
from sqlalchemy.dialects.postgresql import insert

from database import Context
from dtos.pix_transaction_input import AccountInput
from models import AccountNode

# Lock de transação: some sozinho no commit/rollback, sem unlock manual.
SOURCE_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")


class AccountRepository:
    """A camada que fala com a tabela account_node (os nós do grafo)."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def lock_source(self, account: AccountInput) -> None:
        """Serializa os Pix da mesma conta de origem até o fim da transação (C4).

        A chave vem do payload normalizado (participant|branch|account_number),
        não do id_account: o lock precisa pegar ANTES do upsert, que agora
        altera o nó da origem. Origens diferentes seguem em paralelo.
        """
        key = f"{account.participant}|{account.branch}|{account.account_number}"
        self.session.execute(SOURCE_LOCK, {"key": key})

    def upsert(self, account: AccountInput, is_source: bool) -> AccountNode:
        """Cria o nó se ele não existe; se existe, devolve o que está no banco (C2).

        Um INSERT ... ON CONFLICT só, em vez de "busca e, se não achar, cria":
        dois Pix simultâneos para a mesma conta nova não brigam pela chave única.

        Documento do nó:
          origem, nó novo ............... cria verificado, com o documento do payload
          origem, nó não verificado ..... corrige o documento e passa a verificado
                                          (o CPF errado que veio de um destino é trocado
                                          pelo do nosso cliente)
          origem, nó já verificado ...... mantém o documento; a R3 compara com o payload
          destino ....................... nunca altera o documento
        """
        statement = insert(AccountNode).values(
            id_account=uuid.uuid4(),
            participant=account.participant,
            branch=account.branch,
            account_number=account.account_number,
            document_number=account.document_number,
            document_verified=is_source,
            person_type=account.person_type,
            opening_date=account.opening_date,
        )
        set_ = {
            "updated_at": func.now(),
            "opening_date": func.coalesce(AccountNode.opening_date, statement.excluded.opening_date),
        }
        if is_source:
            corrects_document = AccountNode.document_verified.is_(False)
            set_["document_number"] = case(
                (corrects_document, statement.excluded.document_number),
                else_=AccountNode.document_number,
            )
            set_["person_type"] = case(
                (corrects_document, statement.excluded.person_type),
                else_=AccountNode.person_type,
            )
            set_["document_verified"] = True

        statement = statement.on_conflict_do_update(
            constraint="uq_account_node_identity",
            set_=set_,
        ).returning(AccountNode)

        return self.session.scalars(statement, execution_options={"populate_existing": True}).one()

    def get_by_id(self, id_account: uuid.UUID) -> Optional[AccountNode]:
        return self.session.query(AccountNode).filter(AccountNode.id_account == id_account).first()
