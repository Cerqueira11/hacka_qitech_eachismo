"""R1 — Dispositivo não cadastrado: R$ 200 por Pix e R$ 1.000 por dia.

Cadastrado = está em registered_device (cache interno) ou a API externa de
dispositivo confirmou agora (e o motor gravou na tabela). Ver ContextBuilder._load_device.
"""

from typing import List

from antifraud import config
from antifraud.context import AntifraudContext
from antifraud.result import Action, RuleResult

RULE = "R1"


def evaluate(ctx: AntifraudContext, previous: List[RuleResult]) -> List[RuleResult]:
    if not ctx.device_api_available:
        # Nunca aprovar às cegas, nunca rejeitar por falha nossa.
        return [
            RuleResult(
                RULE, "device_api_indisponivel", action=Action.TWO_FACTOR, weight=config.DEVICE_API_UNAVAILABLE_WEIGHT
            )
        ]

    if ctx.device_registered:
        return []

    amount = ctx.data.amount
    over_tx_limit = amount > config.UNREGISTERED_DEVICE_TX_LIMIT
    over_daily_limit = ctx.unregistered_device_amount_today + amount > config.UNREGISTERED_DEVICE_DAILY_LIMIT
    if over_tx_limit or over_daily_limit:
        # Sem peso nem piso: é limite, não indício de fraude.
        return [RuleResult(RULE, "limite_dispositivo_novo", action=Action.REJECT)]

    return [RuleResult(RULE, "dispositivo_nao_cadastrado", weight=config.UNREGISTERED_DEVICE_WEIGHT)]
