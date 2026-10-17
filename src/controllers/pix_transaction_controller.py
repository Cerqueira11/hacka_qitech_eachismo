from typing import Tuple

from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from dtos import AccountInput, PixTransactionDTO, PixTransactionInput
from errors import NotFoundPixTransaction
from models import AccountNode
from repositories import (
    AccountRepository,
    GeolocationRepository,
    MetadataRepository,
    StatusResultHistoryRepository,
    TransactionRepository,
)

TRANSACTION_ID_CONSTRAINT = "uq_transaction_history_transaction_id"


class PixTransactionController(BaseController):
    """Regras de negócio e orquestração da análise de transações PIX antifraude."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.account_repository = AccountRepository(self.context)
        self.transaction_repository = TransactionRepository(self.context)
        self.geolocation_repository = GeolocationRepository(self.context)
        self.metadata_repository = MetadataRepository(self.context)
        self.status_result_history_repository = StatusResultHistoryRepository(self.context)

    def _evaluate_antifraud(
        self,
        data: PixTransactionInput,
        source_account: AccountNode,
        destination_account: AccountNode,
    ) -> str:
        """Ponto de entrada das regras antifraude.

        Roda ANTES de a transação ser gravada: assim velocity, média de valores
        e vizinhança do grafo enxergam só o passado, nunca o próprio Pix.

        Status possíveis (enum_status_result): 'approved' | 'rejected' | 'two_factor_required'
        """
        # Regra padrão inicial (espaço reservado para o motor de regras):
        return "approved"

    def create(self, payload: dict) -> Tuple[dict, bool]:
        """Analisa e registra um Pix. Devolve (veredito, criado_agora).

        O "id" do payload é a chave de idempotência: reenviar o mesmo Pix
        devolve o veredito já dado, em vez de analisar (e gravar) de novo.
        """
        data = PixTransactionInput.from_payload(payload)
        self.logger.debug(f"Processando transação PIX {data.transaction_id} para antifraude")

        existing = self.transaction_repository.get_by_transaction_id(data.transaction_id)
        if existing is not None:
            return PixTransactionDTO.obj_to_dict(existing), False

        source_account = self.account_repository.upsert(data.source_account)
        destination_account = self.account_repository.upsert(data.destination_account)
        self._warn_on_owner_mismatch(source_account, data.source_account, "source_account")
        self._warn_on_owner_mismatch(destination_account, data.destination_account, "destination_account")

        decision = self._evaluate_antifraud(data, source_account, destination_account)

        geolocation = None
        if data.geolocation is not None:
            geolocation = self.geolocation_repository.create(
                latitude=data.geolocation.latitude,
                longitude=data.geolocation.longitude,
            )

        tx = self.transaction_repository.create(
            data=data,
            source_account=source_account,
            destination_account=destination_account,
            geolocation=geolocation,
        )
        metadata = self.metadata_repository.create()
        self.status_result_history_repository.create(transaction=tx, status=decision, metadata=metadata)

        try:
            # O flush é o INSERT de fato: a partir daqui key_pix, ids e
            # chaves estrangeiras existem, e o DTO pode ser montado.
            self.session.flush()
        except IntegrityError as error:
            # Dois POSTs com o mesmo id chegaram juntos e o outro gravou primeiro.
            if _violated_constraint(error) != TRANSACTION_ID_CONSTRAINT:
                raise
            self.session.rollback()
            existing = self.transaction_repository.get_by_transaction_id(data.transaction_id)
            return PixTransactionDTO.obj_to_dict(existing), False

        # Monta o DTO antes do commit conforme padrão arquitetural do projeto
        result_dto = PixTransactionDTO.obj_to_dict(tx)

        self.session.commit()

        return result_dto, True

    def get_by_id(self, transaction_id: str) -> dict:
        """Devolve o veredito mais recente de um Pix pelo "id" enviado no POST."""
        tx = self.transaction_repository.get_by_transaction_id(transaction_id)

        if tx is None:
            raise NotFoundPixTransaction(transaction_id)

        return PixTransactionDTO.obj_to_dict(tx)

    def _warn_on_owner_mismatch(self, node: AccountNode, account: AccountInput, field: str) -> None:
        # Mesma conta, outro titular: não é erro de entrada, é sinal para a
        # regra 3 (vínculo conta x documento). Por enquanto só fica no log.
        if node.document_number != account.document_number:
            self.logger.warning(
                f"{field}: conta {node.participant}/{node.branch}/{node.account_number} "
                + "já registrada com outro titular"
            )


def _violated_constraint(error: IntegrityError):
    diag = getattr(error.orig, "diag", None)
    return getattr(diag, "constraint_name", None)
