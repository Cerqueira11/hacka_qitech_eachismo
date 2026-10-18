"""R8, N1, N2 — Velocity e rede: rajadas, fan-in, device/IP compartilhado e tomada de conta."""

from typing import List

from antifraud import config
from antifraud.context import AntifraudContext
from antifraud.result import Action, RuleResult

RULE = "R8"


def evaluate(ctx: AntifraudContext, previous: List[RuleResult]) -> List[RuleResult]:
    hits = []

    # +1: a tentativa atual também conta.
    if (
        ctx.source_attempts_short + 1 >= config.VELOCITY_SHORT_MAX
        or ctx.source_attempts_long + 1 >= config.VELOCITY_LONG_MAX
    ):
        hits.append(RuleResult(RULE, "velocity_origem", action=Action.TWO_FACTOR, weight=config.VELOCITY_WEIGHT))

    if (
        len(ctx.destination_sources_window) >= config.FAN_IN_MIN_SOURCES
        and ctx.destination_age_days < config.NEW_ACCOUNT_DAYS
    ):
        hits.append(RuleResult(RULE, "fan_in_destino", weight=config.FAN_IN_WEIGHT))

    if len(ctx.device_sources_window) >= config.DEVICE_SHARED_MIN_ACCOUNTS:
        hits.append(RuleResult(RULE, "device_compartilhado", weight=config.DEVICE_SHARED_WEIGHT))

    # N1 — IP compartilhado: mesmo IP em >= 3 contas de origem em 24h
    if len(ctx.ip_sources_window) >= config.IP_SHARED_MIN_ACCOUNTS:
        hits.append(RuleResult("N1", "ip_compartilhado", weight=config.IP_SHARED_WEIGHT))

    # N2 — Combo de tomada de conta (Account Takeover):
    # Device não cadastrado + IP nunca visto na origem (com histórico prévio) + destino desconhecido
    if (
        not ctx.device_registered
        and getattr(ctx, "is_new_ip_for_source", False)
        and not ctx.has_previous_edge_to_destination
    ):
        hits.append(
            RuleResult(
                "N2",
                "combo_tomada_conta",
                action=Action.TWO_FACTOR,
                weight=config.TAKEOVER_COMBO_WEIGHT,
            )
        )

    return hits
