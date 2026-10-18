"""As regras, na ordem em que rodam. Cada uma recebe o contexto e os acertos
das anteriores (R7 depende de R6) e devolve uma lista de RuleResult."""

from antifraud.rules import (
    extra_signals,
    r1_unregistered_device,
    r2_night_pattern,
    r3_account_owner,
    r4_person_fraud,
    r5_location,
    r6_amount_outlier,
    r7_recurring_payment,
    r8_velocity,
    r9_pass_through,
)

RULES = (
    r1_unregistered_device.evaluate,
    r2_night_pattern.evaluate,
    r3_account_owner.evaluate,
    r4_person_fraud.evaluate,
    r5_location.evaluate,
    r6_amount_outlier.evaluate,
    r7_recurring_payment.evaluate,
    r8_velocity.evaluate,
    r9_pass_through.evaluate,
    extra_signals.evaluate,
)

__all__ = ["RULES"]
