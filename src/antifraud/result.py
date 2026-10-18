from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Tuple


class Action(IntEnum):
    """Ação fixa de uma regra. A ordem é a precedência: a maior vence."""

    NONE = 0
    TWO_FACTOR = 1
    REJECT = 2


@dataclass(frozen=True)
class RuleResult:
    rule: str
    reason: str
    action: Action = Action.NONE
    weight: float = 0.0              # entra no noisy-OR do rules_score
    discount: float = 0.0            # só R7: reduz o rules_score
    floor: Optional[float] = None    # piso do risk_score final (R3, R4 marcado)

    def to_dict(self) -> dict:
        item = {
            "rule": self.rule,
            "action": self.action.name,
            "weight": round(self.weight, 4),
            "reason": self.reason,
        }
        if self.discount:
            item["discount"] = round(self.discount, 4)
        if self.floor is not None:
            item["floor"] = self.floor
        return item


@dataclass(frozen=True)
class GraphInfluence:
    score: float
    evidence: List[dict] = field(default_factory=list)


STATUS_BY_ACTION = {
    Action.NONE: "approved",
    Action.TWO_FACTOR: "two_factor_required",
    Action.REJECT: "rejected",
}


@dataclass(frozen=True)
class Verdict:
    status: str
    risk_score: float
    rules_score: float
    graph_source_score: float
    graph_destination_score: float
    hits: Tuple[RuleResult, ...]
    graph_evidence: List[dict]
