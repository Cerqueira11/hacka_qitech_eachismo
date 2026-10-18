"""R8 — Velocity: muitos Pix em pouco tempo, fan-in no destino, device compartilhado."""

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

    return hits
