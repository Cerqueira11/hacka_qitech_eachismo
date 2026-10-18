"""R9 — Conta de passagem (pass-through / mula).

Padrão da conta laranja/mula: recebe de MUITAS origens distintas (fan-in alto),
repassa para POUCOS destinos (fan-out baixo) e NÃO retém o dinheiro (o que sai é
quase tudo o que entrou). Olha o comportamento ACUMULADO da conta na janela
(90 dias), não uma rajada curta.

Avalia os dois lados do Pix: a conta mula pode ser a origem (está repassando
agora) ou o destino (está recebendo para repassar). Os três sinais são exigidos
juntos nos dois lados (conservador). O pass_through_ratio é o que separa a mula
do varejista legítimo, que recebe de muitos mas acumula/saca em vez de repassar.

Ação: 2FA + peso (não REJECT): o padrão é forte, mas intermediadores legítimos
existem; o 2FA barra o golpe sem bloquear de cara.
"""

from typing import List

from antifraud import config
from antifraud.context import AntifraudContext
from antifraud.result import Action, RuleResult

RULE = "R9"


def _is_pass_through(fan_in: int, fan_out: int, ratio: float) -> bool:
    return (
        fan_in >= config.R9_FANIN_MIN
        and fan_out <= config.R9_FANOUT_MAX
        and ratio >= config.R9_PASSTHROUGH_RATIO
    )


def evaluate(ctx: AntifraudContext, previous: List[RuleResult]) -> List[RuleResult]:
    hits = []

    if _is_pass_through(ctx.source_fan_in, ctx.source_fan_out, ctx.source_pass_through_ratio):
        hits.append(
            RuleResult(RULE, "origem_conta_passagem", action=Action.TWO_FACTOR, weight=config.R9_WEIGHT)
        )

    if _is_pass_through(ctx.destination_fan_in, ctx.destination_fan_out, ctx.destination_pass_through_ratio):
        hits.append(
            RuleResult(RULE, "destino_conta_passagem", action=Action.TWO_FACTOR, weight=config.R9_WEIGHT)
        )

    return hits
