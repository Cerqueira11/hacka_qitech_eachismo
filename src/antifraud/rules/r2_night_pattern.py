"""R2 — Transferência noturna fora do padrão. Só peso: nunca bloqueia, vale para PF e PJ.

O limite noturno regulatório (R$ 1.000) está fora do escopo deste serviço.
"""

from typing import List

from antifraud import config
from antifraud.context import AntifraudContext, is_night
from antifraud.result import RuleResult
from antifraud.stats import log_zscore, median_of

RULE = "R2"
REASON = "noturna_atipica"


def evaluate(ctx: AntifraudContext, previous: List[RuleResult]) -> List[RuleResult]:
    if not ctx.is_night:
        return []

    amount = ctx.data.amount
    night_amounts = [value for value, date in ctx.source_history if is_night(date.astimezone(config.BRASILIA))]

    if len(night_amounts) >= config.NIGHT_MIN_HISTORY:
        z = log_zscore(amount, night_amounts, config.LOG_STD_FLOOR)
        if z is not None and z > config.NIGHT_Z_THRESHOLD:
            # Quanto mais acima do padrão noturno, maior o peso.
            weight = min(config.NIGHT_MAX_WEIGHT, config.NIGHT_WEIGHT_PER_Z * z)
            return [RuleResult(RULE, REASON, weight=weight)]
        return []

    # Pouco histórico noturno: compara com o padrão geral da conta.
    all_amounts = [value for value, _ in ctx.source_history]
    if len(all_amounts) >= config.NIGHT_FALLBACK_MIN_HISTORY:
        if amount > config.NIGHT_FALLBACK_MEDIAN_MULTIPLIER * median_of(all_amounts):
            return [RuleResult(RULE, REASON, weight=config.NIGHT_FALLBACK_WEIGHT)]

    return []
