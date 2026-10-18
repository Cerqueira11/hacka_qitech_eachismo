"""Sinais extras: sem ação fixa, só peso."""

from typing import List

from antifraud import config
from antifraud.context import AntifraudContext
from antifraud.result import RuleResult

RULE = "EXTRA"


def evaluate(ctx: AntifraudContext, previous: List[RuleResult]) -> List[RuleResult]:
    hits = []
    if ctx.destination_age_days < config.NEW_ACCOUNT_DAYS:
        hits.append(RuleResult(RULE, "destino_conta_nova", weight=config.NEW_DESTINATION_ACCOUNT_WEIGHT))
    if not ctx.has_previous_edge_to_destination:
        hits.append(RuleResult(RULE, "destino_desconhecido", weight=config.UNKNOWN_DESTINATION_WEIGHT))
    return hits
