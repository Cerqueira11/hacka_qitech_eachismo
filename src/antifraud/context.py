from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Set, Tuple
from uuid import UUID

from antifraud import config
from connectors.dict_client import CLEAN_PERSON, DictEntry, DictMockClient, DictPersonRisk, DictUnavailable
from dtos.pix_transaction_input import PixTransactionInput
from models import AccountNode
from repositories import RiskRepository
from utils.logger import get_logger

logger = get_logger(__name__)


def is_night(local_time: datetime) -> bool:
    return local_time.hour >= config.NIGHT_START_HOUR or local_time.hour < config.NIGHT_END_HOUR


@dataclass
class AntifraudContext:
    """Tudo o que as regras precisam saber sobre um Pix, calculado ANTES de gravá-lo."""

    data: PixTransactionInput
    source: AccountNode
    destination: AccountNode
    as_of: datetime
    local_time: datetime

    # Nosso banco
    source_owner_conflict: bool = False
    destination_owner_conflict: bool = False
    device_registered: bool = False
    unregistered_device_amount_today: int = 0
    source_history: List[Tuple[int, datetime]] = field(default_factory=list)
    source_geolocations: List[Tuple[datetime, float, float]] = field(default_factory=list)
    approved_to_destination: List[Tuple[int, datetime]] = field(default_factory=list)
    source_attempts_short: int = 0   # tentativas anteriores na janela curta
    source_attempts_long: int = 0    # tentativas anteriores na janela longa
    destination_sources_window: Set[UUID] = field(default_factory=set)  # inclui a origem atual
    device_sources_window: Set[UUID] = field(default_factory=set)       # inclui a origem atual
    has_previous_edge_to_destination: bool = False
    has_previous_pair_edge: bool = False

    # DICT
    dict_available: bool = True
    destination_entry: Optional[DictEntry] = None
    source_person: DictPersonRisk = CLEAN_PERSON
    destination_person: DictPersonRisk = CLEAN_PERSON
    source_linked: List[Tuple[str, DictPersonRisk]] = field(default_factory=list)
    destination_linked: List[Tuple[str, DictPersonRisk]] = field(default_factory=list)

    @property
    def is_night(self) -> bool:
        return is_night(self.local_time)

    @property
    def destination_age_days(self) -> float:
        opening_date = self.destination.opening_date or self.data.destination_account.opening_date
        return (self.as_of - opening_date).total_seconds() / 86400


class ContextBuilder:
    def __init__(self, risk_repository: RiskRepository, dict_client: DictMockClient) -> None:
        self.risk = risk_repository
        self.dict = dict_client

    def build(self, data: PixTransactionInput, source: AccountNode, destination: AccountNode) -> AntifraudContext:
        as_of = data.transaction_date
        local_time = as_of.astimezone(config.BRASILIA)
        day_start = local_time.replace(hour=0, minute=0, second=0, microsecond=0)
        history_since = as_of - timedelta(days=config.HISTORY_WINDOW_DAYS)
        source_document = data.source_account.document_number

        ctx = AntifraudContext(data=data, source=source, destination=destination, as_of=as_of, local_time=local_time)

        # O nó guarda o primeiro titular visto; o payload diz quem é agora.
        ctx.source_owner_conflict = source.document_number != data.source_account.document_number
        ctx.destination_owner_conflict = destination.document_number != data.destination_account.document_number

        ctx.device_registered = self.risk.is_device_registered(source_document, data.device_id)
        ctx.unregistered_device_amount_today = self.risk.sum_unregistered_device_amount(
            source.id_account, source_document, day_start, as_of
        )
        ctx.source_history = self.risk.list_source_history(source.id_account, history_since, as_of)
        ctx.source_geolocations = self.risk.list_source_geolocations(source.id_account, as_of)
        ctx.approved_to_destination = self.risk.list_approved_to_destination(
            source.id_account,
            destination.id_account,
            as_of - timedelta(days=config.RECURRING_WINDOW_DAYS),
            as_of,
        )
        ctx.source_attempts_short = self.risk.count_source_attempts(
            source.id_account, as_of - config.VELOCITY_SHORT_WINDOW, as_of
        )
        ctx.source_attempts_long = self.risk.count_source_attempts(
            source.id_account, as_of - config.VELOCITY_LONG_WINDOW, as_of
        )
        ctx.destination_sources_window = self.risk.distinct_sources_to_destination(
            destination.id_account, as_of - config.FAN_IN_WINDOW, as_of
        ) | {source.id_account}
        ctx.device_sources_window = self.risk.distinct_sources_on_device(
            data.device_id, as_of - config.DEVICE_SHARED_WINDOW, as_of
        ) | {source.id_account}
        ctx.has_previous_edge_to_destination = self.risk.has_edge(
            source.id_account, destination.id_account, either_direction=False
        )
        ctx.has_previous_pair_edge = self.risk.has_edge(
            source.id_account, destination.id_account, either_direction=True
        )

        self._load_dict(ctx)
        return ctx

    def _load_dict(self, ctx: AntifraudContext) -> None:
        source_document = ctx.data.source_account.document_number
        destination = ctx.data.destination_account
        try:
            ctx.destination_entry = self.dict.get_entry(
                destination.participant, destination.branch, destination.account_number, destination.document_number
            )
            ctx.source_person = self.dict.get_person_risk(source_document)
            ctx.destination_person = self.dict.get_person_risk(destination.document_number)
            ctx.source_linked = [
                (document, self.dict.get_person_risk(document))
                for document in self.risk.linked_documents(source_document)
            ]
            ctx.destination_linked = [
                (document, self.dict.get_person_risk(document))
                for document in self.risk.linked_documents(destination.document_number)
            ]
        except DictUnavailable as error:
            # Sem DICT, R3/R4 não têm como decidir: o motor pede 2FA.
            logger.warning(f"DICT indisponível, seguindo sem ele: {error}")
            ctx.dict_available = False
            ctx.destination_entry = None
            ctx.source_person = CLEAN_PERSON
            ctx.destination_person = CLEAN_PERSON
            ctx.source_linked = []
            ctx.destination_linked = []
