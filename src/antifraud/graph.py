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
from utils.logger import get_logger

logger = get_logger(__name__)


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
        logger.info(
            f"Grafo: iniciando busca no={start.id_account}, contraparte_excluida={counterpart_id}, "
            f"profundidade_maxima={config.GRAPH_MAX_DEPTH}"
        )
        contributions: List[Tuple[float, AccountNode, int, float]] = []

        own = decayed_learned_risk(start, as_of)
        if own > 0:
            contributions.append((own, start, 0, own))

        since = as_of - timedelta(days=config.GRAPH_WINDOW_DAYS)
        visited = {start.id_account, counterpart_id}
        frontier = {start.id_account}

        for depth in range(1, config.GRAPH_MAX_DEPTH + 1):
            if not frontier:
                logger.debug(f"Grafo: busca encerrada no nivel {depth}; fronteira vazia")
                break

            reached: Dict[UUID, datetime] = {}
            edges = self.graph.neighbor_edges(frontier, since, as_of)
            for _from_id, to_id, last_seen in edges:
                if to_id in visited:
                    continue
                if to_id not in reached or last_seen > reached[to_id]:
                    reached[to_id] = last_seen
            if not reached:
                logger.info(f"Grafo: nivel={depth}, arestas_consultadas={len(edges)}, novos_nos=0")
                break

            # Limita o tamanho do nível: fica com as ligações mais recentes.
            nearest = sorted(reached.items(), key=lambda item: item[1], reverse=True)
            nearest = dict(nearest[: config.GRAPH_MAX_NODES_PER_LEVEL])
            nodes = self.graph.get_nodes(nearest.keys())
            logger.info(
                f"Grafo: nivel={depth}, arestas_consultadas={len(edges)}, "
                f"nos_alcancados={len(reached)}, nos_avaliados={len(nodes)}"
            )

            hop_decay = config.GRAPH_HOP_DECAY**depth
            for node in nodes:
                risk = node_risk(node, as_of)
                if risk <= 0:
                    continue
                elapsed_days = max(0.0, (as_of - nearest[node.id_account]).total_seconds() / 86400)
                time_decay = math.exp(-elapsed_days / config.GRAPH_TIME_DECAY_DAYS)
                hub_penalty = math.log2(2 + (node.degree or 0))
                contributions.append((hop_decay * risk * time_decay / hub_penalty, node, depth, risk))
                logger.debug(
                    f"Grafo: contribuicao no={node.id_account}, nivel={depth}, "
                    f"risco={risk:.4f}, contribuicao={contributions[-1][0]:.4f}"
                )

            visited.update(nearest.keys())
            # Não expande por hubs (varejista, folha de pagamento ligam todo mundo).
            frontier = {node.id_account for node in nodes if (node.degree or 0) <= config.GRAPH_MAX_DEGREE}

        if not contributions:
            logger.info(f"Grafo: no={start.id_account}, score=0.0000, sem evidencias")
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
        score = min(1.0, contributions[0][0])
        evidence_summary = [{key: value for key, value in item.items() if key != "account"} for item in evidence]
        logger.info(f"Grafo: no={start.id_account}, score={score:.4f}, evidencias={evidence_summary}")
        return GraphInfluence(score=score, evidence=evidence)

    def learn(self, ctx: AntifraudContext, verdict: Verdict) -> None:
        """Atualiza os nós depois de gravar o Pix.

        Usa o rules_score (o que as regras viram neste Pix), não o risk_score
        final: o risco que veio do grafo não volta para o grafo, senão a mesma
        conta suspeita seria contada duas vezes.
        """
        # degree conta contrapartes distintas; Pix rejeitado não cria ligação.
        new_link = verdict.status != "rejected" and not ctx.has_previous_pair_edge
        degree_increment = 1 if new_link else 0
        logger.info(
            f"Grafo: aprendendo Pix {ctx.data.transaction_id}, status={verdict.status}, "
            f"evidencia={verdict.rules_score:.4f}, incremento_degree={degree_increment}"
        )

        source_external: Optional[float] = ctx.source_person.external_risk if ctx.dict_available else None
        destination_external: Optional[float] = ctx.destination_person.external_risk if ctx.dict_available else None

        if ctx.source.id_account == ctx.destination.id_account:
            # Pix para a própria conta: atualiza uma vez só.
            logger.info(f"Grafo: origem e destino sao o mesmo no ({ctx.source.id_account}); atualizando uma vez")
            self.graph.update_node_risk(
                ctx.destination.id_account, verdict.rules_score, config.DESTINATION_LEARNING_RATE,
                ctx.as_of, config.GRAPH_TIME_DECAY_DAYS, destination_external, 0,
            )
            return

        self.graph.update_node_risk(
            ctx.destination.id_account, verdict.rules_score, config.DESTINATION_LEARNING_RATE,
            ctx.as_of, config.GRAPH_TIME_DECAY_DAYS, destination_external, degree_increment,
        )
        logger.debug(f"Grafo: risco atualizado para no de destino {ctx.destination.id_account}")
        self.graph.update_node_risk(
            ctx.source.id_account, verdict.rules_score, config.SOURCE_LEARNING_RATE,
            ctx.as_of, config.GRAPH_TIME_DECAY_DAYS, source_external, degree_increment,
        )
        logger.debug(f"Grafo: risco atualizado para no de origem {ctx.source.id_account}")
