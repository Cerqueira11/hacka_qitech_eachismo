from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Set, Tuple
from uuid import UUID

from antifraud import config
from connectors.device_client import DeviceApiClient, DeviceApiUnavailable
from connectors.dict_client import CLEAN_PERSON, DictApiClient, DictPersonRisk, DictUnavailable
from dtos.pix_transaction_input import PixTransactionInput
from models import AccountNode
from repositories import DeviceRepository, RiskRepository
from utils.logger import get_logger

logger = get_logger(__name__)


def is_night(local_time: datetime) -> bool:
    return local_time.hour >= config.NIGHT_START_HOUR or local_time.hour < config.NIGHT_END_HOUR


def night_window(local_time: datetime) -> Tuple[datetime, datetime]:
    """[início, fim) da noite que contém local_time (que precisa ser noturno).

    Ancorada no início do período: às 2h, a noite começou às 20h do dia anterior.
    """
    start = local_time.replace(hour=config.NIGHT_START_HOUR, minute=0, second=0, microsecond=0)
    if local_time.hour < config.NIGHT_END_HOUR:
        start -= timedelta(days=1)
    night_hours = 24 - config.NIGHT_START_HOUR + config.NIGHT_END_HOUR
    return start, start + timedelta(hours=night_hours)


@dataclass(frozen=True)
class ExternalSignals:
    """O que vem de fora do nosso banco. É buscado ANTES do lock por origem (C4):
    uma API lenta não segura a fila de Pix da mesma conta."""

    # DICT: só estatísticas por documento (R4). dict_available=False -> R4 pede 2FA.
    dict_available: bool = True
    source_person: DictPersonRisk = CLEAN_PERSON
    destination_person: DictPersonRisk = CLEAN_PERSON
    source_linked: Tuple[Tuple[str, DictPersonRisk], ...] = ()
    destination_linked: Tuple[Tuple[str, DictPersonRisk], ...] = ()

    # Dispositivo (R1): registered_device primeiro, API externa só se não achar.
    # None = API indisponível -> R1 pede 2FA.
    device_registered: Optional[bool] = None
    # True quando a API acabou de confirmar (200): o controller grava em registered_device.
    device_confirmed_by_api: bool = False


@dataclass
class AntifraudContext:
    """Tudo o que as regras precisam saber sobre um Pix, calculado ANTES de gravá-lo."""

    data: PixTransactionInput
    source: AccountNode
    destination: AccountNode
    as_of: datetime
    local_time: datetime

    # Nosso banco
    source_owner_conflict: bool = False        # origem verificada com outro documento
    destination_owner_conflict: bool = False   # destino verificado (já foi origem) com outro documento
    unregistered_device_amount_today: int = 0
    night_amount: int = 0              # soma da origem na noite corrente (sem o Pix atual)
    night_average: float = 0.0         # média das somas noturnas dos últimos 90 dias
    nights_with_pix: int = 0
    source_history: List[Tuple[int, datetime]] = field(default_factory=list)
    source_geolocations: List[Tuple[datetime, float, float]] = field(default_factory=list)
    approved_to_destination: List[Tuple[int, datetime]] = field(default_factory=list)
    source_attempts_short: int = 0   # tentativas anteriores na janela curta
    source_attempts_long: int = 0    # tentativas anteriores na janela longa
    destination_sources_window: Set[UUID] = field(default_factory=set)  # inclui a origem atual
    device_sources_window: Set[UUID] = field(default_factory=set)       # inclui a origem atual
    ip_sources_window: Set[UUID] = field(default_factory=set)           # inclui a origem atual (N1)
    is_new_ip_for_source: bool = False                                  # True se a origem tem histórico de IP e este é inédito (N2)
    has_previous_edge_to_destination: bool = False
    has_previous_pair_edge: bool = False

    # R9 — conta de passagem (pass-through): comportamento acumulado na janela.
    source_fan_in: int = 0           # origens distintas que pagaram a ORIGEM deste Pix
    source_fan_out: int = 0          # destinos distintos que a ORIGEM pagou
    source_incoming: int = 0         # total que entrou na ORIGEM
    source_outgoing: int = 0         # total que saiu da ORIGEM
    destination_fan_in: int = 0      # origens distintas que pagaram o DESTINO deste Pix
    destination_fan_out: int = 0     # destinos distintos que o DESTINO pagou
    destination_incoming: int = 0    # total que entrou no DESTINO
    destination_outgoing: int = 0    # total que saiu do DESTINO

    # De fora (ExternalSignals)
    device_api_available: bool = True
    device_registered: bool = False
    dict_available: bool = True
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

    @property
    def source_pass_through_ratio(self) -> float:
        """(saiu) / (entrou) na ORIGEM. 0 se nada entrou (não há o que repassar)."""
        return (self.source_outgoing / self.source_incoming) if self.source_incoming > 0 else 0.0

    @property
    def destination_pass_through_ratio(self) -> float:
        """(saiu) / (entrou) no DESTINO. 0 se nada entrou (não há o que repassar)."""
        return (self.destination_outgoing / self.destination_incoming) if self.destination_incoming > 0 else 0.0


