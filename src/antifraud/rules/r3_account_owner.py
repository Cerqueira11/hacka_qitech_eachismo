"""R3 — Vínculo conta x documento (C2). Não consulta o DICT.

O payload não diz se o Pix foi por chave ou manual, e o DICT não busca por
conta. A R3 compara o payload com o account_node, e só um nó VERIFICADO (que
já foi origem, ou seja, conta nossa) tem documento para divergir. Por isso a
primeira transação de uma conta nunca cai aqui.
"""

from typing import List

from antifraud import config
from antifraud.context import AntifraudContext
from antifraud.result import Action, RuleResult

RULE = "R3"
REASON = "vinculo_nao_confere"


def evaluate(ctx: AntifraudContext, previous: List[RuleResult]) -> List[RuleResult]:
    hits = []
    if ctx.source_owner_conflict:
        # Conta nossa com outro titular no payload: indício forte.
        hits.append(RuleResult(RULE, REASON, action=Action.REJECT, floor=config.OWNER_MISMATCH_FLOOR))
    if ctx.destination_owner_conflict:
        # Conta conhecida com outro documento: pode ser erro de digitação de quem paga.
        hits.append(RuleResult(RULE, REASON, action=Action.REJECT))
    return hits
