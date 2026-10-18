"""R3 — Vínculo conta x documento. Não confere: reject."""

from typing import List

from antifraud import config
from antifraud.context import AntifraudContext
from antifraud.result import Action, RuleResult

RULE = "R3"


def _reject(reason: str) -> RuleResult:
    return RuleResult(RULE, reason, action=Action.REJECT, floor=config.OWNER_MISMATCH_FLOOR)


def evaluate(ctx: AntifraudContext, previous: List[RuleResult]) -> List[RuleResult]:
    # O DICT é a fonte oficial: ele fala primeiro. Sem resposta dele, a parte
    # DICT fica de fora e R4 pede o 2FA.
    if ctx.dict_available:
        if ctx.destination_entry is None:
            return [_reject("conta_nao_encontrada")]
        if ctx.destination_entry.owner_document_number != ctx.data.destination_account.document_number:
            return [_reject("vinculo_nao_confere")]

    # A conta já estava no grafo com outro titular.
    if ctx.source_owner_conflict or ctx.destination_owner_conflict:
        return [_reject("vinculo_nao_confere")]

    return []
