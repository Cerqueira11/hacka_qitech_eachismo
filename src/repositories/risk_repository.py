from datetime import datetime, timedelta, tzinfo
from typing import List, Set, Tuple
from uuid import UUID

from sqlalchemy import Date, Interval, and_, cast, exists, func, or_, select

from database import Context
from models import Geolocation, PersonLink, StatusResultHistory, TransactionHistory


def _utc_offset(local_tz: tzinfo) -> str:
    """'-03:00' para UTC-3. O timedelta de Python (-1 dia + 21h) não serve:
    o Postgres recusa fuso em interval com dias."""
    minutes = int(local_tz.utcoffset(None).total_seconds() // 60)
    sign = "-" if minutes < 0 else "+"
    hours, minutes = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


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

    O Pix em análise ainda não foi gravado quando elas rodam. Os históricos
    terminam em `as_of` (a data do Pix em análise); as somas de período
    corrente (dia da R1, noite da R2) cobrem o período inteiro, para que o
    lock por origem (C4) as mantenha corretas em rajadas paralelas.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    # ── R1: dispositivo ─────────────────────────────────────────────────
    def sum_unregistered_device_amount(self, source_account_id: UUID, start: datetime, end: datetime) -> int:
        """Quanto a origem movimentou em [start, end) por dispositivos não cadastrados.

        Usa o device_registered gravado em cada Pix (o que a R1 concluiu naquele
        momento: registered_device ou a API de dispositivo). Pix com a API indisponível (NULL) não
        entram: a R1 não foi avaliada neles, e contar seria rejeitar por falha nossa.

        A janela é o dia inteiro, não "até o Pix atual": com o lock por origem
        (C4), um Pix processado depois enxerga todos os que já foram gravados,
        mesmo que o transaction_date dele seja um pouco anterior.
        """
        total = (
            self.session.query(func.coalesce(func.sum(TransactionHistory.amount), 0))
            .filter(
                TransactionHistory.source_account_id == source_account_id,
                TransactionHistory.transaction_date >= start,
                TransactionHistory.transaction_date < end,
                TransactionHistory.device_registered.is_(False),
                not_rejected(),
            )
            .scalar()
        )
        return int(total)

    # ── R2: padrão noturno ──────────────────────────────────────────────
    def sum_source_amount(self, source_account_id: UUID, start: datetime, end: datetime) -> int:
        """Soma da origem em [start, end): approved + 2FA pendente (não rejeitados)."""
        total = (
            self.session.query(func.coalesce(func.sum(TransactionHistory.amount), 0))
            .filter(
                TransactionHistory.source_account_id == source_account_id,
                TransactionHistory.transaction_date >= start,
                TransactionHistory.transaction_date < end,
                not_rejected(),
            )
            .scalar()
        )
        return int(total)

    def night_totals_stats(
        self,
        source_account_id: UUID,
        since: datetime,
        until: datetime,
        local_tz: tzinfo,
        night_start_hour: int,
        night_end_hour: int,
    ) -> Tuple[int, float]:
        """(noites com Pix, média das somas dessas noites) em [since, until).

        Uma noite vai das night_start_hour às night_end_hour do dia seguinte,
        no fuso local_tz. Deslocar o horário local em -night_start_hour faz
        todos os Pix da mesma noite caírem na mesma data, que vira a chave.
        """
        local_time = func.timezone(cast(_utc_offset(local_tz), Interval), TransactionHistory.transaction_date)
        hour = func.extract("hour", local_time)
        night_key = cast(local_time - timedelta(hours=night_start_hour), Date)

        nightly = (
            select(func.sum(TransactionHistory.amount).label("total"))
            .where(
                TransactionHistory.source_account_id == source_account_id,
                TransactionHistory.transaction_date >= since,
                TransactionHistory.transaction_date < until,
                or_(hour >= night_start_hour, hour < night_end_hour),
                not_rejected(),
            )
            .group_by(night_key)
            .subquery()
        )
        nights, average = self.session.execute(
            select(func.count(), func.coalesce(func.avg(nightly.c.total), 0)).select_from(nightly)
        ).one()
        return int(nights), float(average)

    # ── R6: histórico de valores ────────────────────────────────────────
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
