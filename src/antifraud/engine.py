"""Motor antifraude: regras → grafo → score → decisão (ETAPAS 2 a 5 do README.md)."""

import math
from typing import Dict, List

from antifraud import config
from antifraud.context import AntifraudContext
from antifraud.graph import GraphScorer
from antifraud.result import STATUS_BY_ACTION, Action, RuleResult, Verdict
from antifraud.rules import RULES


def effective_weights(hits: List[RuleResult], discount: float = 0.0) -> List[float]:
    """Pesos que entram no noisy-OR.

    Sinais da mesma família medem a mesma coisa (R2 e R6: desvio de valor):
    entra só o maior peso da família, senão o mesmo desvio contaria duas vezes.
    O desconto de R7 incide exclusivamente sobre a família de desvio de valor (A3).
    """
    independent: List[float] = []
    strongest: Dict[str, float] = {}
    for hit in hits:
        if hit.weight <= 0:
            continue
        if hit.family is None:
            independent.append(hit.weight)
        else:
            strongest[hit.family] = max(strongest.get(hit.family, 0.0), hit.weight)

    if config.AMOUNT_DEVIATION_FAMILY in strongest and discount > 0:
        strongest[config.AMOUNT_DEVIATION_FAMILY] = max(
            0.0, strongest[config.AMOUNT_DEVIATION_FAMILY] * (1 - discount)
        )

    return independent + list(strongest.values())


def combine_rules(hits: List[RuleResult]) -> float:
    """noisy-OR dos pesos, com o desconto de R7 (teto MAX_DISCOUNT) na família de desvio de valor."""
    discount = min(config.MAX_DISCOUNT, sum(hit.discount for hit in hits))
    not_fraud = math.prod(1 - weight for weight in effective_weights(hits, discount))
    return 1 - not_fraud


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
        hits: List[RuleResult] = []
        for rule in RULES:
            hits.extend(rule(ctx, hits))

        source = self.graph.influence(ctx.source, ctx.destination.id_account, ctx.as_of)
        destination = self.graph.influence(ctx.destination, ctx.source.id_account, ctx.as_of)

        rules_score = combine_rules(hits)
        floor = max((hit.floor for hit in hits if hit.floor is not None), default=0.0)
        risk_score = combine_scores(rules_score, source.score, destination.score, floor)
        action = max((hit.action for hit in hits), default=Action.NONE)

        return Verdict(
            status=decide(action, risk_score),
            risk_score=round(risk_score, 4),
            rules_score=round(rules_score, 4),
            graph_source_score=round(source.score, 4),
            graph_destination_score=round(destination.score, 4),
            hits=tuple(hits),
            graph_evidence=[{"side": "source", **item} for item in source.evidence]
            + [{"side": "destination", **item} for item in destination.evidence],
        )
