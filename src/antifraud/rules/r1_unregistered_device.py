"""R1 — Dispositivo não cadastrado (limite regulatório: R$ 200 por Pix, R$ 1.000 por dia)."""

from typing import List

from antifraud import config
from antifraud.context import AntifraudContext
from antifraud.result import Action, RuleResult

RULE = "R1"


def evaluate(ctx: AntifraudContext, previous: List[RuleResult]) -> List[RuleResult]:
    if ctx.device_registered:
        return []

    amount = ctx.data.amount
    over_tx_limit = amount > config.UNREGISTERED_DEVICE_TX_LIMIT
    over_daily_limit = ctx.unregistered_device_amount_today + amount > config.UNREGISTERED_DEVICE_DAILY_LIMIT
    if over_tx_limit or over_daily_limit:
        # Sem peso nem piso: é limite regulatório, não indício de fraude.
        return [RuleResult(RULE, "limite_dispositivo_novo", action=Action.REJECT)]

    return [RuleResult(RULE, "dispositivo_nao_cadastrado", weight=config.UNREGISTERED_DEVICE_WEIGHT)]
