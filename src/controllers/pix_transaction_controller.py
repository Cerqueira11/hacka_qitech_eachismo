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
    DeviceRepository,
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
        self.device_repository = DeviceRepository(self.context)

        self.context_builder = ContextBuilder(
            RiskRepository(self.context), DictMockClient(), self.device_repository, DeviceApiClient()
        )
        self.graph_scorer = GraphScorer(GraphRepository(self.context))
        self.engine = AntifraudEngine(self.graph_scorer)

    def create(self, payload: dict) -> Tuple[dict, bool]:
        """Analisa e registra um Pix. Devolve (veredito, criado_agora).

        O "id" do payload é a chave de idempotência: reenviar o mesmo Pix
        devolve o veredito já dado, em vez de analisar (e gravar) de novo.
        Mesmo "id" com outro conteúdo é 409 (C4).

        Ordem (C4): externos → lock por origem → idempotência → upsert →
        regras → gravação → commit. Dispositivo (R1): registered_device
        primeiro, API externa só se não achar; o 200 é gravado na tabela.
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
        # segura a fila de Pix da mesma origem. O dispositivo é procurado
        # primeiro em registered_device; a API só é chamada se não estiver lá.
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
        if external.device_confirmed_by_api:
            # A API confirmou: o próximo Pix deste device nem chama a API.
            self.device_repository.save(data.source_account.document_number, data.device_id)

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

    def submit_2fa(self, transaction_id: str, payload: dict) -> dict:
        """Grava o resultado do 2FA (approved | rejected) para uma transação (D2)."""
        tx = self.transaction_repository.get_by_transaction_id(transaction_id)
        if tx is None:
            raise NotFoundPixTransaction(transaction_id)

        latest = tx.status_history[0]
        status = payload["status"]

        if latest.status == status:
            return PixTransactionDTO.obj_to_dict(tx)

        self.status_result_history_repository.create(
            transaction=tx,
            status=status,
            metadata=latest.metadata_item,
        )

        if status == "approved":
            # Incrementa o grau entre nós se for uma nova conexão
            has_prev = self.context_builder.risk.has_edge(
                tx.source_account_id, tx.destination_account_id, either_direction=True
            )
            degree_increment = 0 if has_prev else 1
            if degree_increment > 0:
                self.graph_scorer.graph.update_node_risk(
                    tx.destination_account_id,
                    evidence=float(tx.risk_score or 0),
                    alpha=antifraud_config.DESTINATION_LEARNING_RATE,
                    as_of=tx.transaction_date,
                    tau_days=antifraud_config.GRAPH_TIME_DECAY_DAYS,
                    external_risk=None,
                    degree_increment=degree_increment,
                )
                self.graph_scorer.graph.update_node_risk(
                    tx.source_account_id,
                    evidence=float(tx.risk_score or 0),
                    alpha=antifraud_config.SOURCE_LEARNING_RATE,
                    as_of=tx.transaction_date,
                    tau_days=antifraud_config.GRAPH_TIME_DECAY_DAYS,
                    external_risk=None,
                    degree_increment=degree_increment,
                )

        self.session.commit()
        self.logger.info(f"2FA para transação {transaction_id} concluído com status: {status}")
        return PixTransactionDTO.obj_to_dict(tx)

    def report_fraud(self, transaction_id: str) -> dict:
        """Marcação de fraude confirmada (MED / contestação - D3).

        A aresta da transação vai a 1.0 e o destino recebe external_risk = 1.0.
        O status mais recente passa a ser rejected.
        """
        tx = self.transaction_repository.get_by_transaction_id(transaction_id)
        if tx is None:
            raise NotFoundPixTransaction(transaction_id)

        # Aresta vai a 1.0 (peso de fraude confirmada)
        tx.risk_score = 1.0

        latest = tx.status_history[0]
        self.status_result_history_repository.create(
            transaction=tx,
            status="rejected",
            metadata=latest.metadata_item,
        )

        # Nó destino recebe external_risk = 1.0
        self.graph_scorer.graph.update_node_risk(
            tx.destination_account_id,
            evidence=1.0,
            alpha=1.0,
            as_of=tx.transaction_date,
            tau_days=antifraud_config.GRAPH_TIME_DECAY_DAYS,
            external_risk=1.0,
            degree_increment=0,
        )

        self.session.commit()
        self.logger.info(f"Fraude confirmada para Pix {transaction_id}. Conta destino marcada com risco 1.0.")
        return {
            "transaction_id": transaction_id,
            "status": "fraud_confirmed",
            "destination_account_id": str(tx.destination_account_id),
            "risk_score": 1.0,
        }

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
