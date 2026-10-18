"""O grafo antifraude: influência da vizinhança e aprendizado do risco dos nós.

nó     = account_node        risco R(u) = max(external_risk, risk_score decaído)
aresta = transaction_history peso = risk_score do Pix
"""

import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from antifraud import config
from antifraud.context import AntifraudContext
from antifraud.result import GraphInfluence, Verdict
from models import AccountNode
from repositories import GraphRepository


def decayed_learned_risk(node: AccountNode, as_of: datetime) -> float:
    """risk_score · e^(-Δt/τ): o risco aprendido perde força com o tempo."""
    learned = float(node.risk_score or 0)
    if learned == 0 or node.risk_updated_at is None:
        return learned
    elapsed_days = max(0.0, (as_of - node.risk_updated_at).total_seconds() / 86400)
    return learned * math.exp(-elapsed_days / config.GRAPH_TIME_DECAY_DAYS)


def node_risk(node: AccountNode, as_of: datetime) -> float:
    """R(u): o fato (DICT) nunca decai; a estimativa (aprendida) decai."""
    return max(float(node.external_risk or 0), decayed_learned_risk(node, as_of))


def describe(node: AccountNode) -> str:
    return f"{node.participant}/{node.branch}/{node.account_number}"


class GraphScorer:
    def __init__(self, graph_repository: GraphRepository) -> None:
        self.graph = graph_repository

    def influence(self, start: AccountNode, counterpart_id: UUID, as_of: datetime) -> GraphInfluence:
        """O quanto a vizinhança de `start` está suja. Busca em largura até K saltos.

        d = 0: o risco aprendido da própria conta, sem dividir por degree
               (dividir esconderia justamente a conta laranja, que recebe de muitos).
               O external_risk dela não entra aqui: R4 já tratou.
        d >= 1: λ^d · R(u) · e^(-Δt/τ) / log2(2 + degree(u))

        A contraparte deste Pix fica fora: ela é analisada pela outra ponta.
        """
        contributions: List[Tuple[float, AccountNode, int, float]] = []

        own = decayed_learned_risk(start, as_of)
        if own > 0:
            contributions.append((own, start, 0, own))

        since = as_of - timedelta(days=config.GRAPH_WINDOW_DAYS)
        visited = {start.id_account, counterpart_id}
        frontier = {start.id_account}

        for depth in range(1, config.GRAPH_MAX_DEPTH + 1):
            if not frontier:
                break

            reached: Dict[UUID, datetime] = {}
            for _from_id, to_id, last_seen in self.graph.neighbor_edges(frontier, since, as_of):
                if to_id in visited:
                    continue
                if to_id not in reached or last_seen > reached[to_id]:
                    reached[to_id] = last_seen
            if not reached:
                break

            # Limita o tamanho do nível: fica com as ligações mais recentes.
            nearest = sorted(reached.items(), key=lambda item: item[1], reverse=True)
            nearest = dict(nearest[: config.GRAPH_MAX_NODES_PER_LEVEL])
            nodes = self.graph.get_nodes(nearest.keys())

            hop_decay = config.GRAPH_HOP_DECAY**depth
            for node in nodes:
                risk = node_risk(node, as_of)
                if risk <= 0:
                    continue
                elapsed_days = max(0.0, (as_of - nearest[node.id_account]).total_seconds() / 86400)
                time_decay = math.exp(-elapsed_days / config.GRAPH_TIME_DECAY_DAYS)
                hub_penalty = math.log2(2 + (node.degree or 0))
                contributions.append((hop_decay * risk * time_decay / hub_penalty, node, depth, risk))

            visited.update(nearest.keys())
            # Não expande por hubs (varejista, folha de pagamento ligam todo mundo).
            frontier = {node.id_account for node in nodes if (node.degree or 0) <= config.GRAPH_MAX_DEGREE}

        if not contributions:
            return GraphInfluence(score=0.0, evidence=[])

        contributions.sort(key=lambda item: item[0], reverse=True)
        evidence = [
            {
                "account": describe(node),
                "distance": distance,
                "risk": round(risk, 4),
                "contribution": round(contribution, 4),
            }
            for contribution, node, distance, risk in contributions[: config.GRAPH_EVIDENCE_SIZE]
        ]
        return GraphInfluence(score=min(1.0, contributions[0][0]), evidence=evidence)

    def learn(self, ctx: AntifraudContext, verdict: Verdict) -> None:
        """Atualiza os nós depois de gravar o Pix.

        Usa o rules_score (o que as regras viram neste Pix), não o risk_score
        final: o risco que veio do grafo não volta para o grafo, senão a mesma
        conta suspeita seria contada duas vezes.
        """
        # degree conta contrapartes distintas; Pix rejeitado não cria ligação.
        new_link = verdict.status != "rejected" and not ctx.has_previous_pair_edge
        degree_increment = 1 if new_link else 0

        source_external: Optional[float] = ctx.source_person.external_risk if ctx.dict_available else None
        destination_external: Optional[float] = ctx.destination_person.external_risk if ctx.dict_available else None

        if ctx.source.id_account == ctx.destination.id_account:
            # Pix para a própria conta: atualiza uma vez só.
            self.graph.update_node_risk(
                ctx.destination.id_account, verdict.rules_score, config.DESTINATION_LEARNING_RATE,
                ctx.as_of, config.GRAPH_TIME_DECAY_DAYS, destination_external, 0,
            )
            return

        self.graph.update_node_risk(
            ctx.destination.id_account, verdict.rules_score, config.DESTINATION_LEARNING_RATE,
            ctx.as_of, config.GRAPH_TIME_DECAY_DAYS, destination_external, degree_increment,
        )
        self.graph.update_node_risk(
            ctx.source.id_account, verdict.rules_score, config.SOURCE_LEARNING_RATE,
            ctx.as_of, config.GRAPH_TIME_DECAY_DAYS, source_external, degree_increment,
        )
