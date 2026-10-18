"""Motor antifraude: regras → grafo → score → decisão (ETAPAS 2 a 5 de regras_antifraude.txt)."""

import math
from typing import List

from antifraud import config
from antifraud.context import AntifraudContext
from antifraud.graph import GraphScorer
from antifraud.result import STATUS_BY_ACTION, Action, RuleResult, Verdict
from antifraud.rules import RULES
from utils.logger import get_logger

logger = get_logger(__name__)


def combine_rules(hits: List[RuleResult]) -> float:
    """noisy-OR dos pesos, com o desconto de R7 (teto MAX_DISCOUNT)."""
    not_fraud = math.prod(1 - hit.weight for hit in hits if hit.weight > 0)
    discount = min(config.MAX_DISCOUNT, sum(hit.discount for hit in hits))
    return (1 - not_fraud) * (1 - discount)


def combine_scores(rules_score: float, graph_source: float, graph_destination: float, floor: float) -> float:
    risk = 1 - (
        (1 - rules_score)
        * (1 - config.SOURCE_GRAPH_WEIGHT * graph_source)
        * (1 - config.DESTINATION_GRAPH_WEIGHT * graph_destination)
    )
    return min(1.0, max(risk, floor))


def decide(action: Action, risk_score: float) -> str:
    if action == Action.REJECT or risk_score >= config.REJECT_THRESHOLD:
        return STATUS_BY_ACTION[Action.REJECT]
    if action == Action.TWO_FACTOR or risk_score >= config.TWO_FACTOR_THRESHOLD:
        return STATUS_BY_ACTION[Action.TWO_FACTOR]
    return STATUS_BY_ACTION[Action.NONE]


class AntifraudEngine:
    def __init__(self, graph_scorer: GraphScorer) -> None:
        self.graph = graph_scorer

    def evaluate(self, ctx: AntifraudContext) -> Verdict:
        # Todas as regras rodam, mesmo depois de um REJECT: o metadata guarda
        # todos os motivos e a aresta recebe o peso real.
        logger.info(
            f"Iniciando regras para Pix {ctx.data.transaction_id} "
            f"(valor={ctx.data.amount}, origem={ctx.source.id_account}, destino={ctx.destination.id_account})"
        )
        hits: List[RuleResult] = []
        for rule in RULES:
            rule_name = rule.__module__.rsplit(".", 1)[-1]
            logger.debug(f"Executando {rule_name} para Pix {ctx.data.transaction_id}")
            rule_hits = rule(ctx, hits)
            hits.extend(rule_hits)
            if rule_hits:
                logger.info(f"{rule_name}: sinais={ [hit.to_dict() for hit in rule_hits] }")
            else:
                logger.info(f"{rule_name}: sem sinais")

        logger.info(f"Iniciando analise do grafo para Pix {ctx.data.transaction_id}")
        source = self.graph.influence(ctx.source, ctx.destination.id_account, ctx.as_of)
        destination = self.graph.influence(ctx.destination, ctx.source.id_account, ctx.as_of)

        rules_score = combine_rules(hits)
        floor = max((hit.floor for hit in hits if hit.floor is not None), default=0.0)
        risk_score = combine_scores(rules_score, source.score, destination.score, floor)
        action = max((hit.action for hit in hits), default=Action.NONE)
        status = decide(action, risk_score)
        logger.info(
            f"Resultado do motor para Pix {ctx.data.transaction_id}: status={status} "
            f"rules_score={rules_score:.4f} graph_source={source.score:.4f} "
            f"graph_destination={destination.score:.4f} floor={floor:.4f} risk_score={risk_score:.4f}"
        )

        return Verdict(
            status=status,
            risk_score=round(risk_score, 4),
            rules_score=round(rules_score, 4),
            graph_source_score=round(source.score, 4),
            graph_destination_score=round(destination.score, 4),
            hits=tuple(hits),
            graph_evidence=[{"side": "source", **item} for item in source.evidence]
            + [{"side": "destination", **item} for item in destination.evidence],
        )