class ContextBuilder:
    def __init__(
        self,
        risk_repository: RiskRepository,
        dict_client: DictApiClient,
        device_repository: DeviceRepository,
        device_client: DeviceApiClient,
    ) -> None:
        self.risk = risk_repository
        self.dict = dict_client
        self.devices = device_repository
        self.device_api = device_client

    # ── Fora do lock ────────────────────────────────────────────────────
    def load_external(self, data: PixTransactionInput) -> ExternalSignals:
        registered, confirmed_by_api = self._load_device(data)
        return self._load_dict(data, registered, confirmed_by_api)

    def _load_device(self, data: PixTransactionInput) -> Tuple[Optional[bool], bool]:
        """(registrado?, confirmado agora pela API?).

        1. registered_device tem o par (documento, device) .... registrado, sem chamar a API
        2. senão, API externa responde registered = true ...... registrado; o controller grava na tabela
        3. API responde 404 (ou registered = false) .......... não registrado; nada é gravado,
                                                                 a próxima vez pergunta de novo
        4. API indisponível ................................... None: a R1 pede 2FA
        """
        document_number = data.source_account.document_number
        if self.devices.is_registered(document_number, data.device_id):
            return True, False
        try:
            registered = self.device_api.is_registered(document_number, data.device_id)
        except DeviceApiUnavailable as error:
            # Sem a API, a R1 não tem como decidir: o motor pede 2FA.
            logger.warning(f"API de dispositivo indisponível, seguindo sem ela: {error}")
            return None, False
        return registered, registered

    def _load_dict(
        self, data: PixTransactionInput, device_registered: Optional[bool], device_confirmed_by_api: bool
    ) -> ExternalSignals:
        source_document = data.source_account.document_number
        destination_document = data.destination_account.document_number
        try:
            return ExternalSignals(
                dict_available=True,
                source_person=self.dict.get_person_risk(source_document),
                destination_person=self.dict.get_person_risk(destination_document),
                source_linked=tuple(
                    (document, self.dict.get_person_risk(document))
                    for document in self.risk.linked_documents(source_document)
                ),
                destination_linked=tuple(
                    (document, self.dict.get_person_risk(document))
                    for document in self.risk.linked_documents(destination_document)
                ),
                device_registered=device_registered,
                device_confirmed_by_api=device_confirmed_by_api,
            )
        except DictUnavailable as error:
            # Sem DICT, a R4 não tem como decidir: o motor pede 2FA. A R3 não usa o DICT (C2).
            logger.warning(f"DICT indisponível, seguindo sem ele: {error}")
            return ExternalSignals(
                dict_available=False,
                device_registered=device_registered,
                device_confirmed_by_api=device_confirmed_by_api,
            )

    # ── Dentro do lock ──────────────────────────────────────────────────
    def build(
        self, data: PixTransactionInput, source: AccountNode, destination: AccountNode, external: ExternalSignals
    ) -> AntifraudContext:
        as_of = data.transaction_date
        local_time = as_of.astimezone(config.BRASILIA)
        day_start = local_time.replace(hour=0, minute=0, second=0, microsecond=0)
        history_since = as_of - timedelta(days=config.HISTORY_WINDOW_DAYS)

        ctx = AntifraudContext(data=data, source=source, destination=destination, as_of=as_of, local_time=local_time)

        # R3 (C2): só nó verificado tem documento para divergir. O upsert da
        # origem já corrigiu nó não verificado; o do destino nunca altera.
        # Se divergir, confere se é documento vinculado (ex.: MEI/sócio CPF <-> CNPJ).
        source_conflict = (
            source.document_verified and source.document_number != data.source_account.document_number
        )
        if source_conflict and data.source_account.document_number in self.risk.linked_documents(source.document_number):
            source_conflict = False
        ctx.source_owner_conflict = source_conflict

        destination_conflict = (
            destination.document_verified and destination.document_number != data.destination_account.document_number
        )
        if destination_conflict and data.destination_account.document_number in self.risk.linked_documents(destination.document_number):
            destination_conflict = False
        ctx.destination_owner_conflict = destination_conflict

        ctx.device_api_available = external.device_registered is not None
        ctx.device_registered = bool(external.device_registered)
        ctx.unregistered_device_amount_today = self.risk.sum_unregistered_device_amount(
            source.id_account, day_start, day_start + timedelta(days=1)
        )

        if ctx.is_night:
            night_start, night_end = night_window(local_time)
            ctx.night_amount = self.risk.sum_source_amount(source.id_account, night_start, night_end)
            ctx.nights_with_pix, ctx.night_average = self.risk.night_totals_stats(
                source.id_account,
                since=night_start - timedelta(days=config.NIGHT_LOOKBACK_DAYS),
                until=night_start,  # noites anteriores: a corrente não entra na própria média
                local_tz=config.BRASILIA,
                night_start_hour=config.NIGHT_START_HOUR,
                night_end_hour=config.NIGHT_END_HOUR,
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
        ctx.ip_sources_window = self.risk.distinct_sources_on_ip(
            data.ip, as_of - config.IP_SHARED_WINDOW, as_of
        ) | {source.id_account}
        source_ips_count = self.risk.count_source_ips(source.id_account, as_of)
        ctx.is_new_ip_for_source = source_ips_count > 0 and not self.risk.has_seen_source_ip(
            source.id_account, data.ip, as_of
        )
        ctx.has_previous_edge_to_destination = self.risk.has_edge(
            source.id_account, destination.id_account, either_direction=False
        )
        ctx.has_previous_pair_edge = self.risk.has_edge(
            source.id_account, destination.id_account, either_direction=True
        )

        # R9 — conta de passagem: fan-in, fan-out e volumes acumulados na janela,
        # para origem e destino (o padrão mula pode estar dos dois lados).
        r9_since = as_of - timedelta(days=config.R9_WINDOW_DAYS)
        ctx.source_fan_in = self.risk.count_distinct_sources_to(source.id_account, r9_since, as_of)
        ctx.source_fan_out = self.risk.count_distinct_destinations_from(source.id_account, r9_since, as_of)
        ctx.source_incoming = self.risk.sum_incoming_amount(source.id_account, r9_since, as_of)
        ctx.source_outgoing = self.risk.sum_outgoing_amount(source.id_account, r9_since, as_of)
        ctx.destination_fan_in = self.risk.count_distinct_sources_to(destination.id_account, r9_since, as_of)
        ctx.destination_fan_out = self.risk.count_distinct_destinations_from(destination.id_account, r9_since, as_of)
        ctx.destination_incoming = self.risk.sum_incoming_amount(destination.id_account, r9_since, as_of)
        ctx.destination_outgoing = self.risk.sum_outgoing_amount(destination.id_account, r9_since, as_of)

        ctx.dict_available = external.dict_available
        ctx.source_person = external.source_person
        ctx.destination_person = external.destination_person
        ctx.source_linked = list(external.source_linked)
        ctx.destination_linked = list(external.destination_linked)
        return ctx
