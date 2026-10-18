"""R4 — Fraude na pessoa via DICT: titular e documentos vinculados (CPF <-> CNPJ)."""

from typing import List, Tuple

from antifraud import config
from antifraud.context import AntifraudContext
from antifraud.result import Action, RuleResult
from connectors.dict_client import DictPersonRisk

RULE = "R4"


def _linked_marked(linked: List[Tuple[str, DictPersonRisk]]) -> bool:
    return any(person.has_strong_marker for _, person in linked)


def _source(ctx: AntifraudContext) -> List[RuleResult]:
    person = ctx.source_person
    hits = []
    if person.has_strong_marker:
        hits.append(RuleResult(RULE, "origem_marcada", action=Action.REJECT, floor=config.MARKED_FLOOR))
    elif "SCAM" in person.open_infractions:
        hits.append(RuleResult(RULE, "origem_em_analise", action=Action.REJECT))
    elif config.TAKEOVER_SITUATIONS & set(person.open_infractions):
        hits.append(
            RuleResult(RULE, "origem_conta_roubada", action=Action.TWO_FACTOR, weight=config.SOURCE_TAKEOVER_WEIGHT)
        )
    elif person.has_weak_marker or person.open_infractions:
        hits.append(RuleResult(RULE, "origem_sinal_fraco", weight=config.WEAK_SIGNAL_WEIGHT))

    if _linked_marked(ctx.source_linked):
        hits.append(
            RuleResult(RULE, "vinculado_marcado", action=Action.TWO_FACTOR, weight=config.LINKED_MARKED_WEIGHT)
        )
    return hits


def _destination(ctx: AntifraudContext) -> List[RuleResult]:
    person = ctx.destination_person
    hits = []
    if person.has_strong_marker:
        hits.append(RuleResult(RULE, "destino_marcado", action=Action.REJECT, floor=config.MARKED_FLOOR))
    elif person.open_infractions:
        # Destino em análise nunca bloqueia por si só: limite menor + 2FA.
        weight = (
            config.DESTINATION_UNDER_ANALYSIS_LOW_WEIGHT
            if ctx.data.amount <= config.DESTINATION_UNDER_ANALYSIS_LIMIT
            else config.DESTINATION_UNDER_ANALYSIS_HIGH_WEIGHT
        )
        hits.append(RuleResult(RULE, "destino_em_analise", action=Action.TWO_FACTOR, weight=weight))
    elif person.has_weak_marker:
        hits.append(RuleResult(RULE, "destino_sinal_fraco", weight=config.WEAK_SIGNAL_WEIGHT))

    if _linked_marked(ctx.destination_linked):
        hits.append(
            RuleResult(RULE, "vinculado_marcado", action=Action.TWO_FACTOR, weight=config.LINKED_MARKED_WEIGHT)
        )
    return hits


def evaluate(ctx: AntifraudContext, previous: List[RuleResult]) -> List[RuleResult]:
    if not ctx.dict_available:
        # Nunca aprovar às cegas, nunca rejeitar por falha nossa.
        return [
            RuleResult(RULE, "dict_indisponivel", action=Action.TWO_FACTOR, weight=config.DICT_UNAVAILABLE_WEIGHT)
        ]
    return _source(ctx) + _destination(ctx)
