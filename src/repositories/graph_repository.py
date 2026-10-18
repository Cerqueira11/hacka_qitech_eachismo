from datetime import datetime
from typing import Iterable, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select, text, union_all

from database import Context
from models import AccountNode, TransactionHistory
from repositories.risk_repository import not_rejected

# O decaimento do risco aprendido é calculado aqui dentro, no próprio UPDATE,
# para que dois Pix simultâneos na mesma conta não sobrescrevam um ao outro.
UPDATE_NODE_RISK = text(
    """
    UPDATE account_node SET
        risk_score = LEAST(
            1.0,
            :alpha * :evidence
            + (1 - :alpha) * risk_score::float8 * exp(
                -GREATEST(
                    0,
                    EXTRACT(EPOCH FROM (
                        CAST(:as_of AS timestamptz) - COALESCE(risk_updated_at, CAST(:as_of AS timestamptz))
                    ))
                ) / 86400.0 / :tau_days
            )
        ),
        risk_updated_at = GREATEST(COALESCE(risk_updated_at, CAST(:as_of AS timestamptz)), CAST(:as_of AS timestamptz)),
        external_risk   = COALESCE(CAST(:external_risk AS numeric), external_risk),
        degree          = degree + :degree_increment,
        updated_at      = now()
    WHERE id_account = CAST(:id_account AS uuid)
    """
)


class GraphRepository:
    """Consultas e atualizações do grafo: nós (account_node) e arestas (transaction_history)."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def neighbor_edges(
        self, frontier: Iterable[UUID], since: datetime, as_of: datetime
    ) -> List[Tuple[UUID, UUID, datetime, float]]:
        """Arestas que saem ou chegam nos nós da fronteira.

        O grafo é percorrido nos dois sentidos. Aresta rejeitada não entra:
        o dinheiro não passou por ela. Para cada par, retorna a data e o risco
        da transação elegível mais recente.
        """
        frontier = list(frontier)
        if not frontier:
            return []

        def latest_edges(from_id, to_id):
            ranked = (
                select(
                    from_id.label("from_id"),
                    to_id.label("to_id"),
                    TransactionHistory.transaction_date.label("last_seen"),
                    TransactionHistory.risk_score.label("edge_risk"),
                    func.row_number()
                    .over(
                        partition_by=(
                            TransactionHistory.source_account_id,
                            TransactionHistory.destination_account_id,
                        ),
                        order_by=(
                            TransactionHistory.transaction_date.desc(),
                            TransactionHistory.key_pix.desc(),
                        ),
                    )
                    .label("edge_rank"),
                )
                .where(
                    from_id.in_(frontier),
                    TransactionHistory.transaction_date >= since,
                    TransactionHistory.transaction_date <= as_of,
                    not_rejected(),
                )
                .subquery()
            )
            return select(
                ranked.c.from_id,
                ranked.c.to_id,
                ranked.c.last_seen,
                ranked.c.edge_risk,
            ).where(ranked.c.edge_rank == 1)

        outgoing = latest_edges(
            TransactionHistory.source_account_id,
            TransactionHistory.destination_account_id,
        )
        incoming = latest_edges(
            TransactionHistory.destination_account_id,
            TransactionHistory.source_account_id,
        )
        rows = self.session.execute(union_all(outgoing, incoming)).all()
        return [
            (row.from_id, row.to_id, row.last_seen, float(row.edge_risk or 0))
            for row in rows
        ]

    def get_nodes(self, ids: Iterable[UUID]) -> List[AccountNode]:
        ids = list(ids)
        if not ids:
            return []
        return self.session.query(AccountNode).filter(AccountNode.id_account.in_(ids)).all()

    def update_node_risk(
        self,
        id_account: UUID,
        evidence: float,
        alpha: float,
        as_of: datetime,
        tau_days: float,
        external_risk: Optional[float],
        degree_increment: int,
    ) -> None:
        """risk_score ← alpha·evidence + (1-alpha)·risk_score decaído até as_of."""
        self.session.execute(
            UPDATE_NODE_RISK,
            {
                "id_account": str(id_account),
                "evidence": float(evidence),
                "alpha": float(alpha),
                "as_of": as_of,
                "tau_days": float(tau_days),
                "external_risk": external_risk,
                "degree_increment": int(degree_increment),
            },
        )
