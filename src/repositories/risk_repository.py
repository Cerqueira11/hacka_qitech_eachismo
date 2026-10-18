from datetime import datetime
from typing import List, Set, Tuple
from uuid import UUID

from sqlalchemy import exists, func, or_, and_, select

from database import Context
from models import Geolocation, PersonLink, RegisteredDevice, StatusResultHistory, TransactionHistory


def latest_status():
    """Último veredito de cada transação, para usar dentro de um WHERE."""
    return (
        select(StatusResultHistory.status)
        .where(StatusResultHistory.key_pix == TransactionHistory.key_pix)
        .order_by(StatusResultHistory.date.desc())
        .limit(1)
        .correlate(TransactionHistory)
        .scalar_subquery()
    )


def not_rejected():
    # Pix rejeitado não movimentou dinheiro: não entra em soma, média nem padrão.
    return latest_status() != "rejected"


class RiskRepository:
    """As consultas que alimentam as regras antifraude.

    Todas olham só o passado: a janela termina em `as_of` (a data do Pix em
    análise), e o Pix em análise ainda não foi gravado quando elas rodam.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    # ── R1: dispositivo ─────────────────────────────────────────────────
    def is_device_registered(self, document_number: str, device_id: str) -> bool:
        return self.session.query(
            exists().where(
                RegisteredDevice.document_number == document_number,
                RegisteredDevice.device_id == device_id,
            )
        ).scalar()

    def sum_unregistered_device_amount(
        self, source_account_id: UUID, document_number: str, since: datetime, as_of: datetime
    ) -> int:
        """Quanto a conta já movimentou no período por dispositivos não cadastrados."""
        registered = exists().where(
            RegisteredDevice.document_number == document_number,
            RegisteredDevice.device_id == TransactionHistory.source_device_id,
        )
        total = (
            self.session.query(func.coalesce(func.sum(TransactionHistory.amount), 0))
            .filter(
                TransactionHistory.source_account_id == source_account_id,
                TransactionHistory.transaction_date >= since,
                TransactionHistory.transaction_date <= as_of,
                ~registered,
                not_rejected(),
            )
            .scalar()
        )
        return int(total)

    # ── R2 / R6: histórico de valores ───────────────────────────────────
    def list_source_history(
        self, source_account_id: UUID, since: datetime, as_of: datetime, limit: int = 500
    ) -> List[Tuple[int, datetime]]:
        rows = (
            self.session.query(TransactionHistory.amount, TransactionHistory.transaction_date)
            .filter(
                TransactionHistory.source_account_id == source_account_id,
                TransactionHistory.transaction_date >= since,
                TransactionHistory.transaction_date <= as_of,
                not_rejected(),
            )
            .order_by(TransactionHistory.transaction_date.desc())
            .limit(limit)
            .all()
        )
        return [(int(amount), date) for amount, date in rows]

    # ── R5: localização ─────────────────────────────────────────────────
    def list_source_geolocations(
        self, source_account_id: UUID, as_of: datetime, limit: int = 10
    ) -> List[Tuple[datetime, float, float]]:
        rows = (
            self.session.query(TransactionHistory.transaction_date, Geolocation.latitude, Geolocation.longitude)
            .join(Geolocation, Geolocation.id_geolocation == TransactionHistory.source_geolocation)
            .filter(
                TransactionHistory.source_account_id == source_account_id,
                TransactionHistory.transaction_date <= as_of,
                not_rejected(),
            )
            .order_by(TransactionHistory.transaction_date.desc())
            .limit(limit)
            .all()
        )
        return [(date, float(lat), float(lon)) for date, lat, lon in rows]

    # ── R7: recorrência ─────────────────────────────────────────────────
    def list_approved_to_destination(
        self, source_account_id: UUID, destination_account_id: UUID, since: datetime, as_of: datetime
    ) -> List[Tuple[int, datetime]]:
        rows = (
            self.session.query(TransactionHistory.amount, TransactionHistory.transaction_date)
            .filter(
                TransactionHistory.source_account_id == source_account_id,
                TransactionHistory.destination_account_id == destination_account_id,
                TransactionHistory.transaction_date >= since,
                TransactionHistory.transaction_date <= as_of,
                latest_status() == "approved",
            )
            .order_by(TransactionHistory.transaction_date.asc())
            .all()
        )
        return [(int(amount), date) for amount, date in rows]

    # ── R8: velocity ────────────────────────────────────────────────────
    def count_source_attempts(self, source_account_id: UUID, since: datetime, as_of: datetime) -> int:
        """Todas as tentativas, inclusive rejeitadas: insistência também é sinal."""
        return (
            self.session.query(func.count(TransactionHistory.key_pix))
            .filter(
                TransactionHistory.source_account_id == source_account_id,
                TransactionHistory.transaction_date >= since,
                TransactionHistory.transaction_date <= as_of,
            )
            .scalar()
        )

    def distinct_sources_to_destination(
        self, destination_account_id: UUID, since: datetime, as_of: datetime
    ) -> Set[UUID]:
        rows = (
            self.session.query(TransactionHistory.source_account_id)
            .filter(
                TransactionHistory.destination_account_id == destination_account_id,
                TransactionHistory.transaction_date >= since,
                TransactionHistory.transaction_date <= as_of,
            )
            .distinct()
            .all()
        )
        return {row[0] for row in rows}

    def distinct_sources_on_device(self, device_id: str, since: datetime, as_of: datetime) -> Set[UUID]:
        rows = (
            self.session.query(TransactionHistory.source_account_id)
            .filter(
                TransactionHistory.source_device_id == device_id,
                TransactionHistory.transaction_date >= since,
                TransactionHistory.transaction_date <= as_of,
            )
            .distinct()
            .all()
        )
        return {row[0] for row in rows}

    # ── Arestas anteriores entre as duas contas ─────────────────────────
    def has_edge(self, source_account_id: UUID, destination_account_id: UUID, either_direction: bool) -> bool:
        same_direction = and_(
            TransactionHistory.source_account_id == source_account_id,
            TransactionHistory.destination_account_id == destination_account_id,
        )
        condition = same_direction
        if either_direction:
            condition = or_(
                same_direction,
                and_(
                    TransactionHistory.source_account_id == destination_account_id,
                    TransactionHistory.destination_account_id == source_account_id,
                ),
            )
        return self.session.query(exists().where(condition, not_rejected())).scalar()

    # ── R4: vínculos CPF <-> CNPJ ───────────────────────────────────────
    def linked_documents(self, document_number: str) -> List[str]:
        rows = (
            self.session.query(PersonLink.cpf, PersonLink.cnpj)
            .filter(or_(PersonLink.cpf == document_number, PersonLink.cnpj == document_number))
            .all()
        )
        linked = set()
        for cpf, cnpj in rows:
            linked.add(cnpj.strip() if cpf.strip() == document_number else cpf.strip())
        return sorted(linked)
