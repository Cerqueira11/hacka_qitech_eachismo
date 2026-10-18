from typing import Tuple

from sqlalchemy.exc import IntegrityError

from antifraud import config as antifraud_config
from antifraud.context import ContextBuilder
from antifraud.engine import AntifraudEngine
from antifraud.graph import GraphScorer
from connectors.device_client import DeviceApiClient
from connectors.dict_client import DictMockClient
from controllers.base_controller import BaseController
from dtos import PixTransactionDTO, PixTransactionInput
from errors import IdempotencyConflict, NotFoundPixTransaction
from models import TransactionHistory
from repositories import (
    AccountRepository,
    GeolocationRepository,
    GraphRepository,
    MetadataRepository,
    RiskRepository,
    StatusResultHistoryRepository,
    TransactionRepository,
)

TRANSACTION_ID_CONSTRAINT = "uq_transaction_history_transaction_id"


class PixTransactionController(BaseController):
    """Orquestra a análise antifraude de um Pix (o caminho de regras_antifraude.txt)."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.account_repository = AccountRepository(self.context)
        self.transaction_repository = TransactionRepository(self.context)
        self.geolocation_repository = GeolocationRepository(self.context)
        self.metadata_repository = MetadataRepository(self.context)
        self.status_result_history_repository = StatusResultHistoryRepository(self.context)

        self.context_builder = ContextBuilder(RiskRepository(self.context), DictMockClient(), DeviceApiClient())
        self.graph_scorer = GraphScorer(GraphRepository(self.context))
        self.engine = AntifraudEngine(self.graph_scorer)

    def create(self, payload: dict) -> Tuple[dict, bool]:
        """Analisa e registra um Pix. Devolve (veredito, criado_agora).

        O "id" do payload é a chave de idempotência: reenviar o mesmo Pix
        devolve o veredito já dado, em vez de analisar (e gravar) de novo.
        Mesmo "id" com outro conteúdo é 409 (C4).

        Ordem (C4): externos → lock por origem → idempotência → upsert →
        regras → gravação → commit.
        """
        # ETAPA 0 — portaria (o schema já foi validado no resource)
        data = PixTransactionInput.from_payload(payload)
        payload_sha256 = data.canonical_sha256()
        self.logger.debug(f"Processando transação PIX {data.transaction_id} para antifraude")

        # Retry de um Pix já analisado (a IF reenvia quando estouramos o
        # timeout dela): responde sem chamar as APIs externas de novo. Linha
        # gravada não some, então esta leitura sem lock já é definitiva.
        existing = self.transaction_repository.get_by_transaction_id(data.transaction_id)
        if existing is not None:
            return self._replay(existing, payload_sha256), False

        # ETAPA 1a — o que vem de fora, ANTES do lock: uma API lenta não
        # segura a fila de Pix da mesma origem.
        external = self.context_builder.load_external(data)

        # Lock por conta de origem até o commit: Pix diferentes da mesma
        # origem em paralelo (lote, conta tomada disparando rajada) passam
        # a ler os agregados (R1, R2, R8) um depois do outro.
        self.account_repository.lock_source(data.source_account)

        # Idempotência de verdade: dentro do lock, depois de quem chegou antes.
        existing = self.transaction_repository.get_by_transaction_id(data.transaction_id)
        if existing is not None:
            return self._replay(existing, payload_sha256), False

        # ETAPA 0.5 — nós do grafo. A origem verifica (ou corrige) o documento; o destino nunca (C2).
        source_account = self.account_repository.upsert(data.source_account, is_source=True)
        destination_account = self.account_repository.upsert(data.destination_account, is_source=False)

        # ETAPAS 1 a 5 — contexto, regras, grafo, score e decisão. Rodam ANTES
        # de gravar o Pix: o histórico e o grafo enxergam só o passado.
        antifraud_context = self.context_builder.build(data, source_account, destination_account, external)
        verdict = self.engine.evaluate(antifraud_context)

        # ETAPA 6 — gravação
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
            risk_score=verdict.risk_score,
            payload_sha256=payload_sha256,
            device_registered=external.device_registered,
        )
        metadata = self.metadata_repository.create(
            risk_score=verdict.risk_score,
            rules_score=verdict.rules_score,
            graph_source_score=verdict.graph_source_score,
            graph_destination_score=verdict.graph_destination_score,
            rule_hits=[hit.to_dict() for hit in verdict.hits],
            graph_evidence=verdict.graph_evidence,
            engine_version=antifraud_config.ENGINE_VERSION,
        )
        self.status_result_history_repository.create(transaction=tx, status=verdict.status, metadata=metadata)

        try:
            # O flush é o INSERT de fato: a partir daqui key_pix, ids e
            # chaves estrangeiras existem, e o DTO pode ser montado.
            self.session.flush()
        except IntegrityError as error:
            # Fallback: o mesmo id chegou por OUTRA origem (outro lock) e gravou
            # primeiro. Também compara o hash.
            if _violated_constraint(error) != TRANSACTION_ID_CONSTRAINT:
                raise
            self.session.rollback()
            existing = self.transaction_repository.get_by_transaction_id(data.transaction_id)
            return self._replay(existing, payload_sha256), False

        # Risco aprendido e degree dos nós: só depois que o Pix entrou, e na
        # mesma transação de banco (ou vai tudo, ou não vai nada).
        self.graph_scorer.learn(antifraud_context, verdict)

        self.logger.info(
            f"Pix {data.transaction_id}: {verdict.status} risk_score={verdict.risk_score} "
            + f"motivos={[hit.reason for hit in verdict.hits]}"
        )

        # Monta o DTO antes do commit conforme padrão arquitetural do projeto
        result_dto = PixTransactionDTO.obj_to_dict(tx)

        # O commit também solta o lock da origem.
        self.session.commit()

        return result_dto, True

    def get_by_id(self, transaction_id: str) -> dict:
        """Devolve o veredito mais recente de um Pix pelo "id" enviado no POST."""
        tx = self.transaction_repository.get_by_transaction_id(transaction_id)

        if tx is None:
            raise NotFoundPixTransaction(transaction_id)

        return PixTransactionDTO.obj_to_dict(tx)

    @staticmethod
    def _replay(existing: TransactionHistory, payload_sha256: str) -> dict:
        """Mesmo id: mesmo conteúdo devolve o veredito já dado; outro conteúdo é 409.

        Linha gravada antes da v2 não tem hash: vale o veredito antigo.
        """
        if existing.payload_sha256 is not None and existing.payload_sha256 != payload_sha256:
            raise IdempotencyConflict(existing.transaction_id)
        return PixTransactionDTO.obj_to_dict(existing)


def _violated_constraint(error: IntegrityError):
    diag = getattr(error.orig, "diag", None)
    return getattr(diag, "constraint_name", None)
