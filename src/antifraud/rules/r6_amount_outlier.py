"""R6 — Valor fora do padrão da conta (z-score em escala log)."""

from typing import List

from antifraud import config
from antifraud.context import AntifraudContext
from antifraud.result import RuleResult
from antifraud.stats import log_zscore

RULE = "R6"


def evaluate(ctx: AntifraudContext, previous: List[RuleResult]) -> List[RuleResult]:
    amount = ctx.data.amount
    amounts = [value for value, _ in ctx.source_history]

    if len(amounts) < config.AMOUNT_MIN_HISTORY:
        if amount > config.AMOUNT_NO_HISTORY_LIMIT:
            return [RuleResult(RULE, "valor_alto_sem_historico", weight=config.AMOUNT_NO_HISTORY_WEIGHT)]
        return []

    z = log_zscore(amount, amounts, config.LOG_STD_FLOOR)
    if z is not None and z > config.AMOUNT_Z_THRESHOLD:
        weight = min(config.AMOUNT_MAX_WEIGHT, config.AMOUNT_WEIGHT_PER_Z * (z - 2))
        return [RuleResult(RULE, "valor_atipico", weight=weight)]
    return []
