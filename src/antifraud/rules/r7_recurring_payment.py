"""R7 — Pagamento periódico: um valor alto para quem a conta paga sempre não é suspeito."""

from datetime import timedelta
from typing import List

from antifraud import config
from antifraud.context import AntifraudContext
from antifraud.result import RuleResult
from antifraud.stats import median_of

RULE = "R7"


def _is_regular(intervals_days: List[float]) -> bool:
    for period in config.RECURRING_PERIODS_DAYS:
        if all(abs(interval - period) <= config.RECURRING_PERIOD_TOLERANCE_DAYS for interval in intervals_days):
            return True
    return False


def evaluate(ctx: AntifraudContext, previous: List[RuleResult]) -> List[RuleResult]:
    # Só faz sentido descontar quando R6 achou o valor atípico.
    if not any(hit.rule == "R6" for hit in previous):
        return []

    payments = ctx.approved_to_destination  # mais antigo primeiro
    if len(payments) < config.RECURRING_MIN_PAYMENTS:
        return []

    first_date = payments[0][1]
    if ctx.as_of - first_date < timedelta(days=config.RECURRING_MIN_AGE_DAYS):
        return []

    intervals = [
        (payments[i][1] - payments[i - 1][1]).total_seconds() / 86400 for i in range(1, len(payments))
    ]
    if not _is_regular(intervals):
        return []

    typical = median_of(amount for amount, _ in payments)
    if abs(ctx.data.amount - typical) > config.RECURRING_AMOUNT_TOLERANCE * typical:
        return []

    return [RuleResult(RULE, "pagamento_recorrente", discount=config.RECURRING_DISCOUNT)]
