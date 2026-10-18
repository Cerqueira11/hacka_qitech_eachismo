"""R2 — Desvio do padrão noturno (C3). Só peso: nunca rejeita.

O limite noturno é decisão do cliente no BaaS e é aplicado por quem executa o
Pix. Aqui a R2 só compara a noite corrente com o histórico noturno do próprio
cliente. Mede desvio de valor, como a R6: no score vale o maior peso entre as duas.
"""

from typing import List

from antifraud import config
from antifraud.context import AntifraudContext
from antifraud.result import RuleResult

RULE = "R2"
REASON = "desvio_noturno"


def evaluate(ctx: AntifraudContext, previous: List[RuleResult]) -> List[RuleResult]:
    if not ctx.is_night:
        return []

    # Pouco histórico noturno: o valor isolado fica com a R6.
    if ctx.nights_with_pix < config.NIGHT_MIN_NIGHTS or ctx.night_average <= 0:
        return []

    total = ctx.night_amount + ctx.data.amount
    if total > config.NIGHT_HIGH_MULTIPLIER * ctx.night_average:
        weight = config.NIGHT_HIGH_WEIGHT
    elif total > config.NIGHT_MODERATE_MULTIPLIER * ctx.night_average:
        weight = config.NIGHT_MODERATE_WEIGHT
    else:
        return []

    return [RuleResult(RULE, REASON, weight=weight, family=config.AMOUNT_DEVIATION_FAMILY)]
