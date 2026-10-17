from controllers.base_controller import BaseController
from dtos import PixTransactionDTO
from errors import NotFoundPixTransaction
from repositories import (
    GeolocationRepository,
    StatusResultHistoryRepository,
    TransactionRepository,
)


class PixTransactionController(BaseController):
    """Regras de negócio e orquestração da análise de transações PIX antifraude."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.transaction_repository = TransactionRepository(self.context)
        self.geolocation_repository = GeolocationRepository(self.context)
        self.status_result_history_repository = StatusResultHistoryRepository(self.context)

    def _evaluate_antifraud(self, payload: dict) -> str:
        """Aqui você pode aplicar suas regras de negócio de antifraude.

        Status possíveis (definidos no enum_status_result do banco):
          - 'approved'
          - 'rejected'
          - 'two_factor_required'

        Exemplo de ideias para regras:
          - Análise do valor (amount)
          - Histórico da conta de origem (self.transaction_repository.list_by_source_account)
          - Histórico do dispositivo (self.transaction_repository.list_by_device)
          - IP / Geolocalização suspeita
        """
        # Regra padrão inicial (espaço reservado para a sua lógica de negócio):
        return "approved"

    def create(self, payload: dict) -> dict:
        """Processa e registra uma nova transação PIX com análise antifraude."""
        self.logger.debug("Processando nova transação PIX para antifraude")

        geolocation_id = None
        if "geolocation" in payload and payload["geolocation"]:
            geo = self.geolocation_repository.create(
                latitude=payload["geolocation"]["latitude"],
                longitude=payload["geolocation"]["longitude"],
            )
            geolocation_id = geo.id_geolocation
        elif "source_geolocation" in payload and payload["source_geolocation"]:
            geolocation_id = payload["source_geolocation"]

        tx = self.transaction_repository.create(
            transaction_data=payload,
            geolocation_id=geolocation_id,
        )

        decision = self._evaluate_antifraud(payload)

        self.status_result_history_repository.create(
            key_pix=tx.key_pix,
            status=decision,
            date=tx.transaction_date,
        )

        # Monta o DTO antes do commit conforme padrão arquitetural do projeto
        result_dto = PixTransactionDTO.obj_to_dict(tx)

        self.session.commit()

        return result_dto

    def get_by_id(self, key_pix: int) -> dict:
        """Busca os detalhes e o histórico de vereditos de uma transação pelo ID (key_pix)."""
        tx = self.transaction_repository.get_by_key_pix(key_pix)

        if tx is None:
            raise NotFoundPixTransaction(key_pix)

        return PixTransactionDTO.obj_to_dict(tx)
